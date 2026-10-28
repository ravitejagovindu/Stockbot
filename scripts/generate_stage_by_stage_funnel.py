"""
scripts/generate_stage_by_stage_funnel.py — Outcome-Free Multi-Config Stage-by-Stage Attrition Funnel.

Simulates all 7 pre-registered configurations across 2020-2026 in a single day-by-day pass.
Tracks candidate attrition stage-by-stage:
  1. Screened Universe (Gates 1-3: Mcap > 5000cr, ADTV > 25cr, Age > 252d)
  2. Strategy Trigger & RS Cut (Breakout / Trend / Pullback + RS Percentile)
  3. Macro Regime / Kill Switch (Nifty < SMA200, VIX > 20, Bull Correction)
  4. Risk:Reward Gate (1.5 <= projected_rr <= 5.0)
  5. Capacity & Heat Constraints (Max 10/12 positions, sector cap, heat limit)
  6. Next-Day Open Execution (Gap limit <= 1.5%/3.0% and RR at fill >= 1.5)
  7. Final Executed Fills (Cash allocation)

Outputs results to backtest/outputs/stage_by_stage_funnel.csv.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import logging

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from sqlalchemy import select

from config import load_config
from data.db.connection import get_session
from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.costs import CostModel
from engine_core.entry_filters import apply_entry_filters
from engine_core.indicators import atr
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
    plan_entry_fill,
)
from engine_core.regime_filter import RegimeFilter
from engine_core.regime_gates import bull_correction_active, is_bull, nifty_sma
from engine_core.risk_sizing import RiskAndSizingEngine
from engine_core.universe_screener import UniverseScreener

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("stage_funnel")

OUTPUT_DIR = ROOT / "backtest" / "outputs"


def _to_date(d) -> date:
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


def _bar(session, cfg: dict, rules: LifecycleRules, sym: str, dt: date):
    """Retrieve bar, rolling ATR, parabolic reference, and corporate action flag matching Simulator."""
    c = build_candidate_dicts(session, cfg, [sym], dt)
    if not c:
        return None
    adj = c[0]["adjusted_ohlcv"]
    if dt not in adj.index:
        return None
    a = atr(
        adj["high_adj"],
        adj["low_adj"],
        adj["close_adj"],
        period=int(cfg["risk"]["atr_period"]),
    )
    r = adj.loc[dt]
    if isinstance(r, pd.DataFrame):
        r = r.iloc[-1]
    atr_val = (
        float(a.loc[dt])
        if (dt in a.index and pd.notna(a.loc[dt]))
        else (float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else 0.0)
    )
    return (
        Bar(float(r.open_adj), float(r.high_adj), float(r.low_adj), float(r.close_adj)),
        atr_val,
        parabolic_ref_close(list(adj["close_adj"]), rules.parabolic_lookback),
        any(_to_date(x.get("ex_date")) == dt for x in c[0]["corporate_actions"]),
    )


def main():
    base_cfg = load_config()

    configs_to_run = [
        ("CFG-00", "Baseline Breakout (Gap 3.0%)", {
            "entry_filters": {"breakout_required": True, "pullback_required": False, "rs_rank_percentile": None},
            "execution": {"max_entry_gap_up_pct": 3.0}
        }),
        ("CFG-01", "Trend Continuation (RS Top 50%, Gap 1.5%)", {
            "entry_filters": {"breakout_required": False, "pullback_required": False, "rs_rank_percentile": 50},
            "execution": {"max_entry_gap_up_pct": 1.5}
        }),
        ("CFG-02", "Trend Continuation (RS Top 40%, Gap 1.5%)", {
            "entry_filters": {"breakout_required": False, "pullback_required": False, "rs_rank_percentile": 40},
            "execution": {"max_entry_gap_up_pct": 1.5}
        }),
        ("CFG-03", "Trend Continuation (RS Top 30%, Gap 1.5%)", {
            "entry_filters": {"breakout_required": False, "pullback_required": False, "rs_rank_percentile": 30},
            "execution": {"max_entry_gap_up_pct": 1.5}
        }),
        ("CFG-04", "Pullback to SMA20 (RS Top 50%, Gap 1.5%)", {
            "entry_filters": {"breakout_required": False, "pullback_required": True, "rs_rank_percentile": 50, "pullback_sma_period": 20, "pullback_tolerance_lower": 0.98, "pullback_tolerance_upper": 1.03},
            "execution": {"max_entry_gap_up_pct": 1.5}
        }),
        ("CFG-05", "Pullback to SMA20 (RS Top 40%, Gap 1.5%)", {
            "entry_filters": {"breakout_required": False, "pullback_required": True, "rs_rank_percentile": 40, "pullback_sma_period": 20, "pullback_tolerance_lower": 0.98, "pullback_tolerance_upper": 1.03},
            "execution": {"max_entry_gap_up_pct": 1.5}
        }),
        ("CFG-06", "Pullback to SMA20 (RS Top 30%, Gap 1.5%)", {
            "entry_filters": {"breakout_required": False, "pullback_required": True, "rs_rank_percentile": 30, "pullback_sma_period": 20, "pullback_tolerance_lower": 0.98, "pullback_tolerance_upper": 1.03},
            "execution": {"max_entry_gap_up_pct": 1.5}
        }),
    ]

    with get_session() as session:
        # Load all trading days
        days_raw = (
            session.execute(
                select(MarketDataLake.trade_date)
                .distinct()
                .where(MarketDataLake.trade_date >= date(2020, 1, 1), MarketDataLake.trade_date <= date(2026, 10, 16))
                .order_by(MarketDataLake.trade_date)
            )
            .scalars()
            .all()
        )
        days = [_to_date(d) for d in days_raw]
        logger.info(f"Loaded {len(days)} trading sessions from 2020-01-01 to 2026-10-16.")

        # Initialize state for each config
        cfg_states = {}
        for cid, desc, overrides in configs_to_run:
            cfg = deepcopy(base_cfg)
            for section, kvs in overrides.items():
                if section not in cfg:
                    cfg[section] = {}
                for k, v in kvs.items():
                    cfg[section][k] = v
            cfg_states[cid] = {
                "cid": cid,
                "desc": desc,
                "cfg": cfg,
                "rules": LifecycleRules.from_config(cfg),
                "costs": CostModel.from_config(cfg),
                "sizer": RiskAndSizingEngine(cfg),
                "cash": 1_000_000.0,
                "open_pos": {},
                "pending": [],
                "counts": {
                    "W1": {"screened": 0, "signals": 0, "regime_ok": 0, "rr_ok": 0, "capacity_ok": 0, "gap_ok": 0, "dropped_cash": 0, "fills": 0},
                    "W2": {"screened": 0, "signals": 0, "regime_ok": 0, "rr_ok": 0, "capacity_ok": 0, "gap_ok": 0, "dropped_cash": 0, "fills": 0},
                },
                "fills_list": [],
            }

        screener = UniverseScreener(base_cfg, session)
        regime = RegimeFilter(base_cfg, session)
        sma_n = int(base_cfg.get("macro", {}).get("bull_entry_sma_period", 0))

        def _heat_view(pos_dict: dict) -> list:
            out = []
            for sym, p in pos_dict.items():
                st = p["st"]
                out.append({
                    "symbol": sym,
                    "sector": p["sector"],
                    "risk_amount": max(0.0, st.shares_remaining * (st.entry_price - st.live_stop)),
                    "position_value": st.shares_remaining * st.entry_price,
                })
            return out

        windows = [
            ("W1", date(2020, 1, 1), date(2021, 12, 31)),
            ("W2", date(2022, 1, 1), date(2026, 10, 16)),
        ]

        # Execute each window independently (clean initial portfolio & 10L cash, matching Simulator)
        for win, win_start, win_end in windows:
            logger.info(f"\n--- Simulating Attrition Funnel for {win} ({win_start} to {win_end}) ---")
            win_days = [d for d in days if win_start <= d <= win_end]

            # Reset state for each config at the start of each window
            for cid, st in cfg_states.items():
                st["cash"] = 1_000_000.0
                st["open_pos"] = {}
                st["pending"] = []

            for day_idx, d in enumerate(win_days):
                if (day_idx + 1) % 100 == 0 or day_idx == len(win_days) - 1:
                    logger.info(f"[{win}] Processing session {day_idx + 1}/{len(win_days)}: {d}...")

                rs = regime.evaluate(d)
                ks = bool(rs.kill_switch_active)
                bull = is_bull(ks, rs.nifty_close, rs.nifty_sma200)
                nsma = nifty_sma(session, base_cfg, d, sma_n) if sma_n else None
                is_correction = bool(sma_n and bull_correction_active(rs.nifty_close, rs.nifty_sma200, nsma))
                macro_blocked = ks or is_correction

                # -------------------------------------------------------------
                # Step 1: Fill yesterday's pending tickets at today's open
                # -------------------------------------------------------------
                for cid, st in cfg_states.items():
                    ex = st["cfg"]["execution"]
                    risk_pct = float(st["cfg"]["risk"]["max_loss_pct_per_trade"])
                    eq_now = st["cash"] + sum(p["st"].shares_remaining * p["last_close"] for p in st["open_pos"].values())

                    for t in st["pending"]:
                        info = _bar(session, st["cfg"], st["rules"], t.symbol, d)
                        if info is None or t.symbol in st["open_pos"]:
                            continue
                        bar, _, _, has_ca = info
                        if has_ca:
                            continue

                        plan = plan_entry_fill(
                            ticket_entry=t.entry_price,
                            stop=t.live_stop_loss,
                            target=t.initial_resistance_target,
                            next_open=bar.open,
                            equity=eq_now,
                            risk_pct=risk_pct,
                            slippage_pct=float(ex["entry_slippage_pct"]),
                            max_gap_up_pct=float(ex["max_entry_gap_up_pct"]),
                            min_rr=float(ex["min_rr_at_fill"]),
                            cash=st["cash"],
                        )
                        if not plan.ok:
                            continue

                        # Order passed opening gap and R:R at fill
                        st["counts"][win]["gap_ok"] += 1

                        buy_cost = st["costs"].buy_cost(plan.fill_price * plan.shares)
                        if plan.shares > 0 and st["cash"] >= plan.fill_price * plan.shares + buy_cost:
                            st["cash"] -= plan.fill_price * plan.shares + buy_cost
                            st["open_pos"][t.symbol] = {
                                "sector": t.sector,
                                "entry_date": d,
                                "orig": plan.shares,
                                "last_close": plan.fill_price,
                                "st": PosState(
                                    entry_price=plan.fill_price,
                                    initial_stop=t.live_stop_loss,
                                    live_stop=t.live_stop_loss,
                                    target=t.initial_resistance_target,
                                    highest_high=plan.fill_price,
                                    shares_remaining=plan.shares,
                                ),
                            }
                            st["counts"][win]["fills"] += 1
                            st["fills_list"].append({"symbol": t.symbol, "entry_date": d, "window": win})
                        else:
                            st["counts"][win]["dropped_cash"] += 1

                    st["pending"] = []

                # -------------------------------------------------------------
                # Step 2: Advance open positions with today's bar
                # -------------------------------------------------------------
                for cid, st in cfg_states.items():
                    ex = st["cfg"]["execution"]
                    for sym, p in list(st["open_pos"].items()):
                        info = _bar(session, st["cfg"], st["rules"], sym, d)
                        if info is None:
                            continue
                        bar, atr_v, ref, _ = info
                        res = advance_one_bar(p["st"], bar, BarCtx(atr_v, ks, bull, ref), st["rules"], float(ex["exit_slippage_pct"]))
                        p["st"], p["last_close"] = res.pos, bar.close

                        for e in res.exits:
                            sell = st["costs"].sell_cost(e.price * e.shares)
                            st["cash"] += e.price * e.shares - sell

                        if res.closed:
                            del st["open_pos"][sym]

                # -------------------------------------------------------------
                # Step 3: Screen today's universe once
                # -------------------------------------------------------------
                all_syms = screener._get_all_symbols(d)
                passed_screener = [
                    sym for sym in all_syms
                    if sym not in ("NIFTY50_INDEX", "INDIA_VIX")
                    and screener.screen_single(sym, d, apply_event_gates=False).passed
                ]

                if not passed_screener:
                    continue

                cands_raw = build_candidate_dicts(session, base_cfg, passed_screener, d)
                if not cands_raw:
                    continue

                # -------------------------------------------------------------
                # Step 4: Evaluate funnel for each config
                # -------------------------------------------------------------
                for cid, st in cfg_states.items():
                    st["counts"][win]["screened"] += len(passed_screener)

                    # Exclude symbols already held in open positions (matching Simulator)
                    avail_cands = [c for c in cands_raw if c["symbol"] not in st["open_pos"]]
                    filtered = apply_entry_filters(avail_cands, st["cfg"])
                    st["counts"][win]["signals"] += len(filtered)

                    if macro_blocked:
                        continue

                    st["counts"][win]["regime_ok"] += len(filtered)

                    # Evaluate risk sizing & R:R gate
                    eq = st["cash"] + sum(p["st"].shares_remaining * p["last_close"] for p in st["open_pos"].values())
                    setups = st["sizer"].compute_all(
                        candidates=filtered,
                        eval_date=d,
                        account_equity=eq,
                        current_positions=_heat_view(st["open_pos"]),
                        session=session,
                        is_bull_regime=bull,
                    )

                    for setup in setups:
                        if setup.block_reason and ("RR_TOO_LOW" in setup.block_reason or "RR_ABOVE_CAP" in setup.block_reason):
                            continue
                        st["counts"][win]["rr_ok"] += 1

                        if not setup.blocked:
                            st["counts"][win]["capacity_ok"] += 1
                            st["pending"].append(setup)

    # -------------------------------------------------------------
    # Collate and Output Funnel Results
    # -------------------------------------------------------------
    rows = []
    for cid, desc, _ in configs_to_run:
        st = cfg_states[cid]
        c = st["counts"]
        for win in ["W1", "W2", "Pooled"]:
            if win == "Pooled":
                s1 = c["W1"]["screened"] + c["W2"]["screened"]
                s2 = c["W1"]["signals"] + c["W2"]["signals"]
                s3 = c["W1"]["regime_ok"] + c["W2"]["regime_ok"]
                s4 = c["W1"]["rr_ok"] + c["W2"]["rr_ok"]
                s5 = c["W1"]["capacity_ok"] + c["W2"]["capacity_ok"]
                s6 = c["W1"]["gap_ok"] + c["W2"]["gap_ok"]
                d_cash = c["W1"]["dropped_cash"] + c["W2"]["dropped_cash"]
                s7 = c["W1"]["fills"] + c["W2"]["fills"]
            else:
                s1 = c[win]["screened"]
                s2 = c[win]["signals"]
                s3 = c[win]["regime_ok"]
                s4 = c[win]["rr_ok"]
                s5 = c[win]["capacity_ok"]
                s6 = c[win]["gap_ok"]
                d_cash = c[win]["dropped_cash"]
                s7 = c[win]["fills"]

            conv = (s7 / s2 * 100.0) if s2 > 0 else 0.0

            rows.append({
                "config_id": cid,
                "description": desc,
                "window": win,
                "stage1_screened_universe": s1,
                "stage2_strategy_signals": s2,
                "stage3_regime_survivors": s3,
                "dropped_regime": s2 - s3,
                "stage4_rr_approved": s4,
                "dropped_rr": s3 - s4,
                "stage5_capacity_approved": s5,
                "dropped_capacity": s4 - s5,
                "stage6_gap_and_fill_approved": s6,
                "dropped_gap_and_rr_fill": s5 - s6,
                "dropped_insufficient_cash": d_cash,
                "stage7_executed_fills": s7,
                "conversion_rate_pct": round(conv, 2),
            })

    df_funnel = pd.DataFrame(rows)
    out_csv = OUTPUT_DIR / "stage_by_stage_funnel.csv"
    df_funnel.to_csv(out_csv, index=False)
    logger.info(f"Successfully saved stage-by-stage funnel to {out_csv}.")

    print("\n" + "="*110)
    print("  STAGE-BY-STAGE CANDIDATE ATTRITION FUNNEL (2020-2026)")
    print("="*110)
    summary_cols = [
        "config_id", "window", "stage2_strategy_signals", "dropped_regime", "dropped_rr",
        "dropped_capacity", "dropped_gap_and_rr_fill", "dropped_insufficient_cash", "stage7_executed_fills", "conversion_rate_pct"
    ]
    print(df_funnel[summary_cols].to_string(index=False))


if __name__ == "__main__":
    main()

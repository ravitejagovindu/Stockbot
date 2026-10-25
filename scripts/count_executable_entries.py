"""
scripts/count_executable_entries.py — Outcome-Free Executable Entry Funnel.
Simulates candidate generation, sizing, and position fills through the execution state machine
(accounting for position slots, cash, gap limits, and RR at fill) with NO forward returns or P&L.
Counts the exact executable trades per config per window.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys

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
from engine_core.entry_filters import apply_entry_filters, passes_breakout, passes_trend_filter, rs_return
from engine_core.indicators import atr, donchian_low, donchian_high
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
logger = logging.getLogger("executable_funnel")

OUTPUT_DIR = ROOT / "backtest" / "outputs"


def _to_date(d) -> date:
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


def count_executable_entries_for_config(base_cfg: dict, config_id: str, cfg_overrides: dict, session) -> dict:
    """Run outcome-free execution loop counting actual position fills."""
    cfg = deepcopy(base_cfg)
    # Apply overrides
    for section, kvs in cfg_overrides.items():
        if section not in cfg:
            cfg[section] = {}
        for k, v in kvs.items():
            cfg[section][k] = v

    rules = LifecycleRules.from_config(cfg)
    regime = RegimeFilter(cfg, session)
    screener = UniverseScreener(cfg, session)
    sizer = RiskAndSizingEngine(cfg)
    ex = cfg["execution"]
    risk_pct = float(cfg["risk"]["max_loss_pct_per_trade"])
    sma_n = int(cfg.get("macro", {}).get("bull_entry_sma_period", 0))

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

    cash = 1_000_000.0
    open_pos = {}
    pending = []
    executed_trades = []

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

    for d in days:
        rs = regime.evaluate(d)
        ks = bool(rs.kill_switch_active)
        bull = is_bull(ks, rs.nifty_close, rs.nifty_sma200)

        # 1. Fill yesterday's tickets at today's open
        eq_now = cash + sum(p["st"].shares_remaining * p["last_close"] for p in open_pos.values())
        for t in pending:
            # Fetch today's bar
            c = build_candidate_dicts(session, cfg, [t.symbol], d)
            if not c or t.symbol in open_pos:
                continue
            adj = c[0]["adjusted_ohlcv"]
            if d not in adj.index:
                continue
            row = adj.loc[d]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            open_p = float(row.open_adj)

            plan = plan_entry_fill(
                ticket_entry=t.entry_price,
                stop=t.live_stop_loss,
                target=t.initial_resistance_target,
                next_open=open_p,
                equity=eq_now,
                risk_pct=risk_pct,
                slippage_pct=float(ex["entry_slippage_pct"]),
                max_gap_up_pct=float(ex["max_entry_gap_up_pct"]),
                min_rr=float(ex["min_rr_at_fill"]),
                cash=cash,
            )
            if not plan.ok:
                continue

            # Fill executed
            cash -= plan.fill_price * plan.shares
            open_pos[t.symbol] = {
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
            executed_trades.append({
                "symbol": t.symbol,
                "entry_date": d,
                "window": "W1" if d < date(2022, 1, 1) else "W2",
            })

        pending = []

        # 2. Advance open positions with today's bar
        for sym, p in list(open_pos.items()):
            c = build_candidate_dicts(session, cfg, [sym], d)
            if not c:
                continue
            adj = c[0]["adjusted_ohlcv"]
            if d not in adj.index:
                continue
            r = adj.loc[d]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[-1]
            bar = Bar(float(r.open_adj), float(r.high_adj), float(r.low_adj), float(r.close_adj))
            atr_s = atr(adj["high_adj"], adj["low_adj"], adj["close_adj"], period=int(cfg["risk"]["atr_period"]))
            atr_v = float(atr_s.loc[d]) if (d in atr_s.index and pd.notna(atr_s.loc[d])) else 0.0
            ref = parabolic_ref_close(list(adj["close_adj"]), rules.parabolic_lookback)

            res = advance_one_bar(p["st"], bar, BarCtx(atr_v, ks, bull, ref), rules, float(ex["exit_slippage_pct"]))
            p["st"], p["last_close"] = res.pos, bar.close
            if res.closed:
                # Free cash
                exit_p = res.exits[-1].price if res.exits else bar.close
                cash += exit_p * p["orig"]
                del open_pos[sym]

        # 3. Generate tomorrow's tickets
        nsma = nifty_sma(session, cfg, d, sma_n) if sma_n else None
        if ks or (sma_n and bull_correction_active(rs.nifty_close, rs.nifty_sma200, nsma)):
            continue

        all_syms = session.execute(
            select(MarketDataLake.symbol)
            .where(MarketDataLake.trade_date == d)
            .where(MarketDataLake.symbol.notin_(["NIFTY50_INDEX", "INDIA_VIX"]))
        ).scalars().all()

        passed = []
        for sym in all_syms:
            if sym in open_pos:
                continue
            if not screener.screen_single(sym, d, apply_event_gates=False).passed:
                continue
            passed.append(sym)

        if not passed:
            continue

        cands_raw = build_candidate_dicts(session, cfg, passed, d)
        if not cands_raw:
            continue

        filtered_cands = apply_entry_filters(cands_raw, cfg)
        if not filtered_cands:
            continue

        setups = sizer.compute_all(
            candidates=filtered_cands,
            eval_date=d,
            account_equity=cash + sum(p["st"].shares_remaining * p["last_close"] for p in open_pos.values()),
            current_positions=_heat_view(open_pos),
            session=session,
            is_bull_regime=bull,
        )
        pending = [x for x in setups if not x.blocked]

    df_exec = pd.DataFrame(executed_trades)
    w1_count = len(df_exec[df_exec["window"] == "W1"]) if not df_exec.empty else 0
    w2_count = len(df_exec[df_exec["window"] == "W2"]) if not df_exec.empty else 0
    pooled_count = len(df_exec) if not df_exec.empty else 0

    return {
        "config_id": config_id,
        "w1_executed_trades": w1_count,
        "w2_executed_trades": w2_count,
        "pooled_executed_trades": pooled_count,
        "meets_w1_gate": w1_count >= 20,
        "meets_pooled_gate": pooled_count >= 80,
    }


def main():
    cfg = load_config()
    print("=== Outcome-Free Executable Entry Funnel Evaluation ===")
    configs_to_test = [
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

    results = []
    with get_session() as s:
        for cid, desc, overrides in configs_to_test:
            logger.info(f"Simulating executable entries for {cid}: {desc}...")
            res = count_executable_entries_for_config(cfg, cid, overrides, s)
            res["description"] = desc
            results.append(res)

    print("\n" + "="*95)
    print("  OUTCOME-FREE EXECUTABLE ENTRY FUNNEL RESULTS (Actual Trades Filled)")
    print("="*95)
    df_res = pd.DataFrame(results)[[
        "config_id", "description", "w1_executed_trades", "w2_executed_trades", "pooled_executed_trades", "meets_w1_gate", "meets_pooled_gate"
    ]]
    print(df_res.to_string(index=False))


if __name__ == "__main__":
    main()

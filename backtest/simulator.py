"""backtest/simulator.py — one simulator for Pass 1 (exclusions=None) and Pass 2 (exclusions=Exclusions)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import distinct, select

from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.costs import CostModel
from engine_core.entry_filters import apply_entry_filters
from engine_core.indicators import atr
from engine_core.lifecycle_rules import (
    BarCtx,
    Bar,
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


def _to_date(d) -> date:
    if hasattr(d, "date") and callable(getattr(d, "date")):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


@dataclass
class SimResult:
    trades: pd.DataFrame
    equity: pd.Series
    skipped: list = field(default_factory=list)
    compliance_applied: bool = False


class Simulator:
    def __init__(self, config: dict, session):
        self.cfg, self.s = config, session
        self.rules = LifecycleRules.from_config(config)
        self.costs = CostModel.from_config(config)
        self.regime = RegimeFilter(config, session)
        self.screener = UniverseScreener(config, session)
        self.sizer = RiskAndSizingEngine(config)

    # ---- helpers --------------------------------------------------------------
    def _bar(self, sym: str, d: date):
        dt = _to_date(d)
        c = build_candidate_dicts(self.s, self.cfg, [sym], dt)
        if not c:
            return None
        adj = c[0]["adjusted_ohlcv"]
        if dt not in adj.index:
            return None
        a = atr(
            adj["high_adj"],
            adj["low_adj"],
            adj["close_adj"],
            period=int(self.cfg["risk"]["atr_period"]),
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
            parabolic_ref_close(list(adj["close_adj"]), self.rules.parabolic_lookback),
            any(_to_date(x.get("ex_date")) == dt for x in c[0]["corporate_actions"]),
        )

    @staticmethod
    def _heat_view(open_pos: dict) -> list:
        out = []
        for sym, p in open_pos.items():
            st = p["st"]
            out.append(
                {
                    "symbol": sym,
                    "sector": p["sector"],
                    "risk_amount": max(0.0, st.shares_remaining * (st.entry_price - st.live_stop)),
                    "position_value": st.shares_remaining * st.entry_price,
                }
            )
        return out

    # ---- main loop ------------------------------------------------------------
    def run(self, start: date, end: date, initial_equity: float, exclusions=None) -> SimResult:
        cfg, ex = self.cfg, self.cfg["execution"]
        risk_pct = float(cfg["risk"]["max_loss_pct_per_trade"])
        sma_n = int(cfg.get("macro", {}).get("bull_entry_sma_period", 0))
        start_d, end_d = _to_date(start), _to_date(end)
        days_raw = (
            self.s.execute(
                select(MarketDataLake.trade_date)
                .distinct()
                .where(MarketDataLake.trade_date >= start_d, MarketDataLake.trade_date <= end_d)
                .order_by(MarketDataLake.trade_date)
            )
            .scalars()
            .all()
        )
        days = [_to_date(d) for d in days_raw]
        cash, open_pos, pending, trades, curve, skipped, pid = float(initial_equity), {}, [], [], {}, [], 0

        for d in days:
            rs = self.regime.evaluate(d)
            ks = bool(rs.kill_switch_active)
            bull = is_bull(ks, rs.nifty_close, rs.nifty_sma200)

            # 1) fill yesterday's tickets at today's open (rank order)
            eq_now = cash + sum(p["st"].shares_remaining * p["last_close"] for p in open_pos.values())
            for t in pending:
                info = self._bar(t.symbol, d)
                if info is None or t.symbol in open_pos:
                    skipped.append((d, t.symbol, "NO_BAR_OR_ALREADY_HELD"))
                    continue
                bar, _, _, has_ca = info
                if has_ca:
                    skipped.append((d, t.symbol, "CORP_ACTION_ON_EXEC_DATE"))
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
                    cash=cash,
                )
                if not plan.ok:
                    skipped.append((d, t.symbol, plan.reason))
                    continue
                buy_cost = self.costs.buy_cost(plan.fill_price * plan.shares)
                cash -= plan.fill_price * plan.shares + buy_cost
                pid += 1
                open_pos[t.symbol] = {
                    "id": pid,
                    "sector": t.sector,
                    "entry_date": d,
                    "orig": plan.shares,
                    "entry_costs": buy_cost,
                    "gross": 0.0,
                    "costs": buy_cost,
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
            pending = []

            # 2) advance every open position with today's bar (includes positions filled this morning)
            for sym, p in list(open_pos.items()):
                info = self._bar(sym, d)
                if info is None:
                    continue
                bar, atr14, ref, _ = info
                res = advance_one_bar(
                    p["st"],
                    bar,
                    BarCtx(atr14, ks, bull, ref),
                    self.rules,
                    float(ex["exit_slippage_pct"]),
                )
                p["st"], p["last_close"] = res.pos, bar.close
                for e in res.exits:
                    sell = self.costs.sell_cost(e.price * e.shares)
                    cash += e.price * e.shares - sell
                    p["gross"] += (e.price - p["st"].entry_price) * e.shares
                    p["costs"] += sell
                if res.closed:
                    net = p["gross"] - p["costs"]
                    trades.append(
                        {
                            "position_id": p["id"],
                            "symbol": sym,
                            "entry_date": p["entry_date"],
                            "exit_date": d,
                            "entry_price": p["st"].entry_price,
                            "stop": p["st"].initial_stop,
                            "shares": p["orig"],
                            "pnl_gross": p["gross"],
                            "costs": p["costs"],
                            "pnl_net": net,
                            "tax_est": self.costs.tax_on_gain(net),
                            "days_held": p["st"].days_held,
                        }
                    )
                    del open_pos[sym]

            # 3) mark to market
            eq = cash + sum(p["st"].shares_remaining * p["last_close"] for p in open_pos.values())
            curve[d] = eq

            # 4) generate tomorrow's tickets
            nsma = nifty_sma(self.s, cfg, d, sma_n) if sma_n else None
            if ks or (sma_n and bull_correction_active(rs.nifty_close, rs.nifty_sma200, nsma)):
                continue

            all_syms = self.screener._get_all_symbols(d)
            passed = []
            for sym in all_syms:
                if sym in open_pos:
                    continue
                if sym in ("NIFTY50_INDEX", "INDIA_VIX"):
                    continue
                if not self.screener.screen_single(sym, d, apply_event_gates=False).passed:
                    continue
                if exclusions and (exclusions.asm_blocked(sym, d) or exclusions.earnings_within(sym, d)):
                    continue
                passed.append(sym)

            cands = apply_entry_filters(build_candidate_dicts(self.s, cfg, passed, d), cfg)
            setups = self.sizer.compute_all(
                candidates=cands,
                eval_date=d,
                account_equity=eq,
                current_positions=self._heat_view(open_pos),
                session=self.s,
                is_bull_regime=bull,
            )
            pending = [x for x in setups if not x.blocked]

        # close anything still open at the last close (marked, costs applied) so metrics are complete
        if open_pos and days:
            last_d = days[-1]
            for sym, p in list(open_pos.items()):
                rem_shares = p["st"].shares_remaining
                if rem_shares > 0:
                    exit_price = p["last_close"] * (1.0 - float(ex["exit_slippage_pct"]) / 100.0)
                    sell = self.costs.sell_cost(exit_price * rem_shares)
                    cash += exit_price * rem_shares - sell
                    p["gross"] += (exit_price - p["st"].entry_price) * rem_shares
                    p["costs"] += sell
                    net = p["gross"] - p["costs"]
                    trades.append(
                        {
                            "position_id": p["id"],
                            "symbol": sym,
                            "entry_date": p["entry_date"],
                            "exit_date": last_d,
                            "entry_price": p["st"].entry_price,
                            "stop": p["st"].initial_stop,
                            "shares": p["orig"],
                            "pnl_gross": p["gross"],
                            "costs": p["costs"],
                            "pnl_net": net,
                            "tax_est": self.costs.tax_on_gain(net),
                            "days_held": p["st"].days_held,
                        }
                    )
            open_pos.clear()

        cols = [
            "position_id",
            "symbol",
            "entry_date",
            "exit_date",
            "entry_price",
            "stop",
            "shares",
            "pnl_gross",
            "costs",
            "pnl_net",
            "tax_est",
            "days_held",
        ]
        trades_df = pd.DataFrame(trades, columns=cols) if trades else pd.DataFrame(columns=cols)
        return SimResult(
            trades_df,
            pd.Series(curve, dtype="float64"),
            skipped,
            compliance_applied=bool(exclusions and exclusions.applied),
        )

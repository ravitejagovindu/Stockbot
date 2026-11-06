"""backtest/simulator.py — one simulator for Pass 1 (exclusions=None) and Pass 2 (exclusions=Exclusions)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import distinct, select, text
from sqlalchemy.engine import make_url

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
from engine_core.trade_metrics import compute_trade_r
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
    regime_seed: dict = field(default_factory=dict)  # starting regime state of the run (value + derivation)


REGIME_WARMUP_SESSIONS = 250  # sessions replayed (in memory) before the window to derive the starting regime state


def _live_db_path():
    """Absolute path of the live database file (from data.db.connection.DATABASE_URL), or None if not a file DB."""
    import data.db.connection as conn
    from pathlib import Path

    url = make_url(conn.DATABASE_URL)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def _session_db_path(session):
    from pathlib import Path

    try:
        url = session.get_bind().url
    except Exception:
        return None
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


class Simulator:
    def __init__(self, config: dict, session, allow_live_db: bool = False):
        live, mine = _live_db_path(), _session_db_path(session)
        self._on_live_db = bool(live is not None and mine is not None and live == mine)
        if self._on_live_db and not allow_live_db:
            raise RuntimeError(
                f"Simulator refuses to run on the live database ({mine}). Use a copy, or pass allow_live_db=True "
                "(--allow-live-db); the run then executes with PRAGMA query_only=ON so nothing can be written."
            )
        self.cfg, self.s = config, session
        self.rules = LifecycleRules.from_config(config)
        self.costs = CostModel.from_config(config)
        self.regime = RegimeFilter(config, session, persist=False)
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

    def _trade_row(self, sym: str, p: dict, exit_date: date, exit_reason: str, exit_state: str) -> dict:
        """One closed-position output row. R metrics come from engine_core.trade_metrics.compute_trade_r
        (R base = initial risk in INR recorded at entry; see that module for partial-exit handling)."""
        st = p["st"]
        net = p["gross"] - p["costs"]
        tax = self.costs.tax_on_gain(net)
        one_r = st.entry_price - st.initial_stop
        tot_proceeds = p["gross"] + p["orig"] * st.entry_price
        avg_exit_price = tot_proceeds / p["orig"] if p["orig"] > 0 else st.entry_price
        lowest = p.get("lowest_low", st.entry_price)
        r = compute_trade_r(entry_price=st.entry_price, stop=st.initial_stop, shares_initial=p["orig"],
                            pnl_gross=p["gross"], pnl_net=net, tax_est=tax, risk_inr=p.get("risk_inr"))
        return {
            "position_id": p["id"],
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": exit_date,
            "entry_price": st.entry_price,
            "stop": st.initial_stop,
            "shares": p["orig"],
            "exit_price": avg_exit_price,
            "exit_reason": exit_reason,
            "exit_state": exit_state,
            "highest_high": st.highest_high,
            "lowest_low": lowest,
            "mfe_r": (st.highest_high - st.entry_price) / one_r if one_r > 0 else 0.0,
            "mae_r": (st.entry_price - lowest) / one_r if one_r > 0 else 0.0,
            "risk_inr": r["risk_inr"],
            "gross_r": r["gross_r"],
            "net_r": r["net_r"],
            "net_r_after_tax": r["net_r_after_tax"],
            "realized_r": r["gross_r"],  # DEPRECATED alias of gross_r (kept for old scripts)
            "pnl_gross": p["gross"],
            "costs": p["costs"],
            "pnl_net": net,
            "tax_est": tax,
            "days_held": st.days_held,
        }

    def _derive_regime_seed(self, start_d: date, regime_seed: Optional[dict]) -> dict:
        """Starting regime state of a run: explicit, or replayed in memory from REGIME_WARMUP_SESSIONS before start."""
        if regime_seed is not None:
            seed = {
                "kill_switch_active": bool(regime_seed.get("kill_switch_active", False)),
                "reentry_consecutive_count": int(regime_seed.get("reentry_consecutive_count", 0)),
            }
            seed["derivation"] = "explicit (caller supplied)"
            return seed
        prior = (
            self.s.execute(
                select(MarketDataLake.trade_date)
                .where(MarketDataLake.symbol == self.cfg.get("data", {}).get("nifty_symbol", "NIFTY50_INDEX"))
                .where(MarketDataLake.trade_date < start_d)
                .order_by(MarketDataLake.trade_date.desc())
                .limit(REGIME_WARMUP_SESSIONS)
            ).scalars().all()
        )
        prior = [_to_date(x) for x in reversed(prior)]
        replay = RegimeFilter(self.cfg, self.s, persist=False)
        used = 0
        for d in prior:
            try:
                replay.evaluate(d)
                used += 1
            except RuntimeError:
                continue
        seed = replay.memory_state()
        seed["derivation"] = (
            f"warm-up replay in memory over {used} sessions before {start_d} (start inactive/0, "
            f"max {REGIME_WARMUP_SESSIONS}); no database state used"
        )
        return seed

    # ---- main loop ------------------------------------------------------------
    def run(self, start: date, end: date, initial_equity: float, exclusions=None,
            regime_seed: Optional[dict] = None) -> SimResult:
        if self._on_live_db:
            self.s.execute(text("PRAGMA query_only=ON"))
            try:
                return self._run(start, end, initial_equity, exclusions, regime_seed)
            finally:
                self.s.execute(text("PRAGMA query_only=OFF"))
        return self._run(start, end, initial_equity, exclusions, regime_seed)

    def _run(self, start: date, end: date, initial_equity: float, exclusions, regime_seed) -> SimResult:
        cfg, ex = self.cfg, self.cfg["execution"]
        risk_pct = float(cfg["risk"]["max_loss_pct_per_trade"])
        sma_n = int(cfg.get("macro", {}).get("bull_entry_sma_period", 0))
        start_d, end_d = _to_date(start), _to_date(end)
        seed = self._derive_regime_seed(start_d, regime_seed)
        self.regime = RegimeFilter(
            cfg, self.s, persist=False,
            seed_state={k: seed[k] for k in ("kill_switch_active", "reentry_consecutive_count")},
        )
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
                    "risk_inr": plan.shares * (plan.fill_price - t.live_stop_loss),
                    "gross": 0.0,
                    "costs": buy_cost,
                    "last_close": plan.fill_price,
                    "lowest_low": bar.low,
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
                p["lowest_low"] = min(p.get("lowest_low", p["st"].entry_price), bar.low)
                prev_state = p["st"].state
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
                    final_exit_reason = res.exits[-1].reason if res.exits else "UNKNOWN"
                    trades.append(self._trade_row(sym, p, d, final_exit_reason, prev_state))
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
                    trades.append(self._trade_row(sym, p, last_d, "END_OF_WINDOW", p["st"].state))
            open_pos.clear()

        cols = [
            "position_id",
            "symbol",
            "entry_date",
            "exit_date",
            "entry_price",
            "stop",
            "shares",
            "exit_price",
            "exit_reason",
            "exit_state",
            "highest_high",
            "lowest_low",
            "mfe_r",
            "mae_r",
            "risk_inr",
            "gross_r",
            "net_r",
            "net_r_after_tax",
            "realized_r",
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
            regime_seed=seed,
        )

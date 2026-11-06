"""backtest/path_sim.py — simulate ONE position forward from a ticket, exactly like ``Simulator`` does (F6).

Used by the matched-random baseline so that random trades and actual trades share: the same adjusted per-session price
path (``candidate_builder.bar_context``), the same next-open fill rule (``plan_entry_fill``), the same lifecycle
(``advance_one_bar``), the same corporate-action rebasing (F3, ``corporate_action_events``) and the same R definition
(``trade_metrics.compute_trade_r``). Portfolio effects (cash competition, position caps) are intentionally absent: the
baseline asks "what would an equally-exposed random entry have earned under identical execution and exit rules?".
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select

from data.db.models import CorporateActionsLog, MarketDataLake
from engine_core.adjustments import get_adjusted_series
from engine_core.candidate_builder import bar_context
from engine_core.corporate_action_events import apply_actions_to_position, due_actions
from engine_core.costs import CostModel
from engine_core.lifecycle_rules import BarCtx, LifecycleRules, PosState, advance_one_bar, plan_entry_fill
from engine_core.trade_metrics import compute_trade_r

_LOOKBACK_ROWS = 282  # same history depth candidate_builder gives the Simulator (252 + 30)


def _d(x) -> date:
    return x.date() if hasattr(x, "date") and callable(getattr(x, "date")) else x


def load_raw_path(session, symbol: str, start: date, end: date) -> pd.DataFrame:
    rows = session.execute(
        select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw, MarketDataLake.low_raw,
               MarketDataLake.close_raw, MarketDataLake.volume_raw)
        .where(MarketDataLake.symbol == symbol, MarketDataLake.trade_date >= start, MarketDataLake.trade_date <= end)
        .order_by(MarketDataLake.trade_date)
    ).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [{"trade_date": _d(r.trade_date), "open_raw": float(r.open_raw), "high_raw": float(r.high_raw),
          "low_raw": float(r.low_raw), "close_raw": float(r.close_raw), "volume_raw": int(r.volume_raw)} for r in rows]
    ).set_index("trade_date")


def load_actions(session, symbol: str) -> list[dict]:
    return [
        {"ex_date": c.ex_date, "action_type": c.action_type, "ratio_numerator": c.ratio_numerator,
         "ratio_denominator": c.ratio_denominator}
        for c in session.execute(
            select(CorporateActionsLog).where(CorporateActionsLog.symbol == symbol).order_by(CorporateActionsLog.ex_date)
        ).scalars().all()
    ]


def simulate_position_path(session, cfg: dict, symbol: str, setup, fill_date: date, end_date: date,
                           daily_regime: dict, equity: float = 1_000_000.0, cash: Optional[float] = None,
                           rules: Optional[LifecycleRules] = None, costs: Optional[CostModel] = None) -> dict:
    """Fill ``setup`` (a TradeSetup computed at close T) at the open of ``fill_date`` and run it to exit / ``end_date``.

    Returns ``{"ok": False, "reason": ...}`` if the ticket is not filled, else a dict with exit info and R metrics.
    ``daily_regime`` maps date -> (kill_switch_active, is_bull).
    """
    rules = rules or LifecycleRules.from_config(cfg)
    costs = costs or CostModel.from_config(cfg)
    ex_cfg = cfg["execution"]
    atr_period = int(cfg["risk"]["atr_period"])
    slip_exit = float(ex_cfg["exit_slippage_pct"])

    raw = load_raw_path(session, symbol, fill_date - timedelta(days=500), end_date)
    if raw.empty or fill_date not in raw.index:
        return {"ok": False, "reason": "NO_BAR_ON_FILL_DATE"}
    actions = load_actions(session, symbol)
    if any(_d(a["ex_date"]) == fill_date for a in actions):
        return {"ok": False, "reason": "CORP_ACTION_ON_EXEC_DATE"}

    def ctx_for(d: date):
        prefix = raw.loc[:d].tail(_LOOKBACK_ROWS)
        return bar_context(get_adjusted_series(prefix, actions, as_of_date=d), d, atr_period, rules.parabolic_lookback)

    fill_ctx = ctx_for(fill_date)
    if fill_ctx is None:
        return {"ok": False, "reason": "NO_BAR_ON_FILL_DATE"}
    plan = plan_entry_fill(
        ticket_entry=setup.entry_price, stop=setup.live_stop_loss, target=setup.initial_resistance_target,
        next_open=fill_ctx[0].open, equity=equity, risk_pct=float(cfg["risk"]["max_loss_pct_per_trade"]),
        slippage_pct=float(ex_cfg["entry_slippage_pct"]), max_gap_up_pct=float(ex_cfg["max_entry_gap_up_pct"]),
        min_rr=float(ex_cfg["min_rr_at_fill"]), cash=cash,
    )
    if not plan.ok:
        return {"ok": False, "reason": plan.reason}

    buy_cost = costs.buy_cost(plan.fill_price * plan.shares)
    st = PosState(entry_price=plan.fill_price, initial_stop=setup.live_stop_loss, live_stop=setup.live_stop_loss,
                  target=setup.initial_resistance_target, highest_high=plan.fill_price, shares_remaining=plan.shares)
    risk_inr = plan.shares * (plan.fill_price - setup.live_stop_loss)
    gross, total_costs, orig = 0.0, buy_cost, float(plan.shares)
    ca_done: list[str] = []
    excluded_ca = False
    last_close = plan.fill_price
    exit_reason, exit_date, closed = "END_OF_WINDOW", None, False

    for d in [x for x in raw.index if fill_date <= x <= end_date]:
        ctx = ctx_for(d)
        if ctx is None:
            continue
        bar, atr14, ref = ctx
        due = due_actions(actions, fill_date, d, already=ca_done)
        if due:
            ca = apply_actions_to_position(st, due, ex_price=bar.open)
            st = ca.pos
            ca_done += ca.applied + ca.review
            excluded_ca = excluded_ca or bool(ca.review)
            if ca.total_factor != 1.0:
                orig /= ca.total_factor
            if ca.fractional_shares:
                gross += ca.fractional_shares * (bar.open - st.entry_price)
        ks, bull = daily_regime.get(d, (False, True))
        res = advance_one_bar(st, bar, BarCtx(atr14, ks, bull, ref), rules, slip_exit)
        st, last_close = res.pos, bar.close
        for e in res.exits:
            gross += (e.price - st.entry_price) * e.shares
            total_costs += costs.sell_cost(e.price * e.shares)
        if res.closed:
            closed, exit_date = True, d
            exit_reason = res.exits[-1].reason if res.exits else "STOP_HIT"
            break

    if not closed and st.shares_remaining > 0:
        exit_price = last_close * (1.0 - slip_exit / 100.0)
        gross += (exit_price - st.entry_price) * st.shares_remaining
        total_costs += costs.sell_cost(exit_price * st.shares_remaining)
        exit_date = raw.index[-1] if exit_date is None else exit_date

    pnl_net = gross - total_costs
    tax = costs.tax_on_gain(pnl_net)
    r = compute_trade_r(entry_price=st.entry_price, stop=st.initial_stop, shares_initial=orig, pnl_gross=gross,
                        pnl_net=pnl_net, tax_est=tax, risk_inr=risk_inr)
    return {"ok": True, "fill_price": plan.fill_price, "shares": plan.shares, "exit_reason": exit_reason,
            "exit_date": exit_date, "days_held": st.days_held, "pnl_gross": gross, "costs": total_costs,
            "pnl_net": pnl_net, "excluded_ca": excluded_ca, **r}

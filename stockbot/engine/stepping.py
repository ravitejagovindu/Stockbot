"""Generic position stepping (ENGINE_CONTRACT section 5): ONE fixed order for every exit policy and for random-entry baselines.

For one position and one session bar:
  1. a market exit requested on the previous bar executes at this bar's open x (1 - exit slippage);
  2. the stop live at the previous close is checked against this bar's low; a hit fills at min(open, stop) x (1 - exit slippage). This also applies to the
     ENTRY bar (decision C1): a position filled at the open is stepped through the same bar. There is NO floor at the bar's low (unfloored = conservative);
  3. days held and the highest high are updated, then the policy's ``step`` runs (stop moves, state, requests); a stop never moves down;
  4. limit requests fill at max(open, limit) x (1 - exit slippage) when the bar's high reaches the limit; market requests are queued for the next open.
Costs (``risk.costs``) are settled here, so the backtest, paper/live and the baseline helper produce identical P&L for identical inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from stockbot.engine.exit_policy import Bar, ExitPolicy, Limit, MarketAtNextOpen, StepContext
from stockbot.engine.types import ExitRecord, Position
from stockbot.risk.costs import CostModel


@dataclass(frozen=True)
class StepOutcome:
    position: Position
    exits: tuple              # ExitRecord
    cash_delta: float
    closed: bool
    flags: tuple              # strings


def _sell(pos: Position, day, reason: str, price: float, shares: int, costs: CostModel, closed: bool, assumed: bool = True):
    sell_cost = costs.sell_cost(price * shares)
    rec = ExitRecord(pos.position_id, pos.strategy_id, pos.symbol, day, reason, price, shares, sell_cost, closed, assumed)
    return rec, price * shares - sell_cost, (price - pos.entry_price) * shares, sell_cost


def step_position(pos: Position, bar: Bar, day, view, policy: ExitPolicy, costs: CostModel, exit_slippage_pct: float, overlays: Mapping[str, Any] = None) -> StepOutcome:
    """Advance ``pos`` through one session bar. Pure: returns a new Position, never mutates the input."""
    slip = 1.0 - exit_slippage_pct / 100.0
    exits: list = []
    flags: list = []
    cash = 0.0
    p = pos

    def book(reason, price, shares, closed):
        nonlocal cash, p
        rec, cash_in, gross, cost = _sell(p, day, reason, price, shares, costs, closed)
        exits.append(rec)
        cash += cash_in
        p = replace(p, shares_remaining=p.shares_remaining - shares, gross_pnl=p.gross_pnl + gross, costs_paid=p.costs_paid + cost)

    # 1) market exit requested on the previous bar
    if p.pending_exit > 0 and p.shares_remaining > 0:
        n = min(p.pending_exit, p.shares_remaining)
        book(p.pending_reason or "POLICY_EXIT", bar.open * slip, n, n == p.shares_remaining)
        p = replace(p, pending_exit=0, pending_reason="", last_close=bar.close)
        if p.shares_remaining == 0:
            return StepOutcome(p, tuple(exits), cash, True, tuple(flags))

    # 2) the stop live at the previous close (entry bar included)
    if bar.low <= p.live_stop:
        book("STOP_HIT", min(bar.open, p.live_stop) * slip, p.shares_remaining, True)
        flags.append("STOP_HIT")
        if bar.open < p.live_stop:
            flags.append("GAP_THROUGH_STOP")
        p = replace(p, last_close=bar.close)
        return StepOutcome(p, tuple(exits), cash, True, tuple(flags))

    # 3) age, high, policy
    p = replace(p, days_held=p.days_held + 1, highest_high=max(p.highest_high, bar.high), last_close=bar.close)
    act = policy.step(p, bar, view, StepContext(days_held=p.days_held, overlays=dict(overlays or {})))
    flags.extend(act.flags)
    new_stop = p.live_stop
    if act.new_live_stop is not None:
        if act.new_live_stop < p.live_stop:
            flags.append("STOP_LOWERING_IGNORED")
        else:
            new_stop = act.new_live_stop
    p = replace(p, live_stop=new_stop, exit_state=dict(act.new_exit_state) if act.new_exit_state is not None else p.exit_state)

    # 4) requests: limits fill on this bar, market requests are queued for the next open
    queued, reason = 0, ""
    for r in act.requests:
        if isinstance(r, Limit):
            n = min(int(r.shares), p.shares_remaining)
            if n > 0 and bar.high >= r.limit_price:
                book(r.reason, max(bar.open, r.limit_price) * slip, n, n == p.shares_remaining)
        elif isinstance(r, MarketAtNextOpen):
            if int(r.shares) > 0:
                queued, reason = queued + int(r.shares), (reason or r.reason)
        else:
            raise TypeError(f"unknown exit request: {r!r}")
    if p.shares_remaining > 0 and queued:
        p = replace(p, pending_exit=min(queued, p.shares_remaining), pending_reason=reason)
    return StepOutcome(p, tuple(exits), cash, p.shares_remaining == 0, tuple(flags))

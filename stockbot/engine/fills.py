"""Shared fill rule (ENGINE_CONTRACT section 6, step 2): a ticket created at close T is filled at the open of T+1 - in ``decide`` AND in the matched-random baseline
helper (``engine.path``), so both apply the identical gap rules, slippage, per-strategy confirmation and sizing from the FILL price.

Order (the legacy ``plan_entry_fill`` order): symbol not already held / bar exists -> corporate action on the execution date -> gap through the stop (open <= stop) ->
gap-up cap (shared, ``execution.max_entry_gap_up_pct``) -> fill = open x (1 + entry slippage) -> per-strategy ``confirm`` (for example a minimum R:R at the fill) ->
shares = ``risk.sizing`` from the fill price, equity and the ticket's stop, capped by cash.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Callable, Optional

from stockbot.engine.exit_policy import Bar
from stockbot.engine.types import Fill, Position, Ticket
from stockbot.risk.costs import CostModel
from stockbot.risk.sizing import size_position
from stockbot.strategies.base import Proposal


@dataclass(frozen=True)
class FillPlan:
    ok: bool
    reason: str = ""
    position: Optional[Position] = None
    fill: Optional[Fill] = None
    cash_delta: float = 0.0


def fill_ticket(t: Ticket, bar: Optional[Bar], day: date, *, execution, risk_pct: float, equity: float, cash: float, costs: CostModel, policy_id: str,
                held: bool, corporate_action_today: bool, confirm: Callable[[Proposal, float], Optional[str]], initial_exit_state: Callable[[Position], dict]) -> FillPlan:
    if bar is None or held:
        return FillPlan(False, "NO_BAR_OR_ALREADY_HELD")
    if corporate_action_today:
        return FillPlan(False, "CORP_ACTION_ON_EXEC_DATE")
    if bar.open <= t.stop:
        return FillPlan(False, "GAP_THROUGH_STOP")
    if bar.open > t.reference_price * (1 + execution.max_entry_gap_up_pct / 100.0):
        return FillPlan(False, "GAP_UP_TOO_LARGE")
    price = bar.open * (1 + execution.entry_slippage_pct / 100.0)
    if price - t.stop <= 0:
        return FillPlan(False, "NONPOSITIVE_RISK")
    verdict = confirm(Proposal(t.strategy_id, t.symbol, t.signal_date, t.reference_price, t.stop, t.target, t.rank, t.metadata), price)
    if verdict is not None:
        return FillPlan(False, str(verdict))
    size = size_position(equity=equity, risk_pct=risk_pct, entry=price, stop=t.stop, cash=cash)
    if not size.ok:
        return FillPlan(False, size.reason)
    buy = costs.buy_cost(price * size.shares)
    pos = Position(position_id=f"{t.strategy_id}:{t.symbol}:{day.isoformat()}", strategy_id=t.strategy_id, symbol=t.symbol, sector=t.sector, entry_date=day,
                   entry_price=price, initial_stop=t.stop, live_stop=t.stop, target=t.target, shares_initial=float(size.shares), shares_remaining=size.shares,
                   risk_inr=size.shares * (price - t.stop), exit_policy_id=policy_id, highest_high=price, last_close=price, costs_paid=buy)
    pos = replace(pos, exit_state=initial_exit_state(pos))
    return FillPlan(True, "OK", pos, Fill(t.ticket_id, pos.position_id, t.strategy_id, t.symbol, day, price, size.shares, buy, True), -(price * size.shares + buy))

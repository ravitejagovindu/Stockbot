"""Operator reports in LIVE (decision D4): actual fills, actual exits and "ticket not taken".

The live adapter turns each report into a ``ReportEffect`` (what changes in State, computed once from the report, the pending ticket / open position and the as-of
view for the policy's initial state) and applies it to State BEFORE ``decide`` runs. The effect is also what the journal stores, so State can be rebuilt by
folding effects and Decisions without a view or a policy (``apply_effect`` is pure and needs nothing else). Reality overrides the engine's inference: a reported
fill replaces the simulated one for that ticket; an unreported ticket is simulated by ``decide`` and flagged UNRECONCILED_FILL.
Corrections of an event ``decide`` has already simulated are NOT supported in Part B (report before the next session is processed).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Mapping, Optional

from stockbot.engine.types import ClosedTrade, Position, State, Ticket, _d, to_plain
from stockbot.risk.costs import CostModel


class ReportError(ValueError):
    """The report does not match the State (unknown ticket / position, too many shares ...). Never guessed around."""


@dataclass(frozen=True)
class FillReport:
    ticket_id: str
    date: date
    price: float
    shares: int
    cost: Optional[float] = None       # actual charges if the operator has them; otherwise the cost model estimate

    def report_id(self) -> str:
        return hashlib.sha256(("fill|" + json.dumps(to_plain(self), sort_keys=True)).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ExitReport:
    position_id: str
    date: date
    price: float
    shares: int
    reason: str = "OPERATOR_EXIT"
    cost: Optional[float] = None

    def report_id(self) -> str:
        return hashlib.sha256(("exit|" + json.dumps(to_plain(self), sort_keys=True)).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class NotTakenReport:
    ticket_id: str
    date: date
    note: str = ""

    def report_id(self) -> str:
        return hashlib.sha256(("nottaken|" + json.dumps(to_plain(self), sort_keys=True)).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ReportEffect:
    kind: str                                  # "fill" | "exit" | "not_taken"
    report_id: str
    date: date
    ticket_id: Optional[str] = None            # the pending ticket this resolves (removed from State.pending)
    position: Optional[Position] = None        # the position as it stands afterwards (new or reduced); None if closed or not taken
    closed: Optional[ClosedTrade] = None
    cash_delta: float = 0.0
    realised_delta: float = 0.0
    note: str = ""

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "ReportEffect":
        d = dict(d)
        d["date"] = _d(d["date"])
        d["position"] = Position.from_plain(d["position"]) if d.get("position") else None
        d["closed"] = ClosedTrade.from_plain(d["closed"]) if d.get("closed") else None
        return ReportEffect(**d)


def _find_ticket(state: State, ticket_id: str) -> Ticket:
    for t in state.pending:
        if t.ticket_id == ticket_id:
            return t
    raise ReportError(f"no pending ticket {ticket_id}")


def _find_position(state: State, position_id: str) -> Position:
    for p in state.positions:
        if p.position_id == position_id:
            return p
    raise ReportError(f"no open position {position_id}")


def fill_effect(state: State, r: FillReport, policy, view, costs: CostModel) -> ReportEffect:
    t = _find_ticket(state, r.ticket_id)
    if r.shares < 1 or r.price <= 0:
        raise ReportError("a fill needs shares >= 1 and a positive price")
    if any(p.symbol == t.symbol for p in state.positions):
        raise ReportError(f"{t.symbol} is already held")
    buy = r.cost if r.cost is not None else costs.buy_cost(r.price * r.shares)
    pos = Position(position_id=f"{t.strategy_id}:{t.symbol}:{r.date.isoformat()}", strategy_id=t.strategy_id, symbol=t.symbol, sector=t.sector, entry_date=r.date,
                   entry_price=r.price, initial_stop=t.stop, live_stop=t.stop, target=t.target, shares_initial=float(r.shares), shares_remaining=r.shares,
                   risk_inr=r.shares * (r.price - t.stop), exit_policy_id=policy.id, highest_high=r.price, last_close=r.price, costs_paid=buy)
    pos = replace(pos, exit_state=dict(policy.initial_state(pos, view)))
    return ReportEffect("fill", r.report_id(), r.date, t.ticket_id, pos, None, -(r.price * r.shares + buy), 0.0, "reported fill")


def exit_effect(state: State, r: ExitReport, costs: CostModel) -> ReportEffect:
    p = _find_position(state, r.position_id)
    if not (1 <= r.shares <= p.shares_remaining) or r.price <= 0:
        raise ReportError(f"an exit needs 1 <= shares <= {p.shares_remaining} and a positive price")
    sell = r.cost if r.cost is not None else costs.sell_cost(r.price * r.shares)
    p2 = replace(p, shares_remaining=p.shares_remaining - r.shares, gross_pnl=p.gross_pnl + (r.price - p.entry_price) * r.shares, costs_paid=p.costs_paid + sell,
                 pending_exit=0, pending_reason="")
    cash = r.price * r.shares - sell
    if p2.shares_remaining > 0:
        return ReportEffect("exit", r.report_id(), r.date, None, p2, None, cash, 0.0, r.reason)
    net = p2.gross_pnl - p2.costs_paid
    ct = ClosedTrade(p2.position_id, p2.strategy_id, p2.symbol, p2.entry_date, r.date, p2.entry_price, p2.initial_stop, p2.shares_initial, p2.risk_inr, p2.gross_pnl,
                     p2.costs_paid, net, r.reason, p2.hold)
    return ReportEffect("exit", r.report_id(), r.date, None, p2, ct, cash, net, r.reason)


def not_taken_effect(state: State, r: NotTakenReport) -> ReportEffect:
    t = _find_ticket(state, r.ticket_id)
    return ReportEffect("not_taken", r.report_id(), r.date, t.ticket_id, None, None, 0.0, 0.0, r.note or "ticket not taken")


def apply_effect(state: State, e: ReportEffect) -> State:
    """Pure: the State after one operator report. Needs nothing but the effect."""
    pending = tuple(t for t in state.pending if t.ticket_id != e.ticket_id) if e.ticket_id else state.pending
    positions = list(state.positions)
    if e.position is not None:
        ids = [p.position_id for p in positions]
        if e.position.position_id in ids:
            positions[ids.index(e.position.position_id)] = e.position
        else:
            positions.append(e.position)
    if e.closed is not None:
        positions = [p for p in positions if p.position_id != e.closed.position_id]
    return replace(state, pending=pending, positions=tuple(positions), cash=state.cash + e.cash_delta, realised_pnl_net=state.realised_pnl_net + e.realised_delta)

"""Single-position path simulation for the matched-random baseline (decision Q5): the SAME fill rule (``engine.fills``), corporate-action rebasing (``engine.corporate``)
and stepping (``engine.stepping``) that ``decide`` uses, for one ticket, without portfolio effects (no cash competition, no caps): the baseline asks what an
equally-exposed entry would have earned under identical execution and exit rules.
``simulate_ticket`` is pure given a view factory: ``view_at(day)`` returns the as-of view for that session.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Callable, Optional, Sequence

from stockbot.engine.corporate import apply_actions, due_actions
from stockbot.engine.decide import bar_of
from stockbot.engine.fills import fill_ticket
from stockbot.engine.stepping import step_position
from stockbot.engine.types import ClosedTrade, ExitRecord, Ticket
from stockbot.risk.costs import CostModel


def simulate_ticket(t: Ticket, sessions: Sequence[date], view_at: Callable[[date], object], *, shared_config, policy, equity: float, cash: Optional[float] = None,
                    confirm: Callable = lambda proposal, price: None) -> tuple:
    """Fill ``t`` at the first session in ``sessions`` after its signal date and step it to the end of ``sessions``.
    Returns (ClosedTrade or None, exits, reason): None means not filled (reason says why) or still open at the end (reason "OPEN_AT_END")."""
    costs = CostModel.from_shared(shared_config.costs)
    ex, pr = shared_config.execution, shared_config.portfolio_risk
    todo = [d for d in sessions if d > t.signal_date]
    if not todo:
        return None, (), "NO_SESSION"
    day = todo[0]
    view = view_at(day)
    plan = fill_ticket(t, bar_of(view, t.symbol), day, execution=ex, risk_pct=pr.max_loss_pct_per_trade, equity=equity, cash=equity if cash is None else cash, costs=costs,
                       policy_id=policy.id, held=False, corporate_action_today=any(a["ex_date"] == day for a in view.corporate_actions(t.symbol)),
                       confirm=confirm, initial_exit_state=lambda p: dict(policy.initial_state(p, view)))
    if not plan.ok:
        return None, (), plan.reason
    pos, exits = plan.position, []
    for d in todo:
        view = view_at(d)
        bar = bar_of(view, pos.symbol)
        if bar is None:
            continue
        due = due_actions(view.corporate_actions(pos.symbol), pos.entry_date, d, pos.ca_done)
        if due:
            pos = apply_actions(pos, due, bar.open, policy).position
        res = step_position(pos, bar, d, view, policy, costs, ex.exit_slippage_pct)
        exits.extend(res.exits)
        pos = res.position
        if res.closed:
            net = pos.gross_pnl - pos.costs_paid
            return ClosedTrade(pos.position_id, pos.strategy_id, pos.symbol, pos.entry_date, d, pos.entry_price, pos.initial_stop, pos.shares_initial, pos.risk_inr,
                               pos.gross_pnl, pos.costs_paid, net, res.exits[-1].reason, pos.hold), tuple(exits), "CLOSED"
    return None, tuple(exits), "OPEN_AT_END"

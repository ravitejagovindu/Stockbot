"""Drive one policy through hand-made bars with the REAL engine stepping (engine.stepping.step_position), no lake needed."""
from __future__ import annotations

from datetime import date, timedelta

from stockbot.engine.exit_policy import Bar
from stockbot.engine.stepping import step_position
from stockbot.engine.types import Position
from stockbot.risk.costs import CostModel
from tests.fixtures.engine_run import CFG

COSTS = CostModel.from_shared(CFG.costs)
SLIP_OUT = CFG.execution.exit_slippage_pct
SLIP = 1.0 - SLIP_OUT / 100.0
D0 = date(2024, 3, 1)


def new_position(policy, entry=100.0, stop=90.0, shares=100, **kw) -> Position:
    """A position as fill_ticket leaves it (entry day not yet stepped): exit_state from the policy's initial_state."""
    p = Position(position_id="p1", strategy_id="s", symbol="AAA", sector=None, entry_date=D0, entry_price=entry, initial_stop=stop, live_stop=stop, target=None,
                 shares_initial=float(shares), shares_remaining=shares, risk_inr=shares * (entry - stop), exit_policy_id=policy.id, highest_high=entry, last_close=entry, **kw)
    from dataclasses import replace
    return replace(p, exit_state=dict(policy.initial_state(p, None)))


def walk(policy, pos, bars, start_day=0):
    """Step ``pos`` through ``bars`` (tuples open, high, low, close) one per consecutive day; returns [(day, StepOutcome)] until the position closes."""
    out = []
    for i, b in enumerate(bars):
        day = D0 + timedelta(days=start_day + i)
        res = step_position(pos, Bar(*b), day, None, policy, COSTS, SLIP_OUT)
        out.append((day, res))
        pos = res.position
        if res.closed:
            break
    return out

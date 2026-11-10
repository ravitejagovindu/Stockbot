"""A split or bonus on the session a pending market exit executes must scale the pending exit with the shares (engine/corporate.py::_rescale).

Rule: a full pending exit (pending_exit >= the old shares_remaining) becomes exactly the new shares_remaining; a partial one becomes
floor(pending_exit / factor + 1e-9), capped at the new shares_remaining; no pending exit stays none. Then step_position sells what is pending."""
from datetime import date

import pytest

from stockbot.engine.corporate import apply_actions
from stockbot.engine.exit_policy import Bar
from stockbot.engine.stepping import step_position
from tests.fixtures.dummies import FixedPolicy
from tests.fixtures.engine_run import CFG
from tests.unit.test_engine_corporate import act, position
from stockbot.risk.costs import CostModel

COSTS = CostModel.from_shared(CFG.costs)
EX = date(2020, 2, 3)


def split(num, den):
    return act(EX, "SPLIT", num, den)


def bonus(num, den):
    return act(EX, "BONUS", num, den)


def test_full_pending_exit_follows_a_1_to_5_split():
    p = position(shares_remaining=100, shares_initial=100.0, pending_exit=100, pending_reason="TIME_EXIT")
    q = apply_actions(p, [split(1, 5)], 20.0).position
    assert q.shares_remaining == 500 and q.pending_exit == 500 and q.pending_reason == "TIME_EXIT"


def test_full_pending_exit_follows_a_1_to_1_bonus():
    p = position(shares_remaining=100, shares_initial=100.0, pending_exit=100, pending_reason="TIME_EXIT")
    q = apply_actions(p, [bonus(1, 1)], 50.0).position
    assert q.shares_remaining == 200 and q.pending_exit == 200


def test_full_pending_exit_has_no_leftover_when_the_division_is_inexact():
    p = position(shares_remaining=101, shares_initial=101.0, pending_exit=101, pending_reason="TIME_EXIT")
    q = apply_actions(p, [bonus(1, 2)], 70.0).position                   # factor 2/3: 151.5 shares, floor 151, remainder paid in cash
    assert q.shares_remaining == 151 and q.pending_exit == 151


def test_partial_pending_exit_stays_partial():
    p = position(shares_remaining=100, shares_initial=100.0, pending_exit=40, pending_reason="PART")
    q = apply_actions(p, [split(1, 5)], 20.0).position
    assert q.shares_remaining == 500 and q.pending_exit == 200 and q.pending_exit < q.shares_remaining


def test_partial_pending_exit_is_floored_and_capped():
    p = position(shares_remaining=101, shares_initial=101.0, pending_exit=51, pending_reason="PART")
    q = apply_actions(p, [bonus(1, 2)], 70.0).position                   # 51 / (2/3) = 76.5 -> 76
    assert q.pending_exit == 76 and q.pending_exit <= q.shares_remaining


def test_no_pending_exit_stays_none():
    q = apply_actions(position(), [split(1, 5)], 20.0).position
    assert q.pending_exit == 0


@pytest.mark.parametrize("a,shares", [(split(1, 5), 500), (bonus(1, 1), 200)])
def test_the_whole_position_exits_at_the_open_on_the_ex_date(a, shares):
    p = position(shares_remaining=100, shares_initial=100.0, pending_exit=100, pending_reason="TIME_EXIT", live_stop=1.0)
    q = apply_actions(p, [a], 20.0).position
    bar = Bar(20.0, 21.0, 19.0, 20.5)
    out = step_position(q, bar, EX, None, FixedPolicy(), COSTS, 0.1)
    assert out.closed and out.position.shares_remaining == 0
    assert [(e.shares, e.reason, e.closed) for e in out.exits] == [(shares, "TIME_EXIT", True)]

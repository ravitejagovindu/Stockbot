"""Corporate actions with the library policies: the engine passes the action's price factor (1:5 -> 0.2, 1:10 -> 0.1, 1:1 bonus -> 0.5) and the PRE-action state to
on_corporate_action (engine/corporate.py::_rescale); TrailingStop.highest_close must scale by the same factor as live_stop, entry price and target."""
from dataclasses import replace
from datetime import timedelta

import pytest

from stockbot.data.adjustments import action_factor
from stockbot.engine.corporate import apply_actions
from stockbot.engine.exit_policies.fixed_hold import FixedHold
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.engine.exit_policies.trailing_stop import TrailingStop
from stockbot.engine.exit_policy import Bar
from stockbot.engine.stepping import step_position
from tests.fixtures import mini_lake
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days
from tests.fixtures.policy_lakes import lake_with_action
from tests.fixtures.policy_steps import COSTS, D0, SLIP_OUT, new_position, walk
from tests.unit.test_engine_corporate import act

DS = mini_lake.sessions()
EX_DAY = D0 + timedelta(days=3)
SPLIT_1_5, SPLIT_1_10, BONUS_1_1 = act(EX_DAY, "SPLIT", 1, 5), act(EX_DAY, "SPLIT", 1, 10), act(EX_DAY, "BONUS", 1, 1)


def test_the_factors_the_engine_computes():
    assert action_factor(SPLIT_1_5) == pytest.approx(0.2) and action_factor(SPLIT_1_10) == pytest.approx(0.1) and action_factor(BONUS_1_1) == pytest.approx(0.5)


@pytest.mark.parametrize("a,factor", [(SPLIT_1_5, 0.2), (SPLIT_1_10, 0.1), (BONUS_1_1, 0.5)])
def test_highest_close_scales_with_the_stop_and_the_position(a, factor):
    p = TrailingStop(10)
    pos = walk(p, new_position(p, entry=100.0, stop=90.0, shares=100), [(100, 110, 99, 108)])[0][1].position
    assert pos.exit_state == {"highest_close": 108.0}
    q = apply_actions(pos, [a], 20.0, p).position
    assert q.exit_state == {"highest_close": pytest.approx(108.0 * factor)}
    assert q.live_stop == pytest.approx(pos.live_stop * factor) and q.entry_price == pytest.approx(100.0 * factor)
    assert q.exit_state["highest_close"] / q.live_stop == pytest.approx(pos.exit_state["highest_close"] / pos.live_stop)          # the trail distance is unchanged
    assert not q.hold and pos.exit_state == {"highest_close": 108.0}                                                         # the input state is not mutated


def test_the_policy_gets_the_factor_and_the_pre_action_state_once_per_action_in_order():
    seen = []

    class Spy(TrailingStop):
        def on_corporate_action(self, exit_state, factor):
            seen.append((dict(exit_state), factor))
            return super().on_corporate_action(exit_state, factor)

    p = Spy(10)
    pos = new_position(p, entry=100.0)
    two = [act(EX_DAY, "BONUS", 1, 1), act(EX_DAY, "SPLIT", 1, 5)]
    q = apply_actions(pos, two, 20.0, p).position
    assert [round(f, 12) for _, f in seen] == [0.2, 0.5] or [round(f, 12) for _, f in seen] == [0.5, 0.2]       # (ex_date, type) order is the engine's
    assert seen[0][0] == {"highest_close": 100.0} and q.exit_state["highest_close"] == pytest.approx(100.0 * 0.1)


@pytest.mark.parametrize("bad", [act(EX_DAY, "RIGHTS", 1, 4), act(EX_DAY, "MERGER", 1, 1), {"ex_date": EX_DAY, "action_type": "SPLIT"}, act(EX_DAY, "SPLIT", 0, 5)])
def test_an_unsupported_or_unparsable_action_puts_the_position_on_hold_and_leaves_the_state_alone(bad):
    p = TrailingStop(10)
    pos = walk(p, new_position(p), [(100, 110, 99, 108)])[0][1].position
    out = apply_actions(pos, [bad], 20.0, p)
    q = out.position
    assert q.hold and out.review and q.exit_state == pos.exit_state == {"highest_close": 108.0} and q.live_stop == pos.live_stop and q.entry_price == pos.entry_price


def test_dividends_are_ignored_and_fixed_hold_state_stays_empty():
    p = FixedHold(5)
    pos = new_position(p)
    from stockbot.engine.corporate import due_actions
    assert due_actions([act(EX_DAY, "DIVIDEND", 1, 1)], D0, EX_DAY + timedelta(days=1)) == []
    q = apply_actions(pos, [SPLIT_1_5], 20.0, p).position
    assert q.exit_state == {} and q.days_held == pos.days_held and q.risk_inr == pos.risk_inr


# ------------------------------------------------------------------ the same trade with and without a split mid-hold is economically identical
def run_bars(policy, bars, ex_index=None, action=None, factor=1.0):
    """Walk ``bars`` (in the unsplit basis); from bar ``ex_index`` on the data are in the new basis (x factor) and the action is applied first. Returns exits."""
    pos = new_position(policy, entry=100.0, stop=90.0, shares=100)
    exits = []
    for i, b in enumerate(bars):
        day = D0 + timedelta(days=i)
        if ex_index is not None and i >= ex_index:
            b = tuple(x * factor for x in b)
        if ex_index is not None and i == ex_index:
            pos = apply_actions(pos, [dict(action, ex_date=day)], b[0], policy).position
        res = step_position(pos, Bar(*b), day, None, policy, COSTS, SLIP_OUT)
        exits += list(res.exits)
        pos = res.position
        if res.closed:
            break
    return exits, pos


RISING_THEN_FALLING = [(100, 105, 99, 104), (104, 112, 103, 111), (111, 120, 110, 118), (118, 119, 112, 114), (114, 115, 105, 108), (108, 109, 100, 102), (102, 103, 98, 99)]


@pytest.mark.parametrize("a,factor", [(SPLIT_1_5, 0.2), (SPLIT_1_10, 0.1), (BONUS_1_1, 0.5)])
@pytest.mark.parametrize("policy,ex_index", [(TrailingStop(10), 1), (TrailingStop(10), 2), (TrailingStop(10), 3), (TrailingStop(10), 4),       # 4 = the session the stop is hit
                                             (FixedHold(3), 1), (FixedHold(3), 2), (FixedHold(3), 3),                                           # 3 = the session the queued exit executes
                                             (FixedHold(4), 1), (FixedHold(4), 3), (FixedHold(4), 4)], ids=lambda x: getattr(x, "id", str(x)))
def test_a_split_or_bonus_mid_hold_changes_nothing_economically(policy, ex_index, a, factor):
    base, _ = run_bars(policy, RISING_THEN_FALLING)
    split, _ = run_bars(policy, RISING_THEN_FALLING, ex_index, a, factor)
    assert [(e.reason, e.closed) for e in base] == [(e.reason, e.closed) for e in split] and len(base) == 1
    assert sum(e.shares for e in split) == pytest.approx(sum(e.shares for e in base) / factor)                    # whole position, no leftover
    proceeds = lambda es: sum(e.price * e.shares for e in es)
    assert proceeds(split) == pytest.approx(proceeds(base), rel=1e-12) and split[0].cost == pytest.approx(base[0].cost)


def test_a_fixed_hold_exit_is_complete_when_the_ex_date_is_the_exit_session():
    """fixed_hold_3: requested on session 3, executes at the open of session 4; a 1:5 split with ex-date = session 4 must still exit the whole position (engine fix)."""
    p = FixedHold(3)
    exits, pos = run_bars(p, RISING_THEN_FALLING, 3, SPLIT_1_5, 0.2)
    assert pos.shares_remaining == 0 and exits[0].shares == 500 and exits[0].closed


# ------------------------------------------------------------------ through decide() on lakes with a real corporate action row
def trade(lake, pid, last):
    s = ScriptedStrategy(make_spec("dummy", pid), {DS[mini_lake.BREAKOUT].isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    decs, st = run_days(lake, [d for d in DS if DS[mini_lake.BREAKOUT - 2] <= d <= DS[last]], [s], policies_for([s.spec]))
    return [c for d in decs for c in d.closed], st, decs


@pytest.mark.parametrize("pid,ex", [("fixed_hold_3", 1), ("fixed_hold_3", 2), ("fixed_hold_3", 3), ("trailing_pct_5", 1)])         # ex-dates up to the exit session
@pytest.mark.parametrize("kind,num,den,factor", [("SPLIT", 1, 5, 0.2), ("SPLIT", 1, 10, 0.1), ("BONUS", 1, 1, 0.5)])
def test_decide_the_same_trade_with_and_without_a_split_gives_the_same_money(tmp_path, pid, ex, kind, num, den, factor):
    base_c, base_st, _ = trade(_plain(tmp_path), pid, mini_lake.ENTRY + 8)
    c, st, decs = trade(lake_with_action(tmp_path / "s.db", mini_lake.ENTRY + ex, kind, num, den), pid, mini_lake.ENTRY + 8)
    assert len(base_c) == len(c) == 1 and st.positions == () and base_st.positions == ()
    a, b = base_c[0], c[0]
    assert (a.exit_reason, a.exit_date) == (b.exit_reason, b.exit_date) and not b.excluded_ca
    assert b.shares_initial == pytest.approx(a.shares_initial / factor) and b.entry_price == pytest.approx(a.entry_price * factor)
    assert b.gross_pnl == pytest.approx(a.gross_pnl, rel=1e-9) and b.net_pnl == pytest.approx(a.net_pnl, rel=1e-9) and b.risk_inr == pytest.approx(a.risk_inr)
    assert base_st.cash == pytest.approx(st.cash, rel=1e-9)
    assert [e.shares for d in decs for e in d.exits] and sum(e.shares for d in decs for e in d.exits) == int(round(a.shares_initial / factor))


def _plain(tmp_path):
    from tests.fixtures.policy_lakes import plain_lake
    return plain_lake(tmp_path / "plain.db")


def test_decide_a_held_position_on_an_unsupported_action_is_flagged_and_keeps_its_state(tmp_path):
    from tests.fixtures.policy_lakes import lake_with_action
    lake = lake_with_action(tmp_path / "r.db", mini_lake.ENTRY + 2, "RIGHTS", 1, 4)
    c, st, decs = trade(lake, "trailing_pct_5", mini_lake.ENTRY + 4)
    assert any(f.code == "CORPORATE_ACTION_HOLD" for d in decs for f in d.flags)

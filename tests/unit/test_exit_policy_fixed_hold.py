"""FixedHold: exit requested when days_held reaches N, executed at the next open; the stop is never touched. Hand-derived on bars and on the fixture lake."""
import pytest

from stockbot.engine.exit_policies.fixed_hold import FixedHold
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.engine.exit_policy import Bar, MarketAtNextOpen, PolicyActions, StepContext
from stockbot.engine.stepping import step_position
from tests.fixtures import mini_lake
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days
from tests.fixtures.policy_lakes import lake_without_bar
from tests.fixtures.policy_steps import COSTS, D0, SLIP, SLIP_OUT, new_position, walk

DS = mini_lake.sessions()
FLAT = (100.0, 102.0, 99.0, 101.0)


def test_state_is_empty_and_the_corporate_action_copy_is_unchanged_and_independent():
    p = FixedHold(3)
    pos = new_position(p)
    assert p.initial_state(pos, None) == {} and pos.exit_state == {}
    s = {"x": 1.5}
    out = p.on_corporate_action(s, 0.2)
    assert out == s and out is not s


@pytest.mark.parametrize("n", [1, 2, 5])
def test_it_requests_the_exit_exactly_when_days_held_reaches_n(n):
    p = FixedHold(n)
    pos = new_position(p, shares=77)
    for held in range(1, n + 3):
        act = p.step(pos, Bar(*FLAT), None, StepContext(days_held=held))
        if held < n:
            assert act == PolicyActions()
        else:
            assert act == PolicyActions(requests=(MarketAtNextOpen(77, "TIME_EXIT"),))
        assert act.new_live_stop is None and act.new_exit_state is None and act.flags == ()


def test_the_exit_executes_at_the_open_of_session_n_plus_one_with_exit_slippage():
    p = FixedHold(3)
    bars = [FLAT, FLAT, FLAT, (103.0, 104.0, 95.0, 96.0)]          # session 4 trades far below FLAT but above the stop 90: the open is what counts
    steps = walk(p, new_position(p), bars)
    assert len(steps) == 4
    for _, r in steps[:2]:
        assert not r.exits and r.position.pending_exit == 0
    assert steps[2][1].position.pending_exit == 100 and steps[2][1].position.pending_reason == "TIME_EXIT"      # requested on session 3 ...
    (e,) = steps[3][1].exits                                                                                      # ... executed at session 4's open
    assert (e.reason, e.shares, e.closed) == ("TIME_EXIT", 100, True) and e.price == pytest.approx(103.0 * SLIP) and steps[3][1].closed


def test_n_equals_one_requests_on_the_entry_bar():
    p = FixedHold(1)
    steps = walk(p, new_position(p), [FLAT, (100.5, 101.0, 100.0, 100.8)])
    assert steps[0][1].position.pending_exit == 100 and steps[0][1].position.days_held == 1
    assert steps[1][1].exits[0].price == pytest.approx(100.5 * SLIP)


def test_the_stop_firing_earlier_wins_and_no_exit_is_requested():
    p = FixedHold(5)
    bars = [FLAT, FLAT, (99.0, 99.5, 88.0, 89.0), FLAT, FLAT]      # session 3 trades through the stop 90
    steps = walk(p, new_position(p), bars)
    assert len(steps) == 3
    (e,) = steps[2][1].exits
    assert e.reason == "STOP_HIT" and e.price == pytest.approx(90.0 * SLIP) and steps[2][1].position.pending_exit == 0


def test_a_pending_exit_executes_before_the_stop_check():
    """Session N+1 trades through the stop, but the queued exit runs first: open x slippage, reason TIME_EXIT, not the stop price."""
    p = FixedHold(2)
    steps = walk(p, new_position(p), [FLAT, FLAT, (100.0, 100.5, 50.0, 60.0)])
    (e,) = steps[2][1].exits
    assert e.reason == "TIME_EXIT" and e.price == pytest.approx(100.0 * SLIP)
    assert "STOP_HIT" not in steps[2][1].flags


def test_a_gap_below_the_stop_on_the_exit_session_is_still_an_open_exit():
    p = FixedHold(2)
    steps = walk(p, new_position(p), [FLAT, FLAT, (80.0, 81.0, 79.0, 80.0)])          # opens below the stop 90
    (e,) = steps[2][1].exits
    assert e.reason == "TIME_EXIT" and e.price == pytest.approx(80.0 * SLIP)


def test_the_stop_is_untouched_on_every_session():
    p = FixedHold(4)
    pos = new_position(p, stop=90.0)
    for _, r in walk(p, pos, [(101, 130, 100, 128), (128, 140, 127, 139), FLAT, FLAT, FLAT]):
        assert r.position.live_stop == 90.0 and "STOP_LOWERING_IGNORED" not in r.flags and r.position.exit_state == {}


def test_a_partial_position_is_exited_in_full():
    p = FixedHold(1)
    pos = new_position(p, shares=100)
    from dataclasses import replace
    pos = replace(pos, shares_remaining=60)
    steps = walk(p, pos, [FLAT, FLAT])
    assert steps[0][1].position.pending_exit == 60 and steps[1][1].exits[0].shares == 60


# ------------------------------------------------------------------ through decide() on the fixture lake
SIG, ENTRY = mini_lake.BREAKOUT, mini_lake.ENTRY


def run(lake, pid, last, stop=150.0):
    s = ScriptedStrategy(make_spec("dummy", pid), {DS[SIG].isoformat(): [{"symbol": "FIXCO", "stop": stop}]})
    return run_days(lake, [d for d in DS if DS[SIG - 2] <= d <= DS[last]], [s], policies_for([s.spec]))


def exits_of(decs):
    return [(d.as_of, e) for d in decs for e in d.exits]


def test_decide_exits_at_the_open_of_session_n_plus_one_after_the_entry(tmp_path):
    from tests.fixtures.policy_lakes import plain_lake
    decs, st = run(plain_lake(tmp_path / "l.db"), "fixed_hold_3", ENTRY + 6)
    (pos_day, e), = exits_of(decs)
    assert pos_day == DS[ENTRY + 3] and e.reason == "TIME_EXIT" and e.closed                                   # entry session = 1, request on the 3rd, exit at the open of the 4th
    assert e.price == pytest.approx(mini_lake.fixco_bars(ENTRY + 3)[0] * SLIP) and st.positions == ()
    req_day = [d.as_of for d in decs for u in d.position_updates if u.position.pending_exit]
    assert req_day == [DS[ENTRY + 2]]


def test_decide_the_stop_firing_earlier_beats_the_time_exit(tmp_path):
    from tests.fixtures.policy_lakes import plain_lake
    decs, _ = run(plain_lake(tmp_path / "l.db"), "fixed_hold_5", ENTRY + 8, stop=159.5)          # the crash session (ENTRY+1) opens 160 and trades to 158
    ((day, e),) = exits_of(decs)
    assert day == DS[ENTRY + 1] and e.reason == "STOP_HIT" and e.price == pytest.approx(159.5 * SLIP)


def test_decide_a_session_without_a_bar_does_not_count_as_held(tmp_path):
    """FIXCO has no bar on ENTRY+1: it is flagged, not stepped, days_held does not grow; the 3rd HELD session is ENTRY+3, the exit is at the open of ENTRY+4."""
    lake = lake_without_bar(tmp_path / "gap.db", ENTRY + 1)
    decs, st = run(lake, "fixed_hold_3", ENTRY + 8)
    flags = [(d.as_of, f.code) for d in decs for f in d.flags if f.code == "NO_BAR_POSITION_NOT_STEPPED"]
    assert flags == [(DS[ENTRY + 1], "NO_BAR_POSITION_NOT_STEPPED")]
    held = {d.as_of: u.position.days_held for d in decs for u in d.position_updates}
    assert held[DS[ENTRY]] == 1 and held[DS[ENTRY + 1]] == 1 and held[DS[ENTRY + 2]] == 2 and held[DS[ENTRY + 3]] == 3
    ((day, e),) = exits_of(decs)
    assert day == DS[ENTRY + 4] and e.reason == "TIME_EXIT" and e.price == pytest.approx(mini_lake.fixco_bars(ENTRY + 4)[0] * SLIP)


def test_decide_a_pending_exit_waits_through_a_session_without_a_bar(tmp_path):
    lake = lake_without_bar(tmp_path / "gap.db", ENTRY + 2)
    decs, st = run(lake, "fixed_hold_2", ENTRY + 6)                    # request on ENTRY+1 (2nd held), no bar on ENTRY+2, executes at the open of ENTRY+3
    ((day, e),) = exits_of(decs)
    assert day == DS[ENTRY + 3] and e.price == pytest.approx(mini_lake.fixco_bars(ENTRY + 3)[0] * SLIP)

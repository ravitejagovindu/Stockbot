"""TrailingStop: the reference is the highest close since entry (entry price as the seed); the stop only rises and applies from the NEXT bar. Hand-derived."""
import pytest

from stockbot.engine.exit_policies.trailing_stop import TrailingStop
from stockbot.engine.exit_policy import Bar, PolicyActions, StepContext
from tests.fixtures.policy_steps import D0, SLIP, new_position, walk

P10 = TrailingStop(10)


def stop_of(hc, pct=10):
    return hc * (1 - pct / 100)          # the same expression the policy uses, so equality below is exact


def test_state_schema_and_initial_state_is_the_entry_price():
    pos = new_position(P10, entry=100.0)
    assert P10.initial_state(pos, None) == {"highest_close": 100.0} and list(pos.exit_state) == ["highest_close"]
    assert isinstance(pos.exit_state["highest_close"], float)


def test_the_stop_rises_with_new_closes_and_does_not_lower_when_the_close_falls():
    pos = new_position(P10, entry=100.0, stop=90.0)
    steps = walk(P10, pos, [(100, 105, 99, 104), (104, 110, 100, 108), (108, 109, 101, 102), (102, 103, 98, 99)])
    states = [r.position.exit_state["highest_close"] for _, r in steps]
    stops = [r.position.live_stop for _, r in steps]
    assert states == [104.0, 108.0, 108.0, 108.0]
    assert stops == [stop_of(104.0), stop_of(108.0), stop_of(108.0), stop_of(108.0)]
    assert all(b >= a for a, b in zip(stops, stops[1:])) and all("STOP_LOWERING_IGNORED" not in r.flags for _, r in steps)     # the policy itself never asks for a lower stop


def test_a_close_below_the_previous_high_changes_nothing():
    pos = new_position(P10)
    first = walk(P10, pos, [(100, 110, 99, 110)])[0][1].position
    act = P10.step(first, Bar(109, 110, 100, 105), None, StepContext(days_held=2))
    assert act.new_live_stop is None and act.new_exit_state == {"highest_close": 110.0}


def test_a_candidate_equal_to_the_current_stop_returns_no_stop():
    pos = new_position(P10)
    pos1 = walk(P10, pos, [(100, 110, 99, 110)])[0][1].position           # live_stop = stop_of(110)
    assert pos1.live_stop == stop_of(110.0)
    act = P10.step(pos1, Bar(110, 111, 105, 110.0), None, StepContext(days_held=2))              # same highest close -> candidate == live stop
    assert act.new_live_stop is None


def test_a_candidate_below_the_initial_stop_is_not_proposed():
    """Entry 100, initial stop 95, 10% trail: candidate 90 is below the stop, so no new stop; the engine's STOP_LOWERING_IGNORED flag is not needed."""
    pos = new_position(P10, entry=100.0, stop=95.0)
    (_, r), = walk(P10, pos, [(100, 101, 99, 100)])
    assert r.position.live_stop == 95.0 and r.flags == ()


def test_the_new_stop_applies_from_the_next_bar_only():
    """Entry bar: close 104 -> stop 93.6 produced on this bar, whose low 91 is below 93.6 but above the initial stop 90. The position survives the bar that produced the stop."""
    pos = new_position(P10, entry=100.0, stop=90.0)
    (_, r1), (_, r2) = walk(P10, pos, [(100, 105, 91, 104), (104, 105, 93, 103)])
    assert not r1.closed and r1.position.live_stop == stop_of(104.0)
    assert r2.closed and r2.exits[0].reason == "STOP_HIT"                                                  # the next bar (low 93 <= 93.6) is where it counts
    assert r2.exits[0].price == pytest.approx(stop_of(104.0) * SLIP)                                       # opens 104 above the stop: fills at the stop x (1 - slippage)


def test_a_gap_down_through_the_raised_stop_fills_at_the_open_less_slippage():
    pos = new_position(P10)
    steps = walk(P10, pos, [(100, 105, 99, 104), (104, 110, 100, 108), (90.0, 95.0, 88.0, 92.0)])            # stop is 97.2 after bar 2; bar 3 opens at 90
    r = steps[2][1]
    (e,) = r.exits
    assert e.reason == "STOP_HIT" and e.price == pytest.approx(90.0 * SLIP) and "GAP_THROUGH_STOP" in r.flags and r.closed


def test_entry_day_initial_stop_hit_closes_before_the_policy_runs():
    pos = new_position(P10, entry=100.0, stop=95.0)
    ((_, r),) = walk(P10, pos, [(99.0, 101.0, 94.0, 100.0)])
    assert r.closed and r.exits[0].reason == "STOP_HIT" and r.position.exit_state == {"highest_close": 100.0} and r.position.days_held == 0


def test_entry_day_close_above_the_fill_price_sets_the_reference_and_a_close_below_keeps_the_entry_price():
    up = walk(P10, new_position(P10, entry=100.0), [(100, 106, 99, 105)])[0][1].position
    down = walk(P10, new_position(P10, entry=100.0), [(100, 101, 96, 97)])[0][1].position
    assert up.exit_state["highest_close"] == 105.0 and up.days_held == 1
    assert down.exit_state["highest_close"] == 100.0 and down.live_stop == stop_of(100.0)          # seeded from the entry price (fill price), not from the lower close


def test_a_stop_above_the_close_is_handled_as_the_engine_handles_any_stop():
    """hc 110 -> stop 99; the next bar closes at 95 (< 99) but its low (100) is above the old stop 99... the stop then sits above the close and fires on the following bar."""
    pos = new_position(P10)
    steps = walk(P10, pos, [(100, 110, 99.5, 110), (108, 108, 100, 95), (96, 97, 94, 96)])
    assert steps[1][1].position.live_stop == stop_of(110.0) == pytest.approx(99.0) and steps[1][1].position.last_close == 95 and not steps[1][1].closed
    r = steps[2][1]
    assert r.closed and r.exits[0].price == pytest.approx(96.0 * SLIP)                          # opens below the stop 99: gap rule, open less slippage
    # if the next bar opens above the stop, it fills at the stop
    alt = walk(P10, pos, [(100, 110, 99.5, 110), (108, 108, 100, 95), (101, 102, 98, 100)])
    assert alt[2][1].exits[0].price == pytest.approx(99.0 * SLIP)


def test_the_policy_makes_no_exit_requests_and_never_reads_the_view():
    class NoView:
        def __getattr__(self, name):
            raise AssertionError("TrailingStop must not touch the view")
    pos = new_position(P10)
    act = P10.step(pos, Bar(100, 101, 99, 100), NoView(), StepContext(days_held=1))
    assert act.requests == () and act.flags == () and isinstance(act, PolicyActions)


def test_a_state_without_the_key_falls_back_to_the_entry_price():
    from dataclasses import replace
    pos = replace(new_position(P10, entry=100.0), exit_state={})
    assert P10.step(pos, Bar(100, 101, 99, 100.5), None, StepContext(days_held=1)).new_exit_state == {"highest_close": 100.5}


def test_percent_changes_the_distance():
    pos5, pos20 = new_position(TrailingStop(5)), new_position(TrailingStop(20))
    r5 = walk(TrailingStop(5), pos5, [(100, 120, 99, 120)])[0][1].position
    r20 = walk(TrailingStop(20), pos20, [(100, 120, 99, 120)])[0][1].position
    assert r5.live_stop == stop_of(120.0, 5) and r20.live_stop == stop_of(120.0, 20)

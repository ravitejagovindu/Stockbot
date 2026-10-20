"""Unit tests for engine_core.lifecycle_rules."""
from engine_core.lifecycle_rules import (
    advance_one_bar, plan_entry_fill,
    LifecycleRules, PosState, Bar, BarCtx, Exit, BarResult, EntryPlan,
    INITIAL_RISK, RISK_FREE_1_TO_1, TRAILING_ATR, PARABOLIC_TRAILING, PENDING_MANUAL_EXIT,
)

CFG = {
    "risk": {},
    "trade_management": {"time_decay_sessions": 15},
    "partial_profit": {"enabled": True, "exit_ladder": [{"rr_trigger": 1.0, "exit_pct": 12}]},
    "profit_ratchet": {"enabled": True, "active_in_bull": False, "rungs": [{"trigger_rr": 2.0, "lock_rr": 1.0}]},
}
R = LifecycleRules.from_config(CFG)
CTX = BarCtx(atr14=2.0, kill_switch=False, is_bull=True)


def pos(**k):
    d = dict(entry_price=100.0, initial_stop=95.0, live_stop=95.0, target=110.0,
             highest_high=100.0, shares_remaining=100)
    d.update(k)
    return PosState(**d)


def test_gap_down_fills_at_open_not_stop():
    r = advance_one_bar(pos(), Bar(90, 91, 88, 89), CTX, R)
    assert r.closed and r.exits[0].reason == "STOP_HIT" and r.exits[0].price == 90.0


def test_time_decay_flag_then_exit_at_next_open():
    p = pos(days_held=14)
    r1 = advance_one_bar(p, Bar(100, 101, 99, 100), CTX, R)
    assert r1.pos.state == PENDING_MANUAL_EXIT and not r1.closed
    r2 = advance_one_bar(r1.pos, Bar(101, 103, 100, 102), CTX, R)
    assert r2.closed and r2.exits[0].reason == "TIME_DECAY" and r2.exits[0].price == 101.0


def test_decay_never_fires_after_graduation():
    """Day 8 touches 1R → RISK_FREE, then days_held=20 should NOT re-flag PENDING_MANUAL_EXIT."""
    p = pos()
    r = advance_one_bar(p, Bar(100, 106, 99, 105), CTX, R)       # touches +1R
    assert r.pos.state == RISK_FREE_1_TO_1
    q = r.pos
    q.days_held = 20
    r2 = advance_one_bar(q, Bar(103, 104, 100, 101), CTX, R)
    assert r2.pos.state != PENDING_MANUAL_EXIT


def test_partial_fills_at_max_of_open_and_limit():
    r = advance_one_bar(pos(), Bar(107, 108, 106, 107), CTX, R)  # gaps over the 1R limit (105)
    ex = [e for e in r.exits if e.reason == "PARTIAL_PROFIT"][0]
    assert ex.price == 107.0 and ex.shares == 12


def test_stop_never_moves_down():
    p = pos(state=TRAILING_ATR, live_stop=104.0, highest_high=112.0)
    r = advance_one_bar(p, Bar(108, 109, 107, 108), BarCtx(atr14=6.0, kill_switch=False, is_bull=True), R)
    assert r.pos.live_stop >= 104.0


def test_ratchet_off_in_bull_on_otherwise():
    p = pos(highest_high=110.0)
    on = advance_one_bar(p, Bar(109, 110, 108, 109), BarCtx(2.0, False, False), R).pos.live_stop
    off = advance_one_bar(p, Bar(109, 110, 108, 109), BarCtx(2.0, False, True), R).pos.live_stop
    assert on > off


def test_entry_skipped_when_open_gaps_through_stop_or_too_high():
    kw = dict(ticket_entry=100, stop=95, target=112, equity=1_000_000, risk_pct=1.0,
              slippage_pct=0.1, max_gap_up_pct=3.0, min_rr=1.5)
    assert plan_entry_fill(next_open=94, **kw).reason == "GAP_THROUGH_STOP"
    assert plan_entry_fill(next_open=104, **kw).reason == "GAP_UP_TOO_LARGE"
    assert plan_entry_fill(next_open=100, **kw).ok

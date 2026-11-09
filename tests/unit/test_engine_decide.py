"""stockbot.engine.decide on the fixture lake with dummy strategies/policies (tests/fixtures/dummies.py): hand-derived expectations, no strategy design."""
import sqlite3
from datetime import date, timedelta

import pytest

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.apply import apply_decisions
from stockbot.engine.decide import EngineInputError, EventData, decide
from stockbot.engine.types import Decisions, State
from stockbot.risk.costs import CostModel
from tests.fixtures import mini_lake
from tests.fixtures.dummies import CountingOverlay, FixedPolicy, LoweringPolicy, ScriptedStrategy, ViewReadingPolicy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, policies, run_days
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()


@pytest.fixture(scope="module")
def lake_path(tmp_path_factory):
    """One read-only fixture lake for the whole module (tests that need a modified lake build their own)."""
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p
SIG, ENTRY, CRASH = DS[mini_lake.BREAKOUT], DS[mini_lake.ENTRY], DS[mini_lake.CRASH]
G3_STOP = 159.115349                      # the stop the legacy sizing derived on this fixture (golden master of the G3 test)
SLIP_IN, SLIP_OUT = CFG.execution.entry_slippage_pct / 100.0, CFG.execution.exit_slippage_pct / 100.0
COSTS = CostModel.from_shared(CFG.costs)


def strat(stop, sid="dummy", day=SIG, symbol="FIXCO", **kw):
    return ScriptedStrategy(make_spec(sid), {day.isoformat(): [{"symbol": symbol, "stop": stop, **kw}]})


def days(a, b):
    return [d for d in DS if a <= d <= b]


# ------------------------------------------------------------------ C1: the entry bar
NO_SECTOR = EventData()          # tight stops make big positions; leave the sector cap out of the entry-bar tests


def lake_with_entry_bar(tmp_path, **cols):
    """The fixture lake with some of FIXCO's ENTRY-session columns replaced (open_raw / low_raw ...)."""
    p = tmp_path / "entry_bar.db"
    _make(p)
    con = sqlite3.connect(p)
    for k, v in cols.items():
        con.execute(f"update market_data_lake set {k}=? where symbol='FIXCO' and trade_date=?", (v, ENTRY.isoformat()))
    con.commit(); con.close()
    return p


def lake_with_entry_low(tmp_path, low):
    return lake_with_entry_bar(tmp_path, low_raw=low)


def test_entry_bar_stop_exits_on_the_entry_day(tmp_path):
    p = lake_with_entry_low(tmp_path, 174.0)
    decs, st = run_days(p, days(DS[298], DS[304]), [strat(175.5)], policies(FixedPolicy()), events=NO_SECTOR)
    (t,) = [c for d in decs for c in d.closed]
    assert t.entry_date == t.exit_date == ENTRY and t.exit_reason == "STOP_HIT"            # ENTRY bar: open 177, low 174 <= stop 175.5
    (e,) = [x for d in decs for x in d.exits]
    assert e.price == pytest.approx(175.5 * (1 - SLIP_OUT), abs=1e-9)                        # min(open, stop) x (1 - slippage)
    assert st.positions == ()


def test_entry_bar_stop_has_no_floor_at_the_bars_low(tmp_path):
    p = lake_with_entry_low(tmp_path, 175.45)                                                # low only 0.05 under the stop: inside the slippage band
    decs, _ = run_days(p, days(DS[298], DS[304]), [strat(175.5)], policies(FixedPolicy()), events=NO_SECTOR)
    (e,) = [x for d in decs for x in d.exits]
    assert e.price == pytest.approx(175.5 * (1 - SLIP_OUT), abs=1e-9) and e.price < 175.45   # unfloored fill is BELOW the bar's low: the conservative one (decision C1)


def test_no_entry_bar_exit_when_the_low_stays_above_the_stop(lake_path):
    decs, st = run_days(lake_path, days(DS[298], DS[301]), [strat(170.0)], policies(FixedPolicy()), events=NO_SECTOR)
    assert not [c for d in decs for c in d.closed] and len(st.positions) == 1 and st.positions[0].days_held == 1


# ------------------------------------------------------------------ C2: one session only
def test_decide_handles_exactly_one_session(lake_path):
    conn = open_lake(lake_path)
    st = State(as_of=DS[290], cash=1_000_000.0)
    s = [strat(G3_STOP)]
    p = policies(FixedPolicy())
    for bad in (DS[292], DS[290], DS[289]):
        with pytest.raises(EngineInputError):
            decide(bad, st, AsOfView(conn, bad), s, CFG, EVENTS, policies=p)
    decide(DS[291], st, AsOfView(conn, DS[291]), s, CFG, EVENTS, policies=p)                  # the next session is fine
    with pytest.raises(EngineInputError):
        decide(DS[291], st, AsOfView(conn, DS[292]), s, CFG, EVENTS, policies=p)              # view as-of differs from as_of


def test_a_non_session_date_is_refused(lake_path):
    conn = open_lake(lake_path)
    saturday = DS[10] + timedelta(days=(5 - DS[10].weekday()) % 7)
    with pytest.raises(EngineInputError):
        decide(saturday, State.initial(1e6), AsOfView(conn, saturday), [], CFG, EVENTS, policies={})


# ------------------------------------------------------------------ C3: the policy gets the as-of view
def test_the_exit_policy_receives_the_as_of_view(lake_path):
    pol = ViewReadingPolicy(id="viewer")
    s = ScriptedStrategy(make_spec("dummy", "viewer"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    decs, st = run_days(lake_path, days(DS[298], DS[303]), [s], policies(pol))
    (p,) = st.positions
    assert p.exit_state["seen_as_of"] == DS[303].isoformat()
    assert p.exit_state["seen_close"] == pytest.approx(mini_lake.fixco_bars(303)[3])


# ------------------------------------------------------------------ C4: strict mode
def test_strict_mode_stops_the_run_on_a_strategy_error(lake_path):
    s = ScriptedStrategy(make_spec("dummy"), {}, boom_on=DS[296].isoformat())
    with pytest.raises(RuntimeError, match="scripted failure"):
        run_days(lake_path, days(DS[294], DS[298]), [s], policies(FixedPolicy()))


def test_strict_mode_stops_the_run_on_an_exit_policy_error(lake_path):
    s = ScriptedStrategy(make_spec("dummy", "boom"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    with pytest.raises(RuntimeError, match="policy failure"):
        run_days(lake_path, days(DS[298], DS[304]), [s], policies(FixedPolicy(id="boom", boom=True)))


def test_live_mode_flags_the_error_and_continues_with_the_other_strategies(lake_path):
    bad = ScriptedStrategy(make_spec("a_bad"), {}, boom_on=SIG.isoformat())
    good = strat(G3_STOP, "b_good")
    decs, st = run_days(lake_path, days(DS[298], DS[301]), [bad, good], policies(FixedPolicy()), strict=False, mode="live")
    flags = [f for d in decs for f in d.flags]
    assert any(f.code == "ERROR_PROPOSE" and f.strategy_id == "a_bad" for f in flags)
    assert [t.strategy_id for d in decs for t in d.new_tickets] == ["b_good"]                  # the healthy strategy still produced its ticket
    assert any(f.code == "UNRECONCILED_FILL" for f in flags)                                   # live: assumed fills are flagged for reconciliation


def test_overlay_errors_follow_the_same_rule(lake_path):
    class Boom(CountingOverlay):
        def evaluate(self, view, overlay_state):
            raise RuntimeError("overlay failure")
    s = ScriptedStrategy(make_spec("dummy", overlays={"counter": "1.0.0"}), {})
    with pytest.raises(RuntimeError, match="overlay failure"):
        run_days(lake_path, days(DS[298], DS[299]), [s], policies(FixedPolicy()), overlays={"counter": Boom()})
    decs, _ = run_days(lake_path, days(DS[298], DS[299]), [s], policies(FixedPolicy()), overlays={"counter": Boom()}, strict=False)
    assert any(f.code == "OVERLAY_UNAVAILABLE" for d in decs for f in d.flags)


# ------------------------------------------------------------------ D1: overlays
def test_overlay_signal_reaches_only_the_declaring_strategy_and_state_persists(lake_path):
    a = ScriptedStrategy(make_spec("a_with", overlays={"counter": "1.0.0"}), {})
    b = ScriptedStrategy(make_spec("b_without"), {})
    decs, st = run_days(lake_path, days(DS[298], DS[301]), [a, b], policies(FixedPolicy()), overlays={"counter": CountingOverlay()})
    assert [a.seen_overlays[d.isoformat()]["counter"]["n"] for d in days(DS[298], DS[301])] == [1, 2, 3, 4]
    assert all(v == {} for v in b.seen_overlays.values())
    assert st.overlay_state == {"counter": {"n": 4}}


def test_overlay_declaration_must_match_the_registered_version(lake_path):
    s = ScriptedStrategy(make_spec("dummy", overlays={"counter": "2.0.0"}), {})
    with pytest.raises(EngineInputError):
        run_days(lake_path, days(DS[298], DS[299]), [s], policies(FixedPolicy()), overlays={"counter": CountingOverlay()})
    with pytest.raises(EngineInputError):
        run_days(lake_path, days(DS[298], DS[299]), [s], policies(FixedPolicy()), overlays={})


# ------------------------------------------------------------------ fills, gap rules, per-strategy fill check
def test_confirm_fill_is_per_strategy_and_blocks_the_fill(lake_path):
    s = ScriptedStrategy(make_spec("dummy"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": G3_STOP}]}, reject_fill_above=177.0)
    decs, st = run_days(lake_path, days(DS[298], DS[302]), [s], policies(FixedPolicy()))
    assert not [f for d in decs for f in d.fills]
    assert [(b.reason, b.stage) for d in decs for b in d.blocked if b.stage == "fill"] == [("FILL_ABOVE_LIMIT", "fill")]


def test_gap_through_stop_blocks_the_fill(tmp_path):
    p = lake_with_entry_bar(tmp_path, open_raw=170.0, low_raw=169.0)                                      # the entry session opens at 170, at or below the stop 171
    decs, _ = run_days(p, days(DS[298], DS[302]), [strat(171.0)], policies(FixedPolicy()), events=NO_SECTOR)
    assert [b.reason for d in decs for b in d.blocked] == ["GAP_THROUGH_STOP"] and not [f for d in decs for f in d.fills]


def test_gap_up_cap_is_shared_and_blocks_the_fill(lake_path):
    # reference close 176; open 177 is +0.57%: inside the 3% cap. Tighten the ticket reference so that the open is above reference x 1.03
    s = ScriptedStrategy(make_spec("dummy"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": G3_STOP}]})
    decs, st = run_days(lake_path, days(DS[298], SIG), [s], policies(FixedPolicy()))
    t = st.pending[0]
    from dataclasses import replace
    low_ref = replace(t, reference_price=170.0)                                                  # 177 > 170 x 1.03 = 175.1
    conn = open_lake(lake_path)
    st2 = replace(st, pending=(low_ref,))
    dec, st3 = decide(ENTRY, st2, AsOfView(conn, ENTRY), [s], CFG, EVENTS, policies=policies(FixedPolicy()))
    assert [b.reason for b in dec.blocked] == ["GAP_UP_TOO_LARGE"] and st3.positions == ()


def test_unknown_strategy_or_policy_is_an_input_error(lake_path):
    with pytest.raises(EngineInputError):
        run_days(lake_path, days(DS[298], DS[299]), [strat(150.0)], {})
    with pytest.raises(EngineInputError):
        run_days(lake_path, days(DS[298], DS[299]), [strat(150.0), strat(150.0)], policies(FixedPolicy()))


# ------------------------------------------------------------------ generic stepping order
def test_stops_never_move_down(lake_path):
    s = ScriptedStrategy(make_spec("dummy", "lowering"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    decs, st = run_days(lake_path, days(DS[298], DS[303]), [s], policies(LoweringPolicy(id="lowering")))
    assert st.positions[0].live_stop == 150.0
    assert any(f.code == "STOP_LOWERING_IGNORED" for d in decs for f in d.flags)


def test_time_exit_request_executes_at_the_next_open(lake_path):
    s = ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    decs, st = run_days(lake_path, days(DS[298], DS[308]), [s], policies(FixedPolicy(id="timed", max_days=3)))
    (e,) = [x for d in decs for x in d.exits]
    assert e.reason == "TIME_EXIT" and e.closed and e.date == DS[mini_lake.ENTRY + 3]               # 3rd bar held (entry bar counts) requests; next open executes
    bar_open = mini_lake.fixco_bars(mini_lake.ENTRY + 3)[0]
    assert e.price == pytest.approx(bar_open * (1 - SLIP_OUT))


def test_limit_target_fills_at_max_of_open_and_limit(lake_path):
    entry = 177.0 * (1 + SLIP_IN)
    s = ScriptedStrategy(make_spec("dummy", "tgt"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 160.0}]})
    # target at 0.02 R above entry (177.52): the entry bar's high is 178 -> reached on the entry bar itself
    r = 0.02
    limit = entry + r * (entry - 160.0)
    decs, _ = run_days(lake_path, days(DS[298], DS[303]), [s], policies(FixedPolicy(id="tgt", target_r=r)))
    (e,) = [x for d in decs for x in d.exits]
    assert e.reason == "TARGET" and e.price == pytest.approx(max(177.0, limit) * (1 - SLIP_OUT))


# ------------------------------------------------------------------ determinism, lookahead, fold
def test_determinism_same_inputs_same_outputs(lake_path):
    a = run_days(lake_path, days(DS[290], DS[310]), [strat(G3_STOP)], policies(FixedPolicy()))
    b = run_days(lake_path, days(DS[290], DS[310]), [strat(G3_STOP)], policies(FixedPolicy()))
    assert [d.to_json() for d in a[0]] == [d.to_json() for d in b[0]] and a[1].to_json() == b[1].to_json()


def test_lookahead_changing_every_later_row_does_not_change_earlier_decisions(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    _make(a)
    _make(b)
    T = DS[303]
    con = sqlite3.connect(b)
    con.execute("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*7, close_raw=close_raw*7, volume_raw=1 where trade_date>?", (T.isoformat(),))
    con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('FIXCO', ?, 'SPLIT', 1, 2, 'x', 'T1')",
                ((T + timedelta(days=3)).isoformat(),))
    con.commit(); con.close()
    ra = run_days(a, days(DS[290], T), [strat(G3_STOP)], policies(FixedPolicy()))
    rb = run_days(b, days(DS[290], T), [strat(G3_STOP)], policies(FixedPolicy()))
    assert [d.to_json() for d in ra[0]] == [d.to_json() for d in rb[0]] and ra[1].to_json() == rb[1].to_json()


def test_state_is_the_fold_of_the_decisions(lake_path):
    s = ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    pol = policies(FixedPolicy(id="timed", max_days=40))
    st = State.initial(1_000_000.0)
    rebuilt = State.initial(1_000_000.0)
    conn = open_lake(lake_path)
    for d in days(DS[295], DS[320]):
        dec, st = decide(d, st, AsOfView(conn, d), [s], CFG, EVENTS, policies=pol)
        assert st.cash == dec.cash_after and st.realised_pnl_net == dec.realised_pnl_after and st.as_of == dec.as_of        # the returned State is what the Decisions say
        rebuilt = apply_decisions(rebuilt, Decisions.from_json(dec.to_json()))        # through the journal's JSON form
    assert rebuilt == st and len(st.positions) == 1 and st.positions[0].days_held > 5


# ------------------------------------------------------------------ two strategies: isolation and the held-symbol rule
def test_isolation_a_strategy_gets_the_same_proposals_alone_and_together(lake_path):
    alone = strat(G3_STOP, "a_one")
    run_days(lake_path, days(DS[296], SIG), [alone], policies(FixedPolicy()))
    a2, b2 = strat(G3_STOP, "a_one"), strat(160.0, "b_two")
    run_days(lake_path, days(DS[296], SIG), [a2, b2], policies(FixedPolicy()))
    assert alone.last_proposals == a2.last_proposals and alone.seen_eligible == a2.seen_eligible
    assert b2.last_proposals and b2.last_proposals[0].strategy_id == "b_two"


def test_two_strategies_same_symbol_first_in_order_wins_and_the_other_is_blocked(lake_path):
    a, b = strat(G3_STOP, "a_one"), strat(160.0, "b_two")
    decs, st = run_days(lake_path, days(DS[296], DS[303]), [b, a], policies(FixedPolicy()))
    assert [(t.strategy_id) for d in decs for t in d.new_tickets] == ["a_one"]
    assert [(x.strategy_id, x.reason, x.stage) for d in decs for x in d.blocked] == [("b_two", "SYMBOL_HELD_BY_OTHER_STRATEGY", "risk")]


def test_a_held_symbol_cannot_be_opened_by_another_strategy_later(lake_path):
    a = strat(150.0, "a_one")
    b = ScriptedStrategy(make_spec("b_two"), {DS[303].isoformat(): [{"symbol": "FIXCO", "stop": 120.0}]})
    decs, st = run_days(lake_path, days(DS[298], DS[305]), [a, b], policies(FixedPolicy()))
    assert [(x.strategy_id, x.reason) for d in decs for x in d.blocked] == [("b_two", "SYMBOL_HELD_BY_OTHER_STRATEGY")]
    assert [p.strategy_id for p in st.positions] == ["a_one"]


def test_only_risk_applies_caps(lake_path):
    import tests.fixtures.dummies as dm
    import inspect
    src = inspect.getsource(dm)
    assert "max_concurrent" not in src and "max_total" not in src and "max_sector" not in src       # a strategy never sees or applies a cap
    from stockbot.strategies import base
    assert "caps" not in inspect.signature(base.Strategy.propose).parameters


def test_proposals_outside_the_eligible_universe_are_refused(lake_path):
    s = ScriptedStrategy(make_spec("dummy"), {DS[298].isoformat(): [{"symbol": "NOSUCH", "stop": 1.0}]})
    # propose() builds the reference price from the view, so use a symbol that exists but is not eligible: the index itself
    s2 = ScriptedStrategy(make_spec("dummy"), {DS[298].isoformat(): [{"symbol": "NIFTY50_INDEX", "stop": 1.0}]})
    decs, st = run_days(lake_path, days(DS[298], DS[299]), [s2], policies(FixedPolicy()))
    assert [(b.reason, b.stage) for d in decs for b in d.blocked] == [("NOT_ELIGIBLE", "propose")] and st.pending == ()


# ------------------------------------------------------------------ C1: the entry-bar rule equals the frozen answers of the legacy lifecycle on a random grid
def test_entry_bar_rule_equals_the_frozen_answers_of_the_legacy_advance_one_bar_on_5000_random_cases():
    """The old ``advance_one_bar`` answered these 5,000 entry bars (frozen in tests/golden before engine_core was deleted)."""
    from stockbot.engine.exit_policy import Bar
    from stockbot.engine.stepping import step_position
    from stockbot.engine.types import Position
    from tests.fixtures.golden import legacy
    pol = FixedPolicy()
    cases = legacy()["entry_bar"]
    assert len(cases) == 5000
    stopped = 0
    for c in cases:
        pos = Position("x", "s", "AAA", None, date(2020, 1, 1), c["entry"], c["stop"], c["stop"], None, float(c["shares"]), c["shares"], c["shares"] * (c["entry"] - c["stop"]), "fixed",
                       highest_high=c["entry"], last_close=c["entry"])
        new = step_position(pos, Bar(c["open"], c["high"], c["low"], c["close"]), date(2020, 1, 1), None, pol, COSTS, c["exit_slippage_pct"])
        hit = [e for e in new.exits if e.reason == "STOP_HIT"]
        assert bool(hit) == (c["stop_exit"] is not None), c
        if hit:
            stopped += 1
            assert hit[0].price == pytest.approx(c["stop_exit"]["price"], rel=1e-12) and hit[0].shares == c["stop_exit"]["shares"]
    assert stopped > 1000                                                             # the grid really exercises entry-bar stops, incl. lows inside the slippage band

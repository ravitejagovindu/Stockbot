"""Engine-owned exit history for opt-in strategies (stockbot/engine/exit_history.py; decide.py; reports.apply_effect): recorded on the exit session and visible to that session's proposals,
pruned to the last N sessions, canonical (linked) symbols, SYMBOL_NO_BARS recorded with its reason, END_OF_WINDOW absent, operator-reported exits in live, engine-owned key restored, no change for a
strategy that does not opt in, SQL = memory. Fixture lakes only."""
import json
from dataclasses import replace

import numpy as np
import pytest

from stockbot.backtest.runner import run_backtest
from stockbot.data import symbol_links as SL
from stockbot.engine import exit_history as XH
from stockbot.engine.decide import EventData
from stockbot.engine.reports import ExitReport, FillReport
from stockbot.live.adapter import LiveAdapter
from stockbot.live.state_store import StateStore
from tests.fixtures import mini_lake
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, policies, run_days
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
SIG, ENTRY, CRASH = DS[mini_lake.BREAKOUT], DS[mini_lake.ENTRY], DS[mini_lake.CRASH]
G3_STOP = 159.115349
POL = policies(FixedPolicy(id="timed", max_days=5))


class OptIn(ScriptedStrategy):
    """ScriptedStrategy that opts in and records the state it was given on each session. ``mangle`` is what it returns as its own state."""
    exit_history_sessions = 25
    mangle = "keep"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen_state: dict = {}

    def propose(self, view, eligible, as_of, strategy_state, overlays):
        self.seen_state[as_of.isoformat()] = json.loads(json.dumps(dict(strategy_state)))
        out, st = super().propose(view, eligible, as_of, strategy_state, overlays)
        if self.mangle == "drop":
            return out, {"mine": 1}
        if self.mangle == "alter":
            return out, {**dict(strategy_state), XH.KEY: [["EVIL", "2000-01-01", "STOP_HIT"]]}
        return out, {**st, **{k: v for k, v in dict(strategy_state).items() if k == XH.KEY}}


def strat(cls=OptIn, sid="dummy", stop=G3_STOP, **kw):
    return cls(make_spec(sid, "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": stop}]}, **kw)


@pytest.fixture(scope="module")
def lake_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p


def run(lake, s, a=298, b=312):
    decs, st = run_days(lake, DS[a:b], [s], POL)
    return decs, st


# ------------------------------------------------------------------------------------------------------------------------------ recording and visibility
def test_the_constant_is_the_one_the_strategy_package_will_read():
    assert XH.KEY == "_exits"


def test_an_exit_is_recorded_on_the_exit_session_and_visible_to_that_sessions_proposals(lake_path):
    s = strat()
    decs, st = run(lake_path, s)
    by = {d.as_of: d for d in decs}
    assert [c.exit_reason for c in by[CRASH].closed] == ["STOP_HIT"] and by[CRASH].closed[0].exit_date == CRASH
    assert XH.KEY not in s.seen_state[DS[301].isoformat()] or s.seen_state[DS[301].isoformat()][XH.KEY] == []       # nothing before the exit
    seen = s.seen_state[CRASH.isoformat()][XH.KEY]
    assert seen == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]]                                                          # the same session's proposals see it
    assert by[CRASH].strategy_state_after["dummy"][XH.KEY] == seen and st.strategy_state["dummy"][XH.KEY] == seen
    assert s.seen_state[DS[303].isoformat()][XH.KEY] == seen                                                           # and it persists in the state


def test_a_strategy_that_does_not_opt_in_gets_exactly_the_state_it_got_before(lake_path):
    plain = strat(cls=ScriptedStrategy)
    decs, st = run(lake_path, plain)
    assert all(set(d.strategy_state_after.get("dummy", {})) <= {"n"} for d in decs) and XH.KEY not in st.strategy_state["dummy"]
    assert [d.to_json() for d in decs] == [d.to_json() for d in run(lake_path, strat(cls=ScriptedStrategy))[0]]
    # opting in only adds the reserved key: every other part of every Decisions is the same
    opt = run(lake_path, strat())[0]
    for a, b in zip(decs, opt):
        assert replace(a, strategy_state_after={}).to_json() == replace(b, strategy_state_after={}).to_json()
        assert {k: v for k, v in b.strategy_state_after["dummy"].items() if k != XH.KEY} == a.strategy_state_after["dummy"] if a.strategy_state_after else True


def test_history_is_pruned_to_the_last_n_sessions_of_the_calendar(lake_path):
    s = strat()
    s.exit_history_sessions = 3                                          # instance attribute: the engine reads it with getattr
    run(lake_path, s)
    key = lambda i: s.seen_state[DS[i].isoformat()].get(XH.KEY)           # noqa: E731
    assert key(302) == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]]
    assert key(303) and key(304)                                          # sessions 302, 303, 304 are the last 3 at 304: still there
    assert key(305) == []                                                 # 302 is the 4th session back at 305: dropped


def test_the_engine_restores_its_key_whatever_the_strategy_returns(lake_path):
    for how in ("drop", "alter"):
        s = strat()
        s.mangle = how
        run(lake_path, s)
        assert s.seen_state[DS[304].isoformat()][XH.KEY] == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]], how
    s = strat()
    s.mangle = "drop"
    _, st = run(lake_path, s)
    assert st.strategy_state["dummy"][XH.KEY] == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]] and st.strategy_state["dummy"]["mine"] == 1


def test_a_strategy_that_fails_to_propose_still_gets_its_history_recorded_in_the_state(lake_path):
    s = strat(boom_on=DS[305].isoformat())
    decs, st = run_days(lake_path, DS[298:308], [s], POL, strict=False)
    assert st.strategy_state["dummy"][XH.KEY] == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]]


def test_two_strategies_get_only_their_own_exits(lake_path):
    a, b = strat(sid="strat_a"), ScriptedStrategy(make_spec("strat_b", "timed"), {})
    decs, st = run_days(lake_path, DS[298:306], [a, b], POL)
    assert st.strategy_state["strat_a"][XH.KEY] == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]] and XH.KEY not in st.strategy_state.get("strat_b", {})


# ------------------------------------------------------------------------------------------------------------------------------ linked symbols
def test_the_recorded_symbol_is_the_canonical_one_after_linking(lake_path):
    s = strat()
    _, st = run_days(lake_path, DS[298:302], [s], POL)                    # the position is opened under the physical name FIXCO, before any link exists
    assert [p.symbol for p in st.positions] == ["FIXCO"]
    with SL.override(enabled=True, links=SL.Links([("FIXCO", "FIXNEW")])):    # the stock is renamed: FIXCO -> FIXNEW from now on
        decs, st2 = run_days(lake_path, DS[302:306], [s], POL, state=st)
    assert [c.symbol for d in decs for c in d.closed] == ["FIXCO"]
    assert s.seen_state[DS[304].isoformat()][XH.KEY] == [["FIXNEW", CRASH.isoformat(), "STOP_HIT"]]


# ------------------------------------------------------------------------------------------------------------------------------ SYMBOL_NO_BARS, END_OF_WINDOW
def rising(n=L.N, start=100.0):
    return start * (1.0 + 0.002) ** np.arange(n)


def test_a_position_closed_by_the_no_bars_rule_is_recorded_with_its_reason(tmp_path):
    p = tmp_path / "lake.db"
    ds = L.build(p, {"AAA": rising(), "BBB": rising(start=90.0)}, skip={"AAA": set(range(262, L.N))})
    sig = ds[260]

    class S(OptIn):
        pass
    s = S(make_spec("dummy", "timed"), {sig.isoformat(): [{"symbol": "AAA", "stop": 1.0}]})
    decs, st = run_days(p, ds[258:290], [s], policies(FixedPolicy(id="timed")), events=EventData())
    closed = [c for d in decs for c in d.closed]
    assert [c.exit_reason for c in closed] == ["SYMBOL_NO_BARS"]
    exit_day = closed[0].exit_date
    assert s.seen_state[exit_day.isoformat()][XH.KEY] == [["AAA", exit_day.isoformat(), "SYMBOL_NO_BARS"]]


def test_a_position_still_open_at_the_window_end_is_not_in_the_history(tmp_path):
    p = tmp_path / "lake.db"
    ds = L.build(p, {"AAA": rising()})
    s = OptIn(make_spec("dummy", "timed"), {ds[260].isoformat(): [{"symbol": "AAA", "stop": 1.0}]})
    res = run_backtest(p, ds[258], ds[300], 1_000_000.0, [s], policies(FixedPolicy(id="timed")), CFG, EventData())
    assert [t.exit_reason for t in res.trades] == ["END_OF_WINDOW"]
    assert res.decisions[-1].strategy_state_after["dummy"][XH.KEY] == []


# ------------------------------------------------------------------------------------------------------------------------------ live: reported exits
def live_adapter(tmp_path, lake, s):
    store = StateStore(tmp_path / "state.db")
    store.initialise(1_000_000.0)
    return store, LiveAdapter(store, lake, [s], POL, CFG, EVENTS)


def test_an_operator_reported_exit_is_recorded_and_visible_to_that_sessions_proposals(lake_path, tmp_path):
    s = strat()
    store, ad = live_adapter(tmp_path, lake_path, s)
    for d in DS[298:301]:
        ad.process(d)
    (t,) = ad.state().pending
    ad.process(DS[301], reports=[FillReport(t.ticket_id, DS[301], 177.5, 400)])
    (pos,) = ad.state().positions
    ad.process(DS[302], reports=[ExitReport(pos.position_id, DS[302], 165.0, 400, "OPERATOR_STOP")])
    assert s.seen_state[DS[302].isoformat()][XH.KEY] == [["FIXCO", DS[302].isoformat(), "OPERATOR_STOP"]]
    assert ad.state().strategy_state["dummy"][XH.KEY] == [["FIXCO", DS[302].isoformat(), "OPERATOR_STOP"]]
    assert store.rebuild().to_json() == store.load().to_json()          # the journal fold reproduces the stored state, history included


def test_a_reported_exit_of_a_strategy_that_did_not_opt_in_adds_no_key(lake_path, tmp_path):
    s = strat(cls=ScriptedStrategy)
    store, ad = live_adapter(tmp_path, lake_path, s)
    for d in DS[298:301]:
        ad.process(d)
    (t,) = ad.state().pending
    ad.process(DS[301], reports=[FillReport(t.ticket_id, DS[301], 177.5, 400)])
    (pos,) = ad.state().positions
    ad.process(DS[302], reports=[ExitReport(pos.position_id, DS[302], 165.0, 400, "OPERATOR_STOP")])
    assert XH.KEY not in ad.state().strategy_state.get("dummy", {})


def test_the_live_adapter_and_the_backtest_record_the_same_assumed_exit(lake_path, tmp_path):
    s = strat()
    store, ad = live_adapter(tmp_path, lake_path, s)
    for d in DS[298:312]:
        ad.process(d)
    decs, st = run(lake_path, strat())
    assert ad.state().strategy_state["dummy"][XH.KEY] == st.strategy_state["dummy"][XH.KEY] == [["FIXCO", CRASH.isoformat(), "STOP_HIT"]]


# ------------------------------------------------------------------------------------------------------------------------------ views
def test_sql_and_memory_views_give_identical_histories(lake_path, monkeypatch):
    out = {}
    for view in ("sql", "memory"):
        monkeypatch.setenv("STOCKBOT_VIEW", view)
        s = strat()
        decs, st = run(lake_path, s)
        out[view] = ([d.to_json() for d in decs], st.to_json(), s.seen_state)
    assert out["sql"] == out["memory"]

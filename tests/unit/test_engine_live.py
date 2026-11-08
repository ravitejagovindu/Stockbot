"""The live adapter around decide(): parity with the backtest adapter, idempotency per trading date, the operator's reports (D4), and the separate append-only
state store with its journal (D8)."""
import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from stockbot.backtest.runner import run_backtest
from stockbot.engine.reports import ExitReport, FillReport, NotTakenReport, ReportError
from stockbot.engine.types import Decisions, State
from stockbot.live.adapter import LiveAdapter
from stockbot.live.state_store import SCHEMA_VERSION, StateStore, StateStoreError
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, policies
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
SIG = DS[mini_lake.BREAKOUT]
EARLY = DS[256]
G3_STOP = 159.115349


@pytest.fixture(scope="module")
def lake_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p


def script():
    return {EARLY.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}], SIG.isoformat(): [{"symbol": "FIXCO", "stop": G3_STOP}]}


def make_strategy():
    return ScriptedStrategy(make_spec("dummy", "timed"), script())


POL = policies(FixedPolicy(id="timed", max_days=5))


def strip_live(d: Decisions) -> Decisions:
    return replace(d, flags=tuple(f for f in d.flags if not f.code.startswith("UNRECONCILED")))


def live(tmp_path, lake, cash=1_000_000.0, strategies=None):
    store = StateStore(tmp_path / "state.db")
    store.initialise(cash)
    return store, LiveAdapter(store, lake, strategies or [make_strategy()], POL, CFG, EVENTS)


def test_backtest_and_live_give_identical_decisions_day_by_day(lake_path, tmp_path):
    window = [d for d in DS if DS[250] <= d <= DS[320]]
    assert len(window) >= 60
    bt = run_backtest(lake_path, window[0], window[-1], 1_000_000.0, [make_strategy()], POL, CFG, EVENTS)
    store, adapter = live(tmp_path, lake_path)
    lv = []
    for d in window:
        lv += adapter.process(d)
    assert len(bt.decisions) == len(lv) == len(window)
    assert [strip_live(x).to_json() for x in lv] == [x.to_json() for x in bt.decisions]
    trades = [c for d in bt.decisions for c in d.closed]
    assert len(trades) == 2 and {t.exit_reason for t in trades} == {"TIME_EXIT", "STOP_HIT"}              # a time exit and the G3 stop-out, both paths
    assert adapter.state().to_json() == State.from_json(store.load().to_json()).to_json()
    assert adapter.state().cash == pytest.approx(bt.state.cash) and adapter.state().realised_pnl_net == pytest.approx(bt.state.realised_pnl_net)


def test_processing_the_same_live_date_twice_changes_nothing(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:303]:
        adapter.process(d)
    before = (store.journal_count(), store.load().to_json())
    assert adapter.process(DS[302]) == [] and adapter.process(DS[300]) == []
    assert (store.journal_count(), store.load().to_json()) == before


def test_missed_sessions_are_processed_one_decide_each(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    adapter.process(DS[298])
    out = adapter.process(DS[303])
    assert [d.as_of for d in out] == DS[299:304]
    assert store.load().as_of == DS[303]


def test_reported_fill_overrides_the_simulated_one(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    (t,) = adapter.state().pending
    out = adapter.process(DS[301], reports=[FillReport(t.ticket_id, DS[301], 177.5, 400)])
    (p,) = adapter.state().positions
    assert (p.entry_price, p.shares_remaining, p.entry_date) == (177.5, 400, DS[301])
    assert not out[0].fills and not any(f.code == "UNRECONCILED_FILL" for f in out[0].flags) and p.days_held == 1
    assert out[0].blocked == ()                                   # the resolved ticket is no longer pending: decide() did not try to fill it again
    assert adapter.state().cash == pytest.approx(1_000_000.0 - 177.5 * 400 - adapter.costs.buy_cost(177.5 * 400)) and adapter.state().pending == ()


def test_unreported_ticket_is_simulated_and_flagged(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    out = adapter.process(DS[301])
    assert out[0].fills and out[0].fills[0].assumed
    assert [f.code for f in out[0].flags if f.code.startswith("UNRECONCILED")] == ["UNRECONCILED_FILL"]


def test_ticket_not_taken_is_dropped_without_a_position(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    (t,) = adapter.state().pending
    adapter.process(DS[301], reports=[NotTakenReport(t.ticket_id, DS[301], "no cash")])
    assert adapter.state().positions == () and adapter.state().pending == () and adapter.state().cash == 1_000_000.0


def test_reported_exit_closes_the_position_with_the_real_price(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    (t,) = adapter.state().pending
    adapter.process(DS[301], reports=[FillReport(t.ticket_id, DS[301], 177.5, 400)])
    (p,) = adapter.state().positions
    out = adapter.process(DS[302], reports=[ExitReport(p.position_id, DS[302], 165.0, 400, "OPERATOR_STOP")])
    assert adapter.state().positions == () and adapter.state().realised_pnl_net < 0
    assert not out[0].exits                                   # decide() inferred nothing: the real exit already closed the position
    assert adapter.state().realised_pnl_net == pytest.approx(400 * (165.0 - 177.5) - adapter.costs.buy_cost(177.5 * 400) - adapter.costs.sell_cost(165.0 * 400))


def test_bad_reports_are_refused_not_guessed(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    with pytest.raises(ReportError):
        adapter.process(DS[301], reports=[FillReport("nope", DS[301], 177.5, 400)])
    (t,) = adapter.state().pending
    with pytest.raises(ReportError):
        adapter.process(DS[301], reports=[ExitReport("nope", DS[301], 1.0, 1)])
    adapter.process(DS[301])
    with pytest.raises(ReportError, match="late report"):
        adapter.process(DS[301], reports=[FillReport(t.ticket_id, DS[301], 177.5, 400)])


def test_a_report_given_twice_is_applied_once(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    (t,) = adapter.state().pending
    r = FillReport(t.ticket_id, DS[301], 177.5, 400)
    adapter.process(DS[301], reports=[r, r])
    assert len(adapter.state().positions) == 1 and adapter.state().positions[0].shares_remaining == 400


def test_state_is_rebuilt_from_the_journal_alone(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[250:301]:
        adapter.process(d)
    (t,) = adapter.state().pending
    adapter.process(DS[301], reports=[FillReport(t.ticket_id, DS[301], 177.5, 400)])
    for d in DS[302:310]:
        adapter.process(d)
    assert store.journal_count() > 50
    assert store.rebuild().to_json() == store.load().to_json()
    store.close()
    again = StateStore(tmp_path / "state.db")
    assert again.rebuild().to_json() == again.load().to_json()                         # also from a fresh connection


def test_a_report_journaled_before_any_further_session_is_rebuilt(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:301]:
        adapter.process(d)
    (t,) = adapter.state().pending
    st = adapter._apply_reports(store.load(), [FillReport(t.ticket_id, DS[301], 177.5, 400)])          # journaled, but decide() has not run yet
    assert st.positions and store.load().to_json() == st.to_json()
    assert store.rebuild().to_json() == st.to_json()


def test_journal_is_append_only(lake_path, tmp_path):
    store, adapter = live(tmp_path, lake_path)
    adapter.process(DS[298])
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._con.execute("update journal set payload='x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._con.execute("delete from journal")
    with pytest.raises(sqlite3.IntegrityError):
        store._con.execute("insert into journal (kind, session, key, payload) values ('decisions', ?, ?, '{}')", (DS[298].isoformat(), DS[298].isoformat()))   # same session twice


def test_state_store_is_versioned_and_separate_from_the_lake(tmp_path):
    p = tmp_path / "s.db"
    StateStore(p).close()
    con = sqlite3.connect(p)
    con.execute("update meta set value='99' where key='schema_version'")
    con.commit(); con.close()
    with pytest.raises(StateStoreError, match="schema_version"):
        StateStore(p)
    with pytest.raises(StateStoreError, match="finsight.db"):
        StateStore(tmp_path / "finsight.db")
    assert SCHEMA_VERSION == 1


def test_the_live_adapter_does_not_write_the_lake(lake_path, tmp_path):
    import hashlib
    h = lambda: hashlib.sha256(lake_path.read_bytes()).hexdigest()
    before = h()
    store, adapter = live(tmp_path, lake_path)
    for d in DS[298:303]:
        adapter.process(d)
    assert h() == before

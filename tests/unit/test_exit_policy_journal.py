"""State, position and pending exit survive Decisions JSON, apply_decisions and StateStore.rebuild(), with each policy; same inputs give byte-identical decisions."""
import pytest

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.apply import apply_decisions
from stockbot.engine.decide import decide
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.engine.types import Decisions, State
from stockbot.live.adapter import LiveAdapter
from stockbot.live.state_store import StateStore
from tests.fixtures import mini_lake
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, run_days
from tests.fixtures.own_policy import OwnExit
from tests.fixtures.policy_lakes import lake_with_action, plain_lake

DS = mini_lake.sessions()
SIG, ENTRY = mini_lake.BREAKOUT, mini_lake.ENTRY
CASES = [("fixed_hold_3", None), ("trailing_pct_5", None), ("alpha_exit_2", OwnExit(2, "alpha_exit_2"))]


def strategy(pid, stop=150.0):
    return ScriptedStrategy(make_spec("dummy", pid), {DS[SIG].isoformat(): [{"symbol": "FIXCO", "stop": stop}]})


def window(a, b):
    return [d for d in DS if DS[a] <= d <= DS[b]]


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    return plain_lake(tmp_path_factory.mktemp("lk") / "l.db")


@pytest.mark.parametrize("pid,own", CASES, ids=[c[0] for c in CASES])
def test_state_position_and_pending_exit_survive_the_json_fold(lake, pid, own):
    s = strategy(pid)
    pol = policies_for([s.spec], extra=[own] if own else None)
    conn = open_lake(lake)
    st = rebuilt = State.initial(1_000_000.0)
    saw_state = saw_pending = False
    for d in window(SIG - 2, ENTRY + 6):
        dec, st = decide(d, st, AsOfView(conn, d), [s], CFG, EVENTS, policies=pol)
        rebuilt = apply_decisions(rebuilt, Decisions.from_json(dec.to_json()))
        assert rebuilt == st and State.from_json(st.to_json()) == st and State.from_json(st.to_json()).to_json() == st.to_json()
        for p in st.positions:
            saw_state |= bool(p.exit_state)
            saw_pending |= p.pending_exit > 0
            assert p.exit_policy_id == pid
    assert saw_state == (pid != "fixed_hold_3")
    assert saw_pending == (pid != "trailing_pct_5")


@pytest.mark.parametrize("pid,own", CASES, ids=[c[0] for c in CASES])
def test_the_live_state_equals_the_rebuilt_state_with_each_policy(lake, tmp_path, pid, own):
    s = strategy(pid)
    store = StateStore(tmp_path / "state.db")
    store.initialise(1_000_000.0)
    adapter = LiveAdapter(store, lake, [s], policies_for([s.spec], extra=[own] if own else None), CFG, EVENTS)
    mid = None
    for d in window(SIG - 2, ENTRY + 6):
        adapter.process(d)
        assert store.rebuild().to_json() == store.load().to_json()                       # at every session, not only at the end
        if any(p.pending_exit for p in store.load().positions):
            mid = store.load()
    if pid != "trailing_pct_5":
        assert mid is not None and mid.positions[0].pending_exit > 0                       # the pending exit was in the stored state between two sessions
    st = adapter.state()
    assert st.positions == () and st.realised_pnl_net != 0
    store.close()
    again = StateStore(tmp_path / "state.db")
    assert again.rebuild().to_json() == again.load().to_json()


def test_the_state_after_a_split_round_trips_too(tmp_path):
    lake = lake_with_action(tmp_path / "sp.db", ENTRY + 3, "SPLIT", 1, 5)
    s = strategy("trailing_pct_20")
    conn = open_lake(lake)
    pol = policies_for([s.spec])
    st = State.initial(1_000_000.0)
    seen = []
    for d in window(SIG - 2, ENTRY + 2):
        dec, st = decide(d, st, AsOfView(conn, d), [s], CFG, EVENTS, policies=pol)
    (p,) = st.positions
    before = p.exit_state["highest_close"]
    dec, st2 = decide(DS[ENTRY + 3], st, AsOfView(conn, DS[ENTRY + 3]), [s], CFG, EVENTS, policies=pol)
    assert State.from_json(st2.to_json()) == st2 and apply_decisions(st, Decisions.from_json(dec.to_json())) == st2
    (q,) = st2.positions
    assert before == pytest.approx(177.5) and q.exit_state["highest_close"] == pytest.approx(before * 0.2) and q.shares_remaining == 5 * p.shares_remaining


@pytest.mark.parametrize("pid,own", CASES, ids=[c[0] for c in CASES])
def test_determinism_and_idempotency_byte_identical_decisions(lake, pid, own):
    def once():
        s = strategy(pid)
        return run_days(lake, window(SIG - 2, ENTRY + 6), [s], policies_for([s.spec], extra=[own] if own else None))
    (a, sa), (b, sb) = once(), once()
    assert [d.to_json() for d in a] == [d.to_json() for d in b] and sa.to_json() == sb.to_json() and a and any(d.exits or d.fills for d in a)


def test_replaying_a_session_from_the_same_state_gives_the_same_bytes(lake):
    s = strategy("trailing_pct_5")
    pol = policies_for([s.spec])
    conn = open_lake(lake)
    st = State.initial(1_000_000.0)
    for d in window(SIG - 2, ENTRY):
        dec, st = decide(d, st, AsOfView(conn, d), [s], CFG, EVENTS, policies=pol)
    nxt = DS[ENTRY + 1]
    d1, s1 = decide(nxt, st, AsOfView(conn, nxt), [s], CFG, EVENTS, policies=pol)
    d2, s2 = decide(nxt, st, AsOfView(conn, nxt), [s], CFG, EVENTS, policies=pol)
    assert d1.to_json() == d2.to_json() and s1.to_json() == s2.to_json()

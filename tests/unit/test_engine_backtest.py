"""Backtest adapter and the single-ticket baseline helper: both reuse the same decide()/fill/stepping code (decision Q5)."""
import socket

import pytest

from stockbot.backtest.no_network import NetworkAccessError
from stockbot.backtest.runner import run_backtest
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.path import simulate_ticket
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, policies
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
SIG = DS[mini_lake.BREAKOUT]
G3_STOP = 159.115349
POL = policies(FixedPolicy(id="timed", max_days=5))


@pytest.fixture(scope="module")
def lake_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p


def test_backtest_closes_open_positions_at_the_window_end(lake_path):
    s = ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})
    r = run_backtest(lake_path, DS[298], DS[304], 1_000_000.0, [s], POL, CFG, EVENTS)
    (t,) = r.trades
    assert t.exit_reason == "END_OF_WINDOW" and t.exit_date == DS[304] and r.state.positions == () and r.end_of_window_exits[0].reason == "END_OF_WINDOW"
    last_close = mini_lake.fixco_bars(304)[3]
    assert r.end_of_window_exits[0].price == pytest.approx(last_close * (1 - CFG.execution.exit_slippage_pct / 100.0))
    assert len(r.equity_curve) == 7


def test_backtest_forbids_the_network(lake_path):
    class Netty(ScriptedStrategy):
        def propose(self, view, eligible, as_of, strategy_state, overlays):
            socket.create_connection(("example.com", 80), timeout=1)
            return [], {}
    with pytest.raises(NetworkAccessError):
        run_backtest(lake_path, DS[298], DS[299], 1e6, [Netty(make_spec("dummy", "timed"), {})], POL, CFG, EVENTS)


@pytest.mark.parametrize("stop,max_days", [(G3_STOP, 5), (150.0, 5), (150.0, 12)])
def test_the_baseline_helper_and_the_backtest_agree_on_the_same_ticket(lake_path, stop, max_days):
    pol = policies(FixedPolicy(id="timed", max_days=max_days))
    s = ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": stop}]})
    window = [d for d in DS if DS[298] <= d <= DS[330 - 1]]
    bt = run_backtest(lake_path, window[0], window[-1], 1_000_000.0, [s], pol, CFG, EVENTS)
    ticket = next(t for d in bt.decisions for t in d.new_tickets)
    conn = open_lake(lake_path)
    trade, exits, why = simulate_ticket(ticket, window, lambda d: AsOfView(conn, d), shared_config=CFG, policy=pol["timed"], equity=1_000_000.0)
    (ref,) = [c for c in bt.trades if c.exit_reason != "END_OF_WINDOW"] or [None]
    if ref is None:                                            # still open at the end of the window in both
        assert trade is None and why == "OPEN_AT_END"
    else:
        assert trade == ref and why == "CLOSED"
        assert list(exits) == [e for d in bt.decisions for e in d.exits]


def test_the_run_manifest_records_what_reproduces_the_run(lake_path):
    import json
    s = ScriptedStrategy(make_spec("dummy", "timed", overlays={"counter": "1.0.0"}), {})
    from tests.fixtures.dummies import CountingOverlay
    r = run_backtest(lake_path, DS[298], DS[300], 1_000_000.0, [s], POL, CFG, EVENTS, overlays={"counter": CountingOverlay()}, seed=7)
    m = r.manifest
    assert json.loads(json.dumps(m)) == m                                                             # plain JSON data
    assert len(m["shared_config_hash"]) == 64 and m["seed"] == 7 and m["window"] == [DS[298].isoformat(), DS[300].isoformat()] and m["initial_equity"] == 1_000_000.0
    assert m["strategies"]["dummy"] == {"version": "0.1.0", "config_hash": s.spec.config_hash(), "exit_policy": "timed", "overlays": {"counter": "1.0.0"}}
    assert m["data_snapshot"]["file"] == "lake.db" and m["data_snapshot"]["size"] == lake_path.stat().st_size and m["data_snapshot"]["last_session"] == DS[300].isoformat()
    assert m["git_sha"] is None or len(m["git_sha"]) == 40
    again = run_backtest(lake_path, DS[298], DS[300], 1_000_000.0, [s], POL, CFG, EVENTS, overlays={"counter": CountingOverlay()}, seed=7).manifest
    assert again == m                                                                                 # deterministic
    from dataclasses import replace
    other = replace(CFG, execution=replace(CFG.execution, entry_slippage_pct=CFG.execution.entry_slippage_pct + 0.01))
    assert run_backtest(lake_path, DS[298], DS[300], 1_000_000.0, [s], POL, other, EVENTS, overlays={"counter": CountingOverlay()}, seed=7).manifest["shared_config_hash"] != m["shared_config_hash"]

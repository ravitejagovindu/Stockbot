"""stockbot.live.health_check: each problem is reported; a healthy state store on a fresh lake passes."""
from datetime import timedelta

import pytest

from stockbot.config.shared import load_shared_config
from stockbot.data.lake import open_lake
from stockbot.live import health_check
from stockbot.live.runner import Book, run_eod
from stockbot.live.state_store import StateStore
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
CFG = load_shared_config()


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p


def processed(tmp_path, lake, upto):
    store = StateStore(tmp_path / "s.db")
    s = ScriptedStrategy(make_spec("dummy", status="paper"), {DS[299].isoformat(): [{"symbol": "FIXCO", "stop": 159.115349}]})
    run_eod(cfg=CFG, book=Book((s,), {"fixed": FixedPolicy()}), as_of=DS[upto], store=store, lake=lake, out_dir=tmp_path / "t")
    return store


def test_a_processed_fresh_state_is_healthy(tmp_path, lake):
    store = processed(tmp_path, lake, 329)
    assert health_check.check(open_lake(lake), store, DS[329] + timedelta(days=1)) == []


def test_stale_price_data_is_reported(tmp_path, lake):
    store = processed(tmp_path, lake, 329)
    problems = health_check.check(open_lake(lake), store, DS[329] + timedelta(days=30))
    assert any("price data is stale" in p for p in problems)


def test_a_state_store_behind_the_lake_is_reported(tmp_path, lake):
    store = processed(tmp_path, lake, 320)
    problems = health_check.check(open_lake(lake), store, DS[329] + timedelta(days=1))
    assert any("has not processed the newest session" in p for p in problems)


def test_a_snapshot_that_disagrees_with_the_journal_is_reported(tmp_path, lake):
    store = processed(tmp_path, lake, 329)
    store._con.execute("update snapshot set state = replace(state, '\"cash\": ', '\"cash\": 1')")
    store._con.commit()
    problems = health_check.check(open_lake(lake), store, DS[329] + timedelta(days=1))
    assert any("differs from the state rebuilt" in p for p in problems)


def test_an_uninitialised_store_is_reported(tmp_path, lake):
    problems = health_check.check(open_lake(lake), StateStore(tmp_path / "empty.db"), DS[329] + timedelta(days=1))
    assert any("state store" in p and "not initialised" in p for p in problems)


def test_command_line_exit_codes(tmp_path, lake, monkeypatch, capsys):
    monkeypatch.setenv("STOCKBOT_DB", str(lake))
    monkeypatch.setenv("STOCKBOT_STATE_DB", str(tmp_path / "none.db"))
    assert health_check.main(["--today", "2020-01-01"]) == 1 and "never run" in capsys.readouterr().out
    processed(tmp_path, lake, 329).close()
    monkeypatch.setenv("STOCKBOT_STATE_DB", str(tmp_path / "s.db"))
    assert health_check.main(["--today", (DS[329] + timedelta(days=1)).isoformat()]) == 0
    assert health_check.main(["--today", (DS[329] + timedelta(days=60)).isoformat()]) == 1 and "stale" in capsys.readouterr().out      # problems found: exit code 1

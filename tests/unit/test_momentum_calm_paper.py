"""momentum_calm PAPER setup: the paper spec differs from the registered spec in status only, the account starts at 200,000 with no deposit path, the paper step refuses unsealed data and locks,
and the daily job runs the paper step only after a successful data step. Fixture lake only; no network; the real lake and state database are never opened."""
import dataclasses
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from stockbot.live.runner import strategies_for_mode, ModeError
from stockbot.live.state_store import StateStore
from stockbot.strategies.momentum_calm.paper import PAPER_SPEC, PAPER_START_CASH, paper_policy_extras, paper_strategy, rule_fields, rule_hash
from stockbot.strategies.momentum_calm.strategy import SPEC
from tests.fixtures import mini_lake
from tests.fixtures.lakefile import _make

ROOT = Path(__file__).resolve().parents[2]
REGISTERED_HASH = "d215b84c5b2c340929a7bf4bef3d01e3da4f8e613d35fd0a9bc62edc96cbad55"       # the family_batch7 ledger row
DS = mini_lake.sessions()


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_registered_spec_is_untouched_and_the_paper_spec_differs_in_status_only():
    assert SPEC.status == "research" and SPEC.config_hash() == REGISTERED_HASH
    assert PAPER_SPEC.status == "paper" and PAPER_SPEC.config_hash() != REGISTERED_HASH
    assert rule_fields(PAPER_SPEC) == rule_fields(SPEC) and rule_hash(PAPER_SPEC) == rule_hash(SPEC)
    changed = [f.name for f in dataclasses.fields(SPEC) if getattr(SPEC, f.name) != getattr(PAPER_SPEC, f.name)]
    assert changed == ["status"]
    assert PAPER_SPEC.validation_ref is None


def test_the_paper_book_runs_in_paper_and_never_in_live():
    from stockbot.live.runner import Book
    b = Book.from_strategies([paper_strategy()], extra_policies=paper_policy_extras())
    assert [s.spec.id for s in strategies_for_mode(b, "PAPER")] == ["momentum_calm"]
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")                                   # status paper, no validation_ref: LIVE stays impossible


def test_whole_share_sizing_rejects_a_position_that_rounds_to_zero():
    from stockbot.risk.sizing import size_position
    r = size_position(equity=PAPER_START_CASH, risk_pct=1.0, entry=30000.0, stop=30000.0 - 2400.0)       # 1% of 200,000 = 2,000 < one share's risk of 2,400
    assert not r.ok and r.reason == "SIZE_ZERO" and r.shares == 0
    ok = size_position(equity=PAPER_START_CASH, risk_pct=1.0, entry=2348.0, stop=2127.88)
    assert ok.ok and ok.shares == 9


@pytest.fixture()
def paper(tmp_path, monkeypatch):
    lake = tmp_path / "lake.db"
    _make(lake)
    monkeypatch.setenv("STOCKBOT_DB", str(lake))
    monkeypatch.setenv("STOCKBOT_STATE_DB", str(tmp_path / "state" / "live_state.db"))
    monkeypatch.setenv("STOCKBOT_TICKETS_DIR", str(tmp_path / "tickets"))
    monkeypatch.setenv("STOCKBOT_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("STOCKBOT_RISK_PCT", raising=False)
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    return load_script("paper_run"), tmp_path


def test_the_paper_step_refuses_a_lake_that_is_not_sealed_through_the_date(paper, capsys):
    mod, tmp = paper
    assert mod.main(["--date", DS[298].isoformat()]) == 2
    assert "sealed" in capsys.readouterr().out and not (tmp / "state" / "live_state.db").exists()


def test_the_paper_step_does_nothing_while_a_lock_is_held(paper, capsys):
    mod, tmp = paper
    (tmp / "locks").mkdir()
    (tmp / "locks" / "daily_update.lock").write_text("x")
    assert mod.main(["--date", DS[298].isoformat()]) == 4
    assert "LOCKED" in capsys.readouterr().out and not (tmp / "state" / "live_state.db").exists()


def _lock(tmp, name, db, pid=999999, alive_text=None):
    import json
    (tmp / "locks").mkdir(exist_ok=True)
    (tmp / "locks" / name).write_text(alive_text if alive_text is not None else json.dumps(
        {"kind": "run", "pid": pid, "host": "other-host", "started_at": "2026-11-20T11:00:00+00:00", "db": str(db).lower(), "label": "baseline / signal count", "argv": []}), encoding="utf-8")


def test_an_empty_lock_directory_does_not_block(paper):
    mod, tmp = paper
    (tmp / "locks").mkdir()
    assert mod.locks_held() == []


def test_a_lock_for_another_database_does_not_block(paper, monkeypatch):
    mod, tmp = paper
    _lock(tmp, "run_4580_x.lock", tmp / "pytest" / "ram0" / "lake.db")
    assert mod.locks_held() == []
    monkeypatch.setattr(mod, "seal_of", lambda con, table: DS[298].isoformat())
    assert mod.main(["--date", DS[298].isoformat()]) == 0                     # the paper step runs


def test_a_lock_on_the_same_database_blocks(paper, capsys):
    from stockbot.data.guard.runlock import db_key
    mod, tmp = paper
    _lock(tmp, "run_4580_y.lock", db_key(tmp / "lake.db"))
    assert mod.locks_held() == ["run_4580_y.lock"]
    assert mod.main(["--date", DS[298].isoformat()]) == 4 and not (tmp / "state" / "live_state.db").exists()
    assert "LOCKED" in capsys.readouterr().out


def test_an_unreadable_lock_blocks_whatever_database_it_is_for(paper):
    mod, tmp = paper
    _lock(tmp, "garbage.lock", "", alive_text="not json")
    assert mod.locks_held() == ["garbage.lock"]
    assert mod.main(["--date", DS[298].isoformat()]) == 4


def test_a_lock_for_another_database_and_one_on_this_one_together_block_and_name_only_this_one(paper):
    from stockbot.data.guard.runlock import db_key
    mod, tmp = paper
    _lock(tmp, "run_1_other.lock", tmp / "elsewhere" / "lake.db")
    _lock(tmp, "run_2_same.lock", db_key(tmp / "lake.db"))
    assert mod.locks_held() == ["run_2_same.lock"]


def test_the_account_starts_at_200000_and_a_second_run_changes_nothing(paper, monkeypatch):
    mod, tmp = paper
    monkeypatch.setattr(mod, "seal_of", lambda con, table: DS[298].isoformat())
    assert mod.main(["--date", DS[298].isoformat()]) == 0
    s = StateStore(tmp / "state" / "live_state.db")
    st, n = s.load(), s.journal_count()
    s.close()
    assert st.cash == 200000.0 == PAPER_START_CASH and st.as_of == DS[298] and not st.positions
    assert mod.main(["--date", DS[298].isoformat()]) == 0
    s = StateStore(tmp / "state" / "live_state.db")
    assert s.journal_count() == n and s.load().cash == 200000.0
    s.close()


def test_the_daily_job_runs_the_paper_step_only_after_a_successful_data_step(monkeypatch):
    job = load_script("daily_job")
    calls = []

    def fake(rc_by_script):
        def call(cmd):
            name = Path(cmd[1]).name
            calls.append((name, cmd[2:]))
            return rc_by_script[name]
        return call

    monkeypatch.setattr(job.subprocess, "call", fake({"daily_data_update.py": 3, "paper_run.py": 0}))
    assert job.main(["--scheduled"]) == 3 and calls == [("daily_data_update.py", ["--scheduled"])]
    calls.clear()
    monkeypatch.setattr(job.subprocess, "call", fake({"daily_data_update.py": 0, "paper_run.py": 0}))
    assert job.main(["--scheduled"]) == 0 and [c[0] for c in calls] == ["daily_data_update.py", "paper_run.py"]
    calls.clear()
    monkeypatch.setattr(job.subprocess, "call", fake({"daily_data_update.py": 0, "paper_run.py": 2}))
    assert job.main([]) == 2

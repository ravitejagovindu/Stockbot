"""db-guard R1/R4 on whole runs: manifests, INVALID, byte-identical reads (open_lake, the memory view, the ORM path), a backtest with and without the guard."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from stockbot.backtest.runner import run_backtest
from stockbot.data import guard
from stockbot.data.asof import AsOfView
from stockbot.data.asof_memory import MemoryAsOfView
from stockbot.data.guard import runcheck
from stockbot.data.lake import open_lake
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, EVENTS, policies
from tests.fixtures.lakefile import _make

ROOT = Path(__file__).resolve().parents[2]
DS = mini_lake.sessions()
SIG = DS[mini_lake.BREAKOUT]
POL = policies(FixedPolicy(id="timed", max_days=5))


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def side_files(p) -> dict:
    return {s: (Path(str(p) + s).stat().st_size if Path(str(p) + s).exists() else None) for s in ("-wal", "-shm")}


def strategy():
    return ScriptedStrategy(make_spec("dummy", "timed"), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": 150.0}]})


@pytest.fixture
def plain(tmp_path):
    p = tmp_path / "plain.db"
    _make(p)
    return p


@pytest.fixture
def guarded(tmp_path, plain):
    p = tmp_path / "guarded.db"
    shutil.copy(plain, p)
    con = sqlite3.connect(str(p), isolation_level=None)
    guard.install(con)
    con.close()
    return p


# -------------------------------------------------------------------------------------------------------------------- requirement a: reads leave the file byte-identical
@pytest.mark.parametrize("mode", ["delete", "wal"])
def test_open_lake_and_the_memory_view_leave_the_file_byte_identical(tmp_path, plain, mode):
    p = tmp_path / f"{mode}.db"
    shutil.copy(plain, p)
    if mode == "wal":
        c = sqlite3.connect(str(p))
        assert c.execute("pragma journal_mode=WAL").fetchone()[0] == "wal"
        c.close()
    header = Path(p).read_bytes()[:100]
    before = sha(p)
    conn = open_lake(p)
    AsOfView(conn, DS[300]).adjusted_bars("FIXCO")
    MemoryAsOfView(conn, DS[300]).adjusted_bars("FIXCO")
    conn.close()
    assert sha(p) == before and Path(p).read_bytes()[:100] == header
    # the side files: a read-only connection may create or touch -shm (it does not hold data); -wal must be absent or empty, otherwise the main file is not the whole database
    side = side_files(p)
    assert side["-wal"] in (None, 0)


def _orm_script(db: Path) -> str:
    return ("import os; os.environ['DATABASE_URL']=r'sqlite:///" + db.as_posix() + "'\n"
            "from sqlalchemy import text\nfrom stockbot.data.db.connection import get_session\n"
            "with get_session() as s:\n    print(s.execute(text('select count(*) from market_data_lake')).scalar())\n"
            "    s.execute(text('select * from corporate_actions_log')).fetchall()\n")


@pytest.mark.parametrize("mode", ["delete", "wal"])
def test_reading_through_the_orm_connection_path_leaves_the_file_byte_identical_and_keeps_its_journal_mode(tmp_path, plain, mode):
    p = tmp_path / f"orm_{mode}.db"
    shutil.copy(plain, p)
    if mode == "wal":
        c = sqlite3.connect(str(p))
        c.execute("pragma journal_mode=WAL")
        c.close()
    before, header = sha(p), Path(p).read_bytes()[:100]
    r = subprocess.run([sys.executable, "-c", _orm_script(p)], cwd=str(ROOT), capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0, r.stderr
    assert sha(p) == before, "the ORM engine changed the bytes of an existing database file"
    assert Path(p).read_bytes()[18:20] == header[18:20]                                      # journal-mode bytes (1,1 = rollback journal; 2,2 = WAL)
    assert side_files(p)["-wal"] in (None, 0)


def test_the_orm_engine_still_creates_new_files_in_wal_mode(tmp_path):
    p = tmp_path / "new.db"
    script = ("import os; os.environ['DATABASE_URL']=r'sqlite:///" + p.as_posix() + "'\n"
              "from sqlalchemy import text\nfrom stockbot.data.db.connection import get_session\n"
              "with get_session() as s:\n    s.execute(text('create table t(a)'))\n    s.execute(text('insert into t values (1)'))\n")
    r = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0, r.stderr
    assert Path(p).read_bytes()[18:20] == b"\x02\x02"


def test_the_staging_writer_and_the_orm_engine_do_not_switch_the_journal_mode_of_an_existing_file():
    for f in ("stockbot/data/db/connection.py", "stockbot/data/ingestion/ingest_raw_bhavcopy_range.py"):
        t = (ROOT / f).read_text(encoding="utf-8")
        i = t.index("journal_mode=WAL")
        assert "page_count" in t[max(0, i - 400):i], f


# -------------------------------------------------------------------------------------------------------------------- R1 / R4 on a backtest
def test_the_manifest_records_the_file_hashes_the_counter_the_sealed_dates_and_the_digests(guarded):
    r = run_backtest(guarded, DS[298], DS[300], 1_000_000.0, [strategy()], POL, CFG, EVENTS)
    m = r.manifest["db_check"]
    assert m["unchanged"] and m["file_sha256_before"] == m["file_sha256_after"] == sha(guarded) and len(m["file_sha256_before"]) == 64
    g = m["guard_before"]
    assert g["installed"] and g["correction_counter"] == 0 and g["window_open"] is False
    assert g["tables"]["market_data_lake"]["sealed_through"] == DS[-1].isoformat()
    assert g["tables"]["corporate_actions_log"]["row_count"] == 1 and len(g["tables"]["corporate_actions_log"]["sha256"]) == 64 and g["tables"]["corporate_actions_log"]["max_id"] == 1
    assert g == m["guard_after"]
    assert "full file sha256" in m["verified"]
    assert json.loads(json.dumps(r.manifest)) == r.manifest


def test_a_database_that_changes_during_the_run_makes_the_run_invalid(guarded, monkeypatch, capsys):
    import stockbot.backtest.runner as R
    real = R.decide
    state = {"n": 0}

    def decide_and_write(*a, **k):
        if state["n"] == 0:
            c = sqlite3.connect(str(guarded), isolation_level=None)
            c.execute("INSERT INTO corporate_actions_log(symbol,ex_date,action_type,ratio_numerator,ratio_denominator,source) VALUES ('LATE','2010-01-01','SPLIT',2,1,'t')")      # a late fact
            c.close()
        state["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(R, "decide", decide_and_write)
    with pytest.raises(SystemExit) as e:
        run_backtest(guarded, DS[298], DS[300], 1_000_000.0, [strategy()], POL, CFG, EVENTS)
    assert e.value.code == 3
    err = capsys.readouterr().err
    assert "RUN INVALID (backtest)" in err and "corporate_actions_log" in err and "sha256" in err


def test_a_correction_during_the_run_makes_it_invalid_through_the_counter(guarded, monkeypatch, capsys):
    import stockbot.backtest.runner as R
    real = R.decide
    done = {}

    def decide_and_correct(*a, **k):
        if not done:
            c = sqlite3.connect(str(guarded), isolation_level=None)
            guard.correct(c, "mid-run", "UPDATE market_data_lake SET close_raw=close_raw WHERE symbol='NOSUCH';")        # no row changes, but a window was opened: the counter moved
            c.close()
            done["x"] = 1
        return real(*a, **k)
    monkeypatch.setattr(R, "decide", decide_and_correct)
    with pytest.raises(SystemExit) as e:
        run_backtest(guarded, DS[298], DS[300], 1_000_000.0, [strategy()], POL, CFG, EVENTS)
    assert e.value.code == 3 and "correction_counter" in capsys.readouterr().err


def test_an_end_to_end_backtest_is_byte_identical_with_and_without_the_guard(plain, guarded):
    def run(path, view=None):
        r = run_backtest(path, DS[290], DS[-1], 1_000_000.0, [strategy()], POL, CFG, EVENTS)
        decisions = [(d.as_of, d.cash_after, tuple(d.exits), tuple(d.new_tickets)) for d in r.decisions]
        return repr((decisions, r.trades, sorted(r.equity_curve.items()), r.state, r.end_of_window_exits)), r.manifest
    a, ma = run(plain)
    b, mb = run(guarded)
    assert a == b
    ma, mb = dict(ma), dict(mb)
    for m in (ma, mb):
        m.pop("db_check")
        m["data_snapshot"] = {k: v for k, v in m["data_snapshot"].items() if k not in ("file", "size", "mtime_ns")}     # the two files differ by construction
    assert ma == mb
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


def test_the_sql_view_and_the_memory_view_agree_on_a_guarded_file(guarded, monkeypatch):
    conn = open_lake(guarded)
    for d in (DS[250], DS[300], DS[-1]):
        a, b = AsOfView(conn, d), MemoryAsOfView(conn, d)
        assert a.adjusted_bars("FIXCO").equals(b.adjusted_bars("FIXCO")) and a.sessions() == b.sessions()


def test_an_open_connection_run_compares_the_guard_record_only(guarded):
    conn = open_lake(guarded)
    r = run_backtest(conn, DS[298], DS[300], 1_000_000.0, [strategy()], POL, CFG, EVENTS)
    m = r.manifest["db_check"]
    assert m["file_sha256_before"] is None and m["unchanged"] and m["guard_before"]["installed"]
    assert r.manifest["data_snapshot"] is None


def test_manifests_written_before_the_guard_have_no_db_check_and_stay_valid():
    from stockbot.backtest.manifest import run_manifest
    m = run_manifest(shared_config=CFG, strategies=[strategy()], window=(DS[1], DS[2]), initial_equity=1.0)
    assert "db_check" not in m


def test_guard_state_tables_are_not_listed_among_the_tables_a_run_reads(guarded):
    r = run_backtest(guarded, DS[298], DS[299], 1e6, [strategy()], POL, CFG, EVENTS)
    assert not any(t.startswith("_guard") for t in r.manifest["db_check"]["guard_before"]["tables"])

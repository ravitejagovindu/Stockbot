"""stockbot.live.runner / scheduler / eod_cli (restructure Phase 9): mode gate, freshness check, no ingestion, separate state database, ticket files, idempotency."""
import ast
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from stockbot.backtest.no_network import network_forbidden
from stockbot.config.shared import load_shared_config
from stockbot.live import eod_cli, runner, scheduler
from stockbot.live.runner import Book, DataFreshnessError, ModeError, SurveillanceDataMissing, default_book, run_eod, strategies_for_mode
from stockbot.live.state_store import StateStore
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.lakefile import _make

DS = mini_lake.sessions()
SIG = DS[mini_lake.BREAKOUT]
G3_STOP = 159.115349
CFG = load_shared_config()
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake") / "lake.db"
    _make(p)
    return p


def strat(status="paper", sid="dummy", **kw):
    extra = {"validation_ref": "VAL-1"} if status == "live" else {}
    return ScriptedStrategy(make_spec(sid, status=status, **extra, **kw), {SIG.isoformat(): [{"symbol": "FIXCO", "stop": G3_STOP}]})


def book(*strategies):
    return Book(tuple(strategies), {"fixed": FixedPolicy()})


def go(tmp_path, lake, as_of, b=None, mode=None, **kw):
    store = StateStore(tmp_path / "state" / "live_state.db")
    try:
        return run_eod(cfg=CFG, book=b or book(strat()), as_of=as_of, store=store, lake=lake, out_dir=tmp_path / "tickets", mode=mode, **kw), store.journal_count()
    finally:
        store.close()


# ------------------------------------------------------------------ the mode gate
def test_paper_is_the_default_mode():
    assert CFG.runtime.mode == "PAPER"


def test_paper_runs_paper_and_live_strategies_but_never_research():
    b = book(strat("research", "a_res"), strat("paper", "b_pap"), strat("live", "c_liv"))
    assert [s.spec.id for s in strategies_for_mode(b, "PAPER")] == ["b_pap", "c_liv"]


def test_live_needs_a_strategy_with_status_live_and_a_validation_ref():
    with pytest.raises(ModeError, match="status 'live'"):
        strategies_for_mode(default_book(), "LIVE")
    with pytest.raises(ModeError):
        strategies_for_mode(book(strat("paper")), "LIVE")                                             # a paper strategy is not enough
    assert [s.spec.id for s in strategies_for_mode(book(strat("paper", "a_pap"), strat("live", "b_liv")), "LIVE")] == ["b_liv"]
    from stockbot.strategies.spec import SpecError
    with pytest.raises(SpecError):
        make_spec("x", status="live")                                                                 # the spec itself refuses 'live' without a validation_ref
    with pytest.raises(ModeError):
        strategies_for_mode(default_book(), "SIMULATED")


def test_the_default_book_is_empty_so_nothing_runs_without_a_strategy():
    assert default_book().strategies == ()


# ------------------------------------------------------------------ freshness, ingestion, state database
def test_a_date_the_lake_does_not_hold_yet_is_refused_and_nothing_is_written(tmp_path, lake):
    store = StateStore(tmp_path / "s.db")
    with pytest.raises(DataFreshnessError, match="ingestion"):
        run_eod(cfg=CFG, book=book(strat()), as_of=DS[329] + timedelta(days=3), store=store, lake=lake, out_dir=tmp_path / "t")
    assert store.journal_count() == 0 and not (tmp_path / "t").exists()


def test_the_runner_does_not_ingest_or_use_the_network(tmp_path, lake):
    for mod in (runner, scheduler, eod_cli):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        names = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None]) if True}
        flat = " ".join(str(x) for x in names)
        assert "ingestion" not in flat and "requests" not in flat and "yfinance" not in flat, (mod.__name__, flat)
    with network_forbidden():
        go(tmp_path, lake, DS[299])


def test_state_goes_to_its_own_database_and_the_lake_is_untouched(tmp_path, lake):
    h = lambda: hashlib.sha256(lake.read_bytes()).hexdigest()
    before = h()
    go(tmp_path, lake, DS[298])
    go(tmp_path, lake, DS[300])
    assert h() == before and (tmp_path / "state" / "live_state.db").exists() and (tmp_path / "state" / "live_state.db") != lake
    con = sqlite3.connect(tmp_path / "state" / "live_state.db")
    assert {r[0] for r in con.execute("select name from sqlite_master where type='table'")} >= {"meta", "journal", "snapshot"}


# ------------------------------------------------------------------ tickets and idempotency
def test_tickets_are_written_as_a_file_per_session(tmp_path, lake):
    go(tmp_path, lake, DS[298])
    res, _ = go(tmp_path, lake, SIG)
    f = tmp_path / "tickets" / f"tickets_{SIG.isoformat()}.json"
    assert [Path(p) for p in res.ticket_files] == [tmp_path / "tickets" / f"tickets_{DS[299].isoformat()}.json", f]            # the missed session is processed too
    body = json.loads(f.read_text(encoding="utf-8"))
    (t,) = body["tickets"]
    assert (t["symbol"], t["stop"], t["strategy_id"], t["signal_date"]) == ("FIXCO", G3_STOP, "dummy", SIG.isoformat()) and "Nothing is sent to any broker" in body["note"]
    assert not list((tmp_path / "tickets").glob("*.tmp"))


def test_running_the_same_date_twice_changes_nothing(tmp_path, lake):
    go(tmp_path, lake, DS[298])
    r1, n1 = go(tmp_path, lake, SIG)
    snap = {p.name: p.read_bytes() for p in (tmp_path / "tickets").iterdir()}
    r2, n2 = go(tmp_path, lake, SIG)
    assert r2.decisions == () and n1 == n2 and {p.name: p.read_bytes() for p in (tmp_path / "tickets").iterdir()} == snap


def test_a_fresh_state_database_starts_with_the_configured_paper_equity(tmp_path, lake):
    store = StateStore(tmp_path / "s.db")
    run_eod(cfg=CFG, book=book(), as_of=DS[298], store=store, lake=lake, out_dir=tmp_path / "t")
    assert store.load().cash == CFG.runtime.paper_start_equity and store.load().as_of == DS[298]


# ------------------------------------------------------------------ surveillance data
def test_live_fails_closed_without_an_asm_gsm_snapshot_and_paper_continues(tmp_path, lake):
    b = book(strat("live"))
    with pytest.raises(SurveillanceDataMissing):
        go(tmp_path, lake, DS[298], b=b, mode="LIVE")
    res, _ = go(tmp_path / "paper", lake, DS[298], b=book(strat("paper")), mode="PAPER")
    assert res.asm_data is False


def test_symbols_in_todays_asm_gsm_snapshot_are_not_eligible(tmp_path):
    p = tmp_path / "lake.db"
    _make(p)
    con = sqlite3.connect(p)
    con.execute("create table asm_gsm_daily_snapshot (snapshot_date TEXT NOT NULL, framework TEXT NOT NULL, symbol TEXT NOT NULL, isin TEXT, company_name TEXT, stage TEXT, surv_code TEXT, "
                "surv_desc TEXT, nse_time TEXT, srno INTEGER, fetched_at TEXT NOT NULL, PRIMARY KEY (snapshot_date, framework, symbol))")
    con.execute("insert into asm_gsm_daily_snapshot (snapshot_date, framework, symbol, fetched_at) values (?, 'ASM', 'FIXCO', 'x')", (SIG.isoformat(),))
    con.commit(); con.close()
    s = strat("paper")
    go(tmp_path, p, DS[299], b=book(s))
    res, _ = go(tmp_path, p, SIG, b=book(s))
    assert res.asm_data is True and "FIXCO" not in s.seen_eligible[SIG.isoformat()] and not [t for d in res.decisions for t in d.new_tickets]


# ------------------------------------------------------------------ scheduler and command line
def test_scheduler_job_survives_a_refusal_and_runs_when_data_is_there(tmp_path, lake, monkeypatch):
    monkeypatch.setenv("STOCKBOT_DB", str(lake))
    monkeypatch.setenv("STOCKBOT_STATE_DB", str(tmp_path / "st" / "s.db"))
    monkeypatch.setenv("STOCKBOT_TICKETS_DIR", str(tmp_path / "tk"))
    alerts = []
    monkeypatch.setattr(scheduler, "_send_failure_alert", lambda d, e: alerts.append((d, e)))
    assert scheduler.run_eod_job(today=date(2030, 1, 4)) is None and len(alerts) == 1 and "ingestion" in alerts[0][1]
    res = scheduler.run_eod_job(today=DS[299])
    assert res is not None and res.mode == "PAPER" and res.decisions and len(alerts) == 1


def test_command_line_exit_codes(tmp_path, lake, monkeypatch, capsys):
    monkeypatch.setenv("STOCKBOT_DB", str(lake))
    monkeypatch.setenv("STOCKBOT_STATE_DB", str(tmp_path / "s.db"))
    monkeypatch.setenv("STOCKBOT_TICKETS_DIR", str(tmp_path / "tk"))
    assert eod_cli.main(["--date", DS[299].isoformat()]) == 0
    assert eod_cli.main(["--date", DS[299].isoformat(), "--mode", "LIVE"]) == 2 and "REFUSED" in capsys.readouterr().out
    assert eod_cli.main(["--date", "2031-01-02"]) == 2

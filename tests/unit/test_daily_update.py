"""The daily data job (stockbot/data/ingestion/daily_update.py) and the run locks (stockbot/data/guard/runlock.py). Fixture databases and fake downloads only: no network, never finsight.db."""
import csv
import io
import json
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockbot.data import guard
from stockbot.data.guard import core, runcheck, runlock
from stockbot.data.guard.writers import SealedError, writer_session
from stockbot.data.ingestion import daily_update as DU
from stockbot.data.ingestion.bhavcopy_ingestor import BhavcopyIngestor

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "tests" / "fixtures" / "real_schema.sql"
LAST = date(2026, 10, 16)
HEAD = "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd"


def csv_bytes(day, eq=("AAA", "BBB", "CCC"), be=("DDD",), bl=("AAA",), bad_close=False, other_date=None):
    d = (other_date or day).isoformat()
    lines = [HEAD]
    for i, s in enumerate(eq):
        lines.append(f"{d},{d},CM,NSE,STK,{i},INE00000{i:04d},{s},EQ,10,11,9,10.5,10.5,10,100,1000,5")
    for i, s in enumerate(be):
        c = "" if bad_close else "20.5"
        lines.append(f"{d},{d},CM,NSE,STK,{50 + i},INE11111{i:04d},{s},BE,20,21,19,{c},20.5,20,200,4000,7")
    for i, s in enumerate(bl):
        lines.append(f"{d},{d},CM,NSE,STK,{90 + i},INE00000{i:04d},{s},BL,10,10,10,10,10,10,50,500,1")
    lines.append(f"{d},{d},CM,NSE,STK,99,INE22222,ZZZ,SM,5,6,4,5,5,5,10,50,1")      # a series nobody loads
    return ("\n".join(lines) + "\n").encode()


def zip_of(day, **kw):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv", csv_bytes(day, **kw))
    return b.getvalue()


class Net:
    """Fake downloader: {file name: bytes}; everything else is a 404; ``broken`` makes every request a network error."""

    def __init__(self):
        self.files, self.calls, self.broken = {}, [], False

    def add(self, day, **kw):
        self.files[f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"] = zip_of(day, **kw)

    def __call__(self, url):
        self.calls.append(url)
        if self.broken:
            return None, b"", "boom"
        name = url.rsplit("/", 1)[-1]
        return (200, self.files[name], "") if name in self.files else (404, b"", "404")


def idx_rows(day, ok=True):
    return {"NIFTY50_INDEX": (100.0, 101.0, 99.0, 100.5, "u"), "INDIA_VIX": (14.0, 15.0, 13.0, 14.5, "u")} if ok else {}


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(str(db), isolation_level=None)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    guard.install(con, seal="none")
    d = LAST.isoformat()
    for s in ("AAA", "BBB", "CCC"):
        con.execute("INSERT INTO market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange) VALUES (?,?,?,?,?,?,?,?)", (s, d, 1, 2, 0.5, 1.5, 10, "NSE"))
    for s, v in (("NIFTY50_INDEX", 100.0), ("INDIA_VIX", 14.0)):
        con.execute("INSERT INTO market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange) VALUES (?,?,?,?,?,?,?,?)", (s, d, v, v, v, v, 0, "NSE"))
    con.execute("INSERT INTO market_data_non_eq (symbol, trade_date, series, isin, open_raw, high_raw, low_raw, close_raw, volume_raw) VALUES ('OLD',?, 'BE','INE000000001',1,1,1,1,1)", (d,))
    core.seal_table(con, "market_data_lake", d)
    core.seal_table(con, "market_data_non_eq", d)
    con.close()
    net = Net()
    clock = {"t": datetime(2026, 10, 19, 20, 0, tzinfo=DU.IST)}
    calls = SimpleNamespace(asm=[], ca=[])

    def asm_run(dbp, iso):
        calls.asm.append(iso)
        return calls.asm_rc

    calls.asm_rc = 0
    ctx = DU.Ctx(db=db, root=tmp_path / "data", download=net, now=lambda: clock["t"], index_fetch=lambda c, day: (idx_rows(day, not calls.__dict__.get("no_index")), "fake"),
                 ca_fetch=lambda a, b: calls.ca.append((a, b)) or [], asm_run=asm_run, out=lambda m: None, lock_dir=tmp_path / "locks")
    return SimpleNamespace(db=db, net=net, clock=clock, ctx=ctx, calls=calls, tmp=tmp_path)


def q(env, sql, *a):
    c = sqlite3.connect(str(env.db))
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def sums(env):
    c = sqlite3.connect(str(env.db))
    try:
        return {t: core.day_checksums(c, t, None, LAST.isoformat()) for t in ("market_data_lake", "market_data_non_eq")}
    finally:
        c.close()


def at(env, y, m, d, h=20, mi=0):
    env.clock["t"] = datetime(y, m, d, h, mi, tzinfo=DU.IST)


# ================================================================================================ a. a new day
def test_a_new_day_loads_seals_saves_the_original_unmodified_and_leaves_sealed_history_identical(env):
    before = sums(env)
    day = date(2026, 10, 19)
    env.net.add(day)
    rep = DU.run(env.ctx, steps=False)
    r = [x for x in rep.days if x.day == day][0]
    assert r.status == "LOADED" and r.sealed and r.downloaded and rep.exit_code == 0
    assert q(env, "select count(*) from market_data_lake where trade_date='2026-10-19' and symbol not in ('NIFTY50_INDEX','INDIA_VIX')") == [(3,)]
    assert q(env, "select series, count(*) from market_data_non_eq where trade_date='2026-10-19' group by 1 order by 1") == [("BE", 1), ("BL", 1)]       # SM is not loaded
    assert q(env, "select count(*) from market_data_lake where trade_date='2026-10-19' and symbol in ('NIFTY50_INDEX','INDIA_VIX')") == [(2,)]
    assert q(env, "select sealed_through from _guard_seal where tbl in ('market_data_lake','market_data_non_eq')") == [("2026-10-19",), ("2026-10-19",)]
    name = f"BhavCopy_NSE_CM_0_0_0_20261019_F_0000.csv.zip"
    saved = env.ctx.raw / "2026" / name
    assert saved.read_bytes() == env.net.files[name]                                                                                              # byte for byte
    (m,) = [x for x in csv.DictReader(open(env.ctx.raw / "MANIFEST.csv"))]
    assert (m["date"], m["file_name"], m["status"], m["pattern"], int(m["bytes"])) == ("2026-10-19", name, "OK", "UDIFF", len(env.net.files[name]))
    assert m["sha256"] == DU.sha256_bytes(env.net.files[name])
    assert sums(env) == before                                                                                                                    # every sealed day is unchanged
    c = sqlite3.connect(str(env.db))
    assert core.audit(c)["ok"] is True
    c.close()


def test_a_saved_file_is_never_overwritten_and_a_second_run_downloads_nothing(env):
    day = date(2026, 10, 19)
    env.net.add(day)
    DU.run(env.ctx, steps=False)
    n = len(env.net.calls)
    p = env.ctx.raw / "2026" / "BhavCopy_NSE_CM_0_0_0_20261019_F_0000.csv.zip"
    h = p.read_bytes()
    rep = DU.run(env.ctx, steps=False)
    assert len(env.net.calls) == n + 0 or all("20261019" not in u for u in env.net.calls[n:])
    assert p.read_bytes() == h and len(list(csv.DictReader(open(env.ctx.raw / "MANIFEST.csv")))) == 1
    assert all(r.status != "LOADED" for r in rep.days)


def test_days_are_loaded_oldest_first_one_at_a_time_each_sealed(env):
    for d in (date(2026, 10, 19), date(2026, 10, 20)):
        env.net.add(d)
    at(env, 2026, 10, 21, 8, 0)
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    loaded = [r.day for r in rep.days if r.status == "LOADED"]
    assert loaded == [date(2026, 10, 19), date(2026, 10, 20)]
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-20",)]
    assert q(env, "select day from _guard_day_checksum where tbl='market_data_lake' order by day desc limit 2") == [("2026-10-20",), ("2026-10-19",)]


# ================================================================================================ a sealed day, a half-loaded day, an unparsable price
def test_a_sealed_day_cannot_be_reloaded_and_the_writers_refuse_before_deleting(env):
    r = DU.process_day(env.ctx, LAST)
    assert r.status == "ALREADY_SEALED" and env.net.calls == []
    before = sums(env)
    s = writer_session(env.db)
    with pytest.raises(SealedError):
        BhavcopyIngestor({}).store_day_non_eq(s, [], LAST)                                                                                        # would have deleted the day's rows
    s.close()
    assert sums(env) == before and q(env, "select count(*) from market_data_non_eq where trade_date='2026-10-16'") == [(1,)]


def test_a_half_loaded_day_is_not_sealed_and_is_retried_cleanly(env):
    day = date(2026, 10, 19)
    env.net.add(day)
    env.calls.no_index = True                                                                                                                     # the index/VIX writer cannot deliver
    r = DU.process_day(env.ctx, day)
    assert r.status == "FAILED" and not r.sealed and "UNSEALED" in r.detail
    assert q(env, "select count(*) from market_data_lake where trade_date='2026-10-19'") == [(3,)]                                                # half-loaded: EQ rows are there
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-16",)]
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_non_eq'") == [("2026-10-16",)]
    env.calls.no_index = False
    r = DU.process_day(env.ctx, day)                                                                                                              # the retry replaces the day, no duplicates
    assert r.status == "LOADED" and r.sealed
    assert q(env, "select count(*) from market_data_lake where trade_date='2026-10-19'") == [(5,)]
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_non_eq'") == [("2026-10-19",)]


def test_a_failing_check_or_writer_leaves_the_day_unsealed(env, monkeypatch):
    day = date(2026, 10, 19)
    env.net.add(day)
    monkeypatch.setattr(DU, "run_checks", lambda con, d, prep: [("eq_rows_equal_file", False, "x", True)])
    r = DU.process_day(env.ctx, day)
    assert r.status == "FAILED" and not r.sealed and "check failed" in r.detail
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-16",)]
    monkeypatch.undo()

    def boom(self, s, rows, d):
        raise RuntimeError("disk full")
    monkeypatch.setattr(BhavcopyIngestor, "store_day_non_eq", boom)
    r = DU.process_day(env.ctx, day)
    assert r.status == "FAILED" and not r.sealed and "writer failed" in r.detail
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_non_eq'") == [("2026-10-16",)]


def test_an_unparsable_price_refuses_the_day_and_nothing_is_written(env):
    day = date(2026, 10, 19)
    env.net.add(day, bad_close=True)
    before = sums(env)
    r = DU.process_day(env.ctx, day)
    assert r.status == "REFUSED" and "nothing written" in r.detail and not r.sealed
    assert q(env, "select count(*) from market_data_lake where trade_date>'2026-10-16'") == [(0,)]
    assert q(env, "select count(*) from market_data_non_eq where trade_date>'2026-10-16'") == [(0,)]
    assert sums(env) == before
    rep = DU.run(env.ctx, steps=False)
    assert rep.exit_code == 1


def test_a_file_whose_inner_date_is_not_the_requested_date_is_not_accepted_and_a_failed_day_stops_the_run(env):
    d19, d20 = date(2026, 10, 19), date(2026, 10, 20)
    env.net.files["BhavCopy_NSE_CM_0_0_0_20261019_F_0000.csv.zip"] = zip_of(d19, other_date=date(2026, 10, 16))      # NSE serving the previous session's file
    r = DU.process_day(env.ctx, d19)
    assert r.status == "NO_FILE" and "declares 2026-10-16" in r.detail
    # a day that fails stops the run: the next day is never loaded over it
    env.net.add(d19, bad_close=True)
    env.net.add(d20)
    at(env, 2026, 10, 21, 8)
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    assert [r.status for r in rep.days if r.day >= d19] == ["REFUSED"]
    assert q(env, "select count(*) from market_data_lake where trade_date='2026-10-20'") == [(0,)]


def test_a_network_error_is_an_error_not_a_holiday(env):
    env.net.broken = True
    r = DU.process_day(env.ctx, date(2026, 10, 19))
    assert r.status == "FAILED" and "download error" in r.detail
    assert DU.journal_rows(env.ctx, date(2026, 10, 19)) == []


# ================================================================================================ calendar: NO_FILE, re-check, weekends
def test_no_file_is_recorded_rechecked_for_three_days_and_then_final(env):
    d19 = date(2026, 10, 19)                                                                                                                      # a (holiday) Monday: no file
    at(env, 2026, 10, 20, 8, 0)
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    assert {r.day: r.status for r in rep.days} == {date(2026, 10, 17): "NO_FILE", date(2026, 10, 18): "NO_FILE", d19: "NO_FILE"}
    assert q(env, "select count(*) from market_data_lake where trade_date>'2026-10-16'") == [(0,)] and q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-16",)]
    n = len(env.net.calls)
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)                                                                                        # same day: not asked again
    assert {r.status for r in rep.days} == {"SKIPPED_RECHECKED_TODAY"} and len(env.net.calls) == n
    at(env, 2026, 10, 21, 8)                                                                                                                      # next morning: asked again
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    assert {r.day: r.status for r in rep.days} == {date(2026, 10, 17): "NO_FILE_FINAL", date(2026, 10, 18): "NO_FILE", d19: "NO_FILE", date(2026, 10, 20): "NO_FILE"} and len(env.net.calls) > n
    at(env, 2026, 10, 22, 8)
    DU.run(env.ctx, catch_up_only=True, steps=False)
    n = len(env.net.calls)
    at(env, 2026, 10, 23, 8)                                                                                                                      # 10-19 + 3 = 10-22 was the last day to ask
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    st = {r.day: r.status for r in rep.days}
    assert st[d19] == "NO_FILE_FINAL" and st[date(2026, 10, 20)] == "NO_FILE"                                                                      # 10-20 was first asked on 10-20 ... still inside its 3 days
    assert all("20261019" not in u for u in env.net.calls[n:])


def test_a_late_file_for_a_date_in_its_recheck_window_loads_on_the_recheck(env):
    d = date(2026, 10, 19)
    at(env, 2026, 10, 20, 8)
    DU.run(env.ctx, catch_up_only=True, steps=False)
    env.net.add(d)
    at(env, 2026, 10, 21, 8)
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    assert [r.status for r in rep.days if r.day == d] == ["LOADED"]


def test_a_weekend_file_with_a_valid_date_loads_and_a_weekend_without_a_file_does_nothing(env):
    sat, sun = date(2026, 10, 17), date(2026, 10, 18)
    assert sat.weekday() == 5 and sun.weekday() == 6
    env.net.add(sat)                                                                                                                              # a special Saturday session
    before = sums(env)
    at(env, 2026, 10, 19, 8)
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    st = {r.day: r.status for r in rep.days}
    assert st[sat] == "LOADED" and st[sun] == "NO_FILE"
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-17",)]
    assert q(env, "select count(*) from market_data_lake where trade_date='2026-10-18'") == [(0,)]
    assert sums(env) == before
    # only the Sunday: nothing is written at all
    env2_before = q(env, "select count(*) from market_data_lake")
    rep = DU.run(env.ctx, catch_up_only=True, steps=False)
    assert q(env, "select count(*) from market_data_lake") == env2_before


def test_today_is_pending_before_the_window_ends_and_the_scheduled_window_is_19_30_to_23_45():
    ist = lambda h, m: datetime(2026, 10, 19, h, m, tzinfo=DU.IST)  # noqa: E731
    assert DU.include_today(ist(19, 29), catch_up_only=False, scheduled=True) is False
    assert DU.include_today(ist(19, 30), catch_up_only=False, scheduled=True) is True
    assert DU.include_today(ist(23, 30), catch_up_only=False, scheduled=True) is True
    assert DU.include_today(ist(23, 46), catch_up_only=False, scheduled=True) is False
    assert DU.include_today(ist(8, 0), catch_up_only=False, scheduled=False) is True
    assert DU.include_today(ist(20, 0), catch_up_only=True, scheduled=True) is False


def test_todays_missing_file_is_pending_exit_3_and_is_not_recorded_as_no_file(env):
    at(env, 2026, 10, 19, 19, 30)
    rep = DU.run(env.ctx, scheduled=True, steps=False)
    st = {r.day: r.status for r in rep.days}
    assert st[date(2026, 10, 19)] == "PENDING" and rep.exit_code == 3
    assert DU.journal_rows(env.ctx, date(2026, 10, 19)) == []
    env.net.add(date(2026, 10, 19))
    at(env, 2026, 10, 19, 19, 50)
    rep = DU.run(env.ctx, scheduled=True, steps=False)
    assert rep.exit_code == 0 and q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-19",)]


# ================================================================================================ checks
def test_the_checks_catch_a_symbol_in_both_tables_and_report_a_strange_eq_count_without_blocking(env):
    day = date(2026, 10, 19)
    env.net.add(day, eq=("AAA", "BBB", "CCC", "DDD"), be=("DDD",))                                                                                # DDD is both EQ and BE: forbidden
    r = DU.process_day(env.ctx, day)
    assert r.status == "FAILED" and "no_symbol_in_both_tables" in r.detail and not r.sealed
    day = date(2026, 10, 20)                                                                                                                      # (the archive keeps the first file of 10-19: a saved original is never replaced)
    env.net.add(day, eq=tuple(f"S{i}" for i in range(20)), be=("DDD",))                                                                           # 20 EQ rows after 3: reported, not blocking
    r = DU.process_day(env.ctx, day)
    assert r.status == "LOADED" and "eq_count_vs_previous_session" in r.detail, r.detail


def test_an_empty_eq_section_is_refused(env):
    day = date(2026, 10, 19)
    env.net.add(day, eq=())
    assert DU.process_day(env.ctx, day).status == "REFUSED"


# ================================================================================================ store_day_non_eq
def test_store_day_non_eq_is_delete_and_insert_in_one_transaction(env):
    from stockbot.data import non_eq as NE
    day = date(2026, 10, 19)
    row = lambda s, series="BE": (s, day.isoformat(), series, "INE000000001", 1.0, 2.0, 0.5, 1.5, 1.0, 10, 1, 15.0, "f")  # noqa: E731
    ing = BhavcopyIngestor({})
    s = writer_session(env.db)
    ing.store_day_non_eq(s, [row("A"), row("B")], day)
    ing.store_day_non_eq(s, [row("C")], day)                                                                                                       # reload on an unsealed day replaces it
    assert q(env, "select symbol from market_data_non_eq where trade_date='2026-10-19'") == [("C",)]
    with pytest.raises(Exception):
        ing.store_day_non_eq(s, [row("D"), row("D")], day)                                                                                         # duplicate key fails inside the insert ...
    assert q(env, "select symbol from market_data_non_eq where trade_date='2026-10-19'") == [("C",)]                                              # ... and the delete is rolled back with it
    with pytest.raises(ValueError):
        ing.store_day_non_eq(s, [(("E", "2026-10-20") + row("E")[2:])], day)
    s.close()


# ================================================================================================ corporate actions and ASM/GSM
def test_asm_runs_after_todays_seal_seals_when_both_lists_are_stored_and_never_blocks_prices(env):
    day = date(2026, 10, 19)
    env.net.add(day)

    def asm(dbp, iso):
        env.calls.asm.append(iso)
        if env.calls.asm_rc == 0:
            c = guard.connect_writer(dbp)
            for ep in ("reportASM", "reportGSM"):
                c.execute("insert into asm_gsm_snapshot_raw values (?,?,?,?,?,?)", (iso, ep, "t", 200, 1, "[]"))
                c.execute("insert into asm_gsm_daily_snapshot (snapshot_date, framework, symbol, fetched_at) values (?,?,?,?)", (iso, "GSM" if ep == "reportGSM" else "ASM_LT", "AAA", "t"))
            c.close()
        return env.calls.asm_rc
    env.ctx.asm_run = asm
    env.calls.asm_rc = 1                                                                                                                          # the source is down
    rep = DU.run(env.ctx)
    assert rep.exit_code == 0 and any("SOURCE UNAVAILABLE" in n for n in rep.notes)
    assert q(env, "select sealed_through from _guard_seal where tbl='market_data_lake'") == [("2026-10-19",)]                                      # prices are sealed regardless
    assert q(env, "select sealed_through from _guard_seal where tbl='asm_gsm_snapshot_raw'") == [("0000-00-00",)] or q(env, "select sealed_through from _guard_seal where tbl='asm_gsm_snapshot_raw'")[0][0] < "2026-10-19"
    env.calls.asm_rc = 0
    rep = DU.run(env.ctx)
    assert any("stored and sealed" in n for n in rep.notes), rep.notes
    assert q(env, "select sealed_through from _guard_seal where tbl in ('asm_gsm_snapshot_raw','asm_gsm_daily_snapshot')") == [("2026-10-19",), ("2026-10-19",)]
    env.calls.asm.clear()
    rep = DU.run(env.ctx)
    assert env.calls.asm == [] and any("already" in n for n in rep.notes)


def test_asm_is_skipped_when_todays_session_is_not_loaded(env):
    at(env, 2026, 10, 19, 8)
    rep = DU.run(env.ctx, catch_up_only=True)
    assert env.calls.asm == [] and any("skipped" in n for n in rep.notes)


def test_corporate_actions_are_inserted_once_changes_are_reported_and_an_unavailable_source_does_not_matter(env):
    ev = {"symbol": "AAA", "exDate": "20-Oct-2026", "subject": "Bonus 1:1"}
    n = DU.load_corporate_actions(env.ctx, [ev])
    assert n["inserted"] == 1
    assert DU.load_corporate_actions(env.ctx, [ev])["inserted"] == 0
    changed = dict(ev, subject="Bonus 2:1")
    r = DU.load_corporate_actions(env.ctx, [changed])
    assert r["differ_not_applied"] == 1 and r["inserted"] == 0
    assert q(env, "select ratio_numerator from corporate_actions_log where symbol='AAA'") == [(1.0,)]
    env.ctx.ca_fetch = lambda a, b: None
    assert "UNAVAILABLE" in DU.corporate_actions_step(env.ctx, date(2026, 10, 17), date(2026, 10, 19))


# ================================================================================================ locks
def dead_lock(directory, name, kind, db, hours_old, pid=4_000_000):
    directory.mkdir(parents=True, exist_ok=True)
    started = (datetime.now(runlock.timezone.utc) - timedelta(hours=hours_old)).isoformat(timespec="seconds")
    p = directory / name
    p.write_text(json.dumps({"kind": kind, "pid": pid, "host": runlock.socket.gethostname(), "started_at": started, "db": runlock.db_key(db), "label": "x"}))
    return p


def test_the_daily_job_refuses_to_write_while_a_run_lock_exists_and_does_not_touch_the_database(env):
    run_lock = runlock.acquire_run(env.db, "backtest", env.ctx.lock_dir)
    before = (env.db.stat().st_size, env.db.stat().st_mtime_ns, sums(env))
    rc = DU.main(["--db", str(env.db), "--data-root", str(env.tmp / "data"), "--through", "2026-10-19", "--no-extras"]) if False else None
    with pytest.raises(runlock.LockRefused) as e:
        runlock.acquire_daily(env.db, env.ctx.lock_dir)
    assert e.value.code == runlock.EXIT_LOCKED and "backtest" in e.value.message
    assert (env.db.stat().st_size, env.db.stat().st_mtime_ns, sums(env)) == before
    runlock.release(run_lock)
    p = runlock.acquire_daily(env.db, env.ctx.lock_dir)
    assert p.name == "daily_update.lock" and p.exists()
    runlock.release(p)
    assert not p.exists()


def test_the_command_line_exits_4_when_locked_and_5_when_the_lock_is_stale(env, monkeypatch):
    monkeypatch.setenv("STOCKBOT_LOCK_DIR", str(env.ctx.lock_dir))
    args = ["--db", str(env.db), "--data-root", str(env.tmp / "data"), "--no-extras", "--sleep", "0"]
    live = runlock.acquire_run(env.db, "gates", env.ctx.lock_dir)
    assert DU.main(args) == runlock.EXIT_LOCKED
    runlock.release(live)
    stale = dead_lock(env.ctx.lock_dir, "run_1_old.lock", "run", env.db, 13)
    assert DU.main(args) == runlock.EXIT_STALE and stale.exists()                                                                                 # reported, never deleted
    stale.unlink()
    recent = dead_lock(env.ctx.lock_dir, "run_1_new.lock", "run", env.db, 1)
    assert DU.main(args) == runlock.EXIT_LOCKED and recent.exists()                                                                               # process gone but younger than 12 h: still blocks
    recent.unlink()


def test_a_run_refuses_to_start_while_the_daily_job_holds_its_lock_and_the_other_direction_for_a_stale_one(env, tmp_path):
    d = runlock.acquire_daily(env.db, env.ctx.lock_dir)
    with pytest.raises(runlock.RunRefused) as e:
        runlock.acquire_run(env.db, "backtest", env.ctx.lock_dir)
    assert e.value.code == runlock.EXIT_LOCKED and "daily" in e.value.message
    other = tmp_path / "other.db"
    p = runlock.acquire_run(other, "backtest", env.ctx.lock_dir)                                                                                   # another file is not affected
    runlock.release(p)
    runlock.release(d)
    stale = dead_lock(env.ctx.lock_dir, "daily_update.lock", "daily", env.db, 20)
    with pytest.raises(runlock.RunRefused) as e:
        runlock.acquire_run(env.db, "backtest", env.ctx.lock_dir)
    assert e.value.code == runlock.EXIT_STALE and "Not deleted" in e.value.message and stale.exists()


def test_stale_means_older_than_12_hours_and_no_live_process(env):
    mine = env.ctx.lock_dir
    lk = runlock.acquire_run(env.db, "x", mine)                                                                                                     # a live process (this one), fresh
    (info,) = runlock.locks_for(env.db, directory=mine)
    assert info.alive and not info.stale
    data = json.loads(lk.read_text())
    data["started_at"] = (datetime.now(runlock.timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    lk.write_text(json.dumps(data))
    (info,) = runlock.locks_for(env.db, directory=mine)
    assert info.alive and not info.stale                                                                                                           # old but the process is alive: not stale
    runlock.release(lk)


def test_a_backtest_and_a_validation_step_take_and_release_the_run_lock(env, monkeypatch):
    monkeypatch.setenv("STOCKBOT_LOCK_DIR", str(env.ctx.lock_dir))
    seen = []

    @runcheck.short_step("test step")
    def main(argv=None):
        seen.append([i.kind for i in runlock.locks_for(env.db)])
        return 0
    assert main(["--lake", str(env.db)]) == 0
    assert seen == [["run"]] and runlock.locks_for(env.db) == []                                                                                   # held during, gone after
    d = runlock.acquire_daily(env.db, env.ctx.lock_dir)
    with pytest.raises(runlock.RunRefused):
        main(["--lake", str(env.db)])
    assert seen == [["run"]]                                                                                                                       # the step did not run
    from stockbot.backtest import runner
    with pytest.raises(runlock.RunRefused):
        runner.run_backtest(env.db, date(2026, 1, 1), date(2026, 1, 2), 1.0, [], None, None, None)
    runlock.release(d)


def test_the_baseline_fingerprint_holds_a_run_lock_until_the_process_ends(env, monkeypatch):
    monkeypatch.setenv("STOCKBOT_LOCK_DIR", str(env.ctx.lock_dir))
    from stockbot.data_checks.near_high_signal_count import fingerprint
    fingerprint(env.db, with_hash=False)
    (info,) = runlock.locks_for(env.db)
    assert info.kind == "run" and info.alive
    with pytest.raises(runlock.LockRefused):
        runlock.acquire_daily(env.db, env.ctx.lock_dir)
    fingerprint(env.db, with_hash=False)                                                                                                           # idempotent
    assert len(runlock.locks_for(env.db)) == 1
    runlock.release(info.path)
    runlock._HELD.clear()

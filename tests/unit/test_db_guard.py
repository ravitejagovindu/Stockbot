"""The database guard (stockbot/data/guard): sealed history, insert-only tables, logged corrections, audit, run-time checks. Fixture databases only (the real schema, no data)."""
import os
import re
import sqlite3
from pathlib import Path

import pytest

from stockbot.data import guard
from stockbot.data.guard import core, runcheck
from stockbot.data.guard.registry import BACKTEST_READS, DATED, EXEMPT, INSERT_ONLY, NOT_IN_THE_REAL_FILE, RULES

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "tests" / "fixtures" / "real_schema.sql"
MDL = "INSERT INTO market_data_lake(symbol,trade_date,open_raw,high_raw,low_raw,close_raw,volume_raw,source) VALUES (?,?,?,?,?,?,?,?)"
CA = "INSERT INTO corporate_actions_log(symbol,ex_date,action_type,ratio_numerator,ratio_denominator,notes,source) VALUES (?,?,?,?,?,?,?)"


def make_db(tmp_path, name="g.db", *, install=True):
    p = tmp_path / name
    con = sqlite3.connect(str(p), isolation_level=None)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    for d in ("2020-01-01", "2020-01-02", "2020-01-03"):
        for s in ("AAA", "BBB"):
            con.execute(MDL, (s, d, 1.0, 2.0, 0.5, 1.5, 100, "t"))
    con.execute(CA, ("AAA", "2020-01-02", "SPLIT", 5, 1, "first", "t"))
    con.execute(CA, ("BBB", "2020-01-03", "BONUS", 1, 1, "second", "t"))
    if install:
        guard.install(con)
    return p, con


def refused(con, sql, args=()):
    with pytest.raises(sqlite3.DatabaseError) as e:
        con.execute(sql, args)
    return str(e.value)


# ---------------------------------------------------------------------------------------------------------------------------------- install, classes
def test_install_registers_every_real_table_and_seals_dated_tables_through_their_last_date(tmp_path):
    p, con = make_db(tmp_path)
    st = guard.status(con)
    assert st["installed"] and st["unregistered"] == [] and st["missing_triggers"] == []
    assert st["tables"]["market_data_lake"]["sealed_through"] == "2020-01-03"
    assert st["tables"]["corporate_actions_log"]["class"] == INSERT_ONLY
    assert st["tables"]["regime_state"]["class"] == EXEMPT and st["tables"]["regime_state"]["reason"]
    real = {t: r for t, r in RULES.items() if t not in NOT_IN_THE_REAL_FILE}
    assert {t for t in st["tables"]} == set(real)                                     # the 26 tables of the real file (25 + market_data_non_eq) are exactly the registry (plus tables registered for a script that is not applied yet)
    assert len(real) == 26 and sum(r.cls == DATED for r in real.values()) == 6 and sum(r.cls == INSERT_ONLY for r in real.values()) == 10 and sum(r.cls == EXEMPT for r in real.values()) == 10
    assert guard.audit(con)["ok"]


def test_install_is_idempotent_and_exempt_tables_are_untouched(tmp_path):
    p, con = make_db(tmp_path)
    n = len(core.existing_triggers(con))
    guard.install(con)
    assert len(core.existing_triggers(con)) == n
    con.execute("INSERT INTO regime_state(eval_date, kill_switch_active) VALUES ('2020-01-01', 0)")
    con.execute("UPDATE regime_state SET kill_switch_active=1")
    con.execute("DELETE FROM regime_state")                                           # exempt: free


def test_the_two_native_triggers_of_trade_analytics_log_are_kept(tmp_path):
    p, con = make_db(tmp_path)
    assert {"trg_tal_no_update", "trg_tal_no_delete"} <= {r[0] for r in con.execute("select name from sqlite_master where type='trigger'")}


# ---------------------------------------------------------------------------------------------------------------------------------- DATED_APPEND_ONLY
def test_sealed_rows_refuse_update_delete_and_backdated_insert_with_a_clear_error(tmp_path):
    p, con = make_db(tmp_path)
    for sql, args, word in (("UPDATE market_data_lake SET close_raw=9 WHERE symbol='AAA' AND trade_date='2020-01-02'", (), "update refused"),
                            ("DELETE FROM market_data_lake WHERE trade_date='2020-01-01'", (), "delete refused"),
                            (MDL, ("CCC", "2020-01-02", 1, 1, 1, 1, 1, "t"), "insert refused"),
                            (MDL, ("CCC", "2020-01-01", 1, 1, 1, 1, 1, "t"), "insert refused")):
        msg = refused(con, sql, args)
        assert "guard: market_data_lake" in msg and word in msg and "guard.py correct" in msg
    assert con.execute("select count(*), sum(close_raw) from market_data_lake").fetchone() == (6, 9.0)


def test_an_update_that_moves_a_row_across_the_seal_is_refused_both_ways(tmp_path):
    p, con = make_db(tmp_path)
    con.execute(MDL, ("NEW", "2020-01-04", 1, 1, 1, 1, 1, "t"))                       # unsealed day
    refused(con, "UPDATE market_data_lake SET trade_date='2020-01-02' WHERE symbol='NEW'")     # unsealed -> sealed
    refused(con, "UPDATE market_data_lake SET trade_date='2020-01-09' WHERE symbol='AAA' AND trade_date='2020-01-01'")      # sealed -> unsealed


def test_a_date_with_a_time_part_cannot_slip_under_the_seal(tmp_path):
    p, con = make_db(tmp_path)
    refused(con, MDL, ("CCC", "2020-01-03 00:00:00", 1, 1, 1, 1, 1, "t"))


def test_replace_and_upsert_on_a_sealed_day_are_refused(tmp_path):
    p, con = make_db(tmp_path)
    msg = refused(con, MDL.replace("INSERT INTO", "INSERT OR REPLACE INTO"), ("AAA", "2020-01-02", 9, 9, 9, 9, 9, "t"))
    assert "insert refused" in msg
    refused(con, MDL + " ON CONFLICT(symbol, trade_date) DO UPDATE SET close_raw=excluded.close_raw", ("AAA", "2020-01-02", 9, 9, 9, 9, 9, "t"))
    assert con.execute("select close_raw from market_data_lake where symbol='AAA' and trade_date='2020-01-02'").fetchone()[0] == 1.5


def test_a_new_date_is_accepted_and_an_unsealed_day_can_be_deleted_and_reloaded(tmp_path):
    p, con = make_db(tmp_path)
    con.execute(MDL, ("AAA", "2020-01-06", 1, 1, 1, 1, 1, "t"))
    con.execute("DELETE FROM market_data_lake WHERE trade_date='2020-01-06'")        # the unsealed day (a day being loaded) is free
    con.execute(MDL, ("AAA", "2020-01-06", 2, 2, 2, 2, 2, "t"))
    con.execute("UPDATE market_data_lake SET close_raw=3 WHERE trade_date='2020-01-06'")
    assert con.execute("select close_raw from market_data_lake where trade_date='2020-01-06'").fetchone()[0] == 3


def test_seal_moves_forward_only_refuses_an_unloaded_date_and_stores_the_day_checksums(tmp_path):
    p, con = make_db(tmp_path)
    con.execute(MDL, ("AAA", "2020-01-06", 1, 1, 1, 1, 1, "t"))
    with pytest.raises(guard.GuardError, match="no rows dated up to"):
        guard.seal_table(con, "market_data_lake", "2020-01-09")
    with pytest.raises(guard.GuardError, match="already sealed"):
        guard.seal_table(con, "market_data_lake", "2020-01-02")
    r = guard.seal_table(con, "market_data_lake", "2020-01-06")
    assert r["sealed_through"] == "2020-01-06" and r["days_sealed"] == 1 and r["rows"] == 1
    assert con.execute("select count(*) from _guard_day_checksum where tbl='market_data_lake'").fetchone()[0] == 4
    refused(con, "UPDATE _guard_seal SET sealed_through='2020-01-01' WHERE tbl='market_data_lake'")        # not back, outside a window
    refused(con, "DELETE FROM _guard_seal")


def test_day_checksum_ignores_surrogate_ids_and_load_timestamps_so_a_reload_of_an_unsealed_day_seals_identically(tmp_path):
    p, con = make_db(tmp_path)
    con.execute(MDL, ("AAA", "2020-01-06", 1, 1, 1, 1, 1, "t"))
    a = core.day_checksum_one(con, "market_data_lake", "2020-01-06")
    con.execute("DELETE FROM market_data_lake WHERE trade_date='2020-01-06'")
    con.execute(MDL, ("AAA", "2020-01-06", 1, 1, 1, 1, 1, "t"))                       # new id, new created_at
    assert core.day_checksum_one(con, "market_data_lake", "2020-01-06") == a


# ---------------------------------------------------------------------------------------------------------------------------------- INSERT_ONLY
def test_insert_only_refuses_update_delete_and_a_different_row_with_the_same_key(tmp_path):
    p, con = make_db(tmp_path)
    assert "update refused" in refused(con, "UPDATE corporate_actions_log SET notes='x'")
    assert "delete refused" in refused(con, "DELETE FROM corporate_actions_log")
    for verb in ("INSERT", "INSERT OR REPLACE", "INSERT OR IGNORE"):
        msg = refused(con, CA.replace("INSERT", verb, 1), ("AAA", "2020-01-02", "SPLIT", 9, 1, "changed", "t"))
        assert "different row with the same key" in msg
    refused(con, CA + " ON CONFLICT(symbol,ex_date,action_type) DO UPDATE SET notes=excluded.notes", ("AAA", "2020-01-02", "SPLIT", 5, 1, "changed", "t"))
    assert con.execute("select notes from corporate_actions_log where symbol='AAA'").fetchone()[0] == "first"


def test_insert_only_accepts_a_new_row_and_ignores_an_identical_one_so_idempotent_writers_keep_working(tmp_path):
    p, con = make_db(tmp_path)
    con.execute(CA, ("CCC", "2019-06-01", "DIVIDEND", 1, 1, "late", "t"))             # a late fact with an old ex_date: allowed by design
    for verb in ("INSERT OR IGNORE", "INSERT OR REPLACE"):
        con.execute(CA.replace("INSERT", verb, 1), ("AAA", "2020-01-02", "SPLIT", 5, 1, "first", "t"))
    assert con.execute("select count(*) from corporate_actions_log").fetchone()[0] == 3
    # a re-insert that differs only in a volatile column (load time) is the same fact
    con.execute("INSERT OR REPLACE INTO corporate_actions_log(symbol,ex_date,action_type,ratio_numerator,ratio_denominator,notes,source,loaded_at) VALUES ('AAA','2020-01-02','SPLIT',5,1,'first','t','later')")
    assert con.execute("select count(*) from corporate_actions_log").fetchone()[0] == 3


def test_insert_only_table_with_a_blob_column_logs_it_as_hex_inside_a_window(tmp_path):
    p, con = make_db(tmp_path)
    con.execute("INSERT INTO earnings_api_raw VALUES ('ep','Q','2020-01-01T00:00:00',200,1,?)", (b"\x00\x01",))
    guard.correct(con, "refetch", "INSERT OR REPLACE INTO earnings_api_raw VALUES ('ep','Q','2020-01-02T00:00:00',200,2,x'0203');")
    row = con.execute("select before_json, after_json from _guard_change_log where tbl='earnings_api_raw' and op='REPLACE'").fetchone()
    assert '"body_zlib":"0001"' in row[0] and '"body_zlib":"0203"' in row[1]


# ---------------------------------------------------------------------------------------------------------------------------------- corrections
def test_correct_changes_sealed_rows_logs_before_and_after_increments_the_counter_and_refreshes_the_day(tmp_path):
    p, con = make_db(tmp_path)
    before = core.day_checksum_one(con, "market_data_lake", "2020-01-02")
    c0 = guard.status(con)["correction_counter"]
    res = guard.correct(con, "vendor fixed AAA close", "UPDATE market_data_lake SET close_raw=7.5 WHERE symbol='AAA' AND trade_date='2020-01-02';\nDELETE FROM market_data_lake WHERE symbol='BBB' AND trade_date='2020-01-01';")
    assert res["rows_logged"] == 2 and res["days_refreshed"] == 2 and res["correction_counter"] == c0 + 1
    rows = con.execute("select tbl,op,key,before_json,after_json,reason,correction_no from _guard_change_log where tbl='market_data_lake' order by id").fetchall()
    assert rows[0][1:3] == ("UPDATE", "AAA|2020-01-02") and '"close_raw":1.5' in rows[0][3] and '"close_raw":7.5' in rows[0][4] and rows[0][5] == "vendor fixed AAA close" and rows[0][6] == c0 + 1
    assert rows[1][1] == "DELETE" and rows[1][4] is None
    assert core.day_checksum_one(con, "market_data_lake", "2020-01-02") != before
    assert guard.audit(con)["ok"]                                                                             # the sealed day's checksum was refreshed by the tool
    assert not guard.window_state(con)["open"]
    refused(con, "UPDATE market_data_lake SET close_raw=1 WHERE symbol='AAA'")                                  # sealed again as soon as the transaction ended


def test_correct_can_add_a_backdated_row_and_change_an_insert_only_row(tmp_path):
    p, con = make_db(tmp_path)
    guard.correct(con, "late listing", MDL.replace("?", "'{}'").format("NEW", "2020-01-02", 1, 1, 1, 1, 1, "t") + ";\nUPDATE corporate_actions_log SET notes='fixed' WHERE symbol='AAA';")
    assert con.execute("select count(*) from market_data_lake where symbol='NEW'").fetchone()[0] == 1
    assert con.execute("select notes from corporate_actions_log where symbol='AAA'").fetchone()[0] == "fixed"
    assert guard.audit(con)["ok"]


def test_a_failed_correction_rolls_everything_back_and_leaves_no_open_window(tmp_path):
    p, con = make_db(tmp_path)
    c0 = guard.status(con)["correction_counter"]
    with pytest.raises(sqlite3.Error):
        guard.correct(con, "bad", "UPDATE market_data_lake SET close_raw=9 WHERE symbol='AAA';\nUPDATE no_such_table SET x=1;")
    assert guard.status(con)["correction_counter"] == c0 and not guard.window_state(con)["open"]
    assert con.execute("select count(*) from market_data_lake where close_raw=9").fetchone()[0] == 0
    refused(con, "UPDATE market_data_lake SET close_raw=9")


def test_a_correction_needs_a_reason_and_sql(tmp_path):
    p, con = make_db(tmp_path)
    with pytest.raises(guard.GuardError):
        guard.correct(con, "  ", "UPDATE market_data_lake SET close_raw=9;")
    with pytest.raises(guard.GuardError):
        guard.correct(con, "r", "   ")
    with pytest.raises(guard.GuardError, match="incomplete"):
        guard.correct(con, "r", "UPDATE market_data_lake SET close_raw=9")


def test_open_and_close_correction_pair_allows_changes_only_while_open(tmp_path):
    p, con = make_db(tmp_path)
    w = guard.open_window(con, "interactive fix")
    assert w["open"] and w["corrections"] == 1
    con.execute("UPDATE market_data_lake SET close_raw=4 WHERE symbol='AAA' AND trade_date='2020-01-01'")
    guard.close_window(con)
    assert not guard.window_state(con)["open"]
    refused(con, "UPDATE market_data_lake SET close_raw=5 WHERE symbol='AAA' AND trade_date='2020-01-01'")
    assert con.execute("select count(*) from _guard_change_log where tbl='market_data_lake'").fetchone()[0] == 1
    assert not guard.audit(con)["ok"]                                         # a window changed a sealed day without the tool: the audit says so (day checksum stale)
    with pytest.raises(guard.GuardError, match="reason"):
        guard.open_window(con, "")


def test_a_window_left_open_is_dead_after_its_expiry(tmp_path):
    p, con = make_db(tmp_path)
    guard.open_window(con, "forgot to close")
    assert guard.window_state(con)["open"]
    con.execute("UPDATE _guard_window SET expires_at = strftime('%Y-%m-%dT%H:%M:%f','now','-1 minutes')")
    assert not guard.window_state(con)["open"]
    refused(con, "UPDATE market_data_lake SET close_raw=9")
    assert core.WINDOW_MINUTES == 15


def test_a_window_opened_outside_the_tool_still_changes_the_counter_and_the_log(tmp_path):
    p, con = make_db(tmp_path)
    c0 = guard.status(con)["correction_counter"]
    con.execute("UPDATE _guard_window SET is_open=1, reason=NULL, expires_at=strftime('%Y-%m-%dT%H:%M:%f','now','+1 minutes')")
    con.execute("UPDATE market_data_lake SET close_raw=9 WHERE symbol='AAA' AND trade_date='2020-01-01'")
    assert guard.status(con)["correction_counter"] == c0 + 1
    assert con.execute("select op, reason from _guard_change_log where tbl='_guard_window'").fetchall() == [("OPEN", None)]
    assert con.execute("select count(*) from _guard_change_log where tbl='market_data_lake'").fetchone()[0] == 1


def test_counter_log_registry_and_checksums_are_protected(tmp_path):
    p, con = make_db(tmp_path)
    guard.correct(con, "x", "UPDATE market_data_lake SET close_raw=8 WHERE symbol='AAA' AND trade_date='2020-01-01';")      # gives the log and the counter something to protect
    refused(con, "UPDATE _guard_counter SET corrections = corrections - 1")
    refused(con, "DELETE FROM _guard_counter")
    refused(con, "UPDATE _guard_change_log SET reason='x'")
    refused(con, "DELETE FROM _guard_change_log")
    refused(con, "UPDATE _guard_registry SET class='EXEMPT'")
    refused(con, "DELETE FROM _guard_registry")
    refused(con, "UPDATE _guard_day_checksum SET sha256='x'")
    refused(con, "DELETE FROM _guard_day_checksum")
    refused(con, "DELETE FROM _guard_window")


# ---------------------------------------------------------------------------------------------------------------------------------- audit, uninstall, R5
def test_audit_detects_a_row_changed_after_the_triggers_were_dropped(tmp_path):
    p, con = make_db(tmp_path)
    assert guard.audit(con)["ok"]
    for n in list(core.existing_triggers(con)):
        if n.startswith("g_market_data_lake_"):
            con.execute(f'DROP TRIGGER "{n}"')
    con.execute("UPDATE market_data_lake SET close_raw=99 WHERE symbol='AAA' AND trade_date='2020-01-02'")          # nothing stops this any more
    con.execute("DELETE FROM market_data_lake WHERE trade_date='2020-01-01' AND symbol='BBB'")
    con.execute(MDL, ("ZZZ", "2020-01-03", 1, 1, 1, 1, 1, "t"))
    a = guard.audit(con)
    kinds = {(x["kind"], x.get("day"), x.get("name")) for x in a["problems"]}
    assert not a["ok"]
    assert ("sealed_day_changed", "2020-01-02", None) in kinds and ("sealed_day_changed", "2020-01-01", None) in kinds and ("sealed_day_changed", "2020-01-03", None) in kinds
    assert any(k[0] == "missing_trigger" for k in kinds)


def test_audit_detects_an_altered_trigger_and_an_open_window(tmp_path):
    p, con = make_db(tmp_path)
    con.execute("DROP TRIGGER g_market_data_lake_bu")
    con.execute("CREATE TRIGGER g_market_data_lake_bu BEFORE UPDATE ON market_data_lake BEGIN SELECT 1; END")
    guard.open_window(con, "x")
    kinds = {x["kind"] for x in guard.audit(con)["problems"]}
    assert {"altered_trigger", "window_open"} <= kinds


def test_uninstall_needs_the_explicit_flag_and_leaves_the_data(tmp_path):
    p, con = make_db(tmp_path)
    with pytest.raises(guard.GuardError, match="--yes-remove-guard"):
        guard.uninstall(con)
    assert guard.installed(con)
    r = guard.uninstall(con, yes_remove_guard=True)
    assert r["removed_triggers"] > 0 and not guard.installed(con) and core.existing_triggers(con) == {}
    assert con.execute("select count(*) from market_data_lake").fetchone()[0] == 6
    con.execute("UPDATE market_data_lake SET close_raw=9")                                      # unguarded again
    assert {"trg_tal_no_update", "trg_tal_no_delete"} <= {r[0] for r in con.execute("select name from sqlite_master where type='trigger'")}     # the native ones stay


def test_install_refuses_an_unregistered_table_and_ensure_reports_it_and_protects_a_registered_one_created_later(tmp_path):
    p = tmp_path / "e.db"
    con = sqlite3.connect(str(p), isolation_level=None)
    con.execute("CREATE TABLE brand_new_table(a)")
    with pytest.raises(guard.UnregisteredTables, match="brand_new_table"):
        guard.install(con)
    con.execute("DROP TABLE brand_new_table")
    guard.install(con)                                                                           # an empty database: state only
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    assert guard.status(con)["missing_triggers"]
    r = guard.ensure(con)
    assert r["installed"] and r["created_triggers"] and guard.status(con)["missing_triggers"] == []
    con.execute("CREATE TABLE another_new_table(a)")
    assert guard.ensure(con)["unregistered"] == ["another_new_table"]
    with pytest.raises(guard.UnregisteredTables):
        guard.ensure(con, strict=True)
    assert guard.status(con)["unregistered"] == ["another_new_table"]


def test_every_table_the_code_can_create_has_a_class():
    names = set()
    pat = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?([A-Za-z_][A-Za-z0-9_]*)", re.I)
    for base in ("stockbot", "scripts"):
        for f in (ROOT / base).rglob("*"):
            if f.suffix in (".py", ".sql") and "__pycache__" not in f.parts:
                for m in pat.finditer(f.read_text(encoding="utf-8", errors="replace")):
                    names.add((m.group(1), f.relative_to(ROOT).as_posix()))
    unknown = sorted((n, f) for n, f in names if n not in RULES and not core.is_guard_object(n) and not n.startswith(("tmp", "temp", "_")) and f not in ("stockbot/data/guard/core.py", "stockbot/live/state_store.py"))     # state_store.py: the separate live state database (out of scope, decision D5)
    assert not unknown, f"CREATE TABLE of a table with no class in stockbot/data/guard/registry.py: {unknown}"


def test_the_registry_reads_and_exemptions_are_consistent():
    assert all(r.reason for r in RULES.values() if r.cls == EXEMPT)
    assert all(r.date_col and r.key for r in RULES.values() if r.cls == DATED)
    assert all(r.key for r in RULES.values() if r.cls == INSERT_ONLY)
    assert all(t in RULES and RULES[t].cls != EXEMPT for t in BACKTEST_READS)


def test_triggers_never_change_what_a_select_returns(tmp_path):
    p, con = make_db(tmp_path, "a.db", install=False)
    q = ("select * from market_data_lake order by id", "select * from corporate_actions_log order by id", "select symbol, max(trade_date) from market_data_lake group by 1")
    plain = [con.execute(s).fetchall() for s in q]
    guard.install(con)
    assert [con.execute(s).fetchall() for s in q] == plain


def test_connect_writer_returns_a_guarded_connection_and_does_not_change_the_journal_mode(tmp_path):
    p, con = make_db(tmp_path)
    con.close()
    w = guard.connect_writer(p)
    assert w.execute("pragma journal_mode").fetchone()[0] == "delete"
    refused(w, "UPDATE market_data_lake SET close_raw=9")


# ---------------------------------------------------------------------------------------------------------------------------------- R1: readers and the run check
def test_open_lake_cannot_write(tmp_path):
    from stockbot.data.lake import open_lake
    p, con = make_db(tmp_path)
    con.close()
    ro = open_lake(p)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute(MDL, ("Q", "2030-01-01", 1, 1, 1, 1, 1, "t"))
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM regime_state")                                                  # even an exempt table
    ro.close()


def test_snapshot_is_identical_when_nothing_changed_and_verdict_says_what_was_verified(tmp_path, capsys):
    p, con = make_db(tmp_path)
    con.close()
    for full in (True, False):
        a, b = runcheck.snapshot(p, full_hash=full), runcheck.snapshot(p, full_hash=full)
        assert runcheck.differences(a, b) == []
        assert (a["sha256"] is not None) == full and a["guard"]["installed"] and a["guard"]["tables"]["market_data_lake"]["sealed_through"] == "2020-01-03"
        assert a["guard"]["tables"]["corporate_actions_log"]["row_count"] == 2 and len(a["guard"]["tables"]["corporate_actions_log"]["sha256"]) == 64
        assert runcheck.verdict(a, b, "unit") == 0
    out = capsys.readouterr().out
    assert "unchanged; verified full file sha256" in out and "short step: the file bytes are not hashed" in out


def test_a_change_marks_the_run_invalid_with_exit_code_3_for_each_kind_of_change(tmp_path, capsys):
    p, con = make_db(tmp_path)
    con.close()
    a = runcheck.snapshot(p, full_hash=True)
    # 1 a new corporate action row (INSERT_ONLY digest and file bytes change)
    c = sqlite3.connect(str(p), isolation_level=None)
    c.execute(CA, ("ZZZ", "2020-01-05", "SPLIT", 2, 1, "late", "t"))
    b = runcheck.snapshot(p, full_hash=True)
    d = runcheck.differences(a, b)
    assert any("sha256" in x for x in d) and any("corporate_actions_log" in x for x in d)
    assert runcheck.verdict(a, b, "unit") == 3
    assert "RUN INVALID (unit)" in capsys.readouterr().out
    # 2 a correction (counter) on a short step: no file hash, still caught
    s1 = runcheck.snapshot(p, full_hash=False)
    guard.correct(c, "x", "UPDATE market_data_lake SET close_raw=8 WHERE symbol='AAA' AND trade_date='2020-01-01';")
    s2 = runcheck.snapshot(p, full_hash=False)
    assert any("correction_counter" in x for x in runcheck.differences(s1, s2)) and runcheck.verdict(s1, s2, "unit") == 3
    # 3 a seal moved
    s3 = runcheck.snapshot(p, full_hash=False)
    c.execute(MDL, ("AAA", "2020-01-09", 1, 1, 1, 1, 1, "t"))
    guard.seal_table(c, "market_data_lake", "2020-01-09")
    assert any("sealed_through" in x for x in runcheck.differences(s3, runcheck.snapshot(p, full_hash=False)))


def test_a_non_empty_wal_file_is_part_of_the_check(tmp_path):
    p, con = make_db(tmp_path)
    con.close()
    a = runcheck.snapshot(p, full_hash=False)
    Path(str(p) + "-wal").write_bytes(b"x" * 32)
    assert any("wal_bytes" in x for x in runcheck.differences(a, runcheck.snapshot(p, full_hash=False)))


def test_short_step_decorator_returns_3_when_the_database_changes_during_the_step(tmp_path, capsys):
    p, con = make_db(tmp_path)
    con.close()

    def good(argv=None):
        return 0

    def bad(argv=None):
        c = sqlite3.connect(str(p), isolation_level=None)
        c.execute(CA, ("ZZZ", "2020-01-05", "SPLIT", 2, 1, "late", "t"))
        c.close()
        return 0
    assert runcheck.short_step("unit step")(good)(["--lake", str(p)]) == 0
    assert runcheck.short_step("unit step")(bad)(["--lake", str(p)]) == 3
    assert runcheck.short_step("unit step")(good)(["--help"]) == 0
    out = capsys.readouterr().out
    assert "database check (unit step): unchanged" in out and "RUN INVALID (unit step)" in out


def test_the_cli_status_and_audit_are_read_only_and_uninstall_needs_its_flag(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("guard_cli", ROOT / "scripts" / "guard.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    p, con = make_db(tmp_path, install=False)
    con.close()
    assert cli.main(["--db", str(p), "install"]) == 0
    before = runcheck.sha256_file(p)
    assert cli.main(["--db", str(p), "status"]) == 0 and cli.main(["--db", str(p), "audit"]) == 0
    assert runcheck.sha256_file(p) == before
    sql = tmp_path / "fix.sql"
    sql.write_text("UPDATE market_data_lake SET close_raw=3 WHERE symbol='AAA' AND trade_date='2020-01-01';\n", encoding="utf-8")
    assert cli.main(["--db", str(p), "correct", "--reason", "cli fix", str(sql)]) == 0
    assert cli.main(["--db", str(p), "audit"]) == 0
    assert cli.main(["--db", str(p), "seal", "market_data_lake", "2020-01-01"]) == 1                       # not back
    assert cli.main(["--db", str(p), "uninstall"]) == 1                                                       # (flag is required by the parser's check inside guard.uninstall)
    assert cli.main(["--db", str(p), "uninstall", "--yes-remove-guard"]) == 0
    capsys.readouterr()

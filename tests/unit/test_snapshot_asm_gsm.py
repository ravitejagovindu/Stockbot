"""stockbot/data/ingestion/snapshot_asm_gsm.py: parsing, idempotence, failure handling.  No network (fetch is replaced)."""
import json
import sqlite3
import sys
from pathlib import Path

from stockbot.data.ingestion import snapshot_asm_gsm as snap

ASM = {"longterm": {"data": [{"asmSurvIndicator": "Stage I", "asmTime": "08-Nov-2026", "companyName": "A", "isin": "INE1", "survCode": "LTASM - I (13)", "survDesc": "d", "symbol": "AAA", "srno": 1}]},
       "shortterm": {"data": [{"asmSurvIndicator": "Stage II", "asmTime": "08-Nov-2026", "companyName": "B", "isin": "INE2", "survCode": "STASM - II", "survDesc": "d", "symbol": "BBB", "srno": 1}]}}
GSM = [{"companyName": "C", "gsmStage": "LXII", "gsmTime": "08-Nov-2026 08:06:02", "isin": "INE3", "survCode": "x", "survDesc": "y", "symbol": "CCC", "srno": 1}]


def _run(tmp_path, responses):
    db = str(tmp_path / "t.db")
    snap.fetch = lambda ep, s: responses[ep]
    snap._new_session = lambda: None
    return snap.main(["--db", db]), db


def test_stores_both_lists_and_is_idempotent(tmp_path):
    ok = {"reportASM": (200, ASM, json.dumps(ASM)), "reportGSM": (200, GSM, json.dumps(GSM))}
    rc, db = _run(tmp_path, ok)
    assert rc == 0
    con = sqlite3.connect(db)
    got = sorted(con.execute("select framework, symbol, stage from asm_gsm_daily_snapshot"))
    assert got == [("ASM_LT", "AAA", "Stage I"), ("ASM_ST", "BBB", "Stage II"), ("GSM", "CCC", "LXII")]
    assert con.execute("select count(*) from asm_gsm_snapshot_raw").fetchone()[0] == 2
    con.close()
    rc2, _ = _run(tmp_path, ok)                       # same day again: nothing changes
    con = sqlite3.connect(db)
    assert rc2 == 0 and con.execute("select count(*) from asm_gsm_daily_snapshot").fetchone()[0] == 3
    assert con.execute("select count(*) from asm_gsm_snapshot_log where outcome='ALREADY_STORED'").fetchone()[0] == 2


def test_failure_and_empty_list_write_no_rows_and_exit_nonzero(tmp_path):
    bad = {"reportASM": (403, None, "denied"), "reportGSM": (200, [], "[]")}
    rc, db = _run(tmp_path, bad)
    con = sqlite3.connect(db)
    assert rc == 1
    assert con.execute("select count(*) from asm_gsm_daily_snapshot").fetchone()[0] == 0
    assert con.execute("select count(*) from asm_gsm_snapshot_raw").fetchone()[0] == 0
    assert con.execute("select count(*) from asm_gsm_snapshot_log where outcome='FAILED'").fetchone()[0] >= 1


def test_touches_only_its_own_tables(tmp_path):
    ok = {"reportASM": (200, ASM, "{}"), "reportGSM": (200, GSM, "[]")}
    _, db = _run(tmp_path, ok)
    names = {r[0] for r in sqlite3.connect(db).execute("select name from sqlite_master where type='table'")}
    assert names == {"asm_gsm_snapshot_raw", "asm_gsm_daily_snapshot", "asm_gsm_snapshot_log"}

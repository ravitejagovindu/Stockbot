"""stockbot/data/ingestion/collect_earnings_history.py: timestamp parsing, results-meeting classification, parsing and idempotent storage (no network)."""
import json
import sqlite3
import sys
import zlib
from pathlib import Path

from stockbot.data.ingestion import collect_earnings_history as ce

FIN = {"audited": "Audited", "broadCastDate": "16-Jan-2025 19:42:10", "companyName": "Infosys Limited", "consolidated": "Non-Consolidated",
       "cumulative": "Non-cumulative", "exchdisstime": "16-Jan-2025 19:42:44", "filingDate": "16-Jan-2025 19:42", "format": "New", "fromDate": "01-Oct-2024",
       "isin": "INE009A01021", "params": "p1", "period": "Quarterly", "relatingTo": "Third Quarter", "seqNumber": "1189815", "symbol": "INFY",
       "toDate": "31-Dec-2024", "xbrl": "x"}
FIN_OLD = dict(FIN, broadCastDate=None, filingDate="-", exchdisstime=None, format="Old", params="p0", toDate="31-Mar-2005")
BM = {"bm_symbol": "INFY", "bm_date": "23-Oct-2026", "bm_purpose": "Board Meeting Intimation",
      "bm_desc": "INFOSYS LIMITED has informed the Exchange about Board Meeting to be held on 23-Oct-2026 to consider and approve the Half Yearly Audited Financial results of the Company.",
      "bm_timestamp": "16-Sep-2026 18:34:49", "sm_name": "Infosys Limited", "sm_isin": "INE009A01021", "sysTime": "16-Sep-2026 18:34:52", "attachment": "u"}
BM_BUYBACK = dict(BM, bm_purpose="Buyback", bm_desc="Board meeting to consider buyback of equity shares.")


def test_iso_ts_formats_and_blanks():
    assert ce.iso_ts("16-Jan-2025 19:42:10") == "2025-01-16 19:42:10"
    assert ce.iso_ts("16-Jan-2025 19:42") == "2025-01-16 19:42:00"
    assert ce.iso_ts("31-Dec-2024") == "2024-12-31"
    assert ce.iso_ts("-") is None and ce.iso_ts(None) is None and ce.iso_ts("::") is None


def test_classify_meeting():
    assert ce.classify_meeting("Financial Results/Dividend", "") == (1, "purpose")
    assert ce.classify_meeting("Results", None) == (1, "purpose")
    assert ce.classify_meeting(BM["bm_purpose"], BM["bm_desc"]) == (1, "desc")      # intimation whose text says results
    assert ce.classify_meeting("Buyback", BM_BUYBACK["bm_desc"]) == (0, "none")
    assert ce.classify_meeting("Fund Raising", "to consider raising of funds") == (0, "none")


def test_parse_rows():
    r = ce.parse_results("INFY", [FIN, FIN_OLD])
    assert r[0][13] == "2025-01-16 19:42:10" and r[1][13] is None and r[1][12] is None   # broadcast_ts / filing_ts
    m = ce.parse_meetings("INFY", [BM, BM_BUYBACK])
    assert m[0][4] == "2026-10-23" and m[0][7] == "2026-09-16 18:34:49" and m[0][10] == 1 and m[1][10] == 0


def test_storage_is_idempotent_and_new_tables_only(tmp_path, monkeypatch):
    db = str(tmp_path / "e.db")
    con = sqlite3.connect(db)
    con.execute("create table market_data_lake (symbol text)")
    con.executemany("insert into market_data_lake values (?)", [("INFY",), ("NIFTY50_INDEX",)])
    con.commit(); con.close()

    class Fake:
        def __init__(self, sleep): self.consec_fail = 0
        def get(self, ep, sym):
            return 200, ([FIN, FIN_OLD] if ep == ce.EP_FIN else [BM, BM_BUYBACK]), ""
    monkeypatch.setattr(ce, "Client", Fake)
    assert ce.main(["--db", db, "--symbols", "INFY"]) == 0
    assert ce.main(["--db", db, "--symbols", "INFY"]) == 0                      # second run: skipped, no duplicates
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from earnings_results_filing").fetchone()[0] == 2
    assert con.execute("select count(*) from earnings_board_meeting").fetchone()[0] == 2
    raw = con.execute("select body_zlib from earnings_api_raw where endpoint=?", (ce.EP_FIN,)).fetchone()[0]
    assert json.loads(zlib.decompress(raw))[0]["symbol"] == "INFY"               # lossless
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table' and name like 'earnings_%'")}
    assert names == {"earnings_api_raw", "earnings_results_filing", "earnings_board_meeting", "earnings_symbol_map", "earnings_collect_log"}


def test_stops_after_repeated_failures(tmp_path, monkeypatch):
    db = str(tmp_path / "e.db")
    con = sqlite3.connect(db); con.execute("create table market_data_lake (symbol text)")
    con.executemany("insert into market_data_lake values (?)", [(f"S{i}",) for i in range(30)]); con.commit(); con.close()

    class Blocked:
        calls = 0
        def __init__(self, sleep): self.consec_fail = 0
        def get(self, ep, sym):
            Blocked.calls += 1; self.consec_fail += 1
            return 403, None, "denied"
    monkeypatch.setattr(ce, "Client", Blocked)
    assert ce.main(["--db", db, "--max-consecutive-fail", "5"]) == 2
    assert Blocked.calls == 5                                                    # stopped, did not walk the whole list

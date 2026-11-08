"""stockbot/data/ingestion/snapshot_asm_gsm.py — forward daily snapshot of NSE's current ASM and GSM lists (Step 12, KI-003).

Standalone: no engine, screener or backtest imports.  Reads ``api/reportASM`` (long-term + short-term) and ``api/reportGSM`` once each and appends
to NEW tables only:

  asm_gsm_snapshot_raw  one row per (snapshot_date, endpoint): http status, row count, the raw JSON body
  asm_gsm_daily_snapshot one row per (snapshot_date, framework, symbol): isin, company, stage, surveillance code/description, NSE's own time field
  asm_gsm_snapshot_log   one row per run (success or failure) so a missing day is visible

framework is ASM_LT, ASM_ST or GSM.  The snapshot is point-in-time only from the day it starts; it fills nothing in the past.
Idempotent per day (INSERT OR IGNORE): a second run on the same date changes nothing.  An empty or failed response is logged and writes no rows
(an empty list on a normal day is treated as a failure, not as "nobody is on surveillance").  One retry with a fresh session; a 403/429 stops the run.
Exit code 0 = both lists stored (or already stored today); 1 = something failed.

    py stockbot/data/ingestion/snapshot_asm_gsm.py [--db finsight.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}
BASE = "https://www.nseindia.com/api/"
ENDPOINTS = ("reportASM", "reportGSM")

DDL = """
CREATE TABLE IF NOT EXISTS asm_gsm_snapshot_raw (
    snapshot_date TEXT NOT NULL, endpoint TEXT NOT NULL, fetched_at TEXT NOT NULL,
    http_status INTEGER NOT NULL, row_count INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, endpoint));
CREATE TABLE IF NOT EXISTS asm_gsm_daily_snapshot (
    snapshot_date TEXT NOT NULL, framework TEXT NOT NULL, symbol TEXT NOT NULL, isin TEXT, company_name TEXT,
    stage TEXT, surv_code TEXT, surv_desc TEXT, nse_time TEXT, srno INTEGER, fetched_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, framework, symbol));
CREATE TABLE IF NOT EXISTS asm_gsm_snapshot_log (
    run_at TEXT NOT NULL, snapshot_date TEXT NOT NULL, endpoint TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT);
"""


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=20)       # cookie warm-up; a 403 body is fine
    except requests.RequestException:
        pass
    return s


def fetch(endpoint: str, session: requests.Session) -> tuple[int, object | None, str]:
    """Return (http_status, parsed_json_or_None, body_text).  One retry with a fresh session on a non-200; 403/429 twice -> give up."""
    last = (0, None, "")
    for attempt in range(2):
        try:
            r = session.get(BASE + endpoint, timeout=30)
            last = (r.status_code, None, r.text)
            if r.status_code == 200:
                return 200, r.json(), r.text
        except (requests.RequestException, ValueError) as exc:
            last = (0, None, f"{type(exc).__name__}: {exc}")
        if attempt == 0:
            time.sleep(5)
            session = _new_session()
    return last


def rows_from(endpoint: str, payload: object, snapshot_date: str, fetched_at: str) -> list[tuple]:
    """Flatten a report payload into daily-snapshot rows."""
    out: list[tuple] = []
    if endpoint == "reportASM":
        for key, fw in (("longterm", "ASM_LT"), ("shortterm", "ASM_ST")):
            for e in (payload or {}).get(key, {}).get("data", []) or []:
                out.append((snapshot_date, fw, str(e["symbol"]).strip(), e.get("isin"), e.get("companyName"), e.get("asmSurvIndicator"),
                            e.get("survCode"), e.get("survDesc"), e.get("asmTime"), e.get("srno"), fetched_at))
    else:
        for e in payload or []:
            out.append((snapshot_date, "GSM", str(e["symbol"]).strip(), e.get("isin"), e.get("companyName"), e.get("gsmStage"),
                        e.get("survCode"), e.get("survDesc"), e.get("gsmTime"), e.get("srno"), fetched_at))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    args = ap.parse_args(argv)
    snapshot_date = date.today().isoformat()
    run_at = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(args.db, timeout=120)
    con.executescript(DDL)
    failed = False
    session = _new_session()
    for endpoint in ENDPOINTS:
        if con.execute("select 1 from asm_gsm_snapshot_raw where snapshot_date=? and endpoint=?", (snapshot_date, endpoint)).fetchone():
            con.execute("insert into asm_gsm_snapshot_log values (?,?,?,?,?)", (run_at, snapshot_date, endpoint, "ALREADY_STORED", None))
            print(f"{endpoint}: already stored for {snapshot_date}")
            continue
        status, payload, body = fetch(endpoint, session)
        fetched_at = datetime.now().isoformat(timespec="seconds")
        rows = rows_from(endpoint, payload, snapshot_date, fetched_at) if status == 200 and payload is not None else []
        if status != 200 or not rows:
            failed = True
            detail = f"http {status}, {len(rows)} rows; body head: {body[:200]!r}"
            con.execute("insert into asm_gsm_snapshot_log values (?,?,?,?,?)", (run_at, snapshot_date, endpoint, "FAILED", detail))
            print(f"{endpoint}: FAILED ({detail})", file=sys.stderr)
            if status in (403, 429):
                con.commit()
                break                                         # blocked: stop, do not hammer
            continue
        with con:                                             # raw + parsed rows land together or not at all
            con.execute("insert or ignore into asm_gsm_snapshot_raw values (?,?,?,?,?,?)",
                        (snapshot_date, endpoint, fetched_at, status, len(rows), body))
            con.executemany("insert or ignore into asm_gsm_daily_snapshot values (?,?,?,?,?,?,?,?,?,?,?)", rows)
            con.execute("insert into asm_gsm_snapshot_log values (?,?,?,?,?)", (run_at, snapshot_date, endpoint, "OK", f"{len(rows)} rows"))
        print(f"{endpoint}: stored {len(rows)} rows for {snapshot_date}")
        time.sleep(1.0)
    con.commit()
    con.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

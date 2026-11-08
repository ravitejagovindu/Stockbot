"""scripts/collect_earnings_history.py — Step 12: earnings (results announcement) history from two NSE APIs, into NEW tables only (KI-004).

Sources (only these two; one symbol per request, polite delay, no retry storms):
  api/corporates-financial-results?index=equities&symbol=S&period=Quarterly   -> exchange broadcast / filing timestamps of each results filing
  api/corporate-board-meetings?index=equities&symbol=S&from_date=..&to_date=..  -> board-meeting date + intimation timestamp ("known ahead")

Symbols: every non-fund lake symbol (``market_data_lake``) is queried under its own name; where ``data/reference/isin_symbol_map.csv`` says the ISIN was
renamed (pure_rename chain) the canonical (latest) symbol is queried as well.  Both are recorded in ``earnings_symbol_map``.  The APIs return the ISIN
on every row, so rows can be re-joined by ISIN later.

New tables (nothing existing is altered):
  earnings_api_raw           raw JSON body (zlib-compressed bytes, lossless) per (endpoint, query_symbol)
  earnings_results_filing    parsed results filings (timestamps as ISO text)
  earnings_board_meeting     parsed board meetings; ``is_results_meeting`` + ``results_rule`` say how it was classified
  earnings_symbol_map        lake_symbol -> query_symbol (+ how)
  earnings_collect_log       one row per request: status, rows, note

Resumable: a (endpoint, query_symbol) already in earnings_api_raw is skipped.  Stops (exit 2) after ``--max-consecutive-fail`` consecutive failed
requests (403/429/timeouts), so a block is reported, not hammered.  Not wired into any backtest.

    py scripts/collect_earnings_history.py [--limit N] [--sleep 0.6] [--symbols A,B,...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import zlib
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
}
BASE = "https://www.nseindia.com/api/"
EP_FIN, EP_BM = "corporates-financial-results", "corporate-board-meetings"
FROM_DATE = "01-01-2012"          # a little before the lake (2013) so first-quarter intimations are not cut

DDL = """
CREATE TABLE IF NOT EXISTS earnings_api_raw (
    endpoint TEXT NOT NULL, query_symbol TEXT NOT NULL, fetched_at TEXT NOT NULL, http_status INTEGER NOT NULL,
    row_count INTEGER NOT NULL, body_zlib BLOB NOT NULL, PRIMARY KEY (endpoint, query_symbol));
CREATE TABLE IF NOT EXISTS earnings_results_filing (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query_symbol TEXT NOT NULL, symbol TEXT, isin TEXT, company_name TEXT,
    period TEXT, relating_to TEXT, from_date TEXT, to_date TEXT, audited TEXT, consolidated TEXT, cumulative TEXT, format TEXT,
    filing_ts TEXT, broadcast_ts TEXT, exch_dissem_ts TEXT, seq_number TEXT, params TEXT, xbrl TEXT, row_hash TEXT NOT NULL,
    UNIQUE (query_symbol, row_hash));
CREATE TABLE IF NOT EXISTS earnings_board_meeting (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query_symbol TEXT NOT NULL, symbol TEXT, isin TEXT, company_name TEXT,
    bm_date TEXT, purpose TEXT, description TEXT, intimation_ts TEXT, sys_ts TEXT, attachment TEXT,
    is_results_meeting INTEGER NOT NULL, results_rule TEXT NOT NULL, row_hash TEXT NOT NULL,
    UNIQUE (query_symbol, row_hash));
CREATE TABLE IF NOT EXISTS earnings_symbol_map (
    lake_symbol TEXT NOT NULL, query_symbol TEXT NOT NULL, how TEXT NOT NULL, PRIMARY KEY (lake_symbol, query_symbol));
CREATE TABLE IF NOT EXISTS earnings_collect_log (
    at TEXT NOT NULL, endpoint TEXT NOT NULL, query_symbol TEXT NOT NULL, http_status INTEGER, rows INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS ix_erf_isin ON earnings_results_filing (isin, to_date);
CREATE INDEX IF NOT EXISTS ix_ebm_isin ON earnings_board_meeting (isin, bm_date);
"""

_PURPOSE_RESULTS = re.compile(r"result", re.I)
_DESC_RESULTS = re.compile(r"(financial|quarterly|half[\s-]*yearly|annual|un-?audited|audited)[^.]{0,80}results|results?\s+(for|of)\s+the\s+(quarter|period|year|half)", re.I)


def classify_meeting(purpose: Optional[str], desc: Optional[str]) -> tuple[int, str]:
    """Is this board meeting a results meeting?  Purpose text first; otherwise the description text; otherwise no."""
    if purpose and _PURPOSE_RESULTS.search(purpose):
        return 1, "purpose"
    if desc and _DESC_RESULTS.search(desc):
        return 1, "desc"
    return 0, "none"


def iso_ts(v) -> Optional[str]:
    """'16-Jan-2025 19:42:10' / '16-Jan-2025 19:42' / '16-Jan-2025' -> ISO text; '-', '' or None -> None."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "::", "None"):
        return None
    for fmt, kind in (("%d-%b-%Y %H:%M:%S", "dt"), ("%d-%b-%Y %H:%M", "dt"), ("%d-%b-%Y", "d"), ("%Y-%m-%d", "d")):
        try:
            d = datetime.strptime(s, fmt)
            return d.isoformat(sep=" ") if kind == "dt" else d.date().isoformat()
        except ValueError:
            continue
    return None


def _hash(row: dict) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def parse_results(query_symbol: str, rows: list) -> list[tuple]:
    out = []
    for r in rows:
        out.append((query_symbol, r.get("symbol"), r.get("isin"), r.get("companyName"), r.get("period"), r.get("relatingTo"),
                    iso_ts(r.get("fromDate")), iso_ts(r.get("toDate")), r.get("audited"), r.get("consolidated"), r.get("cumulative"), r.get("format"),
                    iso_ts(r.get("filingDate")), iso_ts(r.get("broadCastDate")), iso_ts(r.get("exchdisstime")), r.get("seqNumber"),
                    r.get("params"), r.get("xbrl"), _hash(r)))
    return out


def parse_meetings(query_symbol: str, rows: list) -> list[tuple]:
    out = []
    for r in rows:
        is_res, rule = classify_meeting(r.get("bm_purpose"), r.get("bm_desc"))
        out.append((query_symbol, r.get("bm_symbol"), r.get("sm_isin"), r.get("sm_name"), iso_ts(r.get("bm_date")), r.get("bm_purpose"),
                    r.get("bm_desc"), iso_ts(r.get("bm_timestamp")), iso_ts(r.get("sysTime")), r.get("attachment"), is_res, rule, _hash(r)))
    return out


class Client:
    def __init__(self, sleep: float):
        self.sleep, self.n, self.consec_fail = sleep, 0, 0
        self._new()

    def _new(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        try:
            self.s.get("https://www.nseindia.com", timeout=20)
        except requests.RequestException:
            pass

    def get(self, endpoint: str, symbol: str) -> tuple[int, Optional[list], str]:
        q = requests.utils.quote(symbol)
        if endpoint == EP_FIN:
            url = f"{BASE}{EP_FIN}?index=equities&symbol={q}&period=Quarterly"
        else:
            url = f"{BASE}{EP_BM}?index=equities&symbol={q}&from_date={FROM_DATE}&to_date={date.today().strftime('%d-%m-%Y')}"
        status, data, text = 0, None, ""
        for attempt in range(2):                                   # one retry with a fresh session, no more
            self.n += 1
            if self.n % 150 == 0:
                self._new()
            try:
                r = self.s.get(url, timeout=30)
                status, text = r.status_code, r.text
                if status == 200:
                    data = r.json()
                    break
                if status in (401, 403, 429):
                    time.sleep(5)
                    self._new()
            except (requests.RequestException, ValueError) as exc:
                status, text = 0, f"{type(exc).__name__}: {exc}"
                time.sleep(3)
        time.sleep(self.sleep)
        ok = status == 200 and isinstance(data, list)
        self.consec_fail = 0 if ok else self.consec_fail + 1
        return status, (data if ok else None), text


def build_query_list(con: sqlite3.Connection, only: Optional[list[str]]) -> list[tuple[str, str, str]]:
    """(lake_symbol, query_symbol, how) for every non-fund lake symbol (+ canonical rename target)."""
    funds = set(pd.read_csv(ROOT / "data/reference/fund_etf_symbols.csv")["symbol"].str.upper())
    lake = [r[0] for r in con.execute("select distinct symbol from market_data_lake")]
    lake = sorted(s for s in lake if s.upper() not in funds and s not in ("NIFTY50_INDEX", "INDIA_VIX"))
    if only:
        lake = [s for s in lake if s in set(only)] + [s for s in only if s not in lake]
    m = pd.read_csv(ROOT / "data/reference/isin_symbol_map.csv")
    canon = {r.symbol: r.canonical_symbol for r in m.itertuples() if isinstance(r.canonical_symbol, str) and r.canonical_symbol != r.symbol}
    out = []
    for s in lake:
        out.append((s, s, "lake_symbol"))
        if s in canon:
            out.append((s, canon[s], "isin_symbol_map"))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--limit", type=int, default=0, help="stop after N query symbols (0 = all)")
    ap.add_argument("--symbols", default="", help="comma list: only these symbols")
    ap.add_argument("--max-consecutive-fail", type=int, default=8)
    args = ap.parse_args(argv)
    con = sqlite3.connect(args.db, timeout=120)
    con.executescript(DDL)
    plan = build_query_list(con, [s for s in args.symbols.split(",") if s] or None)
    con.executemany("insert or ignore into earnings_symbol_map values (?,?,?)", plan)
    con.commit()
    queries = list(dict.fromkeys(q for _, q, _ in plan))
    done = {(r[0], r[1]) for r in con.execute("select endpoint, query_symbol from earnings_api_raw")}
    cl = Client(args.sleep)
    t0, n_done = time.time(), 0
    for i, q in enumerate(queries, 1):
        if args.limit and n_done >= args.limit:
            break
        todo = [ep for ep in (EP_FIN, EP_BM) if (ep, q) not in done]
        if not todo:
            continue
        for ep in todo:
            status, data, text = cl.get(ep, q)
            now = datetime.now().isoformat(timespec="seconds")
            if data is None:
                con.execute("insert into earnings_collect_log values (?,?,?,?,?,?)", (now, ep, q, status, 0, f"FAILED {text[:120]!r}"))
                con.commit()
                if cl.consec_fail >= args.max_consecutive_fail:
                    print(f"STOP: {cl.consec_fail} consecutive failures (last http {status}) at {q} after {i} symbols", file=sys.stderr)
                    return 2
                continue
            with con:
                con.execute("insert or replace into earnings_api_raw values (?,?,?,?,?,?)",
                            (ep, q, now, status, len(data), zlib.compress(json.dumps(data).encode(), 6)))
                if ep == EP_FIN:
                    con.executemany("insert or ignore into earnings_results_filing (query_symbol,symbol,isin,company_name,period,relating_to,from_date,to_date,audited,"
                                    "consolidated,cumulative,format,filing_ts,broadcast_ts,exch_dissem_ts,seq_number,params,xbrl,row_hash) "
                                    "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", parse_results(q, data))
                else:
                    con.executemany("insert or ignore into earnings_board_meeting (query_symbol,symbol,isin,company_name,bm_date,purpose,description,intimation_ts,"
                                    "sys_ts,attachment,is_results_meeting,results_rule,row_hash) values (?,?,?,?,?,?,?,?,?,?,?,?,?)", parse_meetings(q, data))
                con.execute("insert into earnings_collect_log values (?,?,?,?,?,?)", (now, ep, q, status, len(data), "OK"))
        n_done += 1
        if n_done % 100 == 0:
            print(f"{n_done}/{len(queries)} query symbols, {time.time() - t0:.0f}s", flush=True)
    print(f"finished {n_done} query symbols in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

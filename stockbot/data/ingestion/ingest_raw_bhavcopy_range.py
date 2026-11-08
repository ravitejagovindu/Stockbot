"""stockbot/data/ingestion/ingest_raw_bhavcopy_range.py — F2: true RAW daily prices from NSE Bhavcopy into a STAGING table.

Writes ONLY to ``market_data_lake_staging`` and ``bhavcopy_fetch_log`` (never to ``market_data_lake``); the swap into
the lake is a separate, reviewed step (scripts/f2_swap_raw_prices.py). Resumable: dates already logged OK/HOLIDAY are
skipped. Both Bhavcopy formats are handled (legacy ``cmDDMONYYYYbhav.csv.zip`` and the 2024+ UDiFF
``BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip``). EQ series only (same as the existing lake). ISIN and the previous
close are kept: they are used for symbol continuity (renames) and as an independent corporate-action signal.

Usage:
  py -3 stockbot/data/ingestion/ingest_raw_bhavcopy_range.py --start 2020-01-01 --end 2026-09-30 [--db PATH] [--sleep 0.4]
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[3]
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/all-reports",
}
UDIFF_FROM = date(2024, 7, 1)  # UDiFF is tried first from here; legacy first before. Both are always tried.

DDL = """
CREATE TABLE IF NOT EXISTS market_data_lake_staging (
    symbol      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open_raw    REAL NOT NULL,
    high_raw    REAL NOT NULL,
    low_raw     REAL NOT NULL,
    close_raw   REAL NOT NULL,
    volume_raw  BIGINT NOT NULL,
    prev_close  REAL,
    isin        TEXT,
    series      TEXT,
    source      TEXT,
    UNIQUE(symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_mdls_date ON market_data_lake_staging(trade_date);
CREATE INDEX IF NOT EXISTS idx_mdls_isin ON market_data_lake_staging(isin, trade_date);
CREATE TABLE IF NOT EXISTS bhavcopy_fetch_log (
    trade_date  DATE PRIMARY KEY,
    status      TEXT NOT NULL,      -- OK | HOLIDAY_OR_MISSING | ERROR
    n_rows      INTEGER,
    url         TEXT,
    fetched_at  TEXT,
    note        TEXT
);
"""


def candidate_urls(d: date) -> list[str]:
    ymd, dmy = d.strftime("%Y%m%d"), d.strftime("%d%m%Y")
    mon = d.strftime("%b").upper()
    udiff = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
    full = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv"
    legacy = f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/{mon}/cm{d.strftime('%d')}{mon}{d.year}bhav.csv.zip"
    return [udiff, full, legacy] if d >= UDIFF_FROM else [legacy, udiff, full]


def parse_bhavcopy(df: pd.DataFrame, trade_date: date, source: str = "") -> pd.DataFrame:
    """Normalise either Bhavcopy layout to the staging columns (EQ series only)."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    pick = lambda opts: next((c for c in opts if c in df.columns), None)  # noqa: E731
    cols = {
        "series": pick(["SctySrs", "SERIES"]), "symbol": pick(["TckrSymb", "SYMBOL"]),
        "open_raw": pick(["OpnPric", "OPEN_PRICE", "OPEN"]), "high_raw": pick(["HghPric", "HIGH_PRICE", "HIGH"]),
        "low_raw": pick(["LwPric", "LOW_PRICE", "LOW"]), "close_raw": pick(["ClsPric", "CLOSE_PRICE", "CLOSE"]),
        "volume_raw": pick(["TtlTradgVol", "TTL_TRD_QNTY", "TOTTRDQTY"]),
        "prev_close": pick(["PrvsClsgPric", "PREV_CLOSE", "PREVCLOSE"]), "isin": pick(["ISIN"]),
    }
    need = ("series", "symbol", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw")
    if any(cols[k] is None for k in need):
        raise ValueError(f"unrecognised Bhavcopy layout: {list(df.columns)}")
    out = pd.DataFrame({k: (df[v] if v is not None else None) for k, v in cols.items()})
    out = out[out["series"].astype(str).str.strip().str.upper() == "EQ"].copy()
    out["symbol"] = out["symbol"].astype(str).str.strip()
    for c in ("open_raw", "high_raw", "low_raw", "close_raw", "prev_close"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["volume_raw"] = pd.to_numeric(out["volume_raw"], errors="coerce").fillna(0).astype("int64")
    out = out.dropna(subset=["open_raw", "high_raw", "low_raw", "close_raw"])
    out["isin"] = out["isin"].astype(str).str.strip() if "isin" in out else None
    out["series"] = "EQ"
    out["trade_date"] = trade_date.isoformat()
    out["source"] = source
    return out[["symbol", "trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw",
                "prev_close", "isin", "series", "source"]]


def extract_file_date(df: pd.DataFrame) -> Optional[date]:
    """The trade date the file itself declares (DATE1 / TIMESTAMP / TradDt); None if absent or unparseable."""
    cols = {str(c).strip().upper(): c for c in df.columns}
    for key in ("DATE1", "TIMESTAMP", "TRADDT"):
        if key in cols:
            v = str(df[cols[key]].iloc[0]).strip()
            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
    return None


def fetch_day(sess: requests.Session, d: date) -> tuple[Optional[pd.DataFrame], str, str]:
    """Return (parsed_df | None, status, url_or_note). status in OK / HOLIDAY_OR_MISSING / ERROR."""
    last_err = ""
    all_404 = True
    for url in candidate_urls(d):
        for attempt in range(3):
            try:
                r = sess.get(url, timeout=30)
            except requests.RequestException as e:  # network trouble -> retry
                last_err, all_404 = f"{type(e).__name__}: {e}", False
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 404:
                break
            if r.status_code != 200 or len(r.content) < 200:
                last_err, all_404 = f"HTTP {r.status_code} len={len(r.content)}", False
                time.sleep(2 * (attempt + 1))
                continue
            try:
                if url.endswith(".zip"):
                    z = zipfile.ZipFile(io.BytesIO(r.content))
                    raw = pd.read_csv(z.open([n for n in z.namelist() if n.lower().endswith(".csv")][0]))
                else:
                    raw = pd.read_csv(io.StringIO(r.text))
                declared = extract_file_date(raw)
                if declared != d:
                    # NSE answers 200 with the PREVIOUS session's file on holidays (sec_bhavdata_full): never stamp
                    # the requested date on it.  An unreadable date is treated the same way (cannot be verified).
                    last_err = f"file declares {declared}, requested {d}: {url}"
                    break
                parsed = parse_bhavcopy(raw, d, source=url)
            except Exception as e:  # noqa: BLE001
                last_err, all_404 = f"parse error: {e}", False
                break
            if parsed.empty:
                last_err, all_404 = "no EQ rows", False
                break
            return parsed, "OK", url
    if all_404 or last_err.startswith("file declares"):
        return None, "HOLIDAY_OR_MISSING", last_err or "all candidate URLs 404"
    return None, "ERROR", last_err


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--all-days", action="store_true", help="also try Saturdays/Sundays (special sessions)")
    ap.add_argument("--redo", help="comma-separated dates to re-fetch even if already logged")
    ap.add_argument("--retry-errors", action="store_true", help="re-fetch dates logged ERROR")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    con = sqlite3.connect(args.db, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(DDL)
    done = {r[0] for r in con.execute(
        "select trade_date from bhavcopy_fetch_log where status in ('OK','HOLIDAY_OR_MISSING')"
        + ("" if args.retry_errors else " or status='ERROR'"))}
    redo = set((args.redo or "").split(",")) - {""}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    d, n_ok, n_hol, n_err = start, 0, 0, 0
    t0 = time.time()
    while d <= end:
        if (d.weekday() >= 5 and not args.all_days) or (d.isoformat() in done and d.isoformat() not in redo):
            d += timedelta(days=1)
            continue
        df, status, info = fetch_day(sess, d)
        now = datetime.now().isoformat(timespec="seconds")
        if status == "OK":
            with con:
                con.execute("DELETE FROM market_data_lake_staging WHERE trade_date=?", (d.isoformat(),))
                df.to_sql("market_data_lake_staging", con, if_exists="append", index=False)
                con.execute("INSERT OR REPLACE INTO bhavcopy_fetch_log VALUES (?,?,?,?,?,?)",
                            (d.isoformat(), "OK", len(df), info, now, None))
            n_ok += 1
        else:
            with con:
                if status == "HOLIDAY_OR_MISSING":  # a re-fetched date that is not a session must not keep stale rows
                    con.execute("DELETE FROM market_data_lake_staging WHERE trade_date=?", (d.isoformat(),))
                con.execute("INSERT OR REPLACE INTO bhavcopy_fetch_log VALUES (?,?,?,?,?,?)",
                            (d.isoformat(), status, 0, None, now, info))
            n_hol += status == "HOLIDAY_OR_MISSING"
            n_err += status == "ERROR"
        if (n_ok + n_hol + n_err) % 25 == 0:
            print(f"{d} ok={n_ok} holiday/missing={n_hol} error={n_err} elapsed={time.time() - t0:.0f}s", flush=True)
        time.sleep(args.sleep)
        d += timedelta(days=1)
    print(f"DONE ok={n_ok} holiday/missing={n_hol} error={n_err} elapsed={time.time() - t0:.0f}s", flush=True)
    con.close()


if __name__ == "__main__":
    sys.exit(main())

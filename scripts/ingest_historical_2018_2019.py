"""Standalone one-time utility to ingest 2018 and 2019 historical NSE Bhavcopy and indices.

100% PURE NSE ARCHIVES:
  - Equities: https://archives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.zip
  - Indices:  https://archives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv (Nifty 50 & India VIX)

Completely decoupled from the core trading engine.
Touches ONLY the market_data_lake table for dates between 2018-01-01 and 2019-12-31.
"""
from __future__ import annotations

import io
import logging
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import requests
from sqlalchemy import text

from data.db.connection import get_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pure_nse_ingestor_2018_2019")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/all-reports",
}


def get_weekday_range(start_d: date, end_d: date) -> list[date]:
    """Return all Mondays through Fridays between start_d and end_d inclusive."""
    cur = start_d
    dates = []
    while cur <= end_d:
        if cur.weekday() < 5:  # Mon=0, Fri=4
            dates.append(cur)
        cur += timedelta(days=1)
    return dates


def ingest_indices_for_date(target_date: date, http_session: requests.Session) -> int:
    """Download daily Index Bhavcopy from NSE archives and insert NIFTY50_INDEX and INDIA_VIX."""
    d_str = target_date.strftime("%d")
    m_num = target_date.strftime("%m")
    y = target_date.strftime("%Y")

    url = f"https://archives.nseindia.com/content/indices/ind_close_all_{d_str}{m_num}{y}.csv"

    try:
        resp = http_session.get(url, timeout=15)
        if resp.status_code == 404:
            return 0
        if resp.status_code != 200 or len(resp.content) < 100:
            return 0

        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [str(c).strip() for c in df.columns]

        idx_name_col = next((c for c in ["Index Name", "INDEX_NAME"] if c in df.columns), None)
        close_col = next((c for c in ["Closing Index Value", "CLOSE_INDEX_VAL", "CLOSE"] if c in df.columns), None)
        open_col = next((c for c in ["Open Index Value", "OPEN_INDEX_VAL", "OPEN"] if c in df.columns), None)
        high_col = next((c for c in ["High Index Value", "HIGH_INDEX_VAL", "HIGH"] if c in df.columns), None)
        low_col = next((c for c in ["Low Index Value", "LOW_INDEX_VAL", "LOW"] if c in df.columns), None)

        if not (idx_name_col and close_col):
            return 0

        target_map = {
            "NIFTY 50": "NIFTY50_INDEX",
            "INDIA VIX": "INDIA_VIX",
        }

        records = []
        td_str = str(target_date)

        for _, row in df.iterrows():
            name_raw = str(row[idx_name_col]).strip().upper()
            if name_raw in target_map:
                db_symbol = target_map[name_raw]
                try:
                    c = float(str(row[close_col]).replace(",", "").strip())
                    o = float(str(row[open_col]).replace(",", "").strip()) if open_col and pd.notna(row.get(open_col)) else c
                    h = float(str(row[high_col]).replace(",", "").strip()) if high_col and pd.notna(row.get(high_col)) else c
                    l = float(str(row[low_col]).replace(",", "").strip()) if low_col and pd.notna(row.get(low_col)) else c
                except (ValueError, TypeError):
                    continue

                records.append(
                    {
                        "symbol": db_symbol,
                        "trade_date": td_str,
                        "open_raw": o,
                        "high_raw": h,
                        "low_raw": l,
                        "close_raw": c,
                        "volume_raw": 0,
                        "exchange": "NSE",
                    }
                )

        if records:
            with get_session() as session:
                stmt = text("""
                    INSERT OR REPLACE INTO market_data_lake
                    (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange)
                    VALUES (:symbol, :trade_date, :open_raw, :high_raw, :low_raw, :close_raw, :volume_raw, :exchange)
                """)
                session.execute(stmt, records)
                session.commit()

        return len(records)

    except Exception as e:
        logger.warning(f"Error fetching index report for {target_date}: {e}")
        return 0


def ingest_bhavcopy_for_date(target_date: date, http_session: requests.Session) -> int:
    """Download single daily Equity Bhavcopy zip from NSE archives and insert EQ series rows."""
    y = target_date.strftime("%Y")
    m_str = target_date.strftime("%b").upper()
    d_str = target_date.strftime("%d")

    url = f"https://archives.nseindia.com/content/historical/EQUITIES/{y}/{m_str}/cm{d_str}{m_str}{y}bhav.csv.zip"

    try:
        resp = http_session.get(url, timeout=15)
        if resp.status_code == 404:
            return 0
        if resp.status_code != 200 or len(resp.content) < 100:
            return 0

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            csv_candidates = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not csv_candidates:
                return 0
            with z.open(csv_candidates[0]) as f:
                df_raw = pd.read_csv(f)

        df_raw.columns = [str(c).strip() for c in df_raw.columns]

        # Identify EQ series
        series_col = next((c for c in ["SERIES", "SctySrs"] if c in df_raw.columns), None)
        if not series_col:
            return 0

        df_eq = df_raw[df_raw[series_col].astype(str).str.strip().str.upper() == "EQ"].copy()
        if df_eq.empty:
            return 0

        sym_col = next((c for c in ["SYMBOL", "TckrSymb"] if c in df_eq.columns), None)
        open_col = next((c for c in ["OPEN", "OPEN_PRICE", "OpnPric"] if c in df_eq.columns), None)
        high_col = next((c for c in ["HIGH", "HIGH_PRICE", "HghPric"] if c in df_eq.columns), None)
        low_col = next((c for c in ["LOW", "LOW_PRICE", "LwPric"] if c in df_eq.columns), None)
        close_col = next((c for c in ["CLOSE", "CLOSE_PRICE", "ClsPric"] if c in df_eq.columns), None)
        vol_col = next((c for c in ["TOTTRDQTY", "TTL_TRD_QNTY", "TtlTradgVol"] if c in df_eq.columns), None)

        if not all([sym_col, open_col, high_col, low_col, close_col, vol_col]):
            return 0

        records = []
        td_str = str(target_date)
        for _, row in df_eq.iterrows():
            sym = str(row[sym_col]).strip().upper()
            if not sym:
                continue
            try:
                o = float(row[open_col])
                h = float(row[high_col])
                l = float(row[low_col])
                c = float(row[close_col])
                v = int(row[vol_col])
            except (ValueError, TypeError):
                continue

            records.append(
                {
                    "symbol": sym,
                    "trade_date": td_str,
                    "open_raw": o,
                    "high_raw": h,
                    "low_raw": l,
                    "close_raw": c,
                    "volume_raw": v,
                    "exchange": "NSE",
                }
            )

        if not records:
            return 0

        # Batch insert
        with get_session() as session:
            stmt = text("""
                INSERT OR REPLACE INTO market_data_lake
                (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange)
                VALUES (:symbol, :trade_date, :open_raw, :high_raw, :low_raw, :close_raw, :volume_raw, :exchange)
            """)
            session.execute(stmt, records)
            session.commit()

        return len(records)

    except Exception as e:
        logger.error(f"Error processing {target_date}: {e}")
        return 0


def run_pure_nse_ingestion(start_d: date = date(2018, 1, 1), end_d: date = date(2019, 12, 31)) -> None:
    """Download and ingest all Bhavcopy files for weekdays in range from pure NSE archives."""
    weekdays = get_weekday_range(start_d, end_d)
    logger.info(f"Total potential trading days to process: {len(weekdays)}")

    # Check already ingested dates
    with get_session() as session:
        existing_dates_raw = session.execute(
            text("""
                SELECT DISTINCT trade_date FROM market_data_lake
                WHERE trade_date BETWEEN :s AND :e
                AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')
            """),
            {"s": str(start_d), "e": str(end_d)},
        ).scalars().all()

    existing_set = {date.fromisoformat(str(d)) for d in existing_dates_raw}
    logger.info(f"Already ingested dates in database: {len(existing_set)}")

    http_sess = requests.Session()
    http_sess.headers.update(HEADERS)

    ingested_days = 0
    total_eq_rows = 0

    t_start = time.time()
    for idx, d in enumerate(weekdays, 1):
        if d in existing_set:
            continue

        t0 = time.time()
        # 1. Ingest Equities from NSE Equity Bhavcopy
        eq_cnt = ingest_bhavcopy_for_date(d, http_sess)
        
        # 2. Ingest Indices (Nifty 50 and India VIX) from NSE Index archive
        idx_cnt = ingest_indices_for_date(d, http_sess)
        
        dt = time.time() - t0

        if eq_cnt > 0:
            ingested_days += 1
            total_eq_rows += eq_cnt
            logger.info(
                f"[{idx}/{len(weekdays)}] {d}: Ingested {eq_cnt:,} EQ stocks + {idx_cnt} indices in {dt:.2f}s "
                f"(Total: {total_eq_rows:,} rows across {ingested_days} days)"
            )
        else:
            logger.info(f"[{idx}/{len(weekdays)}] {d}: Exchange Holiday / Weekend")

        # Brief rate-limiting pause to respect NSE archive servers
        time.sleep(0.1)

    total_time = time.time() - t_start
    logger.info(
        f"Completed 100% Pure NSE 2018-2019 ingestion: {total_eq_rows:,} rows across {ingested_days} sessions in {total_time/60:.1f} minutes."
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="100% Pure NSE Historical Bhavcopy & Index Ingestor")
    parser.add_argument("--start", default="2018-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2019-12-31", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)

    logger.info(f"=== Starting 100% Pure NSE Historical Ingestion ({start_d} to {end_d}) ===")
    run_pure_nse_ingestion(start_d, end_d)
    logger.info("=== Finished 100% Pure NSE Historical Ingestion ===")


if __name__ == "__main__":
    main()

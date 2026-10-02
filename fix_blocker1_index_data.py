"""
Blocker 1 Fix: Ingest Nifty50 Index and India VIX into finsight.db

Downloads ^NSEI and ^INDIAVIX from Yahoo Finance and inserts them into
market_data_lake using the symbol names the engine expects:
  - NIFTY50_INDEX
  - INDIA_VIX
"""
import sys
sys.path.append(r"f:\Projects\Ravi\StockBot")

import yfinance as yf
import pandas as pd
from sqlalchemy import text
from data.db.connection import engine

START_DATE = "2020-01-01"
END_DATE = "2026-09-30"

INDEX_MAP = {
    "^NSEI":    "NIFTY50_INDEX",
    "^INDIAVIX": "INDIA_VIX",
}

def ingest_index(yf_ticker: str, db_symbol: str):
    print(f"Downloading {yf_ticker} -> storing as '{db_symbol}'...")
    df = yf.download(yf_ticker, start=START_DATE, end=END_DATE, progress=False)
    if df.empty:
        print(f"  ERROR: No data returned for {yf_ticker}")
        return 0

    df.reset_index(inplace=True)
    df.columns = [c[0].strip().lower() if isinstance(c, tuple) else c.strip().lower() for c in df.columns]

    rename_map = {
        "date": "trade_date",
        "open": "open_raw",
        "high": "high_raw",
        "low":  "low_raw",
        "close": "close_raw",
        "volume": "volume_raw",
    }
    df.rename(columns=rename_map, inplace=True)

    required = ["trade_date", "open_raw", "high_raw", "low_raw", "close_raw"]
    for col in required:
        if col not in df.columns:
            print(f"  ERROR: Missing column '{col}' in downloaded data. Columns: {list(df.columns)}")
            return 0

    df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True, errors="coerce").dt.date
    df["symbol"]   = db_symbol
    df["exchange"] = "NSE"

    # Fill missing volume with 0 (indices have no volume)
    if "volume_raw" not in df.columns:
        df["volume_raw"] = 0
    df["volume_raw"] = df["volume_raw"].fillna(0).astype(int)

    keep = ["trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "symbol", "exchange"]
    df = df[[c for c in keep if c in df.columns]].dropna(subset=["trade_date", "close_raw"])

    # Delete existing rows for this symbol to avoid UNIQUE constraint violations
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM market_data_lake WHERE symbol = '{db_symbol}'"))

    df.to_sql("market_data_lake", engine, if_exists="append", index=False, chunksize=2000)
    print(f"  SUCCESS: Inserted {len(df):,} rows for '{db_symbol}'")
    return len(df)

if __name__ == "__main__":
    total = 0
    for yf_ticker, db_symbol in INDEX_MAP.items():
        total += ingest_index(yf_ticker, db_symbol)
    print(f"\nDone. Total rows inserted: {total:,}")

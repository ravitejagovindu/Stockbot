"""
Blocker 2 Fix: Populate shares_outstanding table for all symbols in market_data_lake

Uses yfinance Ticker.info["sharesOutstanding"] to get the current shares count
for each symbol and inserts one row per symbol with effective_date = 2020-01-01.
This allows the PIT Market Cap gate to work for all backtest dates from 2020 onwards.

Note: Yahoo Finance only provides current shares outstanding, not historical.
This is an accepted limitation for retail backtesting purposes.
"""
import sys
sys.path.append(r"f:\Projects\Ravi\StockBot")

import time
import yfinance as yf
import pandas as pd
from sqlalchemy import text
from data.db.connection import engine

EFFECTIVE_DATE = "2020-01-01"
BATCH_SIZE = 50  # Insert in batches

def get_all_symbols():
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT symbol FROM market_data_lake "
            "WHERE symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX') "
            "ORDER BY symbol"
        ))
        return [row[0] for row in result]

def get_already_done():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT symbol FROM shares_outstanding"))
        return set(row[0] for row in result)

def main():
    symbols = get_all_symbols()
    already_done = get_already_done()
    remaining = [s for s in symbols if s not in already_done]

    print(f"Total symbols in DB: {len(symbols)}")
    print(f"Already in shares_outstanding: {len(already_done)}")
    print(f"Remaining to fetch: {len(remaining)}")

    rows_to_insert = []
    skipped = 0
    fetched = 0

    for i, sym in enumerate(remaining, 1):
        yf_sym = f"{sym}.NS"
        try:
            info = yf.Ticker(yf_sym).info
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if shares and shares > 0:
                rows_to_insert.append({
                    "symbol": sym,
                    "effective_date": EFFECTIVE_DATE,
                    "shares_count": int(shares),
                    "source": "yahoo_finance_current"
                })
                fetched += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

        # Batch insert every BATCH_SIZE symbols
        if len(rows_to_insert) >= BATCH_SIZE:
            _insert_batch(rows_to_insert)
            rows_to_insert = []

        if i % 100 == 0:
            print(f"Progress: {i}/{len(remaining)} | Fetched: {fetched} | Skipped: {skipped}")

        # Small delay to avoid rate limiting
        time.sleep(0.3)

    # Insert any remaining rows
    if rows_to_insert:
        _insert_batch(rows_to_insert)

    print(f"\nDone! Inserted shares data for {fetched} symbols. Skipped {skipped} (no data available).")

def _insert_batch(rows: list):
    df = pd.DataFrame(rows)
    df.to_sql("shares_outstanding", engine, if_exists="append", index=False)

if __name__ == "__main__":
    main()

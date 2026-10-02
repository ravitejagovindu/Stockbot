"""
Local CSV Ingestor

Reads historical CSV files from the standalone scraper output folder 
and bulk-inserts them into the finsight.db SQLite database.
"""
import os
import glob
import pandas as pd
from pathlib import Path
import logging
import sys

# Ensure StockBot modules can be loaded
sys.path.append(str(Path(__file__).resolve().parents[2]))

from data.db.connection import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CSV_FOLDER = r"f:\Projects\Ravi\NSE_Standalone_Scraper\output_yahoo_csvs"

def ingest_all():
    csv_files = glob.glob(os.path.join(CSV_FOLDER, "*_historical.csv"))
    if not csv_files:
        logger.error(f"No CSV files found in {CSV_FOLDER}. Make sure the path is correct.")
        return

    logger.info(f"Found {len(csv_files)} CSV files. Starting bulk ingestion...")

    total_rows = 0
    for idx, filepath in enumerate(csv_files, 1):
        filename = os.path.basename(filepath)
        symbol = filename.replace("_historical.csv", "")

        try:
            df = pd.read_csv(filepath)
            if df.empty:
                continue

            # Standardize columns to lowercase
            df.columns = [c.strip().lower() for c in df.columns]
            
            # Map Yahoo columns to Database columns
            rename_map = {
                "date": "trade_date",
                "open": "open_raw",
                "high": "high_raw",
                "low": "low_raw",
                "close": "close_raw",
                "volume": "volume_raw"
            }
            
            valid_cols = []
            for yf_col, db_col in rename_map.items():
                if yf_col in df.columns:
                    df.rename(columns={yf_col: db_col}, inplace=True)
                    valid_cols.append(db_col)
                
            if "trade_date" not in df.columns or "close_raw" not in df.columns:
                logger.warning(f"Skipping {symbol}: Missing required columns.")
                continue
                
            # Filter just the columns we need
            df = df[valid_cols].copy()
            
            # Convert date strings to actual date objects
            df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True).dt.date
            
            # Add the symbol and exchange metadata
            df["symbol"] = symbol
            df["exchange"] = "NSE"
            
            # Drop rows with missing crucial price data or missing trade dates (from Yahoo's sub-headers)
            df.dropna(subset=["trade_date", "close_raw"], inplace=True)

            if df.empty:
                continue

            # Bulk append to the database using pandas. 
            # Note: If running this multiple times, you may get IntegrityError 
            # if the table enforces UNIQUE(symbol, trade_date).
            try:
                df.to_sql(
                    name="market_data_lake",
                    con=engine,
                    if_exists="append",
                    index=False,
                    chunksize=5000,
                    method="multi"
                )
                total_rows += len(df)
            except Exception as sql_err:
                # If there's an integrity error (e.g. data already exists), just warn and skip
                if "IntegrityError" in str(type(sql_err)) or "UNIQUE constraint failed" in str(sql_err):
                    logger.warning(f"[{symbol}] Data already exists in DB. Skipping to avoid duplicates.")
                else:
                    raise sql_err

            if idx % 100 == 0:
                logger.info(f"Processed {idx}/{len(csv_files)} stocks... (Total rows inserted: {total_rows:,})")

        except Exception as e:
            logger.error(f"Failed to process {symbol}: {e}")

    logger.info(f"Ingestion complete! Successfully inserted {total_rows:,} rows into finsight.db.")

if __name__ == "__main__":
    ingest_all()

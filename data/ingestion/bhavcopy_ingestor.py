"""
FInsight Trading Engine — NSE Bhavcopy Ingestor
===============================================
Downloads the official NSE End-of-Day Bhavcopy ZIP, parses the CSV,
and bulk-inserts the EQ (Equity) series data into the market_data_lake.
"""
import io
import zipfile
import logging
import requests
import pandas as pd
from datetime import date
from sqlalchemy import text
from sqlalchemy.orm import Session
from data.db.connection import engine

logger = logging.getLogger(__name__)

class BhavcopyIngestor:
    def __init__(self, config: dict):
        self.config = config
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    def _get_url(self, target_date: date) -> str:
        """Constructs the NSE Bhavcopy URL for a given date."""
        month_str = target_date.strftime("%b").upper()
        day_str = target_date.strftime("%d")
        year_str = target_date.strftime("%Y")
        return f"https://archives.nseindia.com/content/historical/EQUITIES/{year_str}/{month_str}/cm{day_str}{month_str}{year_str}bhav.csv.zip"

    def ingest(self, session: Session, target_date: date) -> int:
        """
        Downloads Bhavcopy for target_date and inserts EQ rows into DB.
        Returns the number of rows inserted.
        """
        url = self._get_url(target_date)
        logger.info(f"Fetching Bhavcopy for {target_date}: {url}")

        try:
            # 1. Download the ZIP file
            response = requests.get(url, headers=self.headers, timeout=15)
            if response.status_code == 404:
                logger.info(f"No Bhavcopy found for {target_date} (likely a holiday/weekend).")
                return 0
            response.raise_for_status()

            # 2. Extract and parse CSV
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                # The zip usually contains one file: cmDDMONYYYYbhav.csv
                csv_filename = z.namelist()[0]
                with z.open(csv_filename) as f:
                    df = pd.read_csv(f)

            # 3. Filter for Equities (EQ) only
            df = df[df["SERIES"] == "EQ"].copy()
            if df.empty:
                logger.warning(f"No EQ series found in Bhavcopy for {target_date}.")
                return 0

            # 4. Map to DB schema
            rename_map = {
                "SYMBOL": "symbol",
                "OPEN": "open_raw",
                "HIGH": "high_raw",
                "LOW": "low_raw",
                "CLOSE": "close_raw",
                "TOTTRDQTY": "volume_raw"
            }
            df.rename(columns=rename_map, inplace=True)
            df["trade_date"] = target_date
            df["exchange"] = "NSE"
            
            # Keep only required columns
            cols_to_keep = ["symbol", "trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "exchange"]
            df = df[[c for c in cols_to_keep if c in df.columns]]

            # 5. Insert into Database
            # To prevent UNIQUE constraint errors, clear existing equity data for this date
            # (Excluding NIFTY50_INDEX and INDIA_VIX which are populated separately)
            session.execute(
                text(
                    "DELETE FROM market_data_lake WHERE trade_date = :td "
                    "AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')"
                ),
                {"td": target_date}
            )
            
            # Bulk insert using pandas
            df.to_sql("market_data_lake", con=engine, if_exists="append", index=False)
            session.commit()

            logger.info(f"Successfully ingested {len(df)} symbols from Bhavcopy for {target_date}.")
            return len(df)

        except Exception as e:
            logger.error(f"Failed to ingest Bhavcopy for {target_date}: {str(e)}")
            session.rollback()
            raise

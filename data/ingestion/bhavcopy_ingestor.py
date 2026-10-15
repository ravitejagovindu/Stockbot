"""
FInsight Trading Engine — NSE Bhavcopy Ingestor
===============================================
Downloads the official NSE End-of-Day Bhavcopy (supporting both modern
CM UDID zip format, full bhavdata csv, and legacy archives), parses the CSV,
and bulk-inserts the EQ (Equity) series data into market_data_lake.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
import pandas as pd
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session
from data.db.connection import engine

logger = logging.getLogger(__name__)


class BhavcopyIngestor:
    def __init__(self, config: dict):
        self.config = config
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.nseindia.com/all-reports",
        }

    def _get_candidate_urls(self, target_date: date) -> list[tuple[str, str]]:
        """
        Returns list of (url, format_type) candidates in priority order:
        1. Modern NSE CM UDID format (.csv.zip)
        2. Modern daily full bhavdata (.csv)
        3. Legacy historical archive (.csv.zip)
        """
        ymd = target_date.strftime("%Y%m%d")
        dmy = target_date.strftime("%d%m%Y")
        y = target_date.strftime("%Y")
        m_str = target_date.strftime("%b").upper()
        d_str = target_date.strftime("%d")

        return [
            # Primary: Modern NSE CM UDID format introduced 2024
            (
                f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
                "zip",
            ),
            # Fallback 1: Direct full bhavdata CSV
            (
                f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dmy}.csv",
                "csv",
            ),
            # Fallback 2: Pre-2024 legacy archive URL
            (
                f"https://archives.nseindia.com/content/historical/EQUITIES/{y}/{m_str}/cm{d_str}{m_str}{y}bhav.csv.zip",
                "zip",
            ),
        ]

    def ingest(self, session: Session, target_date: date) -> int:
        """
        Downloads Bhavcopy for target_date and inserts EQ rows into DB.
        Returns the number of rows inserted (0 if holiday/weekend).
        """
        candidate_urls = self._get_candidate_urls(target_date)
        df_raw: pd.DataFrame | None = None

        with requests.Session() as s:
            s.headers.update(self.headers)
            for url, fmt in candidate_urls:
                try:
                    logger.debug(f"Trying Bhavcopy URL: {url}")
                    resp = s.get(url, timeout=15)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        if fmt == "zip":
                            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                                csv_filename = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
                                with z.open(csv_filename) as f:
                                    df_raw = pd.read_csv(f)
                        else:
                            df_raw = pd.read_csv(io.StringIO(resp.text))
                        logger.info(f"Successfully downloaded Bhavcopy from {url}")
                        break
                    elif resp.status_code == 404:
                        continue
                    else:
                        logger.warning(f"Bhavcopy fetch status {resp.status_code} for {url}")
                except Exception as ex:
                    logger.debug(f"Candidate URL {url} failed: {ex}")
                    continue

        if df_raw is None or df_raw.empty:
            logger.info(f"No Bhavcopy found for {target_date} (likely a holiday/weekend).")
            return 0

        try:
            # Clean and strip column names
            df_raw.columns = [str(c).strip() for c in df_raw.columns]

            # 1. Identify and filter for Equities ('EQ')
            series_col = next((c for c in ["SctySrs", "SERIES"] if c in df_raw.columns), None)
            if not series_col:
                logger.warning(f"Series column not found in Bhavcopy for {target_date}.")
                return 0

            df = df_raw[df_raw[series_col].astype(str).str.strip().str.upper() == "EQ"].copy()
            if df.empty:
                logger.warning(f"No EQ series found in Bhavcopy for {target_date}.")
                return 0

            # 2. Identify symbol column
            sym_col = next((c for c in ["TckrSymb", "SYMBOL"] if c in df.columns), None)
            if not sym_col:
                raise ValueError("Symbol column not found in Bhavcopy.")

            # 3. Identify price & volume columns
            open_col = next((c for c in ["OpnPric", "OPEN_PRICE", "OPEN"] if c in df.columns), None)
            high_col = next((c for c in ["HghPric", "HIGH_PRICE", "HIGH"] if c in df.columns), None)
            low_col = next((c for c in ["LwPric", "LOW_PRICE", "LOW"] if c in df.columns), None)
            close_col = next((c for c in ["ClsPric", "CLOSE_PRICE", "CLOSE"] if c in df.columns), None)
            vol_col = next((c for c in ["TtlTradgVol", "TTL_TRD_QNTY", "TOTTRDQTY"] if c in df.columns), None)

            rename_map = {
                sym_col: "symbol",
                open_col: "open_raw",
                high_col: "high_raw",
                low_col: "low_raw",
                close_col: "close_raw",
                vol_col: "volume_raw",
            }

            df.rename(columns=rename_map, inplace=True)
            df["symbol"] = df["symbol"].astype(str).str.strip()
            df["trade_date"] = target_date
            df["exchange"] = "NSE"

            # Numeric conversion
            for col in ["open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            cols_to_keep = ["symbol", "trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "exchange"]
            df = df[cols_to_keep]

            # 4. Insert into Database
            # Delete existing equity data for this date to prevent duplicate collisions
            session.execute(
                text(
                    "DELETE FROM market_data_lake WHERE trade_date = :td "
                    "AND symbol NOT IN ('NIFTY50_INDEX', 'INDIA_VIX')"
                ),
                {"td": target_date},
            )

            df.to_sql("market_data_lake", con=engine, if_exists="append", index=False)
            session.commit()

            logger.info(f"Successfully ingested {len(df)} symbols from Bhavcopy for {target_date}.")
            return len(df)

        except Exception as e:
            logger.error(f"Failed to ingest Bhavcopy for {target_date}: {str(e)}")
            session.rollback()
            raise


"""data/ingestion/securities_ingestor.py — Bulk Ingestor for NSE Listed Securities Master."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional
import urllib.request
from sqlalchemy import text

from data.db.connection import get_session

logger = logging.getLogger(__name__)

_EQUITY_L_URLS = [
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
]
_CACHE_PATH = Path(__file__).resolve().parents[1] / "reference" / "EQUITY_L.csv"


def _parse_nse_date(date_str: str) -> Optional[date]:
    """Parse dates in formats like '08-FEB-1995', '8-Feb-1995', or '1995-02-08'."""
    clean = date_str.strip()
    if not clean or clean.upper() in ("N/A", "NA", "-"):
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    logger.warning(f"[SECURITIES] Unrecognized date format: '{date_str}'")
    return None


def fetch_equity_l_content() -> str:
    """Download EQUITY_L.csv from NSE or fallback to cached reference file."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for url in _EQUITY_L_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                if "SYMBOL" in content and "DATE OF LISTING" in content:
                    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    _CACHE_PATH.write_text(content, encoding="utf-8")
                    logger.info(f"[SECURITIES] Successfully fetched EQUITY_L.csv from {url}")
                    return content
        except Exception as e:
            logger.warning(f"[SECURITIES] Failed to fetch from {url}: {e}")

    # Fallback to local cache if offline or blocked
    if _CACHE_PATH.exists():
        logger.info(f"[SECURITIES] Using cached EQUITY_L.csv from {_CACHE_PATH}")
        return _CACHE_PATH.read_text(encoding="utf-8")

    raise RuntimeError("Failed to fetch EQUITY_L.csv from NSE and no local cache available.")


def ingest_securities_master() -> int:
    """Download official NSE securities list and upsert into securities_master table."""
    content = fetch_equity_l_content()
    reader = csv.DictReader(io.StringIO(content))

    records = []
    for raw_row in reader:
        # Strip whitespace from keys and values
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}
        sym = row.get("SYMBOL", "").strip().upper()
        if not sym:
            continue

        raw_date = row.get("DATE OF LISTING") or row.get("DATE_OF_LISTING") or ""
        parsed_date = _parse_nse_date(raw_date)
        if not parsed_date:
            continue

        company_name = row.get("NAME OF COMPANY") or row.get("NAME_OF_COMPANY") or ""
        series = row.get("SERIES", "EQ")
        isin = row.get("ISIN NUMBER") or row.get("ISIN") or ""

        records.append({
            "symbol": sym,
            "company_name": company_name[:200],
            "series": series[:10],
            "listing_date": str(parsed_date),
            "isin": isin[:30],
        })

    if not records:
        logger.warning("[SECURITIES] No valid securities found to ingest.")
        return 0

    with get_session() as s:
        # Bulk upsert using INSERT OR REPLACE INTO SQLite
        s.execute(
            text("""
                INSERT OR REPLACE INTO securities_master (symbol, company_name, series, listing_date, isin)
                VALUES (:symbol, :company_name, :series, :listing_date, :isin)
            """),
            records,
        )
        s.commit()

    logger.info(f"[SECURITIES] Ingested {len(records)} securities into securities_master.")
    return len(records)


def fetch_and_save_symbol_listing_date(symbol: str, session=None) -> Optional[date]:
    """Fallback fetch for a single symbol from NSE live Quote API and persist to DB."""
    sym = symbol.strip().upper()
    try:
        from data.ingestion.base_ingestor import BaseIngestor
        ingestor = BaseIngestor()
        nse_sess = ingestor._get_nse_session()
        quote_url = f"https://www.nseindia.com/api/quote-equity?symbol={sym}"
        resp = nse_sess.get(quote_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            meta = data.get("metadata", {})
            raw_date = meta.get("listingDate")
            if raw_date:
                parsed = _parse_nse_date(raw_date)
                if parsed:
                    c_name = meta.get("companyName", "")
                    isin = meta.get("isin", "")
                    
                    def _insert(s):
                        s.execute(
                            text("""
                                INSERT OR REPLACE INTO securities_master (symbol, company_name, series, listing_date, isin)
                                VALUES (:symbol, :company_name, 'EQ', :listing_date, :isin)
                            """),
                            {"symbol": sym, "company_name": c_name[:200], "listing_date": str(parsed), "isin": isin[:30]},
                        )
                        s.commit()

                    if session:
                        _insert(session)
                    else:
                        with get_session() as s:
                            _insert(s)
                    logger.info(f"[SECURITIES] Live fetched & saved listing date for {sym}: {parsed}")
                    return parsed
    except Exception as exc:
        logger.warning(f"[SECURITIES] On-demand quote fetch failed for {sym}: {exc}")
    return None


if __name__ == "__main__":
    count = ingest_securities_master()
    print(f"Successfully ingested {count} securities into securities_master.")

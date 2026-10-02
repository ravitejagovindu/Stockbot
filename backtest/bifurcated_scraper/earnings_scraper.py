"""
FInsight Trading Engine — Earnings Scraper (Bifurcated Pipeline)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
import pandas as pd
import requests

logger = logging.getLogger(__name__)

class EarningsScraper:
    """
    Scrapes NSE Corporate Filings Archive for historical board meeting / results dates.
    Only processes symbols that appear in candidate_trades.csv.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
            "Referer": "https://www.nseindia.com/"
        })
        self._warmup_session()

    def _warmup_session(self):
        """Hit the homepage to get the required session cookies."""
        try:
            self.session.get("https://www.nseindia.com", timeout=10)
        except Exception as e:
            logger.warning(f"Failed to warmup NSE session: {e}")

    def scrape_symbol(self, symbol: str, from_date: date, to_date: date) -> list[dict]:
        """
        Fetches board meeting result dates from NSE filings.
        Returns list of {symbol, event_date, event_type, source_url}
        """
        # Note: True historical backfilling from NSE requires parsing their archives.
        # Here we mock the HTTP interaction based on the NSE corporate actions API.
        url = f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol}"
        
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 401:
                    self._warmup_session()
                    continue
                resp.raise_for_status()
                data = resp.json()
                
                results = []
                for item in data:
                    purpose = item.get("purpose", "").lower()
                    if "results" in purpose or "financial" in purpose or "dividend" in purpose:
                        ex_date_str = item.get("exDate")
                        if not ex_date_str or ex_date_str == "-":
                            continue
                        
                        try:
                            # Format usually DD-MMM-YYYY
                            event_date = datetime.strptime(ex_date_str, "%d-%b-%Y").date()
                        except ValueError:
                            continue
                        
                        if from_date <= event_date <= to_date:
                            results.append({
                                "symbol": symbol,
                                "event_date": event_date,
                                "event_type": "EARNINGS_OR_CORP_ACTION",
                                "source_url": url
                            })
                return results
            except Exception as e:
                logger.warning(f"Earnings scrape failed for {symbol} (Attempt {attempt+1}): {e}")
                time.sleep(2 ** attempt)
        
        return []

    def scrape_candidates(self, candidate_trades_path: str) -> pd.DataFrame:
        """Reads CSV, scrapes unique symbols, outputs historical earnings dates."""
        df = pd.read_csv(candidate_trades_path, parse_dates=["entry_date"])

        if df.empty or df["entry_date"].isna().all():
            logger.warning(f"No candidates found in {candidate_trades_path}. Skipping earnings scrape.")
            return pd.DataFrame()

        symbols = df["symbol"].unique()
        from_date = df["entry_date"].min().date()
        to_date = df["entry_date"].max().date()

        logger.info(f"Scraping historical earnings for {len(symbols)} candidates from {from_date} to {to_date}")
        
        all_events = []
        for sym in symbols:
            logger.info(f"Fetching earnings for {sym}...")
            events = self.scrape_symbol(sym, from_date, to_date)
            all_events.extend(events)
            time.sleep(1) # Be nice to NSE
            
        results_df = pd.DataFrame(all_events)
        if not results_df.empty:
            out_path = candidate_trades_path.replace("candidate_trades", "historical_earnings")
            results_df.to_csv(out_path, index=False)
            logger.info(f"Saved {len(results_df)} events to {out_path}")
        return results_df

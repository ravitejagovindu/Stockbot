"""
FInsight Trading Engine — Shares Outstanding Ingestor
======================================================
Fetches and persists raw shares-outstanding counts for NSE-listed equities.

Used for Point-in-Time (PIT) Market Capitalisation:
    Market Cap = raw_close × raw_shares_outstanding

INVARIANT: Only raw_close (never adjusted close) is used with shares_count
           for Market Cap.  See UniverseScreener for the actual computation.

Data Sources (tried in order):
    1. Kite instruments list — includes a ``lot_size`` proxy that can be
       combined with known capital structure data.
    2. NSE Corporate Announcements API:
       https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O
       or individual company page for paid-up capital data.
    3. NSE company-specific equity API:
       https://www.nseindia.com/api/quote-equity?symbol={symbol}
       → response["metadata"]["issuedSize"] gives outstanding shares.

The NSE ``issuedSize`` field is the most accurate freely-available source for
shares outstanding and is updated after each corporate action.

Usage:
    ingestor = SharesOutstandingIngestor(kite_instance)
    ingestor.ingest_symbol("HDFC")
    shares = ingestor.get_latest_shares("HDFC", as_of_date=date.today())
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from data.db.connection import get_session
from data.db.models import SharesOutstanding
from data.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)

# NSE API endpoint for equity quote metadata (includes issuedSize)
_NSE_EQUITY_QUOTE_URL = "https://www.nseindia.com/api/quote-equity?symbol={symbol}"

# NSE corporate action announcement endpoint
_NSE_CORP_ANNC_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&symbol={symbol}"
)


class SharesOutstandingIngestor(BaseIngestor):
    """
    Fetches and stores raw shares-outstanding data for a given NSE symbol.

    Strategy:
        1. Try NSE ``/api/quote-equity`` for ``issuedSize`` — most accurate.
        2. Fall back to Kite instruments data (``lot_size`` is a rough proxy
           only; prefer source 1 whenever possible).

    Shares counts are stored with an ``effective_date`` equal to the fetch
    date.  The ``get_latest_shares()`` method uses a point-in-time query
    (≤ as_of_date) so historical computations remain accurate after splits.

    Args:
        kite: Authenticated ``kiteconnect.KiteConnect`` instance.
    """

    def __init__(self, kite: Any) -> None:
        super().__init__()
        self._kite = kite

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, symbol: str) -> bool:
        """
        Convenience alias satisfying ``BaseIngestor.ingest()`` contract.

        Delegates to ``ingest_symbol()``.

        Args:
            symbol: NSE ticker.

        Returns:
            True if a row was written, False on failure.
        """
        return self.ingest_symbol(symbol)

    def ingest_symbol(self, symbol: str) -> bool:
        """
        Fetch and persist the current shares-outstanding count for *symbol*.

        Attempt order:
          1. NSE ``/api/quote-equity`` → ``metadata.issuedSize``
          2. Kite instruments list → ``lot_size`` × listed quantity (fallback)

        The fetched count is stored with ``effective_date = today`` so that
        the PIT query in ``get_latest_shares()`` returns it for future queries.

        Args:
            symbol: NSE ticker (e.g. ``"RELIANCE"``).

        Returns:
            True if upsert succeeded, False if both sources failed.
        """
        self.logger.info("Ingesting shares outstanding for %s", symbol)
        shares_count: int | None = None
        source: str = "UNKNOWN"

        # ── Source 1: NSE Equity Quote API ────────────────────────────
        try:
            shares_count = self._fetch_from_nse(symbol)
            if shares_count is not None:
                source = "NSE_QUOTE_API"
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "NSE source failed for %s: %s — trying Kite fallback.", symbol, exc
            )

        # ── Source 2: Kite instruments fallback ───────────────────────
        if shares_count is None:
            try:
                shares_count = self._fetch_from_kite(symbol)
                if shares_count is not None:
                    source = "KITE_INSTRUMENTS"
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Kite fallback also failed for %s: %s", symbol, exc
                )

        if shares_count is None or shares_count <= 0:
            self.logger.error(
                "Could not determine shares outstanding for %s from any source.", symbol
            )
            return False

        self._upsert(symbol, date.today(), shares_count, source)
        self.logger.info(
            "Stored shares outstanding for %s: %d (source=%s)",
            symbol,
            shares_count,
            source,
        )
        return True

    def get_latest_shares(self, symbol: str, as_of_date: date) -> int | None:
        """
        Return the most recent shares-outstanding count as of *as_of_date*.

        Uses a point-in-time (PIT) query: ``effective_date ≤ as_of_date``.
        This ensures historical Market Cap calculations are accurate even after
        splits or bonus issues update the shares count.

        Args:
            symbol: NSE ticker.
            as_of_date: The date for which shares count is needed.

        Returns:
            Integer shares count, or ``None`` if no record exists ≤ as_of_date.
        """
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT shares_count FROM shares_outstanding
                    WHERE symbol = :sym AND effective_date <= :dt
                    ORDER BY effective_date DESC
                    LIMIT 1
                    """
                ),
                {"sym": symbol, "dt": as_of_date},
            ).fetchone()

        if row is None:
            self.logger.debug(
                "No shares_outstanding record for %s as of %s", symbol, as_of_date
            )
            return None
        return int(row[0])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_from_nse(self, symbol: str) -> int | None:
        """
        Query the NSE Equity Quote API and extract ``issuedSize``.

        The ``issuedSize`` field represents the total number of shares issued
        (paid-up capital / face value × quantity).

        Args:
            symbol: NSE ticker.

        Returns:
            Shares outstanding as integer, or ``None`` if field not present.
        """
        url = _NSE_EQUITY_QUOTE_URL.format(symbol=symbol)
        session = self._get_nse_session()
        resp = self._with_retry(session.get, url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # NSE returns a nested structure: data["metadata"]["issuedSize"]
        issued = (
            data.get("metadata", {}).get("issuedSize")
            or data.get("securityInfo", {}).get("issuedSize")
        )
        if issued is None:
            self.logger.debug("issuedSize not found in NSE response for %s", symbol)
            return None

        # issuedSize can be a string with commas (e.g., "1,43,14,20,020")
        shares = int(str(issued).replace(",", ""))
        self.logger.debug("NSE issuedSize for %s: %d", symbol, shares)
        return shares

    def _fetch_from_kite(self, symbol: str) -> int | None:
        """
        Attempt to derive a rough shares-outstanding estimate from the Kite
        instruments list.

        NOTE: The Kite instruments endpoint does not directly expose shares
        outstanding.  The ``lot_size`` field is the F&O lot size, not share
        count.  This fallback is only a placeholder; in a production setup
        you would cross-reference the BSE paid-up capital data.

        Args:
            symbol: NSE ticker.

        Returns:
            ``None`` always (placeholder — signals caller to treat as
            unavailable).  Override in a subclass if you integrate a paid
            data source.
        """
        self.logger.warning(
            "Kite instruments fallback for shares_outstanding is a placeholder. "
            "No shares count derived for %s.",
            symbol,
        )
        # Future: integrate BSE bulk-download or another authoritative source.
        return None

    def _upsert(
        self,
        symbol: str,
        effective_date: date,
        shares_count: int,
        source: str,
    ) -> None:
        """
        Upsert a shares_outstanding row.

        Uses SQLite ``ON CONFLICT DO UPDATE`` so repeated runs on the same date
        update the count rather than fail.

        Args:
            symbol: NSE ticker.
            effective_date: The date the count is effective from.
            shares_count: Total shares outstanding.
            source: Data source label for audit purposes.
        """
        with get_session() as session:
            stmt = sqlite_insert(SharesOutstanding).values(
                symbol=symbol,
                effective_date=effective_date,
                shares_count=shares_count,
                source=source,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "effective_date"],
                set_={
                    "shares_count": stmt.excluded.shares_count,
                    "source": stmt.excluded.source,
                },
            )
            session.execute(stmt)

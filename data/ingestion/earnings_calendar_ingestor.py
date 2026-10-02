"""
FInsight Trading Engine — Earnings Calendar Ingestor
=====================================================
Fetches upcoming earnings / board meeting / dividend dates from the NSE
Corporate Actions API and persists them in the ``earnings_calendar`` table.

Used by:
    - ``UniverseScreener``: block new entries if earnings within 14 days.
    - ``PositionLifecycleManager``: flag ``earnings_alert`` if event within 7 days.

Source:
    NSE Corporate Actions API:
    https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol}

    This endpoint returns upcoming board meetings, dividend ex-dates, and
    results announcements.

    NOTE: NSE requires an active session cookie obtained by first hitting
    ``https://www.nseindia.com``.  ``BaseIngestor._get_nse_session()`` handles
    this automatically via a warm-up request.

Usage:
    ingestor = EarningsCalendarIngestor()
    ingestor.refresh_universe(["INFY", "TCS", "RELIANCE"])

    next_event = ingestor.get_next_event("INFY", date.today())
    will_block = ingestor.has_event_within("INFY", date.today(), days=14)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from data.db.connection import get_session
from data.db.models import EarningsCalendar
from data.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)

# NSE corporate actions endpoint (returns upcoming and recent events per symbol)
_NSE_CORP_ACTIONS_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&symbol={symbol}"
)

# Minimum forward-look window (days) to fetch when refreshing calendar
_MIN_FORWARD_LOOK_DAYS = 30

# Mapping from NSE ``subject`` / ``purpose`` strings to canonical event types
_EVENT_TYPE_MAP: dict[str, str] = {
    "board meeting": "EARNINGS",
    "quarterly results": "EARNINGS",
    "annual results": "EARNINGS",
    "financial results": "EARNINGS",
    "unaudited financial results": "EARNINGS",
    "agm": "AGM",
    "annual general meeting": "AGM",
    "dividend": "DIVIDEND",
    "interim dividend": "DIVIDEND",
    "final dividend": "DIVIDEND",
    "rights issue": "RIGHTS",
    "rights": "RIGHTS",
    "bonus": "BONUS",
}


def _map_event_type(description: str) -> str:
    """
    Map a raw NSE event description to a canonical event type.

    Args:
        description: Raw description / subject string from NSE API.

    Returns:
        One of: ``"EARNINGS"``, ``"AGM"``, ``"DIVIDEND"``, ``"RIGHTS"``,
        ``"BONUS"``, or ``"OTHER"``.
    """
    lower = description.lower()
    for key, canonical in _EVENT_TYPE_MAP.items():
        if key in lower:
            return canonical
    return "OTHER"


class EarningsCalendarIngestor(BaseIngestor):
    """
    Fetches and persists upcoming corporate events (earnings, AGMs, dividends)
    for the NSE universe.

    All dates stored in ``earnings_calendar`` are forward-looking (≥ today).
    Historical events are not useful for the screener and are not stored.

    Args:
        None — config loaded from ``strategy_config.yaml`` via ``BaseIngestor``.
    """

    def __init__(self) -> None:
        super().__init__(
            kite_rate_per_sec=1.0,  # NSE scraping — conservative rate
            max_retries=3,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, symbols: list[str]) -> int:
        """
        Convenience alias for ``BaseIngestor.ingest()`` contract.

        Delegates to ``refresh_universe()``.

        Args:
            symbols: List of NSE tickers.

        Returns:
            Total rows upserted across all symbols.
        """
        return self.refresh_universe(symbols)

    def refresh_universe(self, symbols: list[str]) -> int:
        """
        Refresh the earnings calendar for the entire active universe.

        Fetches upcoming events for each symbol and upserts them into
        ``earnings_calendar``.  Processes symbols sequentially to respect
        the NSE rate limit.

        Args:
            symbols: List of NSE tickers (e.g. ``["INFY", "TCS", "HDFCBANK"]``).

        Returns:
            Total number of rows upserted.
        """
        self.logger.info(
            "Refreshing earnings calendar for %d symbols.", len(symbols)
        )
        total_upserted = 0
        for symbol in symbols:
            try:
                upserted = self._refresh_symbol(symbol)
                total_upserted += upserted
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Failed to refresh earnings calendar for %s: %s",
                    symbol,
                    exc,
                    exc_info=True,
                )
        self.logger.info(
            "Earnings calendar refresh complete. Total rows upserted: %d",
            total_upserted,
        )
        return total_upserted

    def get_next_event(
        self, symbol: str, from_date: date
    ) -> dict | None:
        """
        Return the nearest upcoming event for *symbol* on or after *from_date*.

        Args:
            symbol: NSE ticker.
            from_date: Earliest date to consider (inclusive).

        Returns:
            Dict with keys ``symbol``, ``event_date``, ``event_type``,
            ``description``, ``source``, or ``None`` if no upcoming event.
        """
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT symbol, event_date, event_type, description, source
                    FROM earnings_calendar
                    WHERE symbol = :sym AND event_date >= :dt
                    ORDER BY event_date ASC
                    LIMIT 1
                    """
                ),
                {"sym": symbol, "dt": from_date},
            ).fetchone()

        if row is None:
            return None

        return {
            "symbol": row[0],
            "event_date": (
                row[1] if isinstance(row[1], date) else date.fromisoformat(row[1])
            ),
            "event_type": row[2],
            "description": row[3],
            "source": row[4],
        }

    def has_event_within(
        self, symbol: str, from_date: date, days: int
    ) -> bool:
        """
        Return True if *symbol* has any corporate event within *days* calendar
        days starting from *from_date*.

        Used by:
            - ``UniverseScreener``: ``days = config["trade_management"]["binary_event_block_days"]``
              (default 14) to block new entries near events.
            - ``PositionLifecycleManager``: ``days = config["trade_management"]["earnings_alert_days"]``
              (default 7) to set ``earnings_alert`` flag.

        Args:
            symbol: NSE ticker.
            from_date: Start of the look-ahead window (inclusive).
            days: Number of calendar days to look ahead.

        Returns:
            True if any event exists in ``[from_date, from_date + days]``.
        """
        look_ahead = from_date + timedelta(days=days)
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT 1 FROM earnings_calendar
                    WHERE symbol = :sym
                      AND event_date BETWEEN :start AND :end
                    LIMIT 1
                    """
                ),
                {"sym": symbol, "start": from_date, "end": look_ahead},
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _refresh_symbol(self, symbol: str) -> int:
        """
        Fetch upcoming events for a single symbol and upsert into the DB.

        Args:
            symbol: NSE ticker.

        Returns:
            Number of rows upserted.
        """
        events = self._fetch_events_from_nse(symbol)
        if not events:
            self.logger.debug("No upcoming events found for %s", symbol)
            return 0

        return self._bulk_upsert(events)

    def _fetch_events_from_nse(self, symbol: str) -> list[dict]:
        """
        Fetch corporate events from the NSE Corporate Actions API.

        The NSE API returns a JSON array; each item has fields:
            ``subject``, ``exDate``, ``bcStartDate``, ``bcEndDate``, ``series``.

        We normalise these into our canonical event schema and filter to only
        forward-looking events (≥ today).

        Args:
            symbol: NSE ticker.

        Returns:
            List of normalised event dicts ready for DB upsert.
        """
        url = _NSE_CORP_ACTIONS_URL.format(symbol=symbol)
        nse_session = self._get_nse_session()

        resp = self._with_retry(nse_session.get, url, timeout=15)
        resp.raise_for_status()

        raw_list = resp.json()
        if not isinstance(raw_list, list):
            self.logger.debug(
                "NSE returned non-list for %s corporate actions", symbol
            )
            return []

        today = date.today()
        events: list[dict] = []

        for item in raw_list:
            event = self._parse_nse_event(symbol, item)
            if event is None:
                continue
            # Only keep forward-looking events
            if event["event_date"] >= today:
                events.append(event)

        self.logger.debug(
            "Parsed %d upcoming events for %s from NSE.", len(events), symbol
        )
        return events

    def _parse_nse_event(self, symbol: str, item: dict) -> dict | None:
        """
        Parse a single NSE corporate action item into our canonical event dict.

        NSE field names can vary.  We try multiple field aliases for robustness.

        Args:
            symbol: NSE ticker (owner of the event).
            item: Raw dict from NSE API response item.

        Returns:
            Normalised event dict, or ``None`` if the event date cannot be parsed.
        """
        # Extract event date — try multiple field name aliases
        event_date: date | None = None
        for field in ("exDate", "ex_date", "bcStartDate", "recordDate", "meetingDate"):
            raw_date = item.get(field)
            if raw_date:
                try:
                    if isinstance(raw_date, date):
                        event_date = raw_date
                    else:
                        val_str = str(raw_date).strip()
                        if len(val_str) >= 10:
                            event_date = date.fromisoformat(val_str[:10])
                    if event_date:
                        break
                except (ValueError, TypeError):
                    continue

        if event_date is None:
            return None

        description: str = (
            item.get("subject")
            or item.get("purpose")
            or item.get("description")
            or ""
        )
        event_type = _map_event_type(description)

        return {
            "symbol": symbol,
            "event_date": event_date,
            "event_type": event_type,
            "description": description[:500] if description else None,
            "source": _NSE_CORP_ACTIONS_URL.format(symbol=symbol),
        }

    def _bulk_upsert(self, events: list[dict]) -> int:
        """
        Upsert a list of events into ``earnings_calendar``.

        Uses ``ON CONFLICT DO UPDATE`` on ``(symbol, event_date, event_type)``
        so re-running is idempotent.

        Args:
            events: List of normalised event dicts.

        Returns:
            Number of rows processed.
        """
        if not events:
            return 0

        with get_session() as session:
            stmt = sqlite_insert(EarningsCalendar).values(
                [
                    {
                        "symbol": ev["symbol"],
                        "event_date": ev["event_date"],
                        "event_type": ev["event_type"],
                        "description": ev.get("description"),
                        "source": ev.get("source"),
                    }
                    for ev in events
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "event_date", "event_type"],
                set_={
                    "description": stmt.excluded.description,
                    "source": stmt.excluded.source,
                },
            )
            session.execute(stmt)

        return len(events)

"""
FInsight Trading Engine — Corporate Actions Ingestor
=====================================================
Fetches corporate action events (splits, bonuses, dividends) for NSE-listed
equities and stores them in the ``corporate_actions_log`` table.

IMPORTANT: This module only *logs* events.  It does NOT apply adjustments to
stored OHLCV prices.  Backward price adjustments are performed in-memory by
``engine_core/adjustments.py`` when the engine needs adjusted series.

Sources (tried in order):
    1. Zerodha Kite corporate actions endpoint:
       ``kite.corporate_actions(exchange, symbol)``
    2. NSE Corporate Actions API:
       ``https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={symbol}``

Split-ratio parsing:
    NSE represents splits as strings like ``"1:2"`` (1 new share for every 2
    old shares, i.e. a 2-for-1 split).  This module parses them into
    ``ratio_numerator`` (new) and ``ratio_denominator`` (old).

Usage:
    from data.ingestion.corporate_actions_ingestor import CorporateActionsIngestor
    from datetime import date

    ingestor = CorporateActionsIngestor(kite_instance)
    ingestor.ingest_all("WIPRO")
    actions = ingestor.get_actions_after("WIPRO", date(2023, 1, 1))
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from data.db.connection import get_session
from data.db.models import CorporateActionsLog
from data.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)

# NSE corporate actions endpoint
_NSE_CORP_ACTIONS_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&symbol={symbol}"
)

# Mapping from NSE/Kite action type strings to our canonical action_type enum
_ACTION_TYPE_MAP: dict[str, str] = {
    "split": "SPLIT",
    "stock split": "SPLIT",
    "bonus": "BONUS",
    "bonus issue": "BONUS",
    "dividend": "DIVIDEND",
    "interim dividend": "DIVIDEND",
    "final dividend": "DIVIDEND",
    "rights": "RIGHTS",
    "rights issue": "RIGHTS",
}


def parse_ratio(ratio_str: str) -> tuple[float, float] | tuple[None, None]:
    """
    Parse a ratio string of the form ``"N:D"`` into (numerator, denominator).

    NSE and Kite use strings like:
        - ``"1:2"``  → 1 new share per 2 old (i.e., 2-for-1 split)
        - ``"1:5"``  → 1 new bonus share per 5 held
        - ``"5:1"``  → old-style notation (5 new for 1 old)

    Args:
        ratio_str: Raw ratio string from NSE/Kite API response.

    Returns:
        Tuple of (numerator, denominator) floats, or (None, None) if the
        string cannot be parsed.
    """
    if not ratio_str or not isinstance(ratio_str, str):
        return None, None

    # Match patterns like "1:2", "1 : 2", "1.5:2"
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$", ratio_str.strip())
    if not match:
        logger.debug("Could not parse ratio string: %r", ratio_str)
        return None, None

    numerator = float(match.group(1))
    denominator = float(match.group(2))
    return numerator, denominator


class CorporateActionsIngestor(BaseIngestor):
    """
    Ingests corporate action events from Kite and NSE into ``corporate_actions_log``.

    This class stores events as an immutable log; it never modifies OHLCV data.
    The ``engine_core/adjustments.py`` module reads this log to compute in-memory
    price adjustments.

    Args:
        kite: Authenticated ``kiteconnect.KiteConnect`` instance.
        exchange: Exchange (default ``"NSE"``).
    """

    def __init__(self, kite: Any, exchange: str = "NSE") -> None:
        super().__init__()
        self._kite = kite
        self._exchange = exchange

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, symbol: str) -> int:
        """
        Convenience alias satisfying ``BaseIngestor.ingest()`` contract.

        Delegates to ``ingest_all()``.

        Args:
            symbol: NSE ticker.

        Returns:
            Number of rows upserted.
        """
        return self.ingest_all(symbol)

    def ingest_all(self, symbol: str) -> int:
        """
        Fetch the full corporate action history for *symbol* and persist it.

        Tries Kite first, then falls back to NSE if Kite returns nothing.
        Rows are upserted (idempotent on ``symbol + ex_date + action_type``).

        Args:
            symbol: NSE ticker (e.g. ``"TCS"``).

        Returns:
            Number of rows upserted into ``corporate_actions_log``.
        """
        self.logger.info("Ingesting corporate actions for %s", symbol)

        events: list[dict] = []

        # ── Source 1: Kite corporate actions ─────────────────────────
        try:
            kite_events = self._fetch_from_kite(symbol)
            events.extend(kite_events)
            self.logger.debug(
                "Kite returned %d corporate actions for %s", len(kite_events), symbol
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Kite corporate actions fetch failed for %s: %s", symbol, exc
            )

        # ── Source 2: NSE fallback (supplements Kite data) ───────────
        try:
            nse_events = self._fetch_from_nse(symbol)
            events.extend(nse_events)
            self.logger.debug(
                "NSE returned %d corporate actions for %s", len(nse_events), symbol
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "NSE corporate actions fetch failed for %s: %s", symbol, exc
            )

        if not events:
            self.logger.info("No corporate actions found for %s", symbol)
            return 0

        # Deduplicate by (ex_date, action_type) before upsert
        seen: set[tuple[str, str]] = set()
        unique_events = []
        for ev in events:
            key = (str(ev.get("ex_date")), ev.get("action_type", "UNKNOWN"))
            if key not in seen:
                seen.add(key)
                unique_events.append(ev)

        rows_upserted = self._bulk_upsert(unique_events)
        self.logger.info(
            "Upserted %d corporate action rows for %s", rows_upserted, symbol
        )
        return rows_upserted

    def get_actions_after(
        self, symbol: str, from_date: date
    ) -> list[dict]:
        """
        Return all corporate actions for *symbol* with ``ex_date >= from_date``.

        Used by ``engine_core/adjustments.py`` to determine which events
        need to be factored into the adjustment calculation.

        Args:
            symbol: NSE ticker.
            from_date: Only return actions on or after this date.

        Returns:
            List of dicts with keys:
                ``symbol``, ``ex_date``, ``action_type``,
                ``ratio_numerator``, ``ratio_denominator``, ``notes``.
        """
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT symbol, ex_date, action_type,
                           ratio_numerator, ratio_denominator, notes
                    FROM corporate_actions_log
                    WHERE symbol = :sym AND ex_date >= :dt
                    ORDER BY ex_date ASC
                    """
                ),
                {"sym": symbol, "dt": from_date},
            ).fetchall()

        return [
            {
                "symbol": r[0],
                "ex_date": r[1] if isinstance(r[1], date) else date.fromisoformat(r[1]),
                "action_type": r[2],
                "ratio_numerator": r[3],
                "ratio_denominator": r[4],
                "notes": r[5],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_from_kite(self, symbol: str) -> list[dict]:
        """
        Fetch corporate actions from Kite's corporate actions endpoint.

        Kite returns a list of dicts with keys like:
            ``ex_date``, ``purpose`` (e.g., "SPLIT - 1:2"), ``record_date`` etc.

        Args:
            symbol: NSE ticker.

        Returns:
            List of normalised event dicts ready for upsert.
        """
        raw: list[dict] = self._rate_limited_retry(
            self._kite.corporate_actions,
            self._exchange,
            symbol,
        )
        return [self._normalise_kite_event(symbol, ev) for ev in (raw or []) if ev]

    def _fetch_from_nse(self, symbol: str) -> list[dict]:
        """
        Fetch corporate actions from the NSE Corporate Actions API.

        NSE returns a JSON array of objects. Relevant fields:
            ``exDate``, ``purpose``, ``series``, ``faceVal`` etc.

        Args:
            symbol: NSE ticker.

        Returns:
            List of normalised event dicts ready for upsert.
        """
        url = _NSE_CORP_ACTIONS_URL.format(symbol=symbol)
        nse_session = self._get_nse_session()
        resp = self._with_retry(nse_session.get, url, timeout=15)
        resp.raise_for_status()
        raw_list = resp.json()

        if not isinstance(raw_list, list):
            self.logger.debug("NSE returned non-list for %s", symbol)
            return []

        return [
            ev
            for item in raw_list
            for ev in [self._normalise_nse_event(symbol, item)]
            if ev is not None
        ]

    def _normalise_kite_event(self, symbol: str, raw: dict) -> dict:
        """
        Convert a Kite corporate action dict into our canonical format.

        Kite field names can vary by API version.  We handle the most common
        known shapes and fall back gracefully.

        Args:
            symbol: NSE ticker (owner of this event).
            raw: Raw dict from Kite API response.

        Returns:
            Normalised event dict with keys matching ``corporate_actions_log``.
        """
        purpose_str: str = str(raw.get("purpose", "") or "").lower()
        action_type = self._map_action_type(purpose_str)

        ex_date = self._parse_date_field(raw, ("ex_date", "record_date", "payment_date"))

        ratio_num, ratio_den = None, None
        # Try to extract ratio from purpose string e.g. "SPLIT - 1:2"
        ratio_match = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", purpose_str)
        if ratio_match:
            ratio_num = float(ratio_match.group(1))
            ratio_den = float(ratio_match.group(2))

        return {
            "symbol": symbol,
            "ex_date": ex_date,
            "action_type": action_type,
            "ratio_numerator": ratio_num,
            "ratio_denominator": ratio_den,
            "notes": raw.get("purpose", ""),
        }

    def _normalise_nse_event(self, symbol: str, raw: dict) -> dict | None:
        """
        Convert an NSE corporate action dict into our canonical format.

        NSE field names: ``exDate``, ``purpose``, ``series``.

        Args:
            symbol: NSE ticker.
            raw: Raw dict from NSE API response.

        Returns:
            Normalised event dict, or ``None`` if the record is unusable.
        """
        purpose_str: str = str(raw.get("purpose", "") or "").lower()
        action_type = self._map_action_type(purpose_str)

        ex_date = self._parse_date_field(raw, ("exDate", "ex_date", "bcEndDate"))
        if ex_date is None:
            return None

        ratio_str = raw.get("splitRatio") or raw.get("ratio") or ""
        ratio_num, ratio_den = parse_ratio(ratio_str)

        # Also try extracting ratio from purpose string
        if ratio_num is None:
            ratio_match = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", purpose_str)
            if ratio_match:
                ratio_num = float(ratio_match.group(1))
                ratio_den = float(ratio_match.group(2))

        return {
            "symbol": symbol,
            "ex_date": ex_date,
            "action_type": action_type,
            "ratio_numerator": ratio_num,
            "ratio_denominator": ratio_den,
            "notes": raw.get("purpose", ""),
        }

    def _map_action_type(self, purpose_lower: str) -> str:
        """
        Map a raw purpose string to a canonical action type.

        Args:
            purpose_lower: Lowercase purpose string from API response.

        Returns:
            One of ``"SPLIT"``, ``"BONUS"``, ``"DIVIDEND"``, ``"RIGHTS"``,
            or ``"OTHER"``.
        """
        for key, canonical in _ACTION_TYPE_MAP.items():
            if key in purpose_lower:
                return canonical
        return "OTHER"

    def _parse_date_field(
        self, raw: dict, field_names: tuple[str, ...]
    ) -> date | None:
        """
        Try multiple field names and return the first parseable date.

        Args:
            raw: Source dict.
            field_names: Tuple of field names to try in order.

        Returns:
            Parsed ``date`` object, or ``None`` if none could be parsed.
        """
        for field in field_names:
            val = raw.get(field)
            if not val:
                continue
            try:
                if isinstance(val, date):
                    return val
                # Kite often returns "YYYY-MM-DD" or "DD-MMM-YYYY"
                val_str = str(val).strip()
                if re.match(r"^\d{4}-\d{2}-\d{2}", val_str):
                    return date.fromisoformat(val_str[:10])
                # Try DD-MMM-YYYY format (e.g., "01-Jan-2024")
                from datetime import datetime
                for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y"):
                    try:
                        return datetime.strptime(val_str, fmt).date()
                    except ValueError:
                        continue
            except Exception:  # noqa: BLE001
                continue
        return None

    def _bulk_upsert(self, events: list[dict]) -> int:
        """
        Upsert a list of normalised corporate action events into the DB.

        Uses SQLite ``ON CONFLICT DO UPDATE`` on ``(symbol, ex_date, action_type)``.

        Args:
            events: List of normalised event dicts.

        Returns:
            Number of rows processed (not only newly inserted).
        """
        valid_events = [e for e in events if e.get("ex_date") is not None]
        if not valid_events:
            return 0

        with get_session() as session:
            stmt = sqlite_insert(CorporateActionsLog).values(valid_events)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "ex_date", "action_type"],
                set_={
                    "ratio_numerator": stmt.excluded.ratio_numerator,
                    "ratio_denominator": stmt.excluded.ratio_denominator,
                    "notes": stmt.excluded.notes,
                },
            )
            session.execute(stmt)

        return len(valid_events)

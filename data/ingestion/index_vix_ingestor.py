"""
FInsight Trading Engine — Index & VIX Ingestor
===============================================
Fetches Nifty 50 EOD close and India VIX close and stores them in the
``market_data_lake`` table using special synthetic symbols:
    - ``NIFTY50_INDEX``  — Nifty 50 index close
    - ``INDIA_VIX``      — India VIX close

These symbols are referenced in ``strategy_config.yaml`` under
``data.nifty_symbol`` and ``data.vix_symbol``.

Sources:
    1. Nifty 50 via Kite: instrument token for ``NSE:NIFTY 50`` (index)
    2. India VIX via Kite: instrument token for ``NSE:INDIA VIX``
    3. NSE API fallback for VIX: https://www.nseindia.com/api/allIndices
       (returns JSON with current VIX as ``"India VIX"`` under ``data`` array)

CRITICAL: Nifty 50 and India VIX are stored with the same schema as equity
OHLCV.  For index data: open=high=low=close (index has no volume bar) or we
store actual OHLCV if Kite provides it.  Volume is stored as 0 for indices
where volume is not meaningful.

Usage:
    from data.ingestion.index_vix_ingestor import IndexVIXIngestor
    from datetime import date

    ingestor = IndexVIXIngestor(kite)
    result = ingestor.ingest_today()
    # → {'nifty_close': 24650.25, 'vix_close': 14.2, 'date': date(2024, 10, 1)}

    ingestor.ingest_historical(from_date=date(2020, 1, 1), to_date=date(2024, 9, 30))
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from data.db.connection import get_session
from data.db.models import MarketDataLake
from data.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)

# ── Kite instrument names for NSE index data ─────────────────────────────────
# The Kite API uses the exchange segment "NSE" and tradingsymbol "NIFTY 50"
# for the index.  These must match exactly.
_KITE_NIFTY_TRADINGSYMBOL = "NIFTY 50"
_KITE_VIX_TRADINGSYMBOL = "INDIA VIX"
_KITE_INDEX_EXCHANGE = "NSE"
_KITE_INTERVAL = "day"

# NSE fallback endpoint for all index data (includes India VIX)
_NSE_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"

# Maximum calendar days per Kite historical_data call (conservative)
_MAX_DAYS_PER_CALL = 365


class IndexVIXIngestor(BaseIngestor):
    """
    Pulls Nifty 50 EOD close and India VIX close from Kite (with NSE fallback)
    and stores them in ``market_data_lake`` under synthetic symbol keys.

    The macro regime filter (``engine_core/regime_filter.py``) reads from these
    rows via the configured symbol keys in ``strategy_config.yaml``.

    Args:
        kite: Authenticated ``kiteconnect.KiteConnect`` instance.
    """

    def __init__(self, kite: Any) -> None:
        super().__init__()
        self._kite = kite

        # Load symbol keys from strategy config
        data_cfg = self.config.get("data", {})
        self._nifty_symbol: str = data_cfg.get("nifty_symbol", "NIFTY50_INDEX")
        self._vix_symbol: str = data_cfg.get("vix_symbol", "INDIA_VIX")

        # Cached Kite instrument tokens (resolved once per instance)
        self._nifty_token: int | None = None
        self._vix_token: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, *args: Any, **kwargs: Any) -> dict:
        """
        Convenience alias satisfying ``BaseIngestor.ingest()`` contract.

        Delegates to ``ingest_today()``.
        """
        return self.ingest_today()

    def ingest_today(self) -> dict:
        """
        Fetch and store today's Nifty 50 and India VIX closing values.

        Called from the daily EOD pipeline after market close (5 PM IST).

        Returns:
            Dict with keys:
                ``nifty_close`` (float | None): Nifty 50 closing price.
                ``vix_close`` (float | None): India VIX closing value.
                ``date`` (date): The trading date fetched.

        Note:
            If fetching fails for one index, the other is still attempted and
            stored.  A ``None`` value indicates the fetch failed.
        """
        today = date.today()
        self.logger.info("Ingesting today's Nifty50 and India VIX (%s)", today)

        nifty_close: float | None = None
        vix_close: float | None = None

        # ── Nifty 50 ──────────────────────────────────────────────────
        try:
            nifty_rows = self._fetch_kite_index(
                symbol_key=self._nifty_symbol,
                tradingsymbol=_KITE_NIFTY_TRADINGSYMBOL,
                from_date=today,
                to_date=today,
            )
            if nifty_rows:
                nifty_close = nifty_rows[-1]["close_raw"]
                self._store_rows(nifty_rows)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Nifty 50 ingest failed: %s", exc, exc_info=True)

        # ── India VIX ─────────────────────────────────────────────────
        try:
            vix_rows = self._fetch_kite_index(
                symbol_key=self._vix_symbol,
                tradingsymbol=_KITE_VIX_TRADINGSYMBOL,
                from_date=today,
                to_date=today,
            )
            if vix_rows:
                vix_close = vix_rows[-1]["close_raw"]
                self._store_rows(vix_rows)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Kite VIX fetch failed: %s — trying NSE fallback.", exc
            )
            try:
                vix_close = self._fetch_vix_from_nse()
                if vix_close is not None:
                    self._store_rows(
                        [
                            {
                                "symbol": self._vix_symbol,
                                "trade_date": today,
                                "open_raw": vix_close,
                                "high_raw": vix_close,
                                "low_raw": vix_close,
                                "close_raw": vix_close,
                                "volume_raw": 0,
                                "exchange": "NSE",
                            }
                        ]
                    )
            except Exception as nse_exc:  # noqa: BLE001
                self.logger.error(
                    "NSE VIX fallback also failed: %s", nse_exc, exc_info=True
                )

        result = {"nifty_close": nifty_close, "vix_close": vix_close, "date": today}
        self.logger.info("Index/VIX ingest complete: %s", result)
        return result

    def ingest_historical(
        self, from_date: date, to_date: date
    ) -> dict[str, int]:
        """
        Fetch and store historical Nifty 50 and India VIX data.

        Used for initial data population and backfill operations.

        Args:
            from_date: Start of historical range (inclusive).
            to_date: End of historical range (inclusive).

        Returns:
            Dict mapping symbol key to number of rows upserted:
            ``{'NIFTY50_INDEX': 1200, 'INDIA_VIX': 1200}``.
        """
        self.logger.info(
            "Ingesting historical Index/VIX from %s to %s", from_date, to_date
        )
        results: dict[str, int] = {
            self._nifty_symbol: 0,
            self._vix_symbol: 0,
        }

        for symbol_key, tradingsymbol in [
            (self._nifty_symbol, _KITE_NIFTY_TRADINGSYMBOL),
            (self._vix_symbol, _KITE_VIX_TRADINGSYMBOL),
        ]:
            try:
                total_rows = self._ingest_historical_index(
                    symbol_key, tradingsymbol, from_date, to_date
                )
                results[symbol_key] = total_rows
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Historical ingest failed for %s: %s",
                    symbol_key,
                    exc,
                    exc_info=True,
                )

        self.logger.info("Historical Index/VIX ingest complete: %s", results)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ingest_historical_index(
        self,
        symbol_key: str,
        tradingsymbol: str,
        from_date: date,
        to_date: date,
    ) -> int:
        """
        Chunk and ingest a historical date range for a single index.

        Args:
            symbol_key: Storage symbol (e.g. ``"NIFTY50_INDEX"``).
            tradingsymbol: Kite tradingsymbol (e.g. ``"NIFTY 50"``).
            from_date: Start date.
            to_date: End date.

        Returns:
            Total rows upserted.
        """
        total = 0
        current_start = from_date
        while current_start <= to_date:
            chunk_end = min(
                current_start + timedelta(days=_MAX_DAYS_PER_CALL - 1),
                to_date,
            )
            rows = self._fetch_kite_index(
                symbol_key, tradingsymbol, current_start, chunk_end
            )
            if rows:
                self._store_rows(rows)
                total += len(rows)
            current_start = chunk_end + timedelta(days=1)
        return total

    def _resolve_index_token(self, tradingsymbol: str) -> int:
        """
        Resolve the Kite instrument token for an NSE index.

        Index instruments use segment ``"INDICES"`` in the Kite instrument list.

        Args:
            tradingsymbol: Kite tradingsymbol for the index.

        Returns:
            Integer instrument token.

        Raises:
            RuntimeError: If the index token cannot be resolved.
        """
        # Cache both tokens together on first call
        if self._nifty_token is None or self._vix_token is None:
            self.logger.debug("Resolving NSE index instrument tokens.")
            instruments: list[dict] = self._rate_limited_retry(
                self._kite.instruments, _KITE_INDEX_EXCHANGE
            )
            for inst in instruments:
                ts = inst.get("tradingsymbol", "")
                seg = inst.get("segment", "")
                if ts == _KITE_NIFTY_TRADINGSYMBOL and "INDICES" in seg.upper():
                    self._nifty_token = int(inst["instrument_token"])
                elif ts == _KITE_VIX_TRADINGSYMBOL and "INDICES" in seg.upper():
                    self._vix_token = int(inst["instrument_token"])

        if tradingsymbol == _KITE_NIFTY_TRADINGSYMBOL and self._nifty_token:
            return self._nifty_token
        if tradingsymbol == _KITE_VIX_TRADINGSYMBOL and self._vix_token:
            return self._vix_token

        raise RuntimeError(
            f"Could not resolve Kite instrument token for index '{tradingsymbol}'. "
            "Check that the segment is 'NSE-INDICES' in the instruments list."
        )

    def _fetch_kite_index(
        self,
        symbol_key: str,
        tradingsymbol: str,
        from_date: date,
        to_date: date,
    ) -> list[dict]:
        """
        Fetch EOD bars for an NSE index from the Kite historical data API.

        Uses ``continuous=False`` (same as equity OHLCV) — not that it matters
        for indices, but it ensures consistency with the equity ingestor.

        Args:
            symbol_key: Storage symbol (``"NIFTY50_INDEX"`` or ``"INDIA_VIX"``).
            tradingsymbol: Kite tradingsymbol string.
            from_date: Start date.
            to_date: End date.

        Returns:
            List of OHLCV row dicts ready for ``_store_rows()``.
        """
        token = self._resolve_index_token(tradingsymbol)

        candles: list[dict] = self._rate_limited_retry(
            self._kite.historical_data,
            token,
            from_date,
            to_date,
            _KITE_INTERVAL,
            continuous=False,
            oi=False,
        )

        rows = []
        for c in (candles or []):
            candle_date = c["date"]
            if hasattr(candle_date, "date"):
                candle_date = candle_date.date()
            elif isinstance(candle_date, str):
                candle_date = date.fromisoformat(candle_date[:10])

            # For indices, volume is 0 if not provided by Kite
            rows.append(
                {
                    "symbol": symbol_key,
                    "trade_date": candle_date,
                    "open_raw": float(c.get("open", c["close"])),
                    "high_raw": float(c.get("high", c["close"])),
                    "low_raw": float(c.get("low", c["close"])),
                    "close_raw": float(c["close"]),
                    "volume_raw": int(c.get("volume", 0)),
                    "exchange": "NSE",
                }
            )
        return rows

    def _fetch_vix_from_nse(self) -> float | None:
        """
        Fetch the current India VIX value from the NSE ``allIndices`` API.

        This is a fallback used when Kite's VIX endpoint fails.

        Returns:
            India VIX float value, or ``None`` if not found.
        """
        nse_session = self._get_nse_session()
        resp = self._with_retry(nse_session.get, _NSE_ALL_INDICES_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        indices_list = data.get("data", [])
        for index_item in indices_list:
            name = str(index_item.get("indexSymbol", "") or "").upper()
            if "VIX" in name or "INDIA VIX" in name:
                last_val = index_item.get("last") or index_item.get("previousClose")
                if last_val is not None:
                    self.logger.debug("NSE VIX fallback value: %s", last_val)
                    return float(last_val)

        self.logger.warning("India VIX not found in NSE allIndices response.")
        return None

    def _store_rows(self, rows: list[dict]) -> None:
        """
        Upsert a list of OHLCV row dicts into ``market_data_lake``.

        Uses ``ON CONFLICT DO UPDATE`` on ``(symbol, trade_date)`` so
        repeated calls are idempotent.

        Args:
            rows: List of dicts with OHLCV fields.
        """
        if not rows:
            return

        with get_session() as session:
            stmt = sqlite_insert(MarketDataLake).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date"],
                set_={
                    "open_raw": stmt.excluded.open_raw,
                    "high_raw": stmt.excluded.high_raw,
                    "low_raw": stmt.excluded.low_raw,
                    "close_raw": stmt.excluded.close_raw,
                    "volume_raw": stmt.excluded.volume_raw,
                },
            )
            session.execute(stmt)

        self.logger.debug("Stored %d index rows.", len(rows))

"""
FInsight Trading Engine — Universe Screener
===========================================
The UniverseScreener applies a five-gate filter to determine which symbols
from the data lake qualify as entry candidates for a given evaluation date.

Gate Order (short-circuit — first failure stops further checks)
---------------------------------------------------------------
1. **Market Cap** > ₹5,000 Cr  — liquidity and stability proxy
2. **ADTV**       > ₹25 Cr     — ensures we can enter/exit without slippage
3. **Listing Age** > 252 trading days — IPO lock-out period
4. **Not in ASM/GSM** — regulatory quarantine exclusion
5. **No binary event in next 14 calendar days** — earnings/corp-action block

Design Principles
-----------------
* All gates use **raw prices** for market-cap and ADTV calculations.
* The screener is **stateless**: it never writes to the database.
* Each ``screen_single`` call is fully self-contained and independently
  testable via in-memory SQLite.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from data.db.models import (
    ASMGSMList,
    EarningsCalendar,
    MarketDataLake,
    SharesOutstanding,
)
from engine_core.adjustments import compute_adtv, compute_market_cap

logger = logging.getLogger(__name__)

# Conversion constant: 1 crore = 10,000,000
_CR = 1e7


# ---------------------------------------------------------------------------
# ScreeningResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScreeningResult:
    """Result of the five-gate universe screen for a single symbol.

    Attributes
    ----------
    symbol:
        NSE ticker symbol.
    passed:
        ``True`` only if **all** five gates are cleared.
    rejection_reason:
        Human-readable reason for the first failed gate, or ``None`` if
        the symbol passed all gates.
    market_cap_cr:
        Market capitalisation in crores on ``eval_date``, or ``None`` if
        data was unavailable.
    adtv_cr:
        20-day Average Daily Traded Value in crores, or ``None`` if
        insufficient history.
    listing_age_days:
        Number of trading days since the first recorded row in
        ``market_data_lake``, or ``None`` if data was unavailable.
    is_under_asm_gsm:
        ``True`` if the symbol appears in the ASM/GSM surveillance list.
    days_to_next_event:
        Calendar days to the nearest upcoming earnings/corp action,
        or ``None`` if no event was found within the look-ahead window.
    """

    symbol: str
    passed: bool
    rejection_reason: Optional[str]
    market_cap_cr: Optional[float]
    adtv_cr: Optional[float]
    listing_age_days: Optional[int]
    is_under_asm_gsm: bool
    days_to_next_event: Optional[int]


# ---------------------------------------------------------------------------
# UniverseScreener class
# ---------------------------------------------------------------------------

class UniverseScreener:
    """Stateless five-gate candidate filter.

    Parameters
    ----------
    config:
        Full strategy config dict (both ``universe`` and ``trade_management``
        sub-dicts are used).
    session:
        Active SQLAlchemy session.  Read-only — no writes performed here.
    """

    def __init__(self, config: dict, session: Session) -> None:
        """Initialise with strategy config and a read-only DB session."""
        uni = config["universe"]
        tm = config["trade_management"]
        data_cfg = config.get("data", {})

        self._min_market_cap_cr: float = float(uni["min_market_cap_cr"])
        self._min_adtv_cr: float = float(uni["min_adtv_cr"])
        self._min_listing_days: int = int(uni["min_listing_age_trading_days"])
        self._binary_event_block_days: int = int(tm["binary_event_block_days"])
        self._adtv_period: int = int(data_cfg.get("adtv_sma_period", 20))

        # Gate 6 — Volume breakout
        self._volume_breakout_mult: float = float(uni.get("volume_breakout_multiplier", 1.5))

        # Gate 7 — Relative strength
        self._rs_lookback: int = int(uni.get("relative_strength_lookback_days", 63))
        self._rs_top_pct: float = float(uni.get("relative_strength_top_pct", 35))

        self._session = session

        # Cache for RS computation: built once per screen_all() call
        self._rs_threshold_return: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def screen_all(self, eval_date: date) -> list[ScreeningResult]:
        """Screen every symbol present in the data lake for ``eval_date``.

        The full universe is derived from distinct symbols that have at least
        one row in ``market_data_lake`` on or before ``eval_date``.  Each
        symbol is independently screened through all five gates.

        Parameters
        ----------
        eval_date:
            Evaluation date (today's date in the live runner; a historical
            date in the back-tester).

        Returns
        -------
        list[ScreeningResult]
            One result per symbol.  Results with ``passed=True`` are the
            entry candidates for today's run.
        """
        symbols = self._get_all_symbols(eval_date)
        logger.info(
            "[UniverseScreener] Screening %d symbols for %s …", len(symbols), eval_date
        )
        # Pre-compute universe-wide RS threshold once (avoids N²  DB queries)
        self._rs_threshold_return = self._compute_rs_threshold(symbols, eval_date)
        results = [self.screen_single(sym, eval_date) for sym in symbols]
        passed = sum(1 for r in results if r.passed)
        logger.info(
            "[UniverseScreener] %d/%d symbols passed all gates.", passed, len(symbols)
        )
        return results

    def screen_single(self, symbol: str, eval_date: date) -> ScreeningResult:
        """Screen one symbol through all five gates.

        Gates are applied in order; the first failure short-circuits remaining
        checks to avoid unnecessary DB queries.

        Parameters
        ----------
        symbol:
            NSE ticker symbol to evaluate.
        eval_date:
            Point-in-time evaluation date.

        Returns
        -------
        ScreeningResult
            Full result including whichever data was computed before the
            first gate failure.
        """
        market_cap_cr: Optional[float] = None
        adtv_cr: Optional[float] = None
        listing_age_days: Optional[int] = None
        is_under_asm_gsm: bool = False
        days_to_next_event: Optional[int] = None

        # -------------------------------------------------------------------
        # Gate 1 — Market Cap > min_market_cap_cr
        # -------------------------------------------------------------------
        raw_close, shares = self._get_latest_price_and_shares(symbol, eval_date)
        if raw_close is None or shares is None:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason="NO_PRICE_DATA",
                market_cap_cr=None,
                adtv_cr=None,
                listing_age_days=None,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        mc_raw = compute_market_cap(raw_close, shares)
        market_cap_cr = mc_raw / _CR

        if market_cap_cr <= self._min_market_cap_cr:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason=f"MARKET_CAP_TOO_LOW({market_cap_cr:.1f}cr<{self._min_market_cap_cr}cr)",
                market_cap_cr=market_cap_cr,
                adtv_cr=None,
                listing_age_days=None,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        # -------------------------------------------------------------------
        # Gate 2 — ADTV > min_adtv_cr
        # -------------------------------------------------------------------
        raw_ohlcv = self._fetch_ohlcv(symbol, eval_date, lookback=self._adtv_period + 5)
        if raw_ohlcv.empty or len(raw_ohlcv) < self._adtv_period:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason="INSUFFICIENT_HISTORY_FOR_ADTV",
                market_cap_cr=market_cap_cr,
                adtv_cr=None,
                listing_age_days=None,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        adtv_series = compute_adtv(
            raw_ohlcv["close_raw"], raw_ohlcv["volume_raw"], period=self._adtv_period
        )
        latest_adtv = adtv_series.iloc[-1]
        if pd.isna(latest_adtv):
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason="ADTV_NAN",
                market_cap_cr=market_cap_cr,
                adtv_cr=None,
                listing_age_days=None,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        adtv_cr = float(latest_adtv) / _CR
        if adtv_cr <= self._min_adtv_cr:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason=f"ADTV_TOO_LOW({adtv_cr:.2f}cr<{self._min_adtv_cr}cr)",
                market_cap_cr=market_cap_cr,
                adtv_cr=adtv_cr,
                listing_age_days=None,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        # -------------------------------------------------------------------
        # Gate 3 — Listing Age > min_listing_days trading days
        # -------------------------------------------------------------------
        listing_age_days = self._get_listing_age(symbol, eval_date)
        if listing_age_days is None:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason="LISTING_AGE_UNKNOWN",
                market_cap_cr=market_cap_cr,
                adtv_cr=adtv_cr,
                listing_age_days=None,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        if listing_age_days < self._min_listing_days:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason=f"TOO_YOUNG({listing_age_days}d<{self._min_listing_days}d)",
                market_cap_cr=market_cap_cr,
                adtv_cr=adtv_cr,
                listing_age_days=listing_age_days,
                is_under_asm_gsm=False,
                days_to_next_event=None,
            )

        # -------------------------------------------------------------------
        # Gate 4 — Not in ASM/GSM
        # -------------------------------------------------------------------
        is_under_asm_gsm = self._is_under_surveillance(symbol)
        if is_under_asm_gsm:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason="UNDER_ASM_GSM_SURVEILLANCE",
                market_cap_cr=market_cap_cr,
                adtv_cr=adtv_cr,
                listing_age_days=listing_age_days,
                is_under_asm_gsm=True,
                days_to_next_event=None,
            )

        # -------------------------------------------------------------------
        # Gate 5 — No earnings/corp action within binary_event_block_days
        # -------------------------------------------------------------------
        days_to_next_event = self._days_to_next_event(symbol, eval_date)
        if (
            days_to_next_event is not None
            and days_to_next_event <= self._binary_event_block_days
        ):
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason=f"BINARY_EVENT_TOO_CLOSE({days_to_next_event}d)",
                market_cap_cr=market_cap_cr,
                adtv_cr=adtv_cr,
                listing_age_days=listing_age_days,
                is_under_asm_gsm=False,
                days_to_next_event=days_to_next_event,
            )

        # -------------------------------------------------------------------
        # Gate 6 — Volume Breakout: today's volume >= multiplier × 20-day avg volume
        # -------------------------------------------------------------------
        today_volume = int(raw_ohlcv["volume_raw"].iloc[-1]) if not raw_ohlcv.empty else 0
        avg_volume = float(raw_ohlcv["volume_raw"].iloc[:-1].mean()) if len(raw_ohlcv) > 1 else 0.0
        if self._volume_breakout_mult > 0 and avg_volume > 0 and today_volume < self._volume_breakout_mult * avg_volume:
            return ScreeningResult(
                symbol=symbol,
                passed=False,
                rejection_reason=f"NO_VOLUME_BREAKOUT({today_volume}<{self._volume_breakout_mult:.1f}x avg {avg_volume:.0f})",
                market_cap_cr=market_cap_cr,
                adtv_cr=adtv_cr,
                listing_age_days=listing_age_days,
                is_under_asm_gsm=False,
                days_to_next_event=days_to_next_event,
            )

        # -------------------------------------------------------------------
        # Gate 7 — Relative Strength: 3-month return in top N% of universe
        # -------------------------------------------------------------------
        if self._rs_threshold_return is not None:
            rs_ohlcv = self._fetch_ohlcv(symbol, eval_date, lookback=self._rs_lookback + 5)
            if len(rs_ohlcv) >= self._rs_lookback:
                price_now = float(rs_ohlcv["close_raw"].iloc[-1])
                price_then = float(rs_ohlcv["close_raw"].iloc[-self._rs_lookback])
                symbol_return = (price_now - price_then) / price_then if price_then > 0 else 0.0
                if symbol_return < self._rs_threshold_return:
                    return ScreeningResult(
                        symbol=symbol,
                        passed=False,
                        rejection_reason=f"WEAK_RELATIVE_STRENGTH({symbol_return*100:.1f}%<threshold {self._rs_threshold_return*100:.1f}%)",
                        market_cap_cr=market_cap_cr,
                        adtv_cr=adtv_cr,
                        listing_age_days=listing_age_days,
                        is_under_asm_gsm=False,
                        days_to_next_event=days_to_next_event,
                    )

        # All gates passed
        return ScreeningResult(
            symbol=symbol,
            passed=True,
            rejection_reason=None,
            market_cap_cr=market_cap_cr,
            adtv_cr=adtv_cr,
            listing_age_days=listing_age_days,
            is_under_asm_gsm=False,
            days_to_next_event=days_to_next_event,
        )


    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_rs_threshold(self, symbols: list[str], eval_date: date) -> Optional[float]:
        """Compute the minimum 3-month return required to be in the top N% of the universe.

        Fetches only the start and end close prices for each symbol over the RS
        lookback window — two DB rows per symbol rather than a full OHLCV fetch.
        Returns the percentile cutoff value (e.g., the 65th percentile return
        for top-35% requirement), or ``None`` if insufficient data.
        """
        lookback = self._rs_lookback
        returns = []
        for sym in symbols:
            rows = self._session.execute(
                select(MarketDataLake.trade_date, MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == sym)
                .where(MarketDataLake.trade_date <= eval_date)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(lookback + 5)
            ).all()
            if len(rows) < lookback:
                continue
            price_now = float(rows[0].close_raw)
            price_then = float(rows[lookback - 1].close_raw)
            if price_then > 0:
                returns.append((price_now - price_then) / price_then)

        if not returns:
            return None

        # e.g. top 35% means we want symbols whose return >= 65th percentile
        cutoff_percentile = 100.0 - self._rs_top_pct
        threshold = float(pd.Series(returns).quantile(cutoff_percentile / 100.0))
        logger.debug(
            "[UniverseScreener] RS threshold for %s: %.2f%% (top %g%% of %d symbols)",
            eval_date, threshold * 100, self._rs_top_pct, len(returns)
        )
        return threshold


    def _get_all_symbols(self, eval_date: date) -> list[str]:
        """Return all distinct symbols in the data lake up to ``eval_date``."""
        rows = self._session.execute(
            select(MarketDataLake.symbol)
            .where(MarketDataLake.trade_date <= eval_date)
            .distinct()
        ).scalars().all()
        return list(rows)

    def _get_latest_price_and_shares(
        self, symbol: str, eval_date: date
    ) -> tuple[Optional[float], Optional[int]]:
        """Fetch latest raw close and PIT shares outstanding for ``symbol``.

        Returns
        -------
        (raw_close, shares_count) or (None, None) if data missing.
        """
        price_row = (
            self._session.execute(
                select(MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == symbol)
                .where(MarketDataLake.trade_date <= eval_date)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if price_row is None:
            return None, None

        shares_row = (
            self._session.execute(
                select(SharesOutstanding.shares_count)
                .where(SharesOutstanding.symbol == symbol)
                .where(SharesOutstanding.effective_date <= eval_date)
                .order_by(desc(SharesOutstanding.effective_date))
                .limit(1)
            )
            .scalars()
            .first()
        )
        if shares_row is None:
            return None, None

        return float(price_row), int(shares_row)

    def _fetch_ohlcv(
        self, symbol: str, eval_date: date, lookback: int
    ) -> pd.DataFrame:
        """Fetch last ``lookback`` rows of raw OHLCV for ``symbol`` up to ``eval_date``."""
        rows = (
            self._session.execute(
                select(
                    MarketDataLake.trade_date,
                    MarketDataLake.open_raw,
                    MarketDataLake.high_raw,
                    MarketDataLake.low_raw,
                    MarketDataLake.close_raw,
                    MarketDataLake.volume_raw,
                )
                .where(MarketDataLake.symbol == symbol)
                .where(MarketDataLake.trade_date <= eval_date)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(lookback)
            )
            .all()
        )
        if not rows:
            return pd.DataFrame()

        rows = list(reversed(rows))  # chronological order
        return pd.DataFrame(
            [
                {
                    "trade_date": r.trade_date,
                    "open_raw": float(r.open_raw),
                    "high_raw": float(r.high_raw),
                    "low_raw": float(r.low_raw),
                    "close_raw": float(r.close_raw),
                    "volume_raw": int(r.volume_raw),
                }
                for r in rows
            ]
        ).set_index("trade_date")

    def _get_listing_age(self, symbol: str, eval_date: date) -> Optional[int]:
        """Count the number of trading days the symbol has been in the data lake."""
        count = (
            self._session.execute(
                select(func.count(MarketDataLake.id))
                .where(MarketDataLake.symbol == symbol)
                .where(MarketDataLake.trade_date <= eval_date)
            )
            .scalar()
        )
        return int(count) if count else None

    def _is_under_surveillance(self, symbol: str) -> bool:
        """Return ``True`` if the symbol appears in the ASM/GSM list."""
        row = (
            self._session.execute(
                select(ASMGSMList.id).where(ASMGSMList.symbol == symbol).limit(1)
            )
            .scalars()
            .first()
        )
        return row is not None

    def _days_to_next_event(
        self, symbol: str, eval_date: date
    ) -> Optional[int]:
        """Return calendar days to the nearest upcoming event, or ``None`` if none found.

        The look-ahead window is ``binary_event_block_days`` + a small buffer
        to avoid edge cases.
        """
        look_ahead = eval_date + timedelta(days=self._binary_event_block_days + 1)
        row = (
            self._session.execute(
                select(EarningsCalendar.event_date)
                .where(EarningsCalendar.symbol == symbol)
                .where(EarningsCalendar.event_date > eval_date)
                .where(EarningsCalendar.event_date <= look_ahead)
                .order_by(EarningsCalendar.event_date)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return None
        return (row - eval_date).days

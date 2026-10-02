"""
FInsight Trading Engine — In-Memory Corporate Action Adjustments
================================================================
This module handles backward price adjustment for splits and bonus issues.

**Critical design invariants (must never be violated):**

1. Raw OHLCV data is **never mutated** — adjustments happen in-memory only.
2. ``compute_adtv`` and ``compute_market_cap`` **always** use raw prices, not
   adjusted prices.  These functions exist here as canonical implementations
   so callers never accidentally use adjusted prices for liquidity screening.
3. Volume is **never** included in the adjusted output DataFrame — callers
   must always use raw volume for ADTV computation.
4. This module is **pure** (no database access, no side-effects).  The caller
   is responsible for fetching ``corporate_actions`` from the DB before
   passing them in.

Adjustment Mechanics
--------------------
Backward price adjustment works by multiplying historical prices by a
*cumulative adjustment factor* that accounts for all corporate actions that
occurred **after** the ``as_of_date``.

For a **1:2 split** (1 new share for every 2 old shares):
    ``ratio_numerator = 1, ratio_denominator = 2``
    ``factor = numerator / denominator = 0.5``
    → Historical prices are halved.

For a **1:1 bonus** (1 bonus share for every 1 held):
    ``ratio_numerator = 1, ratio_denominator = 1``
    ``factor = 1 / (1 + 1) = 0.5``
    → Historical prices are halved (price dilutes by the bonus ratio).

For a **2:5 bonus** (2 bonus shares for every 5 held):
    ``factor = 5 / (5 + 2) ≈ 0.714``

For a **1:5 split** (1 new for every 5 old):
    ``factor = 1 / 5 = 0.2``

Multiple events compose multiplicatively (earliest events to the left):
    ``total_factor = factor_1 × factor_2 × …``
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from engine_core.indicators import sma


# ---------------------------------------------------------------------------
# Factor computation
# ---------------------------------------------------------------------------

def compute_cumulative_factor(
    corporate_actions: list[dict],
    as_of_date: date,
) -> float:
    """Compute the cumulative backward price-adjustment factor.

    Only corporate actions whose ``ex_date`` is **strictly after**
    ``as_of_date`` are included.  This preserves point-in-time (PIT) data
    integrity: when pricing data as of a historical date we must not
    contaminate past prices with future corporate actions.

    Parameters
    ----------
    corporate_actions:
        List of corporate-action dicts.  Each dict must contain:

        * ``ex_date`` (:class:`datetime.date` or ISO string): ex-dividend /
          ex-split / ex-bonus effective date.
        * ``action_type`` (str): ``'SPLIT'`` or ``'BONUS'`` (``'DIVIDEND'``
          is ignored — dividends do not require price adjustment for
          total-return comparisons in this engine).
        * ``ratio_numerator`` (float): see module docstring.
        * ``ratio_denominator`` (float): see module docstring.

    as_of_date:
        The date *up to which* we want adjusted historical prices.  Actions
        on or before this date are **excluded** (they are already reflected in
        the raw prices recorded before that date).

    Returns
    -------
    float
        Cumulative adjustment factor in the range ``(0, 1]``.  A factor of
        ``1.0`` means no adjustment is needed.  A factor of ``0.5`` means
        historical prices should be halved to be comparable with post-event
        prices.

    Raises
    ------
    ValueError
        If a recognised action type has ``None`` or zero ratio fields.

    Examples
    --------
    >>> from datetime import date
    >>> from engine_core.adjustments import compute_cumulative_factor
    >>> actions = [
    ...     {"ex_date": date(2024, 6, 1), "action_type": "SPLIT",
    ...      "ratio_numerator": 1.0, "ratio_denominator": 2.0},
    ... ]
    >>> compute_cumulative_factor(actions, as_of_date=date(2024, 5, 31))
    0.5
    """
    cumulative = 1.0

    for action in corporate_actions:
        # Normalise ex_date to a date object
        ex_date = action["ex_date"]
        if isinstance(ex_date, str):
            ex_date = date.fromisoformat(ex_date)

        # Only future actions (after as_of_date) affect past prices
        if ex_date <= as_of_date:
            continue

        action_type = action.get("action_type", "").upper()
        num: Optional[float] = action.get("ratio_numerator")
        den: Optional[float] = action.get("ratio_denominator")

        if action_type == "SPLIT":
            # 1-for-N split: factor = numerator / denominator
            # e.g. 1:2 split → 1/2 = 0.5 (each old share becomes 2 new ones,
            # price halves)
            if not num or not den:
                raise ValueError(
                    f"SPLIT action on {ex_date} has missing ratio fields: "
                    f"numerator={num}, denominator={den}"
                )
            factor = num / den

        elif action_type == "BONUS":
            # N:M bonus: for every M shares held, N bonus shares are issued.
            # Post-event share count = M + N, so price factor = M / (M + N).
            # e.g. 1:1 bonus → 1 / (1+1) = 0.5
            # e.g. 2:5 bonus → 5 / (5+2) ≈ 0.714
            if num is None or den is None:
                raise ValueError(
                    f"BONUS action on {ex_date} has missing ratio fields: "
                    f"numerator={num}, denominator={den}"
                )
            factor = den / (den + num)

        else:
            # DIVIDEND or unknown action types are skipped — this engine does
            # not adjust for dividends (gross returns, not total returns).
            continue

        cumulative *= factor

    return cumulative


def get_adjusted_series(
    raw_ohlcv: pd.DataFrame,
    corporate_actions: list[dict],
    as_of_date: date,
) -> pd.DataFrame:
    """Apply backward price adjustment to a raw OHLCV DataFrame in-memory.

    Prices in ``raw_ohlcv`` that are **on or before** ``as_of_date`` are
    multiplied by the cumulative adjustment factor derived from all corporate
    actions that occurred **after** ``as_of_date``.

    Parameters
    ----------
    raw_ohlcv:
        DataFrame containing raw unadjusted prices.  Must include columns:
        ``open_raw``, ``high_raw``, ``low_raw``, ``close_raw``.  The
        ``volume_raw`` column (if present) is intentionally **not** included
        in the output.
    corporate_actions:
        List of corporate-action dicts as accepted by
        :func:`compute_cumulative_factor`.
    as_of_date:
        Evaluation date.  This is usually "today" in the live runner and the
        specific backtest date in the back-tester.

    Returns
    -------
    pd.DataFrame
        New DataFrame (raw_ohlcv is **never mutated**) with columns:
        ``open_adj``, ``high_adj``, ``low_adj``, ``close_adj``.
        Volume is excluded — callers must always use ``raw_ohlcv.volume_raw``
        directly for ADTV computation.

    Notes
    -----
    All rows in ``raw_ohlcv`` receive the *same* factor.  A more granular
    per-action slice would be needed only if we stored per-row dates and
    needed to adjust across multiple events within the DataFrame's range.
    For the use-case here (adjust the full lookback window as of today),
    the single cumulative factor is correct.
    """
    # Never mutate the caller's DataFrame
    adj = raw_ohlcv.copy(deep=False)

    factor = compute_cumulative_factor(corporate_actions, as_of_date)

    return pd.DataFrame(
        {
            "open_adj": adj["open_raw"] * factor,
            "high_adj": adj["high_raw"] * factor,
            "low_adj": adj["low_raw"] * factor,
            "close_adj": adj["close_raw"] * factor,
        },
        index=adj.index,
    )


# ---------------------------------------------------------------------------
# Liquidity & valuation helpers
# ---------------------------------------------------------------------------

def compute_adtv(
    raw_close: pd.Series,
    raw_volume: pd.Series,
    period: int = 20,
) -> pd.Series:
    """Average Daily Traded Value (ADTV) using raw prices only.

    ``ADTV = SMA(raw_close × raw_volume, period)``

    **Invariant:** This function ALWAYS uses raw (unadjusted) prices.
    Adjusted prices must NEVER be substituted here — doing so would inflate
    or deflate historical ADTV and invalidate the liquidity gate.

    Parameters
    ----------
    raw_close:
        Series of raw unadjusted close prices.
    raw_volume:
        Series of raw trading volume (number of shares).
    period:
        SMA lookback for the ADTV calculation.  Defaults to 20 as specified
        in ``strategy_config.yaml`` ``data.adtv_sma_period``.

    Returns
    -------
    pd.Series
        ADTV in absolute currency units (e.g. rupees).  Divide by 1e7 to
        convert to crores (₹ crores = ₹10,000,000).
    """
    daily_traded_value = raw_close * raw_volume
    return sma(daily_traded_value, period)


def compute_market_cap(raw_close: float, shares_outstanding: int) -> float:
    """Point-in-time Market Capitalisation using raw price.

    ``Market Cap = raw_close × shares_outstanding``

    **Invariant:** This function ALWAYS uses raw (unadjusted) close.  Using
    adjusted prices would corrupt the market-cap gate in the universe screener
    and produce incorrect inclusion/exclusion decisions.

    Parameters
    ----------
    raw_close:
        The raw (unadjusted) closing price for the symbol on the eval date.
    shares_outstanding:
        The number of shares outstanding as of the eval date (point-in-time
        from the ``shares_outstanding`` table).

    Returns
    -------
    float
        Market capitalisation in absolute currency units.  Divide by 1e7 to
        convert to crores.
    """
    return float(raw_close) * int(shares_outstanding)

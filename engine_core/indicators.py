"""
FInsight Trading Engine — Technical Indicators (Pure Functions)
===============================================================
All functions in this module are **pure**: they accept pandas Series as input
and return pandas Series as output.  No database access, no side-effects, no
global state.  This makes every function trivially unit-testable and safely
reusable across both the live runner and the back-tester.

Conventions
-----------
* NaN is returned for any position that has insufficient lookback data.
* Callers must pass clean, chronologically-sorted Series (ascending index).
* Period validation raises ValueError early — no silent silencing of bad
  parameters that would produce meaningless results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_period(period: int, name: str = "period") -> None:
    """Raise ``ValueError`` when *period* is not a positive integer.

    Parameters
    ----------
    period:
        The lookback period to validate.
    name:
        Human-readable argument name used in the error message.
    """
    if not isinstance(period, int) or period < 1:
        raise ValueError(f"{name} must be a positive integer, got {period!r}")


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average (SMA).

    Computes the arithmetic mean of the last *period* values at every point.
    The first ``period - 1`` positions are returned as ``NaN`` because there
    is insufficient history to form a complete window.

    Parameters
    ----------
    series:
        Input price (or any numeric) series.  Index is preserved in output.
    period:
        Number of bars in the rolling window.  Must be a positive integer.

    Returns
    -------
    pd.Series
        SMA values aligned to the same index as *series*.

    Examples
    --------
    >>> import pandas as pd
    >>> from engine_core.indicators import sma
    >>> prices = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    >>> sma(prices, 3).iloc[-1]
    4.0
    """
    _validate_period(period, "period")
    return series.rolling(window=period, min_periods=period).mean()


def rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's Smoothing / Running Moving Average (RMA / SMMA).

    Wilder's smoothing is an exponential moving average with a smoothing
    factor of ``1 / period``.  It is used internally for ATR computation.

    The first valid value (at index ``period - 1``) is seeded with the simple
    average of the first *period* values, then the EMA recurrence is applied
    forward.  All positions before ``period - 1`` are returned as ``NaN``.

    Parameters
    ----------
    series:
        Input numeric series (e.g. true-range values).
    period:
        Lookback period.  Must be a positive integer.

    Returns
    -------
    pd.Series
        RMA values aligned to the same index as *series*.

    Notes
    -----
    This is **not** the standard ``pandas.ewm`` with ``com=period-1``; that
    would use a smoothing factor of ``1 / period`` as well, but Wilder's
    initialisation uses a simple-average seed rather than the first value.
    The implementation below matches TradingView's ``ta.rma()`` exactly.
    """
    _validate_period(period, "period")

    alpha = 1.0 / period
    values = series.to_numpy(dtype=float, na_value=np.nan)
    result = np.full(len(values), np.nan, dtype=float)

    # Find the first position where we have *period* consecutive non-NaN values
    # to seed the simple-average initial value.
    start = period - 1
    while start < len(values) and np.any(np.isnan(values[start - period + 1: start + 1])):
        start += 1

    if start >= len(values):
        # Not enough non-NaN data at all
        return pd.Series(result, index=series.index, name=series.name)

    # Seed with simple average of first `period` valid bars
    result[start] = np.nanmean(values[start - period + 1: start + 1])

    # Wilder recurrence forward
    for i in range(start + 1, len(values)):
        if np.isnan(values[i]):
            result[i] = np.nan
        else:
            result[i] = alpha * values[i] + (1.0 - alpha) * result[i - 1]

    return pd.Series(result, index=series.index, name=series.name)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range (ATR) using Wilder's smoothing.

    True Range is defined as the largest of:
    * ``high - low``
    * ``|high - prev_close|``
    * ``|low  - prev_close|``

    The first bar has no previous close, so its True Range is simply
    ``high - low`` (standard Wilder convention, not NaN-skipped).

    Parameters
    ----------
    high:
        Series of bar high prices (raw or adjusted — must be consistent with
        ``low`` and ``close``).
    low:
        Series of bar low prices.
    close:
        Series of bar close prices.
    period:
        ATR lookback period.  Defaults to 14 (Wilder's original setting).

    Returns
    -------
    pd.Series
        ATR values indexed identically to *close*.

    Raises
    ------
    ValueError
        If ``period`` is not a positive integer.

    Notes
    -----
    This implementation uses :func:`rma` internally, which matches the exact
    smoothing applied by Kite's charting and TradingView's ``ta.atr()``.
    """
    _validate_period(period, "period")

    # Align all inputs on the same index defensively
    high = high.reindex(close.index)
    low = low.reindex(close.index)

    prev_close = close.shift(1)

    # True range — element-wise max of the three components
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return rma(tr, period)


# ---------------------------------------------------------------------------
# Donchian Channels
# ---------------------------------------------------------------------------

def donchian_low(low: pd.Series, period: int = 20) -> pd.Series:
    """Donchian Channel — Lower Band (rolling minimum of lows).

    Used as the **structural stop-loss (Stop B)** in the sizing engine.
    The first ``period - 1`` positions are ``NaN`` due to insufficient
    lookback data.

    Parameters
    ----------
    low:
        Series of bar low prices.
    period:
        Rolling window length.  Defaults to 20 (per ``strategy_config.yaml``
        ``risk.donchian_period``).

    Returns
    -------
    pd.Series
        Rolling minimum of *low*, indexed identically to *low*.

    Examples
    --------
    >>> import pandas as pd
    >>> from engine_core.indicators import donchian_low
    >>> lows = pd.Series([10.0, 9.0, 8.0, 11.0, 7.0])
    >>> donchian_low(lows, period=3).iloc[-1]
    7.0
    """
    _validate_period(period, "period")
    return low.rolling(window=period, min_periods=period).min()


def donchian_high(high: pd.Series, period: int = 252) -> pd.Series:
    """Donchian Channel — Upper Band (rolling maximum of highs).

    Used as the **first structural resistance target** (52-week high proxy)
    in the sizing engine.  The lookback defaults to 252 trading days as
    configured in ``strategy_config.yaml`` ``data.resistance_lookback_days``.

    Parameters
    ----------
    high:
        Series of bar high prices.
    period:
        Rolling window length.  Defaults to 252 (one trading year).

    Returns
    -------
    pd.Series
        Rolling maximum of *high*, indexed identically to *high*.

    Examples
    --------
    >>> import pandas as pd
    >>> from engine_core.indicators import donchian_high
    >>> highs = pd.Series([100.0, 120.0, 110.0, 115.0, 105.0])
    >>> donchian_high(highs, period=3).iloc[-1]
    120.0
    """
    _validate_period(period, "period")
    return high.rolling(window=period, min_periods=period).max()

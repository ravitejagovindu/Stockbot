"""engine_core/entry_filters.py — entry quality filters and deterministic ranking.

Used by both the live pipeline and the backtest simulator to ensure identical
candidate selection logic in both environments.
"""
from __future__ import annotations

import pandas as pd


def passes_trend_filter(close: pd.Series, fast: int, slow: int) -> bool:
    """Return True iff close > SMA(fast) and SMA(fast) > SMA(slow).

    Requires at least ``slow`` bars of history; returns False if insufficient.
    """
    if len(close) < slow:
        return False
    f, s, c = close.rolling(fast).mean().iloc[-1], close.rolling(slow).mean().iloc[-1], close.iloc[-1]
    return bool(c > f and f > s)


def passes_breakout(close: pd.Series, high: pd.Series, lookback: int) -> bool:
    """Return True iff today's close >= the highest high of the prior ``lookback`` sessions.

    Requires at least ``lookback + 1`` bars of history; returns False if insufficient.
    """
    if len(high) < lookback + 1:
        return False
    return bool(close.iloc[-1] >= high.iloc[-(lookback + 1):-1].max())


def rs_return(close: pd.Series, lookback: int) -> float:
    """Compute the relative-strength return over ``lookback`` periods.

    Returns float("nan") if insufficient history.
    """
    return float(close.iloc[-1] / close.iloc[-(lookback + 1)] - 1.0) if len(close) > lookback else float("nan")


def apply_entry_filters(cands: list, cfg: dict) -> list:
    """Filter by trend + breakout, then rank by RS descending then symbol ascending.

    Same function used in live pipeline AND backtest simulator to guarantee
    identical candidate selection.

    Parameters
    ----------
    cands:
        List of candidate dicts.  Each must have an ``adjusted_ohlcv`` key
        containing a DataFrame with ``close_adj`` and ``high_adj`` columns,
        and a ``symbol`` key.
    cfg:
        Full strategy config dict.

    Returns
    -------
    list
        Filtered and ranked candidates (each augmented with an ``rs_3m`` key).
    """
    ef = cfg.get("entry_filters", {})
    kept = []
    for c in cands:
        adj = c["adjusted_ohlcv"]
        close, high = adj["close_adj"], adj["high_adj"]
        if ef.get("trend_filter_enabled") and not passes_trend_filter(
                close, int(ef.get("trend_fast_sma", 50)), int(ef.get("trend_slow_sma", 200))):
            continue
        if ef.get("breakout_required") and not passes_breakout(close, high, int(ef.get("breakout_lookback", 20))):
            continue
        d = dict(c)
        d["rs_3m"] = rs_return(close, int(ef.get("rs_lookback_days", 63)))
        kept.append(d)
    kept.sort(key=lambda c: (-c["rs_3m"] if pd.notna(c["rs_3m"]) else 1e9, c["symbol"]))
    return kept

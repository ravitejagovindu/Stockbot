"""engine_core/entry_filters.py — entry quality filters and deterministic ranking.

Used by both the live pipeline and the backtest simulator to ensure identical
candidate selection logic in both environments.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
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


def passes_pullback(
    close: pd.Series,
    period: int = 20,
    lower_tol: float = 0.98,
    upper_tol: float = 1.03,
) -> bool:
    """Return True iff today's close is within [lower_tol * SMA, upper_tol * SMA] of SMA(period).

    Requires at least ``period`` bars of history; returns False if insufficient.
    """
    if len(close) < period:
        return False
    sma_val = close.rolling(period).mean().iloc[-1]
    if pd.isna(sma_val) or sma_val <= 0:
        return False
    c = close.iloc[-1]
    return bool(lower_tol * sma_val <= c <= upper_tol * sma_val)


def rs_return(close: pd.Series, lookback: int) -> float:
    """Compute the relative-strength return over ``lookback`` periods.

    Returns float("nan") if insufficient history.
    """
    return float(close.iloc[-1] / close.iloc[-(lookback + 1)] - 1.0) if len(close) > lookback else float("nan")


def compute_universe_rs_cutoff(cands: list, percentile: float | None, lookback: int = 63) -> float | None:
    """Compute the RS return threshold for the top `percentile`% of the screened universe.

    For example, for percentile=30.0 (top 30%), returns the 70th percentile of universe RS returns.
    Returns None if percentile is None or >= 100.0, or if insufficient candidates.
    """
    if percentile is None or percentile >= 100.0 or not cands:
        return None
    rs_vals = []
    for c in cands:
        adj = c.get("adjusted_ohlcv")
        if adj is not None and "close_adj" in adj:
            r = rs_return(adj["close_adj"], lookback)
            if pd.notna(r):
                rs_vals.append(r)
    if not rs_vals:
        return None
    return float(np.percentile(rs_vals, 100.0 - float(percentile)))


def apply_rs_rank_percentile(cands: list, percentile: float | None) -> list:
    """[DEPRECATED] Legacy candidate-pool relative strength rank filter.

    .. deprecated:: Phase2-Audit
       Use :func:`compute_universe_rs_cutoff` instead. Production strategy execution
       computes the RS cutoff across the entire screened liquid universe (Gates 1-3)
       prior to candidate technical filtering to prevent thin-day distortion.
       This function operates on post-filter candidate lists and is retained only
       for backwards compatibility with legacy unit tests.

    Uses mathematical ceil: keeps ceil(len(cands) * percentile / 100) candidates.
    If percentile is None or >= 100.0, returns all candidates.
    Candidates must be pre-sorted descending by rs_3m (with secondary sort by symbol ASC).
    """
    warnings.warn(
        "apply_rs_rank_percentile is deprecated. Use compute_universe_rs_cutoff for broad universe filtering.",
        DeprecationWarning,
        stacklevel=2,
    )
    if percentile is None or percentile >= 100.0 or not cands:
        return cands
    cutoff_count = int(math.ceil(len(cands) * (percentile / 100.0)))
    return cands[:cutoff_count]


def apply_entry_filters(cands: list, cfg: dict) -> list:
    """Filter by trend + breakout/pullback, and universe Relative Strength percentile.

    Same function used in live pipeline AND backtest simulator to guarantee
    identical candidate selection.

    Parameters
    ----------
    cands:
        List of candidate dicts built from the screened liquid universe (Gates 1-3).
        Each candidate dict must contain ``adjusted_ohlcv`` and ``symbol``.
    cfg:
        Full strategy config dict.

    Returns
    -------
    list
        Filtered and ranked candidates (each augmented with an ``rs_3m`` key).
    """
    ef = cfg.get("entry_filters", {})
    rs_lookback = int(ef.get("rs_lookback_days", 63))
    pct = ef.get("rs_rank_percentile")

    # Compute universe RS cutoff across screened liquid universe
    cutoff_rs = compute_universe_rs_cutoff(cands, float(pct) if pct is not None else None, rs_lookback)

    kept = []
    for c in cands:
        adj = c["adjusted_ohlcv"]
        close, high = adj["close_adj"], adj["high_adj"]
        if ef.get("trend_filter_enabled") and not passes_trend_filter(
                close, int(ef.get("trend_fast_sma", 50)), int(ef.get("trend_slow_sma", 200))):
            continue
        if ef.get("breakout_required") and not passes_breakout(
                close, high, int(ef.get("breakout_lookback", 20))):
            continue
        if ef.get("pullback_required") and not passes_pullback(
                close,
                int(ef.get("pullback_sma_period", 20)),
                float(ef.get("pullback_tolerance_lower", 0.98)),
                float(ef.get("pullback_tolerance_upper", 1.03))):
            continue

        d = dict(c)
        d["rs_3m"] = rs_return(close, rs_lookback)

        # Enforce universe RS percentile cutoff
        if cutoff_rs is not None and (pd.isna(d["rs_3m"]) or d["rs_3m"] < cutoff_rs):
            continue

        kept.append(d)

    # Deterministic secondary sort: rs_3m descending, symbol ascending
    kept.sort(key=lambda c: (-c["rs_3m"] if pd.notna(c["rs_3m"]) else 1e9, c["symbol"]))

    return kept

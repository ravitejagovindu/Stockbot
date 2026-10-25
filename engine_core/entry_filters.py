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


def apply_rs_rank_percentile(cands: list, percentile: float | None) -> list:
    """Filter candidates to keep only the top `percentile`% by rs_3m.

    If percentile is None or >= 100.0, returns all candidates.
    Candidates must be pre-sorted descending by rs_3m (with secondary sort by symbol ASC).
    At least 1 candidate is kept if cands is non-empty.
    """
    if percentile is None or percentile >= 100.0 or not cands:
        return cands
    cutoff_count = max(1, int(len(cands) * (percentile / 100.0)))
    return cands[:cutoff_count]


def apply_entry_filters(cands: list, cfg: dict) -> list:
    """Filter by trend + breakout/pullback, rank by RS descending, and optionally cut by percentile.

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
        d["rs_3m"] = rs_return(close, int(ef.get("rs_lookback_days", 63)))
        kept.append(d)

    # Deterministic secondary sort: rs_3m descending, symbol ascending
    kept.sort(key=lambda c: (-c["rs_3m"] if pd.notna(c["rs_3m"]) else 1e9, c["symbol"]))

    pct = ef.get("rs_rank_percentile")
    if pct is not None:
        kept = apply_rs_rank_percentile(kept, float(pct))

    return kept

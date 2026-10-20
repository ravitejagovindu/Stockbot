"""engine_core/regime_gates.py — stateless market-regime gate functions.

These replace window-name string checks (``bull_run``, ``sideways_inflation``,
``enabled_regimes``) with state-driven predicates that work identically
in the live pipeline and the backtest simulator.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, desc

from data.db.models import MarketDataLake


def is_bull(kill_switch_active: bool, nifty_close: Optional[float], nifty_sma200: Optional[float]) -> bool:
    """Return True iff kill switch is OFF and Nifty is above its 200-day SMA."""
    return bool(
        (not kill_switch_active)
        and nifty_close is not None
        and nifty_sma200 is not None
        and nifty_close > nifty_sma200
    )


def bull_correction_active(nifty_close, nifty_sma200, nifty_sma_entry) -> bool:
    """Above the 200-day (bull) but below the entry SMA (e.g. 50-day): pause NEW entries."""
    if nifty_close is None or nifty_sma200 is None or nifty_sma_entry is None:
        return False
    return bool(nifty_close > nifty_sma200 and nifty_close < nifty_sma_entry)


def nifty_sma(session, config: dict, eval_date, period: int) -> Optional[float]:
    """Compute the simple moving average of Nifty close over the last ``period`` sessions up to eval_date."""
    sym = config.get("data", {}).get("nifty_symbol", "NIFTY50_INDEX")
    rows = session.execute(
        select(MarketDataLake.close_raw)
        .where(MarketDataLake.symbol == sym)
        .where(MarketDataLake.trade_date <= eval_date)
        .order_by(desc(MarketDataLake.trade_date))
        .limit(period)
    ).scalars().all()
    return float(sum(rows) / period) if len(rows) >= period else None

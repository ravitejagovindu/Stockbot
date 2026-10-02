"""
FInsight Trading Engine — engine_core package
=============================================
Public re-exports for the engine_core package.

Import order matters for circular-import avoidance:
  indicators → adjustments → regime_filter / universe_screener / risk_sizing
  → position_lifecycle → analytics_loop
"""
from engine_core.indicators import sma, rma, atr, donchian_low, donchian_high
from engine_core.adjustments import (
    compute_cumulative_factor,
    get_adjusted_series,
    compute_adtv,
    compute_market_cap,
)
from engine_core.regime_filter import RegimeFilter, RegimeState
from engine_core.universe_screener import UniverseScreener, ScreeningResult
from engine_core.risk_sizing import RiskAndSizingEngine, TradeSetup
from engine_core.position_lifecycle import (
    PositionLifecycleManager,
    PositionState,
    PositionUpdate,
)
from engine_core.analytics_loop import AnalyticsLoop

__all__ = [
    # indicators
    "sma",
    "rma",
    "atr",
    "donchian_low",
    "donchian_high",
    # adjustments
    "compute_cumulative_factor",
    "get_adjusted_series",
    "compute_adtv",
    "compute_market_cap",
    # regime
    "RegimeFilter",
    "RegimeState",
    # screener
    "UniverseScreener",
    "ScreeningResult",
    # sizing
    "RiskAndSizingEngine",
    "TradeSetup",
    # lifecycle
    "PositionLifecycleManager",
    "PositionState",
    "PositionUpdate",
    # analytics
    "AnalyticsLoop",
]

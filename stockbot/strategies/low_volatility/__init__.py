"""low_volatility strategy package (status: research). See ``strategy.py`` for the rule and ``docs/strategies/low_volatility/`` for the brief and status."""
from stockbot.strategies.low_volatility.strategy import SPEC, LowVolatilityStrategy, register

__all__ = ["SPEC", "LowVolatilityStrategy", "register"]

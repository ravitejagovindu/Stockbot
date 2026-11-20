"""momentum_calm_daily strategy package (status: research). See ``strategy.py`` for the rule, ``exits.py`` for its own exit policy and ``docs/strategies/momentum_calm_daily/`` for the brief and status."""
from stockbot.strategies.momentum_calm_daily.exits import ID as EXIT_ID, McdTrailingAtr3Floor8
from stockbot.strategies.momentum_calm_daily.strategy import SPEC, MomentumCalmDailyStrategy, register

__all__ = ["EXIT_ID", "SPEC", "MomentumCalmDailyStrategy", "McdTrailingAtr3Floor8", "register"]

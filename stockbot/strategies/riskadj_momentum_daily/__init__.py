"""riskadj_momentum_daily strategy package (status: research). See ``strategy.py`` for the rule, ``exits.py`` for its own exit policy and ``docs/strategies/riskadj_momentum_daily/`` for the brief and status."""
from stockbot.strategies.riskadj_momentum_daily.exits import ID as EXIT_ID, RmdTrailingAtr3Floor8
from stockbot.strategies.riskadj_momentum_daily.strategy import SPEC, RiskAdjMomentumDailyStrategy, register

__all__ = ["EXIT_ID", "SPEC", "RiskAdjMomentumDailyStrategy", "RmdTrailingAtr3Floor8", "register"]

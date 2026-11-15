"""riskadj_momentum strategy package (status: research). See ``strategy.py`` for the rule, ``exits.py`` for its own exit policy and ``docs/strategies/riskadj_momentum/`` for the brief and status."""
from stockbot.strategies.riskadj_momentum.exits import ID as EXIT_ID, TrailingAtr3Floor8
from stockbot.strategies.riskadj_momentum.strategy import SPEC, RiskAdjMomentumStrategy, register

__all__ = ["EXIT_ID", "SPEC", "RiskAdjMomentumStrategy", "TrailingAtr3Floor8", "register"]

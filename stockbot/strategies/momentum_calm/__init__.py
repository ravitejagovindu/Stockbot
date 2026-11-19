"""momentum_calm strategy package (status: research). See ``strategy.py`` for the rule, ``exits.py`` for its own exit policy and ``docs/strategies/momentum_calm/`` for the brief and status."""
from stockbot.strategies.momentum_calm.exits import ID as EXIT_ID, McTrailingAtr3Floor8
from stockbot.strategies.momentum_calm.strategy import SPEC, MomentumCalmStrategy, register

__all__ = ["EXIT_ID", "SPEC", "MomentumCalmStrategy", "McTrailingAtr3Floor8", "register"]

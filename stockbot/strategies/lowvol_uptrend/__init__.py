"""lowvol_uptrend strategy package (status: research). See ``strategy.py`` for the rule, ``exits.py`` for its own exit policy and ``docs/strategies/lowvol_uptrend/`` for the brief and status."""
from stockbot.strategies.lowvol_uptrend.exits import ID as EXIT_ID, LvTrailingAtr3Floor8
from stockbot.strategies.lowvol_uptrend.strategy import SPEC, LowVolUptrendStrategy, register

__all__ = ["EXIT_ID", "SPEC", "LowVolUptrendStrategy", "LvTrailingAtr3Floor8", "register"]

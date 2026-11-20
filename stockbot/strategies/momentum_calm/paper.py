"""momentum_calm in PAPER status. The registered research spec (``SPEC``, status ``research``, the hash in the family ledger) is NOT touched: this module derives the paper spec from it with
``dataclasses.replace`` changing ONLY ``status`` (so params, universe overrides, exit policy, overlays, pre-registration reference and every other field are the registered ones).
Owner decision for the paper phase: docs/strategies/momentum_calm/paper/PAPER_DECISION.md. The paper spec has its own config hash (status is part of it); the rule hash is the registered one."""
from __future__ import annotations

import dataclasses

from stockbot.strategies.momentum_calm.exits import McTrailingAtr3Floor8
from stockbot.strategies.momentum_calm.strategy import SPEC, MomentumCalmStrategy

PAPER_SPEC = dataclasses.replace(SPEC, status="paper")
PAPER_START_CASH = 200000.0       # INR, owner decision: forward-only account, NO deposits or withdrawals, idle cash earns nothing. Kept OUT of shared.yaml on purpose: runtime.paper_start_equity (1,000,000) is
                                  # part of shared_config_hash, which every registered backtest manifest records.


def rule_fields(spec) -> dict:
    """Every spec field except ``status``: what the paper spec must share with the registered spec."""
    return {f.name: getattr(spec, f.name) for f in dataclasses.fields(spec) if f.name != "status"}


def paper_strategy() -> MomentumCalmStrategy:
    return MomentumCalmStrategy(PAPER_SPEC)


def paper_policy_extras() -> list:
    return [McTrailingAtr3Floor8()]


def rule_hash(spec) -> str:
    """sha256 of the canonical JSON of every spec field except ``status``. Equal for the registered and the paper spec; ``config_hash`` (which includes status) differs."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(rule_fields(spec), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

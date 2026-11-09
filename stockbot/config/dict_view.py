"""The shared configuration as the plain nested dict that the legacy consumers (ingestion, quality checker, API routers, analytics, paper report) were written against.

Section names follow the old file (``portfolio_risk`` -> ``risk``, ``exclusions`` -> ``earnings``, ``live`` -> ``trade_management``, ``validation_gates`` -> ``gates``); values come from
``shared.yaml`` and are therefore identical to the old ``strategy_config.yaml`` for every shared key (tests/unit/test_shared_config.py). Old-strategy keys are NOT here: they are
recorded in docs/restructure/OLD_STRATEGY_REFERENCE.md (values) and the frozen copy of the old file in tests/golden. Read-only; a fresh dict on every call.
"""
from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Optional

from stockbot.config.shared import SharedConfig, load_shared_config

RENAMED = {"portfolio_risk": "risk", "exclusions": "earnings", "live": "trade_management", "validation_gates": "gates"}


def config_dict(cfg: Optional[SharedConfig] = None) -> dict[str, Any]:
    cfg = cfg or load_shared_config()
    out: dict[str, Any] = {}
    for f in fields(cfg):
        section = RENAMED.get(f.name, f.name)
        value = asdict(getattr(cfg, f.name))
        if f.name == "backtest":
            value["regimes"] = [dict(r) for r in value["regimes"]]
        out[section] = value
    return out

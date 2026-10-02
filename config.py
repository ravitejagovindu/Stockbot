"""
FInsight Trading Engine — Strategy Configuration Loader

Loads strategy_config.yaml once at startup and provides typed access.
All numeric parameters flow from here — no hardcoded magic numbers anywhere else.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(__file__).parent / "strategy_config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """
    Load strategy_config.yaml. Cached after first call.

    Returns the full config dict. Access like:
        cfg = load_config()
        cfg['risk']['atr_period']  # => 14
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict) -> None:
    """Validate required keys exist and values are sane."""
    required_sections = ["universe", "macro", "risk", "trade_management", "data", "backtest"]
    for section in required_sections:
        if section not in cfg:
            raise ValueError(f"strategy_config.yaml is missing required section: '{section}'")

    risk = cfg["risk"]
    assert risk["max_loss_pct_per_trade"] > 0, "max_loss_pct_per_trade must be positive"
    assert risk["min_rr_ratio"] >= 1.0, "min_rr_ratio must be >= 1.0"
    assert risk["max_concurrent_positions"] > 0, "max_concurrent_positions must be positive"
    assert risk["max_total_portfolio_risk_pct"] <= 100, "max_total_portfolio_risk_pct must be <= 100"
    assert risk["max_sector_exposure_pct"] <= 100, "max_sector_exposure_pct must be <= 100"

    macro = cfg["macro"]
    assert macro["vix_reentry_threshold"] < macro["vix_kill_threshold"], \
        "vix_reentry_threshold must be < vix_kill_threshold (hysteresis)"
    assert macro["nifty_reentry_sma_period"] < macro["nifty_kill_sma_period"], \
        "reentry SMA period must be shorter than kill SMA period"

"""Per-run override of ``portfolio_risk.max_loss_pct_per_trade`` for the research, baseline and short-step scripts of a registered backtest trial (family_batch6: 0.5 instead of 1.0).

Default OFF: ``STOCKBOT_RISK_PCT`` unset or empty changes nothing (``apply`` returns the SAME config object, the manifest gets no block), so every stored result reproduces byte-identically.
``shared.yaml`` is never edited. With the variable set (0.1 to 1.0 accepted; anything else is an error) ``apply`` returns a copy of the shared config with only that one number replaced.
Paper and live mode refuse the override (``refuse_in_paper_live``, called by ``stockbot.live.runner.run_eod``). The run manifest carries ``risk_override`` (value and the shared.yaml base value),
``baseline_meta.json`` carries the same block, and ``scripts/validate_family.py`` refuses members run with different values.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from typing import Optional

ENV = "STOCKBOT_RISK_PCT"
MIN_PCT, MAX_PCT = 0.1, 1.0


class RiskOverrideError(ValueError):
    pass


def override_value() -> Optional[float]:
    """The override in percent of equity, or None when the variable is unset or empty. Raises RiskOverrideError for a value that is not a number in [0.1, 1.0]."""
    raw = os.environ.get(ENV, "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        raise RiskOverrideError(f"{ENV}={raw!r} is not a number") from None
    if not (MIN_PCT <= v <= MAX_PCT):                    # also rejects nan (comparisons are false)
        raise RiskOverrideError(f"{ENV}={raw} is outside the accepted range {MIN_PCT} to {MAX_PCT} (percent of equity)")
    return v


def apply(cfg):
    """``cfg`` with max_loss_pct_per_trade replaced when the override is on; the same object when it is off."""
    v = override_value()
    if v is None:
        return cfg
    print(f"RISK OVERRIDE ON: max_loss_pct_per_trade = {v} (shared.yaml base {cfg.portfolio_risk.max_loss_pct_per_trade}); {ENV} is read by this run's scripts only", file=sys.stderr, flush=True)
    return dataclasses.replace(cfg, portfolio_risk=dataclasses.replace(cfg.portfolio_risk, max_loss_pct_per_trade=v))


def block(base_cfg) -> Optional[dict]:
    """The manifest block, or None when the override is off. ``base_cfg`` is the config BEFORE ``apply`` (the shared.yaml value)."""
    v = override_value()
    if v is None:
        return None
    return {"env": ENV, "max_loss_pct_per_trade": v, "base_max_loss_pct_per_trade": base_cfg.portfolio_risk.max_loss_pct_per_trade,
            "note": "per-run override for the registered trial; shared.yaml unchanged; paper and live refuse it"}


def refuse_in_paper_live() -> None:
    if os.environ.get(ENV, "").strip():
        raise RiskOverrideError(f"{ENV} is set: the risk override is for registered backtest trials only; paper and live mode refuse it (unset {ENV})")

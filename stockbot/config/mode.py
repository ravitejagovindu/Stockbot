"""Runtime mode resolution for FInsight Trading Engine."""
from __future__ import annotations


def current_mode(config: dict) -> str:
    """Return the active runtime mode ('PAPER' or 'LIVE').

    Raises
    ------
    ValueError
        If runtime.mode is missing or not one of ('PAPER', 'LIVE').
    """
    m = str(config.get("runtime", {}).get("mode", "")).upper()
    if m not in ("PAPER", "LIVE"):
        raise ValueError("strategy_config.yaml: runtime.mode must be PAPER or LIVE")
    return m

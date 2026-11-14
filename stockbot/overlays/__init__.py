"""Shared overlays: market-wide rules that the engine applies to every strategy (the shared default, ``shared.yaml`` section ``overlays``).

``resolve_default_overlays(shared_config, ids=None)`` is THE place that turns the configured ids into overlay objects; ``stockbot.engine.decide`` calls it, so backtest, paper and live
(all of which call ``decide``) share one code path. ``ids=[]`` is the explicit opt-out (a comparison run WITHOUT the overlays); ``ids=None`` means the shared default.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from stockbot.overlays.market_switch import ID as MARKET_SWITCH_ID, MarketSwitch, MarketSwitchParams

KNOWN = (MARKET_SWITCH_ID,)


def resolve_default_overlays(shared_config, ids: Optional[Sequence[str]] = None) -> Mapping[str, object]:
    ids = tuple(shared_config.overlays.default if ids is None else ids)
    out = {}
    for oid in ids:
        if oid == MARKET_SWITCH_ID:
            out[oid] = MarketSwitch(MarketSwitchParams.from_shared(shared_config))
        else:
            raise ValueError(f"unknown default overlay {oid!r}; known: {KNOWN}")
    return out


def describe_default_overlays(shared_config, ids: Optional[Sequence[str]] = None) -> list:
    """What goes into the run manifest and the config hash: id, version and numbers of every default overlay in force ([] when switched off)."""
    return [ov.describe() for ov in resolve_default_overlays(shared_config, ids).values()]

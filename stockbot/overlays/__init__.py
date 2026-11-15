"""Shared overlay library: market-wide rules (``shared.yaml`` section ``overlays`` holds their numbers). A strategy opts in with StrategySpec.overlays = {"market_switch_v1": "1.0.0"};
``overlays.default`` (empty today) would apply an overlay to EVERY strategy.

``resolve_default_overlays(shared_config, ids=None)`` is THE place that turns the configured ids into overlay objects; ``stockbot.engine.decide`` calls it, so backtest, paper and live
(all of which call ``decide``) share one code path. ``ids=[]`` is the explicit opt-out (a comparison run WITHOUT the overlays); ``ids=None`` means the shared default.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from stockbot.overlays.market_switch import ID as MARKET_SWITCH_ID, MarketSwitch, MarketSwitchParams

KNOWN = (MARKET_SWITCH_ID,)


def library_overlay(shared_config, oid: str):
    """The shared-library overlay with this id, parameters from ``shared.yaml`` (section overlays); None when the id is not in the library."""
    if oid == MARKET_SWITCH_ID:
        return MarketSwitch(MarketSwitchParams.from_shared(shared_config))
    return None


def resolve_default_overlays(shared_config, ids: Optional[Sequence[str]] = None) -> Mapping[str, object]:
    ids = tuple(shared_config.overlays.default if ids is None else ids)
    out = {}
    for oid in ids:
        ov = library_overlay(shared_config, oid)
        if ov is None:
            raise ValueError(f"unknown default overlay {oid!r}; known: {KNOWN}")
        out[oid] = ov
    return out


def describe_effective_overlays(shared_config, strategies: Sequence = (), ids: Optional[Sequence[str]] = None) -> list:
    """Library overlays in force in a run: the shared defaults plus every one a strategy declares (id, version, numbers). [] when none: such a run is byte-identical to master."""
    out = {o["id"]: o for o in describe_default_overlays(shared_config, ids)}
    for s in strategies:
        for oid in s.spec.overlays:
            ov = library_overlay(shared_config, oid)
            if ov is not None:
                out[oid] = ov.describe()
    return [out[k] for k in sorted(out)]


def describe_default_overlays(shared_config, ids: Optional[Sequence[str]] = None) -> list:
    """What goes into the run manifest and the config hash: id, version and numbers of every default overlay in force ([] when switched off)."""
    return [ov.describe() for ov in resolve_default_overlays(shared_config, ids).values()]

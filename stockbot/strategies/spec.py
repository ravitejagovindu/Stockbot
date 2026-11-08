"""Strategy specification schema (restructure Phase 4). Standard library only: the strategies package may import nothing else but data view types.

A spec DESCRIBES a strategy (identity, parameters, which exit policy it uses, its lifecycle status, pre-registration and validation references,
its expected trade rate and smallest edge of interest).  It cannot override the shared config: shared sections (costs, execution, portfolio risk,
validation gates, paper criteria, ...) may not appear in ``params`` or ``universe_overrides``.  ``config_hash`` identifies the exact configuration.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields
from typing import Any, Mapping, Optional

STATUSES = ("research", "paper", "live")
# mirrors stockbot.config.shared.NON_OVERRIDABLE (tests/unit/test_strategy_spec.py asserts they are equal)
NON_OVERRIDABLE = frozenset({"runtime", "data", "execution", "costs", "portfolio_risk", "exclusions", "live", "backtest", "validation_gates", "paper_criteria"})
UNIVERSE_OVERRIDABLE = frozenset({"min_adtv_cr", "min_listing_age_trading_days"})     # min_market_cap_cr is parked (KI-001) and cannot be overridden
_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class SpecError(ValueError):
    pass


def _jsonable(v: Any, where: str) -> Any:
    try:
        return json.loads(json.dumps(v, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{where} must be JSON-serialisable: {exc}") from exc


@dataclass(frozen=True)
class StrategySpec:
    id: str
    version: str
    params: Mapping[str, Any] = field(default_factory=dict)
    universe_overrides: Mapping[str, Any] = field(default_factory=dict)
    exit_policy: str = ""
    status: str = "research"
    prereg_ref: Optional[str] = None
    validation_ref: Optional[str] = None
    expected_trade_rate: Optional[float] = None            # trades per month
    smallest_edge_of_interest: Optional[float] = None      # R per trade, net of costs
    overlays: Mapping[str, str] = field(default_factory=dict)   # overlay id -> version the strategy declares (ids and versions are part of config_hash)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID.match(self.id):
            raise SpecError(f"id must match {_ID.pattern}: {self.id!r}")
        if not isinstance(self.version, str) or not _VERSION.match(self.version):
            raise SpecError(f"version must be MAJOR.MINOR.PATCH: {self.version!r}")
        if not isinstance(self.exit_policy, str) or not self.exit_policy.strip():
            raise SpecError("exit_policy (a reference to an exit policy id) is required")
        if self.status not in STATUSES:
            raise SpecError(f"status must be one of {STATUSES}: {self.status!r}")
        object.__setattr__(self, "params", _jsonable(dict(self.params), "params"))
        object.__setattr__(self, "universe_overrides", _jsonable(dict(self.universe_overrides), "universe_overrides"))
        bad = NON_OVERRIDABLE & set(self.params)
        if bad:
            raise SpecError(f"params may not contain shared-config sections: {sorted(bad)}")
        bad_u = set(self.universe_overrides) - UNIVERSE_OVERRIDABLE
        if bad_u:
            raise SpecError(f"universe_overrides may only contain {sorted(UNIVERSE_OVERRIDABLE)}; got {sorted(bad_u)}")
        ov = dict(self.overlays)
        for oid, ver in ov.items():
            if not isinstance(oid, str) or not _ID.match(oid) or not isinstance(ver, str) or not _VERSION.match(ver):
                raise SpecError(f"overlays must map an overlay id to a MAJOR.MINOR.PATCH version: {oid!r}: {ver!r}")
        object.__setattr__(self, "overlays", _jsonable(ov, "overlays"))
        for name in ("expected_trade_rate", "smallest_edge_of_interest"):
            v = getattr(self, name)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                raise SpecError(f"{name} must be a positive number or None")
        for name in ("prereg_ref", "validation_ref"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, str) or not v.strip()):
                raise SpecError(f"{name} must be a non-empty string or None")
        if self.status == "live" and not self.validation_ref:
            raise SpecError("status 'live' requires a validation_ref (a reference to the validation record)")

    def config_hash(self) -> str:
        """sha256 of the canonical JSON of every field (sorted keys, no whitespace)."""
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "StrategySpec":
        names = {f.name for f in fields(StrategySpec)}
        extra = set(d) - names
        if extra:
            raise SpecError(f"unknown spec keys: {sorted(extra)}")
        return StrategySpec(**dict(d))


def config_hash(spec: StrategySpec) -> str:
    return spec.config_hash()

"""Plain-data engine types (restructure Phase 6 Part B; ENGINE_CONTRACT section 3). Standard library only.

``State`` and ``Decisions`` are frozen dataclasses of numbers, strings, dates, tuples and plain mappings. ``to_json`` / ``from_json`` round-trip them
without loss (tests/unit/test_engine_types.py). Dates are written as ISO strings. Mappings inside (exit_state, strategy_state, metadata ...) must be
JSON-serialisable; the engine never mutates a mapping it received, it builds a new one.
Prices in ``State`` are in the price basis of the day they were set; corporate actions rescale them (engine.corporate).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from typing import Any, Mapping, Optional

SCHEMA_VERSION = 1


def to_plain(o: Any) -> Any:
    if is_dataclass(o) and not isinstance(o, type):
        return {f.name: to_plain(getattr(o, f.name)) for f in fields(o)}
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, (list, tuple)):
        return [to_plain(x) for x in o]
    if isinstance(o, Mapping):
        return {str(k): to_plain(v) for k, v in o.items()}
    return o


def _d(v) -> Optional[date]:
    return None if v is None else date.fromisoformat(v)


def _t(v, cls):
    return tuple(cls.from_plain(x) for x in v)


@dataclass(frozen=True)
class Position:
    position_id: str
    strategy_id: str
    symbol: str
    sector: Optional[str]
    entry_date: date
    entry_price: float
    initial_stop: float
    live_stop: float
    target: Optional[float]
    shares_initial: float              # float: a split divides it; the fractional part is paid in cash at the ex-price
    shares_remaining: int
    risk_inr: float                    # invariant: shares_initial_at_entry * (entry - initial stop); unchanged by corporate actions
    exit_policy_id: str
    exit_state: Mapping[str, Any] = field(default_factory=dict)
    highest_high: float = 0.0
    days_held: int = 0
    last_close: float = 0.0
    gross_pnl: float = 0.0
    costs_paid: float = 0.0
    ca_done: tuple = ()                # corporate-action keys already applied
    hold: bool = False                 # an action the engine cannot rescale: flagged, excluded from statistics
    pending_exit: int = 0              # shares requested to exit at the NEXT open (market), 0 = none
    pending_reason: str = ""

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "Position":
        d = dict(d)
        d["entry_date"] = _d(d["entry_date"])
        d["ca_done"] = tuple(d.get("ca_done", ()))
        return Position(**d)


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    strategy_id: str
    symbol: str
    sector: Optional[str]
    signal_date: date
    reference_price: float
    stop: float
    target: Optional[float]
    shares_planned: int
    risk_planned: float
    value_planned: float
    created_on: date
    rank: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "Ticket":
        d = dict(d)
        d["signal_date"], d["created_on"] = _d(d["signal_date"]), _d(d["created_on"])
        return Ticket(**d)


@dataclass(frozen=True)
class Fill:
    ticket_id: str
    position_id: str
    strategy_id: str
    symbol: str
    date: date
    price: float
    shares: int
    cost: float
    assumed: bool = True               # True when decide() simulated it (backtest / paper); False when the operator reported it (live)

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "Fill":
        d = dict(d)
        d["date"] = _d(d["date"])
        return Fill(**d)


@dataclass(frozen=True)
class ExitRecord:
    position_id: str
    strategy_id: str
    symbol: str
    date: date
    reason: str
    price: float
    shares: int
    cost: float
    closed: bool
    assumed: bool = True

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "ExitRecord":
        d = dict(d)
        d["date"] = _d(d["date"])
        return ExitRecord(**d)


@dataclass(frozen=True)
class ClosedTrade:
    position_id: str
    strategy_id: str
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    initial_stop: float
    shares_initial: float
    risk_inr: float
    gross_pnl: float
    costs: float
    net_pnl: float
    exit_reason: str
    excluded_ca: bool = False

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "ClosedTrade":
        d = dict(d)
        d["entry_date"], d["exit_date"] = _d(d["entry_date"]), _d(d["exit_date"])
        return ClosedTrade(**d)


@dataclass(frozen=True)
class PositionUpdate:
    position_id: str
    live_stop: float
    exit_state: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "PositionUpdate":
        return PositionUpdate(**dict(d))


@dataclass(frozen=True)
class Blocked:
    strategy_id: str
    symbol: str
    reason: str
    stage: str                         # "sizing" | "risk" | "fill" | "propose"

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "Blocked":
        return Blocked(**dict(d))


@dataclass(frozen=True)
class CorporateActionApplied:
    position_id: str
    key: str
    factor: float
    fractional_cash: float

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "CorporateActionApplied":
        return CorporateActionApplied(**dict(d))


@dataclass(frozen=True)
class Flag:
    code: str
    detail: str = ""
    strategy_id: Optional[str] = None
    symbol: Optional[str] = None

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "Flag":
        return Flag(**dict(d))


@dataclass(frozen=True)
class State:
    schema_version: int = SCHEMA_VERSION
    as_of: Optional[date] = None
    cash: float = 0.0
    positions: tuple = ()
    pending: tuple = ()
    strategy_state: Mapping[str, Any] = field(default_factory=dict)
    overlay_state: Mapping[str, Any] = field(default_factory=dict)
    realised_pnl_net: float = 0.0

    @staticmethod
    def initial(cash: float) -> "State":
        return State(cash=float(cash))

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "State":
        d = dict(d)
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported State schema_version {d.get('schema_version')!r} (this build reads {SCHEMA_VERSION})")
        d["as_of"] = _d(d.get("as_of"))
        d["positions"] = _t(d.get("positions", ()), Position)
        d["pending"] = _t(d.get("pending", ()), Ticket)
        return State(**d)

    def to_json(self) -> str:
        return json.dumps(to_plain(self), sort_keys=True)

    @staticmethod
    def from_json(s: str) -> "State":
        return State.from_plain(json.loads(s))


@dataclass(frozen=True)
class Decisions:
    as_of: date
    fills: tuple = ()
    exits: tuple = ()
    closed: tuple = ()
    position_updates: tuple = ()
    new_tickets: tuple = ()
    blocked: tuple = ()
    corporate_actions_applied: tuple = ()
    flags: tuple = ()
    audit: tuple = ()                  # (event, plain mapping) pairs in the order they happened

    @staticmethod
    def from_plain(d: Mapping[str, Any]) -> "Decisions":
        d = dict(d)
        d["as_of"] = _d(d["as_of"])
        for name, cls in (("fills", Fill), ("exits", ExitRecord), ("closed", ClosedTrade), ("position_updates", PositionUpdate), ("new_tickets", Ticket),
                          ("blocked", Blocked), ("corporate_actions_applied", CorporateActionApplied), ("flags", Flag)):
            d[name] = _t(d.get(name, ()), cls)
        d["audit"] = tuple((a, dict(b)) for a, b in d.get("audit", ()))
        return Decisions(**d)

    def to_json(self) -> str:
        return json.dumps(to_plain(self), sort_keys=True)

    @staticmethod
    def from_json(s: str) -> "Decisions":
        return Decisions.from_plain(json.loads(s))

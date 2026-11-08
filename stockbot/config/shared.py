"""Typed shared configuration (restructure Phase 4).

``load_shared_config()`` reads ``stockbot/config/shared.yaml`` into frozen dataclasses and validates ranges.  Nothing here is strategy-specific;
a strategy spec can never override these sections (``NON_OVERRIDABLE``).  Values are carried over unchanged from strategy_config.yaml
(tests/unit/test_shared_config.py compares them key by key).  strategy_config.yaml was removed in Phase 10 (frozen in tests/golden); the legacy nested-dict shape is available from stockbot.config.dict_view.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

SHARED_YAML = Path(__file__).resolve().parent / "shared.yaml"
NON_OVERRIDABLE = frozenset({"runtime", "data", "execution", "costs", "portfolio_risk", "exclusions", "live", "backtest", "validation_gates", "paper_criteria"})


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str
    paper_start_equity: float


@dataclass(frozen=True)
class DataConfig:
    eod_source: str
    adtv_sma_period: int
    nifty_symbol: str
    vix_symbol: str


@dataclass(frozen=True)
class ExecutionConfig:
    entry_fill: str
    entry_slippage_pct: float
    exit_slippage_pct: float
    max_entry_gap_up_pct: float


@dataclass(frozen=True)
class CostsConfig:
    stt_buy_pct: float
    stt_sell_pct: float
    brokerage_per_order_inr: float
    exchange_txn_pct: float
    sebi_fee_pct: float
    stamp_duty_buy_pct: float
    gst_pct: float
    dp_charge_per_sell_inr: float
    stcg_tax_pct: float


@dataclass(frozen=True)
class PortfolioRiskConfig:
    max_loss_pct_per_trade: float
    max_concurrent_positions: int
    max_total_portfolio_risk_pct: float
    max_sector_exposure_pct: float


@dataclass(frozen=True)
class UniverseConfig:
    min_market_cap_cr: float          # parked (KI-001)
    min_adtv_cr: float
    min_listing_age_trading_days: int


@dataclass(frozen=True)
class ExclusionsConfig:
    known_ahead_days: int


@dataclass(frozen=True)
class LiveConfig:
    earnings_alert_days: int


@dataclass(frozen=True)
class BacktestWindow:
    name: str
    role: str
    start: str
    end: str


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: float
    regimes: tuple


@dataclass(frozen=True)
class ValidationGates:
    max_drawdown_pct: float
    min_alpha_after_tax_pct: float
    min_expectancy_r: float
    min_profit_factor: float
    min_trades: int
    ltcg_tax_pct: float
    risk_free_pct: float


@dataclass(frozen=True)
class PaperCriteria:
    min_days: int
    min_closed_trades: int
    max_expectancy_gap_r: float
    max_win_rate_gap_pts: float
    min_profit_factor: float
    max_drawdown_pct: float
    max_skipped_ticket_rate: float


@dataclass(frozen=True)
class SharedConfig:
    runtime: RuntimeConfig
    data: DataConfig
    execution: ExecutionConfig
    costs: CostsConfig
    portfolio_risk: PortfolioRiskConfig
    universe: UniverseConfig
    exclusions: ExclusionsConfig
    live: LiveConfig
    backtest: BacktestConfig
    validation_gates: ValidationGates
    paper_criteria: PaperCriteria

    def flat(self) -> dict[str, Any]:
        """{'section.key': value} for every scalar setting (the backtest windows as 'backtest.regimes' = list of dicts)."""
        out: dict[str, Any] = {}
        for sec in fields(self):
            obj = getattr(self, sec.name)
            for f in fields(obj):
                v = getattr(obj, f.name)
                out[f"{sec.name}.{f.name}"] = [dict(name=w.name, role=w.role, start=w.start, end=w.end) for w in v] if f.name == "regimes" else v
        return out


def _build(cls, d: Mapping[str, Any], where: str):
    names = {f.name for f in fields(cls)}
    extra, missing = set(d) - names, names - set(d)
    if extra or missing:
        raise ValueError(f"shared config section '{where}': unexpected keys {sorted(extra)}, missing keys {sorted(missing)}")
    return cls(**d)


def parse_shared_config(raw: Mapping[str, Any]) -> SharedConfig:
    secs = {f.name for f in fields(SharedConfig)}
    if set(raw) != secs:
        raise ValueError(f"shared config sections must be exactly {sorted(secs)}; got {sorted(raw)}")
    bt = dict(raw["backtest"])
    bt["regimes"] = tuple(_build(BacktestWindow, w, "backtest.regimes") for w in bt["regimes"])
    parts = {}
    for f in fields(SharedConfig):
        d = bt if f.name == "backtest" else raw[f.name]
        parts[f.name] = _build(f.type if not isinstance(f.type, str) else globals()[f.type], d, f.name)
    cfg = SharedConfig(**parts)
    _validate(cfg)
    return cfg


def _validate(c: SharedConfig) -> None:
    if c.runtime.mode not in ("PAPER", "LIVE"):
        raise ValueError("runtime.mode must be PAPER or LIVE")
    if c.runtime.paper_start_equity <= 0 or c.backtest.initial_equity <= 0:
        raise ValueError("starting equity must be positive")
    p = c.portfolio_risk
    if not (0 < p.max_loss_pct_per_trade <= 100 and p.max_concurrent_positions > 0 and 0 < p.max_total_portfolio_risk_pct <= 100 and 0 < p.max_sector_exposure_pct <= 100):
        raise ValueError("portfolio_risk limits out of range")
    if c.execution.entry_fill != "NEXT_OPEN":
        raise ValueError("execution.entry_fill: only NEXT_OPEN is supported")
    for name in ("entry_slippage_pct", "exit_slippage_pct", "max_entry_gap_up_pct"):
        if getattr(c.execution, name) < 0:
            raise ValueError(f"execution.{name} must be >= 0")
    if any(getattr(c.costs, f.name) < 0 for f in fields(c.costs)):
        raise ValueError("costs must be >= 0")
    if c.exclusions.known_ahead_days < 0 or c.live.earnings_alert_days < 0:
        raise ValueError("day counts must be >= 0")
    roles = [w.role for w in c.backtest.regimes]
    if any(r not in ("TUNE", "TEST") for r in roles) or "TEST" not in roles:
        raise ValueError("backtest.regimes: roles must be TUNE/TEST and include a TEST window")


def load_shared_config(path: Optional[str | Path] = None) -> SharedConfig:
    with open(path or SHARED_YAML, "r", encoding="utf-8") as fh:
        return parse_shared_config(yaml.safe_load(fh))

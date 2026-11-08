"""Heat and sector caps (restructure Phase 5.2): three explicit conditions on PROJECTED post-trade values.

Same conditions and reason strings as the legacy ``RiskAndSizingEngine._check_heat_cap`` / ``_is_heat_cap_full`` (tests compare them on a grid):
  A. open positions after the trade        > max_positions          -> BLOCKED_BY_RISK(positions:n>max)
  B. total risk (sum of risk_amount) / equity (%) > max_total_risk_pct -> BLOCKED_BY_RISK(total_risk:x.x%>max%)
  C. sector value after the trade / equity (%)    > max_sector_pct     -> BLOCKED_BY_RISK(sector_S:x.x%>max%)
No strategy knowledge: the numbers come from the proposals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class CapLimits:
    max_positions: int
    max_total_risk_pct: float
    max_sector_pct: float


def _get(p, name, default=0.0):
    return p.get(name, default) if isinstance(p, Mapping) else getattr(p, name, default)


def check_caps(*, limits: CapLimits, equity: float, open_positions: Sequence, sector: Optional[str], position_value: float, risk_amount: float,
               max_positions: Optional[int] = None) -> Optional[str]:
    """Return a block reason if adding one position breaches a cap, else None. ``open_positions`` items need risk_amount, sector, position_value
    (mappings or objects). ``max_positions`` overrides ``limits.max_positions`` (regime-dependent cap, decision Q4 pending)."""
    allowed = max_positions if max_positions is not None else limits.max_positions
    projected_positions = len(open_positions) + 1
    if projected_positions > allowed:
        return f"BLOCKED_BY_RISK(positions:{projected_positions}>{allowed})"
    existing_risk = sum(_get(p, "risk_amount") for p in open_positions)
    projected_risk_pct = (existing_risk + risk_amount) / equity * 100.0
    if projected_risk_pct > limits.max_total_risk_pct:
        return f"BLOCKED_BY_RISK(total_risk:{projected_risk_pct:.1f}%>{limits.max_total_risk_pct}%)"
    if sector and equity > 0:
        sector_capital = sum(_get(p, "position_value") for p in open_positions if _get(p, "sector", None) == sector) + position_value
        sector_pct = sector_capital / equity * 100.0
        if sector_pct > limits.max_sector_pct:
            return f"BLOCKED_BY_RISK(sector_{sector}:{sector_pct:.1f}%>{limits.max_sector_pct}%)"
    return None


def caps_full(*, limits: CapLimits, equity: float, open_positions: Sequence, max_positions: Optional[int] = None) -> bool:
    """True when no further position can be added at all (position count at the cap, or total risk at/over the cap)."""
    allowed = max_positions if max_positions is not None else limits.max_positions
    if len(open_positions) >= allowed:
        return True
    total_risk = sum(_get(p, "risk_amount") for p in open_positions)
    return total_risk / equity * 100.0 >= limits.max_total_risk_pct

"""stockbot.risk.caps: three explicit conditions on projected post-trade values; hand-derived cases and equality with the legacy heat-cap code."""
import random

import pytest

from stockbot.risk.caps import CapLimits, caps_full, check_caps

L = CapLimits(max_positions=3, max_total_risk_pct=5.0, max_sector_pct=15.0)
EQ = 1_000_000.0


def pos(sector, value, risk):
    return {"sector": sector, "position_value": value, "risk_amount": risk}


def test_position_count_gate():
    assert check_caps(limits=L, equity=EQ, open_positions=[pos("A", 1, 1), pos("B", 1, 1)], sector="C", position_value=1, risk_amount=1) is None
    assert check_caps(limits=L, equity=EQ, open_positions=[pos("A", 1, 1)] * 3, sector="C", position_value=1, risk_amount=1) == "BLOCKED_BY_RISK(positions:4>3)"


def test_total_risk_gate_is_on_the_projected_value():
    open_ = [pos("A", 1, 20_000), pos("B", 1, 20_000)]                       # 4.0% at risk
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector="C", position_value=1, risk_amount=10_000) is None               # 5.0% is not > 5.0%
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector="C", position_value=1, risk_amount=10_001) == "BLOCKED_BY_RISK(total_risk:5.0%>5.0%)"
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector="C", position_value=1, risk_amount=15_000) == "BLOCKED_BY_RISK(total_risk:5.5%>5.0%)"


def test_sector_gate_counts_only_that_sector_and_the_new_position():
    open_ = [pos("IT", 100_000, 1), pos("BANK", 140_000, 1)]                 # IT 10%, BANK 14%
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector="IT", position_value=50_000, risk_amount=1) is None               # 15.0% is not > 15.0%
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector="IT", position_value=60_000, risk_amount=1) == "BLOCKED_BY_RISK(sector_IT:16.0%>15.0%)"
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector="AUTO", position_value=149_000, risk_amount=1) is None
    assert check_caps(limits=L, equity=EQ, open_positions=open_, sector=None, position_value=900_000, risk_amount=1) is None           # no sector -> no sector cap


def test_gate_order_count_then_risk_then_sector():
    full = [pos("IT", 140_000, 40_000)] * 3
    assert check_caps(limits=L, equity=EQ, open_positions=full, sector="IT", position_value=1e6, risk_amount=1e6).startswith("BLOCKED_BY_RISK(positions")
    two = [pos("IT", 140_000, 20_000)] * 2
    assert check_caps(limits=L, equity=EQ, open_positions=two, sector="IT", position_value=1e6, risk_amount=20_000).startswith("BLOCKED_BY_RISK(total_risk")


def test_max_positions_override_and_caps_full():
    assert check_caps(limits=L, equity=EQ, open_positions=[pos("A", 1, 1)] * 3, sector="C", position_value=1, risk_amount=1, max_positions=4) is None
    assert caps_full(limits=L, equity=EQ, open_positions=[pos("A", 1, 1)] * 3) is True
    assert caps_full(limits=L, equity=EQ, open_positions=[pos("A", 1, 1)] * 2) is False
    assert caps_full(limits=L, equity=EQ, open_positions=[pos("A", 1, 50_000)]) is True                  # 5.0% at risk >= 5.0%
    assert caps_full(limits=L, equity=EQ, open_positions=[pos("A", 1, 1)] * 3, max_positions=4) is False


def test_equal_to_the_frozen_answers_of_the_legacy_heat_cap_code_on_4000_random_cases():
    """The old ``RiskAndSizingEngine._check_heat_cap`` / ``_is_heat_cap_full`` answered these 4,000 cases (frozen in tests/golden before engine_core was deleted)."""
    from tests.fixtures.golden import legacy
    g = legacy()["caps"]
    lim = CapLimits(*g["limits"])
    assert len(g["cases"]) == 4000
    for c in g["cases"]:
        assert check_caps(limits=lim, equity=c["equity"], open_positions=c["open"], sector=c["sector"], position_value=c["value"], risk_amount=c["risk"],
                          max_positions=c["max_positions"]) == c["reason"]
        assert caps_full(limits=lim, equity=c["equity"], open_positions=c["open"], max_positions=c["max_positions"]) == c["full"]
    assert sum(c["reason"] is not None for c in g["cases"]) > 500 and sum(c["full"] for c in g["cases"]) > 100         # the grid really exercises both outcomes

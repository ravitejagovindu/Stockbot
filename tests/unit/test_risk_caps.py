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


def test_equal_to_the_legacy_heat_cap_code_on_a_random_grid():
    from stockbot.config.legacy_loader import load_config
    from engine_core.risk_sizing import RiskAndSizingEngine
    cfg = load_config()
    eng = RiskAndSizingEngine(cfg)
    lim = CapLimits(int(cfg["risk"]["max_concurrent_positions"]), float(cfg["risk"]["max_total_portfolio_risk_pct"]), float(cfg["risk"]["max_sector_exposure_pct"]))
    rng = random.Random(5)
    sectors = ["IT", "BANK", "AUTO", "PHARMA", None]
    for _ in range(4000):
        equity = rng.choice([1e5, 1e6, 3.3e6])
        open_ = [pos(rng.choice(sectors), rng.uniform(0, 0.3) * equity, rng.uniform(0, 0.03) * equity) for _ in range(rng.randint(0, 13))]
        sec, val, risk = rng.choice(sectors), rng.uniform(0, 0.3) * equity, rng.uniform(0, 0.03) * equity
        mp = rng.choice([None, 5, 12])
        assert check_caps(limits=lim, equity=equity, open_positions=open_, sector=sec, position_value=val, risk_amount=risk, max_positions=mp) == \
            eng._check_heat_cap(sec, val, risk, equity, open_, max_positions=mp)
        assert caps_full(limits=lim, equity=equity, open_positions=open_, max_positions=mp) == eng._is_heat_cap_full(open_, equity, max_positions=mp)

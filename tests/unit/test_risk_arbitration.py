"""stockbot.risk.arbitration: two dummy strategies compete for the same caps; only risk applies caps."""
import random

from stockbot.risk.arbitration import OpenPos, Proposal, arbitrate
from stockbot.risk.caps import CapLimits

EQ = 1_000_000.0
L = CapLimits(max_positions=3, max_total_risk_pct=15.0, max_sector_pct=15.0)


def P(sid, sym, sector, value, risk, rank=0.0):
    return Proposal(sid, sym, sector, value, risk, rank)


def test_two_strategies_compete_for_the_last_two_slots():
    held = [OpenPos("OLD", "X", 50_000, 5_000)]                                    # 1 of 3 slots used
    props = [P("a", "A1", "IT", 80_000, 10_000, rank=1.0), P("a", "A2", "BANK", 80_000, 10_000),
             P("b", "B1", "AUTO", 80_000, 10_000, rank=2.0), P("b", "B2", "PHARMA", 80_000, 10_000)]
    got = [(d.strategy_id, d.symbol, d.accepted, d.reason) for d in arbitrate(props, limits=L, equity=EQ, open_positions=held)]
    # order: rank 2 (B1), rank 1 (A1), then rank 0 by strategy id (A2) then B2; two slots -> B1, A1 accepted; the caps are then full
    assert got == [("b", "B1", True, None), ("a", "A1", True, None), ("a", "A2", False, "BLOCKED_BY_RISK"), ("b", "B2", False, "BLOCKED_BY_RISK")]


def test_order_of_arrival_does_not_matter():
    props = [P("a", "A1", "IT", 80_000, 10_000), P("b", "B1", "IT", 80_000, 10_000), P("a", "A2", "BANK", 60_000, 9_000), P("b", "B2", "AUTO", 50_000, 8_000, rank=3.0)]
    ref = arbitrate(props, limits=L, equity=EQ)
    rng = random.Random(3)
    for _ in range(20):
        shuffled = props[:]
        rng.shuffle(shuffled)
        assert arbitrate(shuffled, limits=L, equity=EQ) == ref


def test_sector_cap_is_shared_across_strategies():
    big = CapLimits(max_positions=10, max_total_risk_pct=15.0, max_sector_pct=15.0)            # 15% of 1,000,000 = 150,000 per sector
    props = [P("a", "A1", "IT", 100_000, 5_000), P("b", "B1", "IT", 60_000, 5_000), P("b", "B2", "BANK", 60_000, 5_000)]
    got = {d.symbol: (d.accepted, d.reason) for d in arbitrate(props, limits=big, equity=EQ)}
    assert got["A1"] == (True, None)
    assert got["B1"] == (False, "BLOCKED_BY_RISK(sector_IT:16.0%>15.0%)")                       # 100k + 60k = 16%
    assert got["B2"] == (True, None)


def test_total_risk_cap_is_shared_across_strategies():
    big = CapLimits(max_positions=10, max_total_risk_pct=15.0, max_sector_pct=100.0)
    props = [P("a", "A1", "S1", 1, 100_000), P("b", "B1", "S2", 1, 40_000), P("a", "A2", "S3", 1, 10_001)]
    # rank-equal -> by strategy id then symbol: A1 (10%), A2 (10% + 1.0001% = 11.0001%), B1 (+4% = 15.0001% > 15%) blocked
    got = {d.symbol: d.accepted for d in arbitrate(props, limits=big, equity=EQ)}
    assert got == {"A1": True, "A2": True, "B1": False}


def test_a_strategy_is_unaffected_by_another_when_no_cap_binds():
    big = CapLimits(max_positions=50, max_total_risk_pct=100.0, max_sector_pct=100.0)
    a = [P("a", f"A{i}", "IT", 10_000, 1_000) for i in range(3)]
    b = [P("b", f"B{i}", "BANK", 10_000, 1_000) for i in range(3)]
    alone = [d for d in arbitrate(a, limits=big, equity=EQ)]
    together = [d for d in arbitrate(a + b, limits=big, equity=EQ) if d.strategy_id == "a"]
    assert alone == together


def test_the_caller_state_is_not_mutated_and_empty_input_is_fine():
    held = [OpenPos("X", "IT", 10, 1)]
    assert arbitrate([], limits=L, equity=EQ, open_positions=held) == []
    arbitrate([P("a", "A", "IT", 1, 1)], limits=L, equity=EQ, open_positions=held)
    assert len(held) == 1

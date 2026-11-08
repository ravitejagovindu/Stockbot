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
    # decision D6: rank counts only inside a strategy. a: A1 (rank 1), A2; b: B1 (rank 2), B2. Round-robin in strategy-id order: A1, B1, A2, B2.
    # two free slots -> A1 and B1 are accepted (B1's higher rank does not let it jump ahead of A1); the caps are then full
    assert got == [("a", "A1", True, None), ("b", "B1", True, None), ("a", "A2", False, "BLOCKED_BY_RISK"), ("b", "B2", False, "BLOCKED_BY_RISK")]


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
    # round-robin (D6): A1 (10%), B1 (+4% = 14%), A2 (+1.0001% = 15.0001% > 15%) blocked
    got = {d.symbol: d.accepted for d in arbitrate(props, limits=big, equity=EQ)}
    assert got == {"A1": True, "B1": True, "A2": False}


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


def test_rank_is_only_compared_inside_one_strategy():
    wide = CapLimits(max_positions=1, max_total_risk_pct=100.0, max_sector_pct=100.0)
    props = [P("a", "A1", "IT", 1, 1, rank=1.0), P("b", "B1", "IT", 1, 1, rank=999.0)]
    got = {d.symbol: d.accepted for d in arbitrate(props, limits=wide, equity=EQ)}
    assert got == {"A1": True, "B1": False}                                   # one slot: strategy 'a' goes first whatever 'b' ranks
    inside = [P("a", "A2", "IT", 1, 1, rank=1.0), P("a", "A1", "IT", 1, 1, rank=5.0)]
    assert [d.symbol for d in arbitrate(inside, limits=wide, equity=EQ) if d.accepted] == ["A1"]      # higher rank first inside a strategy
    ties = [P("a", "Z", "IT", 1, 1), P("a", "M", "IT", 1, 1)]
    assert [d.symbol for d in arbitrate(ties, limits=wide, equity=EQ) if d.accepted] == ["M"]          # equal rank: symbol order


def test_interleaving_is_round_robin_in_strategy_id_order():
    from stockbot.risk.arbitration import admission_order
    props = [P("c", "C1", "S", 1, 1), P("a", "A1", "S", 1, 1), P("a", "A2", "S", 1, 1), P("b", "B1", "S", 1, 1), P("a", "A3", "S", 1, 1)]
    assert [p.symbol for p in admission_order(props)] == ["A1", "B1", "C1", "A2", "A3"]


def test_symbol_already_held_cannot_be_opened_by_another_strategy():
    big = CapLimits(max_positions=10, max_total_risk_pct=100.0, max_sector_pct=100.0)
    held = [OpenPos("XYZ", "IT", 10, 1, "a")]
    got = {(d.strategy_id, d.symbol): (d.accepted, d.reason) for d in arbitrate([P("b", "XYZ", "IT", 1, 1), P("a", "XYZ", "IT", 1, 1)], limits=big, equity=EQ, open_positions=held)}
    assert got[("b", "XYZ")] == (False, "SYMBOL_HELD_BY_OTHER_STRATEGY")
    assert got[("a", "XYZ")] == (False, "ALREADY_HELD")


def test_first_in_admission_order_wins_a_symbol_proposed_by_two_strategies():
    big = CapLimits(max_positions=10, max_total_risk_pct=100.0, max_sector_pct=100.0)
    got = {d.strategy_id: (d.accepted, d.reason) for d in arbitrate([P("b", "XYZ", "IT", 1, 1, rank=50.0), P("a", "XYZ", "IT", 1, 1)], limits=big, equity=EQ)}
    assert got == {"a": (True, None), "b": (False, "SYMBOL_HELD_BY_OTHER_STRATEGY")}


def test_sector_and_total_risk_caps_see_positions_of_every_strategy():
    cap = CapLimits(max_positions=10, max_total_risk_pct=100.0, max_sector_pct=15.0)
    held = [OpenPos("H", "IT", 140_000, 1, "a")]                              # strategy a already holds 14% in IT
    got = arbitrate([P("b", "B1", "IT", 20_000, 1)], limits=cap, equity=EQ, open_positions=held)
    assert got[0].reason == "BLOCKED_BY_RISK(sector_IT:16.0%>15.0%)"

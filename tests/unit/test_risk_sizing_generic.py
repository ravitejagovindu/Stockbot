"""stockbot.risk.sizing: hand-derived cases, and agreement with the fill-time sizing that decided the executed trades (plan_entry_fill)."""
import math
import random

import pytest

from engine_core.lifecycle_rules import plan_entry_fill
from stockbot.risk.sizing import size_position


def test_hand_derived_whole_numbers():
    # equity 1,000,000 x 1% = 10,000 at risk; entry 100, stop 90 -> risk 10 per share -> 1,000 shares
    r = size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=90.0)
    assert (r.shares, r.risk_per_share, r.risk_amount, r.position_value, r.reason) == (1000, 10.0, 10_000.0, 100_000.0, "OK") and r.ok


def test_floors_the_share_count():
    # 10,000 / 18.061651 = 553.67 -> 553 (the G3 trade: fill 177.177, stop 159.115349)
    r = size_position(equity=1_000_000, risk_pct=1.0, entry=177.177, stop=159.115349)
    assert r.shares == 553 and r.risk_amount == pytest.approx(553 * 18.061651)


def test_cash_cap():
    assert size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=90.0, cash=50_000).shares == 500      # 50,000 / 100
    assert size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=90.0, cash=1e9).shares == 1000
    assert size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=90.0, cash=50).reason == "SIZE_ZERO"


def test_blocked_cases():
    assert size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=100.0).reason == "NONPOSITIVE_RISK"
    assert size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=101.0).reason == "NONPOSITIVE_RISK"
    r = size_position(equity=100.0, risk_pct=1.0, entry=100.0, stop=90.0)       # 1 rupee at risk, 10 per share
    assert r.reason == "SIZE_ZERO" and r.shares == 0 and not r.ok


@pytest.mark.parametrize("kw", [dict(equity=0), dict(equity=-1), dict(risk_pct=0), dict(entry=0), dict(entry=float("nan")), dict(equity=float("inf")), dict(stop=float("nan"))])
def test_invalid_inputs_raise(kw):
    base = dict(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=90.0)
    base.update(kw)
    with pytest.raises(ValueError):
        size_position(**base)


def test_agrees_with_plan_entry_fill_on_a_random_grid():
    rng = random.Random(11)
    n = 0
    for _ in range(3000):
        equity = rng.choice([1e5, 1e6, 2.5e6, 987_000.0, 1_234_567.0])
        risk_pct = rng.choice([0.25, 0.5, 1.0, 1.5, 2.0])
        nxt = rng.uniform(20, 3000)
        stop = nxt * rng.uniform(0.6, 0.97)
        plan = plan_entry_fill(ticket_entry=nxt, stop=stop, target=nxt * 3, next_open=nxt, equity=equity, risk_pct=risk_pct, slippage_pct=0.10,
                               max_gap_up_pct=3.0, min_rr=0.0)
        if not plan.ok:
            continue
        mine = size_position(equity=equity, risk_pct=risk_pct, entry=plan.fill_price, stop=stop)
        assert mine.shares == plan.shares, (equity, risk_pct, nxt, stop)
        n += 1
    assert n > 2500


def test_difference_from_the_legacy_ticket_form_is_only_at_exact_boundaries():
    # legacy ticket-time form: floor(equity * (risk_pct / 100) / rps); ours: floor(equity * risk_pct / 100 / rps)
    diffs = checked = 0
    for equity in (1e5, 1e6, 987_000.0):
        for pct in (0.25, 0.5, 1.0, 1.5, 0.75):
            cap = equity * pct / 100.0
            for k in range(1, 1500):
                rps = cap / k                                    # quotient is an exact integer k by construction
                a = math.floor(equity * (pct / 100.0) / rps)
                b = math.floor(equity * pct / 100.0 / rps)
                checked += 1
                if a != b:
                    diffs += 1
                    assert abs(a - b) == 1 and abs(equity * pct / 100.0 / rps - round(equity * pct / 100.0 / rps)) < 1e-9
    assert 0 <= diffs < checked * 0.01                              # rare, and always an off-by-one at an integer boundary

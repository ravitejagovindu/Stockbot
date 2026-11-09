"""stockbot.risk.costs: hand-derived values at the current shared rates; shared-config and legacy-dict construction agree."""
import pytest

from stockbot.config.shared import load_shared_config
from stockbot.risk.costs import CostModel


def test_buy_and_sell_cost_on_100000():
    m = CostModel.from_shared(load_shared_config().costs)
    # fees = 100000 x (0.00297% + 0.0001%) = 3.07 ; GST 18% on (brokerage 0 + fees) = 3.07 x 1.18 = 3.6226
    # buy  = STT 0.10% (100) + stamp 0.015% (15) + 3.6226            = 118.6226
    # sell = STT 0.10% (100) + DP charge 15.34       + 3.6226          = 118.9626
    assert m.buy_cost(100_000) == pytest.approx(118.6226, abs=1e-9)
    assert m.sell_cost(100_000) == pytest.approx(118.9626, abs=1e-9)


def test_costs_scale_linearly_except_the_dp_charge():
    m = CostModel.from_shared(load_shared_config().costs)
    assert m.buy_cost(200_000) == pytest.approx(2 * m.buy_cost(100_000))
    assert m.sell_cost(200_000) - m.sell_cost(100_000) == pytest.approx(m.sell_cost(100_000) - 15.34)


def test_tax_on_gain():
    m = CostModel.from_shared(load_shared_config().costs)
    assert m.tax_on_gain(1000) == 0.0 and m.tax_on_gain(-500) == 0.0                 # stcg_tax_pct stays 0.0
    taxed = CostModel(0, 0, 0, 0, 0, 0, 0, 0, 15.0)
    assert taxed.tax_on_gain(1000) == 150.0 and taxed.tax_on_gain(-1000) == 0.0 and taxed.tax_on_gain(0) == 0.0


def test_shared_construction_equals_the_frozen_legacy_cost_model():
    from tests.fixtures.golden import legacy
    m = CostModel.from_shared(load_shared_config().costs)
    assert {k: getattr(m, k) for k in legacy()["legacy_cost_model"]} == legacy()["legacy_cost_model"]

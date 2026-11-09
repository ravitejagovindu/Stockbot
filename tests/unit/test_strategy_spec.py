"""Strategy spec schema, config hash and the (empty) registry (restructure Phase 4)."""
import pytest

from stockbot.config.shared import NON_OVERRIDABLE as SHARED_NON_OVERRIDABLE
from stockbot.config.shared import load_shared_config
from stockbot.strategies.spec import NON_OVERRIDABLE, UNIVERSE_OVERRIDABLE, SpecError, StrategySpec, config_hash


def spec(**kw):
    base = dict(id="dummy_a", version="0.1.0", params={"lookback": 20}, exit_policy="dummy_exit")
    base.update(kw)
    return StrategySpec(**base)


def test_valid_spec_defaults():
    s = spec()
    assert s.status == "research" and dict(s.universe_overrides) == {} and s.prereg_ref is None and s.expected_trade_rate is None


@pytest.mark.parametrize("kw", [
    dict(id="Bad-Id"), dict(id="x"), dict(version="1.0"), dict(exit_policy=" "), dict(status="prod"),
    dict(expected_trade_rate=0), dict(expected_trade_rate=True), dict(smallest_edge_of_interest=-0.1), dict(prereg_ref=""),
    dict(params={"f": object()}),
])
def test_invalid_specs_are_rejected(kw):
    with pytest.raises(SpecError):
        spec(**kw)


def test_live_requires_a_validation_record_reference():
    with pytest.raises(SpecError, match="validation_ref"):
        spec(status="live")
    with pytest.raises(SpecError, match="validation_ref"):
        spec(status="live", validation_ref="  ")
    assert spec(status="live", validation_ref="validation/ledger/2027-01-01").status == "live"
    assert spec(status="paper").status == "paper"            # paper does not need one


def test_a_spec_cannot_override_shared_config():
    for sec in ("costs", "execution", "validation_gates", "paper_criteria", "portfolio_risk"):
        with pytest.raises(SpecError, match="shared-config"):
            spec(params={sec: {"x": 1}})
    with pytest.raises(SpecError, match="universe_overrides"):
        spec(universe_overrides={"min_market_cap_cr": 1})          # parked gate
    assert dict(spec(universe_overrides={"min_adtv_cr": 30}).universe_overrides) == {"min_adtv_cr": 30}


def test_override_lists_match_the_shared_config():
    assert NON_OVERRIDABLE == SHARED_NON_OVERRIDABLE
    cfg = load_shared_config()
    assert UNIVERSE_OVERRIDABLE < set(cfg.universe.__dataclass_fields__)
    assert "min_market_cap_cr" not in UNIVERSE_OVERRIDABLE


def test_config_hash_is_deterministic_and_sensitive():
    a, b = spec(params={"a": 1, "b": 2}), spec(params={"b": 2, "a": 1})
    assert a.config_hash() == b.config_hash() == config_hash(a) and len(a.config_hash()) == 64
    assert spec(version="0.1.1").config_hash() != a.config_hash()
    assert spec(params={"a": 1, "b": 3}).config_hash() != a.config_hash()
    assert spec(status="paper").config_hash() != spec().config_hash()


def test_from_dict_rejects_unknown_keys():
    assert StrategySpec.from_dict({"id": "dummy_b", "version": "1.0.0", "exit_policy": "e"}).id == "dummy_b"
    with pytest.raises(SpecError, match="unknown spec keys"):
        StrategySpec.from_dict({"id": "dummy_b", "version": "1.0.0", "exit_policy": "e", "stop": 1})

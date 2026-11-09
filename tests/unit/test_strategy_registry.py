"""Strategy registry (restructure Phase 4): validated, unique ids; the default registry is empty."""
import pytest

from stockbot.strategies import registry as reg
from stockbot.strategies.spec import SpecError, StrategySpec


def spec(**kw):
    base = dict(id="dummy_a", version="0.1.0", params={"lookback": 20}, exit_policy="dummy_exit")
    base.update(kw)
    return StrategySpec(**base)


def test_registry_validates_and_is_unique():
    r = reg.StrategyRegistry()
    assert len(r) == 0
    r.register(spec(id="dummy_a"))
    r.register(spec(id="dummy_b"))
    assert r.ids() == ["dummy_a", "dummy_b"] and r.get("dummy_a").id == "dummy_a"
    with pytest.raises(SpecError, match="already registered"):
        r.register(spec(id="dummy_a"))
    with pytest.raises(SpecError, match="unknown"):
        r.get("nope")
    with pytest.raises(SpecError):
        r.register({"id": "dummy_c"})


def test_the_default_registry_is_empty():
    assert len(reg.default_registry) == 0 and reg.default_registry.all() == []

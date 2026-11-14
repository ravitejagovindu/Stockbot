"""stockbot.config.shared: typed shared config; every value equals the legacy strategy_config.yaml value (reviewer acceptance item: values carried over unchanged)."""
import copy
import csv
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from stockbot.config.shared import SHARED_YAML, load_shared_config, parse_shared_config

ROOT = Path(__file__).resolve().parents[2]
from tests.fixtures.golden import legacy as _legacy
LEGACY = _legacy()["strategy_config"]            # the old strategy_config.yaml, frozen before it is deleted (sha256 in tests/golden/legacy_equivalence.json.gz)
RAW = yaml.safe_load(open(SHARED_YAML, encoding="utf-8"))
RENAMED = {"portfolio_risk": "risk", "exclusions": "earnings", "live": "trade_management", "validation_gates": "gates"}
# Reviewed shared changes made AFTER the restructure carried every value over unchanged: shared key -> (legacy value, current value). A change is allowed here only on purpose,
# in its own commit, with the owner's decision recorded; the legacy value stays frozen in tests/golden.
REVIEWED_CHANGES = {"validation_gates.max_drawdown_pct": (15.0, 20.0),       # 2026-11-11, owner: applies to every strategy; paper_criteria.max_drawdown_pct stays 12.0
                    "validation_gates.min_alpha_pct": (-2.0, 0.0)}            # shared-rules B2/B3: renamed from min_alpha_after_tax_pct, now PRE-TAX cash-credited alpha, floor 0.0
RENAMED_KEYS = {"validation_gates.min_alpha_pct": "min_alpha_after_tax_pct"}   # shared key -> its legacy leaf name
NEW_KEYS = {"reporting.after_tax_rates_pct"}                                    # shared-rules B2: reporting-only, outside validation_gates; no legacy counterpart


def _legacy_path(section: str, key: str):
    return RENAMED.get(section, section), RENAMED_KEYS.get(f"{section}.{key}", key)


def test_every_shared_value_equals_the_legacy_value_and_type():
    cfg = load_shared_config()
    flat = cfg.flat()
    assert flat
    for k, v in flat.items():
        if k in NEW_KEYS:
            continue
        sec, key = k.split(".", 1)
        lsec, lkey = _legacy_path(sec, key)
        old = LEGACY[lsec][lkey]
        if k in REVIEWED_CHANGES:
            was, now = REVIEWED_CHANGES[k]
            assert old == was and v == now and type(v) is type(old), (k, v, old)
        elif key == "regimes":
            assert v == [dict(name=w["name"], role=w["role"], start=w["start"], end=w["end"]) for w in old], k
        else:
            assert v == old and type(v) is type(old), (k, v, old)


def test_shared_keys_match_the_classification_file():
    rows = list(csv.DictReader(open(ROOT / "docs/restructure/CONFIG_KEYS.csv", encoding="utf-8", newline="")))
    shared_legacy = {r["key"] for r in rows if r["class"].startswith("shared")}
    carried = set()
    for k in load_shared_config().flat():
        if k in NEW_KEYS:
            continue
        sec, key = k.split(".", 1)
        lsec, lkey = _legacy_path(sec, key)
        carried.add(f"{lsec}.{lkey}")
    assert carried == shared_legacy, (sorted(carried ^ shared_legacy))
    not_shared = {r["key"] for r in rows if not r["class"].startswith("shared")}
    assert not (carried & not_shared)


def test_loaded_object_is_typed_and_frozen():
    cfg = load_shared_config()
    assert cfg.runtime.mode == "PAPER" and cfg.costs.stcg_tax_pct == 0.0 and cfg.universe.min_market_cap_cr == 5000
    assert [w.role for w in cfg.backtest.regimes] == ["TUNE", "TUNE", "TEST"]
    with pytest.raises(FrozenInstanceError):
        cfg.costs.gst_pct = 0.0


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r["runtime"].update(mode="DEMO"), "PAPER or LIVE"),
    (lambda r: r["portfolio_risk"].update(max_sector_exposure_pct=150), "out of range"),
    (lambda r: r["execution"].update(entry_slippage_pct=-1), "must be >= 0"),
    (lambda r: r["costs"].update(extra_fee=1), "unexpected keys"),
    (lambda r: r["costs"].pop("gst_pct"), "missing keys"),
    (lambda r: r.pop("paper_criteria"), "sections must be exactly"),
    (lambda r: r.update(macro={"vix_kill_threshold": 22}), "sections must be exactly"),
    (lambda r: r["backtest"]["regimes"].pop(), "TEST window"),
])
def test_invalid_configs_are_rejected(mutate, match):
    raw = copy.deepcopy(RAW)
    mutate(raw)
    with pytest.raises(ValueError, match=match):
        parse_shared_config(raw)


def test_no_old_strategy_key_is_in_the_shared_file():
    rows = list(csv.DictReader(open(ROOT / "docs/restructure/CONFIG_KEYS.csv", encoding="utf-8", newline="")))
    old_leaves = {r["key"].split(".", 1)[1] for r in rows if r["class"] == "old-strategy"}
    shared_leaves = {k.split(".", 1)[1] for k in load_shared_config().flat() if k not in NEW_KEYS}
    assert not (old_leaves & shared_leaves), old_leaves & shared_leaves


# ------------------------------------------------------------------ strategy_config.yaml was removed in Phase 10: every key has a documented new home
def test_every_key_of_the_removed_yaml_has_a_documented_new_home():
    import csv
    rows = list(csv.DictReader(open(ROOT / "docs" / "restructure" / "CONFIG_KEYS.csv", encoding="utf-8", newline="")))
    homes = {r["key"]: r for r in rows}
    flat = {f"{sec}.{k}" for sec, v in LEGACY.items() for k in (v if isinstance(v, dict) else [])} | {sec for sec, v in LEGACY.items() if not isinstance(v, dict)}
    assert flat == set(homes), sorted(flat ^ set(homes))
    assert {r["class"] for r in rows} <= {"shared", "shared (parked)", "old-strategy", "dropped"}, {r["class"] for r in rows}            # nothing left undecided
    ref = (ROOT / "docs" / "restructure" / "OLD_STRATEGY_REFERENCE.md").read_text(encoding="utf-8")
    missing = [k for k, r in homes.items() if r["class"] in ("old-strategy", "dropped") and f"`{k}`" not in ref]
    assert not missing, f"keys whose old values are not recorded in OLD_STRATEGY_REFERENCE.md: {missing}"
    shared_keys = {k for k, r in homes.items() if r["class"].startswith("shared")}
    assert len(shared_keys) == 44 and not (ROOT / "strategy_config.yaml").exists()


def test_the_config_dict_has_the_legacy_shape_and_the_shared_values():
    from stockbot.config.dict_view import config_dict
    d = config_dict()
    assert {"runtime", "data", "execution", "costs", "risk", "universe", "earnings", "trade_management", "gates", "backtest", "paper_criteria"} <= set(d)
    assert d["risk"]["max_concurrent_positions"] == LEGACY["risk"]["max_concurrent_positions"] and d["costs"] == {k: LEGACY["costs"][k] for k in d["costs"]}
    assert d["backtest"]["regimes"] == LEGACY["backtest"]["regimes"] and d["gates"]["min_trades"] == LEGACY["gates"]["min_trades"]
    d["risk"]["max_concurrent_positions"] = 1                                          # a fresh dict on every call
    assert config_dict()["risk"]["max_concurrent_positions"] == LEGACY["risk"]["max_concurrent_positions"]


def test_the_regime_endpoint_constants_equal_the_frozen_macro_section():
    from stockbot.live.api.regime import LEGACY_MACRO
    assert all(LEGACY["macro"][k] == v for k, v in LEGACY_MACRO.items())


def test_the_reviewed_changes_are_the_drawdown_gate_and_the_alpha_gate_and_the_paper_gate_is_untouched():
    cfg = load_shared_config()
    assert set(REVIEWED_CHANGES) == {"validation_gates.max_drawdown_pct", "validation_gates.min_alpha_pct"}
    assert cfg.validation_gates.max_drawdown_pct == 20.0 and LEGACY["gates"]["max_drawdown_pct"] == 15.0
    assert cfg.paper_criteria.max_drawdown_pct == 12.0 == LEGACY["paper_criteria"]["max_drawdown_pct"]       # a strategy passing 20% in backtest can still fail 12% in paper
    assert cfg.validation_gates.max_drawdown_pct > cfg.paper_criteria.max_drawdown_pct
    import dataclasses
    from stockbot.validation.prereg_lock import gates_hash
    assert gates_hash(dataclasses.asdict(cfg.validation_gates)) != "d70800991ed5e6550fe8a89c050e6b3f989ac99f2a2d6cfaa133761771ab9e64"        # the old hash (15.0) is no longer the shared one


def test_alpha_gate_rename_values_and_unchanged_gates():
    import dataclasses
    cfg = load_shared_config()
    g = dataclasses.asdict(cfg.validation_gates)
    assert "min_alpha_after_tax_pct" not in g and g["min_alpha_pct"] == 0.0
    assert (g["min_expectancy_r"], g["min_profit_factor"], g["min_trades"], g["max_drawdown_pct"]) == (0.15, 1.3, 40, 20.0)
    assert g["ltcg_tax_pct"] == 0.0 and cfg.costs.stcg_tax_pct == 0.0 and g["risk_free_pct"] == 6.5
    assert set(g) == {"max_drawdown_pct", "min_alpha_pct", "min_expectancy_r", "min_profit_factor", "min_trades", "ltcg_tax_pct", "risk_free_pct"}


def test_reporting_section_is_outside_the_gate_hash_and_not_overridable():
    import dataclasses
    from stockbot.config.shared import NON_OVERRIDABLE
    from stockbot.validation.prereg_lock import gates_hash
    cfg = load_shared_config()
    assert cfg.reporting.after_tax_rates_pct == (0.0, 20.0) and "reporting" in NON_OVERRIDABLE
    assert "after_tax_rates_pct" not in dataclasses.asdict(cfg.validation_gates)
    changed = dataclasses.replace(cfg, reporting=dataclasses.replace(cfg.reporting, after_tax_rates_pct=(0.0, 30.0)))
    assert gates_hash(dataclasses.asdict(changed.validation_gates)) == gates_hash(dataclasses.asdict(cfg.validation_gates))       # reporting never enters the gate hash


def test_old_gate_hash_is_reproducible_from_the_old_key_names():
    """The registered near_52w_high result used the old key and value; its hash must still be derivable (history is untouched)."""
    import dataclasses
    from stockbot.validation.prereg_lock import gates_hash
    g = dataclasses.asdict(load_shared_config().validation_gates)
    old = {("min_alpha_after_tax_pct" if k == "min_alpha_pct" else k): (-2.0 if k == "min_alpha_pct" else v) for k, v in g.items()}
    assert gates_hash(old) == "805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f"
    assert gates_hash(g) != "805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f"


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r["reporting"].update(after_tax_rates_pct=[0.0, -5.0]), "after_tax_rates_pct"),
    (lambda r: r["reporting"].update(after_tax_rates_pct=[0.0, 120.0]), "after_tax_rates_pct"),
    (lambda r: r["reporting"].update(after_tax_rates_pct="20"), "after_tax_rates_pct"),
    (lambda r: r["validation_gates"].update(min_alpha_after_tax_pct=-2.0), "unexpected keys"),
    (lambda r: r.pop("reporting"), "sections must be exactly"),
])
def test_reporting_and_renamed_key_are_validated(mutate, match):
    raw = copy.deepcopy(RAW)
    mutate(raw)
    with pytest.raises(ValueError, match=match):
        parse_shared_config(raw)

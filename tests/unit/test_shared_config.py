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


def _legacy_path(section: str, key: str):
    return RENAMED.get(section, section), key


def test_every_shared_value_equals_the_legacy_value_and_type():
    cfg = load_shared_config()
    flat = cfg.flat()
    assert flat
    for k, v in flat.items():
        sec, key = k.split(".", 1)
        lsec, lkey = _legacy_path(sec, key)
        old = LEGACY[lsec][lkey]
        if key == "regimes":
            assert v == [dict(name=w["name"], role=w["role"], start=w["start"], end=w["end"]) for w in old], k
        else:
            assert v == old and type(v) is type(old), (k, v, old)


def test_shared_keys_match_the_classification_file():
    rows = list(csv.DictReader(open(ROOT / "docs/restructure/CONFIG_KEYS.csv", encoding="utf-8", newline="")))
    shared_legacy = {r["key"] for r in rows if r["class"].startswith("shared")}
    carried = set()
    for k in load_shared_config().flat():
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
    shared_leaves = {k.split(".", 1)[1] for k in load_shared_config().flat()}
    assert not (old_leaves & shared_leaves), old_leaves & shared_leaves

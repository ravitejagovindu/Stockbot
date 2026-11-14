"""scripts/validate_family.py on SYNTHETIC data only (never finsight.db): T1 jointly across K series with one Max-T, T2, the T3 placebo size check of the joint procedure, the gates per member.

The two properties that matter: under the null the family-wise rejection rate is near 5% and at most 7.5%; with an edge planted in ONE member only, that member (and no other) is found."""
import dataclasses
import importlib
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.config.shared import load_shared_config
from tests.fixtures import near_high_run_dir as R

ROOT = Path(__file__).resolve().parents[2]
CFG = load_shared_config()
LABELS = ["low_volatility", "pullback_uptrend", "short_term_reversal", "trend_breakout_100d"]


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


F = script("validate_family")
V = script("validate_near_52w_high")


def sim(rng, W=130, K=4, rho=0.5, ar=0.08, edge=None, planted=0):
    """K monthly-sum series: a common factor (cross-member correlation rho), heavy tails (t with 6 df) and a little autocorrelation (the real series show lag-1 about 0.08)."""
    common = rng.standard_t(6, W)
    x = np.sqrt(rho) * common[:, None] + np.sqrt(1 - rho) * rng.standard_t(6, (W, K))
    for t in range(1, W):
        x[t] = ar * x[t - 1] + x[t]
    if edge:
        x[:, planted] += edge
    return pd.DataFrame(x, columns=[f"s{i}" for i in range(K)])


# ------------------------------------------------------------------------------------------------------------------------------ T1, joint
def test_the_joint_t1_has_one_adjusted_p_per_member_and_block_and_the_registered_constants():
    assert (F.SEED, F.BLOCKS, F.ALPHA, F.B_MAIN) == (20261111, (2, 3), 0.05, 10000)
    s = sim(np.random.default_rng(1))
    r = F.family_t1(s, B=500)
    assert r["K"] == 4 and set(r["blocks"]) == {2, 3} and all(set(v) == set(s.columns) for v in r["blocks"].values()) and r["seed"] == 20261111
    assert all(0.0 <= m["adjusted_p_value"] <= 1.0 and m["adjusted_p_value"] >= m["unadjusted_p_value"] - 1e-12 for v in r["blocks"].values() for m in v.values())


def test_a_family_of_one_equals_the_single_strategy_t1():
    s = sim(np.random.default_rng(2), K=1)
    one = V.t1(s["s0"], B=800, seed=11)
    fam = F.family_t1(s, B=800, seed=11)
    for b in (2, 3):
        assert fam["blocks"][b]["s0"] == one["blocks"][b]
    assert fam["members"]["s0"]["dual_significant"] == one["dual_significant"]


def test_the_correction_is_joint_so_the_same_series_is_less_significant_beside_three_more():
    rng = np.random.default_rng(3)
    s = sim(rng, edge=0.22)                                                   # a modest edge in s0
    alone = F.family_t1(s[["s0"]], B=2000, seed=5)["blocks"][2]["s0"]["adjusted_p_value"]
    joint = F.family_t1(s, B=2000, seed=5)["blocks"][2]["s0"]["adjusted_p_value"]
    assert joint >= alone - 1e-12


def test_the_dual_rule_needs_both_block_lengths():
    s = sim(np.random.default_rng(4), edge=0.5)
    r = F.family_t1(s, B=500)
    assert r["members"]["s0"]["dual_significant"] == (r["blocks"][2]["s0"]["fwer_significant"] and r["blocks"][3]["s0"]["fwer_significant"])
    assert F.family_t1(s, B=500, blocks=(2,))["members"]["s0"]["dual_significant"] == r["blocks"][2]["s0"]["fwer_significant"]


def test_t1_is_deterministic_for_a_seed():
    s = sim(np.random.default_rng(5))
    assert F.family_t1(s, B=300, seed=1) == F.family_t1(s, B=300, seed=1) and F.family_t1(s, B=300, seed=1) != F.family_t1(s, B=300, seed=2)


def test_under_the_null_the_family_wise_rejection_rate_is_near_five_percent_and_at_most_seven_and_a_half():
    """K = 4 correlated, heavy-tailed null series, 130 months, dual rule at blocks 2 and 3, B = 1,000 here (10,000 in the real run), 600 independent replications."""
    rng = np.random.default_rng(20261111)
    reps = 600
    rej = sum(F.family_t1(sim(rng), B=1000, seed=int(rng.integers(2 ** 31 - 1)))["family_rejects"] for _ in range(reps))
    rate = rej / reps
    assert 0.02 <= rate <= 0.075, rate


def test_with_an_edge_planted_in_one_member_only_that_member_is_found():
    rng = np.random.default_rng(99)
    s = sim(rng, edge=0.6, planted=2)
    r = F.family_t1(s, B=2000, seed=F.SEED)
    assert r["found"] == ["s2"] and r["family_rejects"] is True
    others = [m for m in s.columns if m != "s2"]
    assert all(not r["members"][m]["dual_significant"] for m in others)
    # a handful of independent draws: the planted member is found every time and a wrong member almost never
    wrong, hit = 0, 0
    for k in range(20):
        rr = F.family_t1(sim(np.random.default_rng(1000 + k), edge=0.6, planted=1), B=800, seed=k + 1)
        hit += "s1" in rr["found"]
        wrong += len([m for m in rr["found"] if m != "s1"])
    assert hit == 20 and wrong <= 1


# ------------------------------------------------------------------------------------------------------------------------------ the whole pipeline on synthetic run directories
def make_member(root: Path, label: str, *, edge_r: float, seed: int, months: int = 130, mean_r: float = 0.4) -> Path:
    d = root / label
    R.make_run(d / "run", months=months, per_month=3, mean_r=mean_r, sd_r=1.1, seed=seed, daily_drift=0.0007, daily_sd=0.004)
    R.make_baseline(d / "baseline", d / "run", edge_r=edge_r, m=12, seed=seed + 50)
    mf = json.loads((d / "run" / "manifest.json").read_text())
    mf["strategies"] = {label: {"exit_policy": "fixed_hold_40"}}
    (d / "run" / "manifest.json").write_text(json.dumps(mf))
    return d


@pytest.fixture(scope="module")
def family(tmp_path_factory):
    root = tmp_path_factory.mktemp("fam")
    dirs = {lab: make_member(root, lab, edge_r=(0.6 if lab == "pullback_uptrend" else 0.0), seed=10 + i) for i, lab in enumerate(LABELS)}
    return root, dirs


def test_the_pipeline_finds_the_one_member_with_an_edge_and_reports_t2_t3_and_counts_for_every_member(family, monkeypatch):
    root, dirs = family

    def boom(*a, **k):
        raise AssertionError("no database may be opened without --lake")
    monkeypatch.setattr(sqlite3, "connect", boom)
    members = {lab: F.load_member(lab, d) for lab, d in dirs.items()}
    res = F.validate_family(members, boot=1500, placebo_reps=10, placebo_boot=100)
    assert res["K"] == 4 and res["members"] == sorted(LABELS) and res["found_by_t1"] == ["pullback_uptrend"]
    assert set(res["T2"]) == set(LABELS) and set(res["counts"]) == set(LABELS) and res["T3"]["reps"] == 10 and res["T3"]["verdict"] in ("size ok", "size unreliable")
    assert set(res["T3"]["per_member_rejection_rate"]) == set(LABELS) and 0.0 <= res["T3"]["size"] <= 1.0
    assert res["gates"] == "not evaluated (no --lake)" and all(c.startswith("NOT EVALUATED") for c in res["conclusion"].values())


def test_the_gates_are_evaluated_per_member_and_the_conclusion_needs_both_t1_and_the_gates(family):
    root, dirs = family
    members = {lab: F.load_member(lab, d) for lab, d in dirs.items()}
    eq = json.loads((dirs["low_volatility"] / "run" / "equity_curve.json").read_text())
    nifty = pd.Series(20000.0 * 1.10 ** (np.arange(len(eq)) / 252.0), index=pd.Index([date.fromisoformat(k) for k in eq]))
    gates = dataclasses.asdict(CFG.validation_gates)
    res = F.validate_family(members, boot=500, placebo_reps=5, placebo_boot=50, nifty=nifty, gates=gates)
    assert set(res["gates"]) == set(LABELS)
    for lab in LABELS:
        g = {r["gate"]: r for r in res["gates"][lab]["gates"]}
        assert set(g) == {"min_trades", "min_expectancy_r", "min_profit_factor", "max_drawdown_pct", "min_alpha_pct"}
        assert g["max_drawdown_pct"]["gate_value"] == CFG.validation_gates.max_drawdown_pct
        found, met = res["T1"]["members"][lab]["dual_significant"], res["gates"][lab]["all_met"]
        assert res["conclusion"][lab] == V.registered_conclusion(found, met)
        if not (found and met):
            assert res["conclusion"][lab].startswith("NOT DEMONSTRATED")


def test_the_command_line_runs_end_to_end_writes_the_json_and_enforces_the_family_size(family, tmp_path, capsys):
    root, dirs = family
    args = [x for lab, d in dirs.items() for x in ("--member", f"{lab}={d}")]
    out = tmp_path / "fam.json"
    assert F.main(args + ["--out-json", str(out), "--boot", "300", "--placebo-reps", "5", "--placebo-boot", "50", "--expect-k", "4"]) == 0
    res = json.loads(out.read_text())
    assert {"K", "members", "T1", "T2", "T3", "gates", "conclusion", "found_by_t1", "counts"} <= set(res) and res["K"] == 4 and res["T1"]["seed"] == 20261111
    assert "found_by_t1" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        F.main(args[:6] + ["--out-json", str(out), "--expect-k", "4"])             # three members given, four registered


def test_bad_inputs_are_refused(family, tmp_path):
    root, dirs = family
    with pytest.raises(ValueError, match="not the strategy"):
        F.load_member("some_other_strategy", dirs["low_volatility"])
    short = make_member(tmp_path, "pullback_uptrend", edge_r=0.0, seed=1, months=60)           # a different window
    members = {"low_volatility": F.load_member("low_volatility", dirs["low_volatility"]), "pullback_uptrend": F.load_member("pullback_uptrend", short)}
    with pytest.raises(ValueError, match="one window"):
        F.validate_family(members, boot=100, placebo_reps=2, placebo_boot=50)
    with pytest.raises(SystemExit):
        F.main(["--member", f"a={dirs['low_volatility']}", "--member", f"a={dirs['low_volatility']}", "--out-json", str(tmp_path / "x.json")])


def test_the_placebo_check_is_deterministic_and_its_limits_are_the_registered_ones(family):
    root, dirs = family
    members = {lab: F.load_member(lab, d) for lab, d in dirs.items()}
    start, end = members[LABELS[0]]["start"], members[LABELS[0]]["end"]
    months = V._months(start, end)
    prepped = {m: F._prep_placebo(v["draws"], v["pairs"], months) for m, v in members.items()}
    a = F.placebo_size_family(prepped, months, reps=8, B=100, seed=3)
    assert a == F.placebo_size_family(prepped, months, reps=8, B=100, seed=3) and a["low"] == 0.025 and a["high"] == 0.075 and a["se"] >= 0.0

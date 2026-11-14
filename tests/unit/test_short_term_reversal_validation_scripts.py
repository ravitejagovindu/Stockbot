"""The B1, B2 and gates scripts of short_term_reversal on fixture lakes only (never finsight.db), the proof that nothing near_52w_high-specific reaches this strategy's outputs, and the layout
scripts/validate_family.py reads:

  member DIR / run/       manifest.json (strategies, window, asof_view), trades.json, equity_curve.json, daily.json, blocked.json   <- scripts/research_short_term_reversal.py --out
  member DIR / baseline/  actual_trades.csv, baseline_draws.csv, baseline_meta.json                                                   <- scripts/baseline_matched_random_short_term_reversal.py --out-dir
The benchmark (B2) and the gates are computed from run/ and the index series; validate_family.py needs run/ and baseline/ only."""
import importlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.strategies.short_term_reversal import SPEC
from tests.fixtures import near_high_run_dir as R
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N = 560
CYCLES = (300, 345, 390, 435)
NAMES = ("research", "baseline_matched_random", "benchmark_nifty_matched", "evaluate_validation_gates")


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


RS, B1, B2, G, F = (script(n) for n in ("research_short_term_reversal", "baseline_matched_random_short_term_reversal", "benchmark_nifty_matched_short_term_reversal",
                           "evaluate_validation_gates_short_term_reversal", "validate_family"))


@pytest.fixture(autouse=True)
def _default_view(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


def dip(depth: float) -> np.ndarray:
    c = np.full(N, 100.0)
    for j in CYCLES:
        c[j:j + 12] = 100.0 * (1.0 - depth)
    return c


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    root = tmp_path_factory.mktemp("strv")
    p = root / "lake.db"
    ds = L.build(p, {f"Z{k:02d}": dip(0.08 + 0.004 * k) for k in range(30)}, n=N)
    member = root / "member"
    assert RS.main(["--lake", str(p), "--start", ds[296].isoformat(), "--end", ds[440].isoformat(), "--out", str(member / "run"), "--execute"]) == 0
    return p, ds, member


def test_the_baseline_uses_the_strategys_own_exit_and_stop_distance_and_records_the_view(chain, capsys):
    p, ds, member = chain
    assert B1.main(["--lake", str(p), "--run-dir", str(member / "run"), "--out-dir", str(member / "baseline"), "--no-hash"]) == 0
    assert "asof_view: sql" in capsys.readouterr().out
    meta = json.loads((member / "baseline" / "baseline_meta.json").read_text())
    assert meta["asof_view"] == "sql" and meta["draws_per_trade"] == 20 and meta["seed"] == 20261111 and meta["policy"] == "fixed_hold_5" and meta["spec_config_hash"] == SPEC.config_hash()
    assert meta["finsight_db"]["unchanged"] is True and meta["usable_trades"] > 0 and meta["pairs_kept"] > 0
    d = pd.read_csv(member / "baseline" / "baseline_draws.csv")
    assert set(d["exit_reason"]) <= {"TIME_EXIT", "STOP_HIT"} and d["days_held"].max() == 5            # fixed_hold_5: exit at the open of session 6, five closes held
    a = pd.read_csv(member / "baseline" / "actual_trades.csv")
    rel = (a["entry_price"] - a["stop"]) / a["entry_price"]
    assert (rel > 0.07).all() and (rel < 0.10).all()                                                   # about 8% below the entry (0.92 x the signal close)
    with pytest.raises(FileExistsError):
        B1.run_baseline(p, member / "run", member / "baseline")                                       # never writes into a used directory


def test_the_baseline_on_the_memory_view_is_byte_identical_and_says_so(chain, tmp_path, monkeypatch):
    p, ds, member = chain
    if not (member / "baseline").exists():
        assert B1.main(["--lake", str(p), "--run-dir", str(member / "run"), "--out-dir", str(member / "baseline"), "--no-hash"]) == 0
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    assert B1.main(["--lake", str(p), "--run-dir", str(member / "run"), "--out-dir", str(tmp_path / "mem"), "--no-hash"]) == 0
    for f in ("actual_trades.csv", "baseline_draws.csv"):
        assert (member / "baseline" / f).read_bytes() == (tmp_path / "mem" / f).read_bytes(), f
    a, b = (json.loads((d / "baseline_meta.json").read_text()) for d in (member / "baseline", tmp_path / "mem"))
    assert (a["asof_view"], b["asof_view"]) == ("sql", "memory")
    assert {k: v for k, v in a.items() if k not in ("asof_view", "finsight_db")} == {k: v for k, v in b.items() if k not in ("asof_view", "finsight_db")}


@pytest.mark.parametrize("view", ["sql", "memory"])
def test_the_benchmark_and_the_gates_run_from_the_run_directory_and_carry_the_view(chain, tmp_path, capsys, monkeypatch, view):
    p, ds, member = chain
    monkeypatch.setenv("STOCKBOT_VIEW", view)
    assert B2.main(["--run-dir", str(member / "run"), "--lake", str(p), "--out-json", str(tmp_path / "b2.json")]) == 0
    b2 = json.loads((tmp_path / "b2.json").read_text())
    assert {"daily_share", "constant_share", "mean_invested_share", "gate_alpha_pct", "asof_view"} <= set(b2) and b2["asof_view"] == view
    assert G.main(["--run-dir", str(member / "run"), "--lake", str(p), "--out-json", str(tmp_path / "g.json"), "--boot", "200"]) == 0
    out = capsys.readouterr().out
    g = json.loads((tmp_path / "g.json").read_text())
    assert g["asof_view"] == view and [r["gate"] for r in g["gates"]] == list(G.GATE_ORDER) and "min_alpha_pct | >= 0.0" in out and "max_drawdown_pct | <= 20.0" in out
    assert g["gate_alpha_is_pre_tax"] is True


def test_nothing_specific_to_near_52w_high_reaches_this_strategys_scripts_or_outputs(chain):
    p, ds, member = chain
    for n in NAMES:                                                                                    # the scripts are this strategy's own: the only near_52w_high name left is the shared T1 script
        src = (ROOT / "scripts" / f"{n}_short_term_reversal.py").read_text(encoding="utf-8")
        left = re.findall(r"near_52w_high|near_high|NearHigh", src.replace("validate_near_52w_high", "").replace("near_high_signal_count", ""))
        assert not left, (n, left)
    blob = " ".join(f.read_text(encoding="utf-8", errors="ignore") for f in (member / "run").iterdir())
    assert "near_52w_high" not in blob and "fixed_hold_40" not in blob
    man = json.loads((member / "run" / "manifest.json").read_text())
    assert list(man["strategies"]) == ["short_term_reversal"] and man["strategies"]["short_term_reversal"]["exit_policy"] == "fixed_hold_5"
    assert {t["strategy_id"] for t in json.loads((member / "run" / "trades.json").read_text())} == {"short_term_reversal"}


def test_the_member_directory_is_the_layout_validate_family_loads(chain, tmp_path):
    p, ds, member = chain
    if not (member / "baseline").exists():
        assert B1.main(["--lake", str(p), "--run-dir", str(member / "run"), "--out-dir", str(member / "baseline"), "--no-hash"]) == 0
    m = F.load_member("short_term_reversal", member)                                                   # manifest label, window, both CSVs, the pair table
    assert m["start"] == ds[296] and m["end"] == ds[440] and len(m["actual"]) > 0 and len(m["draws"]) > 0 and len(m["pairs"]) > 0
    with pytest.raises(ValueError, match="not the strategy"):
        F.load_member("pullback_uptrend", member)
    synth = tmp_path / "synth"                                                                        # the same files and columns as the synthetic members validate_family's own tests use
    R.make_run(synth / "run", months=6, per_month=3, seed=3)
    R.make_baseline(synth / "baseline", synth / "run", edge_r=0.0, seed=4)
    assert {"manifest.json", "trades.json", "equity_curve.json", "daily.json"} <= {f.name for f in (member / "run").iterdir()}
    for csv in ("actual_trades.csv", "baseline_draws.csv"):
        assert set(pd.read_csv(synth / "baseline" / csv).columns) <= set(pd.read_csv(member / "baseline" / csv).columns), csv
    assert set(json.loads((member / "run" / "trades.json").read_text())[0]) >= set(json.loads((synth / "run" / "trades.json").read_text())[0])


def test_validate_family_dry_run_on_two_fixture_members_accepts_the_layout_and_the_family_size(tmp_path, capsys):
    dirs = {}
    for i, lab in enumerate(("short_term_reversal", "pullback_uptrend")):
        d = tmp_path / lab
        R.make_run(d / "run", months=60, per_month=3, mean_r=0.3, seed=20 + i)
        R.make_baseline(d / "baseline", d / "run", edge_r=0.0, m=12, seed=70 + i)
        mf = json.loads((d / "run" / "manifest.json").read_text())
        mf["strategies"] = {lab: {"exit_policy": "fixed_hold_5"}}
        mf["asof_view"] = "memory"
        (d / "run" / "manifest.json").write_text(json.dumps(mf))
        dirs[lab] = d
    argv = [x for lab, d in dirs.items() for x in ("--member", f"{lab}={d}")]
    out = tmp_path / "fam.json"
    assert F.main(argv + ["--out-json", str(out), "--boot", "200", "--placebo-reps", "3", "--placebo-boot", "50", "--expect-k", "2"]) == 0
    res = json.loads(out.read_text())
    assert res["K"] == 2 and set(res["members"]) == {"short_term_reversal", "pullback_uptrend"} and res["T1"]["seed"] == 20261111 and res["T1"]["B"] == 200
    assert "found_by_t1" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        F.main(argv[:2] + ["--out-json", str(out), "--expect-k", "2"])                                # one member given, two registered

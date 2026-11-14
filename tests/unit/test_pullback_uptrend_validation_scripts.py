"""The B1, B2 and gates scripts of pullback_uptrend on fixture lakes and SYNTHETIC run directories only (never finsight.db), and the output layout scripts/validate_family.py reads:

  member DIR / run/       manifest.json (strategies, window, asof_view), trades.json, equity_curve.json, daily.json, blocked.json   <- scripts/research_pullback_uptrend.py --out
  member DIR / baseline/  actual_trades.csv, baseline_draws.csv, baseline_meta.json                                                   <- scripts/baseline_matched_random_pullback_uptrend.py --out-dir
The benchmark (B2) and the gates are computed from run/ and the index series; validate_family.py needs run/ and baseline/ only."""
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.strategies.pullback_uptrend import SPEC
from tests.fixtures import near_high_run_dir as R
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N, S = L.N, 280


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


RS, B1, B2, G, F = (script(n) for n in ("research_pullback_uptrend", "baseline_matched_random_pullback_uptrend", "benchmark_nifty_matched_pullback_uptrend",
                                       "evaluate_validation_gates_pullback_uptrend", "validate_family"))


@pytest.fixture(autouse=True)
def _default_view(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


def dip(seed, drift=0.002):
    rng = np.random.default_rng(seed)
    c = 100.0 * (1 + drift) ** np.arange(N) * (1 + 0.001 * rng.standard_normal(N))
    for i, dr in enumerate((0.04, 0.04, 0.04)):
        c[S - 2 + i] = c[S - 3 + i] * (1 - dr)
    c[S + 1:] = c[S]
    return c


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    """Fixture lake with three dipping names (they signal) and a pool of rising names (they do not, but they are eligible and fill the random draws)."""
    root = tmp_path_factory.mktemp("pbv")
    series = {f"D{k}": dip(k) for k in range(3)}
    series.update({f"N{k:02d}": L.rise(100 + k, 0.001) for k in range(25)})
    p = root / "lake.db"
    ds = L.build(p, series)
    member = root / "member"
    assert RS.main(["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[S + 20].isoformat(), "--out", str(member / "run"), "--execute"]) == 0
    return p, ds, member


def test_the_baseline_uses_the_strategys_own_exit_and_stop_distance_and_records_the_view(chain, tmp_path, capsys, monkeypatch):
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
    assert (rel > 0.07).all() and (rel < 0.10).all()                                                   # about 8% below the entry
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


def test_the_member_directory_is_the_layout_validate_family_loads(chain, tmp_path):
    p, ds, member = chain
    if not (member / "baseline").exists():
        assert B1.main(["--lake", str(p), "--run-dir", str(member / "run"), "--out-dir", str(member / "baseline"), "--no-hash"]) == 0
    m = F.load_member("pullback_uptrend", member)                                                      # manifest label, window, both CSVs, the pair table
    assert m["start"] == ds[S] and m["end"] == ds[S + 20] and len(m["actual"]) > 0 and len(m["draws"]) > 0 and len(m["pairs"]) > 0
    with pytest.raises(ValueError, match="not the strategy"):
        F.load_member("short_term_reversal", member)
    synth = tmp_path / "synth"                                                                        # the same files and columns as the synthetic members validate_family's own tests use
    R.make_run(synth / "run", months=6, per_month=3, seed=3)
    R.make_baseline(synth / "baseline", synth / "run", edge_r=0.0, seed=4)
    assert {"manifest.json", "trades.json", "equity_curve.json", "daily.json"} <= {f.name for f in (member / "run").iterdir()} >= {f.name for f in (synth / "run").iterdir()} - {"blocked.json"}
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

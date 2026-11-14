"""scripts/research_pullback_uptrend.py wires the strategy into run_backtest. Proven on a fixture lake only; the registered run waits for the owner's family registration."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from stockbot.strategies.pullback_uptrend import SPEC
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N, S = L.N, 280                                                   # S: the signal session of the fixture series


def script():
    spec = importlib.util.spec_from_file_location("research_pullback_uptrend", ROOT / "scripts" / "research_pullback_uptrend.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def uptrend_then_drops(seed, drops=(0.04, 0.04, 0.04), drift=0.002, start=100.0):
    rng = np.random.default_rng(seed)
    c = start * (1 + drift) ** np.arange(N) * (1 + 0.001 * rng.standard_normal(N))
    for i, dr in enumerate(drops):
        c[S - len(drops) + 1 + i] = c[S - len(drops) + i] * (1 - dr)
    c[S + 1:] = c[S]
    return c


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    series = {"A_GOOD": uptrend_then_drops(1), "B_STOP": uptrend_then_drops(2), "C_GAP": uptrend_then_drops(3)}
    series["B_STOP"][S + 3:] = series["B_STOP"][S] * 0.80          # the 8% stop fires on S+3
    p = tmp_path_factory.mktemp("rp") / "lake.db"
    ds = L.build(p, series, skip={"C_GAP": {S + 3, S + 4}})
    return p, ds


@pytest.fixture(autouse=True)
def _default_view(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


def args(lake, out, *extra):
    p, ds = lake
    return ["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[S + 14].isoformat(), "--out", str(out), *extra]


@pytest.mark.parametrize("view", ["sql", "memory"])
def test_without_execute_it_prints_the_plan_and_runs_nothing(lake, tmp_path, capsys, monkeypatch, view):
    monkeypatch.setenv("STOCKBOT_VIEW", view)
    rc = script().main(args(lake, tmp_path / "o"))
    assert rc == 0 and not (tmp_path / "o").exists()                                       # refusal: no run, no output directory
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan["strategy"] == "pullback_uptrend" and plan["exit_policy"] == "fixed_hold_5" and plan["status"] == "research"
    assert plan["spec_config_hash"] == SPEC.config_hash() and len(plan["shared_config_hash"]) == 64 and plan["asof_view"] == view
    assert "plan only" in cap.err


def test_execute_without_out_is_refused(lake, capsys):
    p, ds = lake
    assert script().main(["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[S + 14].isoformat(), "--execute"]) == 2
    assert "--out is required" in capsys.readouterr().err


def test_default_window_is_the_family_window_and_the_spec_is_final():
    m = script()
    assert (m.DEFAULT_START, m.DEFAULT_END) == ("2016-01-01", "2026-10-16")
    assert (SPEC.expected_trade_rate, SPEC.smallest_edge_of_interest, SPEC.prereg_ref) == (31.7, 0.15, "docs/strategies/pullback_uptrend/PREREGISTRATION.md")


def test_execute_runs_one_backtest_and_writes_the_layout_the_family_tool_reads(lake, tmp_path, capsys):
    out = tmp_path / "run"
    rc = script().main(args(lake, out, "--execute"))
    assert rc == 0
    cap = capsys.readouterr().out
    assert "asof_view: sql" in cap and "pnl" not in cap.lower()
    assert sorted(f.name for f in out.iterdir()) == ["blocked.json", "daily.json", "equity_curve.json", "manifest.json", "trades.json"]
    man = json.loads((out / "manifest.json").read_text())
    assert man["asof_view"] == "sql" and man["window"][0] == lake[1][S].isoformat()
    assert man["strategies"]["pullback_uptrend"]["exit_policy"] == "fixed_hold_5" and man["strategies"]["pullback_uptrend"]["config_hash"] == SPEC.config_hash()
    trades = json.loads((out / "trades.json").read_text())
    reasons = {t["symbol"]: t["exit_reason"] for t in trades if t["exit_reason"] != "END_OF_WINDOW"}
    assert reasons["A_GOOD"] == "TIME_EXIT" and reasons["B_STOP"] == "STOP_HIT"            # the library policy and the stop, through the shared runner
    daily = json.loads((out / "daily.json").read_text())
    assert set(next(iter(daily.values()))) == {"equity", "cash"} and len(daily) == 15 and all(v["cash"] <= v["equity"] for v in daily.values())
    blocked = json.loads((out / "blocked.json").read_text())
    assert isinstance(blocked, list) and all(set(b) == {"date", "strategy_id", "symbol", "reason", "stage"} for b in blocked)
    assert script().main(args(lake, out, "--execute")) == 2                                # never overwrites a run


def test_the_memory_view_run_is_byte_identical_and_its_manifest_says_so(lake, tmp_path, monkeypatch):
    sql_dir, mem_dir = tmp_path / "sql", tmp_path / "mem"
    assert script().main(args(lake, sql_dir, "--execute")) == 0
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    assert script().main(args(lake, mem_dir, "--execute")) == 0
    for f in ("trades.json", "daily.json", "equity_curve.json", "blocked.json"):
        assert (sql_dir / f).read_bytes() == (mem_dir / f).read_bytes(), f
    a, b = (json.loads((d / "manifest.json").read_text()) for d in (sql_dir, mem_dir))
    assert (a["asof_view"], b["asof_view"]) == ("sql", "memory") and {k: v for k, v in a.items() if k != "asof_view"} == {k: v for k, v in b.items() if k != "asof_view"}

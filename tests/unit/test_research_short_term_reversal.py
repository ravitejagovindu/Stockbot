"""scripts/research_short_term_reversal.py wires the strategy into run_backtest. Proven on a fixture lake only; the registered run waits for the owner's family registration."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from stockbot.strategies.short_term_reversal import SPEC
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N = 560
CYCLES = (300, 345, 390, 435)


def script():
    spec = importlib.util.spec_from_file_location("research_short_term_reversal", ROOT / "scripts" / "research_short_term_reversal.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def dip(depth: float) -> np.ndarray:
    c = np.full(N, 100.0)
    for j in CYCLES:
        c[j:j + 12] = 100.0 * (1.0 - depth)                      # a fall visible against the bar 5 sessions back (still 100), then back to 100
    return c


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("rs") / "lake.db"
    ds = L.build(p, {f"Z{k:02d}": dip(0.08 + 0.004 * k) for k in range(30)}, n=N)
    return p, ds


@pytest.fixture(autouse=True)
def _default_view(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


def args(lake, out, *extra):
    p, ds = lake
    return ["--lake", str(p), "--start", ds[296].isoformat(), "--end", ds[360].isoformat(), "--out", str(out), *extra]


@pytest.mark.parametrize("view", ["sql", "memory"])
def test_without_execute_it_prints_the_plan_and_runs_nothing(lake, tmp_path, capsys, monkeypatch, view):
    monkeypatch.setenv("STOCKBOT_VIEW", view)
    rc = script().main(args(lake, tmp_path / "o"))
    assert rc == 0 and not (tmp_path / "o").exists()                                       # refusal: no run, no output directory
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan["strategy"] == "short_term_reversal" and plan["exit_policy"] == "fixed_hold_5" and plan["status"] == "research"
    assert plan["spec_config_hash"] == SPEC.config_hash() and len(plan["shared_config_hash"]) == 64 and plan["asof_view"] == view
    assert "plan only" in cap.err


def test_execute_without_out_is_refused(lake, capsys):
    p, ds = lake
    assert script().main(["--lake", str(p), "--start", ds[296].isoformat(), "--end", ds[360].isoformat(), "--execute"]) == 2
    assert "--out is required" in capsys.readouterr().err


def test_default_window_is_the_family_window_and_the_spec_is_final():
    m = script()
    assert (m.DEFAULT_START, m.DEFAULT_END) == ("2016-01-01", "2026-10-16")
    assert (SPEC.expected_trade_rate, SPEC.smallest_edge_of_interest, SPEC.prereg_ref) == (23.0, 0.15, "docs/strategies/short_term_reversal/PREREGISTRATION.md")


def test_execute_runs_one_backtest_and_writes_the_layout_the_family_tool_reads(lake, tmp_path, capsys):
    out = tmp_path / "run"
    assert script().main(args(lake, out, "--execute")) == 0
    cap = capsys.readouterr().out
    assert "asof_view: sql" in cap and "pnl" not in cap.lower()
    assert sorted(f.name for f in out.iterdir()) == ["blocked.json", "daily.json", "equity_curve.json", "manifest.json", "trades.json"]
    man = json.loads((out / "manifest.json").read_text())
    assert man["asof_view"] == "sql" and man["window"][0] == lake[1][296].isoformat()
    assert list(man["strategies"]) == ["short_term_reversal"]                               # nothing of another strategy leaks into the run
    assert man["strategies"]["short_term_reversal"]["exit_policy"] == "fixed_hold_5" and man["strategies"]["short_term_reversal"]["config_hash"] == SPEC.config_hash()
    trades = json.loads((out / "trades.json").read_text())
    assert len(trades) >= 8 and {t["strategy_id"] for t in trades} == {"short_term_reversal"}
    assert {t["exit_reason"] for t in trades} <= {"TIME_EXIT", "STOP_HIT", "END_OF_WINDOW"} and "TIME_EXIT" in {t["exit_reason"] for t in trades}
    daily = json.loads((out / "daily.json").read_text())
    assert set(next(iter(daily.values()))) == {"equity", "cash"} and all(v["cash"] <= v["equity"] for v in daily.values())
    eq = json.loads((out / "equity_curve.json").read_text())
    assert all(daily[k]["equity"] == pytest.approx(eq[k]) for k in eq)
    blocked = json.loads((out / "blocked.json").read_text())
    assert isinstance(blocked, list) and all(set(b) == {"date", "strategy_id", "symbol", "reason", "stage"} for b in blocked)
    assert script().main(args(lake, out, "--execute")) == 2                                # never overwrites a run


def test_the_wiring_uses_the_one_shared_sector_lookup():
    import stockbot.data.sector_map as sm
    assert script().SectorLookup is sm.SectorLookup                                        # not a copy


def test_the_memory_view_run_is_byte_identical_and_its_manifest_says_so(lake, tmp_path, monkeypatch):
    sql_dir, mem_dir = tmp_path / "sql", tmp_path / "mem"
    assert script().main(args(lake, sql_dir, "--execute")) == 0
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    assert script().main(args(lake, mem_dir, "--execute")) == 0
    for f in ("trades.json", "daily.json", "equity_curve.json", "blocked.json"):
        assert (sql_dir / f).read_bytes() == (mem_dir / f).read_bytes(), f
    a, b = (json.loads((d / "manifest.json").read_text()) for d in (sql_dir, mem_dir))
    assert (a["asof_view"], b["asof_view"]) == ("sql", "memory") and {k: v for k, v in a.items() if k != "asof_view"} == {k: v for k, v in b.items() if k != "asof_view"}

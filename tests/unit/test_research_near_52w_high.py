"""scripts/research_near_52w_high.py wires the strategy into run_backtest. Proven on a fixture lake only; the real run is STOP 4."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]


def script():
    spec = importlib.util.spec_from_file_location("research_near_52w_high", ROOT / "scripts" / "research_near_52w_high.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("rs") / "lake.db"
    series = {"A_GOOD": L.rise(100, 0.001), "B_STOP": L.rise(100, 0.0012), "C_GAP": L.rise(100, 0.0008)}
    series["B_STOP"][262:] = series["B_STOP"][261] * 0.7
    ds = L.build(p, series, skip={"C_GAP": {270, 271}})
    return p, ds


def test_without_execute_it_prints_the_plan_and_runs_nothing(lake, tmp_path, capsys):
    p, ds = lake
    rc = script().main(["--lake", str(p), "--start", ds[251].isoformat(), "--end", ds[300].isoformat(), "--out", str(tmp_path / "o")])
    assert rc == 0 and not (tmp_path / "o").exists()
    plan = json.loads(capsys.readouterr().out)
    assert plan["strategy"] == "near_52w_high" and plan["exit_policy"] == "fixed_hold_40" and plan["status"] == "research" and plan["window"][0] == ds[251].isoformat()


def test_default_window_is_the_one_the_owner_fixed():
    m = script()
    assert (m.DEFAULT_START, m.DEFAULT_END) == ("2016-01-01", "2026-10-16")


def test_execute_runs_one_backtest_through_run_backtest_and_writes_the_manifest(lake, tmp_path, capsys):
    p, ds = lake
    out = tmp_path / "run"
    rc = script().main(["--lake", str(p), "--start", ds[251].isoformat(), "--end", ds[300].isoformat(), "--out", str(out), "--execute"])
    assert rc == 0
    man = json.loads((out / "manifest.json").read_text())
    assert man["strategies"]["near_52w_high"]["exit_policy"] == "fixed_hold_40" and man["strategies"]["near_52w_high"]["config_hash"]
    trades = json.loads((out / "trades.json").read_text())
    reasons = {t["symbol"]: t["exit_reason"] for t in trades if t["exit_reason"] != "END_OF_WINDOW"}
    assert reasons["A_GOOD"] == "TIME_EXIT" and reasons["B_STOP"] == "STOP_HIT"           # the library policy and the stop, through the shared runner
    assert "pnl" not in capsys.readouterr().out.lower()                                     # nothing about P&L is printed
    assert script().main(["--lake", str(p), "--start", ds[251].isoformat(), "--end", ds[300].isoformat(), "--out", str(out), "--execute"]) == 2     # never overwrites a run

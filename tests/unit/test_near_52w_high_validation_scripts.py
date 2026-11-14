"""The four STOP 4 scripts for near_52w_high, on SYNTHETIC data and fixture lakes only (never finsight.db):
  scripts/benchmark_nifty_matched_near_52w_high.py        B2: Nifty matched to the strategy's daily invested share, 6.5% on the rest, and the annualised alpha;
  scripts/evaluate_validation_gates_near_52w_high.py      every registered gate computed from a run and printed beside the gate value;
  scripts/baseline_matched_random_near_52w_high.py        B1: 20 matched random draws per actual trade through the shared simulator and FixedHold(40);
  scripts/validate_near_52w_high.py                       T1 (Max-T on entry-month sums, blocks 2 and 3), T2 (paired statistics), T3 (placebo size check), sub-periods.
They run on a lake only where a price is needed, and they read no price after what they must."""
import dataclasses
import importlib
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.config.shared import load_shared_config
from stockbot.data.lake import open_lake
from tests.fixtures import mini_lake
from tests.fixtures import near_high_run_dir as R
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
CFG = load_shared_config()
GATES = dataclasses.asdict(CFG.validation_gates)


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


def nifty_for(run: dict, annual: float) -> pd.Series:
    n = len(run["days"])
    return pd.Series(20000.0 * (1.0 + annual) ** (np.arange(n) / 252.0), index=pd.Index(run["days"]))


# ------------------------------------------------------------------------------------------------------------------------------------------ B2 benchmark
def test_benchmark_formula_on_a_hand_example():
    B = script("benchmark_nifty_matched_near_52w_high")
    idx = pd.Index([date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)])
    nifty = pd.Series([100.0, 110.0, 99.0], index=idx)
    share = pd.Series([0.5, 1.0, 0.2], index=idx)
    r = B.benchmark_returns(nifty, share, 6.3)
    rf = 0.063 / 252
    assert list(r.index) == [idx[1], idx[2]]
    assert r.iloc[0] == pytest.approx(0.5 * 0.10 + 0.5 * rf)                        # day 1 uses the share at the PREVIOUS close (0.5)
    assert r.iloc[1] == pytest.approx(1.0 * (99.0 / 110.0 - 1.0) + 0.0 * rf)        # day 2 uses 1.0
    assert B.benchmark_returns(nifty, pd.Series(0.0, index=idx), 6.3).tolist() == pytest.approx([rf, rf])      # fully in cash: only the risk-free rate
    assert B.benchmark_returns(nifty, pd.Series(1.0, index=idx), 6.3).tolist() == pytest.approx([0.10, 99.0 / 110.0 - 1.0])  # fully invested: only the index
    c = B.benchmark_returns(nifty, share, 6.3, constant_share=True)
    assert c.iloc[0] == pytest.approx((0.5 + 1.0 + 0.2) / 3 * 0.10 + (1 - (0.5 + 1.0 + 0.2) / 3) * rf)              # the run's mean share, constant


def test_invested_share_and_alpha_and_tax_hook():
    B = script("benchmark_nifty_matched_near_52w_high")
    idx = pd.Index([date(2020, 1, 1), date(2021, 1, 1)])
    assert B.invested_share(pd.Series([100.0, 200.0], index=idx), pd.Series([25.0, 50.0], index=idx)).tolist() == [0.75, 0.75]
    eq = pd.Series([100.0, 144.0], index=idx)                                       # +44% over 366 days
    bench = pd.Series([0.2], index=pd.Index([idx[1]]))                              # +20% over the same period
    a = B.alpha_pct(eq, bench)
    years = 366 / 365.25
    assert a["strategy_cagr_pct"] == pytest.approx(100 * (1.44 ** (1 / years) - 1)) and a["benchmark_cagr_pct"] == pytest.approx(100 * (1.2 ** (1 / years) - 1))
    assert a["alpha_pct"] == pytest.approx(a["strategy_cagr_pct"] - a["benchmark_cagr_pct"])
    assert B.alpha_pct(eq, bench, tax_pct=0.0) == a                                  # tax 0: after-tax equals pre-tax
    taxed = B.alpha_pct(eq, bench, tax_pct=20.0)
    assert taxed["strategy_cagr_pct"] < a["strategy_cagr_pct"] and taxed["benchmark_cagr_pct"] < a["benchmark_cagr_pct"]


# ------------------------------------------------------------------------------------------------------------------------------------------ gates
@pytest.fixture(scope="module")
def good_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("good") / "run"
    run = R.make_run(d, months=60, per_month=6, mean_r=0.45, sd_r=1.1, seed=3, daily_drift=0.0007, daily_sd=0.004)
    return d, run


def rows(res):
    return {r["gate"]: r for r in res["gates"]}


def test_a_good_run_meets_every_gate_and_each_gate_is_printed_beside_its_registered_value(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    res = G.evaluate(d, nifty_for(run, 0.10), GATES, boot=500)
    r = rows(res)
    assert set(r) == {"min_trades", "min_expectancy_r", "min_profit_factor", "max_drawdown_pct", "min_alpha_pct"}
    assert r["max_drawdown_pct"]["gate_value"] == 20.0 and r["min_trades"]["gate_value"] == 40 and r["min_expectancy_r"]["gate_value"] == 0.15
    assert r["min_profit_factor"]["gate_value"] == 1.3 and r["min_alpha_pct"]["gate_value"] == 0.0
    assert all(x["met"] for x in r.values()) and res["all_met"] is True
    assert r["min_trades"]["observed"] == 360 and r["min_expectancy_r"]["interval"][0] < r["min_expectancy_r"]["observed"] < r["min_expectancy_r"]["interval"][1]
    text = G.format_table(res)
    for name in r:
        assert name in text
    assert "20.0" in text and "DESCRIPTIVE" in text


def test_the_gate_values_come_from_the_shared_config_not_from_the_script(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    custom = dict(GATES, max_drawdown_pct=0.001)
    assert rows(G.evaluate(d, nifty_for(run, 0.10), custom, boot=200))["max_drawdown_pct"]["met"] is False
    assert G.load_gates()["max_drawdown_pct"] == 20.0 == CFG.validation_gates.max_drawdown_pct


def test_excluded_and_end_of_window_trades_are_not_counted(tmp_path):
    G = script("evaluate_validation_gates_near_52w_high")
    run = R.make_run(tmp_path / "r", months=12, per_month=6, mean_r=0.0, seed=5, extra_end_of_window=3, extra_excluded_ca=3)
    res = G.evaluate(tmp_path / "r", nifty_for(run, 0.10), GATES, boot=200)
    assert res["counts"]["closed"] == 72 + 6 and res["counts"]["usable"] == 72 and res["counts"]["end_of_window"] == 3 and res["counts"]["excluded_ca"] == 3
    assert rows(res)["min_trades"]["observed"] == 72


@pytest.mark.parametrize("kwargs,failed,kept", [
    (dict(mean_r=-0.9, sd_r=0.2), {"min_expectancy_r", "min_profit_factor"}, {"min_trades"}),                         # every trade loses about 0.9 R
    (dict(n_trades=39), {"min_trades"}, {"max_drawdown_pct"}),                                                         # 39 trades: one short of the floor
    (dict(drawdown_pct=35.0), {"max_drawdown_pct"}, {"min_trades", "min_expectancy_r"}),                               # a 35% peak-to-trough fall
])
def test_a_deliberately_bad_run_fails_the_relevant_gate_and_only_that_family(tmp_path, kwargs, failed, kept):
    G = script("evaluate_validation_gates_near_52w_high")
    base = dict(months=60, per_month=6, mean_r=0.45, sd_r=1.1, seed=3, daily_drift=0.0007, daily_sd=0.004)
    run = R.make_run(tmp_path / "r", **{**base, **kwargs})
    res = G.evaluate(tmp_path / "r", nifty_for(run, 0.10), GATES, boot=200)
    r = rows(res)
    for g in failed:
        assert r[g]["met"] is False, (g, r[g])
    for g in kept:
        assert r[g]["met"] is True, (g, r[g])
    assert res["all_met"] is False


def test_the_alpha_gate_fails_when_the_matched_benchmark_is_far_ahead(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    r = rows(G.evaluate(d, nifty_for(run, 0.45), GATES, boot=200))
    assert r["min_alpha_pct"]["met"] is False and r["min_alpha_pct"]["observed"] < 0.0


def test_the_wrappers_use_the_one_shared_implementation():
    from stockbot.validation import benchmark_alpha as BA
    B = script("benchmark_nifty_matched_near_52w_high")
    assert B.benchmark_returns is BA.benchmark_returns and B.alpha_pct is BA.alpha_pct and B.invested_share is BA.invested_share and B.cash_credited_equity is BA.cash_credited_equity
    G = script("evaluate_validation_gates_near_52w_high")
    assert G.BA is BA


def test_the_alpha_gate_uses_the_cash_credited_pre_tax_alpha_and_reports_the_raw_one(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    res = G.evaluate(d, nifty_for(run, 0.10), GATES, boot=200)
    a = res["alpha"]
    assert rows(res)["min_alpha_pct"]["observed"] == a["gate_alpha_pct"] == a["cash_credited"]["alpha_pct"]
    assert a["cash_credited"]["alpha_pct"] > a["raw"]["alpha_pct"]                       # the strategy's idle cash now earns the risk-free rate, like the benchmark's
    assert a["cash_credited"]["benchmark_cagr_pct"] == a["raw"]["benchmark_cagr_pct"] and res["gate_alpha_is_pre_tax"] is True and a["risk_free_pct"] == 6.5
    assert set(a["after_tax_illustrative"]) == {"0.0", "20.0"} and a["after_tax_illustrative"]["0.0"]["alpha_pct"] == pytest.approx(a["cash_credited"]["alpha_pct"])
    assert "not tax advice" in a["after_tax_label"] and "does not feed back" in a["note"]


def test_the_after_tax_rates_are_reporting_only_and_never_move_the_gate(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    n = nifty_for(run, 0.10)
    a, b = G.evaluate(d, n, GATES, boot=200, after_tax_rates_pct=(0.0,)), G.evaluate(d, n, GATES, boot=200, after_tax_rates_pct=(0.0, 20.0, 35.0))
    assert [x["observed"] for x in a["gates"]] == [x["observed"] for x in b["gates"]] and a["all_met"] == b["all_met"]
    assert set(b["alpha"]["after_tax_illustrative"]) == {"0.0", "20.0", "35.0"}
    taxed = b["alpha"]["after_tax_illustrative"]
    assert taxed["20.0"]["strategy_cagr_pct"] < taxed["0.0"]["strategy_cagr_pct"]


def test_the_cash_credit_does_not_touch_the_runs_own_equity_or_the_trade_gates(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    before = (d / "equity_curve.json").read_bytes(), (d / "daily.json").read_bytes()
    r1 = rows(G.evaluate(d, nifty_for(run, 0.10), GATES, boot=200))
    after = (d / "equity_curve.json").read_bytes(), (d / "daily.json").read_bytes()
    assert before == after
    r2 = rows(G.evaluate(d, nifty_for(run, 0.10), dict(GATES, risk_free_pct=0.0), boot=200))
    for g in ("min_trades", "min_expectancy_r", "min_profit_factor", "max_drawdown_pct"):
        assert r1[g]["observed"] == r2[g]["observed"]                                         # the credit changes only the alpha, never sizing-derived numbers


def test_the_implied_annual_return_line_is_reported_beside_the_matched_cagr_and_is_not_a_gate(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    res = G.evaluate(d, nifty_for(run, 0.10), GATES, boot=200, max_loss_pct=1.0)
    im, c = res["implied_annual_return"], res["counts"]
    assert im["non_gating"] is True and im["max_loss_pct_per_trade"] == 1.0
    assert im["implied_annual_return_pct"] == pytest.approx(im["trades_per_year"] * im["expectancy_r"] * 1.0)
    assert im["trades_per_year"] == pytest.approx(c["usable"] / res["alpha"]["raw"]["years"]) and im["matched_benchmark_cagr_pct"] == res["alpha"]["raw"]["benchmark_cagr_pct"]
    assert "implied_annual_return" not in {r["gate"] for r in res["gates"]}
    text = G.format_table(res)
    for needle in ("raw alpha", "cash-credited alpha, pre-tax (GATE)", "not tax advice", "implied annual return (reported, not a gate)", "matched Nifty CAGR", "does not feed back into sizing"):
        assert needle in text, needle


def test_the_defaults_for_the_reporting_inputs_come_from_the_shared_config(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    res = G.evaluate(d, nifty_for(run, 0.10), GATES, boot=200)
    assert res["implied_annual_return"]["max_loss_pct_per_trade"] == CFG.portfolio_risk.max_loss_pct_per_trade
    assert set(res["alpha"]["after_tax_illustrative"]) == {str(float(x)) for x in CFG.reporting.after_tax_rates_pct}


def test_drawdown_and_profit_factor_helpers():
    G = script("evaluate_validation_gates_near_52w_high")
    eq = pd.Series([100.0, 120.0, 90.0, 95.0, 130.0, 104.0])
    assert G.max_drawdown_pct(eq) == pytest.approx(25.0)                              # 120 -> 90
    assert G.profit_factor(pd.Series([3.0, -1.0, 2.0, -1.0])) == pytest.approx(2.5)
    assert G.profit_factor(pd.Series([1.0, 2.0])) == float("inf") and G.profit_factor(pd.Series([-1.0])) == 0.0 and G.profit_factor(pd.Series([], dtype=float)) == 0.0


def test_results_are_deterministic_for_a_fixed_seed_and_only_intervals_move_with_the_seed(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    n = nifty_for(run, 0.10)
    a, b = G.evaluate(d, n, GATES, boot=300, seed=7), G.evaluate(d, n, GATES, boot=300, seed=7)
    c = G.evaluate(d, n, GATES, boot=300, seed=8)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert [x["observed"] for x in a["gates"]] == [x["observed"] for x in c["gates"]]
    assert [x["interval"] for x in a["gates"]] != [x["interval"] for x in c["gates"]]


def test_sub_periods_are_descriptive_and_carry_no_pass_or_fail(good_run):
    G = script("evaluate_validation_gates_near_52w_high")
    d, run = good_run
    res = G.evaluate(d, nifty_for(run, 0.10), GATES, boot=200)
    assert set(res["descriptive"]) == {"2016-2019", "2020-2026"}
    flat = json.dumps(res["descriptive"])
    assert "met" not in flat and "pass" not in flat.lower() and all(v["descriptive"] is True for v in res["descriptive"].values())


def test_the_gates_script_reads_only_the_index_series_inside_the_window(tmp_path):
    G = script("evaluate_validation_gates_near_52w_high")
    ds = mini_lake.sessions(L.N)
    lake = tmp_path / "lake.db"
    L.build(lake, {"A": L.rise(100, 0.001)})
    run_dir = tmp_path / "run"
    R.make_run(run_dir, months=3, per_month=4, start=ds[10], mean_r=0.3, seed=2)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    seen = []
    orig = open_lake

    def traced(*a, **k):
        c = orig(*a, **k)
        c.set_trace_callback(seen.append)
        return c
    G_open = G.open_lake
    G.open_lake = traced
    try:
        G.main(["--lake", str(lake), "--run-dir", str(run_dir), "--out-json", str(tmp_path / "g.json")])
    finally:
        G.open_lake = G_open
    prices = [s for s in seen if "market_data_lake" in s]
    assert prices and all("NIFTY50_INDEX" in s for s in prices)                       # no stock price is read
    iso = re.compile(r"\d{4}-\d{2}-\d{2}")
    assert all(d <= manifest["window"][1] for s in prices for d in iso.findall(s))     # and nothing after the window ends
    out = json.loads((tmp_path / "g.json").read_text())
    assert "gates" in out and "counts" in out


# ------------------------------------------------------------------------------------------------------------------------------------------ B1 baseline
def _lake_with_pool(tmp_path, n_names: int = 30):
    series = {f"N{k:02d}": L.rise(100 + k, 0.001) for k in range(n_names)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    return p, ds, series


def _manual_run(tmp_path, ds, symbol="N00", entry_idx=260):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    entry_px = float(L.rise(100, 0.001)[entry_idx]) * 0.999
    stop = 0.85 * float(L.rise(100, 0.001)[entry_idx - 1])
    t = dict(position_id="x1", strategy_id="near_52w_high", symbol=symbol, entry_date=ds[entry_idx].isoformat(), exit_date=ds[entry_idx + 40].isoformat(), entry_price=entry_px,
             initial_stop=stop, shares_initial=600.0, risk_inr=600.0 * (entry_px - stop), gross_pnl=1000.0, costs=50.0, net_pnl=950.0, exit_reason="TIME_EXIT", excluded_ca=False)
    (run_dir / "trades.json").write_text(json.dumps([t]))
    (run_dir / "manifest.json").write_text(json.dumps({"window": [ds[240].isoformat(), ds[310].isoformat()], "initial_equity": 1_000_000.0}))
    return run_dir, t


def test_the_baseline_matches_entry_date_stop_and_exit_and_excludes_the_trades_own_symbol(tmp_path):
    B1 = script("baseline_matched_random_near_52w_high")
    p, ds, _ = _lake_with_pool(tmp_path)
    run_dir, t = _manual_run(tmp_path, ds)
    meta = B1.run_baseline(p, run_dir, tmp_path / "out", draws=20, min_filled=10, seed=20261111)
    d = pd.read_csv(tmp_path / "out" / "baseline_draws.csv")
    assert len(d) == 20 and meta["draws_per_trade"] == 20 and meta["pairs_kept"] == 1 and meta["dropped_pairs"] == 0
    assert set(d["matched_trade_id"]) == {"x1"} and "N00" not in set(d["symbol"]) and d["symbol"].nunique() == 20
    assert set(d["entry_date"]) == {t["entry_date"]}                                    # the actual trade's entry date: the strategy's own timing
    assert set(d["exit_reason"]) == {"TIME_EXIT"} and set(d["days_held"]) == {40}       # the library policy fixed_hold_40: exit at the open of session 41
    rel = (d["entry_price"] - d["stop"]) / d["entry_price"]
    assert rel.between(0.14, 0.16).all()                                                # the same relative stop distance (about 15%)
    a = pd.read_csv(tmp_path / "out" / "actual_trades.csv")
    expected_window = "2016-2019" if ds[260] <= date(2019, 12, 31) else "2020-2026"
    assert a.loc[0, "net_r"] == pytest.approx(950.0 / t["risk_inr"]) and a.loc[0, "window"] == expected_window


def test_the_baseline_is_deterministic_for_a_seed_and_the_seed_matters(tmp_path):
    B1 = script("baseline_matched_random_near_52w_high")
    p, ds, _ = _lake_with_pool(tmp_path)
    run_dir, _ = _manual_run(tmp_path, ds)
    B1.run_baseline(p, run_dir, tmp_path / "o1", seed=11)
    B1.run_baseline(p, run_dir, tmp_path / "o2", seed=11)
    B1.run_baseline(p, run_dir, tmp_path / "o3", seed=12)
    f = lambda o: (tmp_path / o / "baseline_draws.csv").read_text()      # noqa: E731
    assert f("o1") == f("o2") and f("o1") != f("o3")


def test_a_pair_with_fewer_than_ten_filled_draws_is_dropped_and_counted(tmp_path):
    B1 = script("baseline_matched_random_near_52w_high")
    p, ds, _ = _lake_with_pool(tmp_path, n_names=9)                                   # a pool of 8 once the trade's own symbol is out: at most 8 draws
    run_dir, _ = _manual_run(tmp_path, ds)
    meta = B1.run_baseline(p, run_dir, tmp_path / "out", draws=20, min_filled=10, seed=1)
    assert meta["pairs_kept"] == 0 and meta["dropped_pairs"] == 1 and meta["share_dropped"] == 1.0
    assert meta["flag"] and "5%" in meta["flag"]                                       # more than 5% of trades lost their pair: flagged loudly


def test_the_baseline_reads_no_price_beyond_the_exit_and_the_twenty_session_horizon(tmp_path):
    B1 = script("baseline_matched_random_near_52w_high")
    p, ds, _ = _lake_with_pool(tmp_path)
    run_dir, t = _manual_run(tmp_path, ds, entry_idx=260)
    seen = []
    orig = B1.open_lake

    def traced(*a, **k):
        c = orig(*a, **k)
        c.set_trace_callback(seen.append)
        return c
    B1.open_lake = traced
    try:
        B1.run_baseline(p, run_dir, tmp_path / "out", seed=1)
    finally:
        B1.open_lake = orig
    iso = re.compile(r"\d{4}-\d{2}-\d{2}")
    prices = [s for s in seen if "market_data_lake" in s and "NIFTY50_INDEX" not in s]          # stock prices; the Nifty calendar query is bounded by the window end
    assert prices
    latest = max(d for s in prices for d in iso.findall(s))
    assert latest <= ds[261 + 40].isoformat(), latest         # the draws exit at session 300 (index 260 + 40); nothing in the last 20+ sessions of the window (to index 310) is read


def test_forward_returns_are_bounded_and_blank_across_a_split(tmp_path):
    B1 = script("baseline_matched_random_near_52w_high")
    series = {"S": L.rise(100, 0.001), "T": L.rise(100, 0.001)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"S": (265, 1, 5)})
    conn = open_lake(p)
    sessions = list(ds)
    ok = B1.forward_returns_bounded(conn, sessions, "T", ds[260], 100.0)
    truth = L.rise(100, 0.001)
    assert set(ok) == {"ret_1", "ret_5", "ret_10", "ret_20"}
    for h in (1, 5, 10, 20):                                                           # h sessions AFTER the entry session, from the fill price, raw closes
        assert ok[f"ret_{h}"] == pytest.approx((float(truth[260 + h]) / 100.0 - 1.0) * 100.0, rel=1e-9)
    split = B1.forward_returns_bounded(conn, sessions, "S", ds[260], 100.0)           # a split inside the 20 sessions: raw closes would show about -80%: blank instead
    assert all(np.isnan(v) for v in split.values())
    conn.close()


# ------------------------------------------------------------------------------------------------------------------------------------------ T1, T2, T3
@pytest.fixture(scope="module")
def baseline_null(tmp_path_factory):
    d = tmp_path_factory.mktemp("null")
    run = R.make_run(d / "run", months=130, per_month=6, mean_r=0.0, seed=11)
    R.make_baseline(d / "base", d / "run", edge_r=0.0, seed=12)
    return d, run


@pytest.fixture(scope="module")
def baseline_edge(tmp_path_factory):
    d = tmp_path_factory.mktemp("edge")
    run = R.make_run(d / "run", months=130, per_month=6, mean_r=0.0, seed=11)
    R.make_baseline(d / "base", d / "run", edge_r=0.5, seed=12)
    return d, run


def load_pairs(V, d):
    a = pd.read_csv(d / "base" / "actual_trades.csv")
    r = pd.read_csv(d / "base" / "baseline_draws.csv")
    return a, r, V.pair_table(a, r, min_filled=10)


def test_pairs_use_the_mean_of_the_draws_and_drop_short_pairs(tmp_path):
    V = script("validate_near_52w_high")
    run = R.make_run(tmp_path / "run", months=6, per_month=6, seed=1)
    R.make_baseline(tmp_path / "base", tmp_path / "run", short_pairs=4, seed=3)
    a, r, pairs = load_pairs(V, tmp_path)
    assert len(a) == 36 and len(pairs) == 32 and (pairs["n_draws"] >= 10).all()
    row = pairs.iloc[-1]
    assert row["rand_net_r"] == pytest.approx(r[r["matched_trade_id"] == row["unique_trade_id"]]["net_r"].mean())
    assert row["diff"] == pytest.approx(a[a["unique_trade_id"] == row["unique_trade_id"]]["net_r"].iloc[0] - row["rand_net_r"])


def test_the_monthly_series_sums_by_entry_month_and_keeps_empty_months_as_zero(tmp_path):
    V = script("validate_near_52w_high")
    pairs = pd.DataFrame({"unique_trade_id": ["a", "b", "c"], "entry_date": ["2016-01-04", "2016-01-20", "2016-03-02"], "diff": [1.0, 2.0, -0.5], "n_draws": [20, 20, 20]})
    s = V.monthly_series(pairs, date(2016, 1, 1), date(2016, 5, 31))
    assert list(s.index) == ["2016-01", "2016-02", "2016-03", "2016-04", "2016-05"] and s.tolist() == [3.0, 0.0, -0.5, 0.0, 0.0]
    full = V.monthly_series(pairs, date(2016, 1, 1), date(2026, 10, 16))
    assert len(full) == 130                                                           # 2016-01 to 2026-10: the 130 months of the registered window


def test_t1_is_significant_at_both_blocks_for_a_strong_edge_and_not_for_the_null(baseline_null, baseline_edge):
    V = script("validate_near_52w_high")
    for d, expect in ((baseline_edge[0], True), (baseline_null[0], False)):
        a, r, pairs = load_pairs(V, d)
        s = V.monthly_series(pairs, date(2016, 1, 1), date(2026, 10, 16))
        res = V.t1(s, blocks=(2, 3), B=2000, seed=20261111)
        assert set(res["blocks"]) == {2, 3} and res["dual_significant"] is expect and res["months"] == 130 and res["alpha"] == 0.05 and res["K"] == 1
        assert V.dual_significant(res) is expect
        for b in (2, 3):
            assert {"observed_mean", "standard_error", "observed_t", "unadjusted_p_value", "adjusted_p_value", "fwer_significant"} <= set(res["blocks"][b])


def test_the_dual_rule_needs_both_blocks():
    V = script("validate_near_52w_high")
    mk = lambda a, b: {"blocks": {2: {"fwer_significant": a}, 3: {"fwer_significant": b}}}   # noqa: E731
    assert V.dual_significant(mk(True, True)) is True
    assert V.dual_significant(mk(True, False)) is False and V.dual_significant(mk(False, True)) is False and V.dual_significant(mk(False, False)) is False


def test_t1_is_deterministic_for_a_seed(baseline_null):
    V = script("validate_near_52w_high")
    a, r, pairs = load_pairs(V, baseline_null[0])
    s = V.monthly_series(pairs, date(2016, 1, 1), date(2026, 10, 16))
    assert V.t1(s, B=1000, seed=5) == V.t1(s, B=1000, seed=5) and V.t1(s, B=1000, seed=5) != V.t1(s, B=1000, seed=6)


@pytest.mark.parametrize("size,verdict", [(0.0749, "size ok"), (0.075, "size ok"), (0.0751, "size unreliable"), (0.0249, "size unreliable"), (0.025, "size ok"), (0.0251, "size ok"), (0.0, "size unreliable")])
def test_the_placebo_size_limits_are_0_025_and_0_075_and_nobody_recalibrates(size, verdict):
    V = script("validate_near_52w_high")
    assert V.size_verdict(size) == verdict
    assert (V.SIZE_LOW, V.SIZE_HIGH) == (0.025, 0.075)


def test_the_placebo_check_runs_on_the_baseline_draws_alone_and_is_deterministic(baseline_null):
    V = script("validate_near_52w_high")
    a, r, pairs = load_pairs(V, baseline_null[0])
    p1 = V.placebo_size(r, pairs, date(2016, 1, 1), date(2026, 10, 16), reps=40, B=200, seed=20261111)
    p2 = V.placebo_size(r, pairs, date(2016, 1, 1), date(2026, 10, 16), reps=40, B=200, seed=20261111)
    assert p1 == p2 and 0.0 <= p1["size"] <= 1.0 and p1["reps"] == 40 and p1["se"] == pytest.approx(np.sqrt(p1["size"] * (1 - p1["size"]) / 40)) and p1["verdict"] in ("size ok", "size unreliable")


def test_the_registered_conclusion_is_never_phrased_as_no_edge():
    V = script("validate_near_52w_high")
    assert V.registered_conclusion(True, True) == "DEMONSTRATED (registered rule met)"
    for t1, g in ((True, False), (False, True), (False, False)):
        text = V.registered_conclusion(t1, g)
        assert text.startswith("NOT DEMONSTRATED") and "no edge" not in text.lower().replace("not evidence of no edge", "")


def test_the_validate_script_end_to_end_reads_no_database_and_marks_sub_periods_descriptive(baseline_null, tmp_path, monkeypatch):
    V = script("validate_near_52w_high")
    d, run = baseline_null

    def boom(*a, **k):
        raise AssertionError("the validation script must not open a database")
    monkeypatch.setattr(sqlite3, "connect", boom)
    out = tmp_path / "res.json"
    rc = V.main(["--run-dir", str(d / "run"), "--baseline-dir", str(d / "base"), "--out-json", str(out), "--boot", "500", "--placebo-reps", "20", "--placebo-boot", "100"])
    assert rc == 0
    res = json.loads(out.read_text())
    assert {"T1", "T2", "T3", "intervals", "descriptive", "counts", "conclusion_t1_only"} <= set(res)
    assert set(res["descriptive"]) == {"2016-2019", "2020-2026"} and all(v["descriptive"] is True for v in res["descriptive"].values())
    assert "met" not in json.dumps(res["descriptive"]) and "dual_significant" in res["T1"]
    assert res["T2"]["windows"].keys() >= {"2016-2019", "2020-2026", "Pooled"}
    assert res["counts"]["pairs"] == 780 and res["T3"]["reps"] == 20


# ------------------------------------------------------------------------------------------------------------------------------------------ the finalised spec and pre-registration text
SPEC_REF = "docs/strategies/near_52w_high/PREREGISTRATION.md"


def test_the_spec_names_its_preregistration_and_the_document_states_the_same_hashes():
    from dataclasses import asdict
    from stockbot.strategies.near_52w_high import SPEC
    from stockbot.validation.prereg_lock import gates_hash
    assert SPEC.prereg_ref == SPEC_REF and SPEC.validation_ref is None and SPEC.status == "research"
    text = (ROOT / SPEC_REF).read_text(encoding="utf-8")
    assert SPEC.config_hash() in text
    old = {("min_alpha_after_tax_pct" if k == "min_alpha_pct" else k): (-2.0 if k == "min_alpha_pct" else v) for k, v in asdict(CFG.validation_gates).items()}
    assert gates_hash(old) in text and "805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f" in text      # the registered result used the old key and value
    assert gates_hash(asdict(CFG.validation_gates)) not in text                                                         # the shared gates have since changed (shared-rules B2/B3)


def test_the_preregistration_is_final_and_carries_the_owner_decisions():
    text = (ROOT / SPEC_REF).read_text(encoding="utf-8")
    assert "PROPOSED" not in text and "DRAFT" not in text
    for needle in ("approved by the owner on 2026-11-11", "about 61%", "28% to 90%", "not demonstrated", "never \"no edge\"", "max_drawdown_pct | 20.0",
                   "paper_criteria.max_drawdown_pct stays 12.0", "can still fail 12% in paper", "TEST/TUNE labels", "does not touch the exploratory ledger", "Section 12"):
        assert needle in text, needle
    for needle in ("20261111", "m = 20", "at least 10", "0.075", "0.025", "B = 10,000", "blocks 2 and 3"):
        assert needle in text, needle


# ------------------------------------------------------------------------------------------------------------------------------------------ command lines
def test_the_command_lines_of_the_baseline_the_benchmark_and_the_gates_run_on_a_fixture_lake(tmp_path, capsys):
    B1, B2, G, V = (script(n) for n in ("baseline_matched_random_near_52w_high", "benchmark_nifty_matched_near_52w_high", "evaluate_validation_gates_near_52w_high", "validate_near_52w_high"))
    p, ds, _ = _lake_with_pool(tmp_path)
    run_dir, _ = _manual_run(tmp_path, ds)
    assert B1.main(["--lake", str(p), "--run-dir", str(run_dir), "--out-dir", str(tmp_path / "base"), "--no-hash"]) == 0
    meta = json.loads((tmp_path / "base" / "baseline_meta.json").read_text())
    assert meta["finsight_db"]["unchanged"] is True and meta["pairs_kept"] == 1 and meta["draws_per_trade"] == 20 and meta["seed"] == 20261111
    with pytest.raises(FileExistsError):
        B1.run_baseline(p, run_dir, tmp_path / "base")                                  # never writes into a used directory
    run2 = tmp_path / "run2"
    R.make_run(run2, months=3, per_month=4, start=ds[10], mean_r=0.3, seed=2)
    out_b2 = tmp_path / "b2.json"
    assert B2.main(["--run-dir", str(run2), "--lake", str(p), "--out-json", str(out_b2)]) == 0
    b2 = json.loads(out_b2.read_text())
    assert {"daily_share", "constant_share", "mean_invested_share"} <= set(b2) and b2["mean_invested_share"] == pytest.approx(0.78, abs=1e-9)
    R.make_baseline(tmp_path / "vbase", run2, edge_r=0.0, seed=4)
    assert (tmp_path / "vbase" / "actual_trades.csv").exists()
    res = tmp_path / "t1.json"
    t1 = {"T1": {"dual_significant": True}}
    res.write_text(json.dumps(t1))
    assert G.main(["--lake", str(p), "--run-dir", str(run2), "--out-json", str(tmp_path / "g2.json"), "--t1", str(res), "--boot", "200"]) == 0
    out = capsys.readouterr().out
    assert "registered conclusion:" in out and "max_drawdown_pct | <= 20.0" in out
    g = json.loads((tmp_path / "g2.json").read_text())
    assert g["registered_conclusion"].startswith(("DEMONSTRATED", "NOT DEMONSTRATED"))

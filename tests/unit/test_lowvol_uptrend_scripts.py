"""The lowvol_uptrend research, B1, B2 and gates scripts on FIXTURE lakes only (never finsight.db), the end-of-window rule, the equivalence of the strategy-side draw loop with the shared
helper, and the output layout scripts/validate_family.py reads for a family of ONE (--expect-k 1)."""
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.backtest.runner import run_backtest
from stockbot.config.shared import load_shared_config
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.data.sector_map import SectorLookup
from stockbot.engine.decide import EventData
from stockbot.engine.exit_policies.registry import policies_for, resolve
from stockbot.strategies.registry import StrategyRegistry
from stockbot.strategies.lowvol_uptrend import SPEC, LowVolUptrendStrategy, LvTrailingAtr3Floor8, register
from stockbot.strategies.lowvol_uptrend.indicators import atr_last
from stockbot.strategies.lowvol_uptrend.strategy import initial_stop
from stockbot.validation.random_baseline import draw_matched_random
from tests.fixtures import near_high_run_dir as R
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N = 420
S = 284                                   # first session of February 2020 on the fixture calendar
LAST = S + 45


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


RS, B1, B2, G, F = (script(n) for n in ("research_lowvol_uptrend", "baseline_matched_random_lowvol_uptrend", "benchmark_nifty_matched_lowvol_uptrend",
                                       "evaluate_validation_gates_lowvol_uptrend", "validate_family"))
GS = script("evaluate_validation_gates_near_52w_high")          # the shared evaluator that validate_family calls


@pytest.fixture(autouse=True)
def _default_view(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


def walk(seed, drift, sigma, n=N):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(drift + sigma * rng.standard_normal(n)))


def names():
    s = {f"CALM{k:02d}": walk(100 + k, 0.0015, 0.01) for k in range(16)}
    s.update({f"WILD{k:02d}": walk(200 + k, 0.004, 0.03) for k in range(16)})
    return s


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("ram") / "lake.db"
    ds = L.build(p, names(), n=N)
    return p, ds


def run_args(lake, out, *extra, end=LAST):
    p, ds = lake
    return ["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[end].isoformat(), "--out", str(out), *extra]


@pytest.fixture(scope="module")
def chain(lake, tmp_path_factory):
    root = tmp_path_factory.mktemp("ramc")
    member = root / "member"
    assert RS.main(run_args(lake, member / "run", "--execute")) == 0
    p, ds = lake
    assert B1.main(["--lake", str(p), "--run-dir", str(member / "run"), "--out-dir", str(member / "baseline"), "--no-hash"]) == 0
    return member


# ------------------------------------------------------------------------------------------------------------------ research wiring
@pytest.mark.parametrize("view", ["sql", "memory"])
def test_without_execute_it_prints_the_plan_and_runs_nothing(lake, tmp_path, capsys, monkeypatch, view):
    monkeypatch.setenv("STOCKBOT_VIEW", view)
    assert RS.main(run_args(lake, tmp_path / "o")) == 0 and not (tmp_path / "o").exists()
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan["strategy"] == "lowvol_uptrend" and plan["exit_policy"] == "lv_trailing_atr3_floor8" and plan["status"] == "research"
    assert plan["spec_config_hash"] == SPEC.config_hash() and len(plan["shared_config_hash"]) == 64 and plan["asof_view"] == view and "plan only" in cap.err


def test_execute_without_out_or_into_a_used_directory_is_refused(lake, tmp_path, capsys):
    p, ds = lake
    assert RS.main(["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[LAST].isoformat(), "--execute"]) == 2
    assert "--out is required" in capsys.readouterr().err
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "x").write_text("1")
    assert RS.main(run_args(lake, tmp_path / "used", "--execute")) == 2


def test_the_default_window_is_the_registered_one():
    ap = RS.build_parser().parse_args([])
    assert (ap.start, ap.end) == ("2016-01-01", "2026-10-16") and ap.execute is False


def test_the_run_passes_the_strategy_owned_policy_and_writes_the_registered_layout(chain):
    run = chain / "run"
    assert {"manifest.json", "trades.json", "equity_curve.json", "daily.json", "blocked.json"} == {f.name for f in run.iterdir()}
    m = json.loads((run / "manifest.json").read_text())
    assert m["asof_view"] == "sql" and list(m["strategies"]) == ["lowvol_uptrend"] and m["window"][1] and m["end_of_window"]["engine_reason"] == "END_OF_WINDOW"
    trades = json.loads((run / "trades.json").read_text())
    assert trades and all(t["exit_reason_engine"] in {"END_OF_WINDOW", "STOP_HIT"} and t["end_of_window"] == (t["exit_reason_engine"] == "END_OF_WINDOW") for t in trades)


# ------------------------------------------------------------------------------------------------------------------ the end-of-window rule
def test_positions_open_on_the_last_day_are_closed_at_the_last_close_and_counted(lake, chain):
    p, ds = lake
    trades = json.loads((chain / "run" / "trades.json").read_text())
    eow = [t for t in trades if t["end_of_window"]]
    assert len(eow) > 0                                                           # a rising fixture: the trailing stop never fires, so positions are open on the last day
    last = ds[LAST].isoformat()
    assert all(t["exit_date"] == last and t["exit_reason"] == "END_OF_WINDOW_COUNTED" and t["exit_reason_engine"] == "END_OF_WINDOW" for t in eow)
    assert json.loads((chain / "run" / "manifest.json").read_text())["end_of_window"]["trades"] == len(eow)
    # the relabel changes nothing but the label: same trades, same P&L as the engine's own run
    cfg = load_shared_config()
    reg = StrategyRegistry()
    register(reg)
    strat = LowVolUptrendStrategy(reg.get("lowvol_uptrend"))
    res = run_backtest(p, ds[S], ds[LAST], cfg.backtest.initial_equity, [strat], policies_for([strat.spec], extra=[LvTrailingAtr3Floor8()]), cfg, EventData(sectors=SectorLookup(), asm_ranges={}))
    assert [(t.position_id, t.exit_reason == "END_OF_WINDOW") for t in res.trades] == [(t["position_id"], t["end_of_window"]) for t in trades]
    assert [round(t.net_pnl, 6) for t in res.trades] == [round(t["net_pnl"], 6) for t in trades]
    e = eow[0]                                                                    # normal slippage and costs: exit at the last close x (1 - slippage), a sell cost paid
    slip = cfg.execution.exit_slippage_pct / 100.0
    price = float(names()[e["symbol"]][LAST]) * (1.0 - slip)
    assert e["gross_pnl"] == pytest.approx((price - e["entry_price"]) * e["shares_initial"], rel=1e-9)
    assert e["costs"] > 0 and e["net_pnl"] == pytest.approx(e["gross_pnl"] - e["costs"], rel=1e-9)


def test_the_shared_gates_count_those_trades_as_usable_and_the_riskadj_gates_report_them_separately(lake, chain, tmp_path):
    p, ds = lake
    trades = json.loads((chain / "run" / "trades.json").read_text())
    n_eow = sum(t["end_of_window"] for t in trades)
    nifty = B2.nifty_closes(p, ds[S], ds[LAST])
    gates = G.load_gates()
    mine = G.evaluate(chain / "run", nifty, gates, boot=100)
    shared = GS.evaluate(chain / "run", nifty, gates, boot=100)                   # what validate_family calls
    for res in (mine, shared):
        assert res["counts"]["usable"] == len(trades) and res["counts"]["closed"] == len(trades)
    assert mine["counts"]["end_of_window_counted_as_usable"] == n_eow and mine["counts"]["usable_closed_before_window_end"] == len(trades) - n_eow
    raw = [dict(t, exit_reason="END_OF_WINDOW") if t["end_of_window"] else t for t in trades]                  # with the engine's own label the shared code would have dropped them: the reason for the relabel
    d = tmp_path / "raw"
    d.mkdir()
    for f in ("manifest.json", "equity_curve.json", "daily.json"):
        (d / f).write_bytes((chain / "run" / f).read_bytes())
    (d / "trades.json").write_text(json.dumps(raw))
    assert GS.evaluate(d, nifty, gates, boot=100)["counts"]["usable"] == len(trades) - n_eow


def test_random_draws_open_at_the_window_end_are_closed_and_counted_as_filled(chain):
    meta = json.loads((chain / "baseline" / "baseline_meta.json").read_text())
    d = pd.read_csv(chain / "baseline" / "baseline_draws.csv")
    assert meta["end_of_window_draws"] == int(d["end_of_window"].sum()) > 0 and set(d.loc[d["end_of_window"], "exit_reason"]) == {"END_OF_WINDOW"}
    assert meta["draws_closed_before_window_end"] == len(d) - meta["end_of_window_draws"] and meta["draws_total"] == len(d)
    assert meta["end_of_window_trades"] == json.loads((chain / "run" / "manifest.json").read_text())["end_of_window"]["trades"]
    assert "OPEN_AT_END" not in meta["unfilled"] and meta["pairs_kept"] > 0


# ------------------------------------------------------------------------------------------------------------------ the baseline rule
def test_every_random_entry_has_its_own_atr_stop_and_exit_policy(lake, chain):
    p, ds = lake
    d = pd.read_csv(chain / "baseline" / "baseline_draws.csv")
    rel = []
    conn = open_lake(p)
    try:
        for r in d.head(60).itertuples(index=False):
            sig = max(x for x in ds if x < pd.Timestamp(r.entry_date).date())
            view = AsOfView(conn, sig)
            bars = view.adjusted_bars(r.symbol, lookback=252)
            atr = atr_last(bars, 14)
            expect, dist = initial_stop(float(bars["close_adj"].iloc[-1]), atr, SPEC.params)
            assert r.stop == pytest.approx(expect, rel=1e-9)
            rel.append(dist / float(bars["close_adj"].iloc[-1]))
    finally:
        conn.close()
    assert min(rel) >= 0.08 - 1e-12 and max(rel) > 0.09                                 # both branches occur: the 8% floor and the 3 x ATR
    assert len(set(round(x, 4) for x in rel)) > 3                                       # not one relative distance for every draw (the shared helper would give one per trade)
    assert set(d["exit_reason"]) <= {"STOP_HIT", "END_OF_WINDOW"}


def test_the_baseline_defaults_are_the_registered_ones():
    assert (B1.DRAWS, B1.MIN_FILLED, B1.SEED) == (20, 10, 20261111)


# ------------------------------------------------------------------------------------------------------------------ equivalence with the shared helper
@pytest.fixture(scope="module")
def eq_lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("eq") / "lake.db"
    series = {f"E{k:02d}": walk(300 + k, 0.001, 0.02) for k in range(14)}
    for k in (0, 1, 2):
        series[f"E{k:02d}"][S + 12:] = series[f"E{k:02d}"][S + 12] * 0.6                # a fall: the trailing stop fires inside the lake for these
    ds = L.build(p, series, n=N)
    return p, ds


def actual_frame(ds):
    return pd.DataFrame([{"unique_trade_id": f"t{i}", "symbol": f"E{i:02d}", "entry_date": ds[S + 1 + i], "entry_price": 100.0, "stop": 90.0 - i, "window": "all"} for i in range(4)])


def common(eq_lake, policy, **kw):
    p, ds = eq_lake
    cfg = load_shared_config()
    conn = open_lake(p)
    try:
        sess = [d for d in ds if d <= ds[S + 30]]
        view_at = lambda day: AsOfView(conn, day)  # noqa: E731
        a = actual_frame(ds)
        shared = draw_matched_random(a, sessions=sess, view_at=view_at, shared_config=cfg, policy=policy, equity=cfg.backtest.initial_equity, draws_per_trade=5, seed=20261111)
        own = B1.draw_matched_random_own(a, sessions=sess, view_at=view_at, shared_config=cfg, policy=policy, equity=cfg.backtest.initial_equity, draws_per_trade=5, seed=20261111, **kw)
        return shared, own
    finally:
        conn.close()


def test_the_loop_reproduces_the_shared_helper_exactly_with_the_shared_stop_rule_and_a_policy_that_closes(eq_lake):
    shared, own = common(eq_lake, resolve("fixed_hold_5"), stop_rule=B1.shared_relative_stop, close_at_end=False)
    assert len(shared) > 10 and shared.attrs["unfilled"] == own.attrs["unfilled"]
    pd.testing.assert_frame_equal(shared.reset_index(drop=True), own.reset_index(drop=True), check_exact=True)


def test_the_loop_reproduces_the_shared_helper_with_the_strategy_policy_and_end_closure_off_and_only_adds_rows_with_it_on(eq_lake):
    shared, off = common(eq_lake, LvTrailingAtr3Floor8(), stop_rule=B1.shared_relative_stop, close_at_end=False)
    pd.testing.assert_frame_equal(shared.reset_index(drop=True), off.reset_index(drop=True), check_exact=True)
    assert shared.attrs["unfilled"].get("OPEN_AT_END", 0) > 0                                 # the situation the new rule is about
    _, on = common(eq_lake, LvTrailingAtr3Floor8(), stop_rule=B1.shared_relative_stop, close_at_end=True)
    closed = on[on["exit_reason"] != "END_OF_WINDOW"]
    pd.testing.assert_frame_equal(shared.reset_index(drop=True), closed.reset_index(drop=True), check_exact=True)   # same draws, same random stream, nothing else changed
    assert len(on) - len(closed) == shared.attrs["unfilled"]["OPEN_AT_END"] and (on["exit_reason"] == "END_OF_WINDOW").sum() == shared.attrs["unfilled"]["OPEN_AT_END"]


# ------------------------------------------------------------------------------------------------------------------ views, B2, gates, layout
def test_the_outputs_are_identical_under_the_sql_and_the_memory_view(lake, chain, tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    p, ds = lake
    assert RS.main(run_args(lake, tmp_path / "run", "--execute")) == 0
    assert B1.main(["--lake", str(p), "--run-dir", str(tmp_path / "run"), "--out-dir", str(tmp_path / "baseline"), "--no-hash"]) == 0
    for f in ("trades.json", "equity_curve.json", "daily.json", "blocked.json"):
        assert (chain / "run" / f).read_bytes() == (tmp_path / "run" / f).read_bytes(), f
    for f in ("actual_trades.csv", "baseline_draws.csv"):
        assert (chain / "baseline" / f).read_bytes() == (tmp_path / "baseline" / f).read_bytes(), f
    a, b = (json.loads((x / "run" / "manifest.json").read_text()) for x in (chain, tmp_path))
    assert (a["asof_view"], b["asof_view"]) == ("sql", "memory")
    ma, mb = (json.loads((x / "baseline" / "baseline_meta.json").read_text()) for x in (chain, tmp_path))
    assert (ma["asof_view"], mb["asof_view"]) == ("sql", "memory") and {k: v for k, v in ma.items() if k not in ("asof_view", "finsight_db")} == {k: v for k, v in mb.items() if k not in ("asof_view", "finsight_db")}


def test_the_benchmark_and_the_gates_run_from_the_run_directory(lake, chain, tmp_path, capsys):
    p, ds = lake
    assert B2.main(["--run-dir", str(chain / "run"), "--lake", str(p), "--out-json", str(tmp_path / "b2.json")]) == 0
    assert {"daily_share", "constant_share", "gate_alpha_pct", "asof_view"} <= set(json.loads((tmp_path / "b2.json").read_text()))
    assert G.main(["--run-dir", str(chain / "run"), "--lake", str(p), "--out-json", str(tmp_path / "g.json"), "--boot", "100", "--baseline-dir", str(chain / "baseline")]) == 0
    g = json.loads((tmp_path / "g.json").read_text())
    assert [r["gate"] for r in g["gates"]] == list(G.GATE_ORDER) and g["gate_alpha_is_pre_tax"] is True
    meta = json.loads((chain / "baseline" / "baseline_meta.json").read_text())
    assert g["counts"]["baseline_end_of_window_draws"] == meta["end_of_window_draws"] and g["counts"]["end_of_window_counted_as_usable"] == meta["end_of_window_trades"]


def test_validate_family_loads_the_script_outputs_as_a_member(chain):
    m = F.load_member("lowvol_uptrend", chain)
    assert len(m["actual"]) > 0 and len(m["draws"]) > 0 and len(m["pairs"]) > 0
    assert len(m["actual"]) == len(json.loads((chain / "run" / "trades.json").read_text()))       # end-of-window trades are in the T1/T2 inputs
    with pytest.raises(ValueError, match="not the strategy"):
        F.load_member("pullback_uptrend", chain)


def test_validate_family_dry_run_on_a_family_of_one_with_expect_k_1(tmp_path):
    """A fixture family of ONE (the fixture lake has too few months for a real run: the Max-T bootstrap needs at least 10), same files and columns as the script outputs, with
    END_OF_WINDOW trades among the usable ones."""
    d = tmp_path / "lowvol_uptrend"
    R.make_run(d / "run", months=60, per_month=3, mean_r=0.3, seed=21, extra_end_of_window=3)
    R.make_baseline(d / "baseline", d / "run", edge_r=0.0, m=12, seed=71)
    mf = json.loads((d / "run" / "manifest.json").read_text())
    mf["strategies"] = {"lowvol_uptrend": {"exit_policy": "lv_trailing_atr3_floor8"}}
    mf["asof_view"] = "memory"
    (d / "run" / "manifest.json").write_text(json.dumps(mf))
    out = tmp_path / "fam.json"
    argv = ["--member", f"lowvol_uptrend={d}", "--out-json", str(out), "--boot", "200", "--placebo-reps", "3", "--placebo-boot", "50", "--expect-k", "1"]
    assert F.main(argv) == 0
    res = json.loads(out.read_text())
    assert res["K"] == 1 and res["members"] == ["lowvol_uptrend"] and res["T1"]["seed"] == 20261111 and res["T1"]["B"] == 200 and set(res["T1"]["blocks"]) == {"2", "3"}
    assert res["T1"]["correction"].startswith("Westfall-Young") and "lowvol_uptrend" in res["T1"]["members"]
    with pytest.raises(SystemExit):
        F.main(argv[:-2] + ["--expect-k", "2"])                                                   # one member given, two expected
    with pytest.raises(SystemExit):
        F.main(argv[:-2] + ["--expect-k", "0"])


def test_the_layout_matches_the_synthetic_members_of_the_family_tests(chain, tmp_path):
    synth = tmp_path / "synth"
    R.make_run(synth / "run", months=6, per_month=3, seed=3)
    R.make_baseline(synth / "baseline", synth / "run", edge_r=0.0, seed=4)
    assert {f.name for f in (synth / "run").iterdir()} - {"blocked.json"} <= {f.name for f in (chain / "run").iterdir()}
    for csv in ("actual_trades.csv", "baseline_draws.csv"):
        assert set(pd.read_csv(synth / "baseline" / csv).columns) <= set(pd.read_csv(chain / "baseline" / csv).columns), csv
    assert set(json.loads((synth / "run" / "trades.json").read_text())[0]) <= set(json.loads((chain / "run" / "trades.json").read_text())[0])


def test_the_baseline_never_writes_into_a_used_directory(lake, chain):
    p, ds = lake
    with pytest.raises(FileExistsError):
        B1.run_baseline(p, chain / "run", chain / "baseline")


def test_the_manifest_carries_the_symbol_links_and_stale_exit_blocks_and_the_baseline_counts_stale_draws(chain):
    m = json.loads((chain / "run" / "manifest.json").read_text())
    assert "symbol_links" in m and "stale_exit" in m and m["asof_view"] == "sql"
    meta = json.loads((chain / "baseline" / "baseline_meta.json").read_text())
    assert meta["stale_exit_draws"] == 0 and meta["policy"] == "lv_trailing_atr3_floor8"
    assert meta["spec_config_hash"] == SPEC.config_hash()

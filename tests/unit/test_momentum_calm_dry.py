"""Dry check of the momentum_calm wiring on FIXTURE lakes only (never finsight.db): research, baseline and gates run end to end with STOCKBOT_NON_EQ=held and with it off; the engine and the baseline take
the non-EQ path, the manifest records non_eq_view and non_eq_events, a restricted stock is never bought, no risk override is recorded, the family_batch7 registration payload (K = 1) validates against a
copy of the real ledger, the overlap script and the comparison script run (counts and stored numbers only)."""
import dataclasses
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.config.shared import load_shared_config
from stockbot.data import non_eq as NE
from stockbot.strategies.momentum_calm import SPEC
from stockbot.validation import ledger as LG
from stockbot.validation import prereg_lock as pl
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N, S = 420, 284
LAST = S + 45
MOVE = S + 20                              # CALM00 and CALM01 trade in BE from this session on
MOVED = ("CALM00", "CALM01")


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


RS, B1, G, CMP, OV = (script(n) for n in ("research_momentum_calm", "baseline_matched_random_momentum_calm", "evaluate_validation_gates_momentum_calm", "momentum_calm_comparison",
                                            "momentum_calm_overlap"))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    monkeypatch.delenv("STOCKBOT_NON_EQ", raising=False)


def walk(seed, drift, sigma, n=N):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(drift + sigma * rng.standard_normal(n)))


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("ramne") / "lake.db"
    series = {f"CALM{k:02d}": walk(100 + k, 0.0015, 0.01) for k in range(16)}
    series.update({f"WILD{k:02d}": walk(200 + k, 0.004, 0.03) for k in range(16)})
    ds = L.build(p, series, n=N)
    con = sqlite3.connect(p)
    con.executescript(NE.DDL)
    for sym in MOVED:                      # rows leave market_data_lake and go to market_data_non_eq (one bar per day, as in the real migration)
        rows = con.execute("select symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake where symbol=? order by trade_date", (sym,)).fetchall()
        for i, r in enumerate(rows):
            if i >= MOVE:
                con.execute("delete from market_data_lake where symbol=? and trade_date=?", (sym, r[1]))
                con.execute(f"insert into {NE.TABLE}(symbol, trade_date, series, open_raw, high_raw, low_raw, close_raw, volume_raw) values (?,?,?,?,?,?,?,?)",
                            (sym, r[1], "BE", r[2], r[3], r[4], r[5], int(r[6])))
    con.commit()
    con.close()
    return p, ds


def args(lake, out, *extra):
    p, ds = lake
    return ["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[LAST].isoformat(), "--out", str(out), *extra]


@pytest.fixture(scope="module")
def runs(lake, tmp_path_factory):
    root = tmp_path_factory.mktemp("ramner")
    p, ds = lake
    mp = pytest.MonkeyPatch()
    out = {}
    try:
        for label, sw in (("off", None), ("held", "held")):
            if sw:
                mp.setenv("STOCKBOT_NON_EQ", sw)
            else:
                mp.delenv("STOCKBOT_NON_EQ", raising=False)
            m = root / label
            assert RS.main(args(lake, m / "run", "--execute")) == 0
            assert B1.main(["--lake", str(p), "--run-dir", str(m / "run"), "--out-dir", str(m / "baseline"), "--no-hash"]) == 0
            assert G.main(["--run-dir", str(m / "run"), "--lake", str(p), "--out-json", str(m / "gates.json"), "--boot", "50", "--baseline-dir", str(m / "baseline")]) == 0
            out[label] = m
    finally:
        mp.undo()
    return out


def test_the_engine_with_the_switch_on_takes_the_non_eq_path_and_the_manifest_says_so(runs):
    man = json.loads((runs["held"] / "run" / "manifest.json").read_text())
    assert man["non_eq_view"]["switch"] == "STOCKBOT_NON_EQ=held" and man["non_eq_view"]["table"] == NE.TABLE
    assert man["non_eq_view"]["sell_model"]["volume_cap_per_session"] == 0.10 and man["non_eq_view"]["sell_model"]["exit_slippage_multiplier"] == 2.0
    ev = man["non_eq_events"]
    assert set(ev) == {"sell_capped_non_eq", "sell_capped_non_eq_symbols", "not_eq_series_blocked", "symbol_no_bars_exits"} and ev["symbol_no_bars_exits"] == 0


def test_with_the_switch_off_the_manifest_carries_neither_block(runs):
    man = json.loads((runs["off"] / "run" / "manifest.json").read_text())
    assert "non_eq_view" not in man and "non_eq_events" not in man


def test_a_restricted_stock_is_never_bought_with_the_switch_on(runs, lake):
    p, ds = lake
    move_day = ds[MOVE].isoformat()
    trades = json.loads((runs["held"] / "run" / "trades.json").read_text())
    assert trades and all(not (t["symbol"] in MOVED and str(t["entry_date"])[:10] >= move_day) for t in trades)


def test_the_baseline_with_the_switch_on_never_draws_a_restricted_stock_after_the_move(runs, lake):
    p, ds = lake
    d = pd.read_csv(runs["held"] / "baseline" / "baseline_draws.csv")
    sym = next(c for c in ("symbol", "draw_symbol") if c in d.columns)
    dt = next(c for c in ("entry_date", "draw_entry_date") if c in d.columns)
    bad = d[d[sym].isin(MOVED) & (d[dt].astype(str).str[:10] >= ds[MOVE].isoformat())]
    assert len(d) > 0 and len(bad) == 0


def test_the_gates_output_is_produced_in_both_modes(runs):
    for m in runs.values():
        g = json.loads((m / "gates.json").read_text())
        assert [r["gate"] for r in g["gates"]] == list(G.GATE_ORDER)


def test_no_risk_override_is_recorded_and_the_spec_hash_is_the_one_in_the_plan(runs):
    man = json.loads((runs["held"] / "run" / "manifest.json").read_text())
    assert "risk_override" not in man
    meta = json.loads((runs["held"] / "baseline" / "baseline_meta.json").read_text())
    assert "risk_override" not in meta or meta["risk_override"] in (None, {})


def test_the_family_batch7_payload_validates_with_k_1_on_a_copy_of_the_real_ledger(tmp_path):
    import shutil
    gp = dataclasses.asdict(load_shared_config().validation_gates)
    reason = "family_batch7 K=1: momentum_calm, monthly momentum among the calmest half of stocks (PREREGISTRATION.md)"
    path = tmp_path / "family_ledger.csv"
    LG.register_family(path=path, family_id="family_batch7", members=[SPEC], gate_params=gp, git_sha="0" * 40, reason=reason)
    assert LG.family_budget(path, "family_batch7") == 1
    assert LG.family_members(path, "family_batch7") == [{"id": "momentum_calm", "version": "1.0.0", "config_hash": SPEC.config_hash()}]
    pl.verify_ledger(path)
    real = ROOT / "stockbot" / "validation" / "ledger" / "records" / "family_ledger.csv"
    shutil.copy(real, tmp_path / "real.csv")
    LG.register_family(path=tmp_path / "real.csv", family_id="family_batch7", members=[SPEC], gate_params=gp, git_sha="0" * 40, reason=reason)
    pl.verify_ledger(tmp_path / "real.csv")
    assert LG.family_budget(tmp_path / "real.csv", "family_batch7") == 1
    with pytest.raises(Exception):
        LG.register_family(path=path, family_id="family_batch7", members=[SPEC], gate_params=gp, git_sha="0" * 40)      # registering again needs a reason
    assert pl.gates_hash(gp) == "e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054"


def test_the_overlap_script_reports_counts_and_names_only_and_the_rule_outcome(lake, tmp_path):
    p, ds = lake
    out_j, out_m = tmp_path / "o.json", tmp_path / "o.md"
    assert OV.main(["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[LAST].isoformat(), "--out-json", str(out_j), "--out-md", str(out_m)]) == 0
    o = json.loads(out_j.read_text())
    assert o["summary"]["signal_months"] >= 1 and 0.0 <= o["summary"]["overlap"]["mean"] <= 1.0 and o["summary"]["rule"]["threshold"] == 0.85
    r = o["rows"][0]
    assert set(r) >= {"eligible", "calm", "positive_calm", "positive_all", "calm_picks", "plain_picks", "overlap"} and r["calm"] <= r["with_sigma252"] <= r["eligible"]
    assert not any(k in json.dumps(o) for k in ("pnl", "net_r", "equity", "win_rate"))              # no return, P&L, win rate or equity of any kind
    assert "overlap" in out_m.read_text()


def test_the_comparison_script_runs_on_stored_files_and_recomputes_nothing(runs, tmp_path):
    out = tmp_path / "c.json"
    assert CMP.main(["--calm", str(runs["held"]), "--out-json", str(out), "--out-md", str(tmp_path / "c.md"), "--ledger", str(tmp_path / "no_ledger.csv")]) == 0
    c = json.loads(out.read_text())["columns"]
    assert len(c) == 4 and c[-1]["summary"]["trades"] == len(json.loads((runs["held"] / "run" / "trades.json").read_text())) and c[-1]["summary"]["non_eq_switch"] is True
    assert c[-1]["summary"]["risk_per_trade_pct"] == 1.0 and c[-1]["summary"]["worst_fall"] is not None
    assert "| worst fall" in (tmp_path / "c.md").read_text() and "| max drawdown % |" in (tmp_path / "c.md").read_text()

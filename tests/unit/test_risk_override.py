"""The per-run risk override (STOCKBOT_RISK_PCT, family_batch6): default OFF changes nothing; 0.5 halves the position size and risk amount; the baseline sizes its draws with it and refuses a
different value than the run's; paper/live refuse it; validate_family refuses a mixed pair; both riskadj members run end to end with the override and STOCKBOT_NON_EQ=held on a FIXTURE lake;
the family_batch6 payload (K = 2) validates. Never opens finsight.db."""
import dataclasses
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockbot.config import risk_override as RO
from stockbot.config.shared import load_shared_config
from stockbot.data import non_eq as NE
from stockbot.risk.sizing import size_position
from stockbot.strategies.riskadj_momentum import SPEC as SPEC_M
from stockbot.strategies.riskadj_momentum_daily import SPEC as SPEC_D
from stockbot.validation import ledger as LG
from stockbot.validation import prereg_lock as pl
from tests.fixtures import near_high_run_dir as R
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
N, S = 420, 284
LAST = S + 45
MOVE = S + 20


def script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


RSM, RSD, B1M, B1D, GM, GD, F = (script(n) for n in ("research_riskadj_momentum", "research_riskadj_momentum_daily", "baseline_matched_random_riskadj_momentum",
                                                      "baseline_matched_random_riskadj_momentum_daily", "evaluate_validation_gates_riskadj_momentum",
                                                      "evaluate_validation_gates_riskadj_momentum_daily", "validate_family"))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (RO.ENV, "STOCKBOT_VIEW", "STOCKBOT_NON_EQ"):
        monkeypatch.delenv(k, raising=False)


# ------------------------------------------------------------------------------------------------------------------ the module
def test_off_changes_nothing_and_writes_no_block():
    cfg = load_shared_config()
    assert RO.override_value() is None and RO.apply(cfg) is cfg and RO.block(cfg) is None
    assert cfg.portfolio_risk.max_loss_pct_per_trade == 1.0


@pytest.mark.parametrize("raw", ["0.05", "1.01", "2", "-0.5", "abc", "nan", "inf"])
def test_values_outside_0_1_to_1_0_are_refused(monkeypatch, raw):
    monkeypatch.setenv(RO.ENV, raw)
    with pytest.raises(RO.RiskOverrideError):
        RO.override_value()


@pytest.mark.parametrize("raw,v", [("0.1", 0.1), ("0.5", 0.5), ("1.0", 1.0), (" 0.5 ", 0.5)])
def test_accepted_values_replace_only_the_one_number_and_the_value_is_printed(monkeypatch, capsys, raw, v):
    monkeypatch.setenv(RO.ENV, raw)
    cfg = load_shared_config()
    new = RO.apply(cfg)
    assert new.portfolio_risk.max_loss_pct_per_trade == v and new.portfolio_risk.max_concurrent_positions == cfg.portfolio_risk.max_concurrent_positions
    assert new.costs == cfg.costs and new.validation_gates == cfg.validation_gates and new.execution == cfg.execution and cfg.portfolio_risk.max_loss_pct_per_trade == 1.0
    assert f"max_loss_pct_per_trade = {v}" in capsys.readouterr().err
    assert RO.block(cfg) == {**RO.block(cfg), "max_loss_pct_per_trade": v, "base_max_loss_pct_per_trade": 1.0}


def test_the_manifest_config_hash_follows_the_value_in_use_and_the_gates_hash_does_not_move(monkeypatch):
    from stockbot.backtest.manifest import shared_config_hash
    cfg = load_shared_config()
    monkeypatch.setenv(RO.ENV, "0.5")
    on = RO.apply(cfg)
    assert shared_config_hash(cfg) != shared_config_hash(on)
    assert pl.gates_hash(dataclasses.asdict(on.validation_gates)) == pl.gates_hash(dataclasses.asdict(cfg.validation_gates)) == "e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054"
    assert shared_config_hash(cfg) == "da459624294741239ae85230317da357b5b141a62b81f897bfb3d0745e956248"


def test_sizing_halves_with_half_the_risk():
    one = size_position(equity=1_000_000, risk_pct=1.0, entry=100.0, stop=90.0)
    half = size_position(equity=1_000_000, risk_pct=0.5, entry=100.0, stop=90.0)
    assert half.shares * 2 == pytest.approx(one.shares, abs=1.0) and half.risk_amount * 2 == pytest.approx(one.risk_amount, rel=0.01) and half.position_value * 2 == pytest.approx(one.position_value, rel=0.01)


# ------------------------------------------------------------------------------------------------------------------ paper and live refuse
def test_paper_and_live_refuse_the_override(monkeypatch, capsys):
    from stockbot.live import eod_cli
    from stockbot.live.runner import ModeError, default_book, run_eod
    monkeypatch.setenv(RO.ENV, "0.5")
    with pytest.raises(ModeError, match="paper and live mode refuse"):
        run_eod(cfg=load_shared_config(), book=default_book(), mode="PAPER")
    with pytest.raises(ModeError):
        run_eod(cfg=load_shared_config(), book=default_book(), mode="LIVE")
    assert eod_cli.main(["--date", "2026-01-02"], book=default_book()) == 2 and "REFUSED" in capsys.readouterr().out
    with pytest.raises(RO.RiskOverrideError):
        RO.refuse_in_paper_live()
    monkeypatch.delenv(RO.ENV)
    RO.refuse_in_paper_live()                                                     # off: nothing happens


# ------------------------------------------------------------------------------------------------------------------ fixtures
def walk(seed, drift, sigma, n=N):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(drift + sigma * rng.standard_normal(n)))


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("rolake") / "lake.db"
    series = {f"CALM{k:02d}": walk(100 + k, 0.0015, 0.01) for k in range(16)}
    series.update({f"WILD{k:02d}": walk(200 + k, 0.004, 0.03) for k in range(16)})
    ds = L.build(p, series, n=N)
    con = sqlite3.connect(p)
    con.executescript(NE.DDL)
    for sym in ("CALM00",):
        rows = con.execute("select symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake where symbol=? order by trade_date", (sym,)).fetchall()
        for i, r in enumerate(rows):
            if i >= MOVE:
                con.execute("delete from market_data_lake where symbol=? and trade_date=?", (sym, r[1]))
                con.execute(f"insert into {NE.TABLE}(symbol, trade_date, series, open_raw, high_raw, low_raw, close_raw, volume_raw) values (?,?,?,?,?,?,?,?)", (sym, r[1], "BE", r[2], r[3], r[4], r[5], int(r[6])))
    con.commit()
    con.close()
    return p, ds


def args(lake, out, *extra):
    p, ds = lake
    return ["--lake", str(p), "--start", ds[S].isoformat(), "--end", ds[LAST].isoformat(), "--out", str(out), *extra]


def run_member(lake, root, label, RS, B1, G, mp, *, risk, switch=True):
    p, ds = lake
    if risk is None:
        mp.delenv(RO.ENV, raising=False)
    else:
        mp.setenv(RO.ENV, str(risk))
    if switch:
        mp.setenv("STOCKBOT_NON_EQ", "held")
    else:
        mp.delenv("STOCKBOT_NON_EQ", raising=False)
    m = root / label
    assert RS.main(args(lake, m / "run", "--execute")) == 0
    assert B1.main(["--lake", str(p), "--run-dir", str(m / "run"), "--out-dir", str(m / "baseline"), "--no-hash"]) == 0
    assert G.main(["--run-dir", str(m / "run"), "--lake", str(p), "--out-json", str(m / "gates.json"), "--boot", "50", "--baseline-dir", str(m / "baseline")]) == 0
    return m


@pytest.fixture(scope="module")
def runs(lake, tmp_path_factory):
    root = tmp_path_factory.mktemp("rorun")
    mp = pytest.MonkeyPatch()
    out = {}
    try:
        for key, (lab, RS, B1, G) in {"m": ("monthly", RSM, B1M, GM), "d": ("daily", RSD, B1D, GD)}.items():
            out[key + "_off"] = run_member(lake, root, lab + "_off", RS, B1, G, mp, risk=None, switch=False)
            out[key + "_half"] = run_member(lake, root, lab + "_half", RS, B1, G, mp, risk=0.5, switch=True)
    finally:
        mp.undo()
    return out


def man(m):
    return json.loads((m / "run" / "manifest.json").read_text())


@pytest.mark.parametrize("key", ["m", "d"])
def test_off_writes_no_override_block_anywhere(runs, key):
    m = runs[key + "_off"]
    assert "risk_override" not in man(m) and "non_eq_view" not in man(m)
    assert "risk_override" not in json.loads((m / "baseline" / "baseline_meta.json").read_text())


@pytest.mark.parametrize("key", ["m", "d"])
def test_on_records_the_override_and_the_switch_in_the_manifest_and_the_baseline_meta(runs, key):
    m = runs[key + "_half"]
    ro = man(m)["risk_override"]
    assert ro["max_loss_pct_per_trade"] == 0.5 and ro["base_max_loss_pct_per_trade"] == 1.0 and man(m)["non_eq_view"]["switch"] == "STOCKBOT_NON_EQ=held"
    assert man(m)["shared_config_hash"] != man(runs[key + "_off"])["shared_config_hash"]
    assert json.loads((m / "baseline" / "baseline_meta.json").read_text())["risk_override"]["max_loss_pct_per_trade"] == 0.5


@pytest.mark.parametrize("key", ["m", "d"])
def test_half_risk_halves_the_risk_amount_and_the_position_of_the_first_common_trade(runs, key):
    off = {(t["symbol"], t["entry_date"]): t for t in json.loads((runs[key + "_off"] / "run" / "trades.json").read_text())}
    on = json.loads((runs[key + "_half"] / "run" / "trades.json").read_text())
    common = [(off[(t["symbol"], t["entry_date"])], t) for t in on if (t["symbol"], t["entry_date"]) in off]
    assert common
    o, h = common[0]
    assert h["risk_inr"] == pytest.approx(o["risk_inr"] / 2, rel=0.03) and h["shares_initial"] == pytest.approx(o["shares_initial"] / 2, rel=0.03)
    assert max(t["risk_inr"] for t in off.values()) / max(t["risk_inr"] for t in on) == pytest.approx(2.0, rel=0.15)           # equity moves a little, so the bound is the ratio of the largest risks, not 5,000 exactly


@pytest.mark.parametrize("key,B1", [("m", B1M), ("d", B1D)])
def test_the_baseline_draws_are_sized_with_the_override_and_a_different_value_is_refused(runs, lake, tmp_path, monkeypatch, key, B1):
    p, ds = lake
    seen = []
    real = B1.fill_ticket
    monkeypatch.setattr(B1, "fill_ticket", lambda *a, **k: (seen.append(k["risk_pct"]), real(*a, **k))[1])         # what risk_pct every random draw is sized with
    monkeypatch.setenv(RO.ENV, "0.5")
    assert B1.main(["--lake", str(p), "--run-dir", str(runs[key + "_half"] / "run"), "--out-dir", str(tmp_path / "b_on"), "--no-hash"]) == 0
    assert seen and set(seen) == {0.5}
    seen.clear()
    monkeypatch.delenv(RO.ENV)
    assert B1.main(["--lake", str(p), "--run-dir", str(runs[key + "_off"] / "run"), "--out-dir", str(tmp_path / "b_off"), "--no-hash"]) == 0
    assert seen and set(seen) == {1.0}
    monkeypatch.delenv(RO.ENV, raising=False)                                      # the run had 0.5, this baseline sees none
    with pytest.raises(RO.RiskOverrideError, match="same value as the run"):
        B1.main(["--lake", str(p), "--run-dir", str(runs[key + "_half"] / "run"), "--out-dir", str(tmp_path / "b1"), "--no-hash"])
    monkeypatch.setenv(RO.ENV, "0.5")                                              # the run had none, this baseline sees 0.5
    with pytest.raises(RO.RiskOverrideError):
        B1.main(["--lake", str(p), "--run-dir", str(runs[key + "_off"] / "run"), "--out-dir", str(tmp_path / "b2"), "--no-hash"])


@pytest.mark.parametrize("key", ["m", "d"])
def test_the_gates_script_reports_the_implied_return_with_the_override(runs, key):
    g = json.loads((runs[key + "_half"] / "gates.json").read_text())
    assert g["implied_annual_return"]["max_loss_pct_per_trade"] == 0.5
    assert json.loads((runs[key + "_off"] / "gates.json").read_text())["implied_annual_return"]["max_loss_pct_per_trade"] == 1.0


# ------------------------------------------------------------------------------------------------------------------ validate_family: same override, K = 2
def synthetic_member(root, label, override, seed):
    d = root / label
    R.make_run(d / "run", months=60, per_month=3, mean_r=0.2, seed=seed)
    R.make_baseline(d / "baseline", d / "run", edge_r=0.0, m=12, seed=seed + 50)
    mf = json.loads((d / "run" / "manifest.json").read_text())
    mf["strategies"] = {label: {}}
    if override is not None:
        mf["risk_override"] = {"max_loss_pct_per_trade": override}
    (d / "run" / "manifest.json").write_text(json.dumps(mf))
    return d


def test_validate_family_refuses_a_mixed_pair_and_accepts_two_equal_overrides_with_expect_k_2(tmp_path):
    a = synthetic_member(tmp_path, "riskadj_momentum", 0.5, 1)
    b = synthetic_member(tmp_path, "riskadj_momentum_daily", 0.5, 2)
    c = synthetic_member(tmp_path / "mix", "riskadj_momentum_daily", None, 3)
    base = ["--boot", "200", "--placebo-reps", "3", "--placebo-boot", "50", "--expect-k", "2"]
    assert F.main(["--member", f"riskadj_momentum={a}", "--member", f"riskadj_momentum_daily={b}", "--out-json", str(tmp_path / "ok.json"), *base]) == 0
    res = json.loads((tmp_path / "ok.json").read_text())
    assert res["K"] == 2 and res["members"] == ["riskadj_momentum", "riskadj_momentum_daily"] and set(res["T1"]["blocks"]) == {"2", "3"}
    with pytest.raises(ValueError, match="different risk overrides"):
        F.main(["--member", f"riskadj_momentum={a}", "--member", f"riskadj_momentum_daily={c}", "--out-json", str(tmp_path / "bad.json"), *base])


def test_the_family_batch6_registration_payload_validates_with_k_2_and_known_spec_hashes(tmp_path):
    gp = dataclasses.asdict(load_shared_config().validation_gates)
    path = tmp_path / "family_ledger.csv"
    reason = "family_batch6 K=2: monthly and any-day momentum at 0.5% risk per trade, with STOCKBOT_NON_EQ=held (PREREGISTRATION.md)"
    LG.register_family(path=path, family_id="family_batch6", members=[SPEC_M, SPEC_D], gate_params=gp, git_sha="0" * 40, reason=reason)
    assert LG.family_budget(path, "family_batch6") == 2
    assert LG.family_members(path, "family_batch6") == [{"id": "riskadj_momentum", "version": "1.0.0", "config_hash": "72dbec2c3da600cfe6de049a64efd530171ef2f539075f53e57a05e972ef27dc"},
                                                       {"id": "riskadj_momentum_daily", "version": "1.0.0", "config_hash": "5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19"}]
    pl.verify_ledger(path)
    # the same specs registered earlier in other families (batch2, batch4, batch5) do not matter: a family id is the unit
    real = ROOT / "stockbot" / "validation" / "ledger" / "records" / "family_ledger.csv"
    import shutil
    shutil.copy(real, tmp_path / "real.csv")
    LG.register_family(path=tmp_path / "real.csv", family_id="family_batch6", members=[SPEC_M, SPEC_D], gate_params=gp, git_sha="0" * 40, reason=reason)
    pl.verify_ledger(tmp_path / "real.csv")
    assert LG.family_budget(tmp_path / "real.csv", "family_batch6") == 2


# ------------------------------------------------------------------------------------------------------------------ the comparison script
def test_family_batch6_comparison_reads_stored_numbers_only(runs, tmp_path):
    CMP = script("family_batch6_comparison")
    b6 = tmp_path / "b6"
    for key, name in (("m_half", "riskadj_momentum"), ("d_half", "riskadj_momentum_daily")):
        d = b6 / name
        d.mkdir(parents=True)
        for sub in ("run", "baseline"):
            (d / sub).mkdir()
            for f in (runs[key] / sub).iterdir():
                (d / sub / f.name).write_bytes(f.read_bytes())
        (d / "gates.json").write_bytes((runs[key] / "gates.json").read_bytes())
    out = tmp_path / "c.json"
    assert CMP.main(["--batch6", str(b6), "--out-json", str(out), "--out-md", str(tmp_path / "c.md"), "--ledger", str(tmp_path / "no_ledger.csv")]) == 0
    c = json.loads(out.read_text())
    assert set(c) == {"riskadj_momentum", "riskadj_momentum_daily"} and len(c["riskadj_momentum_daily"]) == 3 and len(c["riskadj_momentum"]) == 2
    last = c["riskadj_momentum_daily"][-1]["summary"]
    assert last["risk_per_trade_pct"] == 0.5 and last["non_eq_switch"] is True and last["trades"] == len(json.loads((b6 / "riskadj_momentum_daily" / "run" / "trades.json").read_text()))
    assert "| max drawdown % |" in (tmp_path / "c.md").read_text()

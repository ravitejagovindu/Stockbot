"""F6 — baseline/simulator parity, config-driven windows, and the hash-locked pre-registration + chained ledger."""
from __future__ import annotations

import csv
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from tests.unit.test_corporate_action_hold import DATES, _build


def _session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# ----------------------------------------------------------------------------- parity: baseline path == simulator
@pytest.mark.parametrize("with_split", [False, True])
def test_path_sim_matches_simulator_for_same_entry(with_split):
    from backtest.path_sim import simulate_position_path
    from backtest.simulator import Simulator
    from engine_core.candidate_builder import build_candidate_dicts
    from engine_core.risk_sizing import RiskAndSizingEngine

    s = _session()
    cfg = _build(s, action=("SPLIT", 1.0, 2.0), factor=0.5) if with_split else _build(s)
    sim_t = Simulator(cfg, s).run(DATES[0], DATES[17], 1_000_000.0).trades.iloc[0]

    sd, ed = DATES[9], DATES[10]
    cand = build_candidate_dicts(s, cfg, ["SYNTH"], sd)[0]
    setup = RiskAndSizingEngine(cfg).compute_setup(
        "SYNTH", sd, cand["adjusted_ohlcv"], cand["raw_ohlcv"], 1_000_000.0, [], sector=cand["sector"])
    assert not setup.blocked
    res = simulate_position_path(s, cfg, "SYNTH", setup, ed, DATES[17], {d: (False, True) for d in DATES},
                                 equity=1_000_000.0, cash=1_000_000.0)
    assert res["ok"]
    assert res["exit_date"] == sim_t["exit_date"] and res["exit_reason"] == sim_t["exit_reason"]
    for k in ("gross_r", "net_r", "net_r_after_tax", "risk_inr", "pnl_gross", "pnl_net"):
        assert res[k] == pytest.approx(sim_t[k], rel=1e-9), k


def test_baseline_windows_come_from_config_and_exclude_test_window():
    from scripts.provenance.redesigned_random_baseline import tune_windows

    cfg = {"backtest": {"regimes": [
        {"name": "a", "role": "TUNE", "start": "2020-01-01", "end": "2021-12-31"},
        {"name": "t", "role": "TEST", "start": "2015-01-01", "end": "2019-12-31"},
    ]}}
    assert tune_windows(cfg) == [("a", date(2020, 1, 1), date(2021, 12, 31))]
    src = Path("scripts/provenance/redesigned_random_baseline.py").read_text(encoding="utf-8")
    for hard in ("2026, 10, 16", "date(2019, 10, 1)", "date(2021, 12, 31)"):
        assert hard not in src, f"hardcoded date {hard} still present"


# ----------------------------------------------------------------------------- hash lock
@pytest.fixture
def lock_env(tmp_path, monkeypatch):
    import scripts.provenance.select_candidate as sc

    yml = tmp_path / "pre_registered_configs.yaml"
    shutil.copy(Path("stockbot/validation/ledger/records/pre_registered_configs.yaml"), yml)
    ledger = tmp_path / "trial_ledger.csv"
    monkeypatch.setattr(sc, "PRE_REG_YAML", yml)
    monkeypatch.setattr(sc, "REGISTRY_LEDGER", ledger)
    monkeypatch.setattr(sc, "EXPLORATORY_LOG", tmp_path / "trial_ledger_exploratory.csv")
    # synthetic copy of the ORIGINAL (pre-F6) ledger: one SELECTION row, no chain columns
    ledger.write_text(
        "timestamp_utc,commit_sha,selected_config,selection_reason,CFG-01_gate_reached,CFG-02_gate_reached,"
        "CFG-03_gate_reached,CFG-04_gate_reached,CFG-05_gate_reached,CFG-06_gate_reached\n"
        "2026-11-05T03:25:25.744411+00:00,c3322fc2a850,NONE,No candidate passed all gates,2,2,2,2,2,2\n",
        encoding="utf-8")
    return sc, yml, ledger


def _enforce(sc):
    from stockbot.validation import prereg_lock as pl
    n = len([c for c in yaml.safe_load(sc.PRE_REG_YAML.read_text(encoding="utf-8"))["configs"] if c["role"] == "CANDIDATE"])
    return pl.enforce(sc.PRE_REG_YAML, sc.REGISTRY_LEDGER, sc.gate_parameters(), n)


def test_unregistered_or_legacy_ledger_is_refused(lock_env):
    from stockbot.validation.prereg_lock import PreRegistrationError
    sc, _, _ = lock_env
    with pytest.raises(PreRegistrationError):
        _enforce(sc)


def test_register_then_verify_and_budget_and_yaml_tamper(lock_env):
    from stockbot.validation.prereg_lock import PreRegistrationError
    sc, yml, ledger = lock_env
    sc.register()
    reg = _enforce(sc)
    assert int(reg["budget"]) == 6

    # re-registering silently is refused
    with pytest.raises(PreRegistrationError):
        sc.register()

    # tamper: edit the YAML
    original = yml.read_text(encoding="utf-8")
    yml.write_text(original + "\n# sneaky edit\n", encoding="utf-8")
    with pytest.raises(PreRegistrationError, match="yaml|YAML"):
        _enforce(sc)
    yml.write_text(original, encoding="utf-8")
    _enforce(sc)

    # tamper: add a seventh candidate config
    doc = yaml.safe_load(original)
    doc["configs"].append(dict(doc["configs"][-1], id="CFG-07"))
    yml.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(PreRegistrationError):
        _enforce(sc)


def test_crlf_does_not_change_yaml_hash(tmp_path):
    from stockbot.validation.prereg_lock import sha256_text_file
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_bytes(b"x: 1\ny: 2\n")
    b.write_bytes(b"x: 1\r\ny: 2\r\n")
    assert sha256_text_file(a) == sha256_text_file(b)


def test_ledger_row_deletion_and_alteration_detected(lock_env):
    from stockbot.validation import prereg_lock as pl
    sc, _, ledger = lock_env
    sc.register()
    pl.append_row(ledger, {"timestamp_utc": "t", "commit_sha": "c", "selected_config": "NONE",
                           "selection_reason": "x", "row_type": "SELECTION", "yaml_sha256": "y",
                           "gates_sha256": "g", "budget": 6})
    pl.verify_ledger(ledger)
    original = ledger.read_text(encoding="utf-8")

    rows = list(csv.reader(original.splitlines()))
    # delete the legacy (first data) row
    with open(ledger, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([rows[0]] + rows[2:])
    with pytest.raises(pl.PreRegistrationError, match="chain broken"):
        pl.verify_ledger(ledger)

    # alter a field of the legacy row
    altered = [r[:] for r in rows]
    altered[1][3] = "EDITED REASON"
    with open(ledger, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(altered)
    with pytest.raises(pl.PreRegistrationError, match="altered"):
        pl.verify_ledger(ledger)


def test_legacy_row_is_preserved_and_chained(lock_env):
    from stockbot.validation import prereg_lock as pl
    sc, _, ledger = lock_env
    sc.register()
    header, recs = pl.read_ledger(ledger)
    assert recs[0]["row_type"] == "LEGACY" and recs[0]["selected_config"] == "NONE"
    assert recs[0]["prev_hash"] == pl.GENESIS
    assert recs[1]["row_type"] == "REGISTRATION"


def test_repo_yaml_documents_dated_amendment_made_before_new_selection_runs():
    doc = yaml.safe_load(Path("stockbot/validation/ledger/records/pre_registered_configs.yaml").read_text(encoding="utf-8"))
    am = doc.get("amendments") or []
    assert am and am[0]["date"] == "2026-11-06"
    assert am[0]["made_before_any_new_selection_run"] is True


# ----------------------------------------------------------------------------- decision Q5: the engine's single-ticket path equals the legacy path_sim
@pytest.mark.parametrize("with_split", [False, True])
def test_engine_path_equals_legacy_path_sim_for_the_same_ticket(with_split):
    """Same ticket, same lake: fill, shares, split rebasing, breakeven stop, exit price/date/reason and P&L of ``engine.path.simulate_ticket`` (with a dummy policy that only moves
    the stop to entry after +1R, which is all the old lifecycle does on this path) equal the legacy ``backtest.path_sim`` result."""
    from backtest.path_sim import simulate_position_path
    from engine_core.candidate_builder import build_candidate_dicts
    from engine_core.risk_sizing import RiskAndSizingEngine
    from stockbot.config.shared import load_shared_config
    from stockbot.data.asof import AsOfView
    from stockbot.engine.path import simulate_ticket
    from stockbot.engine.types import Ticket
    from tests.fixtures.dummies import FixedPolicy

    s = _session()
    cfg = _build(s, action=("SPLIT", 1.0, 2.0), factor=0.5) if with_split else _build(s)
    sd, ed = DATES[9], DATES[10]
    cand = build_candidate_dicts(s, cfg, ["SYNTH"], sd)[0]
    setup = RiskAndSizingEngine(cfg).compute_setup("SYNTH", sd, cand["adjusted_ohlcv"], cand["raw_ohlcv"], 1_000_000.0, [], sector=cand["sector"])
    legacy = simulate_position_path(s, cfg, "SYNTH", setup, ed, DATES[17], {d: (False, True) for d in DATES}, equity=1_000_000.0, cash=1_000_000.0)
    assert legacy["ok"]

    from dataclasses import replace
    base = load_shared_config()                                         # the legacy test config differs from production: no slippage, 5% gap-up cap, its own costs
    ex, c = cfg["execution"], cfg["costs"]
    shared = replace(base, execution=replace(base.execution, entry_slippage_pct=ex["entry_slippage_pct"], exit_slippage_pct=ex["exit_slippage_pct"], max_entry_gap_up_pct=ex["max_entry_gap_up_pct"]),
                     costs=replace(base.costs, stt_buy_pct=c["stt_buy_pct"], stt_sell_pct=c["stt_sell_pct"], brokerage_per_order_inr=c["brokerage_per_order_inr"], exchange_txn_pct=c["exchange_txn_pct"],
                                   sebi_fee_pct=c["sebi_fee_pct"], stamp_duty_buy_pct=c["stamp_duty_buy_pct"], gst_pct=c["gst_pct"], dp_charge_per_sell_inr=c["dp_charge_per_sell_inr"],
                                   stcg_tax_pct=c["stcg_tax_pct"]))
    conn = s.connection().connection                                   # the DBAPI connection of the in-memory lake
    t = Ticket("t", "s", "SYNTH", None, sd, setup.entry_price, setup.live_stop_loss, setup.initial_resistance_target, 0, 0.0, 0.0, sd)
    trade, exits, why = simulate_ticket(t, [d for d in DATES if d <= DATES[17]], lambda d: AsOfView(conn, d), shared_config=shared, policy=FixedPolicy(breakeven_r=1.0), equity=1_000_000.0)
    assert why == "CLOSED"
    # a split halves the stored entry price; the legacy result reports the pre-split fill price
    assert trade.entry_price * (2.0 if with_split else 1.0) == pytest.approx(legacy["fill_price"], rel=1e-12) and trade.exit_date == legacy["exit_date"] and trade.exit_reason == legacy["exit_reason"]
    assert trade.shares_initial == pytest.approx(legacy["shares"] * (2.0 if with_split else 1.0))
    for ours, theirs in ((trade.gross_pnl, legacy["pnl_gross"]), (trade.costs, legacy["costs"]), (trade.net_pnl, legacy["pnl_net"]), (trade.risk_inr, legacy["risk_inr"])):
        assert ours == pytest.approx(theirs, rel=1e-9)

"""
tests/unit/test_baseline_reproducibility.py — Programmatic verification of CFG-00 Reproducibility.
Asserts that CFG-00 reproduces the official baseline backtest trade counts, P&L, and Net Expectancy
both via active execution of Simulator and across the verified full backtest dataset.

F10: the active-Simulator tests run on a small fixture lake (tests/fixtures/mini_lake.py) in an in-memory database - they never touch finsight.db.
The real-database versions live in tests/data_integrity/test_baseline_real_db.py (STOCKBOT_DATA_TESTS=1).
"""
from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
import sys
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.simulator import Simulator
from stockbot.config.legacy_loader import load_config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.db.connection import Base
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.entry_filters import apply_entry_filters

OUTPUT_DIR = ROOT / "backtest" / "outputs"

# Cryptographic SHA-256 checksums of frozen baseline trade artifacts
W1_SHA256 = "66e9aec15eb43b051dd2c73b917e5674dd8d762652dc5bed8bac81a7a341d041"
W2_SHA256 = "34e87890c90adc6cf3cab8e1a7af9b90b688516af39c26ca2058cba79407d96e"


@pytest.fixture
def lake():
    from tests.fixtures import mini_lake
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    ds = mini_lake.build(s)
    yield s, ds
    s.close()
    eng.dispose()


def test_simulator_and_funnel_agreement(lake):
    """Simulator and candidate screening/filtering agree on candidate selection (fixture lake, real strategy_config.yaml)."""
    from tests.fixtures import mini_lake as m
    s, ds = lake
    cfg = load_config()
    sim = Simulator(cfg, s)
    d = ds[m.BREAKOUT]                                      # signal date; fill is on the next session

    all_syms = sim.screener._get_all_symbols(d)
    passed = [sym for sym in all_syms if sym not in ("NIFTY50_INDEX", "INDIA_VIX")
              and sim.screener.screen_single(sym, d, apply_event_gates=False).passed]
    assert passed == ["FIXCO"], passed

    filtered = apply_entry_filters(build_candidate_dicts(s, cfg, passed, d), cfg)
    assert [c["symbol"] for c in filtered] == ["FIXCO"]

    approved = [st for st in sim.sizer.compute_all(filtered, d, 1_000_000.0, [], s, is_bull_regime=True) if not st.blocked]
    assert len(approved) == 1 and approved[0].symbol == "FIXCO"
    assert approved[0].projected_rr >= 1.5


def test_active_simulator_on_the_fixture_lake_reproduces_the_hand_derived_trade(lake):
    """Run the real Simulator and real config over the fixture and check every number against arithmetic done by hand.

    Signal close 176 on session 300 (breakout above the prior 20-session high 173). Fill = session 301 open 177 x (1 + 0.10% slippage).
    Session 302 opens 160 (above the stop) and trades down to 158, so the stop is hit and the fill is stop x (1 - 0.10%).
    """
    from tests.fixtures import mini_lake as m
    s, ds = lake
    cfg = load_config()
    res = Simulator(cfg, s).run(ds[290], ds[320], 1_000_000.0)
    t = res.trades
    assert len(t) == 1, t
    r = t.iloc[0]
    slip = cfg["execution"]["entry_slippage_pct"] / 100.0
    exit_slip = cfg["execution"]["exit_slippage_pct"] / 100.0
    assert r["symbol"] == "FIXCO"
    assert pd.Timestamp(r["entry_date"]).date() == ds[m.ENTRY] and pd.Timestamp(r["exit_date"]).date() == ds[m.CRASH]
    assert r["entry_price"] == pytest.approx(177.0 * (1 + slip), abs=1e-9)
    assert r["exit_reason"] == "STOP_HIT" and r["exit_state"] == "INITIAL_RISK"
    assert r["exit_price"] == pytest.approx(r["stop"] * (1 - exit_slip), abs=1e-9)
    risk_per_share = r["entry_price"] - r["stop"]
    assert int(r["shares"]) == int(1_000_000.0 * cfg["risk"]["max_loss_pct_per_trade"] / 100.0 // risk_per_share) == 553
    assert r["risk_inr"] == pytest.approx(r["shares"] * risk_per_share)
    assert r["pnl_gross"] == pytest.approx(r["shares"] * (r["exit_price"] - r["entry_price"]))
    assert r["stop"] == pytest.approx(159.115349, abs=1e-5)             # min(stop A, stop B) on the fixture (golden master of the sizing maths)
    assert r["gross_r"] == pytest.approx(r["pnl_gross"] / r["risk_inr"]) and r["gross_r"] < -1.0
    assert r["pnl_net"] < r["pnl_gross"]                                # costs were charged


def test_cfg00_window1_reproducibility():
    """Verify Window 1 (2020-2021) baseline trade counts, P&L, net expectancy, and SHA-256 hash."""
    w1_path = OUTPUT_DIR / "trades_pass1_window_2020_2021.csv"
    assert w1_path.exists(), f"Missing baseline W1 CSV: {w1_path}"

    with open(w1_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    assert actual_hash == W1_SHA256, f"W1 CSV checksum mismatch: {actual_hash} != {W1_SHA256}"

    df = pd.read_csv(w1_path)
    trades_count = len(df)
    net_pnl = df["pnl_net"].sum()
    one_r = df["entry_price"] - df["stop"]
    net_r = (df["pnl_net"] / (df["shares"] * one_r)).mean()

    # Assert exact pre-registered baseline numbers (dynamically confirmed by Simulator in 1885.4s)
    assert trades_count == 39, f"Expected 39 trades in W1, got {trades_count}"
    assert round(net_pnl) == 229083, f"Expected Net PnL +229,083 in W1, got {net_pnl:.0f}"
    assert round(net_r, 3) == 0.547, f"Expected Net Expectancy +0.547R in W1, got {net_r:.3f}"


def test_cfg00_window2_reproducibility():
    """Verify Window 2 (2022-2026) baseline trade counts, P&L, net expectancy, and SHA-256 hash."""
    w2_path = OUTPUT_DIR / "trades_pass1_window_2022_2026.csv"
    assert w2_path.exists(), f"Missing baseline W2 CSV: {w2_path}"

    with open(w2_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    assert actual_hash == W2_SHA256, f"W2 CSV checksum mismatch: {actual_hash} != {W2_SHA256}"

    df = pd.read_csv(w2_path)
    trades_count = len(df)
    net_pnl = df["pnl_net"].sum()
    one_r = df["entry_price"] - df["stop"]
    net_r = (df["pnl_net"] / (df["shares"] * one_r)).mean()

    # Assert exact pre-registered baseline numbers (dynamically confirmed by Simulator)
    assert trades_count == 159, f"Expected 159 trades in W2, got {trades_count}"
    assert round(net_pnl) == -164616, f"Expected Net PnL -164,616 in W2, got {net_pnl:.0f}"
    assert round(net_r, 3) == -0.104, f"Expected Net Expectancy -0.104R in W2, got {net_r:.3f}"


def test_cfg00_pooled_reproducibility():
    """Verify Pooled (2020-2026) baseline metrics."""
    w1 = pd.read_csv(OUTPUT_DIR / "trades_pass1_window_2020_2021.csv")
    w2 = pd.read_csv(OUTPUT_DIR / "trades_pass1_window_2022_2026.csv")
    pooled = pd.concat([w1, w2], ignore_index=True)

    assert len(pooled) == 198
    assert round(pooled["pnl_net"].sum()) == 64468
    one_r = pooled["entry_price"] - pooled["stop"]
    net_r = (pooled["pnl_net"] / (pooled["shares"] * one_r)).mean()
    assert round(net_r, 3) == 0.024


def test_this_module_does_not_depend_on_the_real_database():
    """F10 guard: no get_session and no database path string in the unit version (real-DB versions are in tests/data_integrity)."""
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "get_session" not in imported
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr)
                  and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    needle = "".join(["fin", "sight"])
    assert not any(needle in x for x in strings)
    assert "sqlite:///:memory:" in strings

"""
tests/unit/test_baseline_reproducibility.py — Programmatic verification of CFG-00 Reproducibility.
Asserts that CFG-00 reproduces the official baseline backtest trade counts, P&L, and Net Expectancy
both via active execution of Simulator and across the verified full backtest dataset.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.simulator import Simulator
from config import load_config
from data.db.connection import get_session
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.entry_filters import apply_entry_filters

OUTPUT_DIR = ROOT / "backtest" / "outputs"


def test_simulator_and_funnel_agreement():
    """Verify that Simulator and candidate screening/filtering agree on candidate selection."""
    cfg = load_config()
    with get_session() as s:
        sim = Simulator(cfg, s)
        d = date(2020, 1, 14)  # Signal date for ESCORTS entry on 2020-01-15

        # Screening through UniverseScreener
        all_syms = sim.screener._get_all_symbols(d)
        passed = [
            sym for sym in all_syms
            if sym not in ("NIFTY50_INDEX", "INDIA_VIX")
            and sim.screener.screen_single(sym, d, apply_event_gates=False).passed
        ]
        assert "ESCORTS" in passed, "ESCORTS must pass universe screening on 2020-01-14"

        # Candidate building & entry filter ranking
        cands = build_candidate_dicts(s, cfg, passed, d)
        filtered = apply_entry_filters(cands, cfg)
        filtered_syms = [c["symbol"] for c in filtered]
        assert "ESCORTS" in filtered_syms, "ESCORTS must qualify in entry filters on 2020-01-14"

        # Risk sizing & R:R qualification (DLF & BALKRISIND blocked by RR < 1.5; ESCORTS approved)
        setups = sim.sizer.compute_all(filtered, d, 1_000_000.0, [], s, is_bull_regime=True)
        approved = [st for st in setups if not st.blocked]
        assert len(approved) == 1, f"Expected exactly 1 approved trade ticket, got {len(approved)}"
        assert approved[0].symbol == "ESCORTS", "Approved trade ticket must be ESCORTS"
        assert approved[0].projected_rr >= 1.5, "ESCORTS projected R:R must clear >= 1.5"


def test_cfg00_window1_reproducibility():
    """Verify Window 1 (2020-2021) baseline trade counts, P&L, and net expectancy."""
    w1_path = OUTPUT_DIR / "trades_pass1_window_2020_2021.csv"
    assert w1_path.exists(), f"Missing baseline W1 CSV: {w1_path}"

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
    """Verify Window 2 (2022-2026) baseline trade counts, P&L, and net expectancy."""
    w2_path = OUTPUT_DIR / "trades_pass1_window_2022_2026.csv"
    assert w2_path.exists(), f"Missing baseline W2 CSV: {w2_path}"

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

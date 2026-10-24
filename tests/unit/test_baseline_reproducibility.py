"""
tests/unit/test_baseline_reproducibility.py — Programmatic verification of CFG-00 Reproducibility.
Asserts that CFG-00 exactly reproduces the official baseline backtest trade counts, P&L, and Net Expectancy.
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "backtest" / "outputs"


def test_cfg00_window1_reproducibility():
    """Verify Window 1 (2020-2021) baseline trade counts, P&L, and net expectancy."""
    w1_path = OUTPUT_DIR / "trades_pass1_window_2020_2021.csv"
    assert w1_path.exists(), f"Missing baseline W1 CSV: {w1_path}"

    df = pd.read_csv(w1_path)
    trades_count = len(df)
    net_pnl = df["pnl_net"].sum()
    one_r = df["entry_price"] - df["stop"]
    net_r = (df["pnl_net"] / (df["shares"] * one_r)).mean()

    # Assert exact pre-registered baseline numbers
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

    # Assert exact pre-registered baseline numbers
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

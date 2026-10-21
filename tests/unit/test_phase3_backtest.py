"""tests/unit/test_phase3_backtest.py — Unit tests for Phase 3 components (Exclusions, AuditGenerator)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
import pytest
import pandas as pd

from backtest.exclusions import Exclusions
from backtest.audit_generator import summarize, generate, AuditGenerator
from backtest.simulator import SimResult


def test_exclusions_asm_blocked():
    exc = Exclusions(
        asm={"RELIANCE": [(date(2024, 1, 10), date(2024, 1, 20))]},
        earnings={},
        block_days=14,
        known_ahead_days=7,
    )
    assert not exc.asm_blocked("RELIANCE", date(2024, 1, 9))
    assert exc.asm_blocked("RELIANCE", date(2024, 1, 10))
    assert exc.asm_blocked("RELIANCE", date(2024, 1, 15))
    assert exc.asm_blocked("RELIANCE", date(2024, 1, 20))
    assert not exc.asm_blocked("RELIANCE", date(2024, 1, 21))
    # Case insensitivity
    assert exc.asm_blocked("reliance", date(2024, 1, 15))
    assert not exc.asm_blocked("TCS", date(2024, 1, 15))


def test_exclusions_earnings_within():
    exc = Exclusions(
        asm={},
        earnings={"INFY": [date(2024, 1, 15), date(2024, 4, 15)]},
        block_days=14,
        known_ahead_days=7,  # lim = min(14, 7) = 7 days
    )
    # Event is 2024-01-15.
    # On 2024-01-05: 15 is 10 days away (> 7) -> not within
    assert not exc.earnings_within("INFY", date(2024, 1, 5))
    # On 2024-01-08: 15 is 7 days away (<= 7) -> within
    assert exc.earnings_within("INFY", date(2024, 1, 8))
    assert exc.earnings_within("INFY", date(2024, 1, 15))
    # On 2024-01-16: event has passed -> not within
    assert not exc.earnings_within("INFY", date(2024, 1, 16))


def test_exclusions_fail_closed_on_missing_or_unverified(tmp_path):
    # Missing files
    with pytest.raises(RuntimeError, match="Pass 2 refused"):
        Exclusions.load(tmp_path, "test_regime", 14, 7, allow_unverified=False)

    # Allow unverified flag allows loading with applied=False
    exc_unv = Exclusions.load(tmp_path, "test_regime", 14, 7, allow_unverified=True)
    assert not exc_unv.applied

    # Create unverified ASM file
    asm_file = tmp_path / "pending_asm_gsm_matches_test_regime.csv"
    asm_file.write_text("symbol,framework,start_date,end_date,status\nTCS,ASM,2024-01-01,2024-01-30,PENDING\n")
    earn_file = tmp_path / "historical_earnings_test_regime.csv"
    earn_file.write_text("symbol,event_date\nINFY,2024-01-15\n")

    with pytest.raises(RuntimeError, match="not VERIFIED"):
        Exclusions.load(tmp_path, "test_regime", 14, 7, allow_unverified=False)

    # When marked VERIFIED, it loads cleanly
    asm_file.write_text("symbol,framework,start_date,end_date,status\nTCS,ASM,2024-01-01,2024-01-30,VERIFIED\n")
    exc_verified = Exclusions.load(tmp_path, "test_regime", 14, 7, allow_unverified=False)
    assert exc_verified.applied
    assert exc_verified.asm_blocked("TCS", date(2024, 1, 15))
    assert exc_verified.earnings_within("INFY", date(2024, 1, 10))


def test_audit_generator_summarize_and_generate(tmp_path):
    cfg = {
        "gates": {
            "max_drawdown_pct": 15.0,
            "min_alpha_after_tax_pct": -2.0,
            "min_expectancy_r": 0.15,
            "min_profit_factor": 1.3,
            "min_trades": 2,
            "ltcg_tax_pct": 12.5,
            "risk_free_pct": 6.5,
        }
    }

    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
    eq_vals = [1_000_000.0 + i * 2000.0 for i in range(100)]
    eq_series = pd.Series(eq_vals, index=dates)

    trades_data = [
        {
            "position_id": 1,
            "symbol": "SYM1",
            "entry_date": dates[10],
            "exit_date": dates[20],
            "entry_price": 100.0,
            "stop": 90.0,
            "shares": 100,
            "pnl_gross": 2000.0,
            "costs": 100.0,
            "pnl_net": 1900.0,
            "tax_est": 380.0,
            "days_held": 10,
        },
        {
            "position_id": 2,
            "symbol": "SYM2",
            "entry_date": dates[30],
            "exit_date": dates[40],
            "entry_price": 200.0,
            "stop": 180.0,
            "shares": 50,
            "pnl_gross": 3000.0,
            "costs": 150.0,
            "pnl_net": 2850.0,
            "tax_est": 570.0,
            "days_held": 10,
        },
    ]
    trades_df = pd.DataFrame(trades_data)
    sim_res = SimResult(trades_df, eq_series, skipped=[], compliance_applied=True)

    nifty_vals = [20000.0 + i * 20.0 for i in range(100)]
    nifty_series = pd.Series(nifty_vals, index=dates)

    summary = summarize(sim_res, nifty_series, cfg, 1_000_000.0)
    assert summary["n_trades"] == 2
    assert summary["compliance_applied"] is True
    assert summary["alpha_after_tax_pct"] > 0
    assert summary["max_drawdown_pct"] >= 0.0

    summaries = {"window_2024": summary}
    audit = generate(summaries, cfg, out_dir=tmp_path)

    assert (tmp_path / "audit.json").exists()
    assert (tmp_path / "audit.sha256").exists()
    assert audit["dual_gate"]["overall_pass"] is True
    assert audit["eligible_for_deployment"] is True

    # Validate SHA matching
    saved_sha = (tmp_path / "audit.sha256").read_text().strip()
    import hashlib
    actual_sha = hashlib.sha256((tmp_path / "audit.json").read_bytes()).hexdigest()
    assert saved_sha == actual_sha

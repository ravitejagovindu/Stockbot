"""tests/unit/test_phase3_backtest.py — Unit tests for Phase 3 components (Exclusions)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
import pytest
import pandas as pd

from stockbot.universe.exclusions import Exclusions


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



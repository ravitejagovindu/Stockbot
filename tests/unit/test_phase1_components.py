"""Unit tests for Phase 1 components:
- stockbot/config/mode.py
- stockbot/data/sector_map.py
- scripts/provenance/regime/regime_gates.py
"""
from datetime import date, timedelta
import pandas as pd
import pytest
from unittest.mock import MagicMock

from stockbot.config.mode import current_mode
from stockbot.data.sector_map import sector_for
from scripts.provenance.regime.regime_gates import is_bull, bull_correction_active


# ---------------------------------------------------------------------------
# 1. Mode tests
# ---------------------------------------------------------------------------

def test_current_mode_valid():
    assert current_mode({"runtime": {"mode": "PAPER"}}) == "PAPER"
    assert current_mode({"runtime": {"mode": "paper"}}) == "PAPER"
    assert current_mode({"runtime": {"mode": "LIVE"}}) == "LIVE"


def test_current_mode_invalid():
    with pytest.raises(ValueError, match="runtime.mode must be PAPER or LIVE"):
        current_mode({"runtime": {"mode": "TEST"}})

    with pytest.raises(ValueError, match="runtime.mode must be PAPER or LIVE"):
        current_mode({})


# ---------------------------------------------------------------------------
# 2. Sector map tests
# ---------------------------------------------------------------------------

def test_sector_map_lookup():
    # RELIANCE is a known Nifty50 energy stock
    sec = sector_for("RELIANCE")
    assert sec == "ENERGY"

    # HDFCBANK is Financials
    sec_hdfc = sector_for("HDFCBANK")
    assert sec_hdfc == "FINANCIALS"

    # An unmapped stock is its own sector (the pooled UNKNOWN bucket is gone; see tests/unit/test_sector_map.py)
    assert sector_for("NON_EXISTENT_TICKER_XYZ") == "UNMAPPED:NON_EXISTENT_TICKER_XYZ"


# ---------------------------------------------------------------------------
# 3. Entry filters tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 4. Regime gates tests
# ---------------------------------------------------------------------------

def test_is_bull():
    assert is_bull(kill_switch_active=False, nifty_close=25000.0, nifty_sma200=24000.0) is True
    assert is_bull(kill_switch_active=True, nifty_close=25000.0, nifty_sma200=24000.0) is False
    assert is_bull(kill_switch_active=False, nifty_close=23000.0, nifty_sma200=24000.0) is False
    assert is_bull(kill_switch_active=False, nifty_close=None, nifty_sma200=24000.0) is False


def test_bull_correction_active():
    # Above 200 SMA (20000) but below 50 SMA (22000) -> correction active
    assert bull_correction_active(nifty_close=21000.0, nifty_sma200=20000.0, nifty_sma_entry=22000.0) is True
    # Above both -> not in correction
    assert bull_correction_active(nifty_close=23000.0, nifty_sma200=20000.0, nifty_sma_entry=22000.0) is False
    # Below 200 SMA -> bear regime, not bull correction
    assert bull_correction_active(nifty_close=19000.0, nifty_sma200=20000.0, nifty_sma_entry=22000.0) is False


# ---------------------------------------------------------------------------
# 5. Risk sizing max_rr_cap test
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. Universe screener apply_event_gates test
# ---------------------------------------------------------------------------

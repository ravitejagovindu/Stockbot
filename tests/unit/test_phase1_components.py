"""Unit tests for Phase 1 components:
- engine_core/mode.py
- engine_core/sector_map.py
- engine_core/entry_filters.py
- engine_core/regime_gates.py
- engine_core/universe_screener.py (apply_event_gates flag)
- engine_core/risk_sizing.py (max_rr_cap)
"""
from datetime import date, timedelta
import pandas as pd
import pytest
from unittest.mock import MagicMock

from engine_core.mode import current_mode
from engine_core.sector_map import sector_for
from engine_core.entry_filters import (
    passes_trend_filter,
    passes_breakout,
    rs_return,
    apply_entry_filters,
)
from engine_core.regime_gates import is_bull, bull_correction_active
from engine_core.risk_sizing import RiskAndSizingEngine, TradeSetup
from engine_core.universe_screener import UniverseScreener, ScreeningResult


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

    # Unknown stock maps to UNKNOWN
    assert sector_for("NON_EXISTENT_TICKER_XYZ") == "UNKNOWN"


# ---------------------------------------------------------------------------
# 3. Entry filters tests
# ---------------------------------------------------------------------------

def test_trend_filter():
    # Construct series where close > SMA5 > SMA10
    prices = list(range(1, 20))  # strictly rising
    s = pd.Series(prices)
    assert passes_trend_filter(s, fast=5, slow=10) is True

    # Falling series
    s_fall = pd.Series(list(reversed(prices)))
    assert passes_trend_filter(s_fall, fast=5, slow=10) is False

    # Insufficient length
    assert passes_trend_filter(pd.Series([10.0, 11.0]), fast=5, slow=10) is False


def test_breakout_filter():
    # 20 prior bars max is 100, today's close is 105 -> breakout
    highs = pd.Series([90.0] * 15 + [100.0] * 5 + [105.0])
    close = pd.Series([85.0] * 20 + [105.0])
    assert passes_breakout(close, highs, lookback=20) is True

    # Today's close is 95 < 100 -> no breakout
    close_low = pd.Series([85.0] * 20 + [95.0])
    assert passes_breakout(close_low, highs, lookback=20) is False


def test_apply_entry_filters_ranking():
    cfg = {
        "entry_filters": {
            "trend_filter_enabled": False,
            "breakout_required": False,
            "rs_lookback_days": 5,
        }
    }
    # Candidate A: +10% return over 5 bars
    df_a = pd.DataFrame({
        "close_adj": [100.0, 101.0, 102.0, 103.0, 104.0, 110.0],
        "high_adj": [101.0, 102.0, 103.0, 104.0, 105.0, 111.0],
    })
    # Candidate B: +50% return over 5 bars
    df_b = pd.DataFrame({
        "close_adj": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
        "high_adj": [101.0, 111.0, 121.0, 131.0, 141.0, 151.0],
    })
    cands = [
        {"symbol": "AAA", "adjusted_ohlcv": df_a},
        {"symbol": "BBB", "adjusted_ohlcv": df_b},
    ]
    ranked = apply_entry_filters(cands, cfg)
    # Highest RS return must come first -> BBB (+50%) then AAA (+10%)
    assert ranked[0]["symbol"] == "BBB"
    assert ranked[1]["symbol"] == "AAA"


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

def test_risk_sizing_max_rr_cap():
    cfg = {
        "risk": {
            "atr_period": 14,
            "atr_stop_multiplier": 2.0,
            "donchian_period": 20,
            "max_loss_pct_per_trade": 1.0,
            "min_rr_ratio": 1.5,
            "max_rr_cap": 5.0,  # Cap at 5.0 R:R
            "max_concurrent_positions": 10,
            "max_total_portfolio_risk_pct": 10.0,
            "max_sector_exposure_pct": 15.0,
        }
    }
    sizer = RiskAndSizingEngine(cfg)
    assert sizer._max_rr_cap == 5.0

    # Build synthetic data: entry 100, stop 98 (risk=2), target 120 -> R:R = 10.0 > 5.0
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
    df = pd.DataFrame({
        "open_raw": [100.0] * 40,
        "high_raw": [100.0] * 39 + [120.0],
        "low_raw": [99.0] * 40,
        "close_raw": [100.0] * 40,
        "volume_raw": [1000000] * 40,
        "open_adj": [100.0] * 40,
        "high_adj": [100.0] * 39 + [120.0],
        "low_adj": [99.0] * 40,
        "close_adj": [100.0] * 40,
    }, index=dates)

    setup = sizer.compute_setup(
        symbol="TEST",
        eval_date=dates[-1],
        adjusted_ohlcv=df,
        raw_ohlcv=df,
        account_equity=1000000.0,
        current_positions=[],
    )
    if setup.projected_rr > 5.0:
        assert setup.blocked is True
        assert "RR_ABOVE_CAP" in setup.block_reason


# ---------------------------------------------------------------------------
# 6. Universe screener apply_event_gates test
# ---------------------------------------------------------------------------

def test_screener_apply_event_gates_bypass():
    mock_session = MagicMock()
    cfg = {
        "universe": {
            "min_market_cap_cr": 100,
            "min_adtv_cr": 1,
            "min_listing_age_trading_days": 10,
            "volume_breakout_multiplier": 0,
            "relative_strength_top_pct": 0,
            "relative_strength_lookback_days": 63,
        },
        "trade_management": {
            "binary_event_block_days": 14,
        },
        "data": {
            "adtv_sma_period": 20,
        }
    }
    screener = UniverseScreener(cfg, mock_session)
    # Mock passed market cap, adtv, age
    screener._get_latest_price_and_shares = MagicMock(return_value=(100.0, 100_000_000))
    ohlcv = pd.DataFrame({
        "close_raw": [100.0] * 25,
        "volume_raw": [1_000_000] * 25,
    })
    screener._fetch_ohlcv = MagicMock(return_value=ohlcv)
    screener._get_listing_age = MagicMock(return_value=500)
    # Mark as under ASM/GSM and having earnings tomorrow
    screener._is_under_surveillance = MagicMock(return_value=True)
    screener._days_to_next_event = MagicMock(return_value=1)

    eval_d = date(2024, 6, 1)

    # When apply_event_gates=True: must fail on ASM/GSM
    res_strict = screener.screen_single("TEST", eval_d, apply_event_gates=True)
    assert res_strict.passed is False
    assert res_strict.rejection_reason == "UNDER_ASM_GSM_SURVEILLANCE"

    # When apply_event_gates=False: must bypass both ASM/GSM and earnings gates
    res_bypass = screener.screen_single("TEST", eval_d, apply_event_gates=False)
    assert res_bypass.passed is True
    assert res_bypass.rejection_reason is None

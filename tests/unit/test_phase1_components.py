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
    passes_pullback,
    rs_return,
    apply_rs_rank_percentile,
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


def test_passes_pullback():
    # 20 bars of 100.0 -> SMA20 is 100.0
    prices = [100.0] * 19
    # In range: 101.0 is between 98.0 and 103.0
    s_in = pd.Series(prices + [101.0])
    assert passes_pullback(s_in, period=20, lower_tol=0.98, upper_tol=1.03) is True

    # Upper bound breach: 104.0 > 103.0
    s_too_high = pd.Series(prices + [104.0])
    assert passes_pullback(s_too_high, period=20, lower_tol=0.98, upper_tol=1.03) is False

    # Lower bound breach: 97.0 < 98.0
    s_too_low = pd.Series(prices + [97.0])
    assert passes_pullback(s_too_low, period=20, lower_tol=0.98, upper_tol=1.03) is False

    # Insufficient length: 15 bars
    s_short = pd.Series([100.0] * 15)
    assert passes_pullback(s_short, period=20) is False


def test_apply_rs_rank_percentile():
    cands = [{"symbol": f"SYM_{i}", "rs_3m": 10.0 - i} for i in range(10)]
    # Top 30% of 10 -> 3 candidates
    top30 = apply_rs_rank_percentile(cands, 30.0)
    assert len(top30) == 3
    assert [c["symbol"] for c in top30] == ["SYM_0", "SYM_1", "SYM_2"]

    # Top 40% of 10 -> 4 candidates
    top40 = apply_rs_rank_percentile(cands, 40.0)
    assert len(top40) == 4

    # Top 50% of 10 -> 5 candidates
    top50 = apply_rs_rank_percentile(cands, 50.0)
    assert len(top50) == 5

    # None or >= 100 -> all 10 candidates
    assert len(apply_rs_rank_percentile(cands, None)) == 10
    assert len(apply_rs_rank_percentile(cands, 100.0)) == 10


def test_apply_entry_filters_pullback_and_percentile():
    cfg = {
        "entry_filters": {
            "trend_filter_enabled": True,
            "trend_fast_sma": 5,
            "trend_slow_sma": 10,
            "breakout_required": False,
            "pullback_required": True,
            "pullback_sma_period": 5,
            "pullback_tolerance_lower": 0.98,
            "pullback_tolerance_upper": 1.03,
            "rs_lookback_days": 3,
            "rs_rank_percentile": 50,
        }
    }
    # Create 3 candidates:
    # SYM1: In trend, in pullback band, high RS
    # SYM2: In trend, in pullback band, lower RS
    # SYM3: In trend, but price blown out way above SMA5 (fails pullback)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(12)]
    
    # SYM1: SMA5 = (98 + 99 + 99.5 + 100 + 102.5) / 5 = 99.8 -> 102.5 / 99.8 = 1.027 (within [0.98, 1.03])
    # 3-day RS: 102.5 / 99.0 - 1 = +3.54%
    p1 = [80.0, 82.0, 85.0, 88.0, 91.0, 94.0, 98.0, 99.0, 99.5, 100.0, 102.5]
    df1 = pd.DataFrame({"close_adj": p1, "high_adj": p1}, index=dates[:len(p1)])
    
    # SYM2: SMA5 = (95 + 96 + 97 + 97.5 + 98) / 5 = 96.7 -> 98 / 96.7 = 1.013 (within [0.98, 1.03])
    # 3-day RS: 98.0 / 97.0 - 1 = +1.03%
    p2 = [85.0, 86.0, 87.0, 88.0, 90.0, 92.0, 95.0, 96.0, 97.0, 97.5, 98.0]
    df2 = pd.DataFrame({"close_adj": p2, "high_adj": p2}, index=dates[:len(p2)])

    # SYM3: huge spike today (120 vs SMA5 ~ 100 -> 1.20 > 1.03, fails pullback)
    p3 = [80.0, 82.0, 85.0, 88.0, 91.0, 94.0, 97.0, 98.0, 99.0, 100.0, 120.0]
    df3 = pd.DataFrame({"close_adj": p3, "high_adj": p3}, index=dates[:len(p3)])

    cands = [
        {"symbol": "SYM1", "adjusted_ohlcv": df1},
        {"symbol": "SYM2", "adjusted_ohlcv": df2},
        {"symbol": "SYM3", "adjusted_ohlcv": df3},
    ]
    passed = apply_entry_filters(cands, cfg)
    # SYM3 should be rejected by pullback gate
    # Top 50% of the 2 surviving candidates (SYM1, SYM2) -> max(1, int(2 * 0.5)) = 1 candidate
    assert len(passed) == 1
    assert passed[0]["symbol"] == "SYM1"


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

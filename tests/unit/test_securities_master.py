"""tests/unit/test_securities_master.py — Unit tests for SecuritiesMaster & official listing date logic."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
import pytest

from data.db.models import SecuritiesMaster
from data.ingestion.securities_ingestor import _parse_nse_date, fetch_and_save_symbol_listing_date
from engine_core.universe_screener import UniverseScreener


def test_parse_nse_date():
    assert _parse_nse_date("08-FEB-1995") == date(1995, 2, 8)
    assert _parse_nse_date("18-Nov-2021") == date(2021, 11, 18)
    assert _parse_nse_date("1995-11-29") == date(1995, 11, 29)
    assert _parse_nse_date("06/10/2008") == date(2008, 10, 6)
    assert _parse_nse_date("NA") is None
    assert _parse_nse_date("") is None


def test_get_listing_age_established_stock():
    mock_session = MagicMock()
    # Mock lookup from SecuritiesMaster returning 1995-11-29 (Reliance)
    mock_session.execute.return_value.scalar.return_value = date(1995, 11, 29)

    cfg = {
        "universe": {
            "min_market_cap_cr": 5000,
            "min_adtv_cr": 25,
            "min_listing_age_trading_days": 252,
        },
        "trade_management": {"binary_event_block_days": 14},
        "data": {"nifty_symbol": "NIFTY50_INDEX"},
    }
    screener = UniverseScreener(cfg, mock_session)

    # On Jan 15, 2020 (when local DB had only 10 days of data):
    age = screener._get_listing_age("RELIANCE", date(2020, 1, 15))
    assert age is not None
    assert age >= 252  # Must pass Gate 3 (>252 trading days)


def test_get_listing_age_recent_ipo_blocked():
    mock_session = MagicMock()
    # Mock lookup returning listing date 2021-11-18 (Paytm)
    mock_session.execute.return_value.scalar.side_effect = [
        date(2021, 11, 18),  # SecuritiesMaster query
        9,                   # Nifty trading days query
    ]

    cfg = {
        "universe": {
            "min_market_cap_cr": 5000,
            "min_adtv_cr": 25,
            "min_listing_age_trading_days": 252,
        },
        "trade_management": {"binary_event_block_days": 14},
        "data": {"nifty_symbol": "NIFTY50_INDEX"},
    }
    screener = UniverseScreener(cfg, mock_session)

    # 13 days after IPO (2021-12-01)
    age = screener._get_listing_age("PAYTM", date(2021, 12, 1))
    assert age == 9
    assert age < 252  # Correctly blocked as IPO lockout


def test_get_listing_age_unlisted_stock():
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar.return_value = date(2025, 1, 1)

    cfg = {
        "universe": {
            "min_market_cap_cr": 5000,
            "min_adtv_cr": 25,
            "min_listing_age_trading_days": 252,
        },
        "trade_management": {"binary_event_block_days": 14},
        "data": {"nifty_symbol": "NIFTY50_INDEX"},
    }
    screener = UniverseScreener(cfg, mock_session)

    # Evaluating on 2024-01-01 before listing date
    age = screener._get_listing_age("FUTURE_IPO", date(2024, 1, 1))
    assert age == 0

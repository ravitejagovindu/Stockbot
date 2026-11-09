"""tests/unit/test_securities_master.py — Unit tests for SecuritiesMaster & official listing date logic."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
import pytest

from stockbot.data.db.models import SecuritiesMaster
from stockbot.data.ingestion.securities_ingestor import _parse_nse_date, fetch_and_save_symbol_listing_date


def test_parse_nse_date():
    assert _parse_nse_date("08-FEB-1995") == date(1995, 2, 8)
    assert _parse_nse_date("18-Nov-2021") == date(2021, 11, 18)
    assert _parse_nse_date("1995-11-29") == date(1995, 11, 29)
    assert _parse_nse_date("06/10/2008") == date(2008, 10, 6)
    assert _parse_nse_date("NA") is None
    assert _parse_nse_date("") is None

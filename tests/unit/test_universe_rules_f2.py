"""F2 universe rules (reviewer-approved 2026-11-07): ETF/fund exclusion by INF ISIN, and the listing date derived from the first raw
trading day (securities_master untouched; names present on the lake's first day count as already seasoned)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from stockbot.data.db.models import Base, MarketDataLake, SecuritiesMaster
from engine_core.universe_screener import UniverseScreener, load_fund_symbols

CFG = {"universe": {"min_market_cap_cr": 5000, "min_adtv_cr": 25, "min_listing_age_trading_days": 252},
       "trade_management": {"binary_event_block_days": 14}, "data": {"nifty_symbol": "NIFTY50_INDEX"}}


def _sessions(start: date, n: int):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    # the lake starts 2013-01-01; OLDCO trades from the first day, YOUNGCO from 2018-05-01, IPOCO from 2021-11-18
    for sym, start, n in [("OLDCO", date(2013, 1, 1), 900), ("YOUNGCO", date(2018, 5, 1), 900), ("IPOCO", date(2021, 11, 18), 40), ("ETFCO", date(2016, 1, 1), 50)]:
        for d in _sessions(start, n):
            s.add(MarketDataLake(symbol=sym, trade_date=d, open_raw=1, high_raw=1, low_raw=1, close_raw=1, volume_raw=1))
    # securities_master holds a PLACEHOLDER listing date for YOUNGCO and OLDCO (the real-data problem found in F2)
    s.add(SecuritiesMaster(symbol="YOUNGCO", listing_date=date(2026, 10, 1)))
    s.add(SecuritiesMaster(symbol="OLDCO", listing_date=date(2026, 10, 1)))
    s.add(SecuritiesMaster(symbol="MASTERONLY", listing_date=date(2000, 1, 1)))
    s.commit()
    return s


def test_placeholder_master_date_is_ignored_and_first_raw_trading_day_is_used(session):
    age = UniverseScreener(CFG, session, fund_symbols=set())._get_listing_age("YOUNGCO", date(2020, 1, 15))
    assert age is not None and age >= 252                   # old code: master 2026-10-01 -> "not yet listed" -> 0


def test_name_present_on_the_lakes_first_day_is_seasoned_even_in_2013(session):
    age = UniverseScreener(CFG, session, fund_symbols=set())._get_listing_age("OLDCO", date(2013, 6, 3))
    assert age >= 252                                       # the lake merely starts there; the company is not a new listing


def test_recent_listing_is_still_blocked(session):
    age = UniverseScreener(CFG, session, fund_symbols=set())._get_listing_age("IPOCO", date(2021, 12, 1))
    assert 0 < age < 252
    assert UniverseScreener(CFG, session, fund_symbols=set())._get_listing_age("IPOCO", date(2021, 11, 1)) == 0   # before its first row


def test_symbol_absent_from_the_lake_falls_back_to_the_master(session):
    age = UniverseScreener(CFG, session, fund_symbols=set())._get_listing_age("MASTERONLY", date(2020, 1, 15))
    assert age is not None and age >= 252


def test_funds_are_excluded_from_the_universe_and_from_single_screening(session):
    scr = UniverseScreener(CFG, session, fund_symbols={"ETFCO"})
    assert "ETFCO" not in scr._get_all_symbols(date(2026, 1, 1)) and "OLDCO" in scr._get_all_symbols(date(2026, 1, 1))
    res = scr.screen_single("ETFCO", date(2016, 3, 1))
    assert res.passed is False and res.rejection_reason == "FUND_OR_ETF"


def test_fund_list_file_is_read(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("symbol,isin\nNIFTYBEES,INF204KB14I2\nGOLDBEES,INF204KB17I5\n")
    assert load_fund_symbols(p) == {"NIFTYBEES", "GOLDBEES"}
    assert load_fund_symbols(tmp_path / "missing.csv") == set()

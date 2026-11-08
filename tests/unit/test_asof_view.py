"""stockbot.data.lake / stockbot.data.asof on a small file-backed fixture lake (never touches finsight.db)."""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import CorporateActionsLog
from stockbot.data.asof import AsOfView, FutureDataError
from stockbot.data.lake import open_lake
from tests.fixtures import mini_lake
from tests.fixtures.lakefile import SPLIT_EX_IDX, _make, lake_path  # noqa: F401

def test_future_is_unreachable(lake_path):
    ds = mini_lake.sessions()
    T = ds[250]
    v = AsOfView(open_lake(lake_path), T)
    with pytest.raises(FutureDataError):
        v.raw_bars("FIXCO", end=T + timedelta(days=1))
    with pytest.raises(FutureDataError):
        v.adjusted_bars("FIXCO", start=T + timedelta(days=1))
    for fr in (v.raw_bars("FIXCO"), v.adjusted_bars("FIXCO"), v.index_bars("NIFTY50_INDEX"), v.index_bars("INDIA_VIX")):
        assert max(fr.index) == T
    assert v.sessions()[-1] == T and max(v.sessions()) == T
    assert all(a["ex_date"] <= T for a in v.corporate_actions("FIXCO"))
    assert v.symbol_info("FIXCO").n_sessions == 251


def test_no_connection_is_exposed(lake_path):
    v = AsOfView(open_lake(lake_path), mini_lake.sessions()[10])
    public = [a for a in dir(v) if not a.startswith("_")]
    assert not {"conn", "connection", "session", "cursor", "execute", "db", "engine"} & set(public)
    assert not [a for a in public if isinstance(getattr(v, a), (sqlite3.Connection, sqlite3.Cursor))]


def test_decisions_do_not_change_when_every_later_row_changes(tmp_path):
    ds = mini_lake.sessions()
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    _make(a)
    _make(b)
    T = ds[250]
    con = sqlite3.connect(b)                                         # corrupt EVERYTHING after T in lake b
    con.execute("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*7, close_raw=close_raw*7, volume_raw=1 where trade_date>?", (T.isoformat(),))
    con.execute("delete from market_data_lake where trade_date>? and symbol='INDIA_VIX'", (T.isoformat(),))
    con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('FIXCO', ?, 'SPLIT', 1, 2, 'x', 'T1')",
                ((T + timedelta(days=3)).isoformat(),))
    con.commit(); con.close()
    va, vb = AsOfView(open_lake(a), T), AsOfView(open_lake(b), T)
    for sym in ("FIXCO", "NIFTY50_INDEX", "INDIA_VIX"):
        pd.testing.assert_frame_equal(va.raw_bars(sym), vb.raw_bars(sym))
    pd.testing.assert_frame_equal(va.adjusted_bars("FIXCO"), vb.adjusted_bars("FIXCO"))
    assert va.corporate_actions("FIXCO") == vb.corporate_actions("FIXCO")
    assert va.sessions() == vb.sessions() and va.adtv("FIXCO") == vb.adtv("FIXCO") and va.symbols_trading() == vb.symbols_trading()
    assert va.symbol_info("FIXCO") == vb.symbol_info("FIXCO")


def test_adjustment_uses_only_actions_known_at_the_as_of_date(lake_path):
    ds = mini_lake.sessions()
    ex = ds[SPLIT_EX_IDX]
    before = AsOfView(open_lake(lake_path), ds[SPLIT_EX_IDX - 1])           # split not yet known
    after = AsOfView(open_lake(lake_path), ds[SPLIT_EX_IDX + 5])
    rb, ra = before.raw_bars("FIXCO", None), after.raw_bars("FIXCO", None)
    pd.testing.assert_series_equal(before.adjusted_bars("FIXCO", None)["close_adj"], rb["close_raw"].rename("close_adj"))
    adj = after.adjusted_bars("FIXCO", None)
    pre = [d for d in ra.index if d < ex]
    assert all(abs(adj.loc[d, "close_adj"] - 0.2 * ra.loc[d, "close_raw"]) < 1e-9 for d in pre)
    assert abs(adj.loc[ex, "close_adj"] - ra.loc[ex, "close_raw"]) < 1e-12      # the ex-date bar and later are not scaled
    assert [a["ex_date"] for a in before.corporate_actions("FIXCO")] == []
    assert [a["ex_date"] for a in after.corporate_actions("FIXCO")] == [ex]


# ------------------------------------------------------------------ F2 listing-age rule (ported from the old universe screener; reviewer-approved 2026-11-07)
def _age_lake(tmp_path):
    p = tmp_path / "age.db"
    con = sqlite3.connect(p)
    con.execute("create table market_data_lake (id integer primary key autoincrement, symbol text not null, trade_date date not null, open_raw real, high_raw real, low_raw real, close_raw real, volume_raw bigint, exchange text default 'NSE', unique(symbol, trade_date))")
    def sessions(start, n):
        out, d = [], start
        while len(out) < n:
            if d.weekday() < 5:
                out.append(d)
            d += timedelta(days=1)
        return out
    for sym, start, n in (("NIFTY50_INDEX", date(2013, 1, 1), 3600), ("OLDCO", date(2013, 1, 1), 3000), ("YOUNGCO", date(2018, 5, 1), 1500), ("IPOCO", date(2021, 11, 18), 40)):
        for d in sessions(start, n):
            con.execute("insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw) values (?,?,1,1,1,1,1)", (sym, d.isoformat()))
    for start, n in ((date(2018, 5, 1), 20), (date(2020, 1, 2), 20)):                  # GAPCO: two short stretches 20 months apart (few sessions, many calendar days)
        for d in sessions(start, n):
            con.execute("insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw) values ('GAPCO',?,1,1,1,1,1)", (d.isoformat(),))
    con.commit(); con.close()
    return p


def test_a_name_trading_on_the_lakes_first_day_is_seasoned_even_in_2013(tmp_path):
    v = AsOfView(open_lake(_age_lake(tmp_path)), date(2013, 6, 3))
    assert v.symbol_info("OLDCO").listing_age_days >= 252 and v.symbol_info("OLDCO").n_sessions < 252      # the lake merely starts there


def test_a_later_name_ages_by_its_own_sessions_until_550_calendar_days(tmp_path):
    p = _age_lake(tmp_path)
    young_day = AsOfView(open_lake(p), date(2018, 8, 1)).symbol_info("YOUNGCO")
    assert young_day.listing_age_days == young_day.n_sessions and 0 < young_day.n_sessions < 252
    assert AsOfView(open_lake(p), date(2020, 1, 15)).symbol_info("YOUNGCO").listing_age_days >= 252          # more than 550 calendar days: seasoned
    gap = AsOfView(open_lake(p), date(2020, 1, 15)).symbol_info("GAPCO")
    assert gap.n_sessions < 60 and gap.listing_age_days >= 252                                              # few sessions but 20 months since the first bar: seasoned


def test_a_recent_listing_is_still_young_and_a_name_without_bars_has_no_age(tmp_path):
    p = _age_lake(tmp_path)
    assert 0 < AsOfView(open_lake(p), date(2021, 12, 1)).symbol_info("IPOCO").listing_age_days < 252
    assert AsOfView(open_lake(p), date(2021, 11, 1)).symbol_info("IPOCO").listing_age_days is None          # before its first row
    assert AsOfView(open_lake(p), date(2021, 12, 1)).symbol_info("NOSUCH").listing_age_days is None


def test_eligibility_uses_the_f2_listing_age(tmp_path):
    from types import SimpleNamespace
    from stockbot.universe.eligibility import eligible_symbols
    p = _age_lake(tmp_path)
    con = sqlite3.connect(p)
    con.execute("update market_data_lake set close_raw=1000, volume_raw=10000000 where symbol != 'NIFTY50_INDEX'")      # ADTV 1,000 crore: liquidity is not the reason
    con.commit(); con.close()
    cfg = SimpleNamespace(min_adtv_cr=25, min_listing_age_trading_days=252)
    assert eligible_symbols(AsOfView(open_lake(p), date(2013, 11, 1)), cfg) == ["OLDCO"]                      # seasoned from the first day; the others do not exist yet
    got = eligible_symbols(AsOfView(open_lake(p), date(2021, 12, 1)), cfg)
    assert "OLDCO" in got and "YOUNGCO" in got and "IPOCO" not in got
    assert eligible_symbols(AsOfView(open_lake(p), date(2020, 1, 15)), cfg) == ["GAPCO", "OLDCO", "YOUNGCO"]


# ------------------------------------------------------------------ fund / ETF exclusion (ported from the old screener: reviewer-approved F2 rule, INF-ISIN list)
def test_the_fund_list_file_is_read_and_funds_are_not_eligible(tmp_path):
    from types import SimpleNamespace
    from stockbot.data.asof import _fund_symbols
    from stockbot.universe.eligibility import eligible_symbols
    funds = _fund_symbols()
    assert {"NIFTYBEES", "GOLDBEES"} <= funds and len(funds) > 400                      # data/reference/fund_etf_symbols.csv (INF ISINs), read and upper-cased
    p = _age_lake(tmp_path)
    con = sqlite3.connect(p)
    con.execute("update market_data_lake set symbol='NIFTYBEES' where symbol='OLDCO'")      # a fund with a long, liquid history
    con.execute("update market_data_lake set close_raw=1000, volume_raw=10000000 where symbol != 'NIFTY50_INDEX'")
    con.commit(); con.close()
    cfg = SimpleNamespace(min_adtv_cr=25, min_listing_age_trading_days=252)
    v = AsOfView(open_lake(p), date(2020, 1, 15))
    assert v.symbol_info("NIFTYBEES").is_fund_or_etf is True and v.symbol_info("YOUNGCO").is_fund_or_etf is False
    assert "NIFTYBEES" not in eligible_symbols(v, cfg) and "YOUNGCO" in eligible_symbols(v, cfg)


def test_no_asm_ranges_and_an_empty_dict_give_the_same_universe(tmp_path):
    from types import SimpleNamespace
    from stockbot.universe.eligibility import eligible_symbols
    p = _age_lake(tmp_path)
    con = sqlite3.connect(p)
    con.execute("update market_data_lake set close_raw=1000, volume_raw=10000000 where symbol != 'NIFTY50_INDEX'")
    con.commit(); con.close()
    cfg = SimpleNamespace(min_adtv_cr=25, min_listing_age_trading_days=252)
    v = AsOfView(open_lake(p), date(2020, 1, 15))
    assert eligible_symbols(v, cfg) == eligible_symbols(v, cfg, asm_ranges={}) == eligible_symbols(v, cfg, asm_ranges=None)
    assert "YOUNGCO" not in eligible_symbols(v, cfg, asm_ranges={"YOUNGCO": [(date(2020, 1, 1), date(2020, 1, 31))]})           # an ASM/GSM range covering the day excludes the name
    assert "YOUNGCO" in eligible_symbols(v, cfg, asm_ranges={"YOUNGCO": [(date(2019, 12, 1), date(2019, 12, 31)), (date(2020, 2, 1), date(2020, 2, 28))]})     # ranges before or after the day do not

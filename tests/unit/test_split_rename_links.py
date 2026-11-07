"""A rename that coincides with an ISIN change at a split is linked only when the split factor reproduces the price step."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from scripts.f2_split_rename_links import find_links


def _db(tmp_path, a_price, b_price):
    c = sqlite3.connect(tmp_path / "t.db")
    c.execute("create table market_data_lake_staging(symbol text, trade_date text, open_raw real, high_raw real, low_raw real, close_raw real, volume_raw int, prev_close real, isin text, series text, source text)")
    d = date(2020, 1, 1)
    days = [(d + timedelta(days=i)).isoformat() for i in range(40) if (d + timedelta(days=i)).weekday() < 5]
    for i, x in enumerate(days):
        sym, isin, px = ("OLD", "INE1", a_price) if i < 15 else ("NEW", "INE2", b_price)
        c.execute("insert into market_data_lake_staging values (?,?,?,?,?,?,?,?,?,?,?)", (sym, x, px, px, px, px, 1000, px, isin, "EQ", ""))
    c.commit()
    return c, days[15]


def _events(ex, factor):
    return pd.DataFrame([{"symbol": "NEW", "ex_date": ex, "factor_logged": factor}])


def test_split_that_reproduces_the_step_links_the_pair(tmp_path):
    con, ex = _db(tmp_path, 100.0, 51.0)
    out = find_links(con, _events(ex, 0.5), {"NEW"})
    assert len(out) == 1 and out.iloc[0].old_symbol == "OLD" and out.iloc[0].new_symbol == "NEW"


def test_price_step_without_a_matching_split_is_not_linked(tmp_path):
    con, ex = _db(tmp_path, 100.0, 51.0)
    assert find_links(con, _events(ex, 0.2), {"NEW"}).empty          # factor does not reproduce the step
    assert find_links(con, _events("2019-01-01", 0.5), {"NEW"}).empty  # no event at the boundary


def test_continuous_price_with_a_split_factor_is_not_linked(tmp_path):
    con, ex = _db(tmp_path, 100.0, 100.0)                             # price continuity alone proves nothing
    assert find_links(con, _events(ex, 0.5), {"NEW"}).empty

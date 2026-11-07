"""F2 Option A: ISIN -> canonical symbol map classification (synthetic staging database)."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from scripts.f2_build_isin_symbol_map import build

DDL = """
create table market_data_lake_staging(symbol text, trade_date text, open_raw real, high_raw real, low_raw real,
  close_raw real, volume_raw int, prev_close real, isin text, series text, source text);
create table bhavcopy_fetch_log(trade_date text primary key, status text, n_rows int, url text, fetched_at text, note text);
"""


def _days(n, start=date(2020, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _db(tmp_path, segments):
    """segments: list of (isin, symbol, first_idx, last_idx, price)"""
    days = _days(120)
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.executescript(DDL)
    for d in days:
        c.execute("insert into bhavcopy_fetch_log values (?, 'OK', 1, null, 'x', null)", (d,))
    for isin, sym, a, b, price in segments:
        for d in days[a:b + 1]:
            c.execute("insert into market_data_lake_staging values (?,?,?,?,?,?,?,?,?,?,?)",
                      (sym, d, price, price, price, price, 1000, price, isin, "EQ", ""))
    c.commit()
    c.close()
    return str(p), days


def _actions(tmp_path, rows):
    p = tmp_path / "a.csv"
    pd.DataFrame(rows, columns=["query_symbol", "symbol", "isin", "exDate", "subject", "series", "faceVal", "recDate", "comp"]).to_csv(p, index=False)
    return p


def test_pure_rename_maps_all_segments_to_latest_symbol(tmp_path):
    db, _ = _db(tmp_path, [("INE001", "OLD", 0, 49, 100.0), ("INE001", "NEW", 50, 119, 101.0)])
    df = build(db, _actions(tmp_path, []))
    assert set(df["isin_class"]) == {"pure_rename"}
    assert set(df["canonical_symbol"]) == {"NEW"}          # applied to the OLD (earlier-year) segment too
    assert list(df["symbol"]) == ["OLD", "NEW"]            # original traded symbol is kept


def test_demerger_in_feed_keeps_split(tmp_path):
    db, days = _db(tmp_path, [("INE002", "PARENT", 0, 49, 100.0), ("INE002", "CHILD", 50, 119, 60.0)])
    ex = pd.Timestamp(days[50]).strftime("%d-%b-%Y")
    df = build(db, _actions(tmp_path, [["PARENT", "PARENT", "INE002", ex, "Demerger", "EQ", 1, "", ""]]))
    assert set(df["isin_class"]) == {"demerger_merger"}
    assert list(df["canonical_symbol"]) == ["PARENT", "CHILD"]  # unchanged


def test_overlap_and_price_step_are_other(tmp_path):
    db, _ = _db(tmp_path, [("INE003", "A", 0, 80, 100.0), ("INE003", "B", 60, 119, 100.0),     # overlap
                           ("INE004", "C", 0, 49, 100.0), ("INE004", "D", 50, 119, 30.0)])     # price step, no event
    df = build(db, _actions(tmp_path, []))
    cls = df.drop_duplicates("isin").set_index("isin")["isin_class"].to_dict()
    assert cls == {"INE003": "other", "INE004": "other"}
    assert (df["canonical_symbol"] == df["symbol"]).all()


def test_deterministic(tmp_path):
    db, _ = _db(tmp_path, [("INE001", "OLD", 0, 49, 100.0), ("INE001", "NEW", 50, 119, 101.0)])
    a = build(db, _actions(tmp_path, []))
    b = build(db, _actions(tmp_path, []))
    pd.testing.assert_frame_equal(a, b)

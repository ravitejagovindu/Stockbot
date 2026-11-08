"""F2 swap: schema migration, Yahoo->raw swap, symbol mapping (synthetic database)."""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from scripts.provenance import f2_swap as sw

LAKE = """create table market_data_lake(id integer primary key autoincrement, symbol text not null, trade_date date not null,
 open_raw real not null, high_raw real not null, low_raw real not null, close_raw real not null, volume_raw bigint not null,
 exchange text not null default 'NSE', created_at timestamp default current_timestamp, unique(symbol, trade_date));
create index idx_mdl_symbol_date on market_data_lake(symbol, trade_date desc);
create table market_data_lake_staging(symbol text not null, trade_date date not null, open_raw real not null, high_raw real not null,
 low_raw real not null, close_raw real not null, volume_raw bigint not null, prev_close real, isin text, series text, source text,
 unique(symbol, trade_date));
create table corporate_actions_log(id integer primary key autoincrement, symbol text not null, ex_date date not null,
 action_type text not null check(action_type in ('SPLIT','BONUS','DIVIDEND','RIGHTS','MERGER')), ratio_numerator real,
 ratio_denominator real, notes text, created_at timestamp default current_timestamp, unique(symbol, ex_date, action_type));
create index idx_corp_symbol_date on corporate_actions_log(symbol, ex_date);
create table active_positions(id integer primary key, symbol text);
create table trade_analytics_log(id integer primary key, symbol text);
create table index_gap_fill(symbol text, trade_date text, open_raw real, high_raw real, low_raw real, close_raw real, source text,
 primary key(symbol, trade_date));
"""


def _row(sym, d, px, vol=1000):
    return (sym, d, px, px, px, px, vol)


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.executescript(LAKE)
    ins = "insert into market_data_lake(symbol,trade_date,open_raw,high_raw,low_raw,close_raw,volume_raw) values (?,?,?,?,?,?,?)"
    # pre-2020 (untouched, traded symbol OLD), a Yahoo-adjusted 2020+ row (replaced), post-window pipeline row, index row
    c.execute(ins, _row("OLD", "2019-12-30", 100.0))
    c.execute(ins, _row("OLD", "2019-12-31", 101.0))
    c.execute(ins, _row("NEW", "2020-01-01", 51.0))        # Yahoo, adjusted, current symbol (will be replaced)
    c.execute(ins, _row("NEW", "2020-01-02", 52.0))
    c.execute(ins, _row("ZZ", "2020-01-02", 5.0))
    c.execute(ins, _row("NEW", "2026-10-05", 70.0))        # pipeline day, untouched
    c.execute(ins, _row("NIFTY50_INDEX", "2020-01-02", 12000.0, 0))
    st = "insert into market_data_lake_staging values (?,?,?,?,?,?,?,?,?,?,?)"
    for sym, d, px in [("OLD", "2019-12-30", 100.0), ("OLD", "2019-12-31", 101.0), ("OLD", "2020-01-01", 102.0),
                       ("OLD", "2020-01-02", 103.0), ("NEW", "2020-01-03", 104.0), ("ZZ", "2020-01-02", 5.0),
                       ("OLD", "2019-10-27", 99.0), ("OLD", "2019-10-28", 99.5)]:
        c.execute(st, (*_row(sym, d, px), px, "INE1", "EQ", "x"))
    c.execute("insert into index_gap_fill values ('NIFTY50_INDEX','2020-01-01',1,2,0.5,1.5,'nse')")
    c.commit()
    c.close()
    return str(p)


@pytest.fixture
def special(tmp_path):
    p = tmp_path / "special.csv"
    pd.DataFrame({"date": ["2019-10-27"], "kind": ["special_session"], "note": ["x"]}).to_csv(p, index=False)
    return p


def _all(db, q):
    c = sqlite3.connect(db)
    try:
        return c.execute(q).fetchall()
    finally:
        c.close()


def test_schema_stage_adds_columns_relaxes_check_and_is_idempotent(db):
    sw.stage_schema(db)
    sw.stage_schema(db)
    cols = {r[1] for r in _all(db, "pragma table_info(market_data_lake)")}
    assert {"source", "loaded_at", "source_symbol"} <= cols
    c = sqlite3.connect(db)
    c.execute("insert into corporate_actions_log(symbol,ex_date,action_type) values ('A','2020-01-01','DEMERGER')")
    c.execute("insert into corporate_actions_log(symbol,ex_date,action_type) values ('A','2020-01-01','OTHER')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("insert into corporate_actions_log(symbol,ex_date,action_type) values ('A','2020-01-01','BOGUS')")
    c.close()
    assert "excluded_ca" in {r[1] for r in _all(db, "pragma table_info(trade_analytics_log)")}
    assert _all(db, "select name from sqlite_master where name='market_data_lake_yahoo_archive'")


def test_swap_replaces_window_and_leaves_the_rest(db, special):
    sw.stage_schema(db)
    before_pre = sw.checksum(db, "trade_date < '2020-01-01'")
    before_post = sw.checksum(db, "trade_date > '2026-09-30'")
    rep = sw.stage_swap(db, window=("2020-01-01", "2026-09-30"), special_csv=special, expect_special=1, expect_index=1)
    assert rep["archived"] == 3 and rep["inserted_window"] == 4 and rep["special_inserted"] == 1 and rep["index_inserted"] == 1
    # Yahoo rows are in the archive and gone from the lake; raw rows are in
    assert _all(db, "select count(*) from market_data_lake_yahoo_archive")[0][0] == 3
    assert _all(db, "select close_raw from market_data_lake where symbol='OLD' and trade_date='2020-01-01'")[0][0] == 102.0
    assert _all(db, "select count(*) from market_data_lake where symbol='NEW' and trade_date='2020-01-01'")[0][0] == 0
    # untouched: original pre-2020 rows and the pipeline day
    assert sw.checksum(db, "trade_date < '2020-01-01' and id <= 7") == before_pre
    assert sw.checksum(db, "trade_date > '2026-09-30'") == before_post
    # special session inserted (2019-10-27) but the ordinary 2019-10-28 staging date is not
    assert _all(db, "select count(*) from market_data_lake where trade_date='2019-10-27'")[0][0] == 1
    assert _all(db, "select count(*) from market_data_lake where trade_date='2019-10-28'")[0][0] == 0
    assert _all(db, "select source from market_data_lake where symbol='NIFTY50_INDEX' and trade_date='2020-01-01'")[0][0].startswith("nse")


def test_swap_rolls_back_when_the_expected_count_is_wrong(db, special):
    sw.stage_schema(db)
    n = _all(db, "select count(*) from market_data_lake")[0][0]
    with pytest.raises(AssertionError):
        sw.stage_swap(db, window=("2020-01-01", "2026-09-30"), special_csv=special, expect_special=99, expect_index=1)
    assert _all(db, "select count(*) from market_data_lake")[0][0] == n
    assert _all(db, "select count(*) from market_data_lake_yahoo_archive")[0][0] == 0


def _map(tmp_path, rows):
    p = tmp_path / "map.csv"
    pd.DataFrame(rows, columns=["isin", "symbol", "first_date", "last_date", "isin_class", "canonical_symbol"]).to_csv(p, index=False)
    return p


def test_mapping_relabels_keeps_source_symbol_and_checksum(db, special, tmp_path):
    sw.stage_schema(db)
    sw.stage_swap(db, window=("2020-01-01", "2026-09-30"), special_csv=special, expect_special=1, expect_index=1)
    m = _map(tmp_path, [["INE1", "OLD", "2019-10-27", "2020-01-02", "pure_rename", "NEW"],
                        ["INE9", "ZZ", "2020-01-02", "2020-01-02", "demerger_merger", "ZZ"]])
    n = _all(db, "select count(*) from market_data_lake")[0][0]
    rep = sw.stage_map(db, m)
    assert rep["rows_relabelled"] > 0 and rep["rows_before"] == rep["rows_after"] == n
    assert _all(db, "select count(*) from market_data_lake where symbol='OLD'")[0][0] == 0
    assert _all(db, "select source_symbol from market_data_lake where symbol='NEW' and trade_date='2019-12-31'")[0][0] == "OLD"
    assert _all(db, "select source_symbol from market_data_lake where symbol='ZZ'")[0][0] is None   # demerger class untouched


def test_mapping_with_duplicate_pair_rolls_back(db, special, tmp_path):
    sw.stage_schema(db)
    sw.stage_swap(db, window=("2020-01-01", "2026-09-30"), special_csv=special, expect_special=1, expect_index=1)
    c = sqlite3.connect(db)                                   # NEW already has 2020-01-03: OLD->NEW would collide there? no, force it
    c.execute("insert into market_data_lake(symbol,trade_date,open_raw,high_raw,low_raw,close_raw,volume_raw) values ('NEW','2019-12-31',1,1,1,1,1)")
    c.commit(); c.close()
    m = _map(tmp_path, [["INE1", "OLD", "2019-10-27", "2020-01-02", "pure_rename", "NEW"]])
    before = _all(db, "select count(*), sum(symbol='OLD') from market_data_lake")[0]
    with pytest.raises(Exception):
        sw.stage_map(db, m)
    assert _all(db, "select count(*), sum(symbol='OLD') from market_data_lake")[0] == before

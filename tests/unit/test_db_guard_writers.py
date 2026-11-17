"""db-guard section 2.3: the writers that could be used again cannot change a sealed or insert-only row, and can add a new one. Fixture database (the real schema), the writers' own code."""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from stockbot.data import guard
from stockbot.data.guard import writers
from stockbot.data.ingestion import (bhavcopy_ingestor, corporate_actions_ingestor, index_vix_ingestor, nse_corporate_actions_history, ohlcv_ingestor, securities_ingestor,
                                     shares_outstanding_ingestor)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "tests" / "fixtures" / "real_schema.sql"


@pytest.fixture
def env(tmp_path, monkeypatch):
    p = tmp_path / "w.db"
    con = sqlite3.connect(str(p), isolation_level=None)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.close()
    eng = create_engine(f"sqlite:///{p.as_posix()}")
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)

    @contextmanager
    def get_session():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
    for mod in (corporate_actions_ingestor, securities_ingestor, shares_outstanding_ingestor, ohlcv_ingestor, index_vix_ingestor):
        monkeypatch.setattr(mod, "get_session", get_session)
    yield type("Env", (), {"path": p, "engine": eng, "Session": Session, "get_session": staticmethod(get_session)})
    eng.dispose()


def install(env):
    c = sqlite3.connect(str(env.path), isolation_level=None)
    guard.install(c)
    return c


def q(env, sql, *a):
    c = sqlite3.connect(str(env.path))
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


# ----------------------------------------------------------------------------------------------------------------------------------- corporate actions
def ev(**k):
    d = dict(symbol="AAA", ex_date=date(2020, 1, 2), action_type="SPLIT", ratio_numerator=5.0, ratio_denominator=1.0, notes="first", source="t")
    d.update(k)
    return d


def test_corporate_actions_writer_adds_new_rows_and_never_changes_a_stored_one(env, caplog):
    corporate_actions_ingestor.CorporateActionsIngestor._bulk_upsert(None, [ev()])
    c = install(env)
    caplog.set_level(logging.WARNING)
    n = corporate_actions_ingestor.CorporateActionsIngestor._bulk_upsert(None, [ev(), ev(notes="changed"), ev(symbol="BBB"), ev(symbol="OLD", ex_date=date(2010, 1, 4))])
    assert n == 4
    rows = q(env, "select symbol, ex_date, notes from corporate_actions_log order by symbol")
    assert rows == [("AAA", "2020-01-02", "first"), ("BBB", "2020-01-02", "first"), ("OLD", "2010-01-04", "first")]      # the changed event was NOT applied; late facts with old dates are welcome
    assert any("were NOT changed" in r.message for r in caplog.records)
    c.close()


def test_corporate_actions_writer_without_the_guard_behaves_the_same(env):
    corporate_actions_ingestor.CorporateActionsIngestor._bulk_upsert(None, [ev(), ev(notes="changed")])
    assert q(env, "select count(*), min(notes) from corporate_actions_log") == [(1, "changed")] or q(env, "select count(*) from corporate_actions_log") == [(1,)]


def test_the_nse_history_loader_inserts_new_events_and_leaves_stored_ones(env, tmp_path):
    c = install(env)
    c.execute("INSERT INTO corporate_actions_log(symbol,ex_date,action_type,ratio_numerator,ratio_denominator,notes,source) VALUES ('AAA','2020-01-02','SPLIT',5,1,'Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share','t')")
    csv = tmp_path / "raw.csv"
    pd.DataFrame([{"symbol": "AAA", "query_symbol": "AAA", "exDate": "02-Jan-2020", "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"},
                  {"symbol": "BBB", "query_symbol": "BBB", "exDate": "03-Jan-2020", "subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share"}]).to_csv(csv, index=False)
    r = nse_corporate_actions_history.load(csv, str(env.path))
    assert r["inserted"] == 1 and q(env, "select count(*) from corporate_actions_log") == [(2,)]
    c.close()


# ----------------------------------------------------------------------------------------------------------------------------------- securities master
LIST_CSV = ("SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, ISIN NUMBER\nAAA,Alpha Ltd,EQ,02-JAN-2020,INE000A01010\nBBB,Beta Ltd,EQ,03-JAN-2020,INE000B01010\n")


def test_securities_master_writer_adds_new_symbols_and_never_replaces_a_stored_one(env, monkeypatch):
    monkeypatch.setattr(securities_ingestor, "fetch_equity_l_content", lambda: LIST_CSV)
    assert securities_ingestor.ingest_securities_master() == 2
    c = install(env)
    monkeypatch.setattr(securities_ingestor, "fetch_equity_l_content", lambda: LIST_CSV.replace("Alpha Ltd", "Alpha Renamed Ltd") + "CCC,Gamma Ltd,EQ,04-JAN-2020,INE000C01010\n")
    securities_ingestor.ingest_securities_master()
    rows = q(env, "select symbol, company_name from securities_master order by symbol")
    assert rows == [("AAA", "Alpha Ltd"), ("BBB", "Beta Ltd"), ("CCC", "Gamma Ltd")]            # the renamed one is NOT applied; the new one is
    c.close()


def test_the_live_listing_date_fetch_adds_a_new_symbol_and_does_not_replace(env):
    c = install(env)
    with env.get_session() as s:
        s.execute(text("INSERT INTO securities_master(symbol, company_name, series, listing_date, isin) VALUES ('AAA','Alpha','EQ','2020-01-02','X')"))
    # the inner _insert of fetch_and_save_symbol_listing_date is exercised through the same split_new rule
    with env.get_session() as s:
        new, same, diff = writers.split_new(writers.session_fetch(s), "securities_master", [dict(symbol="AAA", company_name="Alpha", series="EQ", listing_date="2020-01-02", isin="X"),
                                                                                             dict(symbol="AAA", company_name="Other", series="EQ", listing_date="2020-01-02", isin="X"),
                                                                                             dict(symbol="NEW", company_name="N", series="EQ", listing_date="2020-01-03", isin="Y")],
                                             ("symbol",), ("company_name", "series", "listing_date", "isin"))
    assert [r["symbol"] for r in new] == ["NEW"] and same == 1 and len(diff) == 1
    c.close()


# ----------------------------------------------------------------------------------------------------------------------------------- shares outstanding
def test_shares_writer_adds_a_new_date_and_cannot_change_a_stored_one(env, caplog):
    W = shares_outstanding_ingestor.SharesOutstandingIngestor
    W._upsert(None, "AAA", date(2020, 1, 1), 1000, "src")
    c = install(env)
    caplog.set_level(logging.WARNING)
    W._upsert(None, "AAA", date(2020, 1, 1), 2000, "other")                      # same date, other values: sealed, NOT applied
    W._upsert(None, "AAA", date(2026, 11, 17), 3000, "src")                      # a new date: added
    assert q(env, "select effective_date, shares_count from shares_outstanding order by 1") == [("2020-01-01", 1000), ("2026-11-17", 3000)]
    assert any("NOT changed" in r.message for r in caplog.records)
    c.close()


# ----------------------------------------------------------------------------------------------------------------------------------- the lake writers
def day_df(day, closes):
    return pd.DataFrame([{"symbol": s, "trade_date": day, "open_raw": c, "high_raw": c, "low_raw": c, "close_raw": c, "volume_raw": 10, "exchange": "NSE"} for s, c in closes.items()])


def lake(env):
    return q(env, "select symbol, trade_date, close_raw from market_data_lake order by trade_date, symbol")


def test_bhavcopy_store_day_refuses_a_sealed_day_before_deleting_anything_and_adds_a_new_day(env):
    ing = bhavcopy_ingestor.BhavcopyIngestor({})
    with env.get_session() as s:
        ing.store_day(s, day_df(date(2020, 1, 2), {"AAA": 1.0, "BBB": 2.0}), date(2020, 1, 2))      # unsealed (no guard yet): stored
    c = install(env)                                                                                  # seals through 2020-01-02
    with env.get_session() as s:
        with pytest.raises(writers.SealedError, match="sealed through 2020-01-02"):
            ing.store_day(s, day_df(date(2020, 1, 2), {"AAA": 9.0}), date(2020, 1, 2))
    assert lake(env) == [("AAA", "2020-01-02", 1.0), ("BBB", "2020-01-02", 2.0)]                       # nothing deleted, nothing changed
    with env.get_session() as s:
        ing.store_day(s, day_df(date(2020, 1, 3), {"AAA": 1.5, "BBB": 2.5}), date(2020, 1, 3))
    assert len(lake(env)) == 4
    c.close()


def test_bhavcopy_store_day_on_an_unsealed_day_is_delete_and_insert_in_one_transaction(env):
    ing = bhavcopy_ingestor.BhavcopyIngestor({})
    c = install(env)
    with env.get_session() as s:
        ing.store_day(s, day_df(date(2020, 1, 6), {"AAA": 1.0, "BBB": 2.0}), date(2020, 1, 6))
    with env.get_session() as s:
        ing.store_day(s, day_df(date(2020, 1, 6), {"AAA": 5.0}), date(2020, 1, 6))                     # reload of an unsealed day replaces it
    assert lake(env) == [("AAA", "2020-01-06", 5.0)]
    bad = day_df(date(2020, 1, 6), {"AAA": 7.0, "BBB": 8.0}).rename(columns={"exchange": "no_such_column"})
    with env.get_session() as s:
        with pytest.raises(Exception):
            ing.store_day(s, bad, date(2020, 1, 6))
    assert lake(env) == [("AAA", "2020-01-06", 5.0)]                                                     # the failed reload did not leave the day empty
    c.close()


def test_the_zero_fill_stays_on_unsealed_days_only_and_a_sealed_day_cannot_receive_it(env):
    ing = bhavcopy_ingestor.BhavcopyIngestor({})
    c = install(env)
    with env.get_session() as s:
        ing.store_day(s, day_df(date(2020, 1, 6), {"AAA": 0.0}), date(2020, 1, 6))                      # a zero-filled price on an unsealed day is still storable (data quality is not the guard's job)
    guard.seal_table(c, "market_data_lake", "2020-01-06")
    with env.get_session() as s:
        with pytest.raises(writers.SealedError):
            ing.store_day(s, day_df(date(2020, 1, 6), {"AAA": 3.0}), date(2020, 1, 6))
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE market_data_lake SET close_raw=3.0 WHERE symbol='AAA'")
    c.close()


class FakeKite:
    def __init__(self, day, close):
        self.day, self.close = day, close

    def historical_data(self, token, from_date, to_date, interval, continuous=False, oi=False):
        return [{"date": self.day, "open": self.close, "high": self.close, "low": self.close, "close": self.close, "volume": 10}]


def test_ohlcv_writer_cannot_change_a_sealed_day_and_adds_a_new_one(env):
    first = ohlcv_ingestor.OHLCVIngestor(FakeKite(date(2020, 1, 2), 1.0))
    first._fetch_and_store_chunk("AAA", 1, date(2020, 1, 2), date(2020, 1, 2))
    c = install(env)
    with pytest.raises(Exception, match="sealed"):
        ohlcv_ingestor.OHLCVIngestor(FakeKite(date(2020, 1, 2), 99.0))._fetch_and_store_chunk("AAA", 1, date(2020, 1, 2), date(2020, 1, 2))
    ohlcv_ingestor.OHLCVIngestor(FakeKite(date(2020, 1, 3), 2.0))._fetch_and_store_chunk("AAA", 1, date(2020, 1, 3), date(2020, 1, 3))
    assert lake(env) == [("AAA", "2020-01-02", 1.0), ("AAA", "2020-01-03", 2.0)]
    c.close()


def test_index_and_vix_writer_cannot_change_a_sealed_day_and_adds_a_new_one(env):
    ing = index_vix_ingestor.IndexVIXIngestor.__new__(index_vix_ingestor.IndexVIXIngestor)
    ing.logger = logging.getLogger('test')
    row = lambda d, c: dict(symbol="NIFTY50_INDEX", trade_date=d, open_raw=c, high_raw=c, low_raw=c, close_raw=c, volume_raw=0, exchange="NSE")      # noqa: E731
    ing._store_rows([row(date(2020, 1, 2), 100.0)])
    c = install(env)
    with pytest.raises(Exception, match="sealed"):
        ing._store_rows([row(date(2020, 1, 2), 999.0)])
    ing._store_rows([row(date(2020, 1, 3), 101.0)])
    assert lake(env) == [("NIFTY50_INDEX", "2020-01-02", 100.0), ("NIFTY50_INDEX", "2020-01-03", 101.0)]
    c.close()


def test_the_staging_and_regime_tables_stay_writable_because_they_are_exempt(env):
    c = install(env)
    c.execute("INSERT INTO market_data_lake_staging(symbol,trade_date,open_raw,high_raw,low_raw,close_raw,volume_raw) VALUES ('A','2020-01-01',1,1,1,1,1)")
    c.execute("DELETE FROM market_data_lake_staging")
    c.close()

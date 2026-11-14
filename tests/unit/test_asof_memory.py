"""MemoryAsOfView (in-memory) against AsOfView (SQL) on a fixture lake with the corporate-action edge cases: every answer must be IDENTICAL (exact frame equality, equal lists/objects).

The fixture (never the real lake) has a split, a bonus, a split and a bonus on the same day, a rights issue, a demerger (no ratio), a name with a gap, a late listing, a name that stops,
a name whose first row is the lake's first day, integer-valued prices, a zero-volume row, and a future-dated action (known only after as_of).
"""
import os
import random
import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine

from stockbot.data.asof import AsOfView, FutureDataError
from stockbot.data.asof_memory import MemoryAsOfView
from stockbot.data.db.connection import Base
from stockbot.data.lake import open_lake
from stockbot.universe.eligibility import eligible_symbols

START, N = date(2018, 1, 1), 700


def _sessions():
    out, d = [], START
    while len(out) < N:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DS = _sessions()
ACTIONS = [("SPLITCO", 200, "SPLIT", 1, 5), ("BONUSCO", 250, "BONUS", 2, 5), ("BOTHCO", 300, "SPLIT", 1, 2), ("BOTHCO", 300, "BONUS", 1, 1), ("RIGHTSCO", 320, "RIGHTS", 1, 4),
           ("DEMERGCO", 350, "DEMERGER", None, None), ("SPLITCO", 600, "SPLIT", 1, 2), ("GAPCO", 400, "SPLIT", 1, 10), ("FUTURECO", 650, "BONUS", 1, 1), ("SPLITCO", 100, "DIVIDEND", None, None)]


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("memlake") / "lake.db"
    eng = create_engine(f"sqlite:///{p.as_posix()}")
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(p)
    rng = random.Random(11)

    def put(sym, i, price, vol, integer=False):
        o, h, l, c = (round(price * f, 2) for f in (1.0, 1.02, 0.98, 1.01))
        if integer:
            o, h, l, c = (int(x) for x in (o, h, l, c))
        con.execute("insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange) values (?,?,?,?,?,?,?,'NSE')", (sym, DS[i].isoformat(), o, h, l, c, vol))

    ex_idx = {}
    for sym, i, t, num, den in ACTIONS:
        ex_idx.setdefault(sym, []).append((i, t, num, den))
    for i in range(N):
        put("NIFTY50_INDEX", i, 10000 + 3 * i, 0)
        put("INDIA_VIX", i, 14.0, 0)
    spec = {"SPLITCO": (0, N), "BONUSCO": (0, N), "BOTHCO": (0, N), "RIGHTSCO": (0, N), "DEMERGCO": (0, N), "GAPCO": (0, N), "LATECO": (500, N), "ENDCO": (0, 450), "FUTURECO": (0, N),
            "INTCO": (0, N), "PLAINCO": (0, N)}
    for sym, (a, b) in spec.items():
        px = 400.0 + rng.random() * 100
        for i in range(a, b):
            if sym == "GAPCO" and 380 <= i < 420:
                continue                                                  # a 40-session hole around its split
            px *= 1 + rng.uniform(-0.03, 0.03)
            for j, t, num, den in ex_idx.get(sym, ()):
                if i == j and t in ("SPLIT", "BONUS"):
                    px *= (num / den) if t == "SPLIT" else (den / (den + num))   # raw price falls on the ex-date
            put(sym, i, px, 0 if (sym == "PLAINCO" and i == 123) else rng.randint(50_000, 5_000_000), integer=(sym == "INTCO"))
    for sym, i, t, num, den in ACTIONS:
        con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values (?,?,?,?,?,'t','T1')",
                    (sym, DS[i].isoformat(), t, num, den))
    con.commit()
    con.close()
    return p


@pytest.fixture(autouse=True)
def _sql_is_sql(monkeypatch):
    """The SQL side of every comparison must really be the SQL view, whatever STOCKBOT_VIEW the suite runs under (the switch test sets it itself)."""
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


SYMS = ["SPLITCO", "BONUSCO", "BOTHCO", "RIGHTSCO", "DEMERGCO", "GAPCO", "LATECO", "ENDCO", "FUTURECO", "INTCO", "PLAINCO", "NOSUCH", "NIFTY50_INDEX", "INDIA_VIX"]
CFG = SimpleNamespace(min_adtv_cr=0.001, min_listing_age_trading_days=252)
DAYS = sorted({DS[0], DS[1], DS[19], DS[N - 1], DS[99], DS[100], *(DS[i + k] for i in (200, 250, 300, 320, 350, 400, 420, 450, 500, 600, 650) for k in (-1, 0, 1)), *DS[::37],
               date(2018, 1, 6), date(2017, 6, 1), date(2030, 1, 1)})        # a Saturday, a date before the lake, a date after it


def _same(a, b):
    if isinstance(a, pd.DataFrame):
        pd.testing.assert_frame_equal(a, b, check_exact=True, check_dtype=True, check_index_type=True, check_column_type=True)
    elif isinstance(a, pd.Series):
        pd.testing.assert_series_equal(a, b, check_exact=True, check_index_type=True)
    else:
        assert a == b and type(a) is type(b)


@pytest.mark.parametrize("day", DAYS, ids=[d.isoformat() for d in DAYS])
def test_every_primitive_and_derived_answer_is_identical(lake, day):
    sql, mem = AsOfView(open_lake(lake), day), MemoryAsOfView(open_lake(lake), day)
    assert type(sql) is AsOfView and type(mem) is MemoryAsOfView
    _same(sql.symbols_trading(), mem.symbols_trading())
    _same(sql.sessions(), mem.sessions())
    _same(sql.sessions(7), mem.sessions(7))
    _same(sql._lake_first_date(), mem._lake_first_date())
    for s in SYMS:
        _same(sql.symbol_info(s), mem.symbol_info(s))
        _same(sql.corporate_actions(s), mem.corporate_actions(s))
        for lb in (400, 1, 20, 3000, None):
            _same(sql.raw_bars(s, lb), mem.raw_bars(s, lb))
            _same(sql.adjusted_bars(s, lb), mem.adjusted_bars(s, lb))
        _same(sql.raw_bars(s, None, start=day - timedelta(days=90)), mem.raw_bars(s, None, start=day - timedelta(days=90)))
        _same(sql.raw_bars(s, 50, start=day - timedelta(days=30), end=day - timedelta(days=3)), mem.raw_bars(s, 50, start=day - timedelta(days=30), end=day - timedelta(days=3)))
        _same(sql.raw_bars(s, None, start=day, end=day), mem.raw_bars(s, None, start=day, end=day))
        _same(sql.raw_bars(s, None, start=day - timedelta(days=5), end=day - timedelta(days=10)), mem.raw_bars(s, None, start=day - timedelta(days=5), end=day - timedelta(days=10)))
        for per in (20, 5):
            _same(sql.adtv(s, per), mem.adtv(s, per))
        _same(sql.traded_value(s, 30), mem.traded_value(s, 30))
    for idx in ("NIFTY50_INDEX", "INDIA_VIX"):
        _same(sql.index_bars(idx, 60), mem.index_bars(idx, 60))
    for ov in (None, {"min_adtv_cr": 5.0}, {"min_listing_age_trading_days": 400}):
        _same(eligible_symbols(sql, CFG, overrides=ov), eligible_symbols(mem, CFG, overrides=ov))
    _same(eligible_symbols(sql, CFG, asm_ranges={"SPLITCO": [(DS[0], DS[N - 1])]}), eligible_symbols(mem, CFG, asm_ranges={"SPLITCO": [(DS[0], DS[N - 1])]}))


def test_the_future_is_still_unreachable(lake):
    v = MemoryAsOfView(open_lake(lake), DS[300])
    with pytest.raises(FutureDataError):
        v.raw_bars("SPLITCO", end=DS[301])
    with pytest.raises(FutureDataError):
        v.adjusted_bars("SPLITCO", start=DS[301])
    assert max(v.raw_bars("SPLITCO").index) == DS[300] and v.sessions()[-1] == DS[300]
    assert all(a["ex_date"] <= DS[300] for a in v.corporate_actions("FUTURECO") + v.corporate_actions("SPLITCO"))


def test_adjustment_edge_cases_are_actually_exercised(lake):
    """Guard against a vacuous fixture: the actions really move the adjusted series on the later view."""
    late = MemoryAsOfView(open_lake(lake), DS[N - 1])
    for sym, i in (("SPLITCO", 190), ("BONUSCO", 240), ("BOTHCO", 290), ("GAPCO", 370)):
        raw, adj = late.raw_bars(sym, None), late.adjusted_bars(sym, None)
        assert adj["close_adj"].loc[DS[i]] != raw["close_raw"].loc[DS[i]]
    for sym, i in (("RIGHTSCO", 310), ("DEMERGCO", 340)):                       # rights and demerger never adjust
        assert late.adjusted_bars(sym, None)["close_adj"].loc[DS[i]] == late.raw_bars(sym, None)["close_raw"].loc[DS[i]]
    assert late.symbol_info("GAPCO").n_sessions == N - 40 and late.symbol_info("LATECO").n_sessions == N - 500


def test_the_switch_selects_the_view_and_defaults_to_sql(lake, monkeypatch):
    conn = open_lake(lake)
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)
    assert type(AsOfView(conn, DS[300])) is AsOfView
    monkeypatch.setenv("STOCKBOT_VIEW", "sql")
    assert type(AsOfView(conn, DS[300])) is AsOfView
    monkeypatch.setenv("STOCKBOT_VIEW", "memory")
    v = AsOfView(conn, DS[300])
    assert type(v) is MemoryAsOfView and isinstance(v, AsOfView) and v.as_of == DS[300]

    class Mine(AsOfView):                                                       # a subclass is built as itself (e.g. a script's own capped view)
        pass
    assert type(Mine(conn, DS[300])) is Mine


def test_the_memory_view_never_writes(lake):
    conn = open_lake(lake)
    MemoryAsOfView(conn, DS[300]).adjusted_bars("SPLITCO")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("delete from market_data_lake")
    before = (lake.stat().st_size, lake.stat().st_mtime_ns)
    MemoryAsOfView(open_lake(lake), DS[400]).eligible = None
    assert (lake.stat().st_size, lake.stat().st_mtime_ns) == before

"""non-eq-series (stage 2): the table and its guard class, the held-bar reads (SQL view and memory view), the never-buy rule in the shared engine, the stale rule with BE/BZ bars,
the BE/BZ sell model, the backfill script, and the proof that with the switch OFF nothing changes. Fixture lakes only (never finsight.db)."""
import ast
import csv
import hashlib
import random
import sqlite3
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from stockbot.data import guard
from stockbot.data import non_eq as NE
from stockbot.data.asof import AsOfView
from stockbot.data.asof_memory import MemoryAsOfView
from stockbot.data.guard.registry import DATED, RULES
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData, decide, held_bar_of
from stockbot.engine.exit_policy import Bar
from stockbot.engine.held_view import HeldView, exit_view
from stockbot.engine.path import simulate_ticket
from stockbot.engine.series_rule import blocking_series, is_buyable
from stockbot.engine.stepping import NON_EQ_SLIPPAGE_MULT, NON_EQ_VOLUME_CAP, _sellable, step_position
from stockbot.engine.types import Position, State, Ticket
from stockbot.risk.costs import CostModel
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec
from tests.fixtures.engine_run import CFG, policies, run_days
from tests.fixtures.lakefile import _make

ROOT = Path(__file__).resolve().parents[2]
DS = mini_lake.sessions()
SIG, ENTRY, CRASH = mini_lake.BREAKOUT, mini_lake.ENTRY, mini_lake.CRASH
NO_SECTOR = EventData()
COSTS = CostModel.from_shared(CFG.costs)
SLIP_OUT = CFG.execution.exit_slippage_pct / 100.0


@pytest.fixture(autouse=True)
def _no_switch(monkeypatch):
    monkeypatch.delenv("STOCKBOT_NON_EQ", raising=False)
    monkeypatch.delenv("STOCKBOT_VIEW", raising=False)


def held(monkeypatch):
    monkeypatch.setenv("STOCKBOT_NON_EQ", "held")


def lake_with_non_eq(tmp_path, move_from=None, series="BE", volume=None, name="lake.db", series_of=None):
    """The fixture lake; FIXCO's rows from session index ``move_from`` on move out of market_data_lake into market_data_non_eq (series ``series``, volume ``volume`` if given).
    ``series_of``: {session index: series} gives FIXCO a series per session instead (EQ stays in the lake)."""
    p = tmp_path / name
    _make(p)
    con = sqlite3.connect(p)
    con.executescript(NE.DDL)
    rows = con.execute("select symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake where symbol='FIXCO' order by trade_date").fetchall()
    for i, r in enumerate(rows):
        s = None
        if series_of is not None:
            s = series_of.get(i)
        elif move_from is not None and i >= move_from:
            s = series
        if s and s != "EQ":
            con.execute("delete from market_data_lake where symbol='FIXCO' and trade_date=?", (r[1],))
            con.execute(f"insert into {NE.TABLE}(symbol, trade_date, series, isin, open_raw, high_raw, low_raw, close_raw, prev_close, volume_raw, trades, traded_value, source_file) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("FIXCO", r[1], s, "INE000000001", r[2], r[3], r[4], r[5], None, int(volume if volume is not None else r[6]), 10, None, "fixture"))
    con.commit()
    con.close()
    return p


def strat(stop, day, sid="dummy", symbol="FIXCO"):
    return ScriptedStrategy(make_spec(sid), {DS[day].isoformat(): [{"symbol": symbol, "stop": stop}]})


# ================================================================================================ 1. the table and its guard class
def make_guarded(tmp_path):
    p = tmp_path / "g.db"
    con = sqlite3.connect(p, isolation_level=None)
    con.executescript((ROOT / "tests" / "fixtures" / "real_schema.sql").read_text(encoding="utf-8"))
    guard.install(con, seal="none")
    return p, con


def test_the_table_is_registered_dated_append_only_on_trade_date_and_has_its_triggers(tmp_path):
    r = RULES[NE.TABLE]
    assert r.cls == DATED and r.date_col == "trade_date" and r.key == ("symbol", "trade_date", "series")
    p, con = make_guarded(tmp_path)
    names = set(guard.core.existing_triggers(con))
    assert {f"g_{NE.TABLE}_{s}" for s in ("bi", "bu", "bd")} <= names
    assert guard.status(con)["tables"][NE.TABLE]["class"] == DATED


def test_a_sealed_day_of_the_table_cannot_be_changed_deleted_or_added_to(tmp_path):
    p, con = make_guarded(tmp_path)
    ins = f"INSERT INTO {NE.TABLE}(symbol,trade_date,series,open_raw,high_raw,low_raw,close_raw,volume_raw) VALUES (?,?,?,?,?,?,?,?)"
    con.execute(ins, ("AAA", "2020-01-01", "BE", 1, 2, 1, 2, 10))
    con.execute(ins, ("AAA", "2020-01-02", "BE", 1, 2, 1, 2, 10))
    guard.seal_table(con, NE.TABLE, "2020-01-02")
    for sql in (f"UPDATE {NE.TABLE} SET close_raw=5 WHERE symbol='AAA'", f"DELETE FROM {NE.TABLE} WHERE symbol='AAA'"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(ins, ("BBB", "2020-01-01", "BZ", 1, 2, 1, 2, 10))              # back-dated insert on a sealed day
    con.execute(ins, ("AAA", "2020-01-03", "BE", 1, 2, 1, 2, 10))                   # a later day is free until sealed
    assert guard.audit(con)["ok"]


# ================================================================================================ 2. held bars in the SQL view and the memory view
@pytest.mark.parametrize("view_cls", [AsOfView, MemoryAsOfView])
def test_held_bars_merge_eq_and_be_one_bar_per_day_while_eq_only_reads_stay_eq_only(tmp_path, monkeypatch, view_cls):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=310)
    con = open_lake(p)
    v = view_cls(con, DS[320])
    eq = v.raw_bars("FIXCO", lookback=None)
    hb = v.held_raw_bars("FIXCO", lookback=None)
    assert eq.index.max() == DS[309] and hb.index.max() == DS[320]               # EQ-only read stops where the stock left EQ; the held read goes on
    assert hb.index.is_unique and list(hb.index) == sorted(hb.index) and len(hb) == len(eq) + 11
    assert v.series_on("FIXCO") == "BE" and view_cls(con, DS[309]).series_on("FIXCO") == "EQ"
    assert "FIXCO" not in v.symbols_trading() and v.adtv("FIXCO", 20) is not None        # ADTV: the last 20 EQ bars only
    assert v.adtv("FIXCO", 20) == pytest.approx(open_lake(p) and view_cls(con, DS[309]).adtv("FIXCO", 20))
    adj = v.held_adjusted_bars("FIXCO", lookback=None)
    assert adj.index.equals(hb.index) and adj["close_adj"].iloc[-1] == pytest.approx(hb["close_raw"].iloc[-1])


def test_sql_and_memory_views_give_identical_held_answers(tmp_path, monkeypatch):
    held(monkeypatch)
    rng = random.Random(5)
    so = {i: rng.choice(["EQ", "BE", "BZ", "BE"]) for i in range(230, 330)}
    p = lake_with_non_eq(tmp_path, series_of=so)
    con = open_lake(p)
    for d in (DS[240], DS[260], DS[301], DS[329]):
        a, b = AsOfView(con, d), MemoryAsOfView(con, d)
        pd.testing.assert_frame_equal(a.held_raw_bars("FIXCO", lookback=None), b.held_raw_bars("FIXCO", lookback=None))
        pd.testing.assert_frame_equal(a.held_raw_bars("FIXCO", lookback=7), b.held_raw_bars("FIXCO", lookback=7))
        pd.testing.assert_frame_equal(a.held_adjusted_bars("FIXCO", lookback=40), b.held_adjusted_bars("FIXCO", lookback=40))
        assert a.series_on("FIXCO") == b.series_on("FIXCO") == so.get(DS.index(d), "EQ")
        assert a.symbols_trading() == b.symbols_trading()


@pytest.mark.parametrize("view_cls", [AsOfView, MemoryAsOfView])
def test_with_the_switch_off_the_held_methods_are_the_eq_methods_and_the_table_is_invisible(tmp_path, view_cls):
    p = lake_with_non_eq(tmp_path, move_from=310)
    con = open_lake(p)
    v = view_cls(con, DS[320])
    pd.testing.assert_frame_equal(v.held_raw_bars("FIXCO", lookback=None), v.raw_bars("FIXCO", lookback=None))
    pd.testing.assert_frame_equal(v.held_adjusted_bars("FIXCO", lookback=50), v.adjusted_bars("FIXCO", lookback=50))
    assert v.series_on("FIXCO") is None and view_cls(con, DS[309]).series_on("FIXCO") == "EQ"
    assert exit_view(v) is v


def test_bl_rows_never_form_a_bar_and_a_missing_table_is_an_empty_read(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=None)
    con = sqlite3.connect(p)
    con.execute(f"insert into {NE.TABLE}(symbol,trade_date,series,open_raw,high_raw,low_raw,close_raw,volume_raw) values ('FIXCO',?,'BL',1,1,1,1,5)", (DS[100].isoformat(),))
    con.commit(); con.close()
    c = open_lake(p)
    v = AsOfView(c, DS[329])
    assert v.held_raw_bars("FIXCO", lookback=None).loc[DS[100], "close_raw"] != 1                   # the EQ bar wins; BL is not a bar
    q = tmp_path / "plain.db"
    _make(q)                                                                                          # no non-EQ table at all
    assert open_lake(q) and AsOfView(open_lake(q), DS[329]).held_raw_bars("FIXCO", lookback=5).equals(AsOfView(open_lake(q), DS[329]).raw_bars("FIXCO", lookback=5))


# ================================================================================================ 3. the never-buy rule
def test_a_proposal_for_a_symbol_in_be_today_is_blocked_and_makes_no_ticket(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=ENTRY)
    decs, st = run_days(p, [DS[i] for i in range(ENTRY + 1, ENTRY + 5)], [strat(100.0, ENTRY + 2)], policies(FixedPolicy()), events=NO_SECTOR)
    d = decs[1]
    assert [b.reason for b in d.blocked if b.symbol == "FIXCO"] == ["NOT_EQ_SERIES"] and d.new_tickets == () and st.positions == ()


def test_a_ticket_made_on_an_eq_day_is_not_filled_when_the_stock_is_in_bz_on_the_fill_day(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=ENTRY, series="BZ")
    decs, st = run_days(p, [DS[SIG], DS[ENTRY]], [strat(150.0, SIG)], policies(FixedPolicy()), events=NO_SECTOR)
    assert len(decs[0].new_tickets) == 1                                                   # EQ on the signal day: a legitimate ticket
    assert [b.reason for b in decs[1].blocked] == ["NOT_EQ_SERIES_AT_FILL"] and decs[1].fills == () and st.positions == ()


def test_the_same_run_with_the_stock_in_eq_does_fill(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=None)
    decs, st = run_days(p, [DS[SIG], DS[ENTRY]], [strat(150.0, SIG)], policies(FixedPolicy()), events=NO_SECTOR)
    assert len(decs[1].fills) == 1 and len(st.positions) == 1


@pytest.mark.parametrize("seed", range(6))
def test_property_no_fill_ever_happens_on_a_day_the_stock_trades_outside_eq(tmp_path, monkeypatch, seed):
    """Random series per session for FIXCO, a strategy that proposes it EVERY day: every Fill's day is an EQ day of the stock."""
    held(monkeypatch)
    rng = random.Random(seed)
    so = {i: rng.choice(["EQ", "EQ", "BE", "BZ"]) for i in range(285, 330)}
    p = lake_with_non_eq(tmp_path, series_of=so, name=f"p{seed}.db")
    script = {DS[i].isoformat(): [{"symbol": "FIXCO", "stop": 120.0}] for i in range(285, 330)}
    s = ScriptedStrategy(make_spec("dummy"), script)
    decs, st = run_days(p, [DS[i] for i in range(285, 330)], [s], policies(FixedPolicy(max_days=2)), events=NO_SECTOR)
    fills = [f for d in decs for f in d.fills]
    assert fills, "the fixture must allow some fills for the property to mean anything"
    for f in fills:
        assert so.get(DS.index(f.date), "EQ") == "EQ"
    for d in decs:                                                                         # and a ticket is only ever created on an EQ day
        for t in d.new_tickets:
            assert so.get(DS.index(d.as_of), "EQ") == "EQ"


def test_the_baseline_path_applies_the_same_gate(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=ENTRY)
    con = open_lake(p)
    t = Ticket("t", "dummy", "FIXCO", None, DS[SIG], 176.0, 150.0, None, 100, 2600.0, 17600.0, DS[SIG], 0.0, {})
    out = simulate_ticket(t, DS[SIG:], lambda d: AsOfView(con, d), shared_config=CFG, policy=FixedPolicy(), equity=1_000_000.0)
    assert out[0] is None and out[2] == "NOT_EQ_SERIES_AT_FILL"


def test_series_rule_answers(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=ENTRY)
    con = open_lake(p)
    assert blocking_series(AsOfView(con, DS[ENTRY]), "FIXCO") == "BE" and not is_buyable(AsOfView(con, DS[ENTRY]), "FIXCO")
    assert is_buyable(AsOfView(con, DS[SIG]), "FIXCO") and is_buyable(AsOfView(con, DS[ENTRY]), "NOSUCH")
    assert blocking_series(object(), "X") is None                                          # a view without series information


def test_position_objects_are_built_only_where_a_fill_is_recorded():
    """Static: ``Position(`` is constructed only in engine/fills.py (the one engine fill, guarded by the series gate in decide/path), engine/reports.py (an operator-REPORTED fill) and types.py (deserialising)."""
    found = set()
    for f in (ROOT / "stockbot").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Position":
                found.add(f.relative_to(ROOT).as_posix())
    assert found == {"stockbot/engine/fills.py", "stockbot/engine/reports.py", "stockbot/engine/types.py"}, found
    for rel in ("stockbot/engine/decide.py", "stockbot/engine/path.py"):
        assert "blocking_series" in (ROOT / rel).read_text(encoding="utf-8")                # both fill paths use the one shared gate


# ================================================================================================ 4. held positions: marks, stops, stale rule
def entered(tmp_path, monkeypatch, *, move_from, stop=150.0, volume=None, on=True, upto=329, policy=None, name="lake.db"):
    if on:
        held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=move_from, volume=volume, name=name)
    decs, st = run_days(p, [DS[i] for i in range(SIG, upto + 1)], [strat(stop, SIG)], policies(policy or FixedPolicy()), events=NO_SECTOR)
    return decs, st


def test_a_held_position_is_marked_on_be_bars_and_not_stale_while_it_trades_in_be(tmp_path, monkeypatch):
    decs, st = entered(tmp_path, monkeypatch, move_from=303)                                # filled at 301 in EQ; BE from 303; 27 BE sessions follow
    closed = [c for d in decs for c in d.closed]
    assert not closed and len(st.positions) == 1 and st.positions[0].last_close == pytest.approx(158.0)   # marked at the last BE close (the fixture's last close 158)
    assert not any(f.code == "SYMBOL_NO_BARS" for d in decs for f in d.flags)


def test_with_the_switch_off_the_same_lake_is_stale_closed_after_20_sessions(tmp_path, monkeypatch):
    decs, st = entered(tmp_path, monkeypatch, move_from=303, on=False)
    (c,) = [c for d in decs for c in d.closed]
    assert c.exit_reason == "SYMBOL_NO_BARS" and c.exit_date == DS[302 + 20]


def test_a_stock_gone_from_every_series_is_still_stale_closed_with_the_switch_on(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=None)
    con = sqlite3.connect(p)
    con.execute("delete from market_data_lake where symbol='FIXCO' and trade_date>?", (DS[303].isoformat(),))
    con.commit(); con.close()
    decs, st = run_days(p, [DS[i] for i in range(SIG, 330)], [strat(150.0, SIG)], policies(FixedPolicy()), events=NO_SECTOR)
    (c,) = [c for d in decs for c in d.closed]
    assert c.exit_reason == "SYMBOL_NO_BARS"


def test_a_stop_is_hit_on_a_be_bar_and_sells_at_the_stop_rules_with_doubled_slippage(tmp_path, monkeypatch):
    # the crash session (160 open, 158 low) is a BE bar; stop 175 is above it: a gap through the stop
    decs, st = entered(tmp_path, monkeypatch, move_from=CRASH, stop=175.0, upto=CRASH + 2)
    ex = [e for d in decs for e in d.exits]
    assert [e.reason for e in ex] == ["STOP_HIT"] and ex[0].closed and st.positions == ()
    assert ex[0].price == pytest.approx(160.0 * (1 - NON_EQ_SLIPPAGE_MULT * SLIP_OUT), abs=1e-9)        # min(open, stop) = the open 160, exit slippage doubled


def test_the_volume_cap_splits_a_stop_exit_over_sessions_and_nothing_sells_on_a_locked_bar(tmp_path, monkeypatch):
    # volume 1000 shares/session -> at most 100 sold per session
    decs, st = entered(tmp_path, monkeypatch, move_from=CRASH, stop=175.0, volume=1000, upto=CRASH + 4)
    ex = [e for d in decs for e in d.exits]
    assert ex and all(e.shares <= 100 for e in ex) and all(e.reason in ("STOP_HIT",) for e in ex)
    assert len(st.positions) == 1 and st.positions[0].pending_exit > 0 and st.positions[0].shares_remaining == st.positions[0].shares_initial - sum(e.shares for e in ex)
    assert not any(e.closed for e in ex)


def test_the_eq_path_is_untouched_by_the_sell_model(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=None)
    decs, st = run_days(p, [DS[i] for i in range(SIG, CRASH + 2)], [strat(175.0, SIG)], policies(FixedPolicy()), events=NO_SECTOR)
    (e,) = [e for d in decs for e in d.exits]
    assert e.price == pytest.approx(160.0 * (1 - SLIP_OUT), abs=1e-9) and e.closed                     # single slippage, whole position, as before the change


# ================================================================================================ 5. the sell model on its own
def pos(shares=1000, stop=100.0):
    return Position(position_id="p", strategy_id="s", symbol="X", sector=None, entry_date=DS[0], entry_price=110.0, initial_stop=stop, live_stop=stop, target=None, shares_initial=float(shares),
                    shares_remaining=shares, risk_inr=shares * 10.0, exit_policy_id="fixed", highest_high=110.0, last_close=110.0, costs_paid=0.0)


def test_sellable_rules():
    assert NON_EQ_VOLUME_CAP == 0.10 and NON_EQ_SLIPPAGE_MULT == 2.0
    assert _sellable(Bar(1, 2, 1, 1.5, volume=10_000, series="BE"), 5000) == 1000
    assert _sellable(Bar(1, 2, 1, 1.5, volume=100_000, series="BE"), 5000) == 5000
    assert _sellable(Bar(1, 1, 1, 1, volume=800, series="BE"), 1000) == 0                    # single price, volume below the shares held: locked
    assert _sellable(Bar(1, 1, 1, 1, volume=5000, series="BE"), 1000) == 500                 # single price but liquid: the 10% cap only


def test_step_position_on_a_be_bar_sells_the_cap_and_queues_the_rest():
    bar = Bar(95.0, 96.0, 94.0, 95.0, volume=4000, series="BE")
    out = step_position(pos(1000), bar, DS[1], None, FixedPolicy(), COSTS, 0.1)
    assert [e.shares for e in out.exits] == [400] and not out.closed and out.position.pending_exit == 600 and out.position.pending_reason == "STOP_HIT"
    assert out.exits[0].price == pytest.approx(95.0 * (1 - 2 * 0.001))
    nxt = step_position(out.position, Bar(97.0, 98.0, 96.0, 97.0, volume=10_000, series="BE"), DS[2], None, FixedPolicy(), COSTS, 0.1)
    assert [e.shares for e in nxt.exits] == [600] and nxt.closed and nxt.exits[0].reason == "STOP_HIT" and nxt.exits[0].price == pytest.approx(97.0 * (1 - 2 * 0.001))


def test_step_position_on_an_eq_bar_is_unchanged():
    out = step_position(pos(1000), Bar(95.0, 96.0, 94.0, 95.0), DS[1], None, FixedPolicy(), COSTS, 0.1)
    assert [e.shares for e in out.exits] == [1000] and out.closed and out.exits[0].price == pytest.approx(95.0 * (1 - 0.001))


# ================================================================================================ 6. exit-policy view, manifest, hash
def test_the_exit_policy_view_reads_held_bars_only_with_the_switch_on(tmp_path, monkeypatch):
    p = lake_with_non_eq(tmp_path, move_from=310)
    con = open_lake(p)
    v = AsOfView(con, DS[320])
    assert exit_view(v) is v
    held(monkeypatch)
    ev = exit_view(v)
    assert isinstance(ev, HeldView) and ev.as_of == v.as_of
    pd.testing.assert_frame_equal(ev.adjusted_bars("FIXCO", lookback=30), v.held_adjusted_bars("FIXCO", lookback=30))
    assert ev.adjusted_bars("FIXCO", lookback=30).index.max() == DS[320] and v.adjusted_bars("FIXCO", lookback=30).index.max() == DS[309]


def test_held_bar_of_carries_series_and_volume_only_on_non_eq_days(tmp_path, monkeypatch):
    held(monkeypatch)
    p = lake_with_non_eq(tmp_path, move_from=310, volume=777)
    con = open_lake(p)
    b = held_bar_of(AsOfView(con, DS[311]), "FIXCO")
    assert b.series == "BE" and b.volume == 777.0
    e = held_bar_of(AsOfView(con, DS[305]), "FIXCO")
    assert e.series == "EQ" and e.volume == 0.0


def test_manifest_and_config_hash_the_switch_is_written_only_when_on_and_is_not_in_the_hash(monkeypatch):
    from stockbot.backtest.manifest import run_manifest
    kw = dict(shared_config=CFG, strategies=[], window=(date(2019, 1, 1), date(2019, 2, 1)), initial_equity=1e6, sha="x")
    off = run_manifest(**kw)
    held(monkeypatch)
    on = run_manifest(**kw)
    assert "non_eq_view" not in off and on["non_eq_view"]["switch"] == "STOCKBOT_NON_EQ=held" and on["non_eq_view"]["sell_model"]["volume_cap_per_session"] == 0.10
    assert on["shared_config_hash"] == off["shared_config_hash"]
    assert {k: v for k, v in on.items() if k != "non_eq_view"} == off


def test_run_record_includes_the_table_only_with_the_switch_on(tmp_path, monkeypatch):
    from stockbot.data.guard import runcheck
    p, con = make_guarded(tmp_path)
    con.execute(f"INSERT INTO {NE.TABLE}(symbol,trade_date,series,open_raw,high_raw,low_raw,close_raw,volume_raw) VALUES ('A','2020-01-01','BE',1,2,1,2,10)")
    guard.seal_table(con, NE.TABLE, "2020-01-01")
    assert NE.TABLE not in runcheck.guard_record(con)["tables"]
    held(monkeypatch)
    assert runcheck.guard_record(con)["tables"][NE.TABLE]["sealed_through"] == "2020-01-01"


# ================================================================================================ 7. switch OFF: nothing changes
def test_switch_off_decisions_are_identical_with_and_without_the_table(tmp_path):
    """Lake A: FIXCO leaves the lake after session 304 (no table). Lake B: the same lake plus market_data_non_eq holding FIXCO's later rows. Switch off: every Decisions object is equal."""
    a = tmp_path / "a.db"
    _make(a)
    ca = sqlite3.connect(a)
    ca.execute("delete from market_data_lake where symbol='FIXCO' and trade_date>?", (DS[304].isoformat(),))
    ca.commit(); ca.close()
    b = lake_with_non_eq(tmp_path, move_from=305, name="b.db")
    days = [DS[i] for i in range(SIG, 330)]
    da, sa = run_days(a, days, [strat(150.0, SIG)], policies(FixedPolicy()), events=NO_SECTOR)
    db, sb = run_days(b, days, [strat(150.0, SIG)], policies(FixedPolicy()), events=NO_SECTOR)
    assert da == db and sa == sb
    assert any(c.exit_reason == "SYMBOL_NO_BARS" for d in da for c in d.closed)


# ================================================================================================ 8. the backfill script
def raw_archive(tmp_path, bad_hash=False):
    raw = tmp_path / "raw"
    (raw / "2020").mkdir(parents=True)
    legacy = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
              "AAA,EQ,10,11,9,10.5,10.5,10,100,1000,{d},5,INE000000011,\nBBB,BE,20,21,19,20.5,20.5,20,200,4000,{d},7,INE000000022,\nCCC,BZ,30,31,29,30.5,30.5,30,300,9000,{d},9,INE000000033,\n"
              "CCC,BL,30,30,30,30,30,30,50,1500,{d},1,INE000000033,\nDDD,SM,5,6,4,5,5,5,10,50,{d},1,INE000000044,\n")
    rows = []
    for d, name in (("02-JAN-2020", "cm02JAN2020bhav.csv.zip"), ("03-JAN-2020", "cm03JAN2020bhav.csv.zip")):
        zp = raw / "2020" / name
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr(name.replace(".zip", ""), legacy.format(d=d))
        h = hashlib.sha256(zp.read_bytes()).hexdigest()
        rows.append({"date": datetime_iso(d), "file_name": name, "url": "u", "bytes": zp.stat().st_size, "sha256": ("0" * 64) if bad_hash and d.startswith("03") else h, "pattern": "LEGACY", "status": "OK"})
    with open(raw / "MANIFEST.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return raw


def datetime_iso(d):
    return date(int(d[7:]), {"JAN": 1}[d[3:6]], int(d[:2])).isoformat()


def run_backfill(db, raw, *extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "backfill_non_eq.py"), "--db", str(db), "--raw", str(raw), "--end", "2020-01-03", *extra], capture_output=True, text=True)


def test_backfill_loads_only_be_bz_bl_counts_per_day_seals_and_the_guard_protects_it(tmp_path):
    p, con = make_guarded(tmp_path)
    con.close()
    r = run_backfill(p, raw_archive(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    con = sqlite3.connect(p)
    assert con.execute(f"select series, count(*) from {NE.TABLE} group by series order by series").fetchall() == [("BE", 2), ("BL", 2), ("BZ", 2)]
    assert con.execute(f"select count(*) from {NE.TABLE} where series in ('EQ','SM')").fetchone()[0] == 0
    assert con.execute("select sealed_through from _guard_seal where tbl=?", (NE.TABLE,)).fetchone()[0] == "2020-01-03"
    assert con.execute(f"select isin, traded_value, source_file from {NE.TABLE} where symbol='BBB' and trade_date='2020-01-02'").fetchone() == ("INE000000022", 4000.0, "cm02JAN2020bhav.csv.zip")
    assert con.execute("select count(*) from market_data_lake").fetchone()[0] == 0                   # the lake is never written
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(f"delete from {NE.TABLE}")
    r2 = run_backfill(p, tmp_path / "raw")
    assert r2.returncode == 2 and "already holds" in r2.stdout                                       # never loads twice


def test_backfill_refuses_a_file_whose_sha256_differs_from_the_manifest_before_writing(tmp_path):
    p, con = make_guarded(tmp_path)
    con.close()
    r = run_backfill(p, raw_archive(tmp_path, bad_hash=True))
    assert r.returncode == 2 and "sha256" in r.stdout
    con = sqlite3.connect(p)
    assert con.execute(f"select count(*) from {NE.TABLE}").fetchone()[0] == 0


def test_parse_rows_handles_the_three_layouts(tmp_path):
    full = tmp_path / "sec_bhavdata_full_13072020.csv"
    full.write_text(" SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
                    " AAA, EQ, 13-Jul-2020, 10, 10, 11, 9, 10, 10.5, 10, 100, 2.50, 5, 50, 50\n BBB, BE, 13-Jul-2020, 20, 20, 21, 19, 20, 20.5, 20, 200, 4.00, 7, 200, 100\n", encoding="utf-8")
    (r,) = NE.parse_rows(full, date(2020, 7, 13), full.name)
    assert r[0] == "BBB" and r[2] == "BE" and r[3] is None and r[11] == pytest.approx(400000.0) and r[9] == 200       # the full file has no ISIN column and turnover in lacs
    udiff = tmp_path / "u.csv"
    udiff.write_text("TradDt,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,PrvsClsgPric,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,ISIN\n2026-01-01,ZZZ,BZ,5,6,4,5.5,5,40,220,3,INE000000099\n", encoding="utf-8")
    (r,) = NE.parse_rows(udiff, date(2026, 1, 1), "u.csv")
    assert r[:4] == ("ZZZ", "2026-01-01", "BZ", "INE000000099") and r[11] == 220.0 and NE.file_series_count(udiff) == 1

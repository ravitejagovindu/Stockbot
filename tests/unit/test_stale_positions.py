"""stale-positions: symbol links (data layer) and the no-bars exit (engine), on fixture lakes only (never finsight.db).

A. links: the Links table, the builder (scripts/build_symbol_links.py) and the as-of views (SQL = memory) with the link switch on and off.
B. engine: SYMBOL_NO_BARS closure after ``engine.stale_exit_sessions`` sessions without a bar, the baseline's identical closure, the stress line.
C. live: the same decision is an explicit flag in the session file.
D. a run with no linked and no stale symbol is identical to the behaviour before these rules.
"""
import dataclasses
import json
import sqlite3
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine

from stockbot.config.shared import load_shared_config
from stockbot.data import symbol_links
from stockbot.data.asof import AsOfView
from stockbot.data.asof_memory import MemoryAsOfView
from stockbot.data.db.connection import Base
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData, decide
from stockbot.engine.path import simulate_ticket
from stockbot.engine.stale import no_bars_for, stale_detail
from stockbot.engine.types import State, Ticket
from stockbot.live.runner import write_tickets
from stockbot.risk.costs import CostModel
from stockbot.universe.eligibility import eligible_symbols
from tests.fixtures import mini_lake
from tests.fixtures.dummies import FixedPolicy, ScriptedStrategy, make_spec

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
CFG = load_shared_config()
DS = mini_lake.sessions(400)
SLIP_OUT = CFG.execution.exit_slippage_pct / 100.0
COSTS = CostModel.from_shared(CFG.costs)
SIG = 300                                     # signal session of the scripted entry; the fill is at session 301


def bars(level):
    return (level, level * 1.01, level * 0.99, level * 1.005)


def make_lake(path, series, actions=(), n=400, volume=5_000_000):
    """series: {symbol: {session_index: (o, h, l, c) or a plain level}}; actions: [(symbol, session_index_or_date, type, num, den, notes)]. NIFTY50_INDEX trades every session."""
    eng = create_engine(f"sqlite:///{Path(path).as_posix()}")
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path)
    rows = [("NIFTY50_INDEX", DS[i].isoformat(), *bars(10000.0 + 4 * i), 0) for i in range(n)]
    for sym, d in series.items():
        for i, b in d.items():
            o, h, l, c = bars(b) if isinstance(b, (int, float)) else b
            rows.append((sym, DS[i].isoformat(), o, h, l, c, volume))
    con.executemany("insert into market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange) values (?,?,?,?,?,?,?,'NSE')", rows)
    for sym, when, typ, num, den, notes in actions:
        ex = DS[when] if isinstance(when, int) else when
        con.execute("insert into corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, notes, source, evidence_tier) values (?,?,?,?,?,?,?,?)",
                    (sym, ex.isoformat(), typ, num, den, notes, "test", "T1"))
    con.commit()
    con.close()
    return Path(path)


def run(lake, days, strategies, *, state=None, cfg=CFG, mode="backtest", events=EventData()):
    conn = open_lake(lake)
    st = state if state is not None else State.initial(1_000_000.0)
    decs = []
    pol = {"fixed": FixedPolicy()}
    for d in days:
        dec, st = decide(d, st, AsOfView(conn, d), strategies, cfg, events, policies=pol, strict=True, mode=mode)
        decs.append(dec)
    return decs, st


def scripted(symbol, *days, stop=90.0):
    return ScriptedStrategy(make_spec("dummy"), {DS[i].isoformat(): [{"symbol": symbol, "stop": stop}] for i in days})


FULL = {i: 100.0 for i in range(400)}


def lake_terminal(tmp_path, last=310, resume=None):
    """STALE trades sessions 0..last (and again from ``resume``); a second name, NEWCO, trades every session (for the slot test)."""
    s = {i: 100.0 for i in range(0, last + 1)}
    if resume is not None:
        s.update({i: 100.0 for i in range(resume, 400)})
    return make_lake(tmp_path / "lake.db", {"STALE": s, "NEWCO": dict(FULL)})


def closed_of(decs):
    return [c for d in decs for c in d.closed]


# ================================================================================================================ A. the link table
def test_links_chain_resolves_to_the_latest_symbol_and_rejects_ambiguity():
    L = symbol_links.Links([("A", "B"), ("B", "C"), ("X", "Y")])
    assert L.resolve("A") == L.resolve("B") == L.resolve("C") == "C" and L.resolve("Y") == "Y" and L.resolve("Q") == "Q"
    assert L.members("B") == ("A", "B", "C") and L.members("X") == ("X", "Y") and L.members("Q") == ()
    for bad in ([("A", "B"), ("A", "C")], [("A", "C"), ("B", "C")], [("A", "A")], [("A", "B"), ("B", "A")]):
        with pytest.raises(ValueError):
            symbol_links.Links(bad)


def test_links_switch_and_override():
    L = symbol_links.Links([("OLD", "NEW")])
    with symbol_links.override(enabled=True, links=L):
        assert symbol_links.resolve("OLD") == "NEW" and symbol_links.members("NEW") == ("OLD", "NEW")
    with symbol_links.override(enabled=False, links=L):
        assert symbol_links.active() is None and symbol_links.resolve("OLD") == "OLD" and symbol_links.members("OLD") == ()
    assert symbol_links.enabled() is CFG.data.symbol_links_enabled


# ================================================================================================================ A1: the builder
def test_builder_links_only_what_the_rules_allow(tmp_path):
    import build_symbol_links as B
    series = {"AAA": {i: 100.0 for i in range(0, 200)}, "BBB": {i: 101.0 for i in range(201, 400)},                              # 1 session after, ratio 1.01: linked
              "CCC": {i: 100.0 for i in range(0, 200)}, "DDD": {i: 100.0 for i in range(206, 400)},                                # 7 sessions after: not linked
              "EEE": {i: 100.0 for i in range(0, 200)}, "FFF": {i: 200.0 for i in range(201, 400)},                                # ratio 2.0: not linked
              "GGG": {i: 100.0 for i in range(0, 220)}, "HHH": {i: 100.0 for i in range(200, 400)},                                # overlapping bars: not linked
              "III": {i: 100.0 for i in range(0, 200)}, "JJJ": {i: 100.0 for i in range(201, 400)},                                # map says 'other': not linked
              "KKK": {i: 100.0 for i in range(0, 100)}, "LLL": {i: 100.0 for i in range(102, 250)}, "MMM": {i: 100.0 for i in range(252, 400)},   # chain K -> L -> M (2 sessions each)
              "NNN": {i: 100.0 for i in range(0, 200)}, "OOO": {i: 20.0 for i in range(201, 400)}}                                 # 1:5 split ex on the new first bar: ratio after factor ~1: linked
    lake = make_lake(tmp_path / "b.db", series, actions=[("NNN", 201, "SPLIT", 1, 5, "")])
    rows = []
    for isin, a, b, typ in [("I1", "AAA", "BBB", "pure_rename"), ("I2", "CCC", "DDD", "pure_rename"), ("I3", "EEE", "FFF", "pure_rename"), ("I4", "GGG", "HHH", "pure_rename"),
                            ("I5", "III", "JJJ", "other"), ("I7", "NNN", "OOO", "pure_rename")]:
        rows += [{"isin": isin, "symbol": a, "segment": 1, "boundary_to_next": typ, "boundary_reason": "x"}, {"isin": isin, "symbol": b, "segment": 2, "boundary_to_next": "", "boundary_reason": ""}]
    rows += [{"isin": "I6", "symbol": "KKK", "segment": 1, "boundary_to_next": "pure_rename", "boundary_reason": "x"}, {"isin": "I6", "symbol": "LLL", "segment": 2, "boundary_to_next": "pure_rename", "boundary_reason": "x"},
             {"isin": "I6", "symbol": "MMM", "segment": 3, "boundary_to_next": "", "boundary_reason": ""}]
    links, notl = B.build(str(lake), pd.DataFrame(rows))
    got = {(r.old_symbol, r.new_symbol): r.latest_symbol for r in links.itertuples()}
    assert got == {("AAA", "BBB"): "BBB", ("KKK", "LLL"): "MMM", ("LLL", "MMM"): "MMM", ("NNN", "OOO"): "OOO"}
    why = {(r.old_symbol, r.new_symbol): r.reason for r in notl.itertuples()}
    assert "7 sessions" in why[("CCC", "DDD")] and "outside" in why[("EEE", "FFF")] and "overlapping" in why[("GGG", "HHH")] and "other" in why[("III", "JJJ")]
    nn = links[links.old_symbol == "NNN"].iloc[0]
    assert nn.split_bonus_factor == pytest.approx(0.2) and nn.boundary_ratio_after_factor == pytest.approx(1.0, abs=0.06) and int(nn.sessions_between) == 2
    assert links[links.old_symbol == "AAA"].iloc[0].boundary_ratio_after_factor == pytest.approx(1.01)


def test_committed_link_file_rules_hold():
    """Every row of data/reference/symbol_links.csv satisfies the owner's numbers; PHILIPCARB -> PCBL is linked."""
    L = pd.read_csv(ROOT / "data/reference/symbol_links.csv")
    assert len(L) and L.sessions_between.between(1, 5).all() and L.boundary_ratio_after_factor.between(0.80, 1.25).all() and (L.old_last_bar < L.new_first_bar).all()
    assert not L.duplicated("old_symbol").any() and not L.duplicated("new_symbol").any()
    assert ((L.old_symbol == "PHILIPCARB") & (L.new_symbol == "PCBL")).any()
    N = pd.read_csv(ROOT / "data/reference/symbol_links_not_linked.csv")
    assert not (set(zip(L.old_symbol, L.new_symbol)) & set(zip(N.old_symbol, N.new_symbol))) and N.reason.notna().all()


# ================================================================================================================ A2/A3: the views
def lake_renamed(tmp_path, with_actions=True):
    """OLDCO trades 0..310 at 100 and NEWCO 311..399 at 101 (a rename); OLDCO has a 1:5 split whose ex-date is its LAST bar (already post-split: raw closes before it are 5x), the same split is
    also filed under NEWCO (once-only test) and a bonus is filed under OTHERCO with a note naming NEWCO."""
    old = {i: (500.0 if i < 310 else 100.0) for i in range(0, 311)}
    new = {i: 101.0 for i in range(311, 400)}
    acts = [("OLDCO", 310, "SPLIT", 1, 5, "feed_symbol=NEWCO; face value split"), ("NEWCO", 310, "SPLIT", 1, 5, ""), ("OTHERCO", 350, "BONUS", 1, 1, "feed_symbol=NEWCO; bonus"),
            ("OLDCO", 100, "DIVIDEND", None, None, "")] if with_actions else []
    return make_lake(tmp_path / "ren.db", {"OLDCO": old, "NEWCO": new, "OTHERCO": dict(FULL), "PLAIN": dict(FULL)}, actions=acts)


LINKS = symbol_links.Links([("OLDCO", "NEWCO")])


def test_linked_stock_is_one_symbol_under_its_latest_name(tmp_path):
    lake = lake_renamed(tmp_path)
    conn = open_lake(lake)
    with symbol_links.override(enabled=True, links=LINKS):
        v = AsOfView(conn, DS[320])
        assert v.resolve_symbol("OLDCO") == v.resolve_symbol("NEWCO") == "NEWCO" and v.resolve_symbol("PLAIN") == "PLAIN"
        b = v.raw_bars("NEWCO", lookback=None)
        assert len(b) == 311 + 10 and b.index.is_unique and b.index.is_monotonic_increasing and v.raw_bars("OLDCO", lookback=None).equals(b)         # alias, no duplicate or dropped session
        assert [d for d in b.index][:2] == [DS[0], DS[1]] and b.index[-1] == DS[320] and b.index[310] == DS[310] and b.index[311] == DS[311]
        # a query as of D returns only rows up to D: before the rename NEWCO is just OLDCO's bars
        assert AsOfView(conn, DS[200]).raw_bars("NEWCO", lookback=None).index[-1] == DS[200]
        # the split on the boundary date is applied exactly once (filed under OLDCO and NEWCO): adjusted closes are continuous across the boundary
        acts = v.corporate_actions("NEWCO")
        assert [(a["ex_date"], a["action_type"]) for a in acts] == [(DS[100], "DIVIDEND"), (DS[310], "SPLIT")]                   # one SPLIT; the later bonus (ex 350) is not known at 320
        adj = v.adjusted_bars("NEWCO", lookback=None)["close_adj"]
        assert adj.loc[DS[309]] == pytest.approx(500.0 * 1.005 * 0.2) and adj.loc[DS[310]] == pytest.approx(100.5)
        assert adj.loc[DS[311]] / adj.loc[DS[310]] == pytest.approx(101.505 / 100.5)                                              # ratio at the boundary ~1 (not 5, not 0.2, not 0.04)
        # rows filed under another symbol whose note names a name of the chain count (and only once known)
        late = AsOfView(conn, DS[360]).corporate_actions("NEWCO")
        assert [(a["ex_date"], a["action_type"]) for a in late][-1] == (DS[350], "BONUS")
        # symbols trading: the stock appears once, under its latest name, before and after the rename
        assert "NEWCO" in AsOfView(conn, DS[200]).symbols_trading() and "OLDCO" not in AsOfView(conn, DS[200]).symbols_trading()
        assert AsOfView(conn, DS[320]).symbols_trading().count("NEWCO") == 1
    with symbol_links.override(enabled=False):                                                                                    # switch off: the old behaviour, symbol by symbol
        v = AsOfView(conn, DS[320])
        assert v.resolve_symbol("OLDCO") == "OLDCO" and len(v.raw_bars("NEWCO", lookback=None)) == 10 and v.raw_bars("OLDCO", lookback=None).index[-1] == DS[310]
        assert "OLDCO" not in v.symbols_trading() and "NEWCO" in v.symbols_trading()


def test_listing_age_adtv_and_eligibility_carry_over_the_rename(tmp_path):
    lake = lake_renamed(tmp_path, with_actions=False)
    conn = open_lake(lake)
    d = DS[312]
    with symbol_links.override(enabled=True, links=LINKS):
        v = AsOfView(conn, d)
        info = v.symbol_info("NEWCO")
        assert info.first_date == DS[0] and info.n_sessions == 311 + 2 and info.listing_age_days >= 252
        assert v.adtv("NEWCO") is not None and "NEWCO" in eligible_symbols(v, CFG.universe)
        assert dataclasses.replace(v.symbol_info("OLDCO"), symbol="NEWCO") == info                                   # any name of the chain answers the same
    with symbol_links.override(enabled=False):
        v = AsOfView(conn, d)
        assert v.symbol_info("NEWCO").n_sessions == 2 and v.symbol_info("NEWCO").listing_age_days == 2 and v.adtv("NEWCO") is None and "NEWCO" not in eligible_symbols(v, CFG.universe)


def test_sector_follows_the_link(monkeypatch):
    from stockbot.data import sector_map
    monkeypatch.setattr(sector_map, "_load", lambda: {"OLDCO": "IT", "OTHER": "BANKS"})
    with symbol_links.override(enabled=True, links=LINKS):
        assert sector_map.sector_for("NEWCO") == "IT" and sector_map.sector_for("OLDCO") == "IT" and sector_map.sector_for("ZZZ") == "UNMAPPED:ZZZ"
    with symbol_links.override(enabled=True, links=symbol_links.Links([("QQQ", "RRR")])):
        assert sector_map.sector_for("QQQ") == "UNMAPPED:RRR"                                   # an unmapped linked stock is ONE sector under its latest name
    with symbol_links.override(enabled=False):
        assert sector_map.sector_for("NEWCO") == "UNMAPPED:NEWCO"


def _view_state(v, syms):
    out = {"trading": v.symbols_trading(), "sessions": v.sessions(lookback=5)}
    for s in syms:
        out[s] = (v.raw_bars(s, lookback=30), v.raw_bars(s, lookback=None), v.adjusted_bars(s, lookback=50), v.corporate_actions(s), v.symbol_info(s), v.adtv(s), v.resolve_symbol(s))
    out["eligible"] = eligible_symbols(v, CFG.universe)
    return out


def _same(a, b):
    assert a.keys() == b.keys()
    for k in a:
        x, y = a[k], b[k]
        if isinstance(x, tuple):
            for p, q in zip(x, y):
                if isinstance(p, pd.DataFrame):
                    pd.testing.assert_frame_equal(p, q)
                else:
                    assert p == q, (k, p, q)
        else:
            assert x == y, k


@pytest.mark.parametrize("enabled", [True, False])
def test_sql_view_equals_memory_view(tmp_path, enabled):
    lake = lake_renamed(tmp_path)
    conn = open_lake(lake)
    syms = ["OLDCO", "NEWCO", "OTHERCO", "PLAIN", "NIFTY50_INDEX", "MISSING"]
    with symbol_links.override(enabled=enabled, links=LINKS):
        for i in (5, 120, 305, 310, 311, 312, 330, 351, 399):
            _same(_view_state(_plain_sql(conn, DS[i]), syms), _view_state(MemoryAsOfView(conn, DS[i]), syms))


def _plain_sql(conn, d):
    v = object.__new__(AsOfView)
    v.__init__(conn, d)
    return v


# ================================================================================================================ B. the no-bars exit
def test_terminal_symbol_is_closed_on_the_20th_session_without_a_bar(tmp_path):
    lake = lake_terminal(tmp_path)
    decs, st = run(lake, DS[299:345], [scripted("STALE", SIG)])
    (t,) = closed_of(decs)
    last_bar = 310
    assert t.exit_reason == "SYMBOL_NO_BARS" and t.exit_date == DS[last_bar + 20] and t.symbol == "STALE" and not t.excluded_ca
    (fill,) = [f for d in decs for f in d.fills]
    (e,) = [x for d in decs for x in d.exits]
    last_close = bars(100.0)[3]
    assert e.price == pytest.approx(last_close * (1 - SLIP_OUT)) and e.date == DS[last_bar + 20] and e.closed
    sell = COSTS.sell_cost(e.price * e.shares)
    assert e.cost == pytest.approx(sell) and t.net_pnl == pytest.approx((e.price - fill.price) * fill.shares - fill.cost - sell)
    assert st.positions == () and st.cash == pytest.approx(1_000_000.0 + t.net_pnl)
    # nothing before the 20th session; the 19 sessions before it only flag the position
    before = [d for d in decs if DS[last_bar] < d.as_of < DS[last_bar + 20]]
    assert len(before) == 19 and not any(d.closed for d in before) and all(any(f.code == "NO_BAR_POSITION_NOT_STEPPED" for f in d.flags) for d in before)
    d20 = [d for d in decs if d.as_of == DS[last_bar + 20]][0]
    (fl,) = [f for f in d20.flags if f.code == "SYMBOL_NO_BARS"]
    assert fl.detail == stale_detail("STALE", 20) == "position STALE: no bars for 20 sessions; closed in the book at the last close; check the holding manually (rename, merger, suspension, series change)"
    assert not any(d.new_tickets for d in decs[decs.index(d20):])                                # nothing re-opens


def test_a_gap_that_resumes_after_30_sessions_still_closes_on_the_20th_and_nothing_reopens(tmp_path):
    lake = lake_terminal(tmp_path, last=310, resume=341)
    decs, st = run(lake, DS[299:380], [scripted("STALE", SIG)])
    (t,) = closed_of(decs)
    assert t.exit_reason == "SYMBOL_NO_BARS" and t.exit_date == DS[330] and st.positions == ()
    assert len([f for d in decs for f in d.fills]) == 1                                          # bars resumed at 341: no new position


def test_19_missing_sessions_do_not_close(tmp_path):
    lake = lake_terminal(tmp_path, last=310, resume=330)                                         # missing 311..329 = 19 sessions
    decs, st = run(lake, DS[299:345], [scripted("STALE", SIG)])
    assert not closed_of(decs) and len(st.positions) == 1 and st.positions[0].symbol == "STALE"
    assert not any(f.code == "SYMBOL_NO_BARS" for d in decs for f in d.flags)
    assert st.positions[0].days_held > 11                                                        # stepped again once the bars came back
    conn = open_lake(lake)
    assert not no_bars_for(AsOfView(conn, DS[329]), "STALE", 20) and no_bars_for(AsOfView(conn, DS[329]), "STALE", 19) and not no_bars_for(AsOfView(conn, DS[330]), "STALE", 20)


def test_the_closure_frees_the_slot_for_the_same_session(tmp_path):
    cfg = dataclasses.replace(CFG, portfolio_risk=dataclasses.replace(CFG.portfolio_risk, max_concurrent_positions=1))
    lake = lake_terminal(tmp_path)
    strat = ScriptedStrategy(make_spec("dummy"), {DS[SIG].isoformat(): [{"symbol": "STALE", "stop": 90.0}], DS[329].isoformat(): [{"symbol": "NEWCO", "stop": 90.0}],
                                                 DS[330].isoformat(): [{"symbol": "NEWCO", "stop": 90.0}]})
    decs, st = run(lake, DS[299:340], [strat], cfg=cfg)
    by = {d.as_of: d for d in decs}
    assert [b.reason for b in by[DS[329]].blocked if b.symbol == "NEWCO"] and not by[DS[329]].new_tickets                # slot still taken on session 329
    assert [t.symbol for t in by[DS[330]].new_tickets] == ["NEWCO"] and by[DS[330]].closed[0].exit_reason == "SYMBOL_NO_BARS"
    assert [p.symbol for p in st.positions] == ["NEWCO"]                                                                 # filled at session 331


def test_renamed_symbol_held_across_the_rename_is_not_stale_exited(tmp_path):
    old = {i: 100.0 for i in range(0, 311)}
    new = {i: 100.0 for i in range(311, 400)}
    new[320] = (100.0, 101.0, 80.0, 90.0)                                                                                # the new name's bar crashes through the stop
    lake = make_lake(tmp_path / "r.db", {"OLDCO": old, "NEWCO": new}, actions=[])
    with symbol_links.override(enabled=True, links=LINKS):
        decs, st = run(lake, DS[299:345], [scripted("NEWCO", SIG)])
        (t,) = closed_of(decs)
        assert t.exit_reason == "STOP_HIT" and t.exit_date == DS[320] and t.symbol == "NEWCO" and not any(f.code == "SYMBOL_NO_BARS" for d in decs for f in d.flags)
        assert not any(f.code == "NO_BAR_POSITION_NOT_STEPPED" for d in decs for f in d.flags)                             # a bar existed every session across the boundary
    with symbol_links.override(enabled=False):                                                                           # without the link the same position goes stale
        decs2, _ = run(lake, DS[299:345], [scripted("OLDCO", SIG)])
        (t2,) = closed_of(decs2)
        assert t2.exit_reason == "SYMBOL_NO_BARS" and t2.exit_date == DS[330]


def test_a_position_carried_under_the_old_name_continues_on_the_new_names_bars(tmp_path):
    """State written before the link existed (position under OLDCO) is resolved through the link: stepped on NEWCO's bars, no duplicate holding of the same stock."""
    old = {i: 100.0 for i in range(0, 311)}
    new = {i: 100.0 for i in range(311, 400)}
    new[320] = (100.0, 101.0, 80.0, 90.0)
    lake = make_lake(tmp_path / "r2.db", {"OLDCO": old, "NEWCO": new}, actions=[])
    with symbol_links.override(enabled=False):
        decs, st = run(lake, DS[299:306], [scripted("OLDCO", SIG)])
    assert [p.symbol for p in st.positions] == ["OLDCO"]
    with symbol_links.override(enabled=True, links=LINKS):
        decs2, st2 = run(lake, DS[306:345], [scripted("NEWCO", 309)], state=st)
        (t,) = closed_of(decs2)
        assert t.symbol == "OLDCO" and t.exit_reason == "STOP_HIT" and t.exit_date == DS[320]
        assert [(b.reason, b.stage) for d in decs2 for b in d.blocked if b.symbol == "NEWCO"] == [("ALREADY_HELD", "risk")]                    # the new-name proposal of session 309 would be a second holding of the same stock
        assert not [f for d in decs2 for f in d.fills] and st2.positions == ()


def test_baseline_draw_closes_the_same_way(tmp_path):
    lake = lake_terminal(tmp_path)
    conn = open_lake(lake)
    decs, _ = run(lake, DS[299:345], [scripted("STALE", SIG)])
    (engine_trade,) = closed_of(decs)
    t = Ticket("rand:STALE", "random", "STALE", None, DS[SIG], 100.5, 90.0, None, 0, 0.0, 0.0, DS[SIG])
    trade, exits, why = simulate_ticket(t, DS[299:345], lambda d: AsOfView(conn, d), shared_config=CFG, policy=FixedPolicy(), equity=1_000_000.0)
    assert why == "CLOSED" and trade.exit_reason == "SYMBOL_NO_BARS" and trade.exit_date == DS[330] and exits[-1].reason == "SYMBOL_NO_BARS"
    assert trade.exit_date == engine_trade.exit_date and trade.entry_price == pytest.approx(engine_trade.entry_price)
    # before the 20th session the path is still open (not a closed draw)
    t2, _, why2 = simulate_ticket(t, DS[299:329], lambda d: AsOfView(conn, d), shared_config=CFG, policy=FixedPolicy(), equity=1_000_000.0)
    assert t2 is None and why2 == "OPEN_AT_END"


def test_gates_count_the_stale_exit_as_usable_and_report_the_stress_line():
    import evaluate_validation_gates_near_52w_high as G
    trade = {"position_id": "dummy:STALE:2024-01-03", "strategy_id": "dummy", "symbol": "STALE", "entry_date": "2024-01-03", "exit_date": "2024-03-01", "entry_price": 100.0, "initial_stop": 90.0,
             "shares_initial": 100.0, "risk_inr": 1000.0, "gross_pnl": 1000.0, "costs": 50.0, "net_pnl": 950.0, "exit_reason": "SYMBOL_NO_BARS", "excluded_ca": False}
    assert G.trade_table([trade])["usable"].tolist() == [True]                                    # usable like any other trade (only excluded_ca and END_OF_WINDOW are not)
    idx = pd.Index([date(2024, 2, 28), date(2024, 3, 1), date(2024, 3, 4)])
    run_ = {"manifest": {}, "trades": [trade], "equity": pd.Series([1_000_950.0, 1_000_950.0, 1_000_950.0], index=idx), "daily": (pd.Series([1_000_950.0] * 3, index=idx), pd.Series([900_000.0, 1_000_950.0, 1_000_950.0], index=idx))}
    price = 110.0                                                                                 # gross 1000 = (110 - 100) x 100
    last_close = price / (1 - SLIP_OUT)
    stressed = 0.5 * last_close
    s = G.stress_run(run_, 0.5, CFG)
    (st,) = s["trades"]
    gross2 = 1000.0 - (price - stressed) * 100.0
    costs2 = 50.0 - COSTS.sell_cost(price * 100.0) + COSTS.sell_cost(stressed * 100.0)
    assert st["gross_pnl"] == pytest.approx(gross2) and st["costs"] == pytest.approx(costs2) and st["net_pnl"] == pytest.approx(gross2 - costs2)
    delta = (gross2 - costs2) - 950.0
    assert s["equity"].tolist() == pytest.approx([1_000_950.0, 1_000_950.0 + delta, 1_000_950.0 + delta]) and s["daily"][1].tolist()[0] == 900_000.0 and s["daily"][1].tolist()[1] == pytest.approx(1_000_950.0 + delta)
    assert run_["trades"][0]["net_pnl"] == 950.0                                                  # the input is not touched
    seen = []

    def fake_eval(r, nifty, gates, **kw):
        seen.append(r)
        return {"gates": [{"gate": "x", "comparison": ">=", "gate_value": 1.0, "observed": 0.5, "interval": None, "met": False}], "all_met": False, "alpha": {"cash_credited": {"alpha_pct": -1.0}}}
    rep = G.stale_exit_report(run_, None, {}, fake_eval, shared_config=CFG)
    assert rep["trades"] == 1 and rep["net_pnl_total"] == 950.0 and rep["list"][0]["symbol"] == "STALE"
    assert rep["stress"]["label"] == "stress, not a gate" and rep["stress"]["factor"] == 0.5 and seen[0]["trades"][0]["net_pnl"] == pytest.approx(gross2 - costs2)
    assert G.stale_exit_report({**run_, "trades": []}, None, {}, fake_eval, shared_config=CFG) ["trades"] == 0 and "stress" not in G.stale_exit_report({**run_, "trades": []}, None, {}, fake_eval, shared_config=CFG)
    text = "\n".join(G.stale_exit_lines(rep))
    assert "STRESS (stress, not a gate)" in text and "STALE" in text


def test_run_files_carry_the_stale_fields_only_for_stale_trades(tmp_path):
    from stockbot.backtest.outputs import trade_records
    lake = lake_terminal(tmp_path)
    decs, _ = run(lake, DS[299:345], [scripted("STALE", SIG)])
    res = types.SimpleNamespace(trades=tuple(closed_of(decs)), decisions=tuple(decs))
    (rec,) = trade_records(res)
    assert rec["stale_exit"] is True and rec["exit_reason"] == "SYMBOL_NO_BARS" and rec["exit_price"] == pytest.approx(rec["last_close"] * (1 - SLIP_OUT))
    plain = types.SimpleNamespace(trades=tuple(closed_of(decs)), decisions=())
    assert "stale_exit" not in trade_records(plain)[0]                                            # no exits to look up: the plain record (every non-stale trade is written exactly as before)


# ================================================================================================================ C. live
def test_live_session_output_carries_an_explicit_item(tmp_path):
    lake = lake_terminal(tmp_path)
    decs, _ = run(lake, DS[299:345], [scripted("STALE", SIG)], mode="live")
    d20 = [d for d in decs if d.as_of == DS[330]][0]
    path = write_tickets(d20, tmp_path / "tickets")
    body = json.loads(path.read_text(encoding="utf-8"))
    items = [f for f in body["flags"] if f["code"] == "SYMBOL_NO_BARS"]
    assert len(items) == 1 and items[0]["detail"] == "position STALE: no bars for 20 sessions; closed in the book at the last close; check the holding manually (rename, merger, suspension, series change)"
    assert items[0]["symbol"] == "STALE" and any(f["code"] == "UNRECONCILED_EXIT" for f in body["flags"])
    assert [e["reason"] for e in body["exits_assumed"]] == ["SYMBOL_NO_BARS"]


# ================================================================================================================ D. no linked and no stale symbol: nothing changes
def test_a_run_without_linked_or_stale_symbols_is_identical_to_the_old_behaviour(tmp_path):
    from tests.fixtures.lakefile import _make
    p = tmp_path / "mini.db"
    _make(p)
    ds = mini_lake.sessions()
    old_cfg = types.SimpleNamespace(**{f.name: getattr(CFG, f.name) for f in dataclasses.fields(CFG) if f.name != "engine"})          # no engine section: the no-bars rule is off
    strat = lambda: ScriptedStrategy(make_spec("dummy"), {ds[300].isoformat(): [{"symbol": "FIXCO", "stop": 159.115349}]})
    days = ds[296:325]
    with symbol_links.override(enabled=False):
        a, sa = run(p, days, [strat()], cfg=old_cfg, events=EventData(sectors={"FIXCO": "IT"}))
    with symbol_links.override(enabled=True):                                                      # the real link file: no fixture symbol is in it
        b, sb = run(p, days, [strat()], cfg=CFG, events=EventData(sectors={"FIXCO": "IT"}))
    assert a == b and sa == sb and closed_of(a)
    assert not any(f.code in ("SYMBOL_NO_BARS",) for d in b for f in d.flags)


def test_stale_and_link_settings_are_part_of_the_shared_config_hash_but_not_the_gates_hash():
    from stockbot.backtest.manifest import shared_config_hash
    from stockbot.validation import prereg_lock as pl
    base = shared_config_hash(CFG)
    changed = shared_config_hash(dataclasses.replace(CFG, engine=dataclasses.replace(CFG.engine, stale_exit_sessions=30)))
    off = shared_config_hash(dataclasses.replace(CFG, data=dataclasses.replace(CFG.data, symbol_links_enabled=False)))
    assert len({base, changed, off}) == 3
    gp = dataclasses.asdict(CFG.validation_gates)
    assert pl.gates_hash(gp) == "e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054"

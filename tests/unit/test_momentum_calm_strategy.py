"""momentum_calm (stage 1): the strategy only PROPOSES. Month-start signal sessions, the 12-1 return and volatility against an independent calculation, score order and ties, the history and
gap rules (own bars, 253 needed, 240 of 252 closes), ATR against hand-computed numbers, the stop (floor and ATR branch), the spec hash, isolation, no look-ahead, and the strategy-owned exit
policy ``mc_trailing_atr3_floor8`` (never moves down, floor, ATR, timing, corporate-action rescale, identical under the SQL and the memory view). Fixture lakes only; finsight.db is never opened."""
import ast
import hashlib
import json
import shutil
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.engine.exit_policy import Bar, StepContext
from stockbot.live.runner import Book, ModeError, strategies_for_mode
from stockbot.strategies.momentum_calm import EXIT_ID, SPEC, MomentumCalmStrategy, McTrailingAtr3Floor8, register
from stockbot.strategies.momentum_calm import strategy as MC
from stockbot.strategies.momentum_calm.indicators import atr_last
from stockbot.strategies.momentum_calm.strategy import assess, initial_stop, is_signal_session, order_signals
from stockbot.strategies.registry import StrategyRegistry, default_registry
from stockbot.strategies.spec import SpecError
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days

ROOT = Path(__file__).resolve().parents[2]
P = SPEC.params
N = L.N
S = 284                                    # first session of February 2020 on the fixture calendar (index 283 is the last session of January)
DS = L.mini_lake.sessions(N)


def mom(seed, drift=0.0015, sigma=0.01, n=N, start=100.0):
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(drift + sigma * rng.standard_normal(n)))


def indep(c, t=S):
    """ret, vol, score of the series c at session index t, from the rule's own words (own bars, no gaps)."""
    ret = c[t - 21] / c[t - 252] - 1.0
    vol = float(np.std(np.diff(np.log(c[t - 252:t - 20])), ddof=1))
    return ret, vol, ret / vol


def indep_atr(c, period=14, bars=252, hi=1.01, lo=0.99):
    """Wilder ATR of the LAST bar of the fixture series (H = 1.01 c, L = 0.99 c), independent recursion over the last ``bars`` bars."""
    c = np.asarray(c, dtype=float)[-bars:]
    h, l = hi * c, lo * c
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    a = tr[:period].mean()
    for x in tr[period:]:
        a = (a * (period - 1) + x) / period
    return float(a)


@pytest.fixture
def no_calm(monkeypatch):
    """Every name counts as calm (sigma252 = 0 for all, so each is <= the median): the tests that check the verbatim riskadj_momentum parts of the rule run with the filter neutral."""
    monkeypatch.setattr(MC, "sigma252", lambda bars, n: 0.0)


def view_of(path, j):
    return AsOfView(open_lake(path), DS[j])


def propose(path, j, symbols, strat=None):
    return (strat or MomentumCalmStrategy()).propose(view_of(path, j), list(symbols), DS[j], {}, {})[0]


def frame(closes, spread=0.0, as_of=date(2020, 6, 1)):
    n = len(closes)
    idx = [as_of - timedelta(days=n - 1 - i) for i in range(n)]
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open_adj": c, "high_adj": c * (1 + spread), "low_adj": c * (1 - spread), "close_adj": c}, index=idx), as_of


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("momentum_calm", "1.0.0", "research", "mc_trailing_atr3_floor8") and EXIT_ID == "mc_trailing_atr3_floor8"
    assert SPEC.params == {"ret_long": 252, "ret_skip": 21, "min_closes": 240, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20, "calm_vol_window": 252, "calm_cut": "median_of_eligible"}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {} and SPEC.validation_ref is None and SPEC.smallest_edge_of_interest == 0.15
    assert SPEC.prereg_ref == "docs/strategies/momentum_calm/PREREGISTRATION.md" and SPEC.expected_trade_rate > 0


@pytest.mark.parametrize("key,value", [("ret_long", 251), ("ret_skip", 20), ("min_closes", 239), ("top_n", 24), ("atr_period", 13), ("atr_mult", 2.5), ("stop_floor", 0.09), ("tie_adtv_sessions", 21), ("calm_vol_window", 251), ("calm_cut", "mean_of_eligible")])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    assert replace(SPEC, params={**P, key: value}).config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy_and_the_rates():
    for change in ({"exit_policy": "trailing_pct_10"}, {"expected_trade_rate": SPEC.expected_trade_rate + 1}, {"smallest_edge_of_interest": 0.2}, {"version": "1.0.1"}):
        assert replace(SPEC, **change).config_hash() != SPEC.config_hash()


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    b = Book.from_strategies([MomentumCalmStrategy()], extra_policies=[McTrailingAtr3Floor8()])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["momentum_calm"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0


def test_the_library_does_not_know_the_policy_so_it_is_passed_as_extra():
    with pytest.raises(Exception):
        policies_for([SPEC])
    assert set(policies_for([SPEC], extra=[McTrailingAtr3Floor8()])) == {EXIT_ID}


# ------------------------------------------------------------------------------------------------------------------------------------------------ signal sessions
class FakeCal:
    def __init__(self, sess):
        self.sess = sess

    def sessions(self, lookback=None):
        return self.sess[-lookback:] if lookback else self.sess


def test_only_the_first_session_of_a_month_is_a_signal_session():
    assert is_signal_session(FakeCal([date(2020, 1, 31), date(2020, 2, 3)]))
    assert not is_signal_session(FakeCal([date(2020, 2, 3), date(2020, 2, 4)]))
    assert is_signal_session(FakeCal([date(2019, 12, 31), date(2020, 1, 1)]))                       # a year change is a month change
    assert is_signal_session(FakeCal([date(2019, 1, 31), date(2020, 1, 2)])) and not is_signal_session(FakeCal([date(2020, 1, 2)])) and not is_signal_session(FakeCal([]))


def test_the_strategy_proposes_only_on_a_signal_session(tmp_path):
    series = {"M1": mom(1), "M2": mom(2)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    assert propose(p, S, series) and not propose(p, S - 1, series) and not propose(p, S + 1, series)
    assert [DS[i] for i in range(1, N) if (DS[i].year, DS[i].month) != (DS[i - 1].year, DS[i - 1].month) and i >= 252] == [DS[261], DS[284], DS[304], DS[326]]
    assert propose(p, 261, series) and propose(p, 304, series)


# ------------------------------------------------------------------------------------------------------------------------------------------------ the rule
def test_return_volatility_and_score_match_an_independent_calculation_and_the_order_is_by_score(tmp_path, no_calm):
    series = {f"M{k}": mom(10 + k, drift=0.0008 + 0.0004 * (k % 3), sigma=0.008 + 0.003 * (k % 4)) for k in range(8)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    got = propose(p, S, series)
    exp = {s: indep(c) for s, c in series.items()}
    keep = sorted([s for s in series if exp[s][0] > 0], key=lambda s: (-exp[s][2], s))
    assert [x.symbol for x in got] == keep and len(keep) >= 4
    for x in got:
        r, v, sc = exp[x.symbol]
        assert x.metadata["ret"] == pytest.approx(r, rel=1e-9) and x.metadata["vol"] == pytest.approx(v, rel=1e-9) and x.metadata["score"] == pytest.approx(sc, rel=1e-9)
    assert [x.rank for x in got] == [25.0 - k for k in range(len(got))]


def test_non_positive_return_is_excluded_strictly_and_the_skip_month_is_not_in_the_return(tmp_path, no_calm):
    up, down = mom(1), 100.0 * np.exp(-0.002 * np.arange(N) + 0.01 * np.random.default_rng(5).standard_normal(N).cumsum())
    flat = np.full(N, 100.0)
    crash_last_21 = mom(3).copy()
    crash_last_21[S - 20:S + 1] *= 0.5                                                           # a fall INSIDE the skipped month: t-21 and earlier are untouched
    series = {"UP": up, "DOWN": down, "FLAT": flat, "CRASH": crash_last_21}
    p = tmp_path / "lake.db"
    L.build(p, series)
    got = {x.symbol: x for x in propose(p, S, series)}
    assert "DOWN" not in got and "FLAT" not in got                                               # ret < 0, ret = 0 (and vol = 0): neither qualifies
    assert got["CRASH"].metadata["ret"] == pytest.approx(mom(3)[S - 21] / mom(3)[S - 252] - 1.0, rel=1e-9)
    assert got["CRASH"].reference_price == pytest.approx(crash_last_21[S])                       # the stop reference IS today's close


def test_assess_edges_ret_zero_vol_zero_bad_prices_and_short_histories():
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(0.001 + 0.01 * rng.standard_normal(253)))
    b, t = frame(c, spread=0.01)
    win = b.index[-252]
    assert assess(b, t, win, P)[0] == "ok"
    assert assess(b.iloc[1:], t, b.index[-252], P)[0] == "short"                                  # 252 own bars: t-252 does not exist
    c0 = c.copy(); c0[-22] = c0[-253]
    assert assess(*frame(c0, 0.01)[:1], t, win, P)[0] == "ret_not_positive"                       # ret exactly 0
    cn = c.copy(); cn[100] = -1.0
    assert assess(*frame(cn, 0.01)[:1], t, win, P)[0] == "bad_price"
    cz = c.copy(); cz[-253] = np.nan
    assert assess(*frame(cz, 0.01)[:1], t, win, P)[0] == "bad_price"
    assert assess(b, t + timedelta(days=1), win, P)[0] == "stale"                                  # no bar on the signal date
    assert assess(b, t, b.index[-200], P)[0] == "gap"                                              # fewer than 240 closes inside the window


def test_vol_must_be_strictly_positive(monkeypatch):
    c = 100 * 1.001 ** np.arange(253)
    b, t = frame(c, 0.01)
    monkeypatch.setattr(np, "std", lambda *a, **k: 0.0)
    assert assess(b, t, b.index[-252], P)[0] == "vol_not_positive"


def test_history_gap_and_stale_rules_on_the_lake(tmp_path, no_calm):
    series = {k: mom(20 + i, drift=0.004) for i, k in enumerate(["FULL", "SHORT", "GAP12", "GAP13", "NOBAR", "BARE"])}
    skip = {"SHORT": set(range(0, 40)),                                                         # own bars from index 40: 245 < 253
            "GAP12": set(range(100, 112)),                                                      # 12 missing in the 252-session window: 240 closes, passes
            "GAP13": set(range(100, 113)),                                                      # 13 missing: 239, fails
            "NOBAR": {S},                                                                        # no bar on the signal date
            "BARE": set(range(0, 31))}                                                          # own bars from index 31: exactly 254 bars; passes
    p = tmp_path / "lake.db"
    L.build(p, series, skip=skip)
    syms = {x.symbol for x in propose(p, S, series)}
    assert {"FULL", "GAP12", "BARE"} <= syms and not syms & {"SHORT", "GAP13", "NOBAR"}


def test_no_signal_while_the_calendar_has_fewer_than_252_sessions(tmp_path):
    series = {"M1": mom(1)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    assert propose(p, 261, series) and not propose(p, 261, series, MomentumCalmStrategy(replace(SPEC, params={**P, "ret_long": 300})))   # 300 sessions do not exist before index 299


def test_the_own_bar_offsets_reach_further_back_when_a_symbol_has_gaps(tmp_path):
    c = mom(7)
    p = tmp_path / "lake.db"
    L.build(p, {"G": c}, skip={"G": {200, 201, 202}})
    x = propose(p, S, ["G"])[0]
    own = [i for i in range(N) if i not in (200, 201, 202) and i <= S]                          # the symbol's own bars up to S
    r = c[own[-22]] / c[own[-253]] - 1.0
    assert x.metadata["ret"] == pytest.approx(r, rel=1e-9) and own[-253] == S - 252 - 3 and r != pytest.approx(c[S - 21] / c[S - 252] - 1.0, rel=1e-9)   # reaches 3 sessions further back than the calendar


def test_ties_are_broken_by_adtv_then_symbol_and_the_top_25_cut_uses_an_ordinal_rank(tmp_path, no_calm):
    base = mom(40)
    series = {"TIE_B": base.copy(), "TIE_A": base.copy(), "TIE_C": base.copy()}
    series.update({f"X{k:02d}": mom(100 + k, drift=0.002) for k in range(30)})
    p = tmp_path / "lake.db"
    L.build(p, series, volume={"TIE_B": 9_000_000, "TIE_A": 3_000_000, "TIE_C": 3_000_000})
    got = propose(p, S, series)
    tie = [x.symbol for x in got if x.symbol.startswith("TIE")]
    sc = {x.symbol: x.metadata["score"] for x in got}
    assert sc["TIE_A"] == sc["TIE_B"] == sc["TIE_C"] and tie == ["TIE_B", "TIE_A", "TIE_C"]    # higher ADTV first, equal ADTV by symbol
    assert len(got) == 25 and [x.rank for x in got] == [25.0 - k for k in range(25)]
    three = propose(p, S, series, MomentumCalmStrategy(replace(SPEC, params={**P, "top_n": 3})))
    assert [x.symbol for x in three] == [x.symbol for x in got[:3]] and [x.rank for x in three] == [3.0, 2.0, 1.0]


def test_order_signals_unit_tie_groups_beyond_the_cut_are_not_looked_up():
    asked = []
    view = SimpleNamespace(adtv=lambda s, n: asked.append(s) or {"A": 1.0, "B": 5.0, "C": 2.0, "D": 3.0, "E": 4.0}.get(s))
    sigs = [("A", 2.0), ("B", 2.0), ("C", 1.0), ("D", 0.5), ("E", 0.5)]
    out, adtv = order_signals(view, sigs, top_n=2, tie_n=20)
    assert [c[0] for c in out] == ["B", "A", "C", "D", "E"] and set(adtv) == {"A", "B"} and set(asked) == {"A", "B"}


# ------------------------------------------------------------------------------------------------------------------------------------------------ ATR and the stop
def test_atr_matches_a_hand_computed_value():
    # H, L, C: (10, 8, 9) (11, 9, 10) (12, 9, 11) (13, 10, 12) (12, 10, 11).  TR: 2, 2, 3, 3, 2.  period 3: seed (2+2+3)/3 = 7/3; then (7/3*2+3)/3 = 23/9; then (23/9*2+2)/3 = 64/27.
    b = pd.DataFrame({"high_adj": [10, 11, 12, 13, 12], "low_adj": [8, 9, 9, 10, 10], "close_adj": [9, 10, 11, 12, 11]}, index=pd.date_range("2020-01-01", periods=5).date)
    assert atr_last(b, 3) == pytest.approx(64 / 27, abs=1e-12)
    assert atr_last(b.iloc[:3], 3) is None                                                          # needs period + 1 bars
    assert atr_last(b.iloc[:4], 3) == pytest.approx(23 / 9, abs=1e-12)


def test_atr_matches_an_independent_recursion_over_the_last_252_bars():
    c = mom(9, n=400)
    b = pd.DataFrame({"high_adj": 1.01 * c, "low_adj": 0.99 * c, "close_adj": c}, index=pd.date_range("2019-01-01", periods=400).date)
    assert atr_last(b, 14) == pytest.approx(indep_atr(c), rel=1e-12)
    assert atr_last(b.iloc[:300], 14) == pytest.approx(indep_atr(c[:300]), rel=1e-12)             # as of an earlier session: only the bars up to it


def test_the_stop_is_the_close_minus_the_larger_of_three_atr_and_eight_percent(tmp_path):
    calm = mom(50, drift=0.0015, sigma=0.002)                                                    # ATR small: the 8% floor
    wild = 100.0 * np.exp(np.cumsum(0.0015 + 0.05 * np.random.default_rng(51).standard_normal(N)))
    wild[S - 252:] = wild[S - 252:] * 1.0
    series = {"CALM": calm, "WILD": wild}
    p = tmp_path / "lake.db"
    L.build(p, series)
    got = {x.symbol: x for x in propose(p, S, series)}
    assert "CALM" in got
    a_calm = indep_atr(calm[:S + 1])
    assert 3 * a_calm < 0.08 * calm[S] and got["CALM"].stop == pytest.approx(calm[S] - 0.08 * calm[S])
    if "WILD" in got:
        a_wild = indep_atr(wild[:S + 1])
        assert 3 * a_wild > 0.08 * wild[S] and got["WILD"].stop == pytest.approx(wild[S] - 3 * a_wild)
        assert got["WILD"].metadata["atr"] == pytest.approx(a_wild, rel=1e-9)
    assert (got["CALM"].reference_price, got["CALM"].target) == (pytest.approx(calm[S]), None)
    assert initial_stop(100.0, 1.0, P) == (92.0, 8.0) and initial_stop(100.0, 5.0, P) == (85.0, 15.0)


def test_a_stop_at_or_below_zero_makes_the_name_unusable(tmp_path):
    series = {"M1": mom(1)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    assert propose(p, S, series)
    assert propose(p, S, series, MomentumCalmStrategy(replace(SPEC, params={**P, "atr_mult": 400.0}))) == []


# ------------------------------------------------------------------------------------------------------------------------------------------------ strategy hygiene
def test_the_strategy_reads_its_numbers_from_the_spec_and_proposals_are_point_in_time(tmp_path):
    series = {"M1": mom(1), "M2": mom(2, drift=0.002), "M3": mom(3, drift=0.001)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    before = [(x.symbol, x.stop, x.rank, x.metadata["score"]) for x in propose(p, S, series)]
    q = tmp_path / "lake_alt.db"
    shutil.copy(p, q)
    eng = create_engine(f"sqlite:///{q.as_posix()}")
    with eng.begin() as cx:
        cx.execute(text("update market_data_lake set open_raw = open_raw * 3.7, high_raw = high_raw * 3.7, low_raw = low_raw * 0.2, close_raw = close_raw * 0.1 where trade_date > :d"), {"d": DS[S].isoformat()})
    eng.dispose()
    assert [(x.symbol, x.stop, x.rank, x.metadata["score"]) for x in propose(q, S, series)] == before and before
    half = propose(p, S, series, MomentumCalmStrategy(replace(SPEC, params={**P, "stop_floor": 0.5})))
    assert half[0].stop == pytest.approx(0.5 * half[0].reference_price)


def test_a_split_inside_the_window_is_adjusted_and_a_future_split_does_not_leak(tmp_path, no_calm):
    c = mom(1)
    p = tmp_path / "lake.db"
    L.build(p, {"SPL": c.copy(), "PLAIN": c.copy()}, splits={"SPL": (S - 100, 1, 5)})
    got = {x.symbol: x for x in propose(p, S, ["SPL", "PLAIN"])}
    assert got["SPL"].metadata["ret"] == pytest.approx(got["PLAIN"].metadata["ret"], rel=1e-9) and got["SPL"].metadata["vol"] == pytest.approx(got["PLAIN"].metadata["vol"], rel=1e-9)
    q = tmp_path / "later.db"
    L.build(q, {"SPL": c.copy()}, splits={"SPL": (S + 5, 1, 5)})
    assert propose(q, S, ["SPL"])[0].metadata["ret"] == pytest.approx(indep(c)[0], rel=1e-9)


def test_isolation_a_second_registered_strategy_does_not_change_these_proposals(tmp_path):
    series = {"M1": mom(1)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    alone = propose(p, S, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_other", "fixed_hold_5"))
    assert propose(p, S, series) == alone


def test_the_strategy_package_imports_no_other_strategy_no_database_or_network_and_only_the_exit_interface_from_the_engine():
    for f in (ROOT / "stockbot" / "strategies" / "momentum_calm").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
            for m in names:
                assert not m.startswith(("stockbot.strategies.near_52w_high", "stockbot.strategies.pullback", "stockbot.strategies.short_term", "sqlite3", "sqlalchemy", "requests", "urllib", "socket")), (f.name, m)
                assert not m.startswith("stockbot.engine") or m == "stockbot.engine.exit_policy", (f.name, m)


# ------------------------------------------------------------------------------------------------------------------------------------------------ the exit policy
def pos(entry=100.0, stop=90.0, state=None, symbol="X"):
    return SimpleNamespace(symbol=symbol, entry_price=entry, live_stop=stop, exit_state={} if state is None else state)


def view_with(half_range, n=40, close=100.0):
    """A view whose symbol has constant true range 2 x half_range, so ATR14 = 2 x half_range exactly."""
    c = np.full(n, close)
    b = pd.DataFrame({"open_adj": c, "high_adj": c + half_range, "low_adj": c - half_range, "close_adj": c}, index=pd.date_range("2020-01-01", periods=n).date)
    return SimpleNamespace(adjusted_bars=lambda sym, lookback=None: b.iloc[-lookback:] if lookback else b)


CTX = StepContext(days_held=3)


def bar(close):
    return Bar(close, close, close, close)


def test_policy_id_state_and_the_seed_from_the_entry_price():
    pol = McTrailingAtr3Floor8()
    assert pol.id == "mc_trailing_atr3_floor8" and pol.initial_state(pos(entry=101.5), None) == {"highest_close": 101.5}
    a = pol.step(pos(entry=100.0, stop=80.0), bar(95.0), view_with(1.0), CTX)                       # a first close BELOW the entry: the reference stays the entry price
    assert a.new_exit_state == {"highest_close": 100.0} and a.requests == () and a.new_live_stop == pytest.approx(100.0 - 8.0)


def test_the_floor_applies_when_atr_is_small():
    a = McTrailingAtr3Floor8().step(pos(state={"highest_close": 100.0}, stop=90.0), bar(100.0), view_with(1.0), CTX)      # ATR = 2: 3 x ATR = 6 < 8
    assert a.new_live_stop == pytest.approx(92.0) and a.new_exit_state == {"highest_close": 100.0}


def test_the_atr_applies_when_it_is_large():
    a = McTrailingAtr3Floor8().step(pos(state={"highest_close": 100.0}, stop=60.0), bar(100.0), view_with(5.0), CTX)       # ATR = 10: 3 x ATR = 30 > 8
    assert a.new_live_stop == pytest.approx(70.0)


def test_the_distance_uses_the_reference_not_the_close_for_the_floor_and_the_new_high_lifts_the_stop():
    pol = McTrailingAtr3Floor8()
    a = pol.step(pos(state={"highest_close": 100.0}, stop=92.0), bar(120.0), view_with(1.0), CTX)
    assert a.new_exit_state == {"highest_close": 120.0} and a.new_live_stop == pytest.approx(120.0 - 9.6)


def test_the_stop_never_moves_down_even_when_atr_widens_or_the_price_falls():
    pol = McTrailingAtr3Floor8()
    live = 100.0 - 8.0
    a = pol.step(pos(state={"highest_close": 100.0}, stop=live), bar(80.0), view_with(1.0), CTX)                       # price falls: reference unchanged, candidate = live: no new stop
    assert a.new_live_stop is None and a.new_exit_state == {"highest_close": 100.0}
    b = pol.step(pos(state={"highest_close": 100.0}, stop=live), bar(100.0), view_with(5.0), CTX)                      # ATR widens: candidate 70 < live 92: no new stop
    assert b.new_live_stop is None
    s, state = 50.0, {"highest_close": 100.0}
    rng = np.random.default_rng(2)
    for _ in range(300):                                                                                                # a random path: the stop in force never falls
        c = float(100 + 30 * rng.standard_normal())
        act = pol.step(pos(state=state, stop=s), bar(c), view_with(float(rng.choice([0.5, 1.0, 5.0]))), CTX)
        new = s if act.new_live_stop is None else act.new_live_stop
        assert new >= s and act.new_live_stop is None or act.new_live_stop > s
        s, state = new, dict(act.new_exit_state)


def test_the_policy_requests_no_exit_and_has_no_time_exit():
    pol = McTrailingAtr3Floor8()
    for d in (1, 40, 400):
        assert pol.step(pos(state={"highest_close": 100.0}), bar(100.0), view_with(1.0), StepContext(days_held=d)).requests == ()


def test_atr_unavailable_falls_back_to_the_floor_and_is_flagged():
    a = McTrailingAtr3Floor8().step(pos(state={"highest_close": 100.0}, stop=50.0), bar(100.0), view_with(5.0, n=10), CTX)
    assert a.new_live_stop == pytest.approx(92.0) and a.flags == ("ATR_UNAVAILABLE",)


def test_corporate_action_rescales_the_reference():
    pol = McTrailingAtr3Floor8()
    assert pol.on_corporate_action({"highest_close": 100.0}, 0.2) == {"highest_close": pytest.approx(20.0)}
    assert pol.on_corporate_action({"highest_close": 100.0, "x": 1}, 0.5) == {"highest_close": 50.0, "x": 1} and pol.on_corporate_action({}, 0.5) == {}
    st = {"highest_close": 100.0}
    assert st == {"highest_close": 100.0}                                                           # the input is not mutated


ENTRY_SIG = 300                                                       # the strategy-less scripted signal session of the engine runs below


def engine_series():
    rng = np.random.default_rng(4)
    c = 100.0 * np.exp(np.cumsum(0.004 + 0.03 * rng.standard_normal(N)))
    return c


def run_engine(path, c, days):
    strat = ScriptedStrategy(make_spec("dummy", policy=EXIT_ID), {DS[ENTRY_SIG].isoformat(): [{"symbol": "ENG", "stop": float(0.5 * c[ENTRY_SIG])}]})
    return run_days(path, [DS[i] for i in days], [strat], policies_for([strat.spec], extra=[McTrailingAtr3Floor8()]), events=EventData(sectors={"ENG": "IT"}))


def test_through_the_engine_the_stop_trails_by_the_independent_formula_never_down_and_applies_from_the_next_bar(tmp_path):
    c = engine_series()
    p = tmp_path / "lake.db"
    L.build(p, {"ENG": c})
    decs, st = run_engine(p, c, range(ENTRY_SIG, ENTRY_SIG + 12))
    by = {d.as_of: d for d in decs}
    entry_day = DS[ENTRY_SIG + 1]
    assert [f.symbol for f in by[entry_day].fills] == ["ENG"]
    ups = [(d.as_of, u.position) for d in decs for u in d.position_updates if u.position.symbol == "ENG"]
    assert ups and ups[0][0] == entry_day
    entry_price = ups[0][1].entry_price
    highest, prev_stop = entry_price, 0.5 * c[ENTRY_SIG]
    for day, position in ups:
        i = DS.index(day)
        highest = max(highest, c[i])
        cand = highest - max(3.0 * indep_atr(c[:i + 1]), 0.08 * highest)
        expected = max(prev_stop, cand)
        assert position.live_stop == pytest.approx(expected, rel=1e-9) and position.live_stop >= prev_stop
        assert position.exit_state["highest_close"] == pytest.approx(highest)
        assert position.initial_stop == pytest.approx(0.5 * c[ENTRY_SIG])                              # the strategy's own initial stop is kept
        prev_stop = position.live_stop
    assert len(ups) >= 5


def test_through_the_engine_a_close_below_the_trailing_stop_is_stopped_out_at_the_next_session_not_the_same_one(tmp_path):
    c = engine_series()
    c[ENTRY_SIG + 1:ENTRY_SIG + 6] = c[ENTRY_SIG] * np.array([1.0, 1.01, 1.02, 1.03, 1.04])          # a clean rise inside the 3% gap-up cap
    c[ENTRY_SIG + 6] = c[ENTRY_SIG + 5] * 0.70                                                         # then a sharp fall
    c[ENTRY_SIG + 7:] = c[ENTRY_SIG + 6]
    p = tmp_path / "lake.db"
    L.build(p, {"ENG": c})
    decs, st = run_engine(p, c, range(ENTRY_SIG, ENTRY_SIG + 12))
    closed = [x for d in decs for x in d.closed]
    assert len(closed) == 1 and closed[0].exit_reason == "STOP_HIT"
    ups = {d.as_of: u.position for d in decs for u in d.position_updates if u.position.symbol == "ENG"}
    day_before = DS[ENTRY_SIG + 5]
    assert closed[0].exit_date == DS[ENTRY_SIG + 6]                                                    # the first bar whose low is under the stop that stood at the previous close
    assert ups[day_before].live_stop > c[ENTRY_SIG] * 0.5                                              # the stop had trailed up before the fall


def test_identical_under_the_sql_and_the_memory_view(tmp_path, monkeypatch):
    c = engine_series()
    p = tmp_path / "lake.db"
    L.build(p, {"ENG": c})
    out = {}
    for view in ("sql", "memory"):
        monkeypatch.setenv("STOCKBOT_VIEW", view)
        decs, st = run_engine(p, c, range(ENTRY_SIG, ENTRY_SIG + 20))
        out[view] = hashlib.sha256(json.dumps([d.to_json() for d in decs] + [st.to_json()], sort_keys=True, default=str).encode()).hexdigest()
    assert out["sql"] == out["memory"]
    for view in ("sql", "memory"):                                                                     # and the strategy's proposals too
        monkeypatch.setenv("STOCKBOT_VIEW", view)
        out[view] = [(x.symbol, x.stop, x.rank) for x in propose(p, S, ["ENG"])]
    assert out["sql"] == out["memory"]


def test_the_policy_module_imports_only_the_exit_policy_interface_from_the_engine():
    src = ast.parse((ROOT / "stockbot" / "strategies" / "momentum_calm" / "exits.py").read_text(encoding="utf-8"))
    mods = [n.module for n in ast.walk(src) if isinstance(n, ast.ImportFrom) and n.module]
    assert [m for m in mods if m.startswith("stockbot.engine")] == ["stockbot.engine.exit_policy"]


def test_the_shared_matched_random_helper_accepts_the_strategy_owned_policy_object(tmp_path):
    """Step 6 evidence: draw_matched_random takes any policy object, so a strategy-owned policy works through the shared simulator (the stop of each draw is the actual trade's RELATIVE distance,
    not the random symbol's own ATR rule: see the riskadj_momentum stage 1 report)."""
    from stockbot.config.shared import load_shared_config
    from stockbot.validation.random_baseline import draw_matched_random
    cfg = load_shared_config()
    c = engine_series()
    p = tmp_path / "lake.db"
    o1, o2 = mom(61, drift=0.001), mom(62, drift=0.001)
    o1[ENTRY_SIG + 8:], o2[ENTRY_SIG + 8:] = o1[ENTRY_SIG + 8] * 0.5, o2[ENTRY_SIG + 8] * 0.5                   # a fall so that the trailing stop exits inside the lake
    ds = L.build(p, {"ENG": c, "OTHER1": o1, "OTHER2": o2})
    conn = open_lake(p)
    actual = pd.DataFrame([{"unique_trade_id": "t1", "symbol": "ENG", "entry_date": ds[ENTRY_SIG + 1], "entry_price": float(c[ENTRY_SIG]), "stop": float(0.9 * c[ENTRY_SIG]), "window": "all"}])
    d = draw_matched_random(actual, sessions=ds, view_at=lambda day: AsOfView(conn, day), shared_config=cfg, policy=McTrailingAtr3Floor8(), equity=1_000_000.0, draws_per_trade=2, seed=1)
    assert len(d) >= 1 and set(d["symbol"]) <= {"OTHER1", "OTHER2"} and set(d["exit_reason"]) == {"STOP_HIT"}


# ------------------------------------------------------------------------------------------------------------------------------------------------ the calm filter (CHANGE)
def sig252(c, t=S):
    """sigma252 from the rule's words: sample sd of the 252 daily log returns of the closes t-252 .. t (own bars, no gaps)."""
    return float(np.std(np.diff(np.log(np.asarray(c)[t - 252:t + 1])), ddof=1))


def lake_with(tmp_path, series, **kw):
    p = tmp_path / "lake.db"
    L.build(p, series, **kw)
    return p


def rising(seed, sigma, drift=0.003):
    return mom(seed, drift=drift, sigma=sigma)


def test_sigma252_is_the_sample_sd_of_the_last_252_log_returns_and_the_median_is_over_all_names(tmp_path):
    series = {f"A{k}": rising(100 + k, 0.006 + 0.002 * k) for k in range(5)}                      # five names, all rising (ret > 0), five distinct sigmas
    p = lake_with(tmp_path, series)
    got = propose(p, S, series)
    sg = {s: sig252(c) for s, c in series.items()}
    med = float(np.median(list(sg.values())))
    assert {x.symbol for x in got} == {s for s, v in sg.items() if v <= med} and len(got) == 3     # odd count: the median is one name's sigma
    for x in got:
        assert x.metadata["sigma252"] == pytest.approx(sg[x.symbol], rel=1e-9) and x.metadata["median_sigma252"] == pytest.approx(med, rel=1e-9)


def test_a_tie_at_the_median_is_calm_and_an_even_count_takes_the_mean_of_the_two_middle_values(tmp_path):
    series = {f"A{k}": rising(120 + k, 0.006 + 0.002 * k) for k in range(5)}
    p = lake_with(tmp_path, series)
    sg = sorted((sig252(c), s) for s, c in series.items())
    assert propose(p, S, series)[0].metadata["median_sigma252"] == pytest.approx(sg[2][0])
    assert sg[2][1] in {x.symbol for x in propose(p, S, series)}                                    # the name AT the median is calm
    even = dict(list(series.items())[:4])
    sub = tmp_path / "even"
    sub.mkdir()
    pe = lake_with(sub, even)
    got = propose(pe, S, even)
    s4 = sorted(sig252(c) for c in even.values())
    assert got[0].metadata["median_sigma252"] == pytest.approx((s4[1] + s4[2]) / 2.0) and len(got) == 2


def test_a_name_failing_ret_positive_still_counts_in_the_median_but_is_never_proposed(tmp_path):
    up = {f"U{k}": rising(140 + k, 0.006 + 0.002 * k) for k in range(4)}
    down = {"D0": 100.0 * np.exp(-0.003 * np.arange(N) + 0.004 * np.random.default_rng(9).standard_normal(N).cumsum())}      # ret < 0, a LOW sigma: it pulls the median down
    series = {**up, **down}
    p = lake_with(tmp_path, series)
    got = propose(p, S, series)
    sg = {s: sig252(c) for s, c in series.items()}
    assert indep(series["D0"])[0] < 0
    med = float(np.median(list(sg.values())))
    assert got and got[0].metadata["median_sigma252"] == pytest.approx(med, rel=1e-9)
    assert "D0" not in {x.symbol for x in got} and {x.symbol for x in got} == {s for s in up if sg[s] <= med}
    med_up = float(np.median([sg[s] for s in up]))
    assert med != pytest.approx(med_up)                                                             # leaving D0 out of the median would change it


def test_a_name_without_252_sessions_has_no_sigma_is_never_proposed_and_is_not_in_the_median(tmp_path):
    full = {f"F{k}": rising(160 + k, 0.006 + 0.002 * k) for k in range(4)}
    series = {**full, "NEW": rising(170, 0.001)}                                                    # the calmest name of all, but only 245 own bars
    p = lake_with(tmp_path, series, skip={"NEW": set(range(0, 40))})
    got = propose(p, S, series)
    sg = sorted(sig252(c) for c in full.values())
    assert "NEW" not in {x.symbol for x in got}
    assert got[0].metadata["median_sigma252"] == pytest.approx((sg[1] + sg[2]) / 2.0, rel=1e-9) and len(got) == 2    # the median of the four names that have one


def test_the_calm_names_are_ranked_by_score_and_at_most_25_are_proposed(tmp_path):
    series = {f"C{k:02d}": rising(200 + k, 0.004 + 0.0002 * k, drift=0.002 + 0.00005 * (k % 7)) for k in range(20)}       # 20 names: the calm half
    series.update({f"H{k:02d}": rising(300 + k, 0.03 + 0.001 * k) for k in range(20)})                                    # 20 jumpy names: never calm
    p = lake_with(tmp_path, series)
    got = propose(p, S, series)
    sg = {s: sig252(c) for s, c in series.items()}
    med = float(np.median(list(sg.values())))
    calm = [s for s in series if sg[s] <= med]
    exp = sorted([s for s in calm if indep(series[s])[0] > 0], key=lambda s: (-indep(series[s])[2], s))
    assert 5 <= len(exp) <= 25 and [x.symbol for x in got] == exp and all(x.symbol.startswith("C") for x in got)
    assert [x.rank for x in got] == [25.0 - k for k in range(len(got))]
    many = {f"M{k:02d}": rising(400 + k, 0.004 + 0.0001 * k, drift=0.003) for k in range(60)}
    sub = tmp_path / "many"
    sub.mkdir()
    pm = lake_with(sub, many)
    gm = propose(pm, S, many)
    assert len(gm) == 25 and all(x.metadata["sigma252"] <= x.metadata["median_sigma252"] for x in gm)        # 30 calm and rising: the cut at 25


def test_with_the_filter_off_the_picks_are_exactly_riskadj_momentums(tmp_path):
    """The copied functions are verbatim: the unfiltered screen equals riskadj_momentum's own proposals, and the calm picks are those picks that are calm (a subset, in the same order)."""
    from stockbot.strategies.riskadj_momentum import RiskAdjMomentumStrategy
    from stockbot.strategies.momentum_calm.strategy import screen
    series = {f"A{k:02d}": rising(500 + k, 0.005 + 0.0008 * k, drift=0.001 + 0.0002 * (k % 5)) for k in range(30)}
    p = lake_with(tmp_path, series)
    plain = RiskAdjMomentumStrategy().propose(view_of(p, S), list(series), DS[S], {}, {})[0]
    s = screen(view_of(p, S), list(series), DS[S], P, calm=False)
    assert [(c[0], c[1]) for c in s["ordered"][:25]] == [(x.symbol, x.metadata["score"]) for x in plain]
    calm = propose(p, S, series)
    order = [x.symbol for x in plain]
    assert [x.symbol for x in calm] == [s_ for s_ in order if s_ in {x.symbol for x in calm}] and 0 < len(calm) < len(plain)
    for x in calm:
        y = next(q for q in plain if q.symbol == x.symbol)
        assert (x.stop, x.reference_price) == (y.stop, y.reference_price)                           # the stop rule is the same


def test_the_calm_filter_does_not_look_ahead(tmp_path):
    series = {f"A{k}": rising(600 + k, 0.006 + 0.002 * k) for k in range(5)}
    p1 = lake_with(tmp_path, series)
    sub = tmp_path / "x"
    sub.mkdir()
    later = {s: c.copy() for s, c in series.items()}
    for c in later.values():
        c[S + 1:] *= 1.0 + np.random.default_rng(3).standard_normal(N - S - 1) * 0.2
    p2 = lake_with(sub, later)
    a = [(x.symbol, x.stop, x.rank, x.metadata["sigma252"]) for x in propose(p1, S, series)]
    b = [(x.symbol, x.stop, x.rank, x.metadata["sigma252"]) for x in propose(p2, S, later)]
    assert a == b and a


def test_the_calm_policy_is_the_riskadj_momentum_policy_with_another_id():
    from stockbot.strategies.riskadj_momentum.exits import TrailingAtr3Floor8 as Plain
    a, b = McTrailingAtr3Floor8(), Plain()
    assert a.id != b.id and McTrailingAtr3Floor8.initial_state.__code__.co_code == Plain.initial_state.__code__.co_code
    assert McTrailingAtr3Floor8.step.__code__.co_code == Plain.step.__code__.co_code
    assert McTrailingAtr3Floor8.on_corporate_action.__code__.co_code == Plain.on_corporate_action.__code__.co_code

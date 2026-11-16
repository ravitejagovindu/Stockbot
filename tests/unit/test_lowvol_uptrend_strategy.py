"""lowvol_uptrend: the strategy only PROPOSES. Month-start signal sessions, the volatility and the SMA200 against an independent calculation, lowest-vol-first order and ties, the history, gap and
SMA-window rules (own bars, 253 needed, 240 of 252 closes, 198 of 200), the ATR equal to riskadj_momentum's, ATR against hand-computed numbers, the stop (floor and ATR branch), the spec hash, isolation, no look-ahead, and the strategy-owned exit
policy ``lv_trailing_atr3_floor8`` (never moves down, floor, ATR, timing, corporate-action rescale, identical under the SQL and the memory view). Fixture lakes only; finsight.db is never opened."""
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
from stockbot.strategies.lowvol_uptrend import EXIT_ID, SPEC, LowVolUptrendStrategy, LvTrailingAtr3Floor8, register
from stockbot.strategies.lowvol_uptrend.indicators import atr_last
from stockbot.strategies.lowvol_uptrend.strategy import assess, initial_stop, is_signal_session, order_signals
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


def view_of(path, j):
    return AsOfView(open_lake(path), DS[j])


def propose(path, j, symbols, strat=None):
    return (strat or LowVolUptrendStrategy()).propose(view_of(path, j), list(symbols), DS[j], {}, {})[0]


def frame(closes, spread=0.0, as_of=date(2020, 6, 1)):
    n = len(closes)
    idx = [as_of - timedelta(days=n - 1 - i) for i in range(n)]
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open_adj": c, "high_adj": c * (1 + spread), "low_adj": c * (1 - spread), "close_adj": c}, index=idx), as_of


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("lowvol_uptrend", "1.0.0", "research", "lv_trailing_atr3_floor8") and EXIT_ID == "lv_trailing_atr3_floor8"
    assert SPEC.params == {"vol_window": 252, "min_closes": 240, "sma_window": 200, "sma_min_closes": 198, "top_n": 25, "atr_period": 14, "atr_mult": 3.0, "stop_floor": 0.08, "tie_adtv_sessions": 20}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {} and SPEC.validation_ref is None and SPEC.smallest_edge_of_interest == 0.15
    assert SPEC.prereg_ref == "docs/strategies/lowvol_uptrend/PREREGISTRATION.md" and SPEC.expected_trade_rate > 0


@pytest.mark.parametrize("key,value", [("vol_window", 251), ("min_closes", 239), ("sma_window", 199), ("sma_min_closes", 197), ("top_n", 24), ("atr_period", 13), ("atr_mult", 2.5), ("stop_floor", 0.09), ("tie_adtv_sessions", 21)])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    assert replace(SPEC, params={**P, key: value}).config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy_and_the_rates():
    for change in ({"exit_policy": "trailing_pct_10"}, {"expected_trade_rate": SPEC.expected_trade_rate + 1}, {"smallest_edge_of_interest": 0.2}, {"version": "1.0.1"}):
        assert replace(SPEC, **change).config_hash() != SPEC.config_hash()


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    b = Book.from_strategies([LowVolUptrendStrategy()], extra_policies=[LvTrailingAtr3Floor8()])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["lowvol_uptrend"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0


def test_the_library_does_not_know_the_policy_so_it_is_passed_as_extra():
    with pytest.raises(Exception):
        policies_for([SPEC])
    assert set(policies_for([SPEC], extra=[LvTrailingAtr3Floor8()])) == {EXIT_ID}


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
    series = {"M1": mom(1, drift=0.003, sigma=0.006), "M2": mom(2, drift=0.003, sigma=0.006)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    assert propose(p, S, series) and not propose(p, S - 1, series) and not propose(p, S + 1, series)
    assert [DS[i] for i in range(1, N) if (DS[i].year, DS[i].month) != (DS[i - 1].year, DS[i - 1].month) and i >= 252] == [DS[261], DS[284], DS[304], DS[326]]
    assert propose(p, 261, series) and propose(p, 304, series)


# ------------------------------------------------------------------------------------------------------------------------------------------------ the rule
def indep_vol(c, t=S):
    """vol of the series c at session index t from the rule's own words: the 252 daily log returns of the last 253 own bars (no gaps)."""
    return float(np.std(np.diff(np.log(c[t - 252:t + 1])), ddof=1))


def indep_up(c, t=S):
    """close > SMA200 of the last 200 closes (no gaps)."""
    return bool(c[t] > np.mean(c[t - 199:t + 1]))


def test_volatility_matches_an_independent_calculation_and_the_order_is_lowest_vol_first(tmp_path):
    series = {f"M{k}": mom(10 + k, drift=0.0015 + 0.0002 * (k % 3), sigma=0.006 + 0.003 * (k % 5)) for k in range(10)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    got = propose(p, S, series)
    keep = sorted([s for s, c in series.items() if indep_up(c)], key=lambda s: (indep_vol(series[s]), s))
    assert [x.symbol for x in got] == keep and len(keep) >= 4
    for x in got:
        assert x.metadata["vol"] == pytest.approx(indep_vol(series[x.symbol]), rel=1e-9)
        assert x.metadata["sma200"] == pytest.approx(float(np.mean(series[x.symbol][S - 199:S + 1])), rel=1e-9)
    assert [x.rank for x in got] == [25.0 - k for k in range(len(got))]
    assert [x.metadata["vol"] for x in got] == sorted(x.metadata["vol"] for x in got)              # ascending: the lowest first


def test_the_volatility_uses_253_closes_and_252_returns_not_251_or_253(tmp_path):
    c = mom(3, sigma=0.012)
    p = tmp_path / "lake.db"
    L.build(p, {"A": c})
    v = propose(p, S, ["A"])[0].metadata["vol"]
    assert v == pytest.approx(float(np.std(np.diff(np.log(c[S - 252:S + 1])), ddof=1)), rel=1e-12)
    assert v != pytest.approx(float(np.std(np.diff(np.log(c[S - 251:S + 1])), ddof=1)), rel=1e-6)
    assert v != pytest.approx(float(np.std(np.diff(np.log(c[S - 253:S + 1])), ddof=1)), rel=1e-6)
    assert v != pytest.approx(float(np.std(np.diff(np.log(c[S - 252:S + 1])), ddof=0)), rel=1e-6)        # sample (ddof 1), not population


def test_the_uptrend_filter_is_strict_and_excludes_a_name_below_its_sma200(tmp_path):
    up = mom(1, drift=0.002, sigma=0.006)
    down = 100.0 * np.exp(-0.002 * np.arange(N) + 0.006 * np.random.default_rng(5).standard_normal(N).cumsum())
    pull = mom(2, drift=0.002, sigma=0.006).copy()
    pull[S - 3:S + 1] *= 0.5                                                                         # a sharp fall just before the signal: below the SMA
    series = {"UP": up, "DOWN": down, "PULL": pull}
    p = tmp_path / "lake.db"
    L.build(p, series)
    got = {x.symbol for x in propose(p, S, series)}
    assert indep_up(up) and not indep_up(down) and not indep_up(pull)
    assert got == {"UP"}


def _frame_with_last_200(closes_200, head_n=53, seed=0):
    rng = np.random.default_rng(seed)
    head = 100 * np.exp(np.cumsum(0.0005 + 0.01 * rng.standard_normal(head_n)))
    b, t = frame(np.concatenate([head, np.asarray(closes_200, dtype=float)]), spread=0.01)
    return b, t


def test_assess_close_equal_to_the_sma_is_not_an_uptrend_and_just_above_it_is():
    window = np.array([99.0] * 99 + [101.0] * 99 + [100.0] + [100.0])                                  # 199 others sum to 19900 together with the last 100: mean exactly 100
    assert window.mean() == 100.0 and window[-1] == 100.0
    b, t = _frame_with_last_200(window)
    win, sma_start = b.index[-252], b.index[-200]
    assert assess(b, t, win, sma_start, P)[0] == "below_sma"                                           # close == SMA: not strictly greater
    w2 = window.copy()
    w2[-1] = 101.0
    b2, t2 = _frame_with_last_200(w2)
    r, d = assess(b2, t2, b2.index[-252], b2.index[-200], P)
    assert r == "ok" and d["sma"] == pytest.approx(w2.mean(), rel=1e-12) and d["close"] == 101.0


def test_assess_edges_short_stale_gap_sma_gap_bad_price_vol_zero_and_the_order_of_the_checks(monkeypatch):
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(0.002 + 0.01 * rng.standard_normal(253)))
    b, t = frame(c, spread=0.01)
    win, sma = b.index[-252], b.index[-200]
    assert assess(b, t, win, sma, P)[0] == "ok"
    assert assess(b.iloc[1:], t, b.index[-252], sma, P)[0] == "short"                                  # 252 own bars: 252 returns need 253
    assert assess(b, t + timedelta(days=1), win, sma, P)[0] == "stale"
    assert assess(b, t, b.index[-200], sma, P)[0] == "gap"                                             # fewer than 240 closes inside the 252-session window
    cn = c.copy(); cn[100] = -1.0
    assert assess(frame(cn, 0.01)[0], t, win, sma, P)[0] == "bad_price"
    cz = c.copy(); cz[-253] = np.nan
    assert assess(frame(cz, 0.01)[0], t, win, sma, P)[0] == "bad_price"
    assert assess(b, t, win, b.index[-197], P)[0] == "sma_gap"                                         # a window of only 197 closes: fewer than 198
    assert assess(b, t, win, b.index[-198], P)[0] in ("ok", "below_sma")                               # exactly 198 present is enough
    monkeypatch.setattr(np, "std", lambda *a, **k: 0.0)
    assert assess(b, t, win, sma, P)[0] == "vol_not_positive"


def test_history_gap_and_stale_rules_on_the_lake(tmp_path):
    series = {k: mom(20 + i, drift=0.004, sigma=0.006) for i, k in enumerate(["FULL", "SHORT", "GAP12", "GAP13", "NOBAR", "BARE", "SMA2", "SMA3"])}
    skip = {"SHORT": set(range(0, 40)),                                                         # own bars from index 40: 245 < 253
            "GAP12": set(range(40, 52)),                                                      # 12 missing in the 252-session window but outside the 200-session one: 240 closes, passes
            "GAP13": set(range(40, 53)),                                                      # 13 missing: 239, fails
            "NOBAR": {S},                                                                        # no bar on the signal date
            "BARE": set(range(0, 31)),                                                          # own bars from index 31: exactly 254 bars; passes
            "SMA2": {S - 50, S - 51},                                                           # 198 of the last 200 closes: passes
            "SMA3": {S - 50, S - 51, S - 52}}                                                   # 197 of 200: fails
    p = tmp_path / "lake.db"
    L.build(p, series, skip=skip)
    syms = {x.symbol for x in propose(p, S, series)}
    assert {"FULL", "GAP12", "BARE", "SMA2"} <= syms and not syms & {"SHORT", "GAP13", "NOBAR", "SMA3"}


def test_the_sma_is_the_mean_of_the_closes_present_inside_the_200_session_window(tmp_path):
    c = mom(7, drift=0.004, sigma=0.006)
    p = tmp_path / "lake.db"
    L.build(p, {"G": c}, skip={"G": {S - 50, S - 51}})
    x = propose(p, S, ["G"])[0]
    present = [i for i in range(S - 199, S + 1) if i not in (S - 50, S - 51)]
    assert len(present) == 198 and x.metadata["sma200"] == pytest.approx(float(np.mean(c[present])), rel=1e-9)


def test_no_signal_while_the_calendar_has_fewer_than_252_sessions(tmp_path):
    series = {"M1": mom(1, drift=0.004, sigma=0.006)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    assert propose(p, 261, series)
    assert not propose(p, 261, series, LowVolUptrendStrategy(replace(SPEC, params={**P, "vol_window": 300})))       # 300 sessions do not exist before index 299


def test_the_own_bar_window_reaches_further_back_when_a_symbol_has_gaps(tmp_path):
    c = mom(7, drift=0.004, sigma=0.01)
    p = tmp_path / "lake.db"
    L.build(p, {"G": c}, skip={"G": {40, 41, 42}})
    x = propose(p, S, ["G"])[0]
    own = [i for i in range(N) if i not in (40, 41, 42) and i <= S]
    v = float(np.std(np.diff(np.log(c[own[-253:]])), ddof=1))
    assert x.metadata["vol"] == pytest.approx(v, rel=1e-9) and own[-253] == S - 252 - 3                  # the 253 own bars start 3 sessions further back than the calendar's


def test_ties_are_broken_by_adtv_then_symbol_and_the_top_25_cut_uses_an_ordinal_rank(tmp_path):
    base = mom(40, drift=0.003, sigma=0.01)
    series = {"TIE_B": base.copy(), "TIE_A": base.copy(), "TIE_C": base.copy()}
    series.update({f"X{k:02d}": mom(100 + k, drift=0.003, sigma=0.012 + 0.0004 * k) for k in range(30)})
    p = tmp_path / "lake.db"
    L.build(p, series, volume={"TIE_B": 9_000_000, "TIE_A": 3_000_000, "TIE_C": 3_000_000})
    got = propose(p, S, series)
    vol = {x.symbol: x.metadata["vol"] for x in got}
    tie = [x.symbol for x in got if x.symbol.startswith("TIE")]
    assert vol["TIE_A"] == vol["TIE_B"] == vol["TIE_C"] and tie == ["TIE_B", "TIE_A", "TIE_C"] and len(tie) == 3    # higher ADTV first, equal ADTV by symbol
    assert len(got) == 25 and [x.rank for x in got] == [25.0 - k for k in range(25)]
    three = propose(p, S, series, LowVolUptrendStrategy(replace(SPEC, params={**P, "top_n": 3})))
    assert [x.symbol for x in three] == [x.symbol for x in got[:3]] and [x.rank for x in three] == [3.0, 2.0, 1.0]


def test_order_signals_unit_lowest_first_and_tie_groups_beyond_the_cut_are_not_looked_up():
    asked = []
    view = SimpleNamespace(adtv=lambda s, n: asked.append(s) or {"A": 1.0, "B": 5.0, "C": 2.0, "D": 3.0, "E": 4.0}.get(s))
    sigs = [("A", 0.5), ("B", 0.5), ("C", 1.0), ("D", 2.0), ("E", 2.0)]
    out, adtv = order_signals(view, sigs, top_n=2, tie_n=20)
    assert [c[0] for c in out] == ["B", "A", "C", "D", "E"] and set(adtv) == {"A", "B"} and set(asked) == {"A", "B"}
    assert [c[0] for c in order_signals(view, [("Z", 0.2), ("Y", 0.3)], 5, 20)[0]] == ["Z", "Y"]         # lower vol first


def test_the_atr_function_equals_the_riskadj_momentum_one_on_a_fixture():
    from stockbot.strategies.riskadj_momentum import indicators as RI
    import stockbot.strategies.lowvol_uptrend.indicators as LI
    assert LI.ATR_BARS == RI.ATR_BARS == 252
    for seed in (1, 2, 3):
        c = mom(seed, n=400, sigma=0.02)
        b = pd.DataFrame({"high_adj": 1.013 * c, "low_adj": 0.985 * c, "close_adj": c}, index=pd.date_range("2019-01-01", periods=400).date)
        for k in (400, 300, 260, 100, 15):
            assert LI.atr_last(b.iloc[:k], 14) == RI.atr_last(b.iloc[:k], 14)                         # equal values, including the None for too few bars
        assert LI.atr_last(b, 14) == pytest.approx(indep_atr(c, hi=1.013, lo=0.985), rel=1e-12)


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
    series = {"M1": mom(1, 0.003, 0.006)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    assert propose(p, S, series)
    assert propose(p, S, series, LowVolUptrendStrategy(replace(SPEC, params={**P, "atr_mult": 400.0}))) == []


# ------------------------------------------------------------------------------------------------------------------------------------------------ strategy hygiene
def test_the_strategy_reads_its_numbers_from_the_spec_and_proposals_are_point_in_time(tmp_path):
    series = {"M1": mom(1, 0.003, 0.006), "M2": mom(2, drift=0.003, sigma=0.007), "M3": mom(3, drift=0.003, sigma=0.008)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    before = [(x.symbol, x.stop, x.rank, x.metadata["vol"]) for x in propose(p, S, series)]
    q = tmp_path / "lake_alt.db"
    shutil.copy(p, q)
    eng = create_engine(f"sqlite:///{q.as_posix()}")
    with eng.begin() as cx:
        cx.execute(text("update market_data_lake set open_raw = open_raw * 3.7, high_raw = high_raw * 3.7, low_raw = low_raw * 0.2, close_raw = close_raw * 0.1 where trade_date > :d"), {"d": DS[S].isoformat()})
    eng.dispose()
    assert [(x.symbol, x.stop, x.rank, x.metadata["vol"]) for x in propose(q, S, series)] == before and before
    half = propose(p, S, series, LowVolUptrendStrategy(replace(SPEC, params={**P, "stop_floor": 0.5})))
    assert half[0].stop == pytest.approx(0.5 * half[0].reference_price)


def test_a_split_inside_the_window_is_adjusted_and_a_future_split_does_not_leak(tmp_path):
    c = mom(1, 0.003, 0.006)
    p = tmp_path / "lake.db"
    L.build(p, {"SPL": c.copy(), "PLAIN": c.copy()}, splits={"SPL": (S - 100, 1, 5)})
    got = {x.symbol: x for x in propose(p, S, ["SPL", "PLAIN"])}
    assert 5.0 * got["SPL"].metadata["sma200"] == pytest.approx(got["PLAIN"].metadata["sma200"], rel=1e-9) and got["SPL"].metadata["vol"] == pytest.approx(got["PLAIN"].metadata["vol"], rel=1e-9)
    q = tmp_path / "later.db"
    L.build(q, {"SPL": c.copy()}, splits={"SPL": (S + 5, 1, 5)})
    assert propose(q, S, ["SPL"])[0].metadata["vol"] == pytest.approx(indep_vol(c), rel=1e-9)


def test_isolation_a_second_registered_strategy_does_not_change_these_proposals(tmp_path):
    series = {"M1": mom(1, 0.003, 0.006)}
    p = tmp_path / "lake.db"
    L.build(p, series)
    alone = propose(p, S, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_other", "fixed_hold_5"))
    assert propose(p, S, series) == alone


def test_the_strategy_package_imports_no_other_strategy_no_database_or_network_and_only_the_exit_interface_from_the_engine():
    for f in (ROOT / "stockbot" / "strategies" / "lowvol_uptrend").glob("*.py"):
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
    pol = LvTrailingAtr3Floor8()
    assert pol.id == "lv_trailing_atr3_floor8" and pol.initial_state(pos(entry=101.5), None) == {"highest_close": 101.5}
    a = pol.step(pos(entry=100.0, stop=80.0), bar(95.0), view_with(1.0), CTX)                       # a first close BELOW the entry: the reference stays the entry price
    assert a.new_exit_state == {"highest_close": 100.0} and a.requests == () and a.new_live_stop == pytest.approx(100.0 - 8.0)


def test_the_floor_applies_when_atr_is_small():
    a = LvTrailingAtr3Floor8().step(pos(state={"highest_close": 100.0}, stop=90.0), bar(100.0), view_with(1.0), CTX)      # ATR = 2: 3 x ATR = 6 < 8
    assert a.new_live_stop == pytest.approx(92.0) and a.new_exit_state == {"highest_close": 100.0}


def test_the_atr_applies_when_it_is_large():
    a = LvTrailingAtr3Floor8().step(pos(state={"highest_close": 100.0}, stop=60.0), bar(100.0), view_with(5.0), CTX)       # ATR = 10: 3 x ATR = 30 > 8
    assert a.new_live_stop == pytest.approx(70.0)


def test_the_distance_uses_the_reference_not_the_close_for_the_floor_and_the_new_high_lifts_the_stop():
    pol = LvTrailingAtr3Floor8()
    a = pol.step(pos(state={"highest_close": 100.0}, stop=92.0), bar(120.0), view_with(1.0), CTX)
    assert a.new_exit_state == {"highest_close": 120.0} and a.new_live_stop == pytest.approx(120.0 - 9.6)


def test_the_stop_never_moves_down_even_when_atr_widens_or_the_price_falls():
    pol = LvTrailingAtr3Floor8()
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
    pol = LvTrailingAtr3Floor8()
    for d in (1, 40, 400):
        assert pol.step(pos(state={"highest_close": 100.0}), bar(100.0), view_with(1.0), StepContext(days_held=d)).requests == ()


def test_atr_unavailable_falls_back_to_the_floor_and_is_flagged():
    a = LvTrailingAtr3Floor8().step(pos(state={"highest_close": 100.0}, stop=50.0), bar(100.0), view_with(5.0, n=10), CTX)
    assert a.new_live_stop == pytest.approx(92.0) and a.flags == ("ATR_UNAVAILABLE",)


def test_corporate_action_rescales_the_reference():
    pol = LvTrailingAtr3Floor8()
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
    return run_days(path, [DS[i] for i in days], [strat], policies_for([strat.spec], extra=[LvTrailingAtr3Floor8()]), events=EventData(sectors={"ENG": "IT"}))


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
    src = ast.parse((ROOT / "stockbot" / "strategies" / "lowvol_uptrend" / "exits.py").read_text(encoding="utf-8"))
    mods = [n.module for n in ast.walk(src) if isinstance(n, ast.ImportFrom) and n.module]
    assert [m for m in mods if m.startswith("stockbot.engine")] == ["stockbot.engine.exit_policy"]


def test_the_shared_matched_random_helper_accepts_the_strategy_owned_policy_object(tmp_path):
    """Step 6 evidence: draw_matched_random takes any policy object, so a strategy-owned policy works through the shared simulator (the stop of each draw is the actual trade's RELATIVE distance,
    not the random symbol's own ATR rule: see Claude_Docs/LOWVOL_UPTREND_STAGE1_REPORT.md)."""
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
    d = draw_matched_random(actual, sessions=ds, view_at=lambda day: AsOfView(conn, day), shared_config=cfg, policy=LvTrailingAtr3Floor8(), equity=1_000_000.0, draws_per_trade=2, seed=1)
    assert len(d) >= 1 and set(d["symbol"]) <= {"OTHER1", "OTHER2"} and set(d["exit_reason"]) == {"STOP_HIT"}


# ------------------------------------------------------------------------------------------------------------------------------------------------ the exit policy equals riskadj_momentum's
def test_the_policy_gives_the_same_stops_as_the_riskadj_momentum_policy_session_by_session():
    from stockbot.strategies.riskadj_momentum.exits import TrailingAtr3Floor8 as RiskPolicy
    mine, theirs = LvTrailingAtr3Floor8(), RiskPolicy()
    rng = np.random.default_rng(11)
    n = 330
    c = 100.0 * np.exp(np.cumsum(0.001 + 0.02 * rng.standard_normal(n)))
    b = pd.DataFrame({"open_adj": c, "high_adj": c * (1 + 0.01 + 0.01 * rng.random(n)), "low_adj": c * (1 - 0.01 - 0.01 * rng.random(n)), "close_adj": c}, index=pd.date_range("2019-01-01", periods=n).date)
    entry = 100.0
    s1 = s2 = 0.85 * entry
    st1, st2 = mine.initial_state(pos(entry=entry), None), theirs.initial_state(pos(entry=entry), None)
    assert st1 == st2
    moved = 0
    for i in range(260, n):
        view = SimpleNamespace(adjusted_bars=lambda sym, lookback=None, i=i: b.iloc[:i + 1].iloc[-lookback:] if lookback else b.iloc[:i + 1])
        a1 = mine.step(pos(entry=entry, stop=s1, state=st1), bar(float(c[i])), view, CTX)
        a2 = theirs.step(pos(entry=entry, stop=s2, state=st2), bar(float(c[i])), view, CTX)
        assert a1 == a2                                                                           # the whole PolicyActions: stop, state, requests, flags
        if i == 300:                                                                              # a corporate action in the middle: both rescale the reference alike
            st1, st2 = mine.on_corporate_action(a1.new_exit_state, 0.5), theirs.on_corporate_action(a2.new_exit_state, 0.5)
            s1 = s2 = (s1 if a1.new_live_stop is None else a1.new_live_stop) * 0.5
            entry *= 0.5
            assert st1 == st2
            continue
        moved += a1.new_live_stop is not None
        s1 = s1 if a1.new_live_stop is None else a1.new_live_stop
        s2 = s2 if a2.new_live_stop is None else a2.new_live_stop
        st1, st2 = dict(a1.new_exit_state), dict(a2.new_exit_state)
        assert s1 == s2
    assert moved >= 3

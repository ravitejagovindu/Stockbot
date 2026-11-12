"""pullback_uptrend (stage 1): the strategy only PROPOSES. RSI(2) against hand-computed values and an independent recursion, the SMA200 and its 198-of-200 guard, the 250-bar
history rule, the strict RSI < 10 edge, the order (lowest RSI, then ADTV, then symbol, as an explicit ordinal rank), the top-25 cut, the stop, the spec hash, isolation, no look-ahead
and the path through the real engine (fixed_hold_5, the stop, a no-bar session). Fixture lakes only; finsight.db is never opened."""
import ast
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.live.runner import Book, ModeError, strategies_for_mode
from stockbot.strategies.pullback_uptrend import SPEC, PullbackUptrendStrategy, register, rsi_wilder
from stockbot.strategies.registry import StrategyRegistry, default_registry
from stockbot.strategies.spec import SpecError
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days

ROOT = Path(__file__).resolve().parents[2]
P = SPEC.params
N = L.N
S = 280                                                           # the signal session of the fixture series (a bar on every session, 200-session calendar reached long before)


def view_of(path, ds, j):
    return AsOfView(open_lake(path), ds[j])


def propose(path, ds, j, symbols, strat=None):
    return (strat or PullbackUptrendStrategy()).propose(view_of(path, ds, j), list(symbols), ds[j], {}, {})[0]


def wilder_rsi_independent(c, period=2):
    """Textbook Wilder RSI of the last value: seed = plain mean of the first ``period`` changes, then avg = (avg*(period-1) + x)/period."""
    d = np.diff(np.asarray(c, dtype=float))
    g, l = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = g[:period].mean(), l[:period].mean()
    for x, y in zip(g[period:], l[period:]):
        ag, al = (ag * (period - 1) + x) / period, (al * (period - 1) + y) / period
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def uptrend_then_drops(start=100.0, drops=(0.04, 0.04, 0.04), drift=0.002, last=S, n=N, seed=0):
    """Rises ``drift`` a day (small deterministic noise), falls by ``drops`` on the sessions last-len+1..last, then stays flat after ``last``."""
    rng = np.random.default_rng(seed)
    c = start * (1 + drift) ** np.arange(n) * (1 + 0.001 * rng.standard_normal(n))
    k = len(drops)
    for i, dr in enumerate(drops):
        c[last - k + 1 + i] = c[last - k + i] * (1 - dr)
    c[last + 1:] = c[last]
    return c


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("pullback_uptrend", "1.0.0", "research", "fixed_hold_5")
    assert SPEC.params == {"min_bars": 250, "sma_period": 200, "sma_min_closes": 198, "rsi_period": 2, "rsi_max": 10.0, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {}
    assert SPEC.validation_ref is None and SPEC.smallest_edge_of_interest is None         # the owner supplies the edge; nothing is invented


@pytest.mark.parametrize("key,value", [("min_bars", 249), ("sma_period", 199), ("sma_min_closes", 197), ("rsi_period", 3), ("rsi_max", 9.0), ("top_n", 24), ("stop_fraction", 0.93), ("tie_adtv_sessions", 21)])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    assert replace(SPEC, params={**SPEC.params, key: value}).config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy_and_the_rates():
    for change in ({"exit_policy": "fixed_hold_6"}, {"expected_trade_rate": 6.0}, {"smallest_edge_of_interest": 0.2}, {"version": "1.0.1"}):
        assert replace(SPEC, **change).config_hash() != SPEC.config_hash()


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    b = Book.from_strategies([PullbackUptrendStrategy()])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []
    with pytest.raises(SpecError):
        replace(SPEC, status="live")
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["pullback_uptrend"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0


# ------------------------------------------------------------------------------------------------------------------------------------------------ RSI
def test_rsi_matches_a_hand_computed_value():
    # closes 10, 11, 10.5, 10, 9: changes +1, -.5, -.5, -1. Seed (first 2 changes): gain .5, loss .25. Then gain .25, loss .375. Then gain .125, loss .6875.  RSI = 100 * .125 / (.125 + .6875)
    assert rsi_wilder([10, 11, 10.5, 10, 9], 2) == pytest.approx(100 * 0.125 / 0.8125, abs=1e-12)
    assert rsi_wilder([10, 11, 10.5], 2) == pytest.approx(100 * 0.5 / (0.5 + 0.25), abs=1e-12)      # the seed alone
    assert rsi_wilder([10, 11, 10.5, 10], 2) == pytest.approx(100 * 0.25 / (0.25 + 0.375), abs=1e-12)


def test_rsi_edges_all_up_flat_and_too_short():
    assert rsi_wilder([1, 2, 3, 4, 5], 2) == 100.0
    assert rsi_wilder([5, 4, 3, 2, 1], 2) == pytest.approx(0.0, abs=1e-12)
    assert rsi_wilder([7, 7, 7, 7], 2) == 50.0
    assert rsi_wilder([1, 2], 2) is None and rsi_wilder([], 2) is None


def test_rsi_matches_an_independent_recursion_on_random_walks():
    rng = np.random.default_rng(11)
    for _ in range(25):
        c = 100 * np.cumprod(1 + 0.02 * rng.standard_normal(250))
        assert rsi_wilder(c.tolist(), 2) == pytest.approx(wilder_rsi_independent(c, 2), abs=1e-9)
    c3 = 100 * np.cumprod(1 + 0.02 * rng.standard_normal(40))
    assert rsi_wilder(c3.tolist(), 3) == pytest.approx(wilder_rsi_independent(c3, 3), abs=1e-9)


# ------------------------------------------------------------------------------------------------------------------------------------------------ the rule
def test_signal_needs_close_above_sma200_and_rsi_below_10_and_the_stop_is_92_percent(tmp_path):
    series = {"SIG": uptrend_then_drops(), "NODROP": uptrend_then_drops(drops=()), "ONEDROP": uptrend_then_drops(drops=(0.01,)),
              "DOWN": 400.0 * 0.998 ** np.arange(N) * np.where(np.arange(N) > S - 3, 0.95, 1.0)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    c = series["SIG"]
    assert wilder_rsi_independent(c[:S + 1]) < 10 and wilder_rsi_independent(series["NODROP"][:S + 1]) > 10
    assert c[S] > c[S - 199:S + 1].mean()                                                           # the independent trend check for SIG
    d = series["DOWN"]
    assert wilder_rsi_independent(d[:S + 1]) < 10 and d[S] < d[S - 199:S + 1].mean()                 # DOWN has a low RSI but sits below its SMA200
    got = propose(p, ds, S, series)
    assert [x.symbol for x in got] == ["SIG"]
    x = got[0]
    assert (x.strategy_id, x.signal_date, x.target) == ("pullback_uptrend", ds[S], None)
    assert x.reference_price == pytest.approx(c[S]) and x.stop == pytest.approx(0.92 * c[S])
    assert x.metadata["rsi"] == pytest.approx(wilder_rsi_independent(c[:S + 1]), abs=1e-9)


def test_rsi_limit_is_strict_and_the_sma_uses_the_adjusted_series_with_a_split_inside_the_window(tmp_path):
    c = uptrend_then_drops()
    series = {"SIG": c, "SPL": c.copy() * 1.0}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (S - 10, 1, 5)})                 # raw prices fall 5:1 at S-10: an unadjusted series would sit far below its SMA200
    r = wilder_rsi_independent(c[:S + 1])
    assert {x.symbol for x in propose(p, ds, S, series)} == {"SIG", "SPL"}
    assert [x.symbol for x in propose(p, ds, S, series, PullbackUptrendStrategy(replace(SPEC, params={**P, "rsi_max": r})))] == []                  # RSI == limit: not < limit
    assert {x.symbol for x in propose(p, ds, S, series, PullbackUptrendStrategy(replace(SPEC, params={**P, "rsi_max": r + 1e-6})))} == {"SIG", "SPL"}
    assert {x.symbol for x in propose(p, ds, S - 11, series)} == set()      # before the split and before the drops: no signal, and the future split is not visible


def test_a_future_split_does_not_leak_into_an_earlier_session(tmp_path):
    c = uptrend_then_drops(last=S)
    series = {"SPL": c}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (S + 5, 1, 5)})
    assert [x.reference_price for x in propose(p, ds, S, series)] == [pytest.approx(c[S])]     # the split at S+5 is unknown on S: raw == adjusted


def test_history_rule_250_bars_and_a_bar_on_the_signal_date(tmp_path):
    base = uptrend_then_drops()
    series = {"OK": base, "SHORT": base.copy(), "GONE": base.copy()}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"SHORT": set(range(0, S - 248)), "GONE": {S}})            # SHORT: bars on S-248..S = 249 bars; GONE: no bar on the signal date
    assert {x.symbol for x in propose(p, ds, S, series)} == {"OK"}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, {"SHORT": base}, skip={"SHORT": set(range(0, S - 249))})              # exactly 250 bars: passes
    assert {x.symbol for x in propose(p2, ds2, S, {"SHORT": base})} == {"SHORT"}


def test_sma_guard_198_of_200_closes_two_missing_pass_three_drop_and_gaps_outside_the_window_do_not_count(tmp_path):
    base = uptrend_then_drops()
    series = {k: base.copy() for k in ("MISS2", "MISS3", "OLD3")}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"MISS2": {S - 100, S - 101}, "MISS3": {S - 100, S - 101, S - 102}, "OLD3": {S - 201, S - 202, S - 203}})
    got = {x.symbol for x in propose(p, ds, S, series)}
    assert got == {"MISS2", "OLD3"}                                                        # OLD3's gaps lie before the 200-session window


def test_no_signal_while_the_calendar_has_fewer_than_200_sessions(tmp_path):
    series = {"SIG": uptrend_then_drops(last=150)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    assert propose(p, ds, 150, series) == []                                               # 151 sessions: no SMA200 exists (and fewer than 250 bars)
    series2 = {"SIG": uptrend_then_drops(last=S)}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, series2, n=N)
    assert len(view_of(p2, ds2, 198).sessions(lookback=200)) == 199 and propose(p2, ds2, 198, series2) == []


def test_order_is_lowest_rsi_then_higher_adtv_then_symbol_with_an_ordinal_rank_and_the_top_25_cut(tmp_path):
    series = {f"R{k:02d}": uptrend_then_drops(drops=(0.03 + 0.001 * k,) * 3) for k in range(30)}           # a bigger drop = a lower RSI, so R29 first
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    rs = {k: wilder_rsi_independent(v[:S + 1]) for k, v in series.items()}
    assert all(r < 10 for r in rs.values())
    got = propose(p, ds, S, series)
    assert [x.symbol for x in got] == sorted(series, key=lambda k: (rs[k], k))[:25] and len(got) == 25
    assert [x.rank for x in got] == [25.0 - i for i in range(25)] and sorted([(-x.rank, x.symbol) for x in got]) == [(-x.rank, x.symbol) for x in got]
    ident = uptrend_then_drops()
    tie = {"TIEA": ident, "TIEB": ident.copy(), "TIEC": ident.copy()}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, tie, volume={"TIEB": 12_000_000})
    assert [x.symbol for x in propose(p2, ds2, S, tie)] == ["TIEB", "TIEA", "TIEC"]                # equal RSI: higher raw ADTV first (TIEB), then symbol (TIEA before TIEC)
    assert [x.rank for x in propose(p2, ds2, S, tie)] == [25.0, 24.0, 23.0]


def test_the_strategy_reads_its_numbers_from_the_spec(tmp_path):
    series = {f"R{k:02d}": uptrend_then_drops(drops=(0.03 + 0.001 * k,) * 3) for k in range(5)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    s3 = PullbackUptrendStrategy(replace(SPEC, params={**P, "top_n": 3}))
    assert [x.symbol for x in propose(p, ds, S, series, s3)] == ["R04", "R03", "R02"]
    half = propose(p, ds, S, series, PullbackUptrendStrategy(replace(SPEC, params={**P, "stop_fraction": 0.5})))
    assert half[0].stop == pytest.approx(0.5 * series["R04"][S])


def test_proposals_do_not_change_when_every_row_after_the_as_of_date_is_altered(tmp_path):
    series = {"SIG": uptrend_then_drops(), "OTHER": uptrend_then_drops(start=50.0, drops=(0.05, 0.05, 0.05), seed=3)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    before = [(x.symbol, x.stop, x.rank, x.metadata["rsi"]) for x in propose(p, ds, S, series)]
    q = tmp_path / "lake_alt.db"
    shutil.copy(p, q)
    eng = create_engine(f"sqlite:///{q.as_posix()}")
    with eng.begin() as cx:
        cx.execute(text("update market_data_lake set open_raw = open_raw * 3.7, high_raw = high_raw * 3.7, low_raw = low_raw * 0.2, close_raw = close_raw * 0.1 where trade_date > :d"), {"d": ds[S].isoformat()})
    eng.dispose()
    assert [(x.symbol, x.stop, x.rank, x.metadata["rsi"]) for x in propose(q, ds, S, series)] == before and before


def test_isolation_a_second_registered_strategy_does_not_change_these_proposals(tmp_path):
    series = {"SIG": uptrend_then_drops()}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    alone = propose(p, ds, S, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_other", "fixed_hold_5"))
    assert propose(p, ds, S, series) == alone


def test_the_strategy_package_imports_no_other_strategy_and_no_database_or_network():
    for f in (ROOT / "stockbot" / "strategies" / "pullback_uptrend").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
            for m in names:
                assert not m.startswith("stockbot.strategies.near_52w_high") and not m.startswith(("sqlite3", "sqlalchemy", "requests", "urllib", "socket")), (f.name, m)
                assert not m.startswith("stockbot.engine") or m.startswith("stockbot.engine.exit_policy") and not m.startswith("stockbot.engine.exit_policies"), (f.name, m)


# ------------------------------------------------------------------------------------------------------------------------------------------------ through the engine
SECTORS = {"A_GOOD": "IT", "B_STOP": "BANKS", "C_GAP": "AUTO"}


@pytest.fixture(scope="module")
def engine_lake(tmp_path_factory):
    series = {"A_GOOD": uptrend_then_drops(seed=1), "B_STOP": uptrend_then_drops(seed=2), "C_GAP": uptrend_then_drops(seed=3)}
    series["B_STOP"][S + 3:] = series["B_STOP"][S] * 0.80                  # a 20% fall on S+3: the 8% stop (0.92 x signal close) fires; low of S+3 is 1% under the close
    p = tmp_path_factory.mktemp("pb") / "lake.db"
    ds = L.build(p, series, skip={"C_GAP": {S + 3, S + 4}})
    return p, ds


def run(engine_lake, days):
    p, ds = engine_lake
    s = PullbackUptrendStrategy()
    return run_days(p, [ds[i] for i in days], [s], policies_for([s.spec]), events=EventData(sectors=SECTORS))


def test_through_the_engine_exit_at_the_open_of_session_6_the_stop_earlier_and_a_no_bar_session_not_counted(engine_lake):
    p, ds = engine_lake
    decs, st = run(engine_lake, range(S, S + 14))
    tickets = [t for d in decs for t in d.new_tickets if d.as_of == ds[S]]
    assert {t.symbol for t in tickets} == set(SECTORS) and all(t.stop == pytest.approx(0.92 * t.reference_price) for t in tickets)
    c: dict = {}
    for d in decs:
        for x in d.closed:
            c.setdefault(x.symbol, x)                                           # the flat series keeps signalling, so a name is re-entered later: take its FIRST trade
    a = c["A_GOOD"]                                                         # signal at the close of S, entry at the open of S+1 = session 1, exit at the open of session 6 = S+6
    assert (a.entry_date, a.exit_date, a.exit_reason) == (ds[S + 1], ds[S + 6], "TIME_EXIT")
    b = c["B_STOP"]
    assert (b.entry_date, b.exit_date, b.exit_reason) == (ds[S + 1], ds[S + 3], "STOP_HIT")
    g = c["C_GAP"]                                                          # no bars on S+3 and S+4: those sessions are not counted as held, so the exit is two sessions later
    assert (g.entry_date, g.exit_date, g.exit_reason) == (ds[S + 1], ds[S + 8], "TIME_EXIT")


def test_determinism_through_the_engine_on_the_fixture_lake(engine_lake):
    (a, sa), (b, sb) = run(engine_lake, range(S, S + 10)), run(engine_lake, range(S, S + 10))
    assert [d.to_json() for d in a] == [d.to_json() for d in b] and sa.to_json() == sb.to_json() and any(d.fills for d in a) and any(d.closed for d in a)


def test_a_scripted_second_strategy_does_not_change_this_strategys_tickets(engine_lake):
    p, ds = engine_lake
    s = PullbackUptrendStrategy()
    other = ScriptedStrategy(make_spec("dummy_other", "fixed_hold_5"), {})
    alone, _ = run_days(p, [ds[S]], [s], policies_for([s.spec]), events=EventData(sectors=SECTORS))
    both, _ = run_days(p, [ds[S]], [s, other], policies_for([s.spec, other.spec]), events=EventData(sectors=SECTORS))
    assert [t.symbol for t in alone[0].new_tickets] == [t.symbol for t in both[0].new_tickets]

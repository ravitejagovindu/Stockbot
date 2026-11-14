"""short_term_reversal (Stage 1): the strategy only PROPOSES. ret5 against an independent computation, the inclusive band edges (-0.07 and -0.30, and just outside), the data guards
(min_bars, the 5-session anchor, the as-of bar), ranking (lowest ret5 first), ties (ADTV then symbol, as an explicit rank), the top-25 cut, the stop, the spec hash, isolation,
point-in-time safety, and the path through the real engine (fixed_hold_5, the stop, a no-bar session). Fixture lakes only; never finsight.db."""
import ast
import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData
from stockbot.engine.exit_policies.registry import policies_for
from stockbot.live.runner import Book, ModeError, strategies_for_mode
from stockbot.strategies.registry import StrategyRegistry, default_registry
from stockbot.strategies.short_term_reversal import SPEC, ShortTermReversalStrategy, register
from stockbot.strategies.spec import SpecError
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days

ROOT = Path(__file__).resolve().parents[2]
P = SPEC.params
J = 300                                                    # the as-of session index used by most tests; its anchor (5 sessions back) is index 295


def fall(r: float, j: int = J, base: float = 100.0) -> np.ndarray:
    """Flat at ``base`` except the close of session j, which is base x (1 + r): ret5 at session j is exactly r (the anchor close, session j-5, is base)."""
    c = np.full(L.N, base)
    c[j] = base * (1.0 + r)
    return c


def view_of(path, ds, j):
    return AsOfView(open_lake(path), ds[j])


def propose(path, ds, j, symbols, strat=None):
    strat = strat or ShortTermReversalStrategy()
    return strat.propose(view_of(path, ds, j), list(symbols), ds[j], {}, {})


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("short_term_reversal", "1.0.0", "research", "fixed_hold_5")
    assert SPEC.params == {"lookback_sessions": 5, "min_bars": 10, "ret_floor": -0.30, "ret_cap": -0.07, "top_n": 25, "stop_fraction": 0.92, "tie_adtv_sessions": 20}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {} and SPEC.smallest_edge_of_interest == 0.15 and SPEC.validation_ref is None


@pytest.mark.parametrize("key,value", [("lookback_sessions", 4), ("min_bars", 9), ("ret_floor", -0.31), ("ret_cap", -0.06), ("top_n", 24), ("stop_fraction", 0.91), ("tie_adtv_sessions", 21)])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    other = replace(SPEC, params={**SPEC.params, key: value})
    assert other.config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy_and_the_rates():
    for change in ({"exit_policy": "fixed_hold_6"}, {"expected_trade_rate": 6.0}, {"smallest_edge_of_interest": 0.2}, {"version": "1.0.1"}, {"prereg_ref": "x.md"}):
        assert replace(SPEC, **change).config_hash() != SPEC.config_hash()


def test_the_strategy_reads_its_numbers_from_the_spec(tmp_path):
    series = {f"C{k:02d}": fall(-0.08 - 0.005 * k) for k in range(30)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    assert len(propose(p, ds, J, series)[0]) == 25
    assert len(propose(p, ds, J, series, ShortTermReversalStrategy(replace(SPEC, params={**P, "top_n": 3})))[0]) == 3
    cap = ShortTermReversalStrategy(replace(SPEC, params={**P, "ret_cap": -0.10}))               # -0.08 - 0.005 k <= -0.10  <=>  k >= 4
    assert {x.symbol for x in propose(p, ds, J, series, cap)[0]} == {f"C{k:02d}" for k in range(5, 30)}      # k >= 4 passes (26 names); the deepest 25 are k = 5..29
    floor = ShortTermReversalStrategy(replace(SPEC, params={**P, "ret_floor": -0.15}))           # -0.08 - 0.005 k >= -0.15  <=>  k <= 14
    assert {x.symbol for x in propose(p, ds, J, series, floor)[0]} == {f"C{k:02d}" for k in range(0, 15)}
    half = propose(p, ds, J, series, ShortTermReversalStrategy(replace(SPEC, params={**P, "stop_fraction": 0.5})))[0][0]
    assert half.stop == pytest.approx(0.5 * half.reference_price)


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    s = ShortTermReversalStrategy()
    b = Book.from_strategies([s])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []
    with pytest.raises(SpecError):
        replace(SPEC, status="live")
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["short_term_reversal"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0


# ------------------------------------------------------------------------------------------------------------------------------------------ the rule
def test_ret5_matches_an_independent_computation_including_a_split_inside_the_window(tmp_path):
    rng = np.random.default_rng(11)
    base = 100.0 * (1.0 + 0.004 * rng.standard_normal(L.N))
    series = {"PLAIN": base.copy(), "SPL": 150.0 * (1.0 + 0.004 * rng.standard_normal(L.N))}
    for sym in series:
        series[sym][J] = series[sym][J - 5] * 0.9                                                  # -10% over 5 sessions, whatever the noise
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (298, 1, 5)})                                           # a 1:5 split with ex-date INSIDE the 5-session window
    props, _ = propose(p, ds, J, series)
    got = {x.symbol: x.metadata["ret5"] for x in props}
    for sym, c in series.items():
        assert got[sym] == pytest.approx(c[J] / c[J - 5] - 1.0, abs=1e-12), sym
    raw_would_say = 0.2 * series["SPL"][J] / series["SPL"][J - 5] - 1.0                          # a raw-price version would see about -82%: below the floor, no signal
    assert raw_would_say < -0.30
    props_early, _ = propose(p, ds, 297, series)                                                  # before the split is known the as-of basis is the raw one: no jump
    assert all(abs(x.metadata["ret5"]) < 0.30 for x in props_early)


@pytest.mark.parametrize("last,signal", [(93.0, True), (93.01, False), (70.0, True), (69.99, False), (92.0, True), (99.0, False), (50.0, False), (100.0, False), (110.0, False)])
def test_band_edges_are_inclusive_minus_0_07_and_minus_0_30_in_and_just_outside_out(tmp_path, last, signal):
    series = {"EDGE": fall(last / 100.0 - 1.0)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    props, _ = propose(p, ds, J, series)
    assert [x.symbol for x in props] == (["EDGE"] if signal else []), last
    if signal:
        assert props[0].metadata["ret5"] == pytest.approx(last / 100.0 - 1.0, abs=1e-12)


def test_the_exact_edges_survive_float_noise(tmp_path):
    series = {"AT07": fall(0.93 - 1.0), "AT30": fall(0.70 - 1.0)}                                  # 0.93 - 1.0 is -0.06999999999999995 in floating point: must still be a signal
    assert 0.93 - 1.0 > -0.07
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    props, _ = propose(p, ds, J, series)
    assert {x.symbol: x.metadata["ret5"] for x in props} == {"AT07": -0.07, "AT30": -0.3}


def test_the_return_runs_from_the_close_five_calendar_sessions_back_not_four_or_six(tmp_path):
    c = np.full(L.N, 100.0)
    c[J - 6], c[J - 4] = 50.0, 200.0                                                                # sessions 6 and 4 back are not the anchor
    c[J] = 90.0
    series = {"ANCHOR5": c}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    (x,), _ = propose(p, ds, J, series)
    assert x.metadata["ret5"] == pytest.approx(-0.10, abs=1e-12)


def test_data_guards_min_bars_the_anchor_bar_and_the_as_of_bar(tmp_path):
    series = {"OK": fall(-0.10), "TEN": fall(-0.10), "NINE": fall(-0.10), "NOANCHOR": fall(-0.10), "NOASOF": fall(-0.10), "NOTODAY": fall(-0.10)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"TEN": set(range(0, 291)), "NINE": set(range(0, 292)), "NOANCHOR": {J - 5}, "NOASOF": {J}, "NOTODAY": {J}})
    got = {x.symbol for x in propose(p, ds, J, series)[0]}
    assert got == {"OK", "TEN"}                                      # TEN has exactly 10 bars (291..300) and passes; NINE has 9; no bar on the anchor date or on the as-of date: no signal


def test_a_gap_before_the_anchor_does_not_move_the_anchor(tmp_path):
    c = np.full(L.N, 100.0)
    c[J] = 90.0
    series = {"GAPPY": c}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"GAPPY": {296, 297}})                                              # two bars missing after the anchor: the anchor is still session 295
    (x,), _ = propose(p, ds, J, series)
    assert x.metadata["ret5"] == pytest.approx(-0.10, abs=1e-12)


def test_ranking_lowest_ret5_first_the_top_25_cut_and_an_explicit_ordinal_rank(tmp_path):
    series = {f"C{k:02d}": fall(-0.07 - 0.005 * k) for k in range(30)}                              # C29 is the deepest fall
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    props, _ = propose(p, ds, J, series)
    assert [x.symbol for x in props] == [f"C{k:02d}" for k in range(29, 4, -1)]                      # the 25 deepest; C00..C04 are cut
    assert [x.rank for x in props] == [float(25 - i) for i in range(25)]
    r = [x.metadata["ret5"] for x in props]
    assert r == sorted(r)
    assert sorted(props, key=lambda x: (-x.rank, x.symbol)) == props                                # the engine's own order (rank, then symbol) reproduces the strategy's order


def test_ties_go_by_adtv_then_symbol_and_the_rank_carries_that_order_not_the_alphabet(tmp_path):
    series = {f"V{k:02d}": fall(-0.10) for k in range(30)}
    vol = {f"V{k:02d}": 6_000_000 + k * 1_000_000 for k in range(30)}                                 # V29 trades the most
    series["TIEA"], series["TIEC"] = fall(-0.10), fall(-0.10)                                         # default volume: below V00, equal to each other: symbol order decides
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume=vol)
    props, _ = propose(p, ds, J, series)
    syms = [x.symbol for x in props]
    assert len(props) == 25 and syms[:3] == ["V29", "V28", "V27"] and syms != sorted(syms)
    assert [x.rank for x in props] == [float(25 - i) for i in range(25)] and sorted(props, key=lambda x: (-x.rank, x.symbol)) == props
    assert props[0].metadata["adtv"] > props[1].metadata["adtv"]
    two = {"TIEA": fall(-0.10), "TIEC": fall(-0.10)}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, two)
    assert [x.symbol for x in propose(p2, ds2, J, two)[0]] == ["TIEA", "TIEC"]


def test_a_deeper_fall_beats_a_higher_adtv_and_a_tie_is_only_an_exact_equality(tmp_path):
    series = {"DEEP": fall(-0.20), "LIQ": fall(-0.10), "LIQ2": fall(-0.1001)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume={"LIQ": 90_000_000, "LIQ2": 90_000_000, "DEEP": 6_000_000})
    assert [x.symbol for x in propose(p, ds, J, series)[0]] == ["DEEP", "LIQ2", "LIQ"]


def test_nothing_is_proposed_when_no_name_is_in_the_band_or_no_name_is_eligible(tmp_path):
    series = {"UP": fall(0.05), "FLAT": fall(0.0), "CRASH": fall(-0.5)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    assert propose(p, ds, J, series)[0] == [] and propose(p, ds, J, [])[0] == []
    assert propose(p, ds, 3, series)[0] == []                                                         # session 3 has no 6-session calendar behind it: nothing is proposed


def test_the_stop_is_0_92_times_the_signal_day_adjusted_close_in_the_as_of_basis(tmp_path):
    c = np.full(L.N, 150.0)
    c[J - 1] = 120.0
    c[J] = 126.0                                                                                       # -16% from the anchor (150)
    series = {"SPL": c}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (298, 1, 5)})                                              # raw closes are 0.2 x from session 298 on
    (x,), _ = propose(p, ds, J, series)
    assert x.reference_price == pytest.approx(0.2 * 126.0, rel=1e-12) and x.stop == pytest.approx(0.92 * 0.2 * 126.0, rel=1e-12)
    assert x.signal_date == ds[J] and x.strategy_id == "short_term_reversal" and x.target is None and x.stop < x.reference_price


# ------------------------------------------------------------------------------------------------------------------------------------------ point-in-time safety
def _alter_future(src: Path, dst: Path, after: date, ds):
    shutil.copy(src, dst)
    nxt = ds[ds.index(after) + 1]
    eng = create_engine(f"sqlite:///{dst.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*7, volume_raw=volume_raw*3 where trade_date>:d"),
                  {"d": after.isoformat()})
        c.execute(text("insert into corporate_actions_log(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('A', :d, 'SPLIT', 1, 50, 'test', 'T1')"),
                  {"d": nxt.isoformat()})
    eng.dispose()


def test_changing_every_row_after_the_as_of_date_does_not_change_the_proposals(tmp_path):
    series = {"A": fall(-0.12), "B": fall(-0.08), "C": fall(-0.2)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume={"C": 9_000_000})
    alt = tmp_path / "alt.db"
    _alter_future(p, alt, ds[J], ds)
    a, sa = propose(p, ds, J, series)
    b, sb = propose(alt, ds, J, series)
    assert a == b and sa == sb and len(a) == 3


def test_the_data_requested_never_reaches_past_the_as_of_date(tmp_path):
    series = {"A": fall(-0.12)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    conn = open_lake(p)
    seen: list = []
    conn.set_trace_callback(seen.append)
    ShortTermReversalStrategy().propose(AsOfView(conn, ds[J]), ["A"], ds[J], {}, {})
    conn.close()
    import re
    dates = [d for s in seen for d in re.findall(r"\d{4}-\d{2}-\d{2}", s)]
    assert dates and all(d <= ds[J].isoformat() for d in dates), sorted(set(dates))[-3:]


# ------------------------------------------------------------------------------------------------------------------------------------------ isolation
def test_a_second_registered_strategy_does_not_change_these_proposals_and_state_is_plain(tmp_path):
    series = {"A": fall(-0.12), "B": fall(-0.09)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    alone, st_alone = propose(p, ds, J, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_two"))
    dummy = ScriptedStrategy(make_spec("dummy_two"), {ds[J].isoformat(): [{"symbol": "A", "stop": 1.0, "rank": 9.0}]})
    dummy.propose(view_of(p, ds, J), ["A"], ds[J], {}, {})
    with_other, st_other = propose(p, ds, J, series)
    assert alone == with_other and st_alone == st_other == {} and json.dumps(st_alone) == "{}" and len(alone) == 2


def test_the_strategy_package_imports_only_what_a_strategy_may_import():
    pkg = ROOT / "stockbot" / "strategies" / "short_term_reversal"
    allowed_std = {"__future__", "math", "typing", "dataclasses", "datetime", "collections"}
    for f in sorted(pkg.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [n.module] if isinstance(n, ast.ImportFrom) and n.module else [a.name for a in n.names] if isinstance(n, ast.Import) else []
            for m in mods:
                top = m.split(".")[0]
                if top == "stockbot":
                    assert m.startswith(("stockbot.strategies.base", "stockbot.strategies.spec", "stockbot.strategies.short_term_reversal")), (f.name, m)
                else:
                    assert top in allowed_std, (f.name, m)


# ------------------------------------------------------------------------------------------------------------------------------------------ through the engine
SECTORS = {"A_GOOD": "S1", "B_STOP": "S2", "C_GAP": "S3"}


@pytest.fixture(scope="module")
def engine_lake(tmp_path_factory):
    series = {}
    for sym in SECTORS:
        c = np.full(L.N, 100.0)
        c[300:] = 90.0                                         # a -10% fall on session 300 that stays (the entry open on 301 is then inside the 3% gap-up cap)
        series[sym] = c
    series["B_STOP"][302:] = 60.0                              # a crash far below the stop 0.92 x 90 = 82.8 on session 302
    p = tmp_path_factory.mktemp("str_engine") / "lake.db"
    ds = L.build(p, series, skip={"C_GAP": {304, 305}})
    return p, ds


def run(engine_lake, days=range(298, 314)):
    p, ds = engine_lake
    s = ShortTermReversalStrategy()
    return run_days(p, [ds[i] for i in days], [s], policies_for([s.spec]), events=EventData(sectors=SECTORS))


def closed(decs):
    return {c.symbol: c for d in decs for c in d.closed}


def test_through_the_engine_exit_at_the_open_after_five_closes_the_stop_earlier_and_a_no_bar_session_not_counted(engine_lake):
    p, ds = engine_lake
    decs, st = run(engine_lake)
    tickets = [t for d in decs for t in d.new_tickets if d.as_of == ds[300]]
    assert {t.symbol for t in tickets} == set(SECTORS) and all(t.stop == pytest.approx(0.92 * t.reference_price) for t in tickets)
    c = closed(decs)
    a = c["A_GOOD"]                                            # signal at the close of 300, entry at the open of 301 = session 1, five closes (301..305), exit at the open of 306
    assert (a.entry_date, a.exit_date, a.exit_reason) == (ds[301], ds[306], "TIME_EXIT")
    b = c["B_STOP"]
    assert (b.entry_date, b.exit_date, b.exit_reason) == (ds[301], ds[302], "STOP_HIT")
    g = c["C_GAP"]                                             # bars missing on 304 and 305 are not counted as held: the fifth close is session 307, the exit is the open of 308
    assert (g.entry_date, g.exit_date, g.exit_reason) == (ds[301], ds[308], "TIME_EXIT")


def test_determinism_through_the_engine_on_the_fixture_lake(engine_lake):
    (a, sa), (b, sb) = run(engine_lake), run(engine_lake)
    assert [d.to_json() for d in a] == [d.to_json() for d in b] and sa.to_json() == sb.to_json() and any(d.fills for d in a) and any(d.closed for d in a)

"""near_52w_high (STOP 2): the strategy only PROPOSES. Nearness against an independent computation, the gap guard, the 0.95 edges, the tie-break (ADTV then symbol, as an explicit
rank), the top-25 cut, the stop, the spec hash, isolation, no look-ahead, and the path through the real engine (fixed_hold_40, the stop, a no-bar session). Fixture lakes only."""
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
from stockbot.strategies.near_52w_high import SPEC, NearHighStrategy, register
from stockbot.strategies.registry import StrategyRegistry, default_registry
from stockbot.strategies.spec import SpecError, StrategySpec
from tests.fixtures import mini_lake
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days

ROOT = Path(__file__).resolve().parents[2]
P = SPEC.params


def view_of(path, ds, j):
    return AsOfView(open_lake(path), ds[j])


def propose(path, ds, j, symbols, strat=None):
    strat = strat or NearHighStrategy()
    props, st = strat.propose(view_of(path, ds, j), list(symbols), ds[j], {}, {})
    return props, st


def near(c, j, window=252):
    return c[j] / c[j - window + 1:j + 1].max()


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("near_52w_high", "1.0.0", "research", "fixed_hold_40")
    assert SPEC.params == {"window": 252, "min_bars": 250, "threshold": 0.95, "top_n": 25, "stop_fraction": 0.85, "tie_adtv_sessions": 20}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {}
    assert SPEC.expected_trade_rate == 6.2 and SPEC.smallest_edge_of_interest == 0.15
    assert SPEC.prereg_ref is None and SPEC.validation_ref is None


@pytest.mark.parametrize("key,value", [("window", 251), ("min_bars", 249), ("threshold", 0.96), ("top_n", 24), ("stop_fraction", 0.86), ("tie_adtv_sessions", 21)])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    other = replace(SPEC, params={**SPEC.params, key: value})
    assert other.config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy_status_and_rates():
    for change in ({"exit_policy": "fixed_hold_41"}, {"expected_trade_rate": 6.0}, {"smallest_edge_of_interest": 0.2}, {"version": "1.0.1"}):
        assert replace(SPEC, **change).config_hash() != SPEC.config_hash()


def test_the_strategy_reads_its_numbers_from_the_spec(tmp_path):
    p = tmp_path / "lake.db"
    series = {f"C{k:02d}": np.concatenate([np.full(101, 90.0), np.full(L.N - 101, 100.0 * (1 - 0.0015 * k))]) for k in range(30)}
    for k in range(30):
        series[f"C{k:02d}"][100] = 100.0
    ds = L.build(p, series)
    assert len(propose(p, ds, 329, series)[0]) == 25
    s3 = NearHighStrategy(replace(SPEC, params={**P, "top_n": 3}))
    assert [x.symbol for x in propose(p, ds, 329, series, s3)[0]] == ["C00", "C01", "C02"]
    strict = NearHighStrategy(replace(SPEC, params={**P, "threshold": 0.995}))
    assert [x.symbol for x in propose(p, ds, 329, series, strict)[0]] == ["C00", "C01", "C02", "C03"]      # 1 - 0.0015 k >= 0.995  <=>  k <= 3.33
    assert propose(p, ds, 329, series, NearHighStrategy(replace(SPEC, params={**P, "stop_fraction": 0.5})))[0][0].stop == pytest.approx(50.0)


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    s = NearHighStrategy()
    b = Book.from_strategies([s])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []                       # research strategies never run in the live package (PAPER or LIVE)
    with pytest.raises(SpecError):
        replace(SPEC, status="live")                                  # a live spec needs a validation_ref
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["near_52w_high"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0                                  # importing the package does not put anything in the default registry


# ------------------------------------------------------------------------------------------------------------------------------------------ nearness and cuts
def test_nearness_matches_an_independent_computation_including_a_split_inside_the_window(tmp_path):
    rng = np.random.default_rng(7)
    series = {"UP": L.rise(100, 0.002) * (1 + 0.002 * rng.standard_normal(L.N)), "SPL": L.rise(150, 0.0022) * (1 + 0.002 * rng.standard_normal(L.N))}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (280, 1, 5)})
    for j in (251, 279, 290, 329):                                     # 279: the split is still in the future; 290, 329: it is inside the window
        props, _ = propose(p, ds, j, series)
        got = {x.symbol: x.metadata["nearness"] for x in props}
        for sym, c in series.items():
            want = near(c, j)
            if want >= 0.95:
                assert got[sym] == pytest.approx(want, rel=1e-12), (sym, j)
            else:
                assert sym not in got, (sym, j, want)
    raw_would_say = 0.2 * series["SPL"][290] / series["SPL"][279]      # a raw-price version would see a ~80% fall: the adjusted series must not
    assert raw_would_say < 0.95 and "SPL" in {x.symbol for x in propose(p, ds, 290, series)[0]}


def test_a_name_needs_252_bars_and_a_bar_on_the_as_of_date(tmp_path):
    series = {"OK": L.rise(100, 0.001), "SHORT": L.rise(100, 0.001)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"SHORT": {1, 2}})                    # bars on index 0 and 3.. : 250 bars at session 251, 251 at 252, 252 at 253
    assert {x.symbol for x in propose(p, ds, 251, series)[0]} == {"OK"}
    assert {x.symbol for x in propose(p, ds, 252, series)[0]} == {"OK"}                      # still one bar short
    assert {x.symbol for x in propose(p, ds, 253, series)[0]} == {"OK", "SHORT"}            # 252 bars; one session missing inside the window: passes
    assert {x.symbol for x in propose(p, ds, 329, series)[0]} == {"OK", "SHORT"}
    s2 = {"OK": series["OK"], "GONE": series["OK"]}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, s2, skip={"GONE": {300}})
    assert {x.symbol for x in propose(p2, ds2, 300, s2)[0]} == {"OK"}            # no bar on the as-of session: not proposed


def test_gap_guard_two_missing_pass_three_missing_drop_and_gaps_outside_the_window_do_not_count(tmp_path):
    base = L.rise(100, 0.001)
    series = {"GAP2": base, "GAP3": base, "OLD3": base, "NONE": base}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"GAP2": {290, 291}, "GAP3": {290, 291, 292}, "OLD3": {60, 61, 62}})
    got = {x.symbol for x in propose(p, ds, 329, series)[0]}
    assert got == {"GAP2", "OLD3", "NONE"}                              # 3 missing inside the last 252 sessions drops GAP3; OLD3's gap is before the window (starts at 78)
    assert "GAP3" in {x.symbol for x in propose(p, ds, 289, series)[0]}                 # before its gap opens it passes
    assert "GAP3" not in {x.symbol for x in propose(p, ds, 300, series)[0]}             # three missing sessions are inside the window from session 292 on


def test_threshold_edges_0_9500_in_and_0_9499_out(tmp_path):
    def edge(last):
        c = np.full(L.N, 80.0)
        c[100] = 100.0
        c[101:] = last
        return c
    series = {"EDGEOK": edge(95.0), "EDGELO": edge(94.99)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    props, _ = propose(p, ds, 329, series)
    assert [x.symbol for x in props] == ["EDGEOK"] and props[0].metadata["nearness"] == 0.95


def test_the_top_25_cut_the_rank_and_the_order_by_nearness(tmp_path):
    series = {}
    for k in range(30):
        c = np.full(L.N, 90.0)
        c[100] = 100.0
        c[101:] = 100.0 * (1 - 0.0015 * k)
        series[f"C{k:02d}"] = c
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    props, _ = propose(p, ds, 329, series)
    assert [x.symbol for x in props] == [f"C{k:02d}" for k in range(25)]            # the 25 nearest; C25..C29 are cut
    assert [x.rank for x in props] == [float(25 - i) for i in range(25)]            # an explicit ordinal rank: strictly decreasing, unique, higher first
    assert [x.metadata["nearness"] for x in props] == sorted((x.metadata["nearness"] for x in props), reverse=True)
    assert sorted(props, key=lambda x: (-x.rank, x.symbol)) == props                # the engine's own order (rank, then symbol) reproduces the strategy's order


def test_ties_go_by_adtv_then_symbol_and_the_rank_carries_that_order_not_the_alphabet(tmp_path):
    series = {f"V{k:02d}": np.full(L.N, 100.0) for k in range(30)}
    vol = {f"V{k:02d}": 6_000_000 + k * 1_000_000 for k in range(30)}               # V29 trades the most
    series["TIEA"], series["TIEC"] = np.full(L.N, 100.0), np.full(L.N, 100.0)       # equal ADTV (default volume): symbol order decides
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume=vol)
    props, _ = propose(p, ds, 329, series)
    syms = [x.symbol for x in props]
    assert len(props) == 25 and syms[:3] == ["V29", "V28", "V27"]
    assert syms == sorted(syms, key=lambda s: (-vol.get(s, 6_000_000), s))[:25] and syms != sorted(syms)
    assert [x.rank for x in props] == [float(25 - i) for i in range(25)]
    assert sorted(props, key=lambda x: (-x.rank, x.symbol)) == props               # the engine does not need symbol order to reproduce it
    two = {"TIEA": np.full(L.N, 100.0), "TIEC": np.full(L.N, 100.0)}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, two)
    assert [x.symbol for x in propose(p2, ds2, 329, two)[0]] == ["TIEA", "TIEC"]


def test_the_stop_is_0_85_times_the_signal_day_adjusted_close_in_the_as_of_basis(tmp_path):
    rng = np.random.default_rng(3)
    series = {"SPL": L.rise(150, 0.0022) * (1 + 0.002 * rng.standard_normal(L.N))}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (280, 1, 5)})
    for j, basis in ((270, 1.0), (290, 0.2)):                                      # the as-of basis is the price level in force on the as-of date: after the 1:5 split it is 0.2 x the old level
        (x,), _ = propose(p, ds, j, series)
        close_asof = float(series["SPL"][j]) * basis
        assert x.reference_price == pytest.approx(close_asof, rel=1e-12) and x.stop == pytest.approx(0.85 * close_asof, rel=1e-12)
        assert x.signal_date == ds[j] and x.strategy_id == "near_52w_high" and x.target is None and x.stop < x.reference_price
    raw_close_290 = float(series["SPL"][290]) * 0.2                                # what the raw lake holds on the signal day: equal to the as-of basis after the split
    assert propose(p, ds, 290, series)[0][0].stop == pytest.approx(0.85 * raw_close_290, rel=1e-12)


# ------------------------------------------------------------------------------------------------------------------------------------------ no look-ahead
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
    series = {"A": L.rise(100, 0.002), "B": L.rise(120, 0.0015), "C": np.full(L.N, 100.0)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume={"C": 9_000_000})
    alt = tmp_path / "alt.db"
    _alter_future(p, alt, ds[290], ds)
    for j in (260, 290):
        a, sa = propose(p, ds, j, series)
        b, sb = propose(alt, ds, j, series)
        assert a == b and sa == sb and a


# ------------------------------------------------------------------------------------------------------------------------------------------ isolation
def test_a_second_registered_strategy_does_not_change_these_proposals_and_state_is_plain(tmp_path):
    series = {"A": L.rise(100, 0.002), "B": L.rise(120, 0.0015)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    alone, st_alone = propose(p, ds, 260, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_two"))
    dummy = ScriptedStrategy(make_spec("dummy_two"), {ds[260].isoformat(): [{"symbol": "A", "stop": 1.0, "rank": 9.0}]})
    dummy.propose(view_of(p, ds, 260), ["A"], ds[260], {}, {})
    with_other, st_other = propose(p, ds, 260, series)
    assert alone == with_other and st_alone == st_other == {} and json.dumps(st_alone) == "{}"


def test_the_strategy_package_imports_only_what_a_strategy_may_import():
    pkg = ROOT / "stockbot" / "strategies" / "near_52w_high"
    allowed_std = {"__future__", "math", "typing", "dataclasses", "datetime", "collections"}
    for f in sorted(pkg.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [n.module] if isinstance(n, ast.ImportFrom) and n.module else [a.name for a in n.names] if isinstance(n, ast.Import) else []
            for m in mods:
                top = m.split(".")[0]
                if top == "stockbot":
                    assert m.startswith(("stockbot.strategies.base", "stockbot.strategies.spec", "stockbot.strategies.near_52w_high")), (f.name, m)
                else:
                    assert top in allowed_std, (f.name, m)
    other = [d.name for d in (ROOT / "stockbot" / "strategies").iterdir() if d.is_dir() and d.name not in ("near_52w_high", "__pycache__")]
    assert other == []


# ------------------------------------------------------------------------------------------------------------------------------------------ through the engine
SECTORS = {"A_GOOD": "S1", "B_STOP": "S2", "C_GAP": "S3"}


@pytest.fixture(scope="module")
def engine_lake(tmp_path_factory):
    series = {"A_GOOD": L.rise(100, 0.001), "B_STOP": L.rise(100, 0.0012), "C_GAP": L.rise(100, 0.0008)}
    series["B_STOP"][262:] = series["B_STOP"][261] * 0.7                    # a crash far below the stop 0.85 x signal close, on session 262
    p = tmp_path_factory.mktemp("nh_engine") / "lake.db"
    ds = L.build(p, series, skip={"C_GAP": {270, 271}})
    return p, ds


def run(engine_lake, days=range(251, 300)):
    p, ds = engine_lake
    s = NearHighStrategy()
    return run_days(p, [ds[i] for i in days], [s], policies_for([s.spec]), events=EventData(sectors=SECTORS))


def closed(decs):
    return {c.symbol: c for d in decs for c in d.closed}


def test_through_the_engine_exit_at_the_open_of_session_41_the_stop_earlier_and_a_no_bar_session_not_counted(engine_lake):
    p, ds = engine_lake
    decs, st = run(engine_lake)
    tickets = [t for d in decs for t in d.new_tickets if d.as_of == ds[251]]
    assert {t.symbol for t in tickets} == set(SECTORS) and all(t.stop == pytest.approx(0.85 * t.reference_price) for t in tickets)
    c = closed(decs)
    a = c["A_GOOD"]                                                         # signal at the close of 251, entry at the open of 252 = session 1, exit at the open of session 41
    assert (a.entry_date, a.exit_date, a.exit_reason) == (ds[252], ds[292], "TIME_EXIT")
    b = c["B_STOP"]
    assert (b.entry_date, b.exit_date, b.exit_reason) == (ds[252], ds[262], "STOP_HIT")        # the stop fires long before session 41
    g = c["C_GAP"]                                                          # bars missing on 270 and 271: they are not counted as held, so the exit is two sessions later
    assert (g.entry_date, g.exit_date, g.exit_reason) == (ds[252], ds[294], "TIME_EXIT")


def test_determinism_and_idempotency_through_the_engine_on_the_fixture_lake(engine_lake):
    (a, sa), (b, sb) = run(engine_lake), run(engine_lake)
    assert [d.to_json() for d in a] == [d.to_json() for d in b] and sa.to_json() == sb.to_json() and any(d.fills for d in a) and any(d.closed for d in a)
    p, ds = engine_lake
    s = NearHighStrategy()
    from stockbot.engine.decide import decide
    from stockbot.engine.types import State
    from tests.fixtures.engine_run import CFG
    conn = open_lake(p)
    pol = policies_for([s.spec])
    st = State.initial(1_000_000.0)
    for i in range(251, 262):
        _, st = decide(ds[i], st, AsOfView(conn, ds[i]), [s], CFG, EventData(sectors=SECTORS), policies=pol)
    d1, s1 = decide(ds[262], st, AsOfView(conn, ds[262]), [s], CFG, EventData(sectors=SECTORS), policies=pol)
    d2, s2 = decide(ds[262], st, AsOfView(conn, ds[262]), [s], CFG, EventData(sectors=SECTORS), policies=pol)       # the same session from the same state: the same bytes
    assert d1.to_json() == d2.to_json() and s1.to_json() == s2.to_json()


def test_the_strategy_and_the_stop_1_study_tool_rank_the_same_names_in_the_same_order(tmp_path):
    """The study tool (data_checks) and the strategy are two implementations of one rule; on the study's fixture lake they must agree on every session."""
    from stockbot.config.shared import load_shared_config
    from stockbot.data_checks import near_high_signal_count as M
    from stockbot.universe.eligibility import eligible_symbols
    from tests.fixtures import near_high_lake as F
    cfg = load_shared_config()
    p = tmp_path / "lake.db"
    ds, _ = F.build(p)
    conn = open_lake(p)
    s = NearHighStrategy()
    for j in (251, 270, 300, 329):
        view = AsOfView(conn, ds[j])
        elig = eligible_symbols(view, cfg.universe)
        study = M.snapshot(view, elig)["ranked"][:25]
        props, _ = s.propose(view, elig, ds[j], {}, {})
        assert [(x.symbol, x.metadata["nearness"]) for x in props] == study and study
    conn.close()

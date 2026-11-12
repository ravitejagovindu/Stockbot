"""low_volatility (stage 1): the strategy only PROPOSES. vol60 against an independent computation (split inside the window, no look-ahead), the first-session-of-the-month signal,
252 bars, the ADTV then symbol tie-break as an explicit rank, the top-25 cut, the stop, the spec hash, isolation, and the path through the real engine (fixed_hold_21, the stop,
the sector cap at 10% sizing, a month shorter than the hold). Fixture lakes only; finsight.db is never opened."""
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
from stockbot.strategies.low_volatility import SPEC, LowVolatilityStrategy, register
from stockbot.strategies.low_volatility.strategy import is_signal_session
from stockbot.strategies.registry import StrategyRegistry, default_registry
from stockbot.strategies.spec import SpecError
from tests.fixtures import near_high_series_lake as L
from tests.fixtures.dummies import ScriptedStrategy, make_spec
from tests.fixtures.engine_run import run_days

ROOT = Path(__file__).resolve().parents[2]
P = SPEC.params
SIG = (261, 284, 304, 326)            # first sessions of 2020-01, 02, 03, 04 on the fixture calendar (2019-01-01 start, weekdays only); 261 has 252+ bars for a name present from day 0


def view_of(path, ds, j):
    return AsOfView(open_lake(path), ds[j])


def propose(path, ds, j, symbols, strat=None):
    strat = strat or LowVolatilityStrategy()
    return strat.propose(view_of(path, ds, j), list(symbols), ds[j], {}, {})


def walk(scale, seed, start=100.0, n=L.N):
    """A price path whose daily log returns are scale x a fixed normal draw: its vol60 is close to ``scale`` and ordered by ``scale``."""
    z = np.random.default_rng(seed).standard_normal(n)
    return start * np.exp(np.cumsum(scale * z))


def vol60(c, j, w=60):
    return float(np.std(np.diff(np.log(c[j - w:j + 1])), ddof=1))


def family(k=30, seed=11):
    """k names with strictly increasing volatility (the same normal draw, scaled): name V00 is the calmest."""
    z = np.random.default_rng(seed).standard_normal(L.N)
    return {f"V{i:02d}": 100.0 * np.exp(np.cumsum((0.004 + 0.0004 * i) * z)) for i in range(k)}


# ------------------------------------------------------------------------------------------------------------------------------------------------ the spec
def test_the_spec_carries_every_number_the_owner_fixed():
    assert (SPEC.id, SPEC.version, SPEC.status, SPEC.exit_policy) == ("low_volatility", "1.0.0", "research", "fixed_hold_21")
    assert SPEC.params == {"rebalance": "first_session_of_month", "min_bars": 252, "vol_window": 60, "top_n": 25, "stop_fraction": 0.90, "tie_adtv_sessions": 20}
    assert SPEC.universe_overrides == {} and SPEC.overlays == {} and SPEC.validation_ref is None


@pytest.mark.parametrize("key,value", [("rebalance", "last_session_of_month"), ("min_bars", 251), ("vol_window", 61), ("top_n", 24), ("stop_fraction", 0.91), ("tie_adtv_sessions", 21)])
def test_the_config_hash_changes_when_a_parameter_changes(key, value):
    other = replace(SPEC, params={**SPEC.params, key: value})
    assert other.config_hash() != SPEC.config_hash() and replace(SPEC).config_hash() == SPEC.config_hash()


def test_the_config_hash_also_covers_the_exit_policy_status_and_rates():
    for change in ({"exit_policy": "fixed_hold_22"}, {"expected_trade_rate": 6.0}, {"smallest_edge_of_interest": 0.2}, {"version": "1.0.1"}, {"prereg_ref": "x.md"}):
        assert replace(SPEC, **change).config_hash() != SPEC.config_hash()


def test_status_research_cannot_run_in_live_or_paper_and_registration_is_explicit():
    b = Book.from_strategies([LowVolatilityStrategy()])
    with pytest.raises(ModeError):
        strategies_for_mode(b, "LIVE")
    assert strategies_for_mode(b, "PAPER") == []
    with pytest.raises(SpecError):
        replace(SPEC, status="live")
    reg = StrategyRegistry()
    assert register(reg) is SPEC and reg.ids() == ["low_volatility"]
    with pytest.raises(SpecError):
        register(reg)
    assert len(default_registry) == 0


# ------------------------------------------------------------------------------------------------------------------------------------------------ signal day
def test_it_proposes_only_on_the_first_session_of_a_calendar_month(tmp_path):
    series = family(5)
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    sig = [j for j in range(1, L.N) if (ds[j].year, ds[j].month) != (ds[j - 1].year, ds[j - 1].month)]
    assert [j for j in sig if j >= 252] == list(SIG)
    for j in range(252, L.N):
        props, st = propose(p, ds, j, series)
        assert bool(props) == (j in SIG), (j, ds[j])
        assert st == {}
        assert is_signal_session(view_of(p, ds, j), ds[j]) == (j in SIG)
    assert propose(p, ds, 261, series)[0][0].signal_date == date(2020, 1, 1)
    assert not is_signal_session(view_of(p, ds, 0), ds[0])           # the first session of the calendar has no previous session


# ------------------------------------------------------------------------------------------------------------------------------------------------ vol60
def test_vol60_matches_an_independent_computation_including_a_split_inside_the_window(tmp_path):
    series = {"AAA": walk(0.010, 1), "BBB": walk(0.014, 2), "SPL": walk(0.006, 3)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (290, 1, 5)})
    for j in (261, 304):                                              # 304: the 1:5 split (ex index 290) is inside the 61-close window; the series is the adjusted truth
        props, _ = propose(p, ds, j, series)
        got = {x.symbol: x.metadata["vol60"] for x in props}
        assert set(got) == set(series)
        for sym, c in series.items():
            assert got[sym] == pytest.approx(vol60(c, j), rel=1e-9), (sym, j)
        assert [x.symbol for x in props] == sorted(got, key=lambda s: got[s]) == ["SPL", "AAA", "BBB"]
    raw_would_say = np.std(np.diff(np.log(np.r_[series["SPL"][244:290], 0.2 * series["SPL"][290:305]])), ddof=1)      # an unadjusted split would look like a -80% day
    assert raw_would_say > 5 * vol60(series["SPL"], 304)


def test_lowest_vol_first_and_the_rank_is_an_explicit_ordinal(tmp_path):
    series = family(30)
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    props, _ = propose(p, ds, 261, series)
    assert [x.symbol for x in props] == [f"V{i:02d}" for i in range(25)]                    # the 25 calmest; V25..V29 are cut
    assert [x.rank for x in props] == [float(25 - i) for i in range(25)]
    assert [x.metadata["vol60"] for x in props] == sorted(x.metadata["vol60"] for x in props)
    assert sorted(props, key=lambda x: (-x.rank, x.symbol)) == props                      # the engine's own order (rank, then symbol) reproduces the strategy's order


def test_a_name_needs_252_bars_and_a_bar_on_the_signal_date(tmp_path):
    series = {"OK": walk(0.01, 4), "SHORT": walk(0.01, 5), "GONE": walk(0.01, 6)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"SHORT": set(range(20)), "GONE": {261}})                    # SHORT lists on session 20: 242 bars at 261, 265 at 284; GONE has no bar on 261
    assert {x.symbol for x in propose(p, ds, 261, series)[0]} == {"OK"}
    assert {x.symbol for x in propose(p, ds, 284, series)[0]} == {"OK", "SHORT", "GONE"}


def test_no_gap_guard_on_the_61_close_window_but_it_is_counted(tmp_path):
    series = {"GAPPY": walk(0.01, 7), "CLEAN": walk(0.01, 8)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, skip={"GAPPY": {240, 241, 242}})
    s = LowVolatilityStrategy()
    out = s.score(view_of(p, ds, 261), list(series), ds[261])
    assert {r[0] for r in out["ranked"]} == {"GAPPY", "CLEAN"} and out["window_gaps"] == ["GAPPY"] and out["zero_vol"] == []
    c = series["GAPPY"][[i for i in range(L.N) if i not in (240, 241, 242)]]
    got = dict((r[0], r[1]) for r in out["ranked"])["GAPPY"]
    assert got == pytest.approx(float(np.std(np.diff(np.log(c[len(c) - 61 - (L.N - 262):len(c) - (L.N - 262)])), ddof=1)), rel=1e-9)   # returns are taken over the bars it has


def test_ties_go_by_adtv_then_symbol_and_the_rank_carries_that_order(tmp_path):
    series = {f"V{k:02d}": np.full(L.N, 100.0) for k in range(30)}                           # flat: vol60 = 0 for all, an exact tie
    vol = {f"V{k:02d}": 6_000_000 + k * 1_000_000 for k in range(30)}
    series["TIEA"], series["TIEC"] = np.full(L.N, 100.0), np.full(L.N, 100.0)
    p = tmp_path / "lake.db"
    ds = L.build(p, series, volume=vol)
    s = LowVolatilityStrategy()
    out = s.score(view_of(p, ds, 261), list(series), ds[261])
    assert len(out["zero_vol"]) == 32
    props, _ = propose(p, ds, 261, series)
    syms = [x.symbol for x in props]
    assert syms[:3] == ["V29", "V28", "V27"] and syms == sorted(syms, key=lambda x: (-vol.get(x, 6_000_000), x)) and syms != sorted(syms) and len(props) == 25
    assert sorted(props, key=lambda x: (-x.rank, x.symbol)) == props
    two = {"TIEA": np.full(L.N, 100.0), "TIEC": np.full(L.N, 100.0)}
    p2 = tmp_path / "lake2.db"
    ds2 = L.build(p2, two)
    assert [x.symbol for x in propose(p2, ds2, 261, two)[0]] == ["TIEA", "TIEC"]


def test_the_stop_is_0_90_times_the_signal_day_adjusted_close_in_the_as_of_basis(tmp_path):
    series = {"SPL": walk(0.008, 9)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series, splits={"SPL": (270, 1, 5)})
    (x,), _ = propose(p, ds, 284, series)                                                  # after the 1:5 split (ex index 270): the as-of basis is the post-split raw level, 0.2 x the series
    assert x.reference_price == pytest.approx(0.2 * float(series["SPL"][284]), rel=1e-12) and x.stop == pytest.approx(0.90 * x.reference_price, rel=1e-12)
    assert x.signal_date == ds[284] and x.strategy_id == "low_volatility" and x.target is None
    (y,), _ = propose(p, ds, 261, series)                                                  # before the split: the lake holds the unadjusted level of that date
    assert y.reference_price == pytest.approx(float(series["SPL"][261]), rel=1e-12)
    s5 = LowVolatilityStrategy(replace(SPEC, params={**P, "stop_fraction": 0.5}))
    assert propose(p, ds, 284, series, s5)[0][0].stop == pytest.approx(0.5 * 0.2 * float(series["SPL"][284]))
    s3 = LowVolatilityStrategy(replace(SPEC, params={**P, "top_n": 3}))
    assert len(propose(p, ds, 284, family(30), s3)[0]) <= 3


# ------------------------------------------------------------------------------------------------------------------------------------------------ no look-ahead
def _alter_future(src: Path, dst: Path, after: date, ds):
    shutil.copy(src, dst)
    nxt = ds[ds.index(after) + 1]
    eng = create_engine(f"sqlite:///{dst.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*7, volume_raw=volume_raw*3 where trade_date>:d"),
                  {"d": after.isoformat()})
        c.execute(text("insert into corporate_actions_log(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('V00', :d, 'SPLIT', 1, 50, 'test', 'T1')"),
                  {"d": nxt.isoformat()})
    eng.dispose()


def test_changing_every_row_after_the_as_of_date_does_not_change_the_proposals(tmp_path):
    series = family(6)
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    alt = tmp_path / "alt.db"
    _alter_future(p, alt, ds[261], ds)
    a, sa = propose(p, ds, 261, series)
    b, sb = propose(alt, ds, 261, series)
    assert a == b and sa == sb and len(a) == 6


# ------------------------------------------------------------------------------------------------------------------------------------------------ isolation
def test_a_second_registered_strategy_does_not_change_these_proposals_and_state_is_plain(tmp_path):
    series = family(5)
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    alone, st_alone = propose(p, ds, 261, series)
    reg = StrategyRegistry()
    register(reg)
    reg.register(make_spec("dummy_two"))
    ScriptedStrategy(make_spec("dummy_two"), {ds[261].isoformat(): [{"symbol": "V00", "stop": 1.0, "rank": 9.0}]}).propose(view_of(p, ds, 261), ["V00"], ds[261], {}, {})
    other, st_other = propose(p, ds, 261, series)
    assert alone == other and st_alone == st_other == {} and json.dumps(st_alone) == "{}"


def test_the_strategy_package_imports_only_what_a_strategy_may_import():
    pkg = ROOT / "stockbot" / "strategies" / "low_volatility"
    allowed_std = {"__future__", "math", "typing", "dataclasses", "datetime", "collections", "numpy"}
    for f in sorted(pkg.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [n.module] if isinstance(n, ast.ImportFrom) and n.module else [a.name for a in n.names] if isinstance(n, ast.Import) else []
            for m in mods:
                top = m.split(".")[0]
                if top == "stockbot":
                    assert m.startswith(("stockbot.strategies.base", "stockbot.strategies.spec", "stockbot.strategies.low_volatility")), (f.name, m)
                else:
                    assert top in allowed_std, (f.name, m)


# ------------------------------------------------------------------------------------------------------------------------------------------------ through the engine
SECTORS = {"A_LOW": "S1", "B_SAME": "S1", "C_OTHER": "S2", "D_STOP": "S3"}


@pytest.fixture(scope="module")
def engine_lake(tmp_path_factory):
    z = np.random.default_rng(21).standard_normal(L.N)
    series = {"A_LOW": 100.0 * np.exp(np.cumsum(0.004 * z)), "B_SAME": 100.0 * np.exp(np.cumsum(0.005 * z)), "C_OTHER": 100.0 * np.exp(np.cumsum(0.006 * z)),
              "D_STOP": 100.0 * np.exp(np.cumsum(0.007 * z))}
    series["D_STOP"][270:] = series["D_STOP"][269] * 0.7                      # a crash far below the stop 0.90 x signal close, on session 270
    p = tmp_path_factory.mktemp("lv_engine") / "lake.db"
    ds = L.build(p, series)
    return p, ds


def run(engine_lake, days=range(260, 330)):
    p, ds = engine_lake
    s = LowVolatilityStrategy()
    return run_days(p, [ds[i] for i in days], [s], policies_for([s.spec]), events=EventData(sectors=SECTORS))


def test_through_the_engine_tickets_only_on_the_signal_day_with_the_stop_the_sector_cap_and_fixed_hold_21(engine_lake):
    p, ds = engine_lake
    decs, st = run(engine_lake)
    by_day = {d.as_of: d for d in decs}
    assert {d.as_of for d in decs if d.new_tickets} == {ds[261], ds[284], ds[326]}      # 304 is a signal day too, but no slot is free (see the next test)
    tk = {t.symbol: t for t in by_day[ds[261]].new_tickets}
    assert set(tk) == {"A_LOW", "C_OTHER", "D_STOP"} and all(t.stop == pytest.approx(0.90 * t.reference_price) for t in tk.values())
    blocked = [b for b in by_day[ds[261]].blocked if b.symbol == "B_SAME"]
    assert len(blocked) == 1 and "sector_S1" in blocked[0].reason                          # 10% sizing: a second name in S1 would be 20% > 15%
    closed = {c.symbol: c for d in decs for c in d.closed if c.entry_date == ds[262]}
    a = closed["A_LOW"]                                                                    # signal at the close of 261, entry at the open of 262 = session 1, exit at the open of session 22 = index 283
    assert (a.entry_date, a.exit_date, a.exit_reason) == (ds[262], ds[283], "TIME_EXIT")
    d = closed["D_STOP"]
    assert (d.entry_date, d.exit_date, d.exit_reason) == (ds[262], ds[270], "STOP_HIT")
    assert closed["C_OTHER"].exit_date == ds[283]


def test_a_month_shorter_than_the_hold_leaves_the_slots_full_at_the_next_signal(engine_lake):
    p, ds = engine_lake
    decs, _ = run(engine_lake)
    by_day = {d.as_of: d for d in decs}
    first = [t.symbol for t in by_day[ds[284]].new_tickets]
    assert sorted(first) == ["A_LOW", "C_OTHER", "D_STOP"]                                 # 261 -> 284 is 23 sessions: the first cohort (exit at the open of 283) is gone
    # 284 -> 304 is 20 sessions (< 21): the second cohort exits at the open of 306, after the signal close of 304, so those names are held and nothing new can be bought
    assert {f.symbol for f in by_day[ds[285]].fills} == {"A_LOW", "C_OTHER", "D_STOP"}
    assert not by_day[ds[304]].new_tickets                                                 # every proposal on 304 is for a name already held or has no slot: nothing is bought
    assert {c.exit_date for d in decs for c in d.closed if c.entry_date == ds[285]} == {ds[306]}   # the whole second cohort exits at the open of session 22 = index 306 (D_STOP is flat after its crash, so its stop is not hit again)
    assert not any(d.fills for d in decs if ds[286] <= d.as_of <= ds[325])                  # no entry between the two cohorts: that month of signals is lost


def test_determinism_through_the_engine_on_the_fixture_lake(engine_lake):
    (a, sa), (b, sb) = run(engine_lake), run(engine_lake)
    assert [d.to_json() for d in a] == [d.to_json() for d in b] and sa.to_json() == sb.to_json() and any(d.fills for d in a) and any(d.closed for d in a)

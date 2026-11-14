"""The near-52-week-high signal-count study (stockbot/data_checks/near_high_signal_count.py) on the synthetic fixture lake.

It must (1) reproduce independently computed nearness, gap-guard, data-quality counts and occupancy timing; (2) read no price after the as-of date - proved three ways: the SQL
actually issued (every date literal <= the session being evaluated), invariance of the results when every later row of the file is altered, and prefix-equality between a long
and a truncated run; (3) never compute a return (static scan); (4) leave the database file byte-identical."""
import ast
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from stockbot.config.shared import load_shared_config
from stockbot.data import sector_map
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.data_checks import near_high_signal_count as M
from stockbot.universe.eligibility import eligible_symbols
from tests.fixtures import mini_lake
from tests.fixtures import near_high_lake as F

CFG = load_shared_config()
ELIG = lambda view: eligible_symbols(view, CFG.universe)       # noqa: E731
ROOT = Path(__file__).resolve().parents[2]
FIRST = 251                                                    # index of the 252nd session


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("nh") / "lake.db"
    ds, base = F.build(p)
    return p, ds, base


@pytest.fixture(scope="module")
def study(lake):
    p, ds, base = lake
    conn = open_lake(p)
    res = M.run_study(conn, ELIG, end=ds[-1])
    conn.close()
    return res


def snap(lake, j):
    p, ds, _ = lake
    conn = open_lake(p)
    try:
        v = AsOfView(conn, ds[j])
        return M.snapshot(v, ELIG(v))
    finally:
        conn.close()


def expected_nearness(base, sym, j):
    return base[sym][j] / base[sym][j - 251:j + 1].max()


def test_first_valid_date_is_the_252nd_bar(lake, study):
    _, ds, _ = lake
    assert study["first_valid"] == ds[FIRST] == study["calendar_252nd_session"]
    assert study["calendar_first"] == ds[0] and len(study["sessions"]) == F.N
    assert M.summarise(study)["first_valid_nearness_date_calendar_only"] == str(ds[FIRST])


def test_nearness_matches_an_independent_computation(lake):
    _, ds, base = lake
    for j in (251, 270, 300, 329):
        s = snap(lake, j)
        got = dict(s["ranked"])
        for sym in F.CONTINUOUS:
            want = expected_nearness(base, sym, j)
            if want >= 0.95:
                assert got[sym] == pytest.approx(want, rel=1e-12), (sym, j)
            else:
                assert sym not in got, (sym, j, want)


def test_threshold_edges_exactly_095_in_and_09499_out(lake):
    s = snap(lake, 329)
    got = dict(s["ranked"])
    assert got["EDGEOK"] == 0.95 and "EDGELO" not in got
    assert 94.99 / 100.0 < 0.95


def test_ties_are_ranked_by_adtv_then_symbol_and_counted_as_exactly_one(lake):
    _, ds, base = lake
    for j in (260, 300, 329):
        s = snap(lake, j)
        ones = [sym for sym, n in s["ranked"] if n == 1.0]
        assert s["exact_one"] == len(ones) and {"TIEA", "TIEB", "TIEC"} <= set(ones)
        want = sorted(ones, key=lambda sym: (-F.raw_adtv(base, sym, j), sym))                  # independent: highest ADTV first, then symbol
        assert ones == want, (j, ones, want)
        assert ones.index("TIEB") < ones.index("TIEA") < ones.index("TIEC")                     # more volume first; equal ADTV falls back to symbol
        nears = [n for _, n in s["ranked"]]
        assert nears == sorted(nears, reverse=True)                                              # nearness stays the primary key


def test_adtv_is_fetched_only_for_tie_groups_that_start_inside_the_top_cut():
    class V:
        def __init__(self):
            self.calls = []

        def adtv(self, sym, period):
            self.calls.append((sym, period))
            return {"B": 5.0, "A": 5.0, "C": 9.0, "Z1": 1.0, "Z2": 2.0}.get(sym)

    v = V()
    cands = [("A", 1.0), ("B", 1.0), ("C", 1.0)] + [(f"Y{i:02d}", 0.99 - i * 0.0001) for i in range(30)] + [("Z1", 0.96), ("Z2", 0.96)]
    out = M.order_candidates(v, cands)
    assert [s for s, _ in out[:3]] == ["C", "A", "B"]                      # C has the highest ADTV; A and B tie on ADTV and fall back to symbol
    assert sorted(sym for sym, _ in v.calls) == ["A", "B", "C"] and {p for _, p in v.calls} == {20}
    assert [s for s, _ in out[-2:]] == ["Z1", "Z2"]                          # a tie group beyond the cut is left in symbol order and costs no query
    v2 = V()
    assert M.order_candidates(v2, [("X", 0.97), ("W", 0.97)]) == [("W", 0.97), ("X", 0.97)]     # no ADTV on record (None counts as 0): symbol order


def test_split_inside_the_window_is_adjusted_flagged_and_a_future_split_does_not_leak(lake):
    _, ds, base = lake
    s = snap(lake, 290)                                    # split ex 280 is known and inside the window: nearness is the ADJUSTED one, not -80%
    assert "SPLITCO" in s["split_in"]
    assert dict(s["ranked"])["SPLITCO"] == pytest.approx(expected_nearness(base, "SPLITCO", 290), rel=1e-9)
    s = snap(lake, 279)                                    # the split has not happened yet: not in the view, no flag, raw == base
    assert "SPLITCO" not in s["split_in"]
    assert dict(s["ranked"])["SPLITCO"] == pytest.approx(expected_nearness(base, "SPLITCO", 279), rel=1e-9)


def test_gap_guard_two_missing_pass_three_missing_drop(lake):
    s = snap(lake, 289)                                    # before the gaps: both valid
    assert {"GAP2", "GAP3"} <= s["valid"]
    s = snap(lake, 329)
    assert "GAP2" in s["valid"] and "GAP2" not in s["gap_dropped"]
    assert "GAP3" in s["gap_dropped"] and "GAP3" not in s["valid"]


def test_short_history_and_other_counts(lake, study):
    _, ds, _ = lake
    rows = {r["date"]: r for r in study["rows"]}
    assert rows[ds[100]]["valid"] == 0 and rows[ds[100]]["short"] == rows[ds[100]]["eligible"] - rows[ds[100]]["stale"]
    assert rows[ds[329]]["short"] == 1 and "LATECO" in study["ever"]["short"]
    assert rows[ds[329]]["gap_dropped"] == 1 and study["ever"]["gap_dropped"] == {"GAP3"}


def test_unadjusted_action_in_window_is_counted_and_a_dividend_type_is_not(lake, study):
    _, ds, _ = lake
    rows = {r["date"]: r for r in study["rows"]}
    assert rows[ds[299]]["unadj_in"] == 0 and rows[ds[300]]["unadj_in"] == 1 and rows[ds[329]]["unadj_in"] == 1
    assert study["unadj_types"].get("DEMERGER") == 30 and set(study["unadj_types"]) == {"DEMERGER"}
    assert rows[ds[329]]["split_in"] == 1 and rows[ds[260]]["split_in"] == 0


def test_occupancy_timing_hold_40_exit_at_open_of_session_41(lake, study):
    _, ds, _ = lake
    e = [x for x in study["entries"] if x["symbol"] == "UP1"]
    idx = [ds.index(x["entry"]) for x in e]
    assert idx[0] == FIRST + 1                                    # signal at the close of j, entry at the open of j+1
    assert e[0]["planned_exit"] == ds[idx[0] + 40]                # exit executes at the open of session 41 of the hold
    assert idx[1] == idx[0] + 41                                  # slot free for a signal at that close: next entry the session after
    occ = [r["occupancy"] for r in study["rows"]]
    assert occ[FIRST] == 0 and occ[FIRST + 1] > 0 and max(occ) <= 12


def test_cap_held_symbol_and_sector_rules():
    occ = M.Occupancy(100, 3, hold=2)
    occ.step(0, [("A", .99), ("B", .98), ("C", .97), ("D", .96)])
    assert [x[0] for x in occ.entries] == ["A", "B", "C"]
    occ.step(1, [("A", .99), ("D", .96)])
    assert len(occ.entries) == 3 and occ.occupancy == [0, 3]
    occ.step(3, [("A", .99), ("D", .96)])                         # entries at 1, hold 2 -> exit at the open of 3: free for a signal at the close of 3
    assert [x[0] for x in occ.entries][3:] == ["A", "D"]
    cap = M.Occupancy(100, 12, hold=40, pos_pct=100 / 15, sector_cap_pct=15.0)     # all fixture symbols are unmapped: each is its OWN sector (UNMAPPED:<symbol>), so none is blocked
    cap.step(0, [("X1", .99), ("X2", .98), ("X3", .97), ("X4", .96)])
    assert [x[0] for x in cap.entries] == ["X1", "X2", "X3", "X4"] and cap.blocks == [0]
    mapped = M.Occupancy(100, 12, hold=40, pos_pct=100 / 15, sector_cap_pct=15.0)  # a mapped sector is still capped: 2 x 6.67 = 13.3 fits, a third does not
    banks = [s for s, sec in sector_map._load().items() if sec == "FINANCIALS"][:4]
    mapped.step(0, [(b, .99 - i / 100) for i, b in enumerate(banks)])
    assert [x[0] for x in mapped.entries] == banks[:2] and mapped.blocks == [2]


def test_sector_cap_does_not_pool_unmapped_names(study):
    assert all(r["occupancy_capped"] == r["occupancy"] for r in study["rows"])        # the fixture symbols are all unmapped: the sector cap never binds
    assert sum(r["sector_blocks"] for r in study["rows"]) == 0
    assert len(study["entries_capped"]) == len(study["entries"])


def test_summary_json_and_markdown(lake, study):
    sm = M.summarise(study, measured=date(2026, 11, 10))
    json.dumps(sm, default=str)
    g = sm["groups"]["ALL (from first session)"]
    assert g["entries"] == sm["occupancy_model"]["entries_without_sector_cap"] > 0
    assert sm["params"]["position_pct_of_equity"] == pytest.approx(100 / 15)
    md = M.render_markdown(sm)
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert heads and all("measured 2026-11-10" in h for h in heads)
    assert "OCCUPANCY MODEL" in md and "RAISE the count" in md
    nd = sm["nearness_distribution"]
    assert nd["exactly_1_00"] > 0 and nd["candidate_sessions_total"] >= nd["exactly_1_00"]


def test_every_sql_statement_is_bounded_by_the_session_being_evaluated(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    seen, current = [], [None]
    conn.set_trace_callback(lambda sql: seen.append((current[0], sql)))
    M.run_study(conn, ELIG, end=ds[-1], start=ds[250], max_sessions=3, on_session=lambda t: current.__setitem__(0, t))
    conn.close()
    iso = re.compile(r"\d{4}-\d{2}-\d{2}")
    checked = 0
    for t, sql in seen:
        if t is None:
            continue
        for d in iso.findall(sql):
            assert d <= t.isoformat(), f"price query reaches past the as-of date {t}: {sql}"
        if "market_data_lake" in sql:
            assert re.search(r"trade_date\s*(<=|=)\s*'", sql) or sql.lstrip().lower().startswith("select min(trade_date) from market_data_lake where symbol="), sql
            checked += 1
    assert checked > 100


def _copy_with_future_altered(src: Path, dst: Path, after: date):
    shutil.copy(src, dst)
    s = mini_lake.sessions(F.N)
    nxt = s[s.index(after) + 1]
    eng = create_engine(f"sqlite:///{dst.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*7, volume_raw=volume_raw*3 where trade_date>:d"),
                  {"d": after.isoformat()})
        c.execute(text("insert into corporate_actions_log(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('UP1', :d, 'SPLIT', 1, 50, 'test', 'T1')"),
                  {"d": nxt.isoformat()})
    eng.dispose()


def test_results_up_to_a_date_do_not_depend_on_anything_after_it(lake, tmp_path):
    p, ds, _ = lake
    cut = ds[300]
    alt = tmp_path / "alt.db"
    _copy_with_future_altered(p, alt, cut)
    a, b, full = open_lake(p), open_lake(alt), open_lake(p)
    ra = M.run_study(a, ELIG, end=cut, start=ds[240])
    rb = M.run_study(b, ELIG, end=cut, start=ds[240])             # every row after `cut` made absurd, and a 1:50 split added just after it
    rf = M.run_study(full, ELIG, end=ds[-1], start=ds[240])
    for c in (a, b, full):
        c.close()
    drop = lambda rows: [{k: v for k, v in r.items() if not k.startswith("t_")} for r in rows]       # noqa: E731 - timings differ run to run
    assert drop(ra["rows"]) == drop(rb["rows"]) and ra["entries"] == rb["entries"] and ra["ever"] == rb["ever"]
    n = len(ra["rows"])
    assert drop(ra["rows"]) == drop(rf["rows"])[:n]
    key = lambda e: (e["symbol"], e["signal"], e["entry"], e["nearness"])     # noqa: E731
    assert [key(e) for e in rf["entries"] if e["signal"] < cut] == [key(e) for e in ra["entries"] if e["signal"] < cut]


def test_no_return_is_computed_and_no_strategy_or_engine_is_imported():
    src = (ROOT / "stockbot" / "data_checks" / "near_high_signal_count.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
        elif isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
    assert not [m for m in mods if m.startswith("stockbot") and not m.startswith(("stockbot.data.", "stockbot.config."))], mods
    for forbidden in ("pct_change", "shift(-", "stockbot.strategies", "forward", "sqlite3.connect", "sqlalchemy"):
        assert forbidden not in src.replace("never computes", "").replace("forward return", ""), forbidden


def test_fingerprint_and_cli_leave_the_database_untouched(lake, tmp_path):
    p, ds, _ = lake
    before = M.fingerprint(p)
    out_json, out_md = tmp_path / "o.json", tmp_path / "o.md"
    rc = M.cli(ELIG, argv=["--lake", str(p), "--end", ds[-1].isoformat(), "--start", ds[250].isoformat(), "--max-sessions", "5", "--out-json", str(out_json), "--out-md", str(out_md)])
    assert rc == 0 and M.fingerprint(p) == before and before["sha256"] and len(before["sha256"]) == 64
    sm = json.loads(out_json.read_text())
    assert sm["finsight_db"]["unchanged"] is True and "measured" in out_md.read_text()


def test_cached_segments_joined_equal_one_run(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    one = M.run_study(conn, ELIG, end=ds[-1], start=ds[240])
    a = M.collect_part(conn, ELIG, end=ds[289], start=ds[240])
    b = M.collect_part(conn, ELIG, end=ds[-1], start=ds[290])
    conn.close()
    a, b = M.part_from_json(json.loads(json.dumps(M.part_to_json(a)))), M.part_from_json(json.loads(json.dumps(M.part_to_json(b))))   # through JSON, as the cache is stored
    two = M.assemble(M.merge_parts([b, a]))                                                       # order of the arguments does not matter
    drop = lambda rows: [{k: v for k, v in r.items() if not k.startswith("t_")} for r in rows]    # noqa: E731 - timings differ run to run
    assert drop(one["rows"]) == drop(two["rows"]) and one["entries"] == two["entries"] and one["entries_capped"] == two["entries_capped"]
    assert one["ever"] == two["ever"] and one["bin_total"] == two["bin_total"] and one["exact_total"] == two["exact_total"] and one["unadj_types"] == two["unadj_types"]
    with pytest.raises(ValueError):
        M.merge_parts([a, a])


def test_part_and_assemble_cli_modes_match_the_single_run_and_never_touch_the_database(lake, tmp_path):
    p, ds, _ = lake
    before = M.fingerprint(p)
    f1, f2 = tmp_path / "a.json", tmp_path / "b.json"
    assert M.cli(ELIG, argv=["--lake", str(p), "--end", ds[289].isoformat(), "--start", ds[240].isoformat(), "--part-out", str(f1)]) == 0
    assert M.cli(ELIG, argv=["--lake", str(p), "--end", ds[-1].isoformat(), "--start", ds[290].isoformat(), "--part-out", str(f2)]) == 0
    out_json, out_md = tmp_path / "all.json", tmp_path / "all.md"
    assert M.cli(ELIG, argv=["--assemble", str(f1), str(f2), "--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    sm = json.loads(out_json.read_text())
    conn = open_lake(p)
    one = M.summarise(M.run_study(conn, ELIG, end=ds[-1], start=ds[240]))
    conn.close()
    assert sm["occupancy_model"] == one["occupancy_model"] and sm["entries"] == one["entries"] and sm["nearness_distribution"] == one["nearness_distribution"]
    assert sm["finsight_db"]["unchanged"] is True and len(sm["finsight_db"]["parts"]) == 2 and "part 1" in out_md.read_text()
    assert M.fingerprint(p) == before

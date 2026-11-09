"""The momentum signal-count study (stockbot/data_checks/momentum_signal_count.py) on the synthetic fixture lake.

It must (1) reproduce independently computed scores, trend flags, data-quality counts and the occupancy timing; (2) read no price after the as-of date - proved three ways: the
SQL actually issued (every date literal <= the session being evaluated), invariance of the results when every later row of the file is altered, and prefix-equality between a long
and a truncated run; (3) never compute a return (static scan); (4) leave the database file byte-identical."""
import ast
import json
import re
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from stockbot.config.shared import load_shared_config
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.data_checks import momentum_signal_count as M
from stockbot.universe.eligibility import eligible_symbols
from tests.fixtures import momentum_lake as F

CFG = load_shared_config()
ELIG = lambda view: eligible_symbols(view, CFG.universe)       # noqa: E731
ROOT = Path(__file__).resolve().parents[2]
UP = ["UP1", "UP2", "UP3", "UP4", "UP5", "SPLITCO", "GAPCO"]


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("mom") / "lake.db"
    ds, base = F.build(p)
    return p, ds, base


@pytest.fixture(scope="module")
def study(lake):
    p, ds, base = lake
    conn = open_lake(p)
    res = M.run_study(conn, ELIG, end=ds[-1])
    conn.close()
    return res


def expected_score(base, sym, j):
    return base[sym][j - 5] / base[sym][j - 131] - 1.0


def test_first_valid_date_is_the_200th_bar(lake, study):
    _, ds, _ = lake
    assert study["first_any_valid_score"] == ds[199] == study["calendar_200th_session"]
    assert study["calendar_first"] == ds[0] and len(study["sessions"]) == F.N
    sm = M.summarise(study)
    assert sm["first_valid_score_date"] == str(ds[199])


def test_scores_ranking_and_trend_match_an_independent_computation(lake, study):
    _, ds, base = lake
    first = [e for e in study["entries"] if e["signal"] == ds[199]]
    assert {e["symbol"] for e in first} == set(UP)                        # DN1, DN2 fail the trend test; LATECO is absent that day
    want = sorted(UP, key=lambda s: (-expected_score(base, s, 199), s))
    assert [e["symbol"] for e in first] == want
    for e in first:
        assert e["score"] == pytest.approx(expected_score(base, e["symbol"], 199), rel=1e-12)
        assert e["entry"] == ds[200]


def test_split_inside_the_window_is_adjusted_and_flagged_and_unknown_actions_do_not_leak(lake):
    p, ds, base = lake
    conn = open_lake(p)
    # session 230: the split (ex 220) is known and lies inside both windows; the score must be the ADJUSTED one, not -80%
    v = AsOfView(conn, ds[230])
    s = M.snapshot(v, ELIG(v), risk_pct=1.0, sector_cap_pct=15.0)
    sc = dict(s["ranked"])
    assert sc["SPLITCO"] == pytest.approx(expected_score(base, "SPLITCO", 230), rel=1e-9) and sc["SPLITCO"] > 0
    assert "SPLITCO" in s["ca126"] and "SPLITCO" in s["ca200"]
    # session 219: the split has not happened yet and is not in the view: no flag, raw == base
    v = AsOfView(conn, ds[219])
    s = M.snapshot(v, ELIG(v), risk_pct=1.0, sector_cap_pct=15.0)
    assert "SPLITCO" not in s["ca126"] and "SPLITCO" not in s["ca200"]
    assert dict(s["ranked"])["SPLITCO"] == pytest.approx(expected_score(base, "SPLITCO", 219), rel=1e-9)
    # session 340 would be far later; a session where the split is older than both windows does not exist in 300 sessions, so check the boundary: ex 220, 200-bar window of session 299 starts at 100
    v = AsOfView(conn, ds[299])
    s = M.snapshot(v, ELIG(v), risk_pct=1.0, sector_cap_pct=15.0)
    assert "SPLITCO" in s["ca200"] and "SPLITCO" in s["ca126"]            # window start 168 < 220
    conn.close()


def test_gap_short_history_and_counts(lake, study):
    _, ds, _ = lake
    rows = {r["date"]: r for r in study["rows"]}
    r = rows[ds[230]]
    assert r["gap200"] == 1 and r["gap_score"] == 1 and r["anygap200"] == 1       # GAPCO: 10 missing sessions inside both windows
    assert rows[ds[199]]["gap200"] == 0
    assert rows[ds[199]]["eligible"] == 9 and rows[ds[199]]["trend"] == 7 and rows[ds[199]]["trend_score"] == 7
    assert rows[ds[100]]["short"] == 9 and rows[ds[100]]["trend_score"] == 0 and rows[ds[100]]["score_only"] == 0   # fewer than 200 bars: dropped
    assert rows[ds[150]]["score_only"] == 9                                        # 132..199 bars: score computable, 200-bar trend is not
    assert rows[ds[290]]["short"] == 1                                             # LATECO is eligible again but has about 50 bars
    assert "LATECO" in study["ever"]["short"] and "GAPCO" in study["ever"]["gap200"]
    assert study["ever"]["gap200"] == {"GAPCO"}


def test_gap_helper():
    cal = [date(2020, 1, 1 + i) for i in range(10)]
    pos = {d: i for i, d in enumerate(cal)}
    assert M.max_gap([cal[0], cal[1], cal[7], cal[8]], pos) == 5          # 5 missing: not "longer than 5"
    assert M.max_gap([cal[0], cal[8]], pos) == 7
    assert M.max_gap([date(2019, 1, 1), cal[0], cal[1]], pos) == 0        # a bar before the calendar start is skipped


def test_occupancy_timing_follows_the_engine_order(lake, study):
    _, ds, _ = lake
    e = [x for x in study["entries"] if x["symbol"] == "UP1"]
    idx = [ds.index(x["entry"]) for x in e]
    assert idx[:3] == [200, 221, 242]                                      # signal j, entry j+1, exit at the open of entry+20, slot free for a signal at that close
    assert e[0]["planned_exit"] == ds[220]
    occ = [r["occupancy"] for r in study["rows"]]
    assert occ[199] == 0 and occ[200] == 7 and occ[219] == 7 and occ[220] == 0 and occ[221] == 7
    assert max(occ) <= 12
    naive = [r["occupancy_naive"] for r in study["rows"]]
    assert naive[219] == 0 and naive[220] == 7                              # the naive reading re-uses the slot one session earlier
    nv = M.Occupancy(100, 3, early=1)
    nv.step(0, [("A", .9)])
    nv.step(20, [("A", .9)])
    assert [x[2] for x in nv.entries] == [1, 21]                            # naive: spacing 20; engine order (early=0) spacing 21
    assert study["entries_naive"] >= len(study["entries"])


def test_cap_and_held_symbol_rules():
    occ = M.Occupancy(100, 3)
    occ.step(0, [("A", .9), ("B", .8), ("C", .7), ("D", .6)])
    assert [x[0] for x in occ.entries] == ["A", "B", "C"]                  # the cap limits entries, rank order kept
    occ.step(1, [("A", .9), ("D", .6)])
    assert len(occ.entries) == 3 and occ.occupancy == [0, 3]               # full: nothing more, a held symbol is never re-bought
    occ.step(21, [("A", .9), ("D", .6)])                                   # entries at 1 -> exit at the open of 21: all free again, A may re-enter
    assert [x[0] for x in occ.entries][3:] == ["A", "D"] and occ.occupancy[-1] == 0


def test_summary_json_and_markdown(lake, study):
    sm = M.summarise(study, measured=date(2026, 11, 9))
    json.dumps(sm, default=str)
    g = sm["groups"]["ALL (from first session)"]
    assert g["stats"]["trend_score"]["max"] == 7 and g["entries"] == sm["occupancy_model"]["entries_engine_order"] > 0
    assert sm["selected"]["distinct_symbols"] == 7 and sm["selected"]["symbols_without_sector"] == 7     # the fixture symbols are not in the sector map
    md = M.render_markdown(sm)
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert heads and all("measured 2026-11-09" in h for h in heads)
    assert "UPPER-BOUND OCCUPANCY MODEL" in md and "RAISE the count" in md
    tv = g["stats"]["top_value_pct"]
    assert tv and tv["max"] > 0 and "(xx) EXTRA" in md


def test_every_sql_statement_is_bounded_by_the_session_being_evaluated(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    seen, current = [], [None]
    conn.set_trace_callback(lambda sql: seen.append((current[0], sql)))
    M.run_study(conn, ELIG, end=ds[-1], max_sessions=230, on_session=lambda t: current.__setitem__(0, t))
    conn.close()
    iso = re.compile(r"\d{4}-\d{2}-\d{2}")
    checked = 0
    for t, sql in seen:
        if t is None:
            continue                                                       # the calendar enumeration before the first session (Nifty dates only, bounded by the study's own end)
        for d in iso.findall(sql):
            assert d <= t.isoformat(), f"price query reaches past the as-of date {t}: {sql}"
        if "market_data_lake" in sql:
            assert re.search(r"trade_date\s*(<=|=)\s*'", sql) or sql.lstrip().lower().startswith("select min(trade_date) from market_data_lake where symbol="), sql   # the one calendar-start probe in AsOfView.symbol_info
            checked += 1
    assert checked > 1000


def _copy_with_future_altered(src: Path, dst: Path, after: date):
    shutil.copy(src, dst)
    eng = create_engine(f"sqlite:///{dst.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*7, volume_raw=volume_raw*3 where trade_date>:d"), {"d": after.isoformat()})
        c.execute(text("insert into corporate_actions_log(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('UP1', :d, 'SPLIT', 1, 50, 'test', 'T1')"),
                  {"d": ds_after(after)})
    eng.dispose()


def ds_after(after: date) -> str:
    return mini_next(after).isoformat()


def mini_next(d: date) -> date:
    from tests.fixtures import mini_lake
    s = mini_lake.sessions(F.N)
    return s[s.index(d) + 1]


def test_results_up_to_a_date_do_not_depend_on_anything_after_it(lake, tmp_path):
    p, ds, _ = lake
    cut = ds[250]
    alt = tmp_path / "alt.db"
    _copy_with_future_altered(p, alt, cut)
    a, b, full = open_lake(p), open_lake(alt), open_lake(p)
    ra = M.run_study(a, ELIG, end=cut)
    rb = M.run_study(b, ELIG, end=cut)                                     # every row after `cut` was made absurd, and a 1:50 split was added just after it
    rf = M.run_study(full, ELIG, end=ds[-1])
    for c in (a, b, full):
        c.close()
    assert ra["rows"] == rb["rows"] and ra["entries"] == rb["entries"] and ra["ever"] == rb["ever"]
    n = len(ra["rows"])
    assert ra["rows"] == rf["rows"][:n]                           # a long run and a truncated run agree on every session up to the cut (occupancy fields included)
    key = lambda e: (e["symbol"], e["signal"], e["entry"], e["score"])     # noqa: E731 - planned_exit is None near the end of a truncated run
    assert [key(e) for e in rf["entries"] if e["signal"] < cut] == [key(e) for e in ra["entries"] if e["signal"] < cut]


def test_no_return_is_computed_and_no_strategy_or_engine_is_imported():
    src = (ROOT / "stockbot" / "data_checks" / "momentum_signal_count.py").read_text(encoding="utf-8")
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
    rc = M.cli(ELIG, argv=["--lake", str(p), "--end", ds[-1].isoformat(), "--max-sessions", "60", "--out-json", str(out_json), "--out-md", str(out_md)])
    assert rc == 0 and M.fingerprint(p) == before and before["sha256"] and len(before["sha256"]) == 64
    sm = json.loads(out_json.read_text())
    assert sm["finsight_db"]["unchanged"] is True and "measured" in out_md.read_text()

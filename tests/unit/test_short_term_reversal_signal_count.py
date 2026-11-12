"""The short_term_reversal signal-count study (scripts/strategies/short_term_reversal/signal_count.py) on synthetic fixture lakes.

It must (1) agree with the strategy on every session (it calls the strategy's own rule), (2) count signals, sessions over 25, ties, sector spread and the occupancy model as
computed independently, (3) read no price after the as-of date (the SQL actually issued, invariance when every later row is altered, prefix-equality of a short and a long run),
(4) never compute a return of the strategy (static scan: it issues no SQL of its own), and (5) leave the database file byte-identical."""
import importlib.util
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from stockbot.config.shared import load_shared_config
from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.strategies.short_term_reversal import ShortTermReversalStrategy
from stockbot.universe.eligibility import eligible_symbols
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "scripts" / "strategies" / "short_term_reversal" / "signal_count.py"
_spec = importlib.util.spec_from_file_location("str_signal_count", SRC)
M = importlib.util.module_from_spec(_spec)
sys.modules["str_signal_count"] = M
_spec.loader.exec_module(M)

CFG = load_shared_config()
ELIG = lambda view: eligible_symbols(view, CFG.universe)       # noqa: E731
J = 300


def fall(r: float, j: int = J) -> np.ndarray:
    c = np.full(L.N, 100.0)
    c[j:] = 100.0 * (1.0 + r)                                   # the fall on session j stays: signals persist while the anchor is still 100 (sessions j .. j+4)
    return c


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    """32 names signal on sessions 300..304: Z00..Z29 at -8% - 0.5% k (Z14 is -15%), plus T1 and T2 tied with Z14 at -15%. All unmapped (one UNKNOWN sector). UP never signals."""
    series = {f"Z{k:02d}": fall(-0.08 - 0.005 * k) for k in range(30)}
    series["T1"], series["T2"], series["UP"] = fall(-0.15), fall(-0.15), np.full(L.N, 100.0)
    vol = {"T1": 20_000_000, "T2": 30_000_000}
    p = tmp_path_factory.mktemp("strsc") / "lake.db"
    ds = L.build(p, series, volume=vol)
    return p, ds, series


@pytest.fixture(scope="module")
def part(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    out = M.collect_part(conn, ELIG, start=ds[296], end=ds[310])
    conn.close()
    return out


def row(part, ds, j):
    return next(r for r in part["rows"] if r["date"] == ds[j])


def test_the_study_and_the_strategy_rank_the_same_names_in_the_same_order(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    s = ShortTermReversalStrategy()
    for j in (298, 300, 302, 304, 306):
        view = AsOfView(conn, ds[j])
        elig = ELIG(view)
        snap = M.snapshot(view, elig)
        props, _ = s.propose(view, elig, ds[j], {}, {})
        assert snap["top"] == [(x.symbol, x.metadata["ret5"]) for x in props]
    conn.close()


def test_signal_counts_per_session_and_sessions_over_25(lake, part):
    _, ds, _ = lake
    assert [row(part, ds, j)["counts"].get("signals", 0) for j in (299, 300, 301, 304, 305)] == [0, 32, 32, 32, 0]
    r = row(part, ds, 300)
    assert (r["ordered_n"], len(r["top"]), r["counts"]["valid"], r["counts"]["above_cap"]) == (32, 25, 33, 1)
    sm = M.summarise(M.assemble(part))
    assert sm["groups"]["ALL (from first session)"]["sessions_over_top_n"] == 5 and sm["groups"]["ALL (from first session)"]["signals_total"] == 5 * 32
    assert sum(v["signals"] for v in sm["monthly"].values()) == 160 and sm["first_signal_date"] == str(ds[300])
    assert sm["monthly"][f"{ds[300].year}-{ds[300].month:02d}"]["signals"] >= 32


def test_the_floor_names_are_counted_and_not_signals(tmp_path):
    series = {"IN": fall(-0.10), "BELOW": fall(-0.35), "AT": fall(-0.30)}
    p = tmp_path / "lake.db"
    ds = L.build(p, series)
    conn = open_lake(p)
    view = AsOfView(conn, ds[J])
    s = M.snapshot(view, ELIG(view))
    conn.close()
    assert s["counts"]["below_floor"] == 1 and s["counts"]["signals"] == 2 and {x[0] for x in s["top"]} == {"IN", "AT"}


def test_ties_are_counted_inside_the_top_and_ranked_by_adtv(lake, part):
    _, ds, _ = lake
    r = row(part, ds, 300)
    assert (r["tie_names_in_top"], r["tie_groups_in_top"], r["tie_straddles_cut"], r["tie_symbol_decided"]) == (3, 1, False, 0)
    top = [s for s, _ in r["top"]]
    assert top.index("T2") < top.index("T1")                       # equal ret5 (-0.15): higher ADTV first (T2 30M, T1 20M)
    t = M.summarise(M.assemble(part))["tie_rate"]
    assert t["sessions_with_tie_group_in_top"] == 5 and t["proposed_names_in_a_tie_group"] == 15 and t["proposed_total"] == 125 and t["share_of_proposed_in_a_tie_group"] == pytest.approx(0.12)


def test_a_tie_that_straddles_the_cut_and_a_tie_that_even_adtv_cannot_break_are_counted(tmp_path):
    series = {f"X{k:02d}": fall(-0.12 - 0.005 * k) for k in range(24)}                      # 24 distinct falls deeper than -12%
    series["Y1"], series["Y2"], series["Y3"] = fall(-0.09), fall(-0.09), fall(-0.09)         # positions 25, 26, 27 tie
    p = tmp_path / "lake.db"
    ds = L.build(p, series)                                                                  # equal volume: ADTV equal too
    conn = open_lake(p)
    view = AsOfView(conn, ds[J])
    s = M.snapshot(view, ELIG(view))
    conn.close()
    assert s["tie_straddles_cut"] is True and s["top"][-1][0] == "Y1" and (s["tie_names_in_top"], s["tie_symbol_decided"]) == (1, 1)


def test_sector_spread_counts_every_signal_by_sector(lake, part):
    _, ds, _ = lake
    r = row(part, ds, 300)
    assert r["cand_sectors"] == {"UNKNOWN": 32} and (r["top_sector_distinct"], r["top_sector_max"], r["top_unknown"]) == (1, 25, 25)
    ss = M.summarise(M.assemble(part))["sector_spread"]
    assert ss["unknown_share"] == 1.0 and ss["signals_total"] == 160


def test_stop_fit_arithmetic_against_the_shared_caps():
    sf = M.stop_fit(risk_pct=1.0, max_positions=12, max_total_risk_pct=15.0, sector_cap_pct=15.0)
    assert sf["stop_distance_pct"] == pytest.approx(8.0) and sf["min_stop_distance_pct"] == pytest.approx(6.6667, abs=1e-3) and sf["fits"]
    assert sf["position_pct_of_equity"] == pytest.approx(12.5) and (sf["per_sector"], sf["cash_slots"], sf["risk_slots"], sf["binding_slots"]) == (1, 8, 15, 8)
    tight = M.stop_fit(risk_pct=1.0, max_positions=12, max_total_risk_pct=15.0, sector_cap_pct=10.0)           # a 10% sector cap needs a stop of at least 10%: 8% does not fit
    assert not tight["fits"]


def test_the_occupancy_model_hold_five_and_the_shared_caps(lake, part):
    _, ds, _ = lake
    res = M.assemble(part)
    plain, sector, shared = (res["entries"][k] for k in ("plain", "sector", "shared"))
    assert len(plain) == 12 and all(e["signal"] == ds[300] and e["entry"] == ds[301] and e["planned_exit"] == ds[306] for e in plain)      # 12 slots at the next open, exit five sessions later
    assert plain[0]["symbol"] == "Z29" and plain[0]["ret5"] == pytest.approx(-0.225)                                                              # the deepest fall first
    assert len(sector) == len(shared) == 1                                                       # one UNKNOWN-sector position at 12.5% of equity fits the 15% cap; a second does not
    assert sum(r["sector_blocks_shared"] for r in res["rows"]) > 0
    occ = {r["date"]: r["occ_plain"] for r in res["rows"]}
    assert occ[ds[310]] == 0 and occ[ds[301]] == 12 and occ[ds[305]] == 12 and occ[ds[306]] == 0 and occ[ds[300]] == 0


def test_the_occupancy_class_frees_the_slot_for_a_signal_at_the_close_of_the_exit_session_and_skips_held_names():
    o = M.Occupancy(20, 1, hold=5)
    for j in range(12):
        o.step(j, [("AAA", -0.1)])
    assert [(e[1], e[2], e[3]) for e in o.entries] == [(0, 1, 6), (6, 7, 12)]          # signal 0 -> entry 1 -> exit open of 6; a signal at the close of 6 re-enters at 7 (AAA is no longer held)
    o2 = M.Occupancy(20, 3, hold=5, pos_pct=12.5, sector_cap_pct=15.0)
    o2.step(0, [("ZZZ1", -0.2), ("ZZZ2", -0.1), ("ZZZ1", -0.1)])                       # two unmapped names share UNKNOWN: one fits, one is blocked
    assert [e[0] for e in o2.entries] == ["ZZZ1"] and o2.blocks == [1] and o2.open[0][0] == "ZZZ1"      # ZZZ2 blocked by the sector cap; the repeated ZZZ1 is skipped as held


def test_worst_market_days_and_their_share_of_signals():
    rows = [dict(date=date(2020, 1, 1 + i), nifty=(-0.05 if i < 3 else 0.001 * i), counts={"signals": 30 if i < 3 else 1}, top=[("A", 0)] * (25 if i < 3 else 1)) for i in range(20)]
    rows.append(dict(date=date(2020, 2, 1), nifty=None, counts={"signals": 99}, top=[]))             # no Nifty move (first session): not counted
    w = M.worst_days(rows, n=3)
    assert w["sessions_with_move"] == 20 and w["signals_total"] == 3 * 30 + 17 and w["signals_on_worst"] == 90 and w["share_of_signals"] == pytest.approx(90 / 107)
    assert w["uniform_share"] == pytest.approx(3 / 20) and w["sessions_over_top_n"] == 3 and w["over_top_n_that_are_worst"] == 3 and len(w["days"]) == 3
    assert w["share_of_proposed"] == pytest.approx(75 / 92)


def test_the_nifty_move_is_read_from_the_as_of_view(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    assert M.nifty_move(AsOfView(conn, ds[300])) == pytest.approx(0.0)                 # the fixture's index is flat
    assert M.nifty_move(AsOfView(conn, ds[0])) is None                                 # first session: no previous close
    conn.close()


# ------------------------------------------------------------------------------------------------------------------------------------------ point-in-time
def test_every_date_in_the_sql_issued_is_at_or_before_the_session_evaluated(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    seen: list = []
    conn.set_trace_callback(seen.append)
    view = AsOfView(conn, ds[302])
    M.snapshot(view, ELIG(view))
    conn.close()
    dates = [d for s in seen for d in re.findall(r"\d{4}-\d{2}-\d{2}", s)]
    assert dates and all(d <= ds[302].isoformat() for d in dates), sorted(set(dates))[-3:]


def test_changing_every_row_after_the_session_does_not_change_its_counts(lake, tmp_path):
    p, ds, _ = lake
    alt = tmp_path / "alt.db"
    shutil.copy(p, alt)
    eng = create_engine(f"sqlite:///{alt.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*7, volume_raw=volume_raw*3 where trade_date>:d"), {"d": ds[302].isoformat()})
        c.execute(text("insert into corporate_actions_log(symbol, ex_date, action_type, ratio_numerator, ratio_denominator, source, evidence_tier) values ('Z29', :d, 'SPLIT', 1, 50, 'test', 'T1')"),
                  {"d": ds[303].isoformat()})
    eng.dispose()
    out = []
    for path in (p, alt):
        conn = open_lake(path)
        v = AsOfView(conn, ds[302])
        s = M.snapshot(v, ELIG(v))
        conn.close()
        out.append(s)
    assert out[0] == out[1] and out[0]["ordered_n"] == 32


def test_a_short_run_equals_the_prefix_of_a_longer_run_and_joined_segments_equal_one_run(lake, part):
    p, ds, _ = lake
    conn = open_lake(p)
    short = M.collect_part(conn, ELIG, start=ds[296], end=ds[302])
    a = M.collect_part(conn, ELIG, start=ds[296], end=ds[300])
    b = M.collect_part(conn, ELIG, start=ds[301], end=ds[310])
    conn.close()
    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("t_")} for r in rows]       # noqa: E731  (timings differ)
    assert strip(short["rows"]) == strip(part["rows"][:len(short["rows"])])
    joined = M.merge_parts([M.part_from_json(json.loads(json.dumps(M.part_to_json(x)))) for x in (b, a)])        # any order, through JSON
    assert joined["sessions"] == part["sessions"] and strip(joined["rows"]) == strip(part["rows"])
    with pytest.raises(ValueError):
        M.merge_parts([a, short])


def test_the_study_issues_no_sql_of_its_own_and_computes_no_strategy_return():
    src = SRC.read_text(encoding="utf-8")
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    for banned in ("sqlite3", "sqlalchemy", ".execute(", "market_data_lake", "select ", "pnl", "win_rate", "forward"):
        assert banned not in code, banned
    assert sum(1 for ln in code.splitlines() if "close_raw" in ln) == 1 and "view.index_bars" in code                  # the only raw price read: the Nifty's own move on the as-of date (through the as-of view)


def test_the_database_file_is_byte_identical_after_a_full_cli_run(lake, tmp_path):
    p, ds, _ = lake
    before = M.fingerprint(p)
    out_json, out_md = tmp_path / "o.json", tmp_path / "o.md"
    rc = M.cli(ELIG, argv=["--lake", str(p), "--start", str(ds[296]), "--end", str(ds[310]), "--out-json", str(out_json), "--out-md", str(out_md)])
    assert rc == 0 and M.fingerprint(p) == before
    sm = json.loads(out_json.read_text(encoding="utf-8"))
    assert sm["finsight_db"]["unchanged"] and sm["groups"]["ALL (from first session)"]["signals_total"] == 160 and sm["stop_fit"]["fits"]
    md = out_md.read_text(encoding="utf-8")
    for h in ("(1) Stop fit", "(2) Signals per year", "(3) Signals per month", "(5) Clustering", "(6) Sector spread", "(7) Tie rate", "(8) Expected trade rate", "(9) Data quality"):
        assert h in md
    parts = []
    for k, (s, e) in enumerate(((ds[296], ds[300]), (ds[301], ds[310]))):
        pf = tmp_path / f"part{k}.json"
        assert M.cli(ELIG, argv=["--lake", str(p), "--start", str(s), "--end", str(e), "--part-out", str(pf)]) == 0
        parts.append(str(pf))
    out2 = tmp_path / "o2.json"
    assert M.cli(ELIG, argv=["--assemble", *parts, "--out-json", str(out2), "--out-md", str(tmp_path / "o2.md")]) == 0
    sm2 = json.loads(out2.read_text(encoding="utf-8"))
    assert sm2["groups"]["ALL (from first session)"]["signals_total"] == 160 and sm2["occupancy_model"]["entries"] == sm["occupancy_model"]["entries"]

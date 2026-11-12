"""scripts/signal_count_trend_breakout_100d.py (Stage 1, counts only) on a synthetic fixture lake: the per-session counts agree with the strategy and with an independent computation, the
near_52w_high overlap is exactly that rule's candidate test, the Nifty regime split is right (above / below / n/a), no price after the as-of date is read (alter every later row: the
earlier sessions do not change; segments joined equal one run), the occupancy model never exceeds the cap or double-holds a name, nothing computes a return, and the database file is untouched."""
import hashlib
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
from stockbot.strategies.trend_breakout_100d import TrendBreakoutStrategy
from stockbot.universe.eligibility import eligible_symbols
from tests.fixtures import near_high_series_lake as L

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "signal_count_trend_breakout_100d.py"
spec = importlib.util.spec_from_file_location("signal_count_trend_breakout_100d", SCRIPT)
M = importlib.util.module_from_spec(spec)
sys.modules["signal_count_trend_breakout_100d"] = M
spec.loader.exec_module(M)
CFG = load_shared_config()
ELIG = lambda v: eligible_symbols(v, CFG.universe)       # noqa: E731
N = L.N


def series():
    out = {"RISE1": L.rise(100, 0.001), "RISE2": L.rise(120, 0.0012)}
    c = np.full(N, 100.0)
    c[60] = 200.0                                           # a spike inside the 252-bar window: the breakout on 300 is only 55% of that high
    c[300:] = 110.0
    out["SPIKY"] = c
    b = np.full(N, 100.0)
    b[300:] = 110.0
    out["FLAT_THEN_UP"] = b
    out["FALLING"] = L.rise(200, -0.001)
    return out


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("tb_count") / "lake.db"
    s = series()
    ds = L.build(p, s)
    eng = create_engine(f"sqlite:///{p.as_posix()}")        # a Nifty that is above its 200-session mean for the first half of the lake and below it after
    with eng.begin() as c:
        for i, d in enumerate(ds):
            close = 20000.0 + 10.0 * i if i < 260 else 20000.0 + 10.0 * 260 - 40.0 * (i - 260)
            c.execute(text("update market_data_lake set close_raw=:c where symbol='NIFTY50_INDEX' and trade_date=:d"), {"c": close, "d": d.isoformat()})
    eng.dispose()
    return p, ds, s


@pytest.fixture(scope="module")
def part(lake):
    p, ds, _ = lake
    conn = open_lake(p)
    try:
        return M.collect_part(conn, ELIG, start=ds[199], end=ds[-1])
    finally:
        conn.close()


def row(part, d):
    return next(r for r in part["rows"] if r["date"] == d)


def test_counts_agree_with_the_strategy_and_with_an_independent_computation(lake, part):
    p, ds, s = lake
    for j in (199, 230, 260, 299, 300, 329):
        r = row(part, ds[j])
        want = {k for k, c in s.items() if c[j] > c[j - 100:j].max() and c[j] > c[j - 199:j + 1].mean()}
        conn = open_lake(p)
        got = [x.symbol for x in TrendBreakoutStrategy(M.WIDE).propose(AsOfView(conn, ds[j]), ELIG(AsOfView(conn, ds[j])), ds[j], {}, {})[0]]
        conn.close()
        assert set(got) == want and r["signals"] == len(want) and r["proposed"] == min(25, len(want)), j
        assert r["eligible"] == 5 and r["top"] == got[:25]


def test_overlap_is_exactly_the_near_52w_high_candidate_test(lake, part):
    p, ds, s = lake
    r = row(part, ds[300])
    assert {"SPIKY", "FLAT_THEN_UP"} <= set(r["top"])
    near = {k: c[300] / c[300 - 251:301].max() for k, c in s.items()}
    assert near["SPIKY"] < 0.95 <= near["FLAT_THEN_UP"]
    want = sum(1 for k in r["top"] if near[k] >= 0.95)
    assert r["overlap_all"] == want and r["overlap_top"] == want and 0 < want < r["signals"]


def test_regime_above_below_and_not_available(lake, part):
    p, ds, _ = lake
    nif = np.array([20000.0 + 10.0 * i if i < 260 else 20000.0 + 10.0 * 260 - 40.0 * (i - 260) for i in range(N)])
    for j in (199, 220, 259, 300, 329):
        mean = nif[j - 199:j + 1].mean()
        assert row(part, ds[j])["regime"] == ("above" if nif[j] > mean else "below"), j
    assert {r["regime"] for r in part["rows"]} == {"above", "below"}
    conn = open_lake(p)
    assert M.regime_of(AsOfView(conn, ds[150])) == "n/a"                      # fewer than 200 Nifty bars: no regime
    conn.close()


def test_no_price_after_the_as_of_date_is_read_and_segments_join_exactly(lake, part, tmp_path):
    p, ds, _ = lake
    alt = tmp_path / "alt.db"
    shutil.copy(p, alt)
    eng = create_engine(f"sqlite:///{alt.as_posix()}")
    with eng.begin() as c:
        c.execute(text("update market_data_lake set open_raw=open_raw*7, high_raw=high_raw*7, low_raw=low_raw*0.1, close_raw=close_raw*0.2, volume_raw=volume_raw*3 where trade_date>:d"),
                  {"d": ds[290].isoformat()})
    eng.dispose()
    conn = open_lake(alt)
    try:
        a = M.collect_part(conn, ELIG, start=ds[199], end=ds[290])
        late = M.collect_part(conn, ELIG, start=ds[291], end=ds[-1])
    finally:
        conn.close()
    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("t_")} for r in rows]    # noqa: E731
    assert strip(a["rows"]) == strip([r for r in part["rows"] if r["date"] <= ds[290]])
    merged = M.merge_parts([a, late])
    assert len(merged["rows"]) == len(part["rows"]) and merged["sessions"] == part["sessions"]
    with pytest.raises(ValueError):
        M.merge_parts([a, a])
    rt = M.part_from_json(json.loads(json.dumps(M.part_to_json(part), default=str)))
    assert strip(rt["rows"]) == strip(part["rows"])


def test_occupancy_never_exceeds_the_cap_nor_double_holds_a_name(part):
    for hold in (5, 20):
        o = M.occupancy(part["rows"], hold)
        assert max(o.occupancy) <= M.MAX_POSITIONS
        last = {}
        for sym, sig, ent, ext, _ in o.entries:
            assert sym not in last or ent >= last[sym]
            last[sym] = ext
    o = M.occupancy(part["rows"], 20)
    assert o.entries and all(e[2] == e[1] + 1 for e in o.entries)             # signal at a close, entry at the next open


def test_summary_has_the_regime_overlap_and_trade_rate_tables_and_renders(part):
    sm = M.summarise(part, measured=date(2026, 11, 12))
    g = sm["groups"]["ALL (sample)"]
    assert g["sessions"] == len(part["rows"]) and g["signal_name_sessions"] == sum(r["signals"] for r in part["rows"])
    assert sum(R["sessions"] for R in sm["regimes"].values()) == g["sessions"]
    assert sum(R["signal_name_sessions"] for R in sm["regimes"].values()) == g["signal_name_sessions"]
    assert {f"hold {h} / {v}" for h in M.HOLDS for v in ("no sector cap", "sector cap 15%")} == set(sm["occupancy_models"])
    md = M.render_markdown(sm)
    for needle in ("Overlap with near_52w_high", "Signals by market regime", "Trade-rate estimate", "ASSUMED"):
        assert needle in md


def test_the_script_computes_no_return_and_leaves_the_file_untouched(lake, tmp_path):
    src = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"pct_change|\.shift\(-|forward|pnl|win_rate", src, re.I)
    p, ds, _ = lake
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    out = tmp_path / "part.json"
    assert M.main(["--lake", str(p), "--start", ds[320].isoformat(), "--end", ds[-1].isoformat(), "--part-out", str(out)]) == 0
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["finsight_db"]["unchanged"] is True and len(data["rows"]) == 10
    md = tmp_path / "r.md"
    assert M.main(["--assemble", str(out), "--out-md", str(md), "--out-json", str(tmp_path / "r.json")]) == 0 and md.read_text(encoding="utf-8").startswith("# trend_breakout_100d")

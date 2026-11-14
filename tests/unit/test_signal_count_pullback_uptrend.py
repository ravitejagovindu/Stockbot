"""The counts-only study of pullback_uptrend (scripts/signal_count_pullback_uptrend.py) on a synthetic fixture lake: funnel counts against independent computation, the Nifty regime
and sell-off split, the 5-session occupancy timing, no read after the as-of date, and a byte-identical database file. Never opens finsight.db."""
import hashlib
import importlib.util
import shutil
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, text

from stockbot.config.shared import load_shared_config
from stockbot.data.lake import open_lake
from stockbot.universe.eligibility import eligible_symbols
from tests.fixtures import near_high_series_lake as L
from tests.unit.test_pullback_uptrend_strategy import S, uptrend_then_drops, wilder_rsi_independent

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("signal_count_pb", ROOT / "scripts" / "signal_count_pullback_uptrend.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
CFG = load_shared_config()
ELIG = lambda view: eligible_symbols(view, CFG.universe)       # noqa: E731


def set_nifty(path, ds, closes):
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    with eng.begin() as cx:
        for d, c in zip(ds, closes):
            cx.execute(text("update market_data_lake set close_raw=:c, open_raw=:c, high_raw=:c, low_raw=:c where symbol='NIFTY50_INDEX' and trade_date=:d"), {"c": float(c), "d": d.isoformat()})
    eng.dispose()


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    series = {"SIG": uptrend_then_drops(seed=1), "SIG2": uptrend_then_drops(seed=2, drops=(0.05, 0.05, 0.05)), "NODROP": uptrend_then_drops(drops=(), seed=4),
              "DOWN": 400.0 * 0.998 ** np.arange(L.N) * np.where(np.arange(L.N) > S - 3, 0.95, 1.0)}
    p = tmp_path_factory.mktemp("pbs") / "lake.db"
    ds = L.build(p, series)
    nifty = 20000.0 * 1.001 ** np.arange(L.N)
    nifty[S] = nifty[S - 1] * 0.97                                   # a 3% sell-off on the signal session, Nifty still above its SMA200
    set_nifty(p, ds, nifty)
    return p, ds, series


def part(p, ds, end_idx, start_idx=None):
    conn = open_lake(p)
    try:
        return M.collect_part(conn, ELIG, start=ds[start_idx] if start_idx else None, end=ds[end_idx])
    finally:
        conn.close()


def row_at(pt, ds, j):
    return next(r for r in pt["rows"] if r["date"] == ds[j].isoformat())


def test_funnel_counts_match_an_independent_computation(lake):
    p, ds, series = lake
    r = row_at(part(p, ds, S, S), ds, S)
    assert r["eligible"] == 4 and r["signals"] == 2 and {s for s, _ in r["top"]} == {"SIG", "SIG2"}
    assert r["trend_pass"] == 3                                      # SIG, SIG2, NODROP above their SMA200; DOWN is below
    assert r["trend_fail"] == 1 and r["pullback_only"] == 1          # DOWN fails the trend; NODROP passes it but its RSI is not < 10
    for s, rsi in r["top"]:
        assert rsi == pytest.approx(wilder_rsi_independent(series[s][:S + 1]), abs=1e-9)
    assert [s for s, _ in r["top"]] == ["SIG2", "SIG"]               # the bigger drop has the lower RSI


def test_regime_and_sell_off_fields(lake):
    p, ds, _ = lake
    pt = part(p, ds, S, S - 3)
    r = row_at(pt, ds, S)
    assert r["regime"] == "above"
    assert r["nifty_ret"] <= -2.0
    early = part(p, ds, 150, 150)
    assert row_at(early, ds, 150)["regime"] == "undefined" and row_at(early, ds, 150)["signals"] == 0       # fewer than 200 Nifty sessions


def test_assemble_regime_clustering_and_five_session_occupancy(lake):
    p, ds, _ = lake
    pt = part(p, ds, S + 12, S - 3)
    sm = M.assemble(M.merge_parts([pt]), max_positions=12, risk_pct=1.0, sector_cap_pct=15.0)
    first_sig = next(r["date"] for r in pt["rows"] if r["signals"])                                 # the first session with a signal (the series keeps signalling while it is flat)
    idx = [str(d) for d in ds].index(first_sig)
    sig = [e for e in sm["entries"] if e["symbol"] == "SIG"]
    assert sig[0]["signal"] == first_sig and sig[0]["entry"] == str(ds[idx + 1])
    assert sig[1]["entry"] == str(ds[idx + 1 + 6])                                                   # held 5 sessions, exit at the open of session 6, re-signal at that close, entry the next open
    assert sm["regime"]["above"]["signal_name_sessions"] == sm["clustering"]["total_signal_name_sessions"] and sm["regime"]["below"]["signal_name_sessions"] == 0
    assert sm["clustering"]["selloff"]["nifty_day_change_le_-2.0pct"]["sessions"] == 1
    assert sm["params"]["position_pct_of_equity"] == pytest.approx(12.5)
    assert "pullback_uptrend" in M.render_markdown(sm, "test")


def test_no_bar_after_the_as_of_date_is_read_and_the_database_file_is_untouched(lake, tmp_path):
    p, ds, _ = lake
    h0 = hashlib.sha256(p.read_bytes()).hexdigest()
    base = part(p, ds, S, S - 3)
    assert hashlib.sha256(p.read_bytes()).hexdigest() == h0
    q = tmp_path / "alt.db"
    shutil.copy(p, q)
    eng = create_engine(f"sqlite:///{q.as_posix()}")
    with eng.begin() as cx:
        cx.execute(text("update market_data_lake set open_raw=open_raw*3, high_raw=high_raw*3, low_raw=low_raw*0.1, close_raw=close_raw*0.2, volume_raw=1 where trade_date > :d"), {"d": ds[S].isoformat()})
    eng.dispose()
    alt = part(q, ds, S, S - 3)
    strip = lambda pt: [{k: v for k, v in r.items() if not k.startswith("t_")} for r in pt["rows"]]     # noqa: E731
    assert strip(alt) == strip(base)

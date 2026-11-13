"""Diff harness: SQL AsOfView against MemoryAsOfView on the REAL lake (read-only), over a fixed, seeded set of sessions.

  py -3 docs/shared/fast-view/diff_views.py --out DIR [--shard I/N] [--list-only]

Sessions (window 2016-01-01 .. lake end): first, last, every month end, 100 random (seed 20261113), and the session before / of / after the ex-date of 20 random SPLIT, 20 BONUS,
20 DEMERGER and 20 RIGHTS actions. For each session and each view it records, per symbol that traded that day: symbol_info, adtv(20), a sha256 of adjusted_bars (default lookback 400)
and of raw_bars; and for the day: symbols_trading and eligible_symbols (shared universe config) as ordered lists. Zero differences are required. Nothing is written to the lake.
"""
import argparse
import hashlib
import json
import random
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np  # noqa: E402

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.asof_memory import MemoryAsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402

SEED, WINDOW_START = 20261113, date(2016, 1, 1)


def peak_rss_mb() -> float:
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    ctypes.windll.psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.PeakWorkingSetSize / 1048576.0


def pick_sessions(conn) -> list:
    last_day = date.fromisoformat(conn.execute("select max(trade_date) from market_data_lake where symbol='NIFTY50_INDEX'").fetchone()[0])
    ses = [d for d in AsOfView(conn, last_day).sessions() if d >= WINDOW_START]
    chosen = {ses[0], ses[-1]}
    by_month: dict = {}
    for d in ses:
        by_month[(d.year, d.month)] = d
    chosen |= set(by_month.values())
    rng = random.Random(SEED)
    chosen |= set(rng.sample(ses, 100))
    pos = {d: i for i, d in enumerate(ses)}
    for typ in ("SPLIT", "BONUS", "DEMERGER", "RIGHTS"):
        exs = sorted({date.fromisoformat(r[0][:10]) for r in conn.execute("select ex_date from corporate_actions_log where action_type=?", (typ,))})
        exs = [e for e in exs if ses[1] <= e <= ses[-2]]
        for e in rng.sample(exs, min(20, len(exs))):
            i = next((k for k, d in enumerate(ses) if d >= e), None)
            if i is not None:
                chosen |= {ses[j] for j in (i - 1, i, i + 1) if 0 <= j < len(ses)}
    return sorted(chosen)


def frame_hash(df) -> str:
    h = hashlib.sha256()
    h.update(repr((list(df.columns), [str(t) for t in df.dtypes], str(df.index.dtype), df.index.name, [d.isoformat() for d in df.index])).encode())
    h.update(np.ascontiguousarray(df.to_numpy()).tobytes())
    return h.hexdigest()


def snapshot(view, universe) -> dict:
    out = {}
    out["symbols_trading"] = view.symbols_trading()
    syms = out["symbols_trading"]
    out["symbol_info"] = {s: repr(view.symbol_info(s)) for s in syms}
    out["adtv"] = {s: repr(view.adtv(s)) for s in syms}
    out["adj_hash"] = {s: frame_hash(view.adjusted_bars(s)) for s in syms}
    out["raw_hash"] = {s: frame_hash(view.raw_bars(s)) for s in syms}
    out["eligible"] = eligible_symbols(view, universe)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()
    i, n = (int(x) for x in a.shard.split("/"))
    conn = open_lake()
    days = pick_sessions(conn)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.list_only:
        print(len(days), days[0], days[-1])
        (out / "sessions.json").write_text(json.dumps([d.isoformat() for d in days]), encoding="utf-8")
        return 0
    mine = days[i::n]
    universe = load_shared_config().universe
    t0 = time.time()
    MemoryAsOfView(conn, mine[0])                                      # load once
    load_s = time.time() - t0
    diffs, compared, t_sql, t_mem = [], {"sessions": 0, "symbols": 0}, 0.0, 0.0
    for d in mine:
        sql_view, mem_view = AsOfView(conn, d), MemoryAsOfView(conn, d)
        assert type(sql_view) is AsOfView
        t = time.time(); a_sql = snapshot(sql_view, universe); t_sql += time.time() - t
        t = time.time(); a_mem = snapshot(mem_view, universe); t_mem += time.time() - t
        compared["sessions"] += 1
        compared["symbols"] += len(a_sql["symbols_trading"])
        for k in a_sql:
            if a_sql[k] != a_mem[k]:
                if isinstance(a_sql[k], dict):
                    bad = [s for s in set(a_sql[k]) | set(a_mem[k]) if a_sql[k].get(s) != a_mem[k].get(s)]
                    diffs.append({"date": d.isoformat(), "what": k, "n": len(bad), "first": [(s, a_sql[k].get(s), a_mem[k].get(s)) for s in sorted(bad)[:5]]})
                else:
                    diffs.append({"date": d.isoformat(), "what": k, "sql_len": len(a_sql[k]), "mem_len": len(a_mem[k])})
        print(f"{d} symbols {len(a_sql['symbols_trading'])} eligible {len(a_sql['eligible'])} sql {t_sql:.0f}s mem {t_mem:.0f}s diffs {len(diffs)}", flush=True)
    res = {"shard": a.shard, "sessions_total": len(days), "sessions_this_shard": len(mine), "compared": compared, "differences": len(diffs), "diff_detail": diffs[:50],
           "seconds_sql": t_sql, "seconds_memory": t_mem, "memory_load_seconds": load_s, "peak_rss_mb": peak_rss_mb()}
    (out / f"result_{i}of{n}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "diff_detail"}))
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())

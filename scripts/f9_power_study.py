"""scripts/f9_power_study.py — F9 step 2: size and power of the Westfall-Young step-down Max-T block bootstrap on portfolio-level periodic returns.

Design, blocks, replications, decision rule and the smallest edge of interest are fixed in docs/F9_PREREGISTRATION.md (committed before this ran).
Input: data/f9/trade_library.npz (scripts/f9_trade_library.py).  Output: data/f9/power_results.json, docs/F9_POWER_RESULTS.md.
"""
from __future__ import annotations

import json
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine_core.max_t_bootstrap import WestfallYoungMaxTBootstrap          # noqa: E402

LIB = ROOT / "data" / "f9" / "trade_library.npz"
K, MAX_OPEN, P_ENTRY, RISK_FRAC, B, SEED = 6, 12, 0.188, 0.01, 2000, 20261108   # P_ENTRY: pre-registration Amendment 1
EDGES = (0.0, 0.05, 0.10, 0.15, 0.25, 0.50)
BLOCKS = {"weekly": (4, 8), "monthly": (2, 3)}
REPS_SIZE, REPS_POWER = 2000, 1000
_G: dict = {}


def init():
    z = np.load(LIB, allow_pickle=False)
    start, length, offset, flat, sym = z["start"], z["length"], z["offset"], z["flat"], z["symbol"]
    dates = pd.to_datetime(z["session_dates"])
    S = len(dates)
    by_start: dict[int, np.ndarray] = {}
    order = np.argsort(start, kind="stable")
    for s in np.unique(start):
        by_start[int(s)] = order[np.searchsorted(start[order], s):np.searchsorted(start[order], s, side="right")]
    week = (dates.isocalendar().year.values.astype(int) * 100 + dates.isocalendar().week.values.astype(int))
    month = dates.year.values * 100 + dates.month.values
    def bounds(key):
        chg = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
        return chg
    _G.update(start=start, length=length, offset=offset, flat=flat, sym=sym, S=S, by_start=by_start, dates=dates,
              bounds={"weekly": bounds(week), "monthly": bounds(month)}, entry_sessions=np.array(sorted(by_start)))


def portfolio(rng, edge: float = 0.0):
    """Daily return vector (fraction of equity) of one random-entry portfolio, plus the number of trades."""
    S, flat, offset, length, start = _G["S"], _G["flat"], _G["offset"], _G["length"], _G["start"]
    r = np.zeros(S + 400)
    open_end: list[tuple[int, str]] = []
    n = 0
    draws = rng.random(len(_G["entry_sessions"])) < P_ENTRY
    for s in _G["entry_sessions"][draws]:
        open_end = [(e, y) for e, y in open_end if e > s]
        if len(open_end) >= MAX_OPEN:
            continue
        cand = _G["by_start"][int(s)]
        t = int(cand[rng.integers(len(cand))])
        if any(y == _G["sym"][t] for _, y in open_end):
            continue
        L = int(length[t])
        r[s:s + L] += flat[offset[t]:offset[t] + L]
        if edge:
            r[s:s + L] += edge * RISK_FRAC / L
        open_end.append((s + L, _G["sym"][t]))
        n += 1
    return r[:S], n


def to_periods(r: np.ndarray, freq: str) -> np.ndarray:
    return np.add.reduceat(r, _G["bounds"][freq])


def one_rep(rng, freq: str, n_periods: int, edge: float, seed: int):
    base, n_base = portfolio(rng)
    cols = []
    for k in range(K):
        p, _ = portfolio(rng, edge if k == 0 else 0.0)
        cols.append(p - base)
    D = np.column_stack([to_periods(c, freq) for c in cols])
    total = D.shape[0]
    a = int(rng.integers(0, total - n_periods + 1)) if total > n_periods else 0
    D = D[a:a + n_periods]
    df = pd.DataFrame(D, columns=[f"CFG-{i + 1:02d}" for i in range(K)])
    b1, b2 = BLOCKS[freq]
    res = WestfallYoungMaxTBootstrap(df, num_replications=B, fwer_alpha=0.05, seed=seed, block_size=b1,
                                     sensitivity_block_sizes=[b1, b2]).run_sensitivity()
    sig = {b: np.array([x.fwer_significant for x in res[b]]) for b in (b1, b2)}
    dual = sig[b1] & sig[b2]
    return sig, dual, D, n_base / len(_G["bounds"][freq])


def run_task(args):
    freq, n_periods, edge, reps = args
    if not _G:
        init()
    rng = np.random.default_rng(SEED + zlib.crc32(f"{freq}|{n_periods}|{int(round(edge * 1000))}".encode()) % 1000003)
    b1, b2 = BLOCKS[freq]
    any_b1 = any_b2 = any_dual = c1_b1 = c1_b2 = c1_dual = 0
    sd_acc, shift_acc, tpp_acc = [], [], []
    for i in range(reps):
        sig, dual, D, tpp = one_rep(rng, freq, n_periods, edge, seed=SEED * 1000 + i)
        tpp_acc.append(tpp)
        any_b1 += bool(sig[b1].any()); any_b2 += bool(sig[b2].any()); any_dual += bool(dual.any())
        c1_b1 += bool(sig[b1][0]); c1_b2 += bool(sig[b2][0]); c1_dual += bool(dual[0])
        sd_acc.append(D.std(axis=0, ddof=1).mean()); shift_acc.append(D[:, 0].mean() - D[:, 1:].mean())
    return dict(freq=freq, n_periods=n_periods, edge=edge, reps=reps, blocks=[b1, b2],
                size_any_block1=any_b1 / reps, size_any_block2=any_b2 / reps, size_any_dual=any_dual / reps,
                cfg1_sig_block1=c1_b1 / reps, cfg1_sig_block2=c1_b2 / reps, cfg1_sig_dual=c1_dual / reps,
                trades_per_period=float(np.mean(tpp_acc)), mean_period_sd=float(np.mean(sd_acc)), mean_observed_shift_cfg1_minus_nulls=float(np.mean(shift_acc)))


def main() -> int:
    quick = "--quick" in sys.argv
    tasks = []
    for freq in ("weekly", "monthly"):
        for n in (60, 81):
            for e in EDGES:
                reps = (40 if quick else (REPS_SIZE if e == 0 else REPS_POWER))
                tasks.append((freq, n, e, reps))
    t0 = time.time()
    out = []
    with ProcessPoolExecutor(max_workers=min(len(tasks), 8), initializer=init) as ex:
        for r in ex.map(run_task, tasks):
            out.append(r)
            print(f"{r['freq']:8s} n={r['n_periods']} edge={r['edge']:.2f} reps={r['reps']} size_dual={r['size_any_dual']:.3f} power_dual={r['cfg1_sig_dual']:.3f} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    path = ROOT / "data" / "f9" / ("power_results_quick.json" if quick else "power_results.json")
    path.write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

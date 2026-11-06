"""scripts/validate_max_t.py — F9: size (FWER) and power of the pre-registered Westfall-Young Max-T block bootstrap.

Monte-Carlo, fully seeded. Data-generating processes (all K=6 configs share a common factor, cross-correlation ~0.5):
  AR(1)        x_t = rho x_{t-1} + e_t            rho in {0, 0.2, 0.4, 0.6}
  OVERLAP-L    x_t = sum_{j<L} e_{t+j} / sqrt(L)  L in {4, 12}  (an MA(L-1): trades entered in adjacent weeks share
               their holding window, which is what long holds do to an ENTRY-week keyed weekly statistic)
Size  = P(at least one of the 6 true-null configs has adjusted p <= 0.05).
Power = P(config 1, which has a true mean shift of d weekly-SDs, is declared significant).
Rules compared: single block {2, 4, 8} and the pre-registered DUAL rule (significant at block 4 AND block 8).

Usage: py -3 scripts/validate_max_t.py --reps 500 --B 2000 --out docs/MAXT_VALIDATION.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_core.max_t_bootstrap import WestfallYoungMaxTBootstrap  # noqa: E402

K = 6
COMMON = 0.5  # cross-config correlation target (loading sqrt(0.5) on a shared factor)
BLOCKS = (2, 4, 8)


def innovations(rng: np.random.Generator, n: int, k: int) -> np.ndarray:
    common = rng.standard_normal((n, 1))
    idio = rng.standard_normal((n, k))
    return np.sqrt(COMMON) * common + np.sqrt(1 - COMMON) * idio  # unit variance, corr COMMON


def gen_ar1(rng, w: int, rho: float) -> np.ndarray:
    e = innovations(rng, w + 50, K) * np.sqrt(1 - rho ** 2)
    x = np.zeros_like(e)
    for t in range(1, len(e)):
        x[t] = rho * x[t - 1] + e[t]
    return x[50:]  # burn-in dropped


def gen_overlap(rng, w: int, length: int) -> np.ndarray:
    e = innovations(rng, w + length - 1, K)
    cs = np.cumsum(np.vstack([np.zeros((1, K)), e]), axis=0)
    return (cs[length:length + w] - cs[:w]) / np.sqrt(length)  # moving sum of `length` shocks, unit variance


def one_rep(x: np.ndarray, B: int, seed: int, delta: float | None):
    X = x.copy()
    if delta is not None:
        X[:, 0] += delta
    df = pd.DataFrame(X, columns=[f"CFG-{i + 1:02d}" for i in range(K)])
    res = WestfallYoungMaxTBootstrap(df, num_replications=B, fwer_alpha=0.05, seed=seed,
                                     sensitivity_block_sizes=list(BLOCKS)).run_sensitivity()
    sig = {b: np.array([r.fwer_significant for r in res[b]]) for b in BLOCKS}
    return sig


def run_cell(gen, w: int, reps: int, B: int, seed: int, delta: float | None = None) -> dict:
    rng = np.random.default_rng(seed)
    n_any = {b: 0 for b in BLOCKS}
    n_any["dual"] = 0
    n_c1 = {b: 0 for b in BLOCKS}
    n_c1["dual"] = 0
    for i in range(reps):
        sig = one_rep(gen(rng, w), B, seed * 100003 + i, delta)
        for b in BLOCKS:
            n_any[b] += bool(sig[b].any())
            n_c1[b] += bool(sig[b][0])
        dual = sig[4] & sig[8]
        n_any["dual"] += bool(dual.any())
        n_c1["dual"] += bool(dual[0])
    return {"reps": reps,
            "any": {str(k): v / reps for k, v in n_any.items()},
            "cfg1": {str(k): v / reps for k, v in n_c1.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=500)
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--weeks", type=int, nargs="+", default=[80, 250])
    ap.add_argument("--deltas", type=float, nargs="+", default=[0.15, 0.30])
    ap.add_argument("--out", default=str(ROOT / "docs" / "MAXT_VALIDATION.md"))
    ap.add_argument("--json", default=str(ROOT / "docs" / "maxt_validation.json"))
    args = ap.parse_args()

    dgps = [("AR(1) rho=0.0", lambda r, w: gen_ar1(r, w, 0.0)), ("AR(1) rho=0.2", lambda r, w: gen_ar1(r, w, 0.2)),
            ("AR(1) rho=0.4", lambda r, w: gen_ar1(r, w, 0.4)), ("AR(1) rho=0.6", lambda r, w: gen_ar1(r, w, 0.6)),
            ("OVERLAP L=4", lambda r, w: gen_overlap(r, w, 4)), ("OVERLAP L=12", lambda r, w: gen_overlap(r, w, 12))]
    out = {"args": vars(args), "size": {}, "power": {}}
    t0 = time.time()
    for name, gen in dgps:
        for w in args.weeks:
            out["size"][f"{name}|W={w}"] = run_cell(gen, w, args.reps, args.B, args.seed + w)
            print(f"size  {name:15s} W={w:3d} {out['size'][f'{name}|W={w}']['any']}  ({time.time() - t0:.0f}s)", flush=True)
    for name, gen in [dgps[0], dgps[2], dgps[5]]:
        for w in args.weeks:
            for d in args.deltas:
                out["power"][f"{name}|W={w}|d={d}"] = run_cell(gen, w, args.reps, args.B, args.seed + w + 7, delta=d)
                print(f"power {name:15s} W={w:3d} d={d} {out['power'][f'{name}|W={w}|d={d}']['cfg1']}", flush=True)
    Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    Path(args.out).write_text(render(out), encoding="utf-8")
    print("wrote", args.out, f"({time.time() - t0:.0f}s)")


def render(o: dict) -> str:
    a = o["args"]
    lines = [
        "# Max-T (Westfall-Young step-down, studentized circular block bootstrap) — size and power validation",
        "",
        f"Generated by `scripts/validate_max_t.py` (seed {a['seed']}, {a['reps']} Monte-Carlo reps per cell, "
        f"B={a['B']} bootstrap draws per rep; production uses B=10,000). K=6 configs, common-factor correlation ~0.5. "
        "Nominal FWER = 0.05. Monte-Carlo standard error of a size estimate near 5% is about "
        f"{np.sqrt(0.05 * 0.95 / a['reps']) * 100:.1f} percentage points (larger near 15%).",
        "",
        "## Size (probability that at least one true-null config is declared significant)",
        "",
        "| DGP | weeks | block 2 | block 4 | block 8 | DUAL (4 and 8) |",
        "|---|---|---|---|---|---|",
    ]
    for key, v in o["size"].items():
        name, w = key.split("|W=")
        s = v["any"]
        lines.append(f"| {name} | {w} | {s['2']:.3f} | {s['4']:.3f} | {s['8']:.3f} | {s['dual']:.3f} |")
    lines += ["", "## Power (config 1 has a true mean advantage of d weekly standard deviations)", "",
              "| DGP | weeks | d | block 4 | block 8 | DUAL (4 and 8) |", "|---|---|---|---|---|---|"]
    for key, v in o["power"].items():
        name, rest = key.split("|W=")
        w, d = rest.split("|d=")
        c = v["cfg1"]
        lines.append(f"| {name} | {w} | {d} | {c['4']:.3f} | {c['8']:.3f} | {c['dual']:.3f} |")
    lines += ["", "See the analysis section appended by the team for interpretation and the recommended decision.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()

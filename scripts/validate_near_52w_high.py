"""T1, T2, T3 and the descriptive sub-period reports for the near_52w_high validation. Reads the run directory and the B1 baseline directory only: it opens NO database and reads no price.

  py scripts/validate_near_52w_high.py --run-dir DIR --baseline-dir DIR --out-json FILE [--boot 10000] [--placebo-reps 1000] [--placebo-boot 1000] [--seed 20261111] [--min-filled 10]

Registered tests (docs/strategies/near_52w_high/PREREGISTRATION.md):
  T1  paired monthly series D(m) = sum over the trades ENTERED in month m of (actual net R - mean net R of the trade's retained random draws), one value for every month of the window (130 months,
      2016-01 to 2026-10; empty months are 0). One-sided test of mean D > 0 with the Westfall-Young step-down Max-T studentized circular block bootstrap (K = 1, alpha 0.05, B = 10,000, seed 20261111)
      at block lengths 2 and 3 months: significant at BOTH (the dual rule).
  T2  paired_statistics (forward-return horizons, clustered bootstrap, permutation, expectancy comparison): reported only, never a decision input.
  T3  placebo size check: the same T1 pipeline on the B1 draws alone (one random draw stands in for the actual trade, the mean of the others is its comparator), 1,000 replications; the rejection
      rate is the empirical size. Above 0.075 or below 0.025 the result is labelled "size unreliable" and the owner and reviewer decide; nothing is recalibrated here.
  Sub-periods 2016-2019 and 2020-2026 are DESCRIPTIVE: the same statistics, no pass or fail, never used to select, change or stop anything.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.validation.max_t_bootstrap import WestfallYoungMaxTBootstrap, _block_resample  # noqa: E402
from stockbot.validation.paired_stats import paired_statistics  # noqa: E402

SEED = 20261111
BLOCKS = (2, 3)
ALPHA = 0.05
B_MAIN, PLACEBO_REPS, PLACEBO_B = 10000, 1000, 1000
MIN_FILLED = 10
SIZE_LOW, SIZE_HIGH = 0.025, 0.075
CI_BLOCK = 3
SUBPERIODS = {"2016-2019": (date(2016, 1, 1), date(2019, 12, 31)), "2020-2026": (date(2020, 1, 1), date(2026, 12, 31))}
RET_COLS = [f"ret_{h}" for h in (1, 5, 10, 20)]


def pair_table(actual: pd.DataFrame, draws: pd.DataFrame, min_filled: int = MIN_FILLED) -> pd.DataFrame:
    """One row per actual trade that has at least ``min_filled`` filled draws: the draws' mean net R and the paired difference."""
    g = draws.groupby("matched_trade_id").agg(rand_net_r=("net_r", "mean"), rand_gross_r=("gross_r", "mean"), n_draws=("net_r", "size"))
    m = actual.merge(g, left_on="unique_trade_id", right_index=True, how="inner")
    m = m[m["n_draws"] >= min_filled].copy()
    m["diff"] = m["net_r"] - m["rand_net_r"]
    return m.reset_index(drop=True)


def _months(start: date, end: date) -> list:
    return [str(p) for p in pd.period_range(start=pd.Period(start, "M"), end=pd.Period(end, "M"), freq="M")]


def monthly_series(pairs: pd.DataFrame, start: date, end: date, column: str = "diff") -> pd.Series:
    """Sum of ``column`` by entry month over every month from start to end (empty months are 0.0)."""
    months = _months(start, end)
    key = pd.to_datetime(pairs["entry_date"]).dt.strftime("%Y-%m")
    s = pairs[column].groupby(key).sum().reindex(months, fill_value=0.0)
    s.name = column
    return s.astype(float)


def dual_significant(res: dict) -> bool:
    return bool(all(r["fwer_significant"] for r in res["blocks"].values()))


def t1(series: pd.Series, *, blocks=BLOCKS, B: int = B_MAIN, seed: int = SEED, alpha: float = ALPHA) -> dict:
    df = series.to_frame("near_52w_high")
    out = {"blocks": {}, "months": int(len(series)), "alpha": alpha, "K": 1, "B": B, "seed": seed, "one_sided": "mean paired difference > 0"}
    for b in blocks:
        r = WestfallYoungMaxTBootstrap(df, num_replications=B, fwer_alpha=alpha, seed=seed, block_size=b).run()[0]
        out["blocks"][b] = {"observed_mean": float(r.observed_mean), "standard_error": float(r.standard_error), "observed_t": float(r.observed_t),
                            "unadjusted_p_value": float(r.unadjusted_p_value), "adjusted_p_value": float(r.adjusted_p_value), "fwer_significant": bool(r.fwer_significant),
                            "ci99_lower": float(r.confidence_interval_99_lower), "ci99_upper": float(r.confidence_interval_99_upper)}
    out["dual_significant"] = dual_significant(out)
    return out


def size_verdict(size: float) -> str:
    return "size unreliable" if (size > SIZE_HIGH or size < SIZE_LOW) else "size ok"


def placebo_size(draws: pd.DataFrame, pairs: pd.DataFrame, start: date, end: date, *, reps: int = PLACEBO_REPS, B: int = PLACEBO_B, seed: int = SEED) -> dict:
    """The T1 pipeline on the draws alone. Each replication: for every paired trade one random draw plays the actual trade and the mean of its other draws is the comparator."""
    rng = np.random.default_rng(seed)
    months = _months(start, end)
    mi = {m: i for i, m in enumerate(months)}
    ids = list(pairs["unique_trade_id"])
    mon = np.array([mi[m] for m in pd.to_datetime(pairs["entry_date"]).dt.strftime("%Y-%m")])
    wanted = set(ids)
    groups = {k: v["net_r"].to_numpy(dtype=float) for k, v in draws.groupby("matched_trade_id") if k in wanted}
    arrs = [groups[i] for i in ids]
    cnt = np.array([len(a) for a in arrs])
    mat = np.full((len(arrs), int(cnt.max())), np.nan)
    for i, a in enumerate(arrs):
        mat[i, :len(a)] = a
    rowsum = np.nansum(mat, axis=1)
    rej = 0
    for _ in range(reps):
        j = rng.integers(0, cnt)
        pseudo = mat[np.arange(len(arrs)), j]
        diff = pseudo - (rowsum - pseudo) / (cnt - 1)
        s = pd.Series(np.bincount(mon, weights=diff, minlength=len(months)), index=months)
        rej += int(t1(s, B=B, seed=int(rng.integers(0, 2 ** 31 - 1)))["dual_significant"])
    size = rej / reps
    return {"size": size, "se": float(np.sqrt(size * (1 - size) / reps)), "rejections": rej, "reps": reps, "B": B, "seed": seed, "low": SIZE_LOW, "high": SIZE_HIGH, "verdict": size_verdict(size)}


def registered_conclusion(t1_dual: bool, gates_met: bool) -> str:
    if t1_dual and gates_met:
        return "DEMONSTRATED (registered rule met)"
    return "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)"


def block_interval(sums: np.ndarray, counts: np.ndarray, *, B: int, seed: int, block: int = CI_BLOCK) -> list:
    """95% circular block bootstrap interval of sum(sums) / sum(counts) over months."""
    rng = np.random.default_rng(seed)
    idx = _block_resample(rng, len(sums), block, B)
    v = sums[idx].sum(axis=1) / np.maximum(counts[idx].sum(axis=1), 1.0)
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]


def _intervals(actual_pairs: pd.DataFrame, start: date, end: date, B: int, seed: int) -> dict:
    out = {}
    one = actual_pairs.assign(one=1.0)
    for name, col in (("mean_net_r_per_trade", "net_r"), ("mean_paired_diff_per_trade", "diff")):
        s = monthly_series(one, start, end, col).to_numpy()
        c = monthly_series(one, start, end, "one").to_numpy()
        out[name] = {"point": float(s.sum() / max(c.sum(), 1.0)), "ci95": block_interval(s, c, B=B, seed=seed), "block_months": CI_BLOCK}
    return out


def _plain(o):
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (date, pd.Timestamp)):
        return str(o)
    raise TypeError(type(o))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="T1, T2, T3 and descriptive sub-periods for near_52w_high (reads CSV and JSON only).")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--baseline-dir", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--boot", type=int, default=B_MAIN)
    ap.add_argument("--placebo-reps", type=int, default=PLACEBO_REPS)
    ap.add_argument("--placebo-boot", type=int, default=PLACEBO_B)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--min-filled", type=int, default=MIN_FILLED)
    args = ap.parse_args(argv)
    manifest = json.loads((Path(args.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    start, end = (date.fromisoformat(x) for x in manifest["window"])
    base = Path(args.baseline_dir)
    actual = pd.read_csv(base / "actual_trades.csv")
    draws = pd.read_csv(base / "baseline_draws.csv")
    pairs = pair_table(actual, draws, args.min_filled)
    series = monthly_series(pairs, start, end)
    res = {"window": [start.isoformat(), end.isoformat()], "counts": {"usable_trades": int(len(actual)), "pairs": int(len(pairs)), "dropped_pairs": int(len(actual) - len(pairs)),
                                                                     "draws": int(len(draws)), "months": int(len(series)), "min_filled": args.min_filled}}
    res["T1"] = t1(series, B=args.boot, seed=args.seed)
    keep = set(pairs["unique_trade_id"])
    a2 = actual[actual["unique_trade_id"].isin(keep)].dropna(subset=RET_COLS)
    d2 = draws[draws["matched_trade_id"].isin(set(a2["unique_trade_id"]))]
    res["T2"] = paired_statistics(a2, d2, seed=args.seed)
    res["T2"]["note"] = "secondary, reported only; trades with a blanked forward return (a split inside the 20-session horizon) are left out of T2"
    res["T3"] = placebo_size(draws, pairs, start, end, reps=args.placebo_reps, B=args.placebo_boot, seed=args.seed)
    res["intervals"] = _intervals(pairs, start, end, args.boot, args.seed)
    res["descriptive"] = {}
    for tag, (lo, hi) in SUBPERIODS.items():
        sp = pairs[(pd.to_datetime(pairs["entry_date"]).dt.date >= lo) & (pd.to_datetime(pairs["entry_date"]).dt.date <= hi)]
        s_lo, s_hi = max(lo, start), min(hi, end)
        if len(sp) == 0 or s_lo > s_hi:
            continue
        ser = monthly_series(sp, s_lo, s_hi)
        res["descriptive"][tag] = {"descriptive": True, "months": int(len(ser)), "pairs": int(len(sp)), "mean_net_r_per_trade": float(sp["net_r"].mean()),
                                   "mean_paired_diff_per_trade": float(sp["diff"].mean()), "T1": t1(ser, B=args.boot, seed=args.seed) if len(ser) >= 10 else None}
    res["conclusion_t1_only"] = "T1 significant at both block lengths" if res["T1"]["dual_significant"] else "T1 not significant at both block lengths"
    Path(args.out_json).write_text(json.dumps(res, indent=1, default=_plain), encoding="utf-8")
    print(json.dumps({"counts": res["counts"], "T1": {b: {k: r[k] for k in ("observed_mean", "observed_t", "adjusted_p_value", "fwer_significant")} for b, r in res["T1"]["blocks"].items()},
                      "dual_significant": res["T1"]["dual_significant"], "T3": {k: res["T3"][k] for k in ("size", "se", "verdict")}}, indent=1, default=_plain))
    return 0


if __name__ == "__main__":
    sys.exit(main())

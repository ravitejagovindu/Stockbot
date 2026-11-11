"""Joint validation of ONE family of K strategies: T1 with the Westfall-Young Max-T taken JOINTLY across the K monthly-sum series, T2, the T3 placebo size check, and the shared gates per member.

  py scripts/validate_family.py --member ID=DIR [--member ID=DIR ...] --out-json FILE [--lake PATH] [--boot 10000] [--placebo-reps 1000] [--placebo-boot 1000] [--seed 20261111]
                                [--min-filled 10] [--expect-k 4]

Each member DIR holds ``run/`` (what the strategy's research script wrote: manifest.json, trades.json, equity_curve.json, daily.json) and ``baseline/`` (what its B1 script wrote: actual_trades.csv,
baseline_draws.csv). Reads CSV and JSON only; it opens the lake (read-only, through open_lake, the index closes inside the window only) ONLY when --lake is given, for the alpha gate. Without --lake the
gates are not evaluated and no conclusion is drawn for any member.

The statistics are exactly those of scripts/validate_near_52w_high.py (its functions are imported, not copied), with K = the number of members:
  T1  per member, the paired monthly series D(m) = sum over the trades ENTERED in month m of (actual net R - mean net R of the trade's retained random draws), one value per month of the window. The K series
      are stacked and tested with ONE Westfall-Young step-down Max-T studentized circular block bootstrap (one-sided, mean D > 0, alpha 0.05 family-wise, B = 10,000, one seed, blocks of 2 and 3 months; the same
      block draw is applied to all K series). A member is "found" only if its adjusted p-value is <= alpha at BOTH block lengths (the dual rule).
  T2  paired_statistics per member; reported only, never a decision input.
  T3  placebo size check of the joint procedure: for every replication each member's actual trades are replaced by one random draw each (the mean of the others is its comparator), the K pseudo series go
      through the same joint T1, and the family-wise rejection rate (any member found) is the empirical size. Outside 0.025 to 0.075 it is labelled "size unreliable" and the owner decides; nothing is
      recalibrated here. The members' random draws are independent in this check, so it does not test the cross-member correlation of the real series (T1 resamples the real series jointly, which keeps it).
  Gates  the shared validation_gates per member, each beside its registered value (evaluate_validation_gates_near_52w_high.evaluate; the code takes no strategy input beyond the run directory).
  A member is DEMONSTRATED only if it is found by T1 AND meets every gate; otherwise "NOT DEMONSTRATED (registered rule not met; this is not evidence of no edge)".
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_near_52w_high as V  # noqa: E402  (T1 building blocks shared with the single-strategy script)
from stockbot.validation.max_t_bootstrap import WestfallYoungMaxTBootstrap  # noqa: E402
from stockbot.validation.paired_stats import paired_statistics  # noqa: E402

SEED = V.SEED
BLOCKS = V.BLOCKS
ALPHA = V.ALPHA
B_MAIN, PLACEBO_REPS, PLACEBO_B = V.B_MAIN, V.PLACEBO_REPS, V.PLACEBO_B
MIN_FILLED = V.MIN_FILLED
RET_COLS = V.RET_COLS


# ------------------------------------------------------------------------------------------------------------------------------ T1, joint
def family_t1(series: pd.DataFrame, *, blocks=BLOCKS, B: int = B_MAIN, seed: int = SEED, alpha: float = ALPHA) -> dict:
    """Joint Max-T over the columns of ``series`` (one column per member, one row per month). Every block length uses the same seed."""
    out = {"K": int(series.shape[1]), "members_order": list(series.columns), "months": int(len(series)), "alpha": alpha, "B": B, "seed": seed, "blocks": {},
           "one_sided": "mean paired difference > 0", "correction": "Westfall-Young step-down Max-T, joint across members"}
    for b in blocks:
        res = WestfallYoungMaxTBootstrap(series, num_replications=B, fwer_alpha=alpha, seed=seed, block_size=b).run()
        out["blocks"][b] = {r.config_id: {"observed_mean": float(r.observed_mean), "standard_error": float(r.standard_error), "observed_t": float(r.observed_t),
                                          "unadjusted_p_value": float(r.unadjusted_p_value), "adjusted_p_value": float(r.adjusted_p_value), "fwer_significant": bool(r.fwer_significant),
                                          "ci99_lower": float(r.confidence_interval_99_lower), "ci99_upper": float(r.confidence_interval_99_upper)} for r in res}
    out["members"] = {m: {"dual_significant": bool(all(out["blocks"][b][m]["fwer_significant"] for b in blocks))} for m in series.columns}
    out["found"] = [m for m in series.columns if out["members"][m]["dual_significant"]]
    out["family_rejects"] = bool(out["found"])
    return out


# ------------------------------------------------------------------------------------------------------------------------------ T3, joint
def _prep_placebo(draws: pd.DataFrame, pairs: pd.DataFrame, months: list) -> dict:
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
    return {"mon": mon, "cnt": cnt, "mat": mat, "rowsum": np.nansum(mat, axis=1), "n": len(arrs)}


def placebo_size_family(prepped: dict, months: list, *, reps: int = PLACEBO_REPS, B: int = PLACEBO_B, seed: int = SEED, blocks=BLOCKS) -> dict:
    """The joint T1 pipeline on the draws alone. Each replication draws one random draw per paired trade of every member as its pseudo actual trade."""
    rng = np.random.default_rng(seed)
    names = list(prepped)
    rej_any, rej_member = 0, {m: 0 for m in names}
    for _ in range(reps):
        cols = {}
        for m in names:
            p = prepped[m]
            j = rng.integers(0, p["cnt"])
            pseudo = p["mat"][np.arange(p["n"]), j]
            diff = pseudo - (p["rowsum"] - pseudo) / (p["cnt"] - 1)
            cols[m] = np.bincount(p["mon"], weights=diff, minlength=len(months))
        res = family_t1(pd.DataFrame(cols, index=months), blocks=blocks, B=B, seed=int(rng.integers(0, 2 ** 31 - 1)))
        rej_any += int(res["family_rejects"])
        for m in res["found"]:
            rej_member[m] += 1
    size = rej_any / reps
    return {"size": size, "se": float(np.sqrt(size * (1 - size) / reps)), "rejections": rej_any, "reps": reps, "B": B, "seed": seed, "low": V.SIZE_LOW, "high": V.SIZE_HIGH,
            "verdict": V.size_verdict(size), "per_member_rejection_rate": {m: rej_member[m] / reps for m in names}, "definition": "family-wise: at least one member found at both block lengths"}


# ------------------------------------------------------------------------------------------------------------------------------ loading
def load_member(label: str, member_dir, *, min_filled: int = MIN_FILLED) -> dict:
    d = Path(member_dir)
    manifest = json.loads((d / "run" / "manifest.json").read_text(encoding="utf-8"))
    ids = list(manifest.get("strategies", {}))
    if ids and label not in ids:
        raise ValueError(f"member label {label!r} is not the strategy in {d / 'run' / 'manifest.json'} ({ids})")
    start, end = (date.fromisoformat(x) for x in manifest["window"])
    actual = pd.read_csv(d / "baseline" / "actual_trades.csv")
    draws = pd.read_csv(d / "baseline" / "baseline_draws.csv")
    return {"label": label, "dir": d, "run_dir": d / "run", "start": start, "end": end, "actual": actual, "draws": draws, "pairs": V.pair_table(actual, draws, min_filled)}


def read_nifty(lake, run_dir: Path) -> pd.Series:
    """The NIFTY50_INDEX closes inside the run's window, read-only through open_lake (the one price this script ever reads, and only with --lake)."""
    import evaluate_validation_gates_near_52w_high as G
    from stockbot.data.asof import AsOfView
    from stockbot.data.lake import open_lake
    manifest = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    last = date.fromisoformat(manifest["window"][1])
    conn = open_lake(lake)
    try:
        daily_eq, _ = G.B2.load_daily(Path(run_dir))
        return AsOfView(conn, last).raw_bars(G.B2.NIFTY, lookback=None, start=daily_eq.index[0], end=min(last, daily_eq.index[-1]))["close_raw"]
    finally:
        conn.close()


def evaluate_gates(members: dict, nifty: pd.Series, gates: dict, *, boot: int, seed: int) -> dict:
    import evaluate_validation_gates_near_52w_high as G
    return {m: G.evaluate(v["run_dir"], nifty, gates, boot=boot, seed=seed) for m, v in members.items()}


def member_conclusion(found: bool, gate_res) -> str:
    if gate_res is None:
        return "NOT EVALUATED (gates were not run)"
    return V.registered_conclusion(found, bool(gate_res["all_met"]))


def validate_family(members: dict, *, boot: int = B_MAIN, placebo_reps: int = PLACEBO_REPS, placebo_boot: int = PLACEBO_B, seed: int = SEED, nifty: pd.Series | None = None,
                    gates: dict | None = None, blocks=BLOCKS, alpha: float = ALPHA) -> dict:
    """Everything the module computes, from already loaded members ({label: load_member(...)}). ``nifty`` and ``gates`` switch the gate evaluation on."""
    windows = {(v["start"], v["end"]) for v in members.values()}
    if len(windows) != 1:
        raise ValueError(f"all members must share one window, got {sorted(map(str, windows))}")
    start, end = next(iter(windows))
    months = V._months(start, end)
    labels = sorted(members)
    series = pd.DataFrame({m: V.monthly_series(members[m]["pairs"], start, end) for m in labels})
    res = {"K": len(labels), "members": labels, "window": [start.isoformat(), end.isoformat()],
           "counts": {m: {"usable_trades": int(len(members[m]["actual"])), "pairs": int(len(members[m]["pairs"])), "dropped_pairs": int(len(members[m]["actual"]) - len(members[m]["pairs"])),
                          "draws": int(len(members[m]["draws"]))} for m in labels}}
    res["T1"] = family_t1(series, blocks=blocks, B=boot, seed=seed, alpha=alpha)
    res["T2"] = {}
    for m in labels:
        a, d, p = members[m]["actual"], members[m]["draws"], members[m]["pairs"]
        a2 = a[a["unique_trade_id"].isin(set(p["unique_trade_id"]))].dropna(subset=RET_COLS)
        d2 = d[d["matched_trade_id"].isin(set(a2["unique_trade_id"]))]
        res["T2"][m] = paired_statistics(a2, d2, seed=seed)
    res["T2_note"] = "secondary, reported only; trades with a blanked forward return are left out of T2"
    prepped = {m: _prep_placebo(members[m]["draws"], members[m]["pairs"], months) for m in labels}
    res["T3"] = placebo_size_family(prepped, months, reps=placebo_reps, B=placebo_boot, seed=seed, blocks=blocks)
    gate_res = evaluate_gates(members, nifty, gates, boot=boot, seed=seed) if nifty is not None and gates is not None else None
    res["gates"] = gate_res if gate_res is not None else "not evaluated (no --lake)"
    res["conclusion"] = {m: member_conclusion(res["T1"]["members"][m]["dual_significant"], None if gate_res is None else gate_res[m]) for m in labels}
    res["found_by_t1"] = res["T1"]["found"]
    return res


def _plain(o):
    return V._plain(o)


def _summary(res: dict) -> dict:
    return {"K": res["K"], "members": res["members"], "found_by_t1": res["found_by_t1"],
            "T1": {b: {m: {k: r[k] for k in ("observed_mean", "observed_t", "adjusted_p_value", "fwer_significant")} for m, r in ms.items()} for b, ms in res["T1"]["blocks"].items()},
            "T3": {k: res["T3"][k] for k in ("size", "se", "verdict")}, "conclusion": res["conclusion"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Joint validation of a family of K strategies (T1 Max-T across the K series, T2, T3, gates per member). Reads CSV and JSON only.")
    ap.add_argument("--member", action="append", required=True, metavar="ID=DIR", help="strategy id and its result directory (run/ and baseline/ inside); repeat K times")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--lake", help="finsight.db path: only for the NIFTY50_INDEX closes of the alpha gate (read-only); without it the gates are not evaluated")
    ap.add_argument("--boot", type=int, default=B_MAIN)
    ap.add_argument("--placebo-reps", type=int, default=PLACEBO_REPS)
    ap.add_argument("--placebo-boot", type=int, default=PLACEBO_B)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--min-filled", type=int, default=MIN_FILLED)
    ap.add_argument("--expect-k", type=int, help="refuse to run unless exactly this many members are given (the registered family size)")
    args = ap.parse_args(argv)
    pairs = [m.split("=", 1) for m in args.member]
    if any(len(p) != 2 or not p[0] or not p[1] for p in pairs):
        ap.error("--member must be ID=DIR")
    labels = [p[0] for p in pairs]
    if len(set(labels)) != len(labels):
        ap.error(f"duplicate member ids: {labels}")
    if args.expect_k is not None and len(labels) != args.expect_k:
        ap.error(f"expected {args.expect_k} members, got {len(labels)}")
    members = {label: load_member(label, d, min_filled=args.min_filled) for label, d in pairs}
    nifty = gates = None
    if args.lake:
        import evaluate_validation_gates_near_52w_high as G
        nifty, gates = read_nifty(args.lake, next(iter(members.values()))["run_dir"]), G.load_gates()
    res = validate_family(members, boot=args.boot, placebo_reps=args.placebo_reps, placebo_boot=args.placebo_boot, seed=args.seed, nifty=nifty, gates=gates)
    Path(args.out_json).write_text(json.dumps(res, indent=1, default=_plain), encoding="utf-8")
    print(json.dumps(_summary(res), indent=1, default=_plain))
    return 0


if __name__ == "__main__":
    sys.exit(main())

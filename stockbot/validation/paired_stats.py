"""Paired statistics of actual trades against their matched random draws (restructure Phase 7; the computations come from ``scripts/provenance/redesigned_random_baseline.py``).

Same statistics as the legacy script - forward-return horizons with trade-level t, date-clustered bootstrap SE and sign-flip permutation p-values (Bonferroni
alpha 0.05/4), then the expectancy comparison in R (mean, median, 5% trimmed mean, trade t, clustered t, one-sided skill p, raw draw-level means, holding
durations) - with two changes: they RETURN a plain dict instead of printing, and every random step uses one explicit, seeded ``numpy`` generator (the legacy
code drew from the unseeded global ``np.random``, so its p-values changed from run to run).
Inputs: ``actual_df`` (one row per actual trade: unique_trade_id, window, entry_date, gross_r, net_r, days_held, ret_1/5/10/20) and ``rand_df`` (one row per draw:
matched_trade_id, window, gross_r, net_r, days_held, ret_1/5/10/20).
"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

HORIZONS = (1, 5, 10, 20)
BONFERRONI_ALPHA = 0.05 / len(HORIZONS)
BOOT, PERM = 2000, 5000


def trimmed_mean(arr, proportion_to_cut: float = 0.05) -> float:
    """Mean after cutting ``proportion_to_cut`` of the sorted values from each tail (NaNs dropped)."""
    a = np.asarray(arr, dtype=float)
    clean = a[~np.isnan(a)]
    if len(clean) == 0:
        return float("nan")
    vals = np.sort(clean)
    k = int(len(vals) * proportion_to_cut)
    if k > 0 and 2 * k < len(vals):
        return float(np.mean(vals[k:-k]))
    return float(np.mean(vals))


def _clustered_boot(diff: pd.Series, dates: pd.Series, rng: np.random.Generator, n: int = BOOT) -> np.ndarray:
    uniq = dates.unique()
    by_date = {d: diff[dates == d].values for d in uniq}
    out = np.zeros(n)
    for i in range(n):
        picked = rng.choice(len(uniq), size=len(uniq), replace=True)
        out[i] = np.mean(np.concatenate([by_date[uniq[j]] for j in picked]))
    return out


def paired_statistics(actual_df: pd.DataFrame, rand_df: pd.DataFrame, *, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    agg = {c: "mean" for c in ("gross_r", "net_r", "days_held", *[f"ret_{h}" for h in HORIZONS])}
    rand_means = rand_df.groupby("matched_trade_id").agg(agg).rename(columns=lambda c: f"rand_{c}")
    merged = actual_df.merge(rand_means, left_on="unique_trade_id", right_index=True, how="inner")
    out: dict = {"seed": seed, "paired_trades": int(len(merged)), "windows": {}}
    for tag in [*sorted(merged["window"].unique()), "Pooled"]:
        sub = merged if tag == "Pooled" else merged[merged["window"] == tag]
        sub_raw = rand_df if tag == "Pooled" else rand_df[rand_df["window"] == tag]
        n = len(sub)
        if n < 2:
            continue
        w: dict = {"n_trades": n, "n_entry_dates": int(sub["entry_date"].nunique()), "horizons": []}
        for h in HORIZONS:
            act, rnd = sub[f"ret_{h}"], sub[f"rand_ret_{h}"]
            diff = act - rnd
            d = float(diff.mean())
            se = float(diff.std(ddof=1) / np.sqrt(len(diff.dropna())))
            boot = _clustered_boot(diff, sub["entry_date"], rng)
            se_c = float(np.std(boot))
            arr = diff.dropna().values
            perm = np.array([np.mean(arr * rng.choice([-1.0, 1.0], size=len(arr))) for _ in range(PERM)])
            p = float(np.mean(np.abs(perm) >= abs(d)))
            w["horizons"].append({"horizon": h, "actual_mean": float(act.mean()), "random_mean": float(rnd.mean()), "paired_diff": d, "trade_t": d / se if se > 0 else 0.0,
                                  "clustered_t": d / se_c if se_c > 0 else 0.0, "perm_p": p,
                                  "status": "Significant" if p < BONFERRONI_ALPHA else ("Suggestive" if p < 0.05 else "Not Sig")})
        dn = sub["net_r"] - sub["rand_net_r"]
        m = float(dn.mean())
        se_n = float(dn.std() / np.sqrt(n))
        boot_n = _clustered_boot(dn, sub["entry_date"], rng)
        se_cn = float(np.std(boot_n))
        w["expectancy"] = {
            "actual": {"gross": float(sub["gross_r"].mean()), "net": float(sub["net_r"].mean()), "net_median": float(sub["net_r"].median()), "net_trimmed": trimmed_mean(sub["net_r"].values)},
            "random_trade_averaged": {"gross": float(sub["rand_gross_r"].mean()), "net": float(sub["rand_net_r"].mean()), "net_median": float(sub["rand_net_r"].median()),
                                      "net_trimmed": trimmed_mean(sub["rand_net_r"].values)},
            "paired_diff_net": {"mean": m, "median": float(dn.median()), "trimmed": trimmed_mean(dn.values), "trade_t": m / se_n if se_n > 0 else 0.0,
                                "clustered_t": m / se_cn if se_cn > 0 else 0.0, "skill_p_one_sided": float(np.mean(boot_n <= 0.0))},
            "random_raw_draws": {"n": int(len(sub_raw)), "gross": float(sub_raw["gross_r"].mean()), "net": float(sub_raw["net_r"].mean()), "net_median": float(sub_raw["net_r"].median()),
                                 "net_trimmed": trimmed_mean(sub_raw["net_r"].values)},
        }
        w["holding_days"] = {"actual_mean": float(sub["days_held"].mean()), "actual_median": float(sub["days_held"].median()), "actual_max": float(sub["days_held"].max()),
                             "random_averaged_mean": float(sub["rand_days_held"].mean()), "random_raw_mean": float(sub_raw["days_held"].mean())}
        out["windows"][tag] = w
    return out


def format_report(res: Mapping) -> str:
    lines = [f"Paired {res['paired_trades']} actual trades with matched random draws (seed {res['seed']})"]
    for tag, w in res["windows"].items():
        lines += ["", f"{tag}: N = {w['n_trades']} trades on {w['n_entry_dates']} entry dates"]
        for r in w["horizons"]:
            lines.append(f"  T+{r['horizon']:<2} actual {r['actual_mean']:+.2f}%  random {r['random_mean']:+.2f}%  diff {r['paired_diff']:+.2f}%  t {r['trade_t']:+.2f}  "
                         f"clustered t {r['clustered_t']:+.2f}  perm p {r['perm_p']:.4f}  {r['status']}")
        e = w["expectancy"]
        lines.append(f"  net R: actual {e['actual']['net']:+.3f}  random {e['random_trade_averaged']['net']:+.3f}  paired diff {e['paired_diff_net']['mean']:+.3f}  "
                     f"clustered t {e['paired_diff_net']['clustered_t']:+.2f}  skill p {e['paired_diff_net']['skill_p_one_sided']:.4f}")
    return "\n".join(lines)

"""Post-decision DESCRIPTIVE figures for the STOP 4B report (near_52w_high). NOT part of the registered code and not a decision input: the registered conclusion was produced by
scripts/validate_near_52w_high.py and scripts/evaluate_validation_gates_near_52w_high.py before this file was run. Reads the run directory and the baseline directory only (no database).

  py -I docs/strategies/near_52w_high/observed_4B.py RUN_ROOT [OUT_JSON]

Reports: entries per year and per month, exit reasons, win rate, equity and drawdown dates, occupancy and invested share seen, the shared caps' blocks, sector and symbol concentration, and the
observed dispersion and dependence of the paired per-trade difference set beside the power assumptions of PREREGISTRATION.md section 9 (the power arithmetic is repeated with the observed values).
"""
import json
import sys
from collections import Counter
from datetime import date
from math import sqrt
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from stockbot.data.sector_map import sector_for  # noqa: E402

N = NormalDist()
Z80 = N.inv_cdf(0.80)
C_IDEAL, C_DUAL = N.inv_cdf(0.95), 2.2


def main(root: Path, out: Path | None) -> dict:
    run, base = root / "run", root / "baseline"
    trades = pd.DataFrame(json.loads((run / "trades.json").read_text(encoding="utf-8")))
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    trades["exit_date"] = pd.to_datetime(trades["exit_date"])
    trades["usable"] = (trades["exit_reason"] != "END_OF_WINDOW") & (~trades["excluded_ca"])
    trades["net_r"] = trades["net_pnl"] / trades["risk_inr"]
    use = trades[trades["usable"]].copy()
    res: dict = {}
    res["entries"] = {"closed": int(len(trades)), "usable": int(len(use)), "end_of_window": int((trades["exit_reason"] == "END_OF_WINDOW").sum()),
                      "excluded_ca": int(trades["excluded_ca"].sum()), "per_month_usable": float(len(use) / 130), "per_month_all_closed": float(len(trades) / 130),
                      "per_year_all_closed": {str(k): int(v) for k, v in trades.groupby(trades["entry_date"].dt.year).size().items()},
                      "per_year_usable": {str(k): int(v) for k, v in use.groupby(use["entry_date"].dt.year).size().items()}}
    res["exit_reasons_all_closed"] = {k: int(v) for k, v in trades["exit_reason"].value_counts().items()}
    res["exit_reasons_usable"] = {k: int(v) for k, v in use["exit_reason"].value_counts().items()}
    res["win_rate_usable_pct"] = float(100 * (use["net_pnl"] > 0).mean())
    res["net_r_usable"] = {"mean": float(use["net_r"].mean()), "median": float(use["net_r"].median()), "sd": float(use["net_r"].std(ddof=1)), "min": float(use["net_r"].min()),
                           "max": float(use["net_r"].max()), "p5": float(use["net_r"].quantile(0.05)), "p95": float(use["net_r"].quantile(0.95))}
    res["net_pnl_total_usable_inr"] = float(use["net_pnl"].sum())

    eq = json.loads((run / "equity_curve.json").read_text(encoding="utf-8"))
    eq = pd.Series(list(eq.values()), index=pd.to_datetime(list(eq.keys())))
    peak = eq.cummax()
    dd = (peak - eq) / peak
    trough = dd.idxmax()
    peak_date = eq.loc[:trough].idxmax()
    rec = eq.loc[trough:][eq.loc[trough:] >= eq.loc[peak_date]]
    res["equity"] = {"start": float(eq.iloc[0]), "end_marked": float(eq.iloc[-1]), "total_return_pct": float(100 * (eq.iloc[-1] / 1_000_000.0 - 1)), "sessions": int(len(eq)),
                     "max_drawdown_pct": float(100 * dd.max()), "peak_date": str(peak_date.date()), "trough_date": str(trough.date()),
                     "recovered_to_peak_on": str(rec.index[0].date()) if len(rec) else None, "share_of_sessions_in_drawdown_over_10pct": float((dd > 0.10).mean())}
    daily = json.loads((run / "daily.json").read_text(encoding="utf-8"))
    share = pd.Series({pd.Timestamp(k): 1 - v["cash"] / v["equity"] for k, v in daily.items()})
    open_n = pd.Series({d: int(((trades["entry_date"] <= d) & (trades["exit_date"] > d)).sum()) for d in eq.index})
    res["occupancy"] = {"invested_share_mean": float(share.mean()), "invested_share_median": float(share.median()), "invested_share_p5": float(share.quantile(0.05)),
                        "invested_share_p95": float(share.quantile(0.95)), "open_positions_mean": float(open_n.mean()), "open_positions_median": float(open_n.median()),
                        "share_of_sessions_at_12": float((open_n >= 12).mean()), "open_positions_max": int(open_n.max())}
    blocked = pd.DataFrame(json.loads((run / "blocked.json").read_text(encoding="utf-8")))
    if len(blocked):
        kind = blocked["reason"].str.extract(r"^(BLOCKED_BY_RISK\((?:positions|total_risk|sector))")[0].fillna(blocked["reason"].str.split("(").str[0])
        blocked["kind"] = kind.str.replace("BLOCKED_BY_RISK(", "RISK:", regex=False)
        sec = blocked[blocked["kind"] == "RISK:sector"]
        res["blocked"] = {"total": int(len(blocked)), "by_stage": {k: int(v) for k, v in blocked["stage"].value_counts().items()},
                          "by_kind": {k: int(v) for k, v in blocked["kind"].value_counts().head(12).items()}, "sector_cap_blocks": int(len(sec)),
                          "sessions_with_a_sector_block": int(sec["date"].nunique()),
                          "sector_cap_blocks_in_UNKNOWN": int(sec["reason"].str.contains("sector_UNKNOWN").sum())}
    s = use["symbol"].map(sector_for)
    c = use["symbol"].value_counts()
    res["concentration"] = {"distinct_symbols": int(len(c)), "largest_symbol": [c.index[0], float(c.iloc[0] / len(use))], "top10_share": float(c.head(10).sum() / len(use)),
                            "sector_share_pct": {k: float(100 * v / len(use)) for k, v in s.value_counts().items()},
                            "entries_in_UNKNOWN_pct": float(100 * (s == "UNKNOWN").mean()), "symbols_in_UNKNOWN": int(sum(1 for x in c.index if sector_for(x) == "UNKNOWN"))}

    actual = pd.read_csv(base / "actual_trades.csv")
    draws = pd.read_csv(base / "baseline_draws.csv")
    g = draws.groupby("matched_trade_id").agg(rn=("net_r", "mean"), nd=("net_r", "size"))
    p = actual.merge(g, left_on="unique_trade_id", right_index=True)
    p = p[p["nd"] >= 10].copy()
    p["diff"] = p["net_r"] - p["rn"]
    p["month"] = pd.to_datetime(p["entry_date"]).dt.strftime("%Y-%m")
    months = [str(x) for x in pd.period_range("2016-01", "2026-10", freq="M")]
    S = p["diff"].groupby(p["month"]).sum().reindex(months, fill_value=0.0).to_numpy()
    n_m = p.groupby("month").size().reindex(months, fill_value=0).to_numpy(dtype=float)
    sd_pair, sd_trade = float(p["diff"].std(ddof=1)), float(p["net_r"].std(ddof=1))
    mu = float(p["diff"].mean())
    var_ind = float(n_m.mean() * sd_pair ** 2)
    var_obs = float(np.mean((S - n_m * mu) ** 2))
    deff = var_obs / var_ind
    ac = [float(pd.Series(S).autocorr(k)) for k in (1, 2, 3)]
    n = len(p)
    se_trade = sd_pair / sqrt(n / deff)
    month_se = float(S.std(ddof=1) / sqrt(len(S)))
    mean_n = float(n_m.mean())
    res["dispersion_and_dependence"] = {
        "pairs": int(n), "sd_pair_observed": sd_pair, "sd_pair_assumed": [0.9, 1.2, 1.5], "sd_trade_net_r_paired_trades": sd_trade, "deff_observed": deff, "deff_assumed": [1.0, 1.5, 2.0, 3.0],
        "effective_trades_observed": float(n / deff), "monthly_sum_sd": float(S.std(ddof=1)), "monthly_sum_se": month_se, "mean_trades_per_month_paired": mean_n,
        "monthly_sum_autocorr_lag1_2_3": ac, "se_per_trade_observed": se_trade,
        "mde80_r_per_trade_observed_ideal_c": (C_IDEAL + Z80) * se_trade, "mde80_r_per_trade_observed_dual_c": (C_DUAL + Z80) * se_trade,
        "power_at_0.15_ideal": float(N.cdf(0.15 / se_trade - C_IDEAL)), "power_at_0.15_dual": float(N.cdf(0.15 / se_trade - C_DUAL)),
        "power_at_0.20_ideal": float(N.cdf(0.20 / se_trade - C_IDEAL)), "power_at_0.20_dual": float(N.cdf(0.20 / se_trade - C_DUAL)),
        "monthly_series_check_mde80_r_per_trade_ideal": (C_IDEAL + Z80) * month_se / mean_n, "monthly_series_check_mde80_r_per_trade_dual": (C_DUAL + Z80) * month_se / mean_n,
        "monthly_series_check_power_at_0.15_dual": float(N.cdf(0.15 * mean_n / month_se - C_DUAL)),
        "note": "post-decision and descriptive; the monthly-series check uses the naive SE of the 130 monthly sums, with dependence entering only through the block bootstrap"}
    if out:
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    print(json.dumps(r, indent=1))

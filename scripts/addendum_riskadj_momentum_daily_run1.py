"""Derived facts and DESCRIPTIVE ADDENDUM for the registered riskadj_momentum_daily run 1 (not registered, changes no conclusion).

  py -3 scripts/addendum_riskadj_momentum_daily_run1.py --out docs/strategies/riskadj_momentum_daily/results_run1_addendum.json

Reads only STORED files: docs/strategies/riskadj_momentum_daily/results_run1/ and riskadj_momentum's stored run 1. No engine run, no new draw, no lake access.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_nifty_matched_riskadj_momentum_daily as B2  # noqa: E402
import evaluate_validation_gates_riskadj_momentum_daily as G  # noqa: E402
import validate_near_52w_high as V  # noqa: E402
from stockbot.data import symbol_links as SL  # noqa: E402

RUN = ROOT / "docs/strategies/riskadj_momentum_daily/results_run1"
OLD = ROOT / "docs/strategies/riskadj_momentum/results_run1"
sys.path.insert(0, str(Path(__file__).parent))
import addendum_lowvol_uptrend_run1 as L  # noqa: E402  (drawdown_episodes, monthly_returns, ser: stored-file helpers)


def concentration(trades, pairs):
    tt = G.trade_table(trades)
    use = tt[tt["usable"]]
    out = {"n_usable_trades": int(len(use)), "n_pairs": int(len(pairs))}

    def block(values, label):
        v = values.sort_values(ascending=False).reset_index(drop=True)
        tot = float(v.sum())
        res = {"total": tot, "mean_all": float(v.mean()), "ranked_by": label}
        for k in (5, 10, 20):
            res[f"top{k}_sum"] = float(v.iloc[:k].sum())
            res[f"top{k}_share_of_total"] = float(v.iloc[:k].sum() / tot)
        for k in (5, 10):
            res[f"mean_without_top{k}"] = float(v.iloc[k:].mean())
        return res
    out["net_r"] = block(use["net_r"], "net R, highest first")
    out["net_pnl_inr"] = block(use["net_pnl"], "net P&L INR, highest first")
    out["paired_difference"] = block(pairs["diff"], "paired difference (net R minus mean of its draws), highest first")
    return out


def run_stats(rundir: Path, gates: dict, bench: dict) -> dict:
    """The same descriptive numbers for a stored run (used for both runs in the side by side)."""
    trades = json.loads((rundir / "run/trades.json").read_text(encoding="utf-8"))
    equity, _ = B2.load_daily(rundir / "run")
    sessions = list(equity.index)
    pos = {d: i for i, d in enumerate(sessions)}
    tt = G.trade_table(trades)
    use = tt[tt["usable"]].copy()
    ut = [t for t in trades if not t.get("excluded_ca", False)]
    use["hold"] = [pos[x] - pos[e] for e, x in zip(use["entry_date"], use["exit_date"])]
    r = use["net_r"]
    wins, losses = r[r > 0], r[r <= 0]
    gross = float(sum(t["gross_pnl"] for t in ut))
    costs = float(sum(t["costs"] for t in ut))
    gp = float(sum(t["gross_pnl"] for t in ut if t["gross_pnl"] > 0))
    a = bench["daily_share"]["cash_credited_pre_tax"]
    return {"usable_trades": int(len(use)), "entries_per_month": gates["counts"]["entries_per_month"], "invested_share_mean": gates["counts"]["invested_share_mean"],
            "median_hold_sessions": float(use["hold"].median()), "win_rate": float((r > 0).mean()), "avg_win_r": float(wins.mean()), "avg_loss_r": float(losses.mean()),
            "expectancy_r": float(r.mean()), "profit_factor": G.profit_factor(use["net_pnl"]), "strategy_cagr_raw_pct": bench["daily_share"]["raw"]["strategy_cagr_pct"],
            "strategy_cagr_cash_credited_pct": a["strategy_cagr_pct"], "alpha_cash_credited_pct": a["alpha_pct"], "max_drawdown_pct": G.max_drawdown_pct(equity),
            "total_costs_inr": costs, "total_gross_pnl_inr": gross, "gross_profit_winners_inr": gp, "costs_share_of_total_gross_pnl": costs / gross, "costs_share_of_gross_winners": costs / gp,
            "total_net_pnl_inr": float(sum(t["net_pnl"] for t in ut))}


def facts(trades, equity, blocked, gates):
    sessions = list(equity.index)
    pos = {d: i for i, d in enumerate(sessions)}
    use = [t for t in trades if not t.get("excluded_ca", False)]
    hold = np.array([pos[pd.Timestamp(t["exit_date"]).date()] - pos[pd.Timestamp(t["entry_date"]).date()] for t in use], float)
    cal = np.array([(pd.Timestamp(t["exit_date"]) - pd.Timestamp(t["entry_date"])).days for t in use], float)
    out = {"exit_reasons_all_closed": dict(Counter(t["exit_reason"] for t in trades)), "excluded_ca": sum(1 for t in trades if t.get("excluded_ca"))}
    out["hold_sessions"] = {"median": float(np.median(hold)), "p25": float(np.percentile(hold, 25)), "p75": float(np.percentile(hold, 75)), "max": float(hold.max()), "mean": float(hold.mean())}
    out["hold_calendar_days"] = {"median": float(np.median(cal)), "p25": float(np.percentile(cal, 25)), "p75": float(np.percentile(cal, 75)), "max": float(cal.max())}
    em = Counter(t["entry_date"][:7] for t in trades)
    months = pd.period_range(min(em), max(em), freq="M")
    ev = np.array([em.get(str(m), 0) for m in months], float)
    out["entries_per_month"] = {"mean_over_months_first_to_last_entry": float(ev.mean()), "median": float(np.median(ev)), "min": float(ev.min()), "max": float(ev.max()), "months": int(len(ev))}
    bc = Counter()
    for b in blocked:
        r = b["reason"]
        key = f"{b['stage']}:{r.split('(')[0]}"
        if r.startswith("BLOCKED_BY_RISK("):
            inner = r[len("BLOCKED_BY_RISK("):]
            key += ":" + ("sector_cap" if inner.startswith("sector_") else inner.split(":")[0].split(">")[0].split("=")[0])
        bc[key] += 1
    out["blocked_name_sessions_by_reason"] = dict(bc.most_common())
    out["blocked_total"] = len(blocked)
    # cooldown, derived from the stored trades (the strategy's own skip of a name in cooldown is not logged)
    canon = lambda s: SL.resolve(s)  # noqa: E731
    stops = [t for t in trades if t["exit_reason_engine"] == "STOP_HIT"]
    out["cooldown_derived"] = {"stop_hit_exits_starting_a_cooldown": len(stops)}
    last = len(sessions) - 1
    ns = 0
    for t in stops:
        i = pos[pd.Timestamp(t["exit_date"]).date()]
        ns += min(i + 21, last) - i + 1
    out["cooldown_derived"]["cooldown_name_sessions_day0_to_21_within_window"] = ns
    # of the stop-outs, how many were followed by a re-purchase of the same symbol after the cooldown, and none inside
    by = {}
    for t in trades:
        by.setdefault(canon(t["symbol"]), []).append(t)
    inside = 0
    for t in stops:
        i = pos[pd.Timestamp(t["exit_date"]).date()]
        for u in by[canon(t["symbol"])]:
            j = pos[pd.Timestamp(u["entry_date"]).date()]
            if i < j <= i + 21 + 1 - 1 and u is not t:  # an ENTRY (the session after a signal) inside the blocked span would show up here
                inside += 1
    out["cooldown_derived"]["entries_of_the_same_symbol_in_sessions_1_to_21_after_a_stop_exit"] = inside
    return out


def reentries(trades, equity):
    sessions = list(equity.index)
    pos = {d: i for i, d in enumerate(sessions)}
    tt = G.trade_table(trades)
    rows = []
    for t, (_, r) in zip(trades, tt.iterrows()):
        rows.append({"sym": SL.resolve(t["symbol"]), "e": pos[r["entry_date"]], "x": pos[r["exit_date"]], "net_r": r["net_r"], "usable": bool(r["usable"]), "stop": t["exit_reason_engine"] == "STOP_HIT", "reason": t["exit_reason_engine"]})
    df = pd.DataFrame(rows)
    gap, cat = [], []
    for k, r in df.iterrows():
        prev = df[(df["sym"] == r["sym"]) & (df["x"] <= r["e"]) & (df.index != k)]
        stops = prev[prev["stop"]]
        if len(stops):
            gap.append(int(r["e"] - stops["x"].max()))
            cat.append("rebuy_after_stop")
        elif len(prev):
            gap.append(int(r["e"] - prev["x"].max()))
            cat.append("prior_trade_not_a_stop")
        else:
            gap.append(None)
            cat.append("first_time")
    df["gap"], df["cat"] = gap, cat
    use = df[df["usable"]]
    res = {"definition": "re-buy = the symbol (canonical name) had an earlier closed trade of this run that ended by STOP_HIT; gap = sessions from the latest such stop exit to the new entry fill session; first-time = no earlier trade of the symbol; usable trades only",
           "counts": use["cat"].value_counts().to_dict(), "mean_net_r": use.groupby("cat")["net_r"].mean().to_dict(), "median_net_r": use.groupby("cat")["net_r"].median().to_dict()}
    rb = use[use["cat"] == "rebuy_after_stop"]
    g = rb["gap"].astype(float)
    res["rebuy_gap_sessions"] = {"min": float(g.min()), "p25": float(g.quantile(.25)), "median": float(g.median()), "p75": float(g.quantile(.75)), "max": float(g.max())}
    bins = [(0, 21), (22, 30), (31, 60), (61, 120), (121, 250), (251, 10**6)]
    res["rebuy_gap_buckets"] = [{"gap_sessions": f"{a}-{b}" if b < 10**6 else f">{a-1}", "n": int(((g >= a) & (g <= b)).sum()), "mean_net_r": (float(rb.loc[g[(g >= a) & (g <= b)].index, "net_r"].mean()) if ((g >= a) & (g <= b)).any() else None)} for a, b in bins]
    res["rebuy_net_r_share_positive"] = float((rb["net_r"] > 0).mean())
    ft = use[use["cat"] == "first_time"]
    res["first_time_net_r_share_positive"] = float((ft["net_r"] > 0).mean())
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    trades = json.loads((RUN / "run/trades.json").read_text(encoding="utf-8"))
    blocked = json.loads((RUN / "run/blocked.json").read_text(encoding="utf-8"))
    gates = json.loads((RUN / "gates.json").read_text(encoding="utf-8"))
    bench = json.loads((RUN / "benchmark.json").read_text(encoding="utf-8"))
    actual = pd.read_csv(RUN / "baseline/actual_trades.csv")
    draws = pd.read_csv(RUN / "baseline/baseline_draws.csv")
    equity, _ = B2.load_daily(RUN / "run")
    pairs = V.pair_table(actual, draws, 10)
    res = {"inputs": "stored files only (no engine run, no new draws, no lake access)"}
    res["facts_derived"] = facts(trades, equity, blocked, gates)
    res["a_concentration"] = concentration(trades, pairs)
    mine = L.drawdown_episodes(equity)
    res["b_drawdown_episodes"] = [L.ser(e) for e in mine]
    w = equity[(equity.index >= pd.Timestamp("2020-01-14").date()) & (equity.index <= pd.Timestamp("2020-03-23").date())]
    peak_run = equity.cummax()
    lo = w.idxmin()
    res["b_2020_01_14_to_03_23"] = {"equity_2020_01_14": float(w.iloc[0]), "lowest_equity_in_window": float(w.min()), "date_of_lowest": lo.isoformat(), "fall_from_2020_01_14_to_lowest_pct": float(100 * (w.iloc[0] - w.min()) / w.iloc[0]),
                                    "max_drawdown_inside_window_from_window_peak_pct": G.max_drawdown_pct(w), "drawdown_from_run_peak_on_2020_03_23_pct": float(100 * (peak_run.loc[w.index[-1]] - w.iloc[-1]) / peak_run.loc[w.index[-1]]),
                                    "first_day_in_window": w.index[0].isoformat(), "last_day_in_window": w.index[-1].isoformat()}
    ob = json.loads((OLD / "benchmark.json").read_text(encoding="utf-8"))
    og = json.loads((OLD / "gates.json").read_text(encoding="utf-8"))
    res["c_side_by_side"] = {"riskadj_momentum_daily_run1": run_stats(RUN, gates, bench), "riskadj_momentum_run1": run_stats(OLD, og, ob)}
    a, b = L.monthly_returns(equity), L.monthly_returns(B2.load_daily(OLD / "run")[0])
    common = a.index.intersection(b.index)
    res["c_monthly_return_correlation"] = {"common_months": int(len(common)), "first": common[0], "last": common[-1], "pearson": float(np.corrcoef(a[common], b[common])[0, 1])}
    res["d_reentries"] = reentries(trades, equity)
    Path(args.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

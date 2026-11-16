"""DESCRIPTIVE ADDENDUM for the registered lowvol_uptrend run 1 (not registered, changes no conclusion).

  py -3 scripts/addendum_lowvol_uptrend_run1.py --out docs/strategies/lowvol_uptrend/results_run1_addendum.json

Reads only the STORED result files of docs/strategies/lowvol_uptrend/results_run1/ (trades, equity, daily, actual_trades.csv, baseline_draws.csv) and riskadj_momentum's stored run 1 equity curve.
No engine run, no new random draw. The lake is read READ-ONLY (sqlite mode=ro, immutable) for item (d) only: the trade dates of the held symbols (and of their linked names).
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_nifty_matched_lowvol_uptrend as B2  # noqa: E402
import evaluate_validation_gates_lowvol_uptrend as G  # noqa: E402
import validate_near_52w_high as V  # noqa: E402
from stockbot.data import symbol_links as SL  # noqa: E402

RUN = ROOT / "docs/strategies/lowvol_uptrend/results_run1"
RISK = ROOT / "docs/strategies/riskadj_momentum/results_run1/run"
DB = os.environ.get("STOCKBOT_DB", str(ROOT / "finsight.db"))


def concentration(run_trades: list, pairs: pd.DataFrame) -> dict:
    tt = G.trade_table(run_trades)
    use = tt[tt["usable"]]
    out = {"n_usable_trades": int(len(use)), "n_pairs": int(len(pairs))}

    def block(values: pd.Series, label: str) -> dict:
        v = values.sort_values(ascending=False).reset_index(drop=True)
        tot = float(v.sum())
        res = {"total": tot, "mean_all": float(v.mean()), "ranked_by": label}
        for k in (5, 10, 20):
            res[f"top{k}_sum"] = float(v.iloc[:k].sum())
            res[f"top{k}_share_of_total"] = float(v.iloc[:k].sum() / tot)
        for k in (5, 10):
            res[f"mean_without_top{k}"] = float(v.iloc[k:].mean())
            res[f"n_without_top{k}"] = int(len(v) - k)
        return res
    out["net_r"] = block(use["net_r"], "net R of the trade, highest first")
    out["net_pnl_inr"] = block(use["net_pnl"], "net P&L (INR) of the trade, highest first")
    out["paired_difference"] = block(pairs["diff"], "paired difference (net R minus mean of its draws), highest first")
    return out


def drawdown_episodes(equity: pd.Series, k: int = 5) -> list:
    eps, peak_d, peak_v, in_dd, trough_d, trough_v = [], equity.index[0], equity.iloc[0], False, None, None
    for d, v in equity.items():
        if v >= peak_v:
            if in_dd:
                eps.append({"peak_date": peak_d, "trough_date": trough_d, "recovery_date": d, "depth_pct": 100.0 * (peak_v - trough_v) / peak_v})
                in_dd = False
            peak_d, peak_v = d, v
        else:
            if not in_dd:
                in_dd, trough_d, trough_v = True, d, v
            if v < trough_v:
                trough_d, trough_v = d, v
    if in_dd:
        eps.append({"peak_date": peak_d, "trough_date": trough_d, "recovery_date": None, "depth_pct": 100.0 * (peak_v - trough_v) / peak_v})
    eps.sort(key=lambda e: -e["depth_pct"])
    return eps[:k]


def months_between(a: date, b: date) -> set:
    return {f"{d.year:04d}-{d.month:02d}" for d in pd.period_range(a, b, freq="M").to_timestamp()}


def episode_months(e: dict, last: date, to: str) -> set:
    end = e["trough_date"] if to == "trough" else (e["recovery_date"] or last)
    return months_between(e["peak_date"], end)


def ser(e: dict) -> dict:
    return {**e, "peak_date": e["peak_date"].isoformat(), "trough_date": e["trough_date"].isoformat(), "recovery_date": e["recovery_date"].isoformat() if e["recovery_date"] else None}


def monthly_returns(equity: pd.Series) -> pd.Series:
    m = equity.groupby([f"{d.year:04d}-{d.month:02d}" for d in equity.index]).last()
    return m.pct_change().dropna()


def no_bar_runs(run_trades: list, sessions: list, threshold: int = 5) -> list:
    links = SL.active()
    con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    out = []
    try:
        cache: dict = {}
        for t in run_trades:
            sym = t["symbol"]
            if sym not in cache:
                names = list(links.members(sym)) if links is not None and links.members(sym) else [sym]
                have: set = set()
                for n in names:
                    have |= {r[0] for r in con.execute("select trade_date from market_data_lake where symbol = ?", (n,))}
                cache[sym] = have
            have = cache[sym]
            e, x = t["entry_date"], t["exit_date"]
            run, longest, first_over, over = 0, 0, None, 0
            for s in sessions:
                if s.isoformat() < e or s.isoformat() >= x:
                    continue
                run = 0 if s.isoformat() in have else run + 1
                longest = max(longest, run)
                if run > threshold:
                    over += 1
                    first_over = first_over or s.isoformat()
            if over:
                out.append({"symbol": sym, "position_id": t["position_id"], "entry_date": e, "exit_date": x, "exit_reason": t["exit_reason"], "net_pnl": t["net_pnl"],
                            "longest_run_of_sessions_without_a_bar": longest, "held_sessions_with_run_over_5": over, "first_such_session": first_over})
    finally:
        con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    run_trades = json.loads((RUN / "run/trades.json").read_text(encoding="utf-8"))
    actual = pd.read_csv(RUN / "baseline/actual_trades.csv")
    draws = pd.read_csv(RUN / "baseline/baseline_draws.csv")
    equity, cash = B2.load_daily(RUN / "run")
    pairs = V.pair_table(actual, draws, 10)
    res = {"inputs": "stored files of docs/strategies/lowvol_uptrend/results_run1 and riskadj_momentum results_run1 equity (no engine run, no new draws); lake read-only for (d)"}
    res["a_concentration"] = concentration(run_trades, pairs)
    mine = drawdown_episodes(equity)
    res["b_drawdown_episodes"] = [ser(e) for e in mine]
    req, _ = B2.load_daily(RISK)
    theirs = drawdown_episodes(req)
    res["c_riskadj_run1_drawdown_episodes"] = [ser(e) for e in theirs]
    last = equity.index[-1]
    ov = []
    for i, a in enumerate(mine, 1):
        row = {"lowvol_episode": i, "peak": a["peak_date"].isoformat(), "depth_pct": a["depth_pct"]}
        for to in ("trough", "recovery"):
            ma = episode_months(a, last, to)
            row[f"vs_riskadj_peak_to_{to}_months"] = {j: sorted(ma & episode_months(b, req.index[-1], to)) for j, b in enumerate(theirs, 1)}
        ov.append(row)
    res["c_calendar_month_overlap"] = {"definition": "months from the peak month to the trough month (or the recovery month; to the last month if not recovered) of each episode; lists the shared months per pair of episodes", "rows": ov}
    a, b = monthly_returns(equity), monthly_returns(req)
    common = a.index.intersection(b.index)
    res["c_monthly_return_correlation"] = {"common_months": int(len(common)), "first": common[0], "last": common[-1], "pearson": float(np.corrcoef(a[common], b[common])[0, 1]),
                                           "note": "monthly returns of the daily equity curves (last equity of the month over the previous month's last equity); the first month of each run is dropped"}
    res["d_positions_held_over_5_sessions_without_a_bar"] = no_bar_runs(run_trades, list(equity.index))
    Path(args.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

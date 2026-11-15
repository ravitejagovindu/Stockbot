"""DESCRIPTIVE ADDENDUM for the registered riskadj_momentum run 1 (not registered, changes no conclusion).

  py -3 scripts/addendum_riskadj_momentum_run1.py --out docs/strategies/riskadj_momentum/results_run1_addendum.json

Reads only the STORED result files of docs/strategies/riskadj_momentum/results_run1/ (trades, equity, daily, blocked, actual_trades.csv, baseline_draws.csv). No engine run, no new random draw.
Reads the lake READ-ONLY (sqlite mode=ro, immutable) for: NIFTY closes (alpha, as the gates script does), the closes of the two stale-bar symbols (mark-to-market path used in the
"subtraction" equity of section 2), and section 4 (last bars, corporate_actions_log rows, the stale-bar pattern in stored runs). Shared code is imported, never edited.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_validation_gates_riskadj_momentum as G  # noqa: E402
import validate_family as VF  # noqa: E402
import validate_near_52w_high as V  # noqa: E402
import benchmark_nifty_matched_riskadj_momentum as B2  # noqa: E402

RUN = ROOT / "docs/strategies/riskadj_momentum/results_run1"
DB = "F:/Projects/Ravi/StockBot/finsight.db"
STALE = {"PHILIPCARB": "riskadj_momentum:PHILIPCARB:2018-04-03", "TATASTLBSL": "riskadj_momentum:TATASTLBSL:2021-07-02"}
OTHER_RUNS = {
    "near_52w_high 4B (docs/strategies/near_52w_high/results_4B)": ROOT / "docs/strategies/near_52w_high/results_4B/run/trades.json",
    "family_batch1 run1: pullback_uptrend": ROOT / "docs/strategies/pullback_uptrend/results_run1/run/trades.json",
    "family_batch1 run1: short_term_reversal": ROOT / "docs/strategies/short_term_reversal/results_run1/run/trades.json",
    "riskadj_momentum run1 (this run, all 650 trades)": RUN / "run/trades.json",
}
EXTRA_RUNS = {  # other stored runs found on disk (market_switch study); reported separately
    "market_switch near_52w_high with": Path("F:/Projects/Ravi/StockBot_runs/market_switch/near_52w_high/with/trades.json"),
    "market_switch near_52w_high without": Path("F:/Projects/Ravi/StockBot_runs/market_switch/near_52w_high/without/trades.json"),
    "market_switch pullback_uptrend with": Path("F:/Projects/Ravi/StockBot_runs/market_switch/pullback_uptrend/with/trades.json"),
    "market_switch near_52w_high repro 2016": Path("F:/Projects/Ravi/StockBot_runs/market_switch/repro/near_52w_high_2016/trades.json"),
    "market_switch short_term_reversal with": Path("F:/Projects/Ravi/StockBot_runs/market_switch/short_term_reversal/with/trades.json"),
}


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)


# ---------------------------------------------------------------------------------------------------------------- 1. concentration
def concentration(run_trades: list, actual: pd.DataFrame, pairs: pd.DataFrame) -> dict:
    tt = G.trade_table(run_trades)
    use = tt[tt["usable"]].copy()
    out = {"n_usable_trades": int(len(use)), "n_pairs": int(len(pairs))}

    def block(values: pd.Series, label: str) -> dict:
        v = values.sort_values(ascending=False).reset_index(drop=True)
        tot = float(v.sum())
        res = {"total": tot, "mean_all": float(v.mean())}
        for k in (5, 10, 20):
            res[f"top{k}_sum"] = float(v.iloc[:k].sum())
            res[f"top{k}_share_of_total"] = float(v.iloc[:k].sum() / tot)
        for k in (5, 10):
            res[f"mean_without_top{k}"] = float(v.iloc[k:].mean())
            res[f"n_without_top{k}"] = int(len(v) - k)
        res["ranked_by"] = label
        return res

    out["net_r"] = block(use["net_r"], "net R of the trade, highest first")
    out["net_pnl_inr"] = block(use["net_pnl"], "net P&L (INR) of the trade, highest first")
    out["paired_difference"] = block(pairs["diff"], "paired difference (net R minus mean of its draws), highest first")
    out["note"] = "shares are top-k sum / total over all usable trades (or all pairs); 'mean_without_topk' is the mean of the rest; rank is within the same quantity"
    return out


# ---------------------------------------------------------------------------------------------------------------- 2. stale-bar removal
def stale_info(run_trades: list, sessions: pd.Index, blocked: list) -> dict:
    byid = {t["position_id"]: t for t in run_trades}
    d = {}
    for sym, pid in STALE.items():
        t = byid[pid]
        e, x = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
        held = [s for s in sessions if e <= s < x]       # same convention as the gates' open-position count (entry <= d < exit)
        hs = {s.isoformat() for s in held}
        bl = [b for b in blocked if b["date"] in hs]
        by = {}
        for b in bl:
            key = b["reason"].split("(")[0] if b["reason"].startswith("BLOCKED_BY_RISK") else b["reason"]
            by[key] = by.get(key, 0) + 1
        rules = {}
        for b in bl:
            if b["reason"].startswith("BLOCKED_BY_RISK("):
                r = b["reason"][len("BLOCKED_BY_RISK("):].split(":")[0]
                rules[r] = rules.get(r, 0) + 1
        d[sym] = {"position_id": pid, "entry": t["entry_date"], "exit": t["exit_date"], "slot_sessions": len(held), "net_pnl": t["net_pnl"], "shares_initial": t["shares_initial"],
                  "blocked_proposals_while_held_by_reason": by, "blocked_by_risk_rule_while_held": rules, "blocked_total_while_held": len(bl)}
    return d


SPLIT_FACTOR = {"PHILIPCARB": ("2018-04-19", 2.0 / 10.0)}   # corporate_actions_log SPLIT 2:10 ex 2018-04-19: raw closes before the ex-date x 0.2 = the engine's split-adjusted marks


def adj_close(con, sym: str, sessions: pd.Index, since: str = "1900-01-01") -> pd.Series:
    rows = con.execute("select trade_date, close_raw from market_data_lake where symbol=? and trade_date>=? order by trade_date", (sym, since)).fetchall()
    ser = pd.Series({date.fromisoformat(a): b for a, b in rows})
    if sym in SPLIT_FACTOR:
        ex, f = SPLIT_FACTOR[sym]
        ser = pd.Series({d: (v * f if d < date.fromisoformat(ex) else v) for d, v in ser.items()})
    return ser.reindex(sessions).ffill()


def mark_paths(run_trades: list, sessions: pd.Index) -> dict:
    """Equity effect of each stale-bar position vs not holding it (approximation: marked at the lake close, forward filled; realised net P&L from the exit date on)."""
    con = ro()
    out = {}
    byid = {t["position_id"]: t for t in run_trades}
    for sym, pid in STALE.items():
        t = byid[pid]
        px = adj_close(con, sym, sessions, t["entry_date"])
        e, x = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
        eq_eff, cash_eff = pd.Series(0.0, index=sessions), pd.Series(0.0, index=sessions)
        for s in sessions:
            if e <= s < x:
                eq_eff[s] = t["shares_initial"] * (px[s] - t["entry_price"])
                cash_eff[s] = -t["shares_initial"] * t["entry_price"]
            elif s >= x:
                eq_eff[s] = t["net_pnl"]
                cash_eff[s] = t["net_pnl"]
        out[sym] = (eq_eff, cash_eff)
    con.close()
    return out


def mtm_check(run_trades: list, sessions: pd.Index, equity: pd.Series, cash: pd.Series) -> dict:
    """Validity check of the mark-to-market assumption: equity - cash vs sum over open positions of shares x lake close (forward filled), on a few dates."""
    con = ro()
    cache = {}

    def px(sym):
        if sym not in cache:
            cache[sym] = adj_close(con, sym, sessions)
        return cache[sym]
    res = {}
    for d in (date(2018, 3, 2), date(2018, 4, 17), date(2018, 6, 1), date(2018, 12, 3), date(2021, 7, 30), date(2021, 11, 1), date(2022, 6, 1), date(2024, 6, 3)):
        if d not in equity.index:
            continue
        open_ = [t for t in run_trades if date.fromisoformat(t["entry_date"]) <= d < date.fromisoformat(t["exit_date"])]
        mtm = sum(t["shares_initial"] * px(t["symbol"]).get(d, np.nan) for t in open_)
        res[d.isoformat()] = {"engine_equity_minus_cash": float(equity[d] - cash[d]), "sum_shares_x_lake_close": float(mtm), "ratio": float(mtm / (equity[d] - cash[d])) if equity[d] != cash[d] else None, "open_positions": len(open_)}
    con.close()
    return res


def write_variant(dst: Path, trades: list, equity: pd.Series, cash: pd.Series) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(RUN / "run/manifest.json", dst / "manifest.json")
    (dst / "trades.json").write_text(json.dumps(trades), encoding="utf-8")
    (dst / "equity_curve.json").write_text(json.dumps({k.isoformat(): float(v) for k, v in equity.items()}), encoding="utf-8")
    (dst / "daily.json").write_text(json.dumps({k.isoformat(): {"equity": float(equity[k]), "cash": float(cash[k])} for k in equity.index}), encoding="utf-8")


def nifty_series(last: date, first: date) -> pd.Series:
    from stockbot.data.asof import AsOfView
    from stockbot.data.lake import open_lake
    conn = open_lake(DB)
    try:
        return AsOfView(conn, last).raw_bars(B2.NIFTY, lookback=None, start=first, end=last)["close_raw"]
    finally:
        conn.close()


def gate_rows(res: dict) -> list:
    return [{"gate": r["gate"], "registered": f"{r['comparison']} {r['gate_value']}", "observed": r["observed"], "interval": r["interval"], "met": r["met"]} for r in res["gates"]]


def removal(run_trades, actual, draws, equity, cash, nifty, gates, tmp: Path) -> dict:
    ids = set(STALE.values())
    kept = [t for t in run_trades if t["position_id"] not in ids]
    sessions = equity.index
    paths = mark_paths(run_trades, sessions)
    eq2, ca2 = equity.copy(), cash.copy()
    for sym, (e_eff, c_eff) in paths.items():
        eq2, ca2 = eq2 - e_eff, ca2 - c_eff
    # (a) control: the unmodified run through the same function must reproduce gates.json
    write_variant(tmp / "control", run_trades, equity, cash)
    ctrl = G.evaluate(tmp / "control", nifty, gates, boot=10000, seed=G.SEED)
    # (b) the two positions subtracted
    write_variant(tmp / "removed", kept, eq2, ca2)
    rem = G.evaluate(tmp / "removed", nifty, gates, boot=10000, seed=G.SEED)
    # T1 observed mean with the two baseline pairs removed (same shared code, same seed)
    start, end = date(2016, 1, 1), date(2026, 10, 16)
    a2 = actual[~actual["unique_trade_id"].isin(ids)]
    d2 = draws[~draws["matched_trade_id"].isin(ids)]
    p_full = V.pair_table(actual, draws, 10)
    p_rem = V.pair_table(a2, d2, 10)
    out_t1 = {}
    for tag, p in (("full (registered inputs)", p_full), ("two positions and their baseline pairs removed", p_rem)):
        t1 = VF.family_t1(pd.DataFrame({"riskadj_momentum": V.monthly_series(p, start, end)}), blocks=(2, 3), B=10000, seed=VF.SEED)
        out_t1[tag] = {"pairs": int(len(p)), **{f"block{b}": {k: t1["blocks"][b]["riskadj_momentum"][k] for k in ("observed_mean", "observed_t", "adjusted_p_value", "fwer_significant")} for b in (2, 3)}}
    return {"control_matches_registered": {"expectancy": ctrl["gates"][1]["observed"], "pf": ctrl["gates"][2]["observed"], "dd": ctrl["gates"][3]["observed"], "alpha": ctrl["gates"][4]["observed"]},
            "removed_gates": gate_rows(rem), "removed_counts": {k: rem["counts"][k] for k in ("closed", "usable", "end_of_window", "open_positions_mean", "open_positions_max", "invested_share_mean")},
            "removed_all_met": rem["all_met"], "removed_alpha": {"raw": rem["alpha"]["raw"], "cash_credited": rem["alpha"]["cash_credited"]}, "t1": out_t1,
            "method_note": "trades, expectancy, profit factor and intervals: the stored trades minus the two positions (exact). Drawdown and alpha: stored daily equity and cash minus an estimated path of the two positions "
                           "(shares x lake close, forward filled, until the exit date; realised net P&L after). It is a subtraction, NOT a re-simulation: slots and cash freed by the two positions are not re-used."}


# ---------------------------------------------------------------------------------------------------------------- 3. drawdown episodes
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


def deepest_detail(ep: dict, run_trades: list, equity: pd.Series, cash: pd.Series) -> dict:
    share = B2.invested_share(equity, cash)
    pk, tr = ep["peak_date"], ep["trough_date"]
    rec = ep["recovery_date"]

    def window(lo, hi):
        m = (share.index >= lo) & (share.index <= hi)
        stops = [t for t in run_trades if t["exit_reason"] == "STOP_HIT" and lo < date.fromisoformat(t["exit_date"]) <= hi]
        allx = [t for t in run_trades if lo < date.fromisoformat(t["exit_date"]) <= hi]
        entries = [t for t in run_trades if lo < date.fromisoformat(t["entry_date"]) <= hi]
        return {"from": lo.isoformat(), "to": hi.isoformat(), "sessions": int(m.sum()), "invested_share_mean": float(share[m].mean()), "invested_share_min": float(share[m].min()), "invested_share_max": float(share[m].max()),
                "stop_outs": len(stops), "exits_all_reasons": len(allx), "entries": len(entries), "net_pnl_of_stop_outs": float(sum(t["net_pnl"] for t in stops))}
    out = {"peak_to_trough": window(pk, tr)}
    if rec is not None:
        out["peak_to_recovery"] = window(pk, rec)
    return out


# ---------------------------------------------------------------------------------------------------------------- 4. lake
def lake_facts() -> dict:
    con = ro()
    res = {}
    for sym in STALE:
        n, lo, hi = con.execute("select count(*),min(trade_date),max(trade_date) from market_data_lake where symbol=?", (sym,)).fetchone()
        last_bar = hi
        ca_all = con.execute("select ex_date,action_type,ratio_numerator,ratio_denominator,evidence_tier,notes from corporate_actions_log where symbol=? order by ex_date", (sym,)).fetchall()
        near = [r for r in ca_all if abs((date.fromisoformat(r[0]) - date.fromisoformat(last_bar)).days) <= 365]
        sm = con.execute("select * from securities_master where symbol=?", (sym,)).fetchall()
        cols = [c[0] for c in con.execute("select * from securities_master limit 0").description]
        res[sym] = {"bars": n, "first_bar": lo, "last_bar": last_bar, "ca_rows_total": len(ca_all), "ca_rows_within_365_days_of_last_bar": near,
                    "ca_rows_after_last_bar": [r for r in ca_all if r[0] > last_bar], "last_ca_row": ca_all[-1][:5] if ca_all else None,
                    "securities_master": [dict(zip(cols, r)) for r in sm]}
        feed = [r[5].split("feed_symbol=")[1].split(";")[0] for r in ca_all if r[5] and "feed_symbol=" in r[5]]
        res[sym]["feed_symbol_in_notes"] = sorted(set(feed))
        for f in set(feed) - {sym}:
            res[sym][f"bars_for_symbol_{f}"] = con.execute("select count(*),min(trade_date),max(trade_date) from market_data_lake where symbol=?", (f,)).fetchone()
    con.close()
    return res


def stale_pattern(paths: dict, threshold: int = 20) -> dict:
    con = ro()
    cal = sorted({date.fromisoformat(r[0]) for r in con.execute("select trade_date from market_data_lake where symbol='NIFTY50_INDEX'")})
    cal_idx = pd.Index(cal)
    bars_cache = {}

    def bars(sym):
        if sym not in bars_cache:
            bars_cache[sym] = {date.fromisoformat(r[0]) for r in con.execute("select trade_date from market_data_lake where symbol=?", (sym,))}
        return bars_cache[sym]
    out = {}
    for label, p in paths.items():
        if not Path(p).exists():
            out[label] = {"available": False}
            continue
        trades = json.loads(Path(p).read_text(encoding="utf-8"))
        flagged = []
        for t in trades:
            e, x = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
            sess = [s for s in cal if e <= s <= x]
            have = bars(t["symbol"])
            run = best = 0
            first_missing = None
            for s in sess:
                if s in have:
                    run = 0
                else:
                    run += 1
                    if run > best:
                        best = run
                        first_missing = s
            if best > threshold:
                last_before = max([b for b in have if b < (first_missing or x)], default=None)
                flagged.append({"symbol": t["symbol"], "entry": t["entry_date"], "exit": t["exit_date"], "exit_reason": t["exit_reason"], "longest_missing_run_sessions": best,
                                "sessions_held": len(sess), "last_bar_in_lake": max(have).isoformat() if have else None, "net_pnl": t["net_pnl"],
                                "kind": "no bar from the gap until the exit date (terminal)" if (not have or max(have) < x) else "gap inside the hold, bars resume before the exit date"})
        out[label] = {"available": True, "trades": len(trades), "flagged_count": len(flagged), "flagged_terminal": sum(1 for f in flagged if f["kind"].startswith("no bar")), "flagged": flagged}
    con.close()
    return out


# ---------------------------------------------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    run_trades = json.loads((RUN / "run/trades.json").read_text(encoding="utf-8"))
    blocked = json.loads((RUN / "run/blocked.json").read_text(encoding="utf-8"))
    actual = pd.read_csv(RUN / "baseline/actual_trades.csv")
    draws = pd.read_csv(RUN / "baseline/baseline_draws.csv")
    equity, cash = B2.load_daily(RUN / "run")
    pairs = V.pair_table(actual, draws, 10)
    res = {"inputs": "stored files of docs/strategies/riskadj_momentum/results_run1 (no engine run, no new draws); lake read-only"}
    res["concentration"] = concentration(run_trades, actual, pairs)
    res["stale_positions"] = stale_info(run_trades, equity.index, blocked)
    allrules = {}
    for b in blocked:
        k = b["reason"].split(":")[0].replace("BLOCKED_BY_RISK(", "RISK ") if b["reason"].startswith("BLOCKED_BY_RISK(") else b["reason"]
        allrules[k] = allrules.get(k, 0) + 1
    res["blocked_reasons_whole_run"] = allrules
    res["mtm_check"] = mtm_check(run_trades, equity.index, equity, cash)
    nifty = nifty_series(date(2026, 10, 16), equity.index[0])
    gates = G.load_gates()
    tmp = Path(tempfile.mkdtemp())
    res["removal"] = removal(run_trades, actual, draws, equity, cash, nifty, gates, tmp)
    eps = drawdown_episodes(equity)
    res["drawdown_episodes"] = [{**e, "peak_date": e["peak_date"].isoformat(), "trough_date": e["trough_date"].isoformat(), "recovery_date": e["recovery_date"].isoformat() if e["recovery_date"] else None} for e in eps]
    res["deepest_episode_detail"] = deepest_detail(eps[0], run_trades, equity, cash)
    res["lake"] = lake_facts()
    res["stale_pattern_registered_runs"] = stale_pattern(OTHER_RUNS)
    res["stale_pattern_other_stored_runs"] = stale_pattern(EXTRA_RUNS)
    Path(args.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print("written", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

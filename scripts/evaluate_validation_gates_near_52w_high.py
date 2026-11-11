"""Evaluate the shared validation_gates for ONE near_52w_high run and print every gate beside its registered value. (No code evaluated validation_gates before this script.)

  py scripts/evaluate_validation_gates_near_52w_high.py --run-dir DIR --lake PATH [--out-json FILE] [--t1 validate_results.json] [--boot 10000] [--seed 20261111]

Inputs: the run directory written by scripts/research_near_52w_high.py (manifest.json, trades.json, equity_curve.json, daily.json) and, for the alpha gate, the NIFTY50_INDEX closes inside the
run's window (the only price read from the lake; see scripts/benchmark_nifty_matched_near_52w_high.py). Gate values are read from the shared config at run time, never copied here.

Gates (point estimates, as registered): min_trades (closed, usable trades >= value); min_expectancy_r (mean net R per usable trade >= value); min_profit_factor (sum of winning net P&L /
sum of losing net P&L >= value); max_drawdown_pct (largest peak-to-trough fall of the daily equity curve <= value); min_alpha_after_tax_pct (annualised alpha against the B2 benchmark,
after the shared tax rate >= value). A trade is usable unless its exit reason is END_OF_WINDOW or it is flagged excluded_ca. Intervals (95%, circular block bootstrap over entry months, 3-month
blocks) are reported beside the point estimates and decide nothing. The two sub-periods are DESCRIPTIVE: values only, no gate comparison.
"""
import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_nifty_matched_near_52w_high as B2  # noqa: E402
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402,F401  (module-level name: tests replace it to trace the SQL)
from stockbot.risk.r_metrics import compute_trade_r  # noqa: E402
from stockbot.validation.max_t_bootstrap import _block_resample  # noqa: E402

SEED = 20261111
BLOCK = 3
SUBPERIODS = {"2016-2019": (date(2016, 1, 1), date(2019, 12, 31)), "2020-2026": (date(2020, 1, 1), date(2026, 12, 31))}
GATE_ORDER = ("min_trades", "min_expectancy_r", "min_profit_factor", "max_drawdown_pct", "min_alpha_after_tax_pct")


def load_gates() -> dict:
    return dataclasses.asdict(load_shared_config().validation_gates)


def max_drawdown_pct(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(100.0 * ((peak - equity) / peak).max())


def profit_factor(net_pnl) -> float:
    x = pd.Series(net_pnl, dtype=float)
    gains, losses = float(x[x > 0].sum()), float(-x[x < 0].sum())
    if losses == 0.0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def load_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    eq = json.loads((run_dir / "equity_curve.json").read_text(encoding="utf-8"))
    return {"manifest": json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")), "trades": json.loads((run_dir / "trades.json").read_text(encoding="utf-8")),
            "equity": pd.Series(list(eq.values()), index=pd.Index([date.fromisoformat(k) for k in eq])), "daily": B2.load_daily(run_dir)}


def trade_table(trades: list) -> pd.DataFrame:
    rows = []
    for t in trades:
        r = compute_trade_r(entry_price=t["entry_price"], stop=t["initial_stop"], shares_initial=t["shares_initial"], pnl_gross=t["gross_pnl"], pnl_net=t["net_pnl"], risk_inr=t["risk_inr"])
        rows.append({"entry_date": date.fromisoformat(t["entry_date"]), "exit_date": date.fromisoformat(t["exit_date"]), "net_r": r["net_r"], "net_pnl": float(t["net_pnl"]),
                     "usable": t["exit_reason"] != "END_OF_WINDOW" and not t.get("excluded_ca", False), "end_of_window": t["exit_reason"] == "END_OF_WINDOW",
                     "excluded_ca": bool(t.get("excluded_ca", False))})
    return pd.DataFrame(rows, columns=["entry_date", "exit_date", "net_r", "net_pnl", "usable", "end_of_window", "excluded_ca"])


def _months(equity: pd.Series) -> list:
    return sorted({month_key(d) for d in equity.index})


def _monthly_arrays(table: pd.DataFrame, months: list) -> dict:
    u = table[table["usable"]]
    key = u["entry_date"].map(month_key)
    out = {}
    for name, col in (("sum_r", "net_r"), ("pos", "net_pnl"), ("neg", "net_pnl")):
        v = u[col] if name == "sum_r" else (u[col].clip(lower=0.0) if name == "pos" else (-u[col]).clip(lower=0.0))
        out[name] = v.groupby(key).sum().reindex(months, fill_value=0.0).to_numpy(dtype=float)
    out["cnt"] = u.groupby(key).size().reindex(months, fill_value=0).to_numpy(dtype=float)
    return out


def _monthly_returns(series: pd.Series, months: list) -> np.ndarray:
    key = pd.Series([month_key(d) for d in series.index], index=series.index)
    return ((1.0 + series).groupby(key).prod() - 1.0).reindex(months, fill_value=0.0).to_numpy(dtype=float)


def _ci(values: np.ndarray) -> list:
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def _alpha_for(equity: pd.Series, share: pd.Series, nifty: pd.Series, rf: float, tax: float) -> tuple:
    b = B2.benchmark_returns(nifty, share, rf)
    on = set(equity.index)
    b = b.loc[[d for d in b.index if d in on]]
    return B2.alpha_pct(equity, b, tax_pct=tax), b


def evaluate(run_dir, nifty: pd.Series, gates: dict, *, boot: int = 10000, seed: int = SEED, block: int = BLOCK) -> dict:
    run = load_run(Path(run_dir))
    equity, (eq2, cash) = run["equity"], run["daily"]
    table = trade_table(run["trades"])
    use = table[table["usable"]]
    share = B2.invested_share(eq2, cash)
    alpha, bench = _alpha_for(equity, share, nifty, gates["risk_free_pct"], gates["ltcg_tax_pct"])
    months = _months(equity)
    arr = _monthly_arrays(table, months)
    n_trades = int(len(use))
    expectancy = float(use["net_r"].mean()) if n_trades else 0.0
    pf = profit_factor(use["net_pnl"]) if n_trades else 0.0
    dd = max_drawdown_pct(equity)

    rng = np.random.default_rng(seed)
    W = len(months)
    idx = _block_resample(rng, W, block, boot)
    exp_b = arr["sum_r"][idx].sum(axis=1) / np.maximum(arr["cnt"][idx].sum(axis=1), 1.0)
    neg_b, pos_b = arr["neg"][idx].sum(axis=1), arr["pos"][idx].sum(axis=1)
    pf_b = np.where(neg_b > 0, pos_b / np.where(neg_b > 0, neg_b, 1.0), np.inf)
    rs, rb = _monthly_returns(equity.pct_change().iloc[1:], months), _monthly_returns(bench, months)
    ts, tb = np.prod(1.0 + rs[idx], axis=1), np.prod(1.0 + rb[idx], axis=1)
    inv_years = 1.0 / alpha["years"] if alpha["years"] > 0 else 0.0
    alpha_b = 100.0 * ((ts ** inv_years - 1.0) - (tb ** inv_years - 1.0))

    spec = {"min_trades": (n_trades, ">=", None), "min_expectancy_r": (expectancy, ">=", _ci(exp_b)), "min_profit_factor": (pf, ">=", _ci(pf_b)),
            "max_drawdown_pct": (dd, "<=", None), "min_alpha_after_tax_pct": (alpha["alpha_pct"], ">=", _ci(alpha_b))}
    note = {"min_trades": "a floor only; 40 trades have almost no power", "min_expectancy_r": "the strategy's own absolute net R per usable trade, point estimate",
            "min_profit_factor": "net P&L of usable trades, point estimate", "max_drawdown_pct": "one path, no interval", "min_alpha_after_tax_pct": "annualised against the B2 benchmark (daily share), tax from the shared gates"}
    rows = []
    for g in GATE_ORDER:
        obs, op, interval = spec[g]
        met = bool(obs >= gates[g]) if op == ">=" else bool(obs <= gates[g])
        rows.append({"gate": g, "gate_value": gates[g], "comparison": op, "observed": obs, "interval": interval, "met": met, "note": note[g]})
    open_pos = pd.Series({d: int(((table["entry_date"] <= d) & (table["exit_date"] > d)).sum()) for d in equity.index})
    counts = {"closed": int(len(table)), "usable": n_trades, "end_of_window": int(table["end_of_window"].sum()), "excluded_ca": int(table["excluded_ca"].sum()),
              "entries_per_month": float(n_trades / max(len(months), 1)), "invested_share_mean": float(share.mean()), "invested_share_p5": float(share.quantile(0.05)),
              "invested_share_p95": float(share.quantile(0.95)), "open_positions_mean": float(open_pos.mean()), "open_positions_max": int(open_pos.max())}
    desc = {}
    for tag, (lo, hi) in SUBPERIODS.items():
        mask = [(lo <= d <= hi) for d in equity.index]
        if not any(mask):
            continue
        e = equity[mask]
        sub = use[(use["entry_date"] >= lo) & (use["entry_date"] <= hi)]
        sb = bench.loc[[d for d in bench.index if lo <= d <= hi]]
        d_ = {"descriptive": True, "period": f"{max(lo, e.index[0])} to {min(hi, e.index[-1])}", "trades": int(len(sub)), "expectancy_r": float(sub["net_r"].mean()) if len(sub) else None,
              "profit_factor": profit_factor(sub["net_pnl"]) if len(sub) else None, "max_drawdown_pct": max_drawdown_pct(e),
              "invested_share_mean": float(share[mask].mean())}
        d_["alpha_pct"] = B2.alpha_pct(e, sb, tax_pct=gates["ltcg_tax_pct"])["alpha_pct"] if len(e) > 1 and len(sb) else None
        desc[tag] = d_
    return {"gates": rows, "counts": counts, "all_met": all(r["met"] for r in rows), "descriptive": desc, "seed": seed, "boot": boot, "block_months": block,
            "tax_pct": gates["ltcg_tax_pct"], "risk_free_pct": gates["risk_free_pct"]}


def format_table(res: dict) -> str:
    L = ["gate | registered value | observed | 95% interval | met", "---|---|---|---|---"]
    for r in res["gates"]:
        iv = "-" if r["interval"] is None else f"{r['interval'][0]:.3f} to {r['interval'][1]:.3f}"
        L.append(f"{r['gate']} | {r['comparison']} {r['gate_value']} | {r['observed']:.4f} | {iv} | {'YES' if r['met'] else 'NO'}")
    L += ["", f"all gates met on their point estimates: {res['all_met']}", "", f"counts: {json.dumps(res['counts'])}", "", "DESCRIPTIVE sub-periods (values only; no pass or fail; never used to select, change or stop anything):"]
    for tag, d in res["descriptive"].items():
        L.append(f"  {tag}: {json.dumps(d)}")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate validation_gates for a near_52w_high run (point estimates beside the registered values).")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--lake")
    ap.add_argument("--out-json")
    ap.add_argument("--t1", help="results JSON of scripts/validate_near_52w_high.py: prints the registered conclusion")
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    run_dir = Path(args.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    last = date.fromisoformat(manifest["window"][1])
    from stockbot.data.asof import AsOfView
    conn = open_lake(args.lake)
    try:
        daily_eq, _ = B2.load_daily(run_dir)
        nifty = AsOfView(conn, last).raw_bars(B2.NIFTY, lookback=None, start=daily_eq.index[0], end=min(last, daily_eq.index[-1]))["close_raw"]
    finally:
        conn.close()
    res = evaluate(run_dir, nifty, load_gates(), boot=args.boot, seed=args.seed)
    print(format_table(res))
    if args.t1:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import validate_near_52w_high as V
        t1 = json.loads(Path(args.t1).read_text(encoding="utf-8"))
        res["registered_conclusion"] = V.registered_conclusion(bool(t1["T1"]["dual_significant"]), res["all_met"])
        print("\nregistered conclusion:", res["registered_conclusion"])
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

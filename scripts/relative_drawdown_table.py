"""DESCRIPTIVE, NOT A GATE, NO VERDICT CHANGES: strategy max drawdown against the matched Nifty account and against the full Nifty, for every stored run of docs/results/build_results_page.py.

  py scripts/relative_drawdown_table.py --lake "$STOCKBOT_DB" [--out-json docs/shared/relative-drawdown/TABLE.json] [--out-md docs/shared/relative-drawdown/TABLE.md]

Read-only: reads each run's stored files (run/daily.json, run/equity_curve.json, run/manifest.json, gates.json, benchmark.json) and the NIFTY50_INDEX closes through ``open_lake`` (the AsOfView, as the
benchmark and gates scripts do). Writes only the two output files. Nothing stored is changed; no run, baseline or validation is made; no gate, gates hash, verdict or ledger row is touched.

Matched account: rebuilt with the SAME functions the stored B2 benchmark and the gates script use (``stockbot.validation.benchmark_alpha``): daily invested share from the run (1 - cash / equity at the
previous close), Nifty close-to-close return on that share, idle cash credited at risk_free_pct / 100 / 252 per day; the account starts at 1.0 on the first common date. CHECK per run: the recomputed
cash-credited alpha must equal the stored value to 4 decimals (new-format runs: ``gates.json`` alpha.cash_credited and ``benchmark.json`` gate_alpha_pct; the first run, made under the earlier rules, stored
only the raw alpha in ``b2_benchmark.json``, which is compared instead). A run that fails the check is reported and its drawdown numbers are not used (left empty).
The strategy's own max drawdown is the STORED gate value (``max_drawdown_pct``); its peak and trough dates come from the stored equity curve (a recomputation of the depth is shown as a check only).
Tests A (strategy DD <= matched DD), B (<= 1.25 x matched DD), C (<= full Nifty DD) are shown for every run: DESCRIPTIVE, they are not gates.
"""
import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.validation import benchmark_alpha as BA  # noqa: E402

NIFTY = "NIFTY50_INDEX"
LABEL = "DESCRIPTIVE, NOT A GATE, NO VERDICT CHANGES"
TOL = 5e-5                         # 4 decimals


def runs_list() -> list:
    spec = importlib.util.spec_from_file_location("build_results_page", ROOT / "docs" / "results" / "build_results_page.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.RUNS


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if Path(p).exists() else None


def _series(d: dict) -> pd.Series:
    return pd.Series([float(v) for v in d.values()], index=pd.Index([date.fromisoformat(k) for k in d]))


def load_daily(run: Path) -> tuple:
    d = _j(run / "daily.json")
    idx = pd.Index([date.fromisoformat(k) for k in d])
    return pd.Series([v["equity"] for v in d.values()], index=idx), pd.Series([v["cash"] for v in d.values()], index=idx)


def dd_info(s: pd.Series) -> dict:
    """Max peak-to-trough fall of a value series: depth %, peak date, trough date, recovery date (first later date at or above the peak value) or 'not recovered'."""
    s = s.astype(float)
    peak = s.cummax()
    dd = (peak - s) / peak
    t = dd.idxmax()
    pv = float(peak.loc[t])
    before = s.loc[:t]
    pdate = before[before == pv].index[-1]
    after = s.loc[t:]
    rec = after[after >= pv]
    return {"depth_pct": float(100.0 * dd.max()), "peak_date": pdate.isoformat(), "trough_date": t.isoformat(), "recovery_date": rec.index[0].isoformat() if len(rec) else "not recovered",
            "peak_value": pv, "trough_value": float(s.loc[t])}


def window_overlap(a: dict, b: dict) -> dict:
    """Overlap in calendar days of two falls (peak to trough)."""
    a0, a1, b0, b1 = (date.fromisoformat(x) for x in (a["peak_date"], a["trough_date"], b["peak_date"], b["trough_date"]))
    lo, hi = max(a0, b0), min(a1, b1)
    days = max(0, (hi - lo).days)
    return {"overlap_days": days, "strategy_fall_days": (a1 - a0).days, "matched_fall_days": (b1 - b0).days, "overlap_share_of_strategy_fall": days / max(1, (a1 - a0).days),
            "overlap_share_of_matched_fall": days / max(1, (b1 - b0).days), "strategy_trough_inside_matched_fall": b0 <= a1 <= b1, "matched_trough_inside_strategy_fall": a0 <= b1 <= a1}


def one_run(cfg: dict, conn, rf: float) -> dict:
    run = ROOT / cfg["dir"] / "run"
    gdir = ROOT / cfg["dir"]
    out = {"id": cfg["id"], "name": cfg["name"], "family": cfg["family"], "dir": cfg["dir"]}
    manifest = _j(run / "manifest.json")
    last = date.fromisoformat(manifest["window"][1])
    eq_curve = _series(_j(run / "equity_curve.json"))
    eq2, cash = load_daily(run)
    nifty = AsOfView(conn, last).raw_bars(NIFTY, lookback=None, start=eq2.index[0], end=min(last, eq2.index[-1]))["close_raw"]
    share = BA.invested_share(eq2, cash)
    rep = BA.alpha_report(eq_curve, cash, nifty, risk_free_pct=rf, share=share)
    bench = rep["_benchmark_returns"]
    # ---- the alpha cross-check against the stored value(s)
    gates_name = cfg.get("gates", "gates.json")
    gates = _j(gdir / gates_name) or {}
    bname = cfg.get("bench", "benchmark.json")
    bj = _j(gdir / bname) or {}
    chk = {}
    if isinstance(gates.get("alpha"), dict) and "cash_credited" in gates["alpha"]:
        chk["gates_json_cash_credited_alpha"] = {"stored": gates["alpha"]["cash_credited"]["alpha_pct"], "recomputed": rep["cash_credited"]["alpha_pct"]}
        b_all = BA.benchmark_returns(nifty, share, rf)
        chk["benchmark_json_gate_alpha"] = {"stored": bj.get("gate_alpha_pct"), "recomputed": BA.alpha_pct(BA.cash_credited_equity(eq2, cash, rf), b_all)["alpha_pct"]}
    else:                                                      # the earlier rules: only the raw alpha (idle cash of the strategy not credited) was stored
        b_all = BA.benchmark_returns(nifty, share, rf)
        chk["b2_benchmark_json_raw_alpha"] = {"stored": (bj.get("daily_share") or {}).get("alpha_pct"), "recomputed": BA.alpha_pct(eq2, b_all)["alpha_pct"]}
    for v in chk.values():
        v["abs_diff"] = abs(v["stored"] - v["recomputed"]) if v["stored"] is not None else None
        v["equal_to_4_decimals"] = v["abs_diff"] is not None and v["abs_diff"] < TOL
    ok = all(v["equal_to_4_decimals"] for v in chk.values())
    out["alpha_check"] = chk
    out["alpha_check_ok"] = ok
    out["risk_free_pct_used"] = rf
    out["invested_share_mean"] = float(share.mean())
    out["window"] = [eq2.index[0].isoformat(), eq2.index[-1].isoformat()]
    # ---- strategy drawdown: stored depth, dates from the stored equity curve
    stored_dd = next(g["observed"] for g in gates["gates"] if g["gate"] == "max_drawdown_pct")
    sd = dd_info(eq_curve)
    out["strategy_dd"] = {"depth_pct_stored": stored_dd, "depth_pct_recomputed_check": sd["depth_pct"], "depth_equal_to_4_decimals": abs(stored_dd - sd["depth_pct"]) < TOL,
                          **{k: sd[k] for k in ("peak_date", "trough_date", "recovery_date")}}
    # ---- full Nifty over the same window
    fn = nifty.loc[[d for d in nifty.index if eq_curve.index[0] <= d <= eq_curve.index[-1]]]
    out["full_nifty_dd"] = {k: v for k, v in dd_info(fn).items() if k in ("depth_pct", "peak_date", "trough_date", "recovery_date")}
    if not ok:
        out["matched_dd"] = None
        out["note"] = "alpha cross-check FAILED: matched-account numbers not used"
        out["ratios"] = None
        out["tests"] = None
        return out
    # ---- matched account: starts at 1.0 on the first common date, then compounds the benchmark returns (restricted to the equity dates as in alpha_report)
    first_common = sorted(set(nifty.index) & set(share.index))[0]
    acct = pd.concat([pd.Series([1.0], index=pd.Index([first_common])), (1.0 + bench).cumprod()])
    md = dd_info(acct)
    out["matched_dd"] = {k: md[k] for k in ("depth_pct", "peak_date", "trough_date", "recovery_date")}
    out["matched_account_end_value"] = float(acct.iloc[-1])
    s_depth = stored_dd
    r_m = s_depth / md["depth_pct"] if md["depth_pct"] > 0 else None
    r_f = s_depth / out["full_nifty_dd"]["depth_pct"] if out["full_nifty_dd"]["depth_pct"] > 0 else None
    out["ratios"] = {"strategy_over_matched": r_m, "strategy_over_full_nifty": r_f}
    out["tests"] = {"A_k1.0_vs_matched": s_depth <= md["depth_pct"], "B_k1.25_vs_matched": s_depth <= 1.25 * md["depth_pct"], "C_vs_full_nifty": s_depth <= out["full_nifty_dd"]["depth_pct"]}
    out["_acct"] = acct
    out["_equity"] = eq_curve
    return out


def overlap_block(row: dict) -> dict:
    """For the monthly momentum runs: do the strategy's worst fall and the matched account's worst fall overlap in time; what each did during the other's worst fall."""
    s, m = row["strategy_dd"], row["matched_dd"]
    ov = window_overlap(s, m)
    eq, acct = row["_equity"], row["_acct"]

    def ret(series, a, b):
        sa = series.loc[:date.fromisoformat(a)].iloc[-1]
        sb = series.loc[:date.fromisoformat(b)].iloc[-1]
        return float(100.0 * (sb / sa - 1.0))
    ov["matched_account_change_pct_during_strategy_worst_fall"] = ret(acct, s["peak_date"], s["trough_date"])
    ov["strategy_change_pct_during_matched_worst_fall"] = ret(eq, m["peak_date"], m["trough_date"])
    ov["strategy_peak_to_trough"] = [s["peak_date"], s["trough_date"]]
    ov["matched_peak_to_trough"] = [m["peak_date"], m["trough_date"]]
    return ov


def md_table(rows: list, overlaps: dict) -> str:
    L = [f"# Relative drawdown table ({LABEL})", "",
         "Strategy max drawdown (stored gate value) against the matched Nifty account (rebuilt with the stored B2 functions, idle cash at 6.5% a year) and against the full Nifty 50 over the run window. A: strategy DD <= matched DD; B: <= 1.25 x matched DD; C: <= full Nifty DD. **Not a gate; no verdict changes.**", "",
         "| run | family | invested share (mean) | strategy DD % (peak, trough, recovery) | matched DD % (peak, trough, recovery) | full Nifty DD % (peak, trough, recovery) | strategy / matched | strategy / full Nifty | A | B | C | alpha check |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda d: f"{d['depth_pct']:.2f} ({d['peak_date']}, {d['trough_date']}, {d['recovery_date']})"
    for r in rows:
        s = r["strategy_dd"]
        sd = f"{s['depth_pct_stored']:.2f} ({s['peak_date']}, {s['trough_date']}, {s['recovery_date']})"
        yn = lambda x: "-" if x is None else ("yes" if x else "no")
        t = r["tests"] or {}
        rt = r["ratios"] or {}
        L.append(f"| {r['name']} | {r['family']} | {r['invested_share_mean']:.3f} | {sd} | {f(r['matched_dd']) if r['matched_dd'] else 'n/a (check failed)'} | {f(r['full_nifty_dd'])} | "
                 f"{('%.2f' % rt['strategy_over_matched']) if rt.get('strategy_over_matched') is not None else '-'} | {('%.2f' % rt['strategy_over_full_nifty']) if rt.get('strategy_over_full_nifty') is not None else '-'} | "
                 f"{yn(t.get('A_k1.0_vs_matched'))} | {yn(t.get('B_k1.25_vs_matched'))} | {yn(t.get('C_vs_full_nifty'))} | {'equal to 4 decimals' if r['alpha_check_ok'] else 'FAILED'} |")
    if overlaps:
        L += ["", "## Monthly momentum runs: does the strategy's worst fall overlap the matched account's worst fall?", "",
              "| run | strategy worst fall (peak to trough) | matched worst fall (peak to trough) | overlap (days) | share of strategy fall | trough inside the other fall | matched account change during strategy fall % | strategy change during matched fall % |",
              "|---|---|---|---|---|---|---|---|"]
        for name, o in overlaps.items():
            L.append(f"| {name} | {o['strategy_peak_to_trough'][0]} to {o['strategy_peak_to_trough'][1]} | {o['matched_peak_to_trough'][0]} to {o['matched_peak_to_trough'][1]} | {o['overlap_days']} | "
                     f"{o['overlap_share_of_strategy_fall']:.0%} | strategy trough in matched fall: {'yes' if o['strategy_trough_inside_matched_fall'] else 'no'}; matched trough in strategy fall: {'yes' if o['matched_trough_inside_strategy_fall'] else 'no'} | "
                     f"{o['matched_account_change_pct_during_strategy_worst_fall']:.2f} | {o['strategy_change_pct_during_matched_worst_fall']:.2f} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lake", required=True)
    ap.add_argument("--out-json")
    ap.add_argument("--out-md")
    a = ap.parse_args(argv)
    rf = load_shared_config().validation_gates.risk_free_pct
    conn = open_lake(a.lake)
    try:
        rows = []
        for cfg in runs_list():
            r = one_run(cfg, conn, _rf_for(cfg, rf))
            rows.append(r)
    finally:
        conn.close()
    overlaps = {}
    for r in rows:
        if r["id"] in ("riskadj_momentum", "riskadj_momentum_halfrisk") and r["matched_dd"]:
            overlaps[f"{r['name']} ({r['family']})"] = overlap_block(r)
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    payload = {"label": LABEL, "rows": clean, "monthly_momentum_overlap": overlaps}
    md = md_table(rows, overlaps)
    if a.out_json:
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    if a.out_md:
        Path(a.out_md).write_text(md, encoding="utf-8")
    print(md)
    bad = [r["name"] for r in rows if not r["alpha_check_ok"]]
    if bad:
        print("ALPHA CROSS-CHECK FAILED for: " + "; ".join(bad), file=sys.stderr)
    return 0


def _rf_for(cfg: dict, default: float) -> float:
    """The risk-free rate stored with the run's own gates file when it has one (the first run was made under the earlier rules), else the shared value."""
    g = _j(ROOT / cfg["dir"] / cfg.get("gates", "gates.json")) or {}
    return float(g.get("risk_free_pct", default))


from stockbot.data.guard.runcheck import short_step  # noqa: E402
main = short_step("relative_drawdown_table (short step)")(main)      # run lock and database check before and after


if __name__ == "__main__":
    sys.exit(main())

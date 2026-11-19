"""Build docs/results/results.html from the stored result files.

Run from the repo root:  py docs/results/build_results_page.py
It reads only committed result files (no database, no engine) and writes
docs/results/results_data.json (the numbers) and docs/results/results.html (the page).
To add a backtest: add one entry to RUNS below and run the script again.
The page is a reading aid. The ledger and each strategy's report are the record.
"""
import json
import statistics
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "results"
S = "docs/strategies"

# Fixed order = fixed colour slot per strategy (never re-ordered when a run is added).
RUNS = [
    dict(id="near_52w_high", name="52-week high", slot=1, family="near_52w_high (K=1)",
         rule="Buy stocks closest to their 52-week high. Fixed 40-day hold, 15% stop.",
         dir=f"{S}/near_52w_high/results_4B", gates="gates_results.json", bench="b2_benchmark.json",
         validate=f"{S}/near_52w_high/results_4B/validate_results.json",
         note="Run under the earlier rules: pooled unknown sector, idle cash not credited, alpha gate at -2."),
    dict(id="short_term_reversal", name="Short-term reversal", slot=2, family="family_batch1 (K=2)",
         rule="Buy stocks down 7 to 30% in 5 days. 5-day hold, 8% stop.",
         dir=f"{S}/short_term_reversal/results_run1", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch1/results_run1/validate_family.json", note=""),
    dict(id="pullback_uptrend", name="Pullback in uptrend", slot=3, family="family_batch1 (K=2)",
         rule="Above the 200-day average and RSI(2) under 10. 5-day hold, 8% stop.",
         dir=f"{S}/pullback_uptrend/results_run1", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch1/results_run1/validate_family.json", note=""),
    dict(id="riskadj_momentum", name="Momentum (monthly)", slot=4, family="family_batch2 (K=1)",
         rule="Monthly: top steady 12-month climbers. ATR trailing stop, 8% floor.",
         dir=f"{S}/riskadj_momentum/results_run1", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch2/results_run1/validate_family.json",
         note="Owner decision 2026-11-16: goes to paper trading despite the drawdown gate. Not validated."),
    dict(id="lowvol_uptrend", name="Low volatility", slot=5, family="family_batch3 (K=1)",
         rule="Monthly: calmest stocks above the 200-day average. ATR trailing stop, 8% floor.",
         dir=f"{S}/lowvol_uptrend/results_run1", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch3/results_run1/validate_family.json", note=""),
    dict(id="riskadj_momentum_daily", name="Momentum (any day)", slot=6, family="family_batch4 (K=1)",
         rule="Same as Momentum, but any day is a buy day. 21-day wait after a stop-out.",
         dir=f"{S}/riskadj_momentum_daily/results_run1", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch4/results_run1/validate_family.json",
         note="Variant chosen after the monthly result was seen. 18 positions whose stock left the normal trading category were closed at the last price we have; they made Rs 7.0 lakh of the Rs 36.3 lakh profit. If each had sold at half that price, the expectancy and profit-factor gates would fail."),
    dict(id="riskadj_momentum_daily_noneq", name="Momentum (any day), with restricted-series prices", slot=7, t1_id="riskadj_momentum_daily", family="family_batch5 (K=1)",
         rule="Same rule as Momentum (any day). Stocks that moved to the restricted trading category keep their prices, stops and exits; they are never bought there.",
         dir=f"{S}/riskadj_momentum_daily/results_run2_noneq", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/riskadj_momentum_daily/results_run2_noneq/family_results.json",
         note="New registered trial on the same 2016-2026 data. Stale exits fell from 18 to 2. The test against random picks was not significant (adjusted p 0.42) and drawdown reached 45.6%. The earlier any-day result stands as recorded."),
    dict(id="riskadj_momentum_halfrisk", name="Momentum (monthly), half risk", slot=8, t1_id="riskadj_momentum", family="family_batch6 (K=2)",
         rule="Same rule as Momentum (monthly), but each trade risks 0.5% of the account instead of 1%. Restricted-category stocks keep their prices.",
         dir=f"{S}/family_batch6/results/riskadj_momentum", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch6/results/family_results.json",
         note="New registered trial. Half the risk cut the drawdown from 34% to 24%, still above the 20% gate. The test against random picks dropped to p 0.086 (it was 0.008 under the earlier rules, with a different data treatment and K=1)."),
    dict(id="riskadj_momentum_daily_halfrisk", name="Momentum (any day), half risk", slot=9, t1_id="riskadj_momentum_daily", family="family_batch6 (K=2)",
         rule="Same rule as Momentum (any day), at 0.5% risk per trade, with restricted-category prices.",
         dir=f"{S}/family_batch6/results/riskadj_momentum_daily", gates="gates.json", bench="benchmark.json",
         validate=f"{S}/family_batch6/results/family_results.json",
         note="New registered trial. Drawdown fell from 45.6% to 24.9%, still above the gate. The test against random picks did not change (p 0.42): size does not change which stocks are picked."),
]

# Descriptive study, not a registered trial (docs/shared/market-switch/DECISION.md).
MARKET_SWITCH = dict(
    title="Old kill switch (Nifty below 200-day average or VIX above 22)",
    verdict="Not adopted as a shared rule. Available as an option a strategy can declare.",
    rows=[["Nifty alone: yearly return", "10.4%", "3.5%"], ["Nifty alone: max drawdown", "38%", "24%"],
          ["52-week high: yearly return", "8.4%", "4.4%"], ["52-week high: max drawdown", "27%", "31%"]],
)
NIFTY_WORST_DRAWDOWN_PCT = 38.4   # index-only study in Claude_Docs/MARKET_SWITCH_REPORT.md (2016-2026)

GATE_LABEL = {"min_trades": "Trades", "min_expectancy_r": "Expectancy", "min_profit_factor": "Profit factor",
              "max_drawdown_pct": "Drawdown", "min_alpha_pct": "Alpha", "min_alpha_after_tax_pct": "Alpha"}


def _load(path):
    p = ROOT / path
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _t1(validate, sid):
    if not validate:
        return None
    out = {}
    for b, v in validate["T1"]["blocks"].items():
        v = v.get(sid, v) if isinstance(v, dict) and sid in v else v
        out[b] = dict(p=v["adjusted_p_value"], significant=bool(v["fwer_significant"]), mean=v["observed_mean"])
    return out


def _trade_stats(trades):
    t = trades["trades"] if isinstance(trades, dict) else trades
    u = [x for x in t if not x.get("excluded_ca") and x.get("exit_reason") != "END_OF_WINDOW" and x.get("risk_inr")]
    r = [x["net_pnl"] / x["risk_inr"] for x in u]
    w = [v for v in r if v > 0]
    l = [v for v in r if v <= 0]
    gross = sum(x["gross_pnl"] for x in t)
    costs = sum(x["costs"] for x in t)
    held = []
    for x in u:
        a, b = date.fromisoformat(x["entry_date"]), date.fromisoformat(x["exit_date"])
        held.append((b - a).days)
    return dict(win_rate_pct=100 * len(w) / len(u), avg_win_r=statistics.mean(w), avg_loss_r=statistics.mean(l),
                gross_pnl=gross, fees=costs, net_pnl=gross - costs, median_hold_days=statistics.median(held))


def _monthly(equity):
    last = {}
    for d in sorted(equity):
        v = equity[d]
        last[d[:7]] = v if isinstance(v, (int, float)) else v.get("equity")
    first = equity[sorted(equity)[0]]
    first = first if isinstance(first, (int, float)) else first.get("equity")
    return [[m, round(100 * v / first, 2)] for m, v in sorted(last.items())]


def build_data():
    runs = []
    for cfg in RUNS:
        base = dict(id=cfg["id"], name=cfg["name"], slot=cfg["slot"], family=cfg["family"], rule=cfg["rule"], note=cfg["note"])
        gates = _load(f"{cfg['dir']}/{cfg['gates']}")
        if gates is None:
            runs.append(dict(base, status="running"))
            continue
        bench = _load(f"{cfg['dir']}/{cfg['bench']}") or {}
        t1 = _t1(_load(cfg["validate"]), cfg.get("t1_id", cfg["id"]))
        glist = [dict(key=g["gate"], label=GATE_LABEL.get(g["gate"], g["gate"]), need=g["gate_value"], cmp=g["comparison"],
                      observed=g["observed"], interval=g.get("interval"), met=bool(g["met"])) for g in gates["gates"]]
        alpha = gates.get("alpha", {}).get("cash_credited")
        if alpha:
            cagr, bcagr, a, basis = alpha["strategy_cagr_pct"], alpha["benchmark_cagr_pct"], alpha["alpha_pct"], "idle cash credited at 6.5%"
        else:
            d = bench.get("daily_share", {})
            cagr, bcagr, a, basis = d.get("strategy_cagr_pct"), d.get("benchmark_cagr_pct"), d.get("alpha_pct"), "idle cash not credited (earlier rules)"
        t1_ok = bool(t1) and all(v["significant"] for v in t1.values())
        passed = t1_ok and all(g["met"] for g in glist)
        c = gates.get("counts", {})
        by = {g["key"]: g for g in glist}
        runs.append(dict(
            base, status="done", verdict="PASSED" if passed else "NOT DEMONSTRATED", gates=glist, t1=t1, t1_ok=t1_ok,
            trades=c.get("usable"), entries_per_month=c.get("entries_per_month"), invested_share=c.get("invested_share_mean"),
            open_positions=c.get("open_positions_mean"), cagr_pct=cagr, benchmark_cagr_pct=bcagr, alpha_pct=a, alpha_basis=basis,
            expectancy_r=by["min_expectancy_r"]["observed"], profit_factor=by["min_profit_factor"]["observed"],
            max_drawdown_pct=by["max_drawdown_pct"]["observed"],
            stats=_trade_stats(_load(f"{cfg['dir']}/run/trades.json")),
            equity=_monthly(_load(f"{cfg['dir']}/run/equity_curve.json")),
        ))
    done = [r for r in runs if r["status"] == "done"]
    return dict(updated=date.today().isoformat(), window="2016-01-01 to 2026-10-16", start_equity=1000000,
                nifty_worst_drawdown_pct=NIFTY_WORST_DRAWDOWN_PCT, drawdown_gate_pct=20.0,
                summary=dict(tested=len(done), passed=sum(r["verdict"] == "PASSED" for r in done),
                             running=sum(r["status"] == "running" for r in runs)),
                runs=runs, market_switch=MARKET_SWITCH)


def main():
    data = build_data()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results_data.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    template = (OUT / "results_template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    (OUT / "results.html").write_text(html, encoding="utf-8")
    print(f"wrote results.html: {data['summary']}")


if __name__ == "__main__":
    main()

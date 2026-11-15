"""Part B3 tables: WITHOUT (a run with default_overlays=[]) against WITH (the shared market switch) for one strategy, from the files the run and the gates script wrote. Descriptive only.

  py scripts/market_switch_tables.py --id near_52w_high --without GATES_JSON --without-run RUN_DIR --with GATES_JSON --with-run RUN_DIR
Prints a markdown table. Nothing is computed that the gates script did not already compute (point estimates; alpha against the Nifty matched to each run's own invested share).
"""
import argparse
import json
from pathlib import Path


def load(gates, run):
    g = json.load(open(gates))
    blocked = json.load(open(Path(run) / "blocked.json"))
    ms = [b for b in blocked if b["reason"] == "MARKET_SWITCH"]
    daily = json.load(open(Path(run) / "daily.json"))
    act = sum(1 for v in daily.values() if v.get("market_switch", {}).get("state") == "ACTIVE")
    obs = {x["gate"]: x["observed"] for x in g["gates"]}
    return {"g": g, "obs": obs, "ms": len(ms), "ms_days": len({b["date"] for b in ms}), "ms_distinct": len({(b["symbol"], b["date"]) for b in ms}), "active": act, "sessions": len(daily),
            "has_switch": any("market_switch" in v for v in daily.values())}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    for k in ("without", "without-run", "with", "with-run"):
        ap.add_argument("--" + k, required=True)
    a = vars(ap.parse_args(argv))
    W, S = load(a["without"], a["without_run"]), load(a["with"], a["with_run"])
    rows = []

    def row(name, f, fmt="{:.4f}"):
        def cell(x):
            try:
                v = f(x)
            except KeyError:
                return "-"
            return v if isinstance(v, str) else fmt.format(v)
        rows.append(f"| {name} | {cell(W)} | {cell(S)} |")

    row("closed trades (END_OF_WINDOW included)", lambda x: x["g"]["counts"]["closed"], "{}")
    row("usable trades", lambda x: x["g"]["counts"]["usable"], "{}")
    row("entries per month", lambda x: x["g"]["counts"]["entries_per_month"], "{:.2f}")
    row("proposals blocked MARKET_SWITCH (rows in blocked.json)", lambda x: x["ms"] if x["has_switch"] else "n/a (switch off)", "{}")
    row("  of which distinct symbol-sessions", lambda x: x["ms_distinct"] if x["has_switch"] else "n/a", "{}")
    row("sessions ACTIVE / sessions", lambda x: f"{x['active']} / {x['sessions']}" if x["has_switch"] else "n/a")
    row("invested share (mean)", lambda x: x["g"]["counts"]["invested_share_mean"], "{:.3f}")
    row("open positions (mean)", lambda x: x["g"]["counts"]["open_positions_mean"], "{:.2f}")
    row("expectancy (net R per usable trade)", lambda x: x["obs"]["min_expectancy_r"])
    row("profit factor", lambda x: x["obs"]["min_profit_factor"])
    row("strategy CAGR % (raw)", lambda x: x["g"]["alpha"]["raw"]["strategy_cagr_pct"], "{:.2f}")
    row("strategy CAGR % (cash credited 6.5%)", lambda x: x["g"]["alpha"]["cash_credited"]["strategy_cagr_pct"], "{:.2f}")
    row("matched-Nifty CAGR %", lambda x: x["g"]["alpha"]["raw"]["benchmark_cagr_pct"], "{:.2f}")
    row("alpha pp (raw)", lambda x: x["g"]["alpha"]["raw"]["alpha_pct"], "{:.2f}")
    row("alpha pp (cash credited, pre-tax: the gate quantity)", lambda x: x["g"]["alpha"]["cash_credited"]["alpha_pct"], "{:.2f}")
    row("max drawdown %", lambda x: x["obs"]["max_drawdown_pct"], "{:.2f}")
    out = [f"### {a['id']}", "", "| measure | WITHOUT | WITH |", "|---|---|---|"] + rows + ["", "Sub-periods (descriptive; WITHOUT / WITH):", "",
           "| period | trades | expectancy R | profit factor | max drawdown % | invested share | alpha pp (raw) |", "|---|---|---|---|---|---|---|"]
    for p in W["g"]["descriptive"]:
        d, e = W["g"]["descriptive"][p], S["g"]["descriptive"][p]
        out.append(f"| {p} | {d['trades']} / {e['trades']} | {d['expectancy_r']:.3f} / {e['expectancy_r']:.3f} | {d['profit_factor']:.3f} / {e['profit_factor']:.3f} | "
                   f"{d['max_drawdown_pct']:.2f} / {e['max_drawdown_pct']:.2f} | {d['invested_share_mean']:.3f} / {e['invested_share_mean']:.3f} | {d['alpha_pct']:.2f} / {e['alpha_pct']:.2f} |")
    print("\n".join(out))


if __name__ == "__main__":
    main()

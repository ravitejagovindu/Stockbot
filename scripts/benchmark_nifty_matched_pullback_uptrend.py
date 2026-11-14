"""B2 benchmark for the pullback_uptrend validation: the Nifty matched to the strategy's own invested share, with the risk-free rate on the rest, and the annualised alpha against it.

Daily benchmark return = s(t-1) x Nifty close-to-close return + (1 - s(t-1)) x risk_free_pct / 100 / 252, where s is the strategy's invested share of equity at the previous close
(1 - cash / equity, from the run's daily.json). The run's mean share held constant is the second, reported variant. Both sides are price returns (the lake has no dividends).

The strategy side is credited the same way (shared-rules B1): its idle cash at the previous close earns risk_free_pct / 100 / 252 per day, applied AFTER THE FACT on the recorded equity and
cash (it does not feed back into sizing). The formulas live in ONE module, stockbot/validation/benchmark_alpha.py; this script is a thin wrapper. Alpha is printed raw (no credit) and
cash-credited (the gate value, pre-tax); after-tax lines at reporting.after_tax_rates_pct are illustrative, not tax advice, and decide nothing.

  py scripts/benchmark_nifty_matched_pullback_uptrend.py --run-dir DIR --lake PATH [--out-json FILE]

Reads only the NIFTY50_INDEX series, inside the run's window. Nothing else is read from the lake. No stock price is read.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView, active_view_name  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.validation.benchmark_alpha import TRADING_DAYS, alpha_pct, alpha_report, benchmark_returns, cash_credited_equity, invested_share  # noqa: E402,F401  (the one shared implementation)

NIFTY = "NIFTY50_INDEX"


def load_daily(run_dir: Path) -> tuple:
    daily = json.loads((Path(run_dir) / "daily.json").read_text(encoding="utf-8"))
    idx = pd.Index([date.fromisoformat(k) for k in daily])
    return pd.Series([v["equity"] for v in daily.values()], index=idx), pd.Series([v["cash"] for v in daily.values()], index=idx)


def nifty_closes(lake, first: date, last: date) -> pd.Series:
    """NIFTY50_INDEX raw closes in [first, last] through the as-of view (nothing after ``last``)."""
    conn = open_lake(lake)
    try:
        return AsOfView(conn, last).raw_bars(NIFTY, lookback=None, start=first, end=last)["close_raw"]
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B2: Nifty matched to the invested share (reads the index series only).")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--lake")
    ap.add_argument("--out-json")
    args = ap.parse_args(argv)
    cfg = load_shared_config()
    gates = cfg.validation_gates
    equity, cash = load_daily(Path(args.run_dir))
    nifty = nifty_closes(args.lake, equity.index[0], equity.index[-1])
    share = invested_share(equity, cash)
    out = {}
    for tag, const in (("daily_share", False), ("constant_share", True)):
        b = benchmark_returns(nifty, share, gates.risk_free_pct, constant_share=const)
        rep = {"raw": alpha_pct(equity, b), "cash_credited_pre_tax": alpha_pct(cash_credited_equity(equity, cash, gates.risk_free_pct), b)}
        rep["after_tax_illustrative_not_tax_advice"] = {str(float(t)): alpha_pct(cash_credited_equity(equity, cash, gates.risk_free_pct), b, tax_pct=float(t)) for t in cfg.reporting.after_tax_rates_pct}
        out[tag] = rep
    out["gate_alpha_pct"] = out["daily_share"]["cash_credited_pre_tax"]["alpha_pct"]
    out["mean_invested_share"] = float(share.mean())
    out["asof_view"] = active_view_name()
    print(json.dumps(out, indent=1))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

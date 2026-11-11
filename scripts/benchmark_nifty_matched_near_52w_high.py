"""B2 benchmark for the near_52w_high validation: the Nifty matched to the strategy's own invested share, with the risk-free rate on the rest, and the annualised alpha against it.

Daily benchmark return = s(t-1) x Nifty close-to-close return + (1 - s(t-1)) x risk_free_pct / 100 / 252, where s is the strategy's invested share of equity at the previous close
(1 - cash / equity, from the run's daily.json). The run's mean share held constant is the second, reported variant. Both sides are price returns (the lake has no dividends); the tax rate
is a parameter (the shared ltcg_tax_pct, 0.0), so after-tax equals pre-tax today.

  py scripts/benchmark_nifty_matched_near_52w_high.py --run-dir DIR --lake PATH [--out-json FILE]

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
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402

NIFTY = "NIFTY50_INDEX"
TRADING_DAYS = 252


def invested_share(equity: pd.Series, cash: pd.Series) -> pd.Series:
    """Share of equity not in cash at each close, clipped to 0..1."""
    return (1.0 - cash / equity).clip(lower=0.0, upper=1.0)


def benchmark_returns(nifty: pd.Series, share: pd.Series, risk_free_pct: float, *, constant_share: bool = False, trading_days: int = TRADING_DAYS) -> pd.Series:
    """Daily benchmark returns from the second common date on; each day uses the share at the PREVIOUS close."""
    idx = sorted(set(nifty.index) & set(share.index))
    nifty, share = nifty.loc[idx], share.loc[idx]
    if constant_share:
        share = pd.Series(float(share.mean()), index=pd.Index(idx))
    ret = nifty.pct_change().iloc[1:]
    prev = share.shift(1).iloc[1:]
    rf = risk_free_pct / 100.0 / trading_days
    return prev * ret + (1.0 - prev) * rf


def _after_tax_end(start: float, end: float, tax_pct: float) -> float:
    return start + (end - start) * (1.0 - tax_pct / 100.0) if end > start else end


def alpha_pct(strategy_equity: pd.Series, bench_returns: pd.Series, *, tax_pct: float = 0.0) -> dict:
    """Annualised alpha in percentage points: strategy CAGR minus benchmark CAGR over the strategy's first to last date (365.25-day years), each after tax on a gain."""
    first, last = strategy_equity.index[0], strategy_equity.index[-1]
    years = (last - first).days / 365.25
    s0, s1 = float(strategy_equity.iloc[0]), float(strategy_equity.iloc[-1])
    b0, b1 = 1.0, float((1.0 + bench_returns).prod())
    s1, b1 = _after_tax_end(s0, s1, tax_pct), _after_tax_end(b0, b1, tax_pct)
    cs, cb = 100.0 * ((s1 / s0) ** (1.0 / years) - 1.0), 100.0 * ((b1 / b0) ** (1.0 / years) - 1.0)
    return {"years": years, "strategy_cagr_pct": cs, "benchmark_cagr_pct": cb, "alpha_pct": cs - cb}


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
    gates = load_shared_config().validation_gates
    equity, cash = load_daily(Path(args.run_dir))
    nifty = nifty_closes(args.lake, equity.index[0], equity.index[-1])
    share = invested_share(equity, cash)
    out = {}
    for tag, const in (("daily_share", False), ("constant_share", True)):
        b = benchmark_returns(nifty, share, gates.risk_free_pct, constant_share=const)
        out[tag] = alpha_pct(equity, b, tax_pct=gates.ltcg_tax_pct)
    out["mean_invested_share"] = float(share.mean())
    print(json.dumps(out, indent=1))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

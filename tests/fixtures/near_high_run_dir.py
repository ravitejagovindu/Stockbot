"""Synthetic run directories and baselines for the near_52w_high validation-script tests. Pure fixtures: no lake, no engine, no real price.

``make_run(path, ...)`` writes what scripts/research_near_52w_high.py writes: manifest.json (window, initial equity), trades.json (closed trades, the ClosedTrade fields as plain data),
equity_curve.json (date -> equity marked at the close), daily.json (date -> {"equity", "cash"}). ``make_baseline(path, run_dir, ...)`` writes what the B1 script writes: actual_trades.csv and
baseline_draws.csv (m draws per trade, with a chosen true edge of the actual trades over their random draws).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

START_EQUITY = 1_000_000.0


def weekdays(start: date, end: date) -> list:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def month_starts(start: date, months: int) -> list:
    out = []
    y, m = start.year, start.month
    for _ in range(months):
        out.append(date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def make_run(path: Path, *, months: int = 60, per_month: int = 6, mean_r: float = 0.4, sd_r: float = 1.2, seed: int = 1, start: date = date(2016, 1, 4), risk_inr: float = 10_000.0,
             daily_drift: float = 0.0006, daily_sd: float = 0.006, share: float = 0.78, drawdown_pct: float = 0.0, extra_end_of_window: int = 0, extra_excluded_ca: int = 0,
             n_trades: int | None = None) -> dict:
    """Write a run directory under ``path``. ``mean_r`` is the true mean net R of the trades; ``drawdown_pct`` > 0 inserts a peak-to-trough fall of about that size in the middle of the equity curve."""
    rng = np.random.default_rng(seed)
    path.mkdir(parents=True, exist_ok=True)
    ms = month_starts(start, months)
    end = (ms[-1] + timedelta(days=31)).replace(day=1) - timedelta(days=1)
    trades = []
    k = 0
    for m0 in ms:
        days = [d for d in weekdays(m0, m0 + timedelta(days=27))][:per_month * 2]
        for j in range(per_month):
            entry = days[j * 2]
            exit_ = entry + timedelta(days=58)
            r = float(rng.normal(mean_r, sd_r))
            r = max(r, -1.0)                                           # a stop caps the loss at about 1 R
            pnl = r * risk_inr
            trades.append(dict(position_id=f"p{k}", strategy_id="near_52w_high", symbol=f"S{k % 40:02d}", entry_date=entry.isoformat(), exit_date=exit_.isoformat(),
                               entry_price=100.0, initial_stop=85.0, shares_initial=risk_inr / 15.0, risk_inr=risk_inr, gross_pnl=pnl + 0.05 * risk_inr, costs=0.05 * risk_inr,
                               net_pnl=pnl, exit_reason="STOP_HIT" if r <= -0.95 else "TIME_EXIT", excluded_ca=False))
            k += 1
    if n_trades is not None:
        trades = trades[:n_trades]
    for i in range(extra_end_of_window):
        t = dict(trades[-1]); t.update(position_id=f"eow{i}", exit_reason="END_OF_WINDOW", net_pnl=5.0 * risk_inr, gross_pnl=5.0 * risk_inr); trades.append(t)
    for i in range(extra_excluded_ca):
        t = dict(trades[0]); t.update(position_id=f"xca{i}", excluded_ca=True, net_pnl=-5.0 * risk_inr, gross_pnl=-5.0 * risk_inr); trades.append(t)
    days = weekdays(start, end)
    ret = rng.normal(daily_drift, daily_sd, len(days))
    if drawdown_pct > 0:
        mid = len(days) // 2
        ret[mid:mid + 10] = -(1 - (1 - drawdown_pct / 100.0) ** 0.1)      # ten days of equal falls adding up to the requested drawdown
        ret[mid + 10:mid + 30] = 0.0
    eq = START_EQUITY * np.cumprod(1.0 + ret)
    cash = eq * (1.0 - share)
    (path / "manifest.json").write_text(json.dumps({"window": [start.isoformat(), end.isoformat()], "initial_equity": START_EQUITY, "strategies": {"near_52w_high": {"exit_policy": "fixed_hold_40"}}}))
    (path / "trades.json").write_text(json.dumps(trades))
    (path / "equity_curve.json").write_text(json.dumps({d.isoformat(): float(v) for d, v in zip(days, eq)}))
    (path / "daily.json").write_text(json.dumps({d.isoformat(): {"equity": float(v), "cash": float(c)} for d, v, c in zip(days, eq, cash)}))
    return dict(start=start, end=end, trades=trades, days=days, equity=eq)


def make_baseline(path: Path, run_dir: Path, *, edge_r: float = 0.0, m: int = 20, seed: int = 2, sd_r: float = 1.2, min_filled: int = 10, short_pairs: int = 0) -> None:
    """actual_trades.csv and baseline_draws.csv for the usable trades of ``run_dir``. The actual net R is its draws' true mean (0) plus ``edge_r`` plus noise; ``short_pairs`` trades get
    only ``min_filled - 1`` draws (they must be dropped from the pairs)."""
    rng = np.random.default_rng(seed)
    path.mkdir(parents=True, exist_ok=True)
    trades = json.loads((run_dir / "trades.json").read_text())
    use = [t for t in trades if t["exit_reason"] != "END_OF_WINDOW" and not t["excluded_ca"]]
    rows_a, rows_d = [], []
    for i, t in enumerate(use):
        entry = date.fromisoformat(t["entry_date"])
        window = "2016-2019" if entry <= date(2019, 12, 31) else "2020-2026"
        net = float(rng.normal(edge_r, sd_r))
        rets = {f"ret_{h}": float(rng.normal(0.0, 3.0)) for h in (1, 5, 10, 20)}
        rows_a.append(dict(unique_trade_id=t["position_id"], symbol=t["symbol"], window=window, entry_date=t["entry_date"], exit_date=t["exit_date"], entry_price=100.0, stop=85.0,
                           gross_r=net + 0.05, net_r=net, days_held=40, **rets))
        n = (min_filled - 1) if i < short_pairs else m
        for j in range(n):
            rn = float(rng.normal(0.0, sd_r))
            rows_d.append(dict(matched_trade_id=t["position_id"], symbol=f"R{j:02d}", window=window, entry_date=t["entry_date"], exit_date=t["exit_date"], entry_price=100.0, stop=85.0,
                               exit_reason="TIME_EXIT", gross_r=rn + 0.05, net_r=rn, days_held=40, **{f"ret_{h}": float(rng.normal(0.0, 3.0)) for h in (1, 5, 10, 20)}))
    pd.DataFrame(rows_a).to_csv(path / "actual_trades.csv", index=False)
    pd.DataFrame(rows_d).to_csv(path / "baseline_draws.csv", index=False)
    (path / "baseline_meta.json").write_text(json.dumps({"draws_per_trade": m, "min_filled": min_filled, "seed": 20261111, "dropped_pairs": short_pairs, "unfilled": {}}))

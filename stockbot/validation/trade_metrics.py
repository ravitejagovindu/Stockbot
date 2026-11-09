"""stockbot/validation/trade_metrics.py — trade and portfolio performance REPORTING. The R definitions (risk_inr, gross/net R) live in stockbot/risk/r_metrics.py (Q2)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text

from stockbot.risk.r_metrics import add_r_columns


def trades_from_log(session, mode: str) -> pd.DataFrame:
    """One row per POSITION (partials merged)."""
    return pd.read_sql(
        text("""
            SELECT position_id, symbol, MIN(entry_date) AS entry_date, MAX(exit_date) AS exit_date,
                   MIN(entry_price) AS entry_price, MIN(initial_stop_loss) AS stop, SUM(shares) AS shares, MAX(risk_inr) AS risk_inr, MAX(excluded_ca) AS excluded_ca,
                   SUM(pnl_gross) AS pnl_gross, SUM(costs_total) AS costs, SUM(pnl_net) AS pnl_net,
                   SUM(tax_est) AS tax_est, MAX(days_held) AS days_held
            FROM trade_analytics_log WHERE mode = :m GROUP BY position_id, symbol
        """),
        session.bind,
        params={"m": mode},
        parse_dates=["entry_date", "exit_date"],
    )


def sharpe_from_equity(equity: pd.Series, rf_annual: float = 0.065) -> float:
    r = equity.pct_change().dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float((r.mean() - rf_annual / 252.0) / r.std() * np.sqrt(252))


def metrics_from_trades(df: pd.DataFrame, start_equity: float) -> dict:
    """Columns required: entry_price, stop, shares, pnl_net, tax_est, exit_date."""
    if df.empty:
        return {"n_trades": 0}
    t = df.sort_values("exit_date").copy()
    if "excluded_ca" in t.columns:  # F3: trades touched by unhandled corporate actions are excluded from statistics
        t = t[~t["excluded_ca"].astype(bool)]
        if t.empty:
            return {"n_trades": 0}
    t["net_after_tax"] = t["pnl_net"] - t["tax_est"]
    t["r_net"] = add_r_columns(t)["net_r"].values
    wins, losses = t[t["net_after_tax"] > 0], t[t["net_after_tax"] <= 0]
    eq = start_equity + t["net_after_tax"].cumsum()
    dd = ((eq.cummax() - eq) / eq.cummax()).max() * 100.0
    gl = abs(losses["net_after_tax"].sum())
    return {
        "n_trades": int(len(t)),
        "win_rate_pct": float(len(wins) / len(t) * 100.0),
        "expectancy_r": float(t["r_net"].mean()),
        "profit_factor": float(wins["net_after_tax"].sum() / gl) if gl > 0 else float("inf"),
        "avg_win_r": float(wins["r_net"].mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses["r_net"].mean()) if len(losses) else 0.0,
        "max_drawdown_pct_trade_level": float(dd),
        "net_pnl_after_tax": float(t["net_after_tax"].sum()),
    }

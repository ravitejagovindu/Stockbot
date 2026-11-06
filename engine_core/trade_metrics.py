"""engine_core/trade_metrics.py — Unified trade and portfolio performance metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text


# ---------------------------------------------------------------------------
# R-multiple definitions (single source of truth — F1)
# ---------------------------------------------------------------------------
# R is always measured against the INITIAL risk of the position in rupees:
#     risk_inr = shares_initial * (entry_price - initial_stop)
# recorded at entry (and kept unchanged by splits/bonuses, which rescale prices and
# shares together). Partial exits are NOT measured against remaining risk: the P&L of every
# exit of the position (partials + final) is summed and divided by the one initial risk.
#   gross_r         = pnl_gross / risk_inr                 (price P&L incl. slippage, before fees)
#   net_r           = pnl_net / risk_inr                   (after STT/stamp/DP/GST/exchange/SEBI fees)
#   net_r_after_tax = (pnl_net - tax_est) / risk_inr
# Rows with non-positive risk get 0.0 (matches the previous behaviour of metrics_from_trades).

R_COLUMNS = ("gross_r", "net_r", "net_r_after_tax")


def compute_trade_r(*, entry_price: float, stop: float, shares_initial: float, pnl_gross: float,
                    pnl_net: float, tax_est: float = 0.0, risk_inr: float | None = None) -> dict:
    """Scalar R metrics for one position. ``risk_inr`` overrides entry/stop/shares when given."""
    risk = float(risk_inr) if risk_inr is not None else float(shares_initial) * (float(entry_price) - float(stop))
    if not risk > 0:
        return {"risk_inr": risk, "gross_r": 0.0, "net_r": 0.0, "net_r_after_tax": 0.0}
    return {
        "risk_inr": risk,
        "gross_r": float(pnl_gross) / risk,
        "net_r": float(pnl_net) / risk,
        "net_r_after_tax": (float(pnl_net) - float(tax_est)) / risk,
    }


def add_r_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with ``risk_inr``, ``gross_r``, ``net_r``, ``net_r_after_tax``.

    Uses the same formulas as :func:`compute_trade_r`. Needs ``pnl_gross`` and ``pnl_net``; the risk base is
    the existing ``risk_inr`` column when present, else ``shares * (entry_price - stop)``. ``tax_est`` defaults to 0.
    """
    out = df.copy()
    if "risk_inr" not in out.columns:
        out["risk_inr"] = out["shares"] * (out["entry_price"] - out["stop"])
    tax = out["tax_est"] if "tax_est" in out.columns else 0.0
    ok = out["risk_inr"] > 0
    safe = out["risk_inr"].where(ok, 1.0)
    if "pnl_gross" in out.columns:
        out["gross_r"] = np.where(ok, out["pnl_gross"] / safe, 0.0)
    else:  # metrics-only callers (e.g. DB-log summaries) may not carry gross P&L
        out["gross_r"] = np.nan
    out["net_r"] = np.where(ok, out["pnl_net"] / safe, 0.0)
    out["net_r_after_tax"] = np.where(ok, (out["pnl_net"] - tax) / safe, 0.0)
    return out


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

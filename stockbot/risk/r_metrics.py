"""stockbot/risk/r_metrics.py — R-multiple definitions (single source of truth, F1). Moved out of trade_metrics in restructure Phase 5 (decision Q2): R definitions live in risk; trade-R reporting stays in validation."""
from __future__ import annotations

import numpy as np
import pandas as pd


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

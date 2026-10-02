"""
FInsight Trading Engine — Analytics Loop
=========================================
Records closed trade performance and generates decay reports.

When a position is closed (manually, stop-hit, time-decay, or
earnings-driven), ``record_closed_trade`` computes:

* **Realized R:R** = ``(exit - entry) / (entry - initial_stop)``
  → Negative for a loss; 1.0 means exactly 1:1.
* **Gross P&L** = ``(exit - entry) × shares``

The ``get_decay_report`` method computes the running decay between
projected and realized R:R — the primary performance health metric for
this strategy.

Decay Ratio
-----------
``decay_ratio = avg_realized_rr / avg_projected_rr``

A ratio of 1.0 means the strategy delivers exactly what the setup
projected.  A ratio below 0.5 is a red flag (strategy underperforming
severely vs. back-test expectations) and should trigger a pause and review.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from data.db.models import ActivePosition, TradeAnalyticsLog, RegimeState

logger = logging.getLogger(__name__)


class AnalyticsLoop:
    """Closed-trade performance recorder and decay reporter.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.  Reads from ``active_positions`` and
        ``regime_state``; writes to ``trade_analytics_log`` (append-only).
    """

    def __init__(self, session: Session) -> None:
        """Initialise with an active DB session."""
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_closed_trade(
        self,
        position_id: int,
        exit_price: float,
        exit_date: date,
        exit_reason: str,
    ) -> dict:
        """Record a closed position in ``trade_analytics_log`` and return the log entry.

        This method reads the position from ``active_positions``, computes
        realized metrics, and inserts a new row into ``trade_analytics_log``.
        It does **not** delete the position from ``active_positions`` — that
        is handled by ``PositionLifecycleManager.close_position``.

        Parameters
        ----------
        position_id:
            Primary key of the ``active_positions`` row.
        exit_price:
            Actual price at which the position was closed.
        exit_date:
            Calendar date of the exit.
        exit_reason:
            One of ``'MANUAL'``, ``'STOP_HIT'``, ``'TIME_DECAY'``,
            ``'EARNINGS_EXIT'``.

        Returns
        -------
        dict
            The logged record (mirrors ``trade_analytics_log`` columns).

        Raises
        ------
        ValueError
            If the position ID is not found.
        ZeroDivisionError
            If ``entry_price == initial_stop_loss`` (invalid position data).
        """
        pos: Optional[ActivePosition] = self._session.get(ActivePosition, position_id)
        if pos is None:
            raise ValueError(
                f"Position ID {position_id} not found in active_positions."
            )

        initial_risk_per_share = pos.entry_price - pos.initial_stop_loss
        if initial_risk_per_share == 0:
            raise ZeroDivisionError(
                f"Position {position_id}: entry_price == initial_stop_loss "
                f"({pos.entry_price}). Cannot compute R:R."
            )

        # Core metrics
        realized_rr = (exit_price - pos.entry_price) / initial_risk_per_share
        pnl_gross = (exit_price - pos.entry_price) * pos.shares
        days_held = (exit_date - pos.entry_date).days

        # Regime at exit (best-effort lookup)
        regime_at_exit = self._get_regime_label(exit_date)
        regime_at_entry = self._get_regime_label(pos.entry_date)

        log_row = TradeAnalyticsLog(
            position_id=position_id,
            symbol=pos.symbol,
            entry_date=pos.entry_date,
            exit_date=exit_date,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            shares=pos.shares,
            initial_stop_loss=pos.initial_stop_loss,
            projected_rr=pos.projected_rr,
            realized_rr=realized_rr,
            pnl_gross=pnl_gross,
            exit_reason=exit_reason,
            regime_at_entry=regime_at_entry,
            regime_at_exit=regime_at_exit,
            sector=pos.sector,
            days_held=days_held,
        )
        self._session.add(log_row)
        self._session.flush()

        record = {
            "position_id": position_id,
            "symbol": pos.symbol,
            "entry_date": pos.entry_date.isoformat(),
            "exit_date": exit_date.isoformat(),
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "shares": pos.shares,
            "projected_rr": pos.projected_rr,
            "realized_rr": round(realized_rr, 4),
            "pnl_gross": round(pnl_gross, 2),
            "exit_reason": exit_reason,
            "regime_at_exit": regime_at_exit,
            "days_held": days_held,
            "logged": True,
        }
        logger.info(
            "[AnalyticsLoop] Closed %s: exit=%.2f | realized_rr=%.3f | pnl=%.2f",
            pos.symbol,
            exit_price,
            realized_rr,
            pnl_gross,
        )
        return record

    def get_decay_report(self) -> dict:
        """Compute the projected-vs-realized R:R decay report.

        Returns a dictionary containing:

        * ``avg_projected_rr`` — mean projected R:R across all closed trades.
        * ``avg_realized_rr`` — mean realized R:R across all closed trades.
        * ``decay_ratio`` — ``avg_realized_rr / avg_projected_rr``
          (1.0 = perfect; < 0.5 = review required).
        * ``rolling_3m`` — rolling 3-month (90-day) version of decay ratio.
        * ``rolling_6m`` — rolling 6-month (180-day) version of decay ratio.
        * ``total_trades`` — number of closed trades in the log.
        * ``win_rate`` — fraction of trades where ``realized_rr > 0``.

        Returns
        -------
        dict
            Decay report dictionary.  ``None`` values indicate insufficient
            data for a particular metric.
        """
        rows = (
            self._session.execute(
                select(
                    TradeAnalyticsLog.exit_date,
                    TradeAnalyticsLog.projected_rr,
                    TradeAnalyticsLog.realized_rr,
                )
                .order_by(TradeAnalyticsLog.exit_date)
            )
            .all()
        )

        if not rows:
            return {
                "avg_projected_rr": None,
                "avg_realized_rr": None,
                "decay_ratio": None,
                "rolling_3m": None,
                "rolling_6m": None,
                "total_trades": 0,
                "win_rate": None,
            }

        df = pd.DataFrame(
            [
                {
                    "exit_date": r.exit_date,
                    "projected_rr": float(r.projected_rr),
                    "realized_rr": float(r.realized_rr),
                }
                for r in rows
            ]
        )

        total = len(df)
        avg_proj = float(df["projected_rr"].mean())
        avg_real = float(df["realized_rr"].mean())
        decay_ratio = avg_real / avg_proj if avg_proj != 0 else None
        win_rate = float((df["realized_rr"] > 0).sum()) / total

        # Rolling windows
        today = date.today()
        rolling_3m = self._rolling_decay(df, today, days=90)
        rolling_6m = self._rolling_decay(df, today, days=180)

        return {
            "avg_projected_rr": round(avg_proj, 4),
            "avg_realized_rr": round(avg_real, 4),
            "decay_ratio": round(decay_ratio, 4) if decay_ratio is not None else None,
            "rolling_3m": rolling_3m,
            "rolling_6m": rolling_6m,
            "total_trades": total,
            "win_rate": round(win_rate, 4),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rolling_decay(
        self, df: pd.DataFrame, as_of: date, days: int
    ) -> Optional[float]:
        """Return decay ratio for the last ``days`` calendar days.

        Parameters
        ----------
        df:
            Full closed-trade DataFrame with ``exit_date``, ``projected_rr``,
            ``realized_rr`` columns.
        as_of:
            Reference date (usually today).
        days:
            Rolling window in calendar days.

        Returns
        -------
        float or None
        """
        cutoff = as_of - timedelta(days=days)
        window = df[df["exit_date"] >= cutoff]
        if window.empty:
            return None
        avg_proj = window["projected_rr"].mean()
        avg_real = window["realized_rr"].mean()
        if avg_proj == 0:
            return None
        return round(float(avg_real / avg_proj), 4)

    def _get_regime_label(self, for_date: date) -> Optional[str]:
        """Look up the kill-switch state label for a given date.

        Returns ``'ACTIVE'`` (trading allowed) or ``'KILL_SWITCH'`` (trading
        halted), or ``None`` if not found.
        """
        row = (
            self._session.execute(
                select(RegimeState.kill_switch_active)
                .where(RegimeState.eval_date <= for_date)
                .order_by(RegimeState.eval_date.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return None
        return "KILL_SWITCH" if row else "ACTIVE"

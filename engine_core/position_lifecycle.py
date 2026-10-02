"""
FInsight Trading Engine — Position Lifecycle Manager
====================================================
Implements the daily state machine for all open positions.

State Machine
-------------

::

    INITIAL_RISK
        │
        ├─ highest_high >= entry + 1R  ──► RISK_FREE_1_TO_1  (live_stop = entry)
        └─ days_held >= 15             ──► PENDING_MANUAL_EXIT

    RISK_FREE_1_TO_1
        └─ highest_high > initial_resistance_target  ──► TRAILING_ATR

    TRAILING_ATR
        └─ (ratchet only up)
           candidate_stop = highest_high - (2 × ATR14)
           live_stop = max(live_stop, candidate_stop)

    PENDING_MANUAL_EXIT
        └─ (no automated transitions — UI prompts manual close)

Independent (any state):
    earnings_alert = True  if days_to_earnings <= earnings_alert_days

Where:
    1R = entry_price - initial_stop_loss  (initial risk per share)

Design Invariants
-----------------
* ``RISK_FREE_1_TO_1`` graduation takes priority over ``PENDING_MANUAL_EXIT``
  on the same day (i.e. hitting 1:1 on day 14 does NOT trigger pending).
* The trailing stop is a ratchet — it only moves UP, never down, even if
  ATR expands after a drawdown.
* Earnings alert is evaluated independently after state transitions.
* All DB writes use ``session.flush()`` so the caller controls the commit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Optional

import pandas as pd
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from data.db.models import (
    ActivePosition,
    EarningsCalendar,
    MarketDataLake,
    CorporateActionsLog,
)
from engine_core.adjustments import get_adjusted_series
from engine_core.indicators import atr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Dataclasses
# ---------------------------------------------------------------------------

class PositionState(str, Enum):
    """Lifecycle states for an open position."""

    INITIAL_RISK = "INITIAL_RISK"
    RISK_FREE_1_TO_1 = "RISK_FREE_1_TO_1"
    TRAILING_ATR = "TRAILING_ATR"
    PENDING_MANUAL_EXIT = "PENDING_MANUAL_EXIT"


@dataclass
class PositionUpdate:
    """Result of processing a single position for one trading session.

    Attributes
    ----------
    position_id:
        Primary key of the ``active_positions`` row.
    symbol:
        NSE ticker.
    old_state:
        State at start of today's processing.
    new_state:
        State after today's transitions.
    new_live_stop_loss:
        Updated live stop-loss price.
    new_days_held:
        Incremented days-held counter.
    new_highest_high:
        Updated all-time-high since breakout.
    earnings_alert:
        ``True`` if an upcoming earnings event is within the alert window.
    flags:
        List of event tags for this update, e.g.
        ``['STATE_CHANGED', 'STOP_UPDATED', 'EARNINGS_ALERT']``.
    """

    position_id: int
    symbol: str
    old_state: PositionState
    new_state: PositionState
    new_live_stop_loss: float
    new_days_held: int
    new_highest_high: float
    earnings_alert: bool
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PositionLifecycleManager class
# ---------------------------------------------------------------------------

class PositionLifecycleManager:
    """Daily processor for all open positions.

    Parameters
    ----------
    config:
        Full strategy config dict.  Uses ``risk`` and ``trade_management``
        sub-dicts.
    session:
        Active SQLAlchemy session.  Reads from ``active_positions``,
        ``market_data_lake``, ``corporate_actions_log``, and
        ``earnings_calendar``.  Writes updated state back to
        ``active_positions``.
    """

    def __init__(self, config: dict, session: Session) -> None:
        """Initialise with strategy config and an active DB session."""
        risk = config["risk"]
        tm = config["trade_management"]

        self._atr_period: int = int(risk["atr_period"])
        self._trailing_stop_mult: float = float(risk["trailing_stop_atr_multiplier"])
        self._time_decay_sessions: int = int(tm["time_decay_sessions"])
        self._earnings_alert_days: int = int(tm["earnings_alert_days"])

        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_all(self, eval_date: date) -> list[PositionUpdate]:
        """Process every open position for ``eval_date``.

        Positions are loaded ordered by ``entry_date`` ascending so that
        older positions are processed first (consistent ordering for logs).

        Parameters
        ----------
        eval_date:
            The trading date being processed.

        Returns
        -------
        list[PositionUpdate]
            One update per open position.
        """
        positions = (
            self._session.execute(
                select(ActivePosition).order_by(ActivePosition.entry_date)
            )
            .scalars()
            .all()
        )

        updates = []
        for pos in positions:
            try:
                update = self.process_single(pos.id, eval_date)
                updates.append(update)
            except Exception as exc:
                logger.error(
                    "[PositionLifecycle] Failed to process position %d (%s): %s",
                    pos.id,
                    pos.symbol,
                    exc,
                    exc_info=True,
                )
        return updates

    def process_single(self, position_id: int, eval_date: date) -> PositionUpdate:
        """Process one open position through the daily state machine.

        Parameters
        ----------
        position_id:
            Primary key of the ``active_positions`` row.
        eval_date:
            The trading date to evaluate.

        Returns
        -------
        PositionUpdate
            Full update result for API / logging consumption.

        Raises
        ------
        ValueError
            If the position ID does not exist.
        RuntimeError
            If today's OHLCV data is unavailable for the position's symbol.
        """
        pos: Optional[ActivePosition] = self._session.get(ActivePosition, position_id)
        if pos is None:
            raise ValueError(f"Position ID {position_id} not found in active_positions.")

        # Fetch adjusted OHLCV for ATR and high/low tracking
        raw_ohlcv = self._fetch_raw_ohlcv(pos.symbol, eval_date, lookback=220)
        if raw_ohlcv.empty or eval_date not in raw_ohlcv.index:
            raise RuntimeError(
                f"No OHLCV data for {pos.symbol} on {eval_date}."
            )

        corp_actions = self._fetch_corporate_actions(pos.symbol)
        adj_ohlcv = get_adjusted_series(raw_ohlcv, corp_actions, as_of_date=eval_date)

        # Today's adjusted high (for highest-high tracking)
        today_high_adj = float(adj_ohlcv.loc[eval_date, "high_adj"])

        # Compute ATR14 on adjusted series
        atr_series = atr(
            adj_ohlcv["high_adj"],
            adj_ohlcv["low_adj"],
            adj_ohlcv["close_adj"],
            period=self._atr_period,
        )
        latest_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0

        old_state = PositionState(pos.position_state)

        # Step 1: Increment days_held
        new_days_held = pos.days_held + 1

        # Step 2: Update highest high
        new_highest_high = max(pos.highest_high_since_breakout, today_high_adj)

        # Step 3: Run state machine
        updated = self._evaluate_state_machine(
            pos=pos,
            today_high=today_high_adj,
            atr_14=latest_atr,
            new_days_held=new_days_held,
            new_highest_high=new_highest_high,
        )
        new_state = PositionState(updated["position_state"])
        new_live_stop_loss = updated["live_stop_loss"]

        # Step 4: Earnings alert (independent of state)
        earnings_alert, next_earnings_date = self._check_earnings_alert(
            pos.symbol, eval_date
        )

        # Step 5: Build flags
        flags: list[str] = []
        if new_state != old_state:
            flags.append("STATE_CHANGED")
        if new_live_stop_loss != pos.live_stop_loss:
            flags.append("STOP_UPDATED")
        if earnings_alert:
            flags.append("EARNINGS_ALERT")

        # Step 6: Persist
        pos.days_held = new_days_held
        pos.highest_high_since_breakout = new_highest_high
        pos.position_state = new_state.value
        pos.live_stop_loss = new_live_stop_loss
        pos.earnings_alert = earnings_alert
        pos.next_earnings_date = next_earnings_date
        pos.last_evaluated_date = eval_date
        self._session.flush()

        logger.info(
            "[PositionLifecycle] %s (id=%d): %s → %s | stop=%.2f | flags=%s",
            pos.symbol,
            pos.id,
            old_state.value,
            new_state.value,
            new_live_stop_loss,
            flags,
        )

        return PositionUpdate(
            position_id=position_id,
            symbol=pos.symbol,
            old_state=old_state,
            new_state=new_state,
            new_live_stop_loss=new_live_stop_loss,
            new_days_held=new_days_held,
            new_highest_high=new_highest_high,
            earnings_alert=earnings_alert,
            flags=flags,
        )

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_date: date,
        exit_reason: str,
    ) -> ActivePosition:
        """Mark a position as closed.

        This method removes the row from ``active_positions``.  The caller
        (typically ``AnalyticsLoop.record_closed_trade``) is responsible for
        inserting the corresponding row into ``trade_analytics_log``.

        Parameters
        ----------
        position_id:
            PK of the ``active_positions`` row.
        exit_price:
            Actual exit price.
        exit_date:
            Date the position was closed.
        exit_reason:
            One of ``'MANUAL'``, ``'STOP_HIT'``, ``'TIME_DECAY'``,
            ``'EARNINGS_EXIT'``.

        Returns
        -------
        ActivePosition
            A detached copy of the deleted row (for use by AnalyticsLoop).

        Raises
        ------
        ValueError
            If the position is not found.
        """
        pos: Optional[ActivePosition] = self._session.get(ActivePosition, position_id)
        if pos is None:
            raise ValueError(f"Position ID {position_id} not found.")

        # Detach a copy before deletion so AnalyticsLoop can read its fields
        detached = pos  # SQLAlchemy keeps attributes accessible after expunge
        self._session.delete(pos)
        self._session.flush()
        return detached

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate_state_machine(
        self,
        pos: ActivePosition,
        today_high: float,
        atr_14: float,
        new_days_held: int,
        new_highest_high: float,
    ) -> dict:
        """Apply the position state machine for one session.

        Returns a dict with ``position_state`` and ``live_stop_loss`` keys.

        Priority rule: ``RISK_FREE_1_TO_1`` transition takes precedence
        over ``PENDING_MANUAL_EXIT`` if both conditions are met on the same day.
        """
        state = PositionState(pos.position_state)
        live_stop = pos.live_stop_loss

        # 1R = initial risk per share
        one_r = pos.entry_price - pos.initial_stop_loss

        if state == PositionState.INITIAL_RISK:
            # Check graduation to RISK_FREE_1_TO_1 first (priority)
            if new_highest_high >= pos.entry_price + one_r:
                state = PositionState.RISK_FREE_1_TO_1
                live_stop = pos.entry_price  # Move stop to breakeven
            elif new_days_held >= self._time_decay_sessions:
                # Time-decay: flag for manual exit (no graduation achieved)
                state = PositionState.PENDING_MANUAL_EXIT

        elif state == PositionState.RISK_FREE_1_TO_1:
            # Check transition to trailing ATR stop
            if new_highest_high > pos.initial_resistance_target:
                state = PositionState.TRAILING_ATR
                # Initialise trailing stop
                candidate_stop = new_highest_high - (self._trailing_stop_mult * atr_14)
                live_stop = max(live_stop, candidate_stop)

        elif state == PositionState.TRAILING_ATR:
            # Ratchet trailing stop — only moves UP
            candidate_stop = new_highest_high - (self._trailing_stop_mult * atr_14)
            live_stop = max(live_stop, candidate_stop)

        # PENDING_MANUAL_EXIT: no automated transitions

        return {
            "position_state": state.value,
            "live_stop_loss": live_stop,
        }

    def _check_earnings_alert(
        self, symbol: str, eval_date: date
    ) -> tuple[bool, Optional[date]]:
        """Return (alert_bool, next_earnings_date) for the symbol.

        Checks if any event in ``earnings_calendar`` falls within
        ``earnings_alert_days`` calendar days from ``eval_date``.
        """
        look_ahead = eval_date + timedelta(days=self._earnings_alert_days)
        row = (
            self._session.execute(
                select(EarningsCalendar.event_date)
                .where(EarningsCalendar.symbol == symbol)
                .where(EarningsCalendar.event_date > eval_date)
                .where(EarningsCalendar.event_date <= look_ahead)
                .order_by(EarningsCalendar.event_date)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return False, None
        return True, row

    def _fetch_raw_ohlcv(
        self, symbol: str, eval_date: date, lookback: int
    ) -> pd.DataFrame:
        """Fetch last ``lookback`` bars of raw OHLCV for ``symbol`` up to ``eval_date``."""
        rows = (
            self._session.execute(
                select(
                    MarketDataLake.trade_date,
                    MarketDataLake.open_raw,
                    MarketDataLake.high_raw,
                    MarketDataLake.low_raw,
                    MarketDataLake.close_raw,
                    MarketDataLake.volume_raw,
                )
                .where(MarketDataLake.symbol == symbol)
                .where(MarketDataLake.trade_date <= eval_date)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(lookback)
            )
            .all()
        )
        if not rows:
            return pd.DataFrame()

        rows = list(reversed(rows))
        return pd.DataFrame(
            [
                {
                    "trade_date": r.trade_date,
                    "open_raw": float(r.open_raw),
                    "high_raw": float(r.high_raw),
                    "low_raw": float(r.low_raw),
                    "close_raw": float(r.close_raw),
                    "volume_raw": int(r.volume_raw),
                }
                for r in rows
            ]
        ).set_index("trade_date")

    def _fetch_corporate_actions(self, symbol: str) -> list[dict]:
        """Fetch all corporate actions for ``symbol`` from the DB."""
        rows = (
            self._session.execute(
                select(
                    CorporateActionsLog.ex_date,
                    CorporateActionsLog.action_type,
                    CorporateActionsLog.ratio_numerator,
                    CorporateActionsLog.ratio_denominator,
                )
                .where(CorporateActionsLog.symbol == symbol)
                .order_by(CorporateActionsLog.ex_date)
            )
            .all()
        )
        return [
            {
                "ex_date": r.ex_date,
                "action_type": r.action_type,
                "ratio_numerator": r.ratio_numerator,
                "ratio_denominator": r.ratio_denominator,
            }
            for r in rows
        ]

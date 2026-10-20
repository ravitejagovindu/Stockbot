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
    TradeAnalyticsLog,
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
    PARABOLIC_TRAILING = "PARABOLIC_TRAILING"
    PENDING_MANUAL_EXIT = "PENDING_MANUAL_EXIT"
    CLOSED = "CLOSED"


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
    partial_profit_triggered: bool = False
    shares_to_exit_now: int = 0
    partial_exit_price: float = 0.0
    shares_remaining_after: int = 0


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
        self._trailing_stop_mult_normal: float = float(
            risk.get("trailing_stop_atr_multiplier", 2.5)
        )
        self._trailing_stop_mult_kill_switch: float = float(
            risk.get("trailing_stop_atr_multiplier_kill_switch", 2.0)
        )
        self._trailing_stop_mult: float = self._trailing_stop_mult_normal
        self._time_decay_sessions: int = int(tm["time_decay_sessions"])
        self._earnings_alert_days: int = int(tm["earnings_alert_days"])
        
        parabolic = config.get("parabolic_stop", {})
        self._parabolic_enabled: bool = bool(parabolic.get("enabled", False))
        self._parabolic_thresh: float = float(parabolic.get("acceleration_threshold_atr", 3.0))
        self._parabolic_lookback: int = int(parabolic.get("acceleration_lookback_days", 5))
        self._parabolic_mult: float = float(parabolic.get("parabolic_atr_multiplier", 1.0))

        partial = config.get("partial_profit", {})
        self._partial_enabled: bool = bool(partial.get("enabled", False))
        self._partial_ladder: list = partial.get("exit_ladder", [])

        ratchet = config.get("profit_ratchet", {})
        self._ratchet_enabled: bool = bool(ratchet.get("enabled", False))
        self._ratchet_active_in_bull: bool = bool(ratchet.get("active_in_bull", False))
        self._ratchet_rungs: list = sorted(
            ratchet.get("rungs", []),
            key=lambda x: float(x["trigger_rr"])
        )

        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_all(
        self, eval_date: date, kill_switch_active: Optional[bool] = None
    ) -> list[PositionUpdate]:
        """Process every open position for ``eval_date``.

        Positions are loaded ordered by ``entry_date`` ascending so that
        older positions are processed first (consistent ordering for logs).

        Parameters
        ----------
        eval_date:
            The trading date being processed.
        kill_switch_active:
            Optional boolean indicating if macro kill switch is active today.

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
                update = self.process_single(
                    pos.id, eval_date, kill_switch_active=kill_switch_active
                )
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

    def process_single(
        self, position_id: int, eval_date: date, kill_switch_active: Optional[bool] = None
    ) -> PositionUpdate:
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

        # Today's adjusted prices (for highest-high, stop-loss, and exit tracking)
        today_high_adj = float(adj_ohlcv.loc[eval_date, "high_adj"])
        today_low_adj = float(adj_ohlcv.loc[eval_date, "low_adj"])
        today_close_adj = float(adj_ohlcv.loc[eval_date, "close_adj"])

        old_state = PositionState(pos.position_state)

        # Step 0: Earnings alert (independent of state)
        earnings_alert, next_earnings_date = self._check_earnings_alert(
            pos.symbol, eval_date
        )

        # ── Automated Exit Check: Stop-Loss Hit ───────────────────────────────
        # Assumption of Execution: If today's adjusted low breaches or touches
        # live_stop_loss, the market stop order was triggered. Do not wait for manual UI
        # confirmation — immediately close paper position and archive to analytics.
        if today_low_adj <= pos.live_stop_loss:
            exit_price = pos.live_stop_loss
            shares_to_close = pos.shares_remaining if pos.shares_remaining is not None else pos.shares
            one_r = pos.entry_price - pos.initial_stop_loss
            realized_rr = (exit_price - pos.entry_price) / one_r if one_r > 0 else 0.0
            pnl = (exit_price - pos.entry_price) * shares_to_close
            new_days_held = pos.days_held + 1

            log_entry = TradeAnalyticsLog(
                position_id=pos.id,
                symbol=pos.symbol,
                entry_date=pos.entry_date,
                exit_date=eval_date,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                shares=shares_to_close,
                initial_stop_loss=pos.initial_stop_loss,
                projected_rr=pos.projected_rr,
                realized_rr=realized_rr,
                pnl_gross=pnl,
                exit_reason="STOP_HIT",
                sector=pos.sector,
                days_held=new_days_held,
            )
            self._session.add(log_entry)
            self._session.delete(pos)
            self._session.flush()

            logger.info(
                "[PositionLifecycle] AUTOMATED EXIT (STOP_HIT): %s (id=%d) exited at %.2f | PnL=%.2f | R:R=%.2f",
                pos.symbol,
                pos.id,
                exit_price,
                pnl,
                realized_rr,
            )

            exit_flags = ["AUTOMATED_EXIT_STOP_HIT", "STATE_CHANGED"]
            if earnings_alert:
                exit_flags.append("EARNINGS_ALERT")

            return PositionUpdate(
                position_id=position_id,
                symbol=pos.symbol,
                old_state=old_state,
                new_state=PositionState.CLOSED,
                new_live_stop_loss=pos.live_stop_loss,
                new_days_held=new_days_held,
                new_highest_high=pos.highest_high_since_breakout,
                earnings_alert=earnings_alert,
                flags=exit_flags,
                partial_profit_triggered=False,
                shares_to_exit_now=shares_to_close,
                partial_exit_price=exit_price,
                shares_remaining_after=0,
            )

        # Compute ATR14 on adjusted series
        atr_series = atr(
            adj_ohlcv["high_adj"],
            adj_ohlcv["low_adj"],
            adj_ohlcv["close_adj"],
            period=self._atr_period,
        )
        latest_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0

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
            adj_ohlcv=adj_ohlcv,
            eval_date=eval_date,
            kill_switch_active=kill_switch_active,
        )
        new_state = PositionState(updated["position_state"])
        new_live_stop_loss = updated["live_stop_loss"]

        # ── Automated Exit Check: Time-Decay Reached ──────────────────────────
        # Assumption of Execution: If position reached time decay (or was pending exit)
        # without graduating to 1:1, exit immediately at today's close price.
        # Do not wait for manual UI confirmation.
        if new_state == PositionState.PENDING_MANUAL_EXIT or old_state == PositionState.PENDING_MANUAL_EXIT:
            exit_price = today_close_adj
            shares_to_close = pos.shares_remaining if pos.shares_remaining is not None else pos.shares
            one_r = pos.entry_price - pos.initial_stop_loss
            realized_rr = (exit_price - pos.entry_price) / one_r if one_r > 0 else 0.0
            pnl = (exit_price - pos.entry_price) * shares_to_close

            log_entry = TradeAnalyticsLog(
                position_id=pos.id,
                symbol=pos.symbol,
                entry_date=pos.entry_date,
                exit_date=eval_date,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                shares=shares_to_close,
                initial_stop_loss=pos.initial_stop_loss,
                projected_rr=pos.projected_rr,
                realized_rr=realized_rr,
                pnl_gross=pnl,
                exit_reason="TIME_DECAY",
                sector=pos.sector,
                days_held=new_days_held,
            )
            self._session.add(log_entry)
            self._session.delete(pos)
            self._session.flush()

            logger.info(
                "[PositionLifecycle] AUTOMATED EXIT (TIME_DECAY): %s (id=%d) exited at %.2f | days_held=%d | PnL=%.2f | R:R=%.2f",
                pos.symbol,
                pos.id,
                exit_price,
                new_days_held,
                pnl,
                realized_rr,
            )

            decay_flags = ["AUTOMATED_EXIT_TIME_DECAY", "STATE_CHANGED"]
            if earnings_alert:
                decay_flags.append("EARNINGS_ALERT")

            return PositionUpdate(
                position_id=position_id,
                symbol=pos.symbol,
                old_state=old_state,
                new_state=PositionState.CLOSED,
                new_live_stop_loss=new_live_stop_loss,
                new_days_held=new_days_held,
                new_highest_high=new_highest_high,
                earnings_alert=earnings_alert,
                flags=decay_flags,
                partial_profit_triggered=False,
                shares_to_exit_now=shares_to_close,
                partial_exit_price=exit_price,
                shares_remaining_after=0,
            )
        
        # Step 4: Evaluate partial profits
        partial_res = self._evaluate_partial_profits(pos, today_high_adj)
        
        if partial_res["triggered"]:
            # Automated Assumption of Execution
            shares_sold = partial_res["shares_to_exit"]
            exit_price = partial_res["exit_price"]
            shares_rem = pos.shares_remaining if pos.shares_remaining is not None else pos.shares
            
            pos.shares_remaining = shares_rem - shares_sold
            pos.partial_exit_count += 1
            
            pnl = (exit_price - pos.entry_price) * shares_sold
            pos.total_realized_pnl_partial += pnl
            pos.last_partial_exit_rr = partial_res["last_rr"]
            pos.next_partial_exit_rr = partial_res["next_rr"]
            
            # Log the partial exit to analytics immediately
            one_r = pos.entry_price - pos.initial_stop_loss
            realized_rr = (exit_price - pos.entry_price) / one_r if one_r > 0 else 0
            
            log_entry = TradeAnalyticsLog(
                position_id=pos.id,
                symbol=pos.symbol,
                entry_date=pos.entry_date,
                exit_date=eval_date,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                shares=shares_sold,
                initial_stop_loss=pos.initial_stop_loss,
                projected_rr=pos.projected_rr,
                realized_rr=realized_rr,
                pnl_gross=pnl,
                exit_reason="PARTIAL_PROFIT",
                sector=pos.sector,
                days_held=new_days_held
            )
            self._session.add(log_entry)

        # Step 5: Build flags
        flags: list[str] = []
        if new_state != old_state:
            flags.append("STATE_CHANGED")
        if new_live_stop_loss != pos.live_stop_loss:
            flags.append("STOP_UPDATED")
        if earnings_alert:
            flags.append("EARNINGS_ALERT")
        if partial_res["triggered"]:
            flags.append(f"PARTIAL_PROFIT_EXECUTED_{shares_sold}_SHARES")

        # Step 7: Persist
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
            partial_profit_triggered=partial_res["triggered"],
            shares_to_exit_now=partial_res["shares_to_exit"],
            partial_exit_price=partial_res["exit_price"],
            shares_remaining_after=pos.shares_remaining if pos.shares_remaining is not None else pos.shares
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

    def _is_kill_switch_active(self, eval_date: date) -> bool:
        """Check if macro kill switch was active on or immediately prior to eval_date."""
        if self._session is None:
            return False
        try:
            from data.db.models import RegimeState as DBRegimeState
            row = (
                self._session.execute(
                    select(DBRegimeState.kill_switch_active)
                    .where(DBRegimeState.eval_date <= eval_date)
                    .order_by(DBRegimeState.eval_date.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return bool(row) if row is not None else False
        except Exception:
            return False

    def _is_bull_regime(self, eval_date: date) -> bool:
        """Check if market is in confirmed bull regime (kill switch OFF and Nifty > 200 SMA)."""
        if self._session is None:
            return False
        try:
            from data.db.models import RegimeState as DBRegimeState
            row = (
                self._session.execute(
                    select(
                        DBRegimeState.kill_switch_active,
                        DBRegimeState.nifty_close,
                        DBRegimeState.nifty_sma200,
                    )
                    .where(DBRegimeState.eval_date <= eval_date)
                    .order_by(DBRegimeState.eval_date.desc())
                    .limit(1)
                )
                .first()
            )
            if row and not row.kill_switch_active:
                if row.nifty_close and row.nifty_sma200 and row.nifty_close > row.nifty_sma200:
                    return True
        except Exception:
            return False
        return False

    def _get_trailing_multiplier(
        self, eval_date: Optional[date] = None, kill_switch_active: Optional[bool] = None
    ) -> float:
        """Return the effective trailing ATR multiplier based on macro kill switch state."""
        if kill_switch_active is None and eval_date is not None:
            kill_switch_active = self._is_kill_switch_active(eval_date)

        if kill_switch_active:
            return self._trailing_stop_mult_kill_switch
        return self._trailing_stop_mult_normal

    def _evaluate_state_machine(
        self,
        pos: ActivePosition,
        today_high: float,
        atr_14: float,
        new_days_held: int,
        new_highest_high: float,
        adj_ohlcv: pd.DataFrame,
        eval_date: Optional[date] = None,
        kill_switch_active: Optional[bool] = None,
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

        trail_mult = self._get_trailing_multiplier(
            eval_date=eval_date, kill_switch_active=kill_switch_active
        )

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
                candidate_stop = new_highest_high - (trail_mult * atr_14)
                live_stop = max(live_stop, candidate_stop)

        if state == PositionState.TRAILING_ATR:
            # Check for parabolic acceleration
            if self._check_parabolic_acceleration(adj_ohlcv, atr_14):
                state = PositionState.PARABOLIC_TRAILING
            else:
                # Ratchet standard trailing stop — only moves UP
                candidate_stop = new_highest_high - (trail_mult * atr_14)
                live_stop = max(live_stop, candidate_stop)

        if state == PositionState.PARABOLIC_TRAILING:
            # Ratchet parabolic trailing stop — tighter multiplier
            candidate_stop = new_highest_high - (self._parabolic_mult * atr_14)
            live_stop = max(live_stop, candidate_stop)

        # Apply Step-Lock Profit Ratchet floor across active states
        is_bull = self._is_bull_regime(eval_date) if eval_date is not None else False
        ratchet_active = self._ratchet_enabled and (self._ratchet_active_in_bull or not is_bull)

        if (
            ratchet_active
            and one_r > 0
            and state not in (PositionState.PENDING_MANUAL_EXIT, PositionState.CLOSED)
        ):
            highest_rr = (new_highest_high - pos.entry_price) / one_r
            for rung in self._ratchet_rungs:
                if highest_rr >= float(rung["trigger_rr"]):
                    ratchet_stop = pos.entry_price + (float(rung["lock_rr"]) * one_r)
                    live_stop = max(live_stop, ratchet_stop)

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

    def _check_parabolic_acceleration(self, adj_ohlcv: pd.DataFrame, atr_14: float) -> bool:
        """Check if stock has moved up > threshold ATRs in lookback days."""
        if not self._parabolic_enabled or adj_ohlcv.empty or atr_14 <= 0:
            return False
            
        lookback = min(self._parabolic_lookback, len(adj_ohlcv))
        if lookback < 2:
            return False
            
        # Get the closing price from 'lookback' days ago and today's close
        close_today = float(adj_ohlcv.iloc[-1]["close_adj"])
        close_past = float(adj_ohlcv.iloc[-lookback]["close_adj"])
        
        net_move = close_today - close_past
        
        if net_move >= (self._parabolic_thresh * atr_14):
            return True
        return False

    def _evaluate_partial_profits(self, pos: ActivePosition, today_high_adj: float) -> dict:
        """Check if any partial profit rungs were hit today."""
        res = {
            "triggered": False,
            "shares_to_exit": 0,
            "exit_price": 0.0,
            "next_rr": pos.next_partial_exit_rr,
            "last_rr": pos.last_partial_exit_rr
        }
        
        if not self._partial_enabled or not self._partial_ladder:
            return res
            
        one_r = pos.entry_price - pos.initial_stop_loss
        if one_r <= 0:
            return res
            
        current_rr = (today_high_adj - pos.entry_price) / one_r
        
        # Sort ladder ascending by trigger
        ladder = sorted(self._partial_ladder, key=lambda x: x["rr_trigger"])
        
        last_rr = pos.last_partial_exit_rr or 0.0
        shares_rem = pos.shares_remaining if pos.shares_remaining is not None else pos.shares
        
        for rung in ladder:
            trigger = float(rung["rr_trigger"])
            if trigger > last_rr and current_rr >= trigger:
                # Triggered!
                import math
                exit_pct = float(rung["exit_pct"])
                shares_to_exit = math.floor(shares_rem * (exit_pct / 100.0))
                
                if shares_to_exit > 0:
                    res["triggered"] = True
                    res["shares_to_exit"] = shares_to_exit
                    res["exit_price"] = pos.entry_price + (trigger * one_r) # Exit roughly at the trigger price
                    res["last_rr"] = trigger
                    
                    # find next rr
                    next_rr = None
                    for n_rung in ladder:
                        if float(n_rung["rr_trigger"]) > trigger:
                            next_rr = float(n_rung["rr_trigger"])
                            break
                    res["next_rr"] = next_rr
                    break # Take one partial at a time (highest hit)
                    
        return res

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

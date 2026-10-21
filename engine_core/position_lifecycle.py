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
from sqlalchemy import select, desc, func
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
from engine_core.lifecycle_rules import (
    Bar,
    BarCtx,
    LifecycleRules,
    PosState,
    advance_one_bar,
    parabolic_ref_close,
)
from engine_core.costs import CostModel
from engine_core.mode import current_mode

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
        self._rules = LifecycleRules.from_config(config)
        self._costs = CostModel.from_config(config)
        self._exit_slip = float(config.get("execution", {}).get("exit_slippage_pct", 0.0))
        self._mode = current_mode(config)
        self._earnings_alert_days = int(config.get("trade_management", {}).get("earnings_alert_days", 7))
        self._atr_period = int(config.get("risk", {}).get("atr_period", 14))

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
                select(ActivePosition)
                .where(ActivePosition.mode == self._mode)
                .order_by(ActivePosition.entry_date)
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

        if pos.mode == "LIVE" and pos.pending_close_reason:
            return self._build_update(pos, pos.position_state, flags=[f"ACTION_REQUIRED_{pos.pending_close_reason}"])

        # Compute ATR14 on adjusted series
        atr_series = atr(
            adj_ohlcv["high_adj"],
            adj_ohlcv["low_adj"],
            adj_ohlcv["close_adj"],
            period=self._atr_period,
        )
        atr_14 = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0

        bar = Bar(
            float(adj_ohlcv.loc[eval_date, "open_adj"]),
            float(adj_ohlcv.loc[eval_date, "high_adj"]),
            float(adj_ohlcv.loc[eval_date, "low_adj"]),
            float(adj_ohlcv.loc[eval_date, "close_adj"]),
        )
        ks = kill_switch_active if kill_switch_active is not None else self._is_kill_switch_active(eval_date)
        ctx = BarCtx(
            atr14=float(atr_14),
            kill_switch=bool(ks),
            is_bull=self._is_bull_regime(eval_date),
            close_n_ago=parabolic_ref_close(list(adj_ohlcv["close_adj"]), self._rules.parabolic_lookback),
        )
        state = PosState(
            entry_price=pos.entry_price,
            initial_stop=pos.initial_stop_loss,
            live_stop=pos.live_stop_loss,
            target=pos.initial_resistance_target,
            state=pos.position_state,
            days_held=pos.days_held,
            highest_high=pos.highest_high_since_breakout,
            shares_remaining=pos.shares_remaining if pos.shares_remaining is not None else pos.shares,
            last_partial_rr=pos.last_partial_exit_rr or 0.0,
            partial_count=pos.partial_exit_count or 0,
        )
        res = advance_one_bar(state, bar, ctx, self._rules, exit_slippage_pct=self._exit_slip)
        new, flags = res.pos, list(res.flags)
        earnings_alert, next_earnings = self._check_earnings_alert(pos.symbol, eval_date)
        old_state = pos.position_state

        pos.position_state = new.state
        pos.live_stop_loss = new.live_stop
        pos.days_held = new.days_held
        pos.highest_high_since_breakout = new.highest_high
        pos.last_partial_exit_rr = new.last_partial_rr or None
        pos.partial_exit_count = new.partial_count
        pos.earnings_alert = earnings_alert
        pos.next_earnings_date = next_earnings
        pos.last_evaluated_date = eval_date

        if earnings_alert:
            flags.append("EARNINGS_ALERT")
        if new.state != old_state:
            flags.append("STATE_CHANGED")
        if new.live_stop != pos.live_stop_loss:
            flags.append("STOP_UPDATED")

        if pos.mode == "PAPER":
            for i, ex in enumerate(res.exits):
                self._log_exit(pos, ex, eval_date, new.days_held, final=(res.closed and i == len(res.exits) - 1))
                if ex.reason == "PARTIAL_PROFIT":
                    pos.shares_remaining = new.shares_remaining
                    pos.total_realized_pnl_partial = (pos.total_realized_pnl_partial or 0.0) + (ex.price - pos.entry_price) * ex.shares
            if res.closed:
                pos.position_state = "CLOSED"
                if "STATE_CHANGED" not in flags:
                    flags.append("STATE_CHANGED")
            update = self._build_update(pos, old_state, flags=flags + (["POSITION_CLOSED"] if res.closed else []))
            if res.closed:
                self._session.delete(pos)
            self._session.flush()
            return update

        # LIVE: advisory only. Never auto-delete, never change share counts.
        for ex in res.exits:
            if ex.reason == "PARTIAL_PROFIT":
                flags.append(f"BOOK_PARTIAL_{ex.shares}_SHARES_NEAR_{ex.price:.2f}")
        if res.closed:
            pos.pending_close_reason = res.exits[-1].reason
            flags.append(f"ACTION_REQUIRED_{res.exits[-1].reason}")
        self._session.flush()
        return self._build_update(pos, old_state, flags=flags)


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

    def _build_update(
        self,
        pos: ActivePosition,
        old_state: str,
        flags: list[str],
    ) -> PositionUpdate:
        return PositionUpdate(
            position_id=pos.id,
            symbol=pos.symbol,
            old_state=PositionState(old_state),
            new_state=PositionState(pos.position_state),
            new_live_stop_loss=pos.live_stop_loss,
            new_days_held=pos.days_held,
            new_highest_high=pos.highest_high_since_breakout,
            earnings_alert=bool(pos.earnings_alert),
            flags=flags,
            shares_remaining_after=pos.shares_remaining if pos.shares_remaining is not None else pos.shares,
        )

    def _log_exit(self, pos: ActivePosition, ex, eval_date: date, days_held: int, final: bool) -> None:
        one_r = pos.entry_price - pos.initial_stop_loss
        gross = (ex.price - pos.entry_price) * ex.shares
        orig = pos.original_shares or pos.shares
        costs = self._costs.sell_cost(ex.price * ex.shares) + (pos.entry_costs or 0.0) * (ex.shares / orig)
        net, tax = gross - costs, 0.0
        if final:
            prior = self._session.execute(
                select(func.coalesce(func.sum(TradeAnalyticsLog.pnl_net), 0.0))
                .where(TradeAnalyticsLog.position_id == pos.id)
            ).scalar() or 0.0
            tax = self._costs.tax_on_gain(prior + net)
        self._session.add(
            TradeAnalyticsLog(
                position_id=pos.id,
                symbol=pos.symbol,
                entry_date=pos.entry_date,
                exit_date=eval_date,
                entry_price=pos.entry_price,
                exit_price=ex.price,
                shares=ex.shares,
                initial_stop_loss=pos.initial_stop_loss,
                projected_rr=pos.projected_rr,
                realized_rr=(ex.price - pos.entry_price) / one_r if one_r > 0 else 0.0,
                pnl_gross=gross,
                exit_reason=ex.reason,
                sector=pos.sector,
                days_held=days_held,
                mode=pos.mode,
                costs_total=costs,
                pnl_net=net,
                tax_est=tax,
                is_partial=(ex.reason == "PARTIAL_PROFIT"),
            )
        )

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

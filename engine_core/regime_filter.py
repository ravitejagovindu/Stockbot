"""
FInsight Trading Engine — Macro Regime Filter
==============================================
The RegimeFilter is the *first* module called in every EOD pipeline run.
It acts as a **kill switch**: when macroeconomic conditions deteriorate, no
new trade setups are generated (existing positions are still managed).

Kill Switch Logic
-----------------
**TRIGGER** (OR — either condition activates the kill switch):

* Nifty 50 close < 200-day SMA  → trend is broken
* India VIX close > 20.0        → fear / volatility spike

**RE-ENTRY** (AND + Hysteresis — both must hold for 3 consecutive sessions):

* Nifty 50 close > 50-day SMA
* India VIX close < 18.0

The hysteresis counter resets to zero the moment either condition is missed
on any session.  This prevents premature re-entry during choppy recoveries.

Persistence
-----------
The regime state is persisted to the ``regime_state`` table after every
evaluation.  This allows the hysteresis counter to survive process restarts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from data.db.models import (
    MarketDataLake,
    RegimeState as RegimeStateModel,
)
from engine_core.indicators import sma

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public dataclass — returned by evaluate() and get_current_state()
# ---------------------------------------------------------------------------

@dataclass
class RegimeState:
    """Snapshot of macro regime conditions for a specific evaluation date.

    Attributes
    ----------
    kill_switch_active:
        ``True`` when the kill switch is engaged (no new setups generated).
    nifty_close:
        Nifty 50 closing price on ``eval_date``.
    nifty_sma200:
        200-day SMA of Nifty 50 on ``eval_date``.
    nifty_sma50:
        50-day SMA of Nifty 50 on ``eval_date``.
    vix_close:
        India VIX closing value on ``eval_date``.
    reentry_consecutive_count:
        Number of consecutive qualifying re-entry sessions accumulated so far
        while the kill switch is active.  Resets to 0 on any miss.
    eval_date:
        The trading date this state was evaluated for.
    trigger_reason:
        Short description of what triggered the kill switch (or ``None`` if
        the kill switch is currently inactive / was deactivated this session).
    """

    kill_switch_active: bool
    nifty_close: Optional[float]
    nifty_sma200: Optional[float]
    nifty_sma50: Optional[float]
    vix_close: Optional[float]
    reentry_consecutive_count: int
    eval_date: date
    trigger_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# RegimeFilter class
# ---------------------------------------------------------------------------

class RegimeFilter:
    """Stateful macro regime evaluator with hysteresis-based re-entry.

    Parameters
    ----------
    config:
        The ``macro`` sub-dict from ``strategy_config.yaml``.  Expected keys:

        * ``nifty_kill_sma_period`` (int) — SMA period for kill-switch trigger
        * ``vix_kill_threshold`` (float)
        * ``nifty_reentry_sma_period`` (int)
        * ``vix_reentry_threshold`` (float)
        * ``reentry_consecutive_sessions`` (int)

        Also reads from ``data`` sub-dict:

        * ``nifty_symbol`` (str)
        * ``vix_symbol`` (str)

    session:
        Active SQLAlchemy session.  The regime filter reads from
        ``market_data_lake`` and writes to ``regime_state``.
    """

    def __init__(self, config: dict, session: Session) -> None:
        """Initialise with strategy config and an active DB session."""
        macro = config["macro"]
        data_cfg = config.get("data", {})

        # Thresholds
        self._kill_sma_period: int = int(macro["nifty_kill_sma_period"])
        self._vix_kill_threshold: float = float(macro["vix_kill_threshold"])
        self._reentry_sma_period: int = int(macro["nifty_reentry_sma_period"])
        self._vix_reentry_threshold: float = float(macro["vix_reentry_threshold"])
        self._reentry_sessions: int = int(macro["reentry_consecutive_sessions"])

        # Market data symbols (configurable in case NSE changes ticker names)
        self._nifty_symbol: str = data_cfg.get("nifty_symbol", "NIFTY50_INDEX")
        self._vix_symbol: str = data_cfg.get("vix_symbol", "INDIA_VIX")

        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, eval_date: date) -> RegimeState:
        """Evaluate macro regime for ``eval_date`` and persist to DB.

        Steps
        -----
        1. Fetch Nifty 50 close history (enough for 200-day SMA).
        2. Fetch India VIX close for ``eval_date``.
        3. Compute SMA200 and SMA50.
        4. Apply kill-switch trigger / re-entry / hysteresis logic.
        5. Upsert result into ``regime_state`` table.
        6. Return :class:`RegimeState` dataclass.

        Parameters
        ----------
        eval_date:
            The trading date to evaluate.  Must have data present in
            ``market_data_lake`` for ``NIFTY50_INDEX`` and ``INDIA_VIX``.

        Returns
        -------
        RegimeState
            Computed regime state for ``eval_date``.

        Raises
        ------
        RuntimeError
            If Nifty or VIX data is not available for ``eval_date`` in the
            data lake.
        """
        # Step 1 & 2: Fetch raw market data
        nifty_series = self._fetch_closes(self._nifty_symbol, eval_date, lookback=210)
        vix_series = self._fetch_closes(self._vix_symbol, eval_date, lookback=1)

        if nifty_series.empty:
            raise RuntimeError(
                f"No Nifty data available on or before {eval_date} in market_data_lake."
            )
        if vix_series.empty:
            raise RuntimeError(
                f"No VIX data available on or before {eval_date} in market_data_lake."
            )

        nifty_close = float(nifty_series.iloc[-1])
        vix_close = float(vix_series.iloc[-1])

        # Step 3: Compute SMAs
        nifty_sma200_series = sma(nifty_series, self._kill_sma_period)
        nifty_sma50_series = sma(nifty_series, self._reentry_sma_period)

        nifty_sma200 = (
            float(nifty_sma200_series.iloc[-1])
            if not pd.isna(nifty_sma200_series.iloc[-1])
            else None
        )
        nifty_sma50 = (
            float(nifty_sma50_series.iloc[-1])
            if not pd.isna(nifty_sma50_series.iloc[-1])
            else None
        )

        # Step 4: Apply state machine logic
        prev_state = self._load_previous_state(before_date=eval_date)
        new_state = self._apply_logic(
            prev_state=prev_state,
            nifty_close=nifty_close,
            nifty_sma200=nifty_sma200,
            nifty_sma50=nifty_sma50,
            vix_close=vix_close,
            eval_date=eval_date,
        )

        # Step 5: Persist
        self._persist(new_state)
        return new_state

    def get_current_state(self) -> Optional[RegimeState]:
        """Return the most recent regime state from the DB without re-evaluating.

        Returns
        -------
        RegimeState or None
            The latest persisted state, or ``None`` if no state has been
            evaluated yet.
        """
        row = (
            self._session.execute(
                select(RegimeStateModel).order_by(desc(RegimeStateModel.eval_date)).limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            return None
        return self._row_to_dataclass(row)

    def get_hysteresis_status(self) -> dict:
        """Return how many of the required consecutive re-entry sessions have been met.

        Returns
        -------
        dict
            ``{'current_count': int, 'required': int, 'pct_complete': float}``
        """
        state = self.get_current_state()
        count = state.reentry_consecutive_count if state else 0
        required = self._reentry_sessions
        return {
            "current_count": count,
            "required": required,
            "pct_complete": round(count / required * 100, 1) if required else 0.0,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_closes(self, symbol: str, as_of: date, lookback: int) -> pd.Series:
        """Fetch the last ``lookback`` close prices for ``symbol`` up to ``as_of``.

        Returns a pandas Series indexed by trade_date (ascending).
        """
        rows = (
            self._session.execute(
                select(MarketDataLake.trade_date, MarketDataLake.close_raw)
                .where(MarketDataLake.symbol == symbol)
                .where(MarketDataLake.trade_date <= as_of)
                .order_by(desc(MarketDataLake.trade_date))
                .limit(lookback)
            )
            .all()
        )
        if not rows:
            return pd.Series(dtype=float)

        # Results arrive newest-first; reverse for chronological order
        rows = list(reversed(rows))
        return pd.Series(
            [float(r.close_raw) for r in rows],
            index=[r.trade_date for r in rows],
            name=symbol,
        )

    def _load_previous_state(self, before_date: Optional[date] = None) -> Optional[RegimeStateModel]:
        """Load the most recent row from ``regime_state`` table on or before `before_date` (exclusive)."""
        q = select(RegimeStateModel)
        if before_date is not None:
            q = q.where(RegimeStateModel.eval_date < before_date)
        return (
            self._session.execute(
                q.order_by(desc(RegimeStateModel.eval_date)).limit(1)
            )
            .scalars()
            .first()
        )

    def _apply_logic(
        self,
        prev_state: Optional[RegimeStateModel],
        nifty_close: float,
        nifty_sma200: Optional[float],
        nifty_sma50: Optional[float],
        vix_close: float,
        eval_date: date,
    ) -> RegimeState:
        """Core kill-switch / re-entry state machine.

        Parameters
        ----------
        prev_state:
            Last persisted regime row, or ``None`` on first run.
        nifty_close, nifty_sma200, nifty_sma50, vix_close:
            Current session values.
        eval_date:
            Date being evaluated.

        Returns
        -------
        RegimeState
            Computed state for ``eval_date``.
        """
        # Bootstrap: first ever run — assume inactive
        if prev_state is None:
            prev_active = False
            prev_count = 0
        else:
            prev_active = bool(prev_state.kill_switch_active)
            prev_count = int(prev_state.reentry_consecutive_count)

        kill_switch_active = prev_active
        reentry_count = prev_count
        trigger_reason: Optional[str] = None

        if not prev_active:
            # ---- Kill-switch INACTIVE: check trigger conditions (OR) ----
            trigger_nifty = (
                nifty_sma200 is not None and nifty_close < nifty_sma200
            )
            trigger_vix = vix_close > self._vix_kill_threshold

            if trigger_nifty or trigger_vix:
                kill_switch_active = True
                reentry_count = 0  # Reset counter on activation
                reasons = []
                if trigger_nifty:
                    reasons.append(
                        f"NIFTY({nifty_close:.2f})<SMA{self._kill_sma_period}"
                        f"({nifty_sma200:.2f})"
                    )
                if trigger_vix:
                    reasons.append(
                        f"VIX({vix_close:.2f})>{self._vix_kill_threshold}"
                    )
                trigger_reason = "|".join(reasons)
                logger.warning(
                    "[RegimeFilter] Kill switch ACTIVATED on %s: %s",
                    eval_date,
                    trigger_reason,
                )

        else:
            # ---- Kill-switch ACTIVE: check re-entry conditions (AND) ----
            reentry_nifty = (
                nifty_sma50 is not None and nifty_close > nifty_sma50
            )
            reentry_vix = vix_close < self._vix_reentry_threshold

            if reentry_nifty and reentry_vix:
                # Both conditions met — increment hysteresis counter
                reentry_count = prev_count + 1
                logger.info(
                    "[RegimeFilter] Re-entry progress on %s: %d/%d sessions met.",
                    eval_date,
                    reentry_count,
                    self._reentry_sessions,
                )
                if reentry_count >= self._reentry_sessions:
                    # Hysteresis threshold reached — deactivate kill switch
                    kill_switch_active = False
                    trigger_reason = None
                    logger.info(
                        "[RegimeFilter] Kill switch DEACTIVATED on %s after "
                        "%d consecutive qualifying sessions.",
                        eval_date,
                        reentry_count,
                    )
            else:
                # Condition not met — reset counter
                if reentry_count > 0:
                    logger.info(
                        "[RegimeFilter] Re-entry counter RESET on %s "
                        "(reentry_nifty=%s, reentry_vix=%s).",
                        eval_date,
                        reentry_nifty,
                        reentry_vix,
                    )
                reentry_count = 0

        return RegimeState(
            kill_switch_active=kill_switch_active,
            nifty_close=nifty_close,
            nifty_sma200=nifty_sma200,
            nifty_sma50=nifty_sma50,
            vix_close=vix_close,
            reentry_consecutive_count=reentry_count,
            eval_date=eval_date,
            trigger_reason=trigger_reason,
        )

    def _persist(self, state: RegimeState) -> None:
        """Upsert the computed state into ``regime_state`` (one row per date)."""
        existing = (
            self._session.execute(
                select(RegimeStateModel).where(
                    RegimeStateModel.eval_date == state.eval_date
                )
            )
            .scalars()
            .first()
        )

        if existing:
            # Update in place (idempotent re-run support)
            existing.kill_switch_active = state.kill_switch_active
            existing.nifty_close = state.nifty_close
            existing.nifty_sma200 = state.nifty_sma200
            existing.nifty_sma50 = state.nifty_sma50
            existing.vix_close = state.vix_close
            existing.reentry_consecutive_count = state.reentry_consecutive_count
            existing.trigger_reason = state.trigger_reason
        else:
            new_row = RegimeStateModel(
                eval_date=state.eval_date,
                kill_switch_active=state.kill_switch_active,
                nifty_close=state.nifty_close,
                nifty_sma200=state.nifty_sma200,
                nifty_sma50=state.nifty_sma50,
                vix_close=state.vix_close,
                reentry_consecutive_count=state.reentry_consecutive_count,
                trigger_reason=state.trigger_reason,
            )
            self._session.add(new_row)

        self._session.flush()

    @staticmethod
    def _row_to_dataclass(row: RegimeStateModel) -> RegimeState:
        """Convert an ORM row to a :class:`RegimeState` dataclass."""
        return RegimeState(
            kill_switch_active=bool(row.kill_switch_active),
            nifty_close=row.nifty_close,
            nifty_sma200=row.nifty_sma200,
            nifty_sma50=row.nifty_sma50,
            vix_close=row.vix_close,
            reentry_consecutive_count=int(row.reentry_consecutive_count),
            eval_date=row.eval_date,
            trigger_reason=getattr(row, "trigger_reason", None),
        )

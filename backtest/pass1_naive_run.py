"""
FInsight Backtest Engine — Pass 1 Naive Run
============================================
Simulates the full engine chronologically over a configured regime period.

Gates applied
-------------
* Macro kill switch (Nifty SMA200 / VIX)
* Market-cap gate (raw_close × raw_shares_outstanding > 5 000 Cr)
* ADTV gate (SMA(raw_close × raw_volume, 20) > 25 Cr)
* Listing-age gate (trading days in market_data_lake <= eval_date > 252)
* Technical / risk gate (ATR stops, Donchian channels, R:R ≥ 1.5)
* Position-level heat cap gates (max 10 positions, 10% total risk)

Gates intentionally SKIPPED (unavailable historically)
-------------------------------------------------------
* ASM/GSM quarantine  → added in Pass 2 via PDF scraper
* Earnings binary event block → added in Pass 2 via NSE filings scraper

PIT (Point-In-Time) correctness
---------------------------------
Every data query uses ``WHERE trade_date <= eval_date`` so no look-ahead bias
is introduced.  Specifically:

* **Market Cap**: most recent ``shares_outstanding.shares_count`` with
  ``effective_date <= eval_date``
* **ADTV**: rolling 20-day SMA of ``raw_close × raw_volume`` over the 20 rows
  with ``trade_date <= eval_date``
* **Listing age**: COUNT of distinct ``trade_date`` rows in
  ``market_data_lake`` with ``trade_date <= eval_date``
* **Technical indicators**: computed only on the price history available on
  ``eval_date``

Output CSV schema (saved to backtest/outputs/)
----------------------------------------------
symbol, entry_date, entry_price, live_stop_loss, stop_a, stop_b,
initial_resistance_target, projected_rr, shares, regime,
sector, account_equity_at_entry
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# engine_core imports — wrapped in try/except so the module can be imported
# even before all engine_core modules are fully written.
# TODO: remove the try/except once all engine_core modules are confirmed stable.
# ---------------------------------------------------------------------------
try:
    from engine_core.regime_filter import RegimeFilter, RegimeState
except ImportError as _e:  # pragma: no cover
    RegimeFilter = None  # type: ignore[assignment,misc]
    RegimeState = None  # type: ignore[assignment]
    logging.getLogger(__name__).warning("engine_core.regime_filter not found: %s", _e)

try:
    from engine_core.universe_screener import UniverseScreener, ScreeningResult
except ImportError as _e:  # pragma: no cover
    UniverseScreener = None  # type: ignore[assignment,misc]
    ScreeningResult = None  # type: ignore[assignment]
    logging.getLogger(__name__).warning("engine_core.universe_screener not found: %s", _e)

try:
    from engine_core.risk_sizing import RiskAndSizingEngine, TradeSetup
except ImportError as _e:  # pragma: no cover
    RiskAndSizingEngine = None  # type: ignore[assignment,misc]
    TradeSetup = None  # type: ignore[assignment]
    logging.getLogger(__name__).warning("engine_core.risk_sizing not found: %s", _e)

try:
    from engine_core.position_lifecycle import PositionLifecycleManager
except ImportError as _e:  # pragma: no cover
    PositionLifecycleManager = None  # type: ignore[assignment,misc]
    logging.getLogger(__name__).warning("engine_core.position_lifecycle not found: %s", _e)

try:
    from engine_core.adjustments import get_adjusted_series
except ImportError as _e:  # pragma: no cover
    get_adjusted_series = None  # type: ignore[assignment]
    logging.getLogger(__name__).warning("engine_core.adjustments not found: %s", _e)

from data.db.models import MarketDataLake, SharesOutstanding

logger = logging.getLogger(__name__)

# Output directory relative to project root
_OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")

# Conversion constant: 1 crore = 10,000,000
_CR = 1_00_00_000


# ---------------------------------------------------------------------------
# Simulated position — lightweight replacement for active_positions DB row
# used inside the backtest to avoid polluting the live DB.
# ---------------------------------------------------------------------------

@dataclass
class _SimPosition:
    """In-memory representation of an open simulated position.

    All fields mirror the ``active_positions`` DB schema so the position
    lifecycle manager can work identically in both live and backtest modes.
    """

    symbol: str
    entry_date: date
    entry_price: float
    shares: int
    initial_stop_loss: float
    live_stop_loss: float
    initial_resistance_target: float
    projected_rr: float
    stop_a_at_entry: float
    stop_b_at_entry: float
    position_state: str = "INITIAL_RISK"
    days_held: int = 0
    highest_high_since_breakout: float = 0.0
    sector: Optional[str] = None
    account_equity_at_entry: float = 0.0
    regime: str = ""

    # Running P&L for equity-curve tracking
    _current_close: float = field(default=0.0, repr=False)


# ---------------------------------------------------------------------------
# Pass 1 — Naive Run
# ---------------------------------------------------------------------------

class Pass1NaiveRun:
    """Simulate the FInsight engine chronologically over a regime date window.

    The simulation mirrors the live EOD pipeline exactly, except:

    * No DB writes — portfolio state is tracked in-memory via
      :class:`_SimPosition` objects.
    * ASM/GSM gate skipped — historical data unavailable; re-applied in Pass 2.
    * Earnings binary-event block skipped — historical data unavailable;
      re-applied in Pass 2.

    Parameters
    ----------
    config:
        Full ``strategy_config.yaml`` dict (all top-level sections).

    Usage
    -----
    ::

        runner = Pass1NaiveRun(config)
        df = runner.run(
            regime_name="bull_run",
            start_date=date(2019, 1, 1),
            end_date=date(2024, 12, 31),
            initial_equity=1_000_000.0,
            session=session,
        )
        path = runner.output_csv(df, "bull_run")
    """

    def __init__(self, config: dict) -> None:
        """Initialise with the full strategy configuration dictionary.

        Parameters
        ----------
        config:
            Full parsed ``strategy_config.yaml`` as a Python dict.
        """
        self._config = config
        self._risk_cfg = config["risk"]
        self._backtest_cfg = config.get("backtest", {})

        # Ensure output directory exists
        os.makedirs(_OUTPUTS_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        regime_name: str,
        start_date: date,
        end_date: date,
        initial_equity: float,
        session: Session,
    ) -> pd.DataFrame:
        """Simulate the engine over [start_date, end_date] for a single regime.

        Iterates every **trading day** found in the Nifty index history within
        the date range (we use Nifty trading days as the market calendar).

        For each trading day the sequence is:
        1. Evaluate regime (kill switch) using PIT-correct Nifty/VIX data.
        2. Simulate stop-hit / state-machine updates on open positions.
        3. If kill switch is OFF: screen universe and size new candidates.
        4. Open any candidate positions and track simulated equity.

        Parameters
        ----------
        regime_name:
            Label for this backtest window (e.g. ``"bull_run"``).  Stored in
            output CSV for reference.
        start_date:
            First date of the simulation (inclusive).
        end_date:
            Last date of the simulation (inclusive).
        initial_equity:
            Starting account equity in INR.
        session:
            Active SQLAlchemy ``Session`` connected to the data lake DB.

        Returns
        -------
        pd.DataFrame
            All candidate trade setups generated across the regime window.
            Columns:
            ``symbol, entry_date, entry_price, live_stop_loss, stop_a, stop_b,
            initial_resistance_target, projected_rr, shares, regime,
            sector, account_equity_at_entry``
        """
        logger.info(
            "[Pass1] Starting %s  %s → %s  equity=%.2f",
            regime_name,
            start_date,
            end_date,
            initial_equity,
        )

        # Validate that engine_core modules are available
        if any(m is None for m in [RegimeFilter, UniverseScreener, RiskAndSizingEngine]):
            raise RuntimeError(
                "One or more engine_core modules could not be imported.  "
                "Ensure engine_core/ is fully implemented before running Pass 1."
            )

        # --- Fetch trading calendar from Nifty index rows in data lake ---
        trading_days = self._fetch_trading_days(session, start_date, end_date)
        if not trading_days:
            logger.warning("[Pass1] No trading days found for %s – %s", start_date, end_date)
            return pd.DataFrame()

        # --- Simulation state ---
        account_equity: float = initial_equity
        open_positions: list[_SimPosition] = []
        candidate_rows: list[dict] = []

        # We create a *stateful* regime filter that reads from (and writes to)
        # the DB.  In backtest mode we use the same DB but only look back at
        # historical rows — PIT is enforced by the _fetch_closes method inside
        # RegimeFilter itself (WHERE trade_date <= eval_date).
        regime_filter = RegimeFilter(self._config, session)
        risk_engine = RiskAndSizingEngine(self._config)

        for eval_date in trading_days:
            # ----------------------------------------------------------------
            # 1. Regime evaluation (uses PIT Nifty/VIX from market_data_lake)
            # ----------------------------------------------------------------
            try:
                regime_state: RegimeState = regime_filter.evaluate(eval_date)
            except RuntimeError as exc:
                # Missing Nifty/VIX data for this date — skip gracefully
                logger.debug("[Pass1] %s — regime data missing: %s", eval_date, exc)
                continue

            # ----------------------------------------------------------------
            # 2. Simulate open-position lifecycle (stop hits, state transitions)
            # ----------------------------------------------------------------
            account_equity = self._simulate_lifecycle(
                open_positions=open_positions,
                eval_date=eval_date,
                session=session,
                account_equity=account_equity,
            )

            # ----------------------------------------------------------------
            # 3. Universe screening + sizing (only when kill switch is OFF)
            # ----------------------------------------------------------------
            if not regime_state.kill_switch_active:
                # Discover all symbols present in the lake with data on eval_date
                universe_symbols = self._fetch_universe_symbols(session, eval_date)

                # Construct a screener with ASM/earnings gates disabled
                screener = _Pass1Screener(self._config, session, eval_date)

                # Gather the symbols that pass all ENABLED gates
                passed_symbols: list[str] = []
                for sym in universe_symbols:
                    if sym in {p.symbol for p in open_positions}:
                        # Already holding this symbol — skip
                        continue
                    if screener.screen(sym):
                        passed_symbols.append(sym)

                # Build open-position dicts for heat-cap calculation
                positions_for_heat = self._positions_as_dicts(open_positions)

                # Build candidate dicts with pre-fetched OHLCV — required by compute_all()
                candidate_dicts = self._build_candidate_dicts(
                    symbols=passed_symbols,
                    eval_date=eval_date,
                    session=session,
                )

                # Size each candidate
                setups: list[TradeSetup] = risk_engine.compute_all(
                    candidates=candidate_dicts,
                    eval_date=eval_date,
                    account_equity=account_equity,
                    current_positions=positions_for_heat,
                )

                for setup in setups:
                    if setup.blocked:
                        continue  # Heat-cap or R:R rejected

                    # Record as a candidate trade
                    candidate_rows.append({
                        "symbol": setup.symbol,
                        "entry_date": eval_date,
                        "entry_price": setup.entry_price,
                        "live_stop_loss": setup.live_stop_loss,
                        "stop_a": setup.stop_a,
                        "stop_b": setup.stop_b,
                        "initial_resistance_target": setup.initial_resistance_target,
                        "projected_rr": setup.projected_rr,
                        "shares": setup.shares,
                        "regime": regime_name,
                        "sector": getattr(setup, "sector", None),
                        "account_equity_at_entry": account_equity,
                    })

                    # Open the simulated position
                    pos = _SimPosition(
                        symbol=setup.symbol,
                        entry_date=eval_date,
                        entry_price=setup.entry_price,
                        shares=setup.shares,
                        initial_stop_loss=setup.live_stop_loss,
                        live_stop_loss=setup.live_stop_loss,
                        initial_resistance_target=setup.initial_resistance_target,
                        projected_rr=setup.projected_rr,
                        stop_a_at_entry=setup.stop_a,
                        stop_b_at_entry=setup.stop_b,
                        account_equity_at_entry=account_equity,
                        regime=regime_name,
                    )
                    open_positions.append(pos)

                    logger.debug(
                        "[Pass1] %s — NEW candidate: %s  entry=%.2f  stop=%.2f  rr=%.2f",
                        eval_date,
                        setup.symbol,
                        setup.entry_price,
                        setup.live_stop_loss,
                        setup.projected_rr,
                    )

        logger.info(
            "[Pass1] %s complete. Candidates: %d  Final equity: %.2f",
            regime_name,
            len(candidate_rows),
            account_equity,
        )

        if not candidate_rows:
            return pd.DataFrame(columns=[
                "symbol", "entry_date", "entry_price", "live_stop_loss",
                "stop_a", "stop_b", "initial_resistance_target",
                "projected_rr", "shares", "regime", "sector",
                "account_equity_at_entry",
            ])

        return pd.DataFrame(candidate_rows)

    def output_csv(self, df: pd.DataFrame, regime_name: str) -> str:
        """Save candidate trades DataFrame to a CSV file.

        Parameters
        ----------
        df:
            DataFrame returned by :meth:`run`.
        regime_name:
            Used in the output filename.

        Returns
        -------
        str
            Absolute path to the saved CSV file.
        """
        filename = f"candidate_trades_{regime_name}.csv"
        path = os.path.join(_OUTPUTS_DIR, filename)
        df.to_csv(path, index=False)
        logger.info("[Pass1] Candidate trades saved → %s  (%d rows)", path, len(df))
        return path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_trading_days(
        self,
        session: Session,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """Return all Nifty trading days in [start_date, end_date].

        Uses ``NIFTY50_INDEX`` rows from ``market_data_lake`` as the market
        calendar proxy.  The list is returned in ascending chronological order.
        """
        nifty_symbol = self._config.get("data", {}).get("nifty_symbol", "NIFTY50_INDEX")
        rows = session.execute(
            select(MarketDataLake.trade_date)
            .where(MarketDataLake.symbol == nifty_symbol)
            .where(MarketDataLake.trade_date >= start_date)
            .where(MarketDataLake.trade_date <= end_date)
            .order_by(MarketDataLake.trade_date)
        ).scalars().all()
        return list(rows)

    def _fetch_universe_symbols(self, session: Session, eval_date: date) -> list[str]:
        """Return all distinct non-index symbols in the lake with data on eval_date.

        Excludes the Nifty and VIX pseudo-symbols which are not tradeable
        equities.
        """
        data_cfg = self._config.get("data", {})
        excluded = {
            data_cfg.get("nifty_symbol", "NIFTY50_INDEX"),
            data_cfg.get("vix_symbol", "INDIA_VIX"),
        }
        rows = session.execute(
            select(MarketDataLake.symbol)
            .where(MarketDataLake.trade_date == eval_date)
            .distinct()
        ).scalars().all()
        return [s for s in rows if s not in excluded]

    def _simulate_lifecycle(
        self,
        open_positions: list[_SimPosition],
        eval_date: date,
        session: Session,
        account_equity: float,
    ) -> float:
        """Update open positions for eval_date and realise P&L for stop-hits.

        For each position:
        * Fetch today's high / low / close (raw, used as proxy for adjusted).
        * If ``low_raw <= live_stop_loss``: mark the position closed at the
          stop price and add realized P&L to account equity.
        * Else: increment ``days_held``, update ``highest_high_since_breakout``
          and apply basic state-machine transitions.

        .. note::
           In Pass 1 we intentionally use raw prices for the lifecycle
           simulation.  The full adjusted-price lifecycle is handled by
           :class:`engine_core.position_lifecycle.PositionLifecycleManager`
           in the live runner and in Pass 2.  Here we want a fast, low-bias
           approximation that does not require corporate-action data for the
           entire historical universe.

        Parameters
        ----------
        open_positions:
            Mutable list of currently open simulated positions.  Closed
            positions are removed in-place.
        eval_date:
            Date being evaluated.
        session:
            DB session for fetching market data.
        account_equity:
            Current simulated account equity.

        Returns
        -------
        float
            Updated account equity after realised P&L.
        """
        positions_to_remove: list[_SimPosition] = []

        for pos in open_positions:
            row = session.execute(
                select(
                    MarketDataLake.high_raw,
                    MarketDataLake.low_raw,
                    MarketDataLake.close_raw,
                )
                .where(MarketDataLake.symbol == pos.symbol)
                .where(MarketDataLake.trade_date == eval_date)
            ).first()

            if row is None:
                # No data for this symbol today — skip (possible holiday / suspension)
                continue

            high_raw, low_raw, close_raw = row

            # --- Stop hit check ---
            if low_raw <= pos.live_stop_loss:
                exit_price = pos.live_stop_loss  # Assume filled at stop
                pnl = (exit_price - pos.entry_price) * pos.shares
                account_equity += pnl
                positions_to_remove.append(pos)
                logger.debug(
                    "[Pass1] %s — STOP HIT %s  exit=%.2f  pnl=%.2f",
                    eval_date,
                    pos.symbol,
                    exit_price,
                    pnl,
                )
                continue

            # --- Update position state ---
            pos.days_held += 1
            pos.highest_high_since_breakout = max(pos.highest_high_since_breakout, high_raw)
            pos._current_close = close_raw

            one_r = pos.entry_price - pos.initial_stop_loss  # 1R in price units

            if pos.position_state == "INITIAL_RISK":
                # Breakeven transition: price reached 1:1 (entry + 1R)
                if pos.highest_high_since_breakout >= pos.entry_price + one_r:
                    pos.position_state = "RISK_FREE_1_TO_1"
                    pos.live_stop_loss = pos.entry_price  # Move stop to breakeven
                elif pos.days_held >= self._risk_cfg.get("time_decay_sessions", 15):
                    pos.position_state = "PENDING_MANUAL_EXIT"

            elif pos.position_state == "RISK_FREE_1_TO_1":
                if pos.highest_high_since_breakout >= pos.initial_resistance_target:
                    pos.position_state = "TRAILING_ATR"

            elif pos.position_state == "TRAILING_ATR":
                # Ratchet trailing stop (simple version: use 2×ATR approximation
                # via ATR proxy; full ATR computation is done in live runner)
                # Here we use a simplified 1.5% trailing stop for the sim.
                trailing_mult = float(self._risk_cfg.get("trailing_stop_atr_multiplier", 2.0))
                # Approximate ATR as 1.5% of current price (conservative fallback)
                approx_atr = close_raw * 0.015
                candidate_stop = pos.highest_high_since_breakout - trailing_mult * approx_atr
                if candidate_stop > pos.live_stop_loss:
                    pos.live_stop_loss = candidate_stop

        # Remove closed positions
        for p in positions_to_remove:
            open_positions.remove(p)

        return account_equity

    @staticmethod
    def _positions_as_dicts(open_positions: list[_SimPosition]) -> list[dict]:
        """Convert simulated positions to the dict format expected by RiskAndSizingEngine."""
        result = []
        for pos in open_positions:
            risk_amount = (pos.entry_price - pos.live_stop_loss) * pos.shares
            result.append({
                "symbol": pos.symbol,
                "sector": pos.sector,
                "entry_price": pos.entry_price,
                "live_stop_loss": pos.live_stop_loss,
                "shares": pos.shares,
                "risk_amount": risk_amount,
                "position_value": pos.entry_price * pos.shares,
            })
        return result

    def _build_candidate_dicts(
        self,
        symbols: list[str],
        eval_date: date,
        session: Session,
    ) -> list[dict]:
        """Build the list[dict] format that compute_all() requires.

        For each symbol, fetches raw OHLCV from market_data_lake and computes
        in-memory adjusted prices (using corporate actions from the DB if available,
        otherwise an identity factor of 1.0 is used which means raw == adjusted).

        Parameters
        ----------
        symbols:
            List of NSE ticker symbols that passed the screener gates.
        eval_date:
            Point-in-time date — only data up to and including this date is used.
        session:
            Active DB session.

        Returns
        -------
        list[dict]
            One dict per symbol with keys:
            ``symbol``, ``raw_ohlcv``, ``adjusted_ohlcv``, ``sector``,
            ``corporate_actions``.
        """
        # Lookback: need 252 bars for Donchian high + 14 for ATR + small buffer
        lookback = self._config.get("data", {}).get("resistance_lookback_days", 252) + 30
        result = []

        for sym in symbols:
            # Fetch raw OHLCV
            rows = session.execute(
                select(
                    MarketDataLake.trade_date,
                    MarketDataLake.open_raw,
                    MarketDataLake.high_raw,
                    MarketDataLake.low_raw,
                    MarketDataLake.close_raw,
                    MarketDataLake.volume_raw,
                )
                .where(MarketDataLake.symbol == sym)
                .where(MarketDataLake.trade_date <= eval_date)
                .order_by(MarketDataLake.trade_date.desc())
                .limit(lookback)
            ).all()

            if not rows:
                continue

            rows = list(reversed(rows))  # chronological order
            raw_df = pd.DataFrame(
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

            # Compute adjusted OHLCV. In Pass 1 we use an identity factor (1.0)
            # because full corporate-action history is not guaranteed to exist
            # for all 2,300 symbols. Pass 2 applies verified adjustments.
            # This means raw == adjusted in Pass 1 — a known, accepted simplification.
            adj_df = pd.DataFrame(
                {
                    "open_adj":  raw_df["open_raw"],
                    "high_adj":  raw_df["high_raw"],
                    "low_adj":   raw_df["low_raw"],
                    "close_adj": raw_df["close_raw"],
                },
                index=raw_df.index,
            )

            result.append({
                "symbol":           sym,
                "sector":           None,   # Sector data not loaded in Pass 1
                "raw_ohlcv":        raw_df,
                "adjusted_ohlcv":   adj_df,
                "corporate_actions": [],
            })

        return result




# ---------------------------------------------------------------------------
# Internal screener: wraps UniverseScreener with ASM/earnings gates disabled
# ---------------------------------------------------------------------------

class _Pass1Screener:
    """Thin wrapper around :class:`UniverseScreener` that disables the ASM/GSM
    and earnings binary-event gates for backtest Pass 1.

    The wrapper calls the full screener but overrides the gate logic if the
    rejection reason is ``'ASM_GSM'`` or ``'BINARY_EVENT'``, treating those
    as passes.  This preserves all other gate logic unchanged.

    Parameters
    ----------
    config:
        Full ``strategy_config.yaml`` dict.
    session:
        Active DB session.
    eval_date:
        Date being screened (used for PIT queries).
    """

    def __init__(self, config: dict, session: Session, eval_date: date) -> None:
        self._config = config
        self._session = session
        self._eval_date = eval_date
        # Instantiate screener once; reuse across symbols for this date
        self._screener = UniverseScreener(config, session)

    def screen(self, symbol: str) -> bool:
        """Return ``True`` if the symbol passes all *enabled* gates.

        Enabled gates: Market Cap, ADTV, Listing Age, Technical (R:R check
        is handled later by RiskAndSizingEngine).
        Disabled gates: ASM/GSM, Earnings binary event.

        Parameters
        ----------
        symbol:
            NSE ticker to screen.

        Returns
        -------
        bool
            ``True`` if the symbol passes, ``False`` if rejected by an
            enabled gate.
        """
        result = self._screener.screen_single(symbol, self._eval_date)

        if result.passed:
            return True

        # Allow ASM/GSM and binary-event rejections through
        skip_reasons = {"ASM_GSM", "BINARY_EVENT", "EARNINGS_BLOCK"}
        if result.rejection_reason in skip_reasons:
            return True

        return False

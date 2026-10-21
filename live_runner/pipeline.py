"""
FInsight Trading Engine — EOD Pipeline Orchestrator

Runs the full daily pipeline at 5 PM IST:
1. Data freshness assertion
2. Macro regime evaluation (RegimeFilter)
3. Position lifecycle management (PositionLifecycleManager) — always runs
4. New setup screening (UniverseScreener + RiskAndSizingEngine) — only if kill switch OFF

This module is the single orchestration point. All business logic lives in engine_core.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime

from sqlalchemy.orm import Session

from config import load_config
from live_runner.idempotency import AlreadyRunError, IdempotencyGuard

logger = logging.getLogger(__name__)


class DataFreshnessError(Exception):
    """Raised when today's market data hasn't been ingested yet."""
    pass


class EODPipeline:
    """
    Orchestrates the daily end-of-day pipeline.

    Usage:
        with get_session() as session:
            pipeline = EODPipeline(session)
            pipeline.run(date.today())
    """

    def __init__(self, session: Session):
        self.session = session
        self.config = load_config()

    def run(self, eval_date: date) -> dict:
        """
        Execute the full EOD pipeline for eval_date.

        Returns a summary dict with pipeline results.
        Raises AlreadyRunError if today's pipeline already completed.
        """
        guard = IdempotencyGuard(self.session)

        acquired = guard.acquire(eval_date)
        if not acquired:
            raise AlreadyRunError(f"Pipeline already completed for {eval_date}.")

        results = {
            "eval_date": str(eval_date),
            "kill_switch_active": False,
            "candidates_screened": 0,
            "candidates_passed": 0,
            "new_setups_generated": 0,
            "positions_evaluated": 0,
        }

        try:
            # ── Step 0: Data Ingestion ────────────────────────────────────────
            self._run_ingestion(eval_date)

            # ── Step 1: Data freshness check ──────────────────────────────────
            self._assert_data_freshness(eval_date)
            logger.info(f"[PIPELINE] Data freshness OK for {eval_date}.")

            # ── Step 1.5: Pre-flight spot-check ──────────────────────────────
            from engine_core.preflight import assert_preflight_spot_check
            assert_preflight_spot_check()

            # ── Step 2: Macro regime evaluation ───────────────────────────────
            from engine_core.regime_filter import RegimeFilter
            regime_filter = RegimeFilter(config=self.config, session=self.session)
            regime_state = regime_filter.evaluate(eval_date)
            results["kill_switch_active"] = regime_state.kill_switch_active

            if regime_state.kill_switch_active:
                logger.warning(
                    f"[PIPELINE] ⚠️ KILL SWITCH ACTIVE for {eval_date}. "
                    f"Reason: {regime_state.trigger_reason}. "
                    f"Re-entry count: {regime_state.reentry_consecutive_count}/3"
                )
            else:
                logger.info(f"[PIPELINE] Regime: ACTIVE (Nifty: {regime_state.nifty_close:.0f}, VIX: {regime_state.vix_close:.1f})")

            # ── Step 2.5: Paper Trader (PAPER mode only) ──────────────────────
            from engine_core.mode import current_mode
            mode = current_mode(self.config)
            if mode == "PAPER":
                from live_runner.paper_trader import expire_stale_tickets, open_pending_tickets
                expire_stale_tickets(self.session, eval_date)
                results["paper_fills"] = open_pending_tickets(self.session, self.config, eval_date)

            # ── Step 3: Position lifecycle (always runs) ───────────────────────
            from engine_core.position_lifecycle import PositionLifecycleManager
            plm = PositionLifecycleManager(config=self.config, session=self.session)
            position_updates = plm.process_all(
                eval_date, kill_switch_active=regime_state.kill_switch_active
            )
            results["positions_evaluated"] = len(position_updates)

            # Log notable state changes
            for update in position_updates:
                if update.old_state != update.new_state:
                    logger.info(
                        f"[PIPELINE] {update.symbol}: {update.old_state} → {update.new_state} "
                        f"(days_held={update.new_days_held})"
                    )
                if update.earnings_alert:
                    logger.warning(f"[PIPELINE] ⚠️ EARNINGS ALERT: {update.symbol}")

            # ── Step 4: New setup screening (only if kill switch OFF) ──────────
            from engine_core.regime_gates import bull_correction_active
            sma_n = int(self.config.get("macro", {}).get("bull_entry_sma_period", 0))
            is_bull_correction = bool(sma_n > 0 and not regime_state.kill_switch_active and bull_correction_active(
                regime_state.nifty_close, regime_state.nifty_sma200, self._fetch_nifty_sma(eval_date, sma_n)))

            if not regime_state.kill_switch_active and not is_bull_correction:
                new_setups = self._run_screening(eval_date, results)
                self._persist_watchlist(eval_date, new_setups)
            elif is_bull_correction:
                logger.info(
                    f"[PIPELINE] Market in bull intermediate correction (Nifty < SMA{bull_sma_period}) — pausing new setups."
                )
            else:
                logger.info("[PIPELINE] Kill switch active — skipping new setup screening.")

            # ── Done ──────────────────────────────────────────────────────────
            guard.complete(eval_date, results)
            logger.info(
                f"[PIPELINE] ✓ EOD pipeline complete for {eval_date}. "
                f"Setups: {results['new_setups_generated']}, "
                f"Positions evaluated: {results['positions_evaluated']}"
            )
            return results

        except Exception as e:
            guard.fail(eval_date, str(e))
            logger.error(f"[PIPELINE] Pipeline FAILED for {eval_date}: {e}", exc_info=True)
            raise

    def _assert_data_freshness(self, eval_date: date) -> None:
        """Verify today's OHLCV data has been ingested. Raises DataFreshnessError if not."""
        from sqlalchemy import text
        nifty_symbol = self.config["data"]["nifty_symbol"]
        result = self.session.execute(
            text("SELECT trade_date FROM market_data_lake WHERE symbol = :sym ORDER BY trade_date DESC LIMIT 1"),
            {"sym": nifty_symbol}
        ).fetchone()

        if not result:
            raise DataFreshnessError(f"No data found for {nifty_symbol}. Run data ingestion first.")

        latest_date = result[0]
        if isinstance(latest_date, str):
            from datetime import datetime
            latest_date = datetime.strptime(latest_date, "%Y-%m-%d").date()

        if latest_date < eval_date:
            raise DataFreshnessError(
                f"Latest data for {nifty_symbol} is {latest_date}, but pipeline is running for {eval_date}. "
                "Run the EOD data ingestor before the pipeline."
            )

    def _run_ingestion(self, eval_date: date) -> None:
        """Run daily data ingestion using the configured source."""
        eod_source = self.config.get("data", {}).get("eod_source", "kite")

        if eod_source == "bhavcopy":
            logger.info("[PIPELINE] Running Bhavcopy Ingestion...")
            from data.ingestion.bhavcopy_ingestor import BhavcopyIngestor
            BhavcopyIngestor(self.config).ingest(self.session, eval_date)

            # Ingest NIFTY50 and INDIA_VIX using yfinance (not present in Bhavcopy)
            self._ingest_indices_yahoo(eval_date)

        elif eod_source == "kite":
            logger.info("[PIPELINE] Running Kite Ingestion...")
            from data.ingestion.ohlcv_ingestor import OHLCVIngestor
            from data.ingestion.index_vix_ingestor import IndexVIXIngestor
            try:
                # Kite ingestion expects historical sync structure, here we just do today
                OHLCVIngestor(self.config).ingest_universe(None, eval_date, eval_date)
                IndexVIXIngestor(self.config).ingest_today()
            except Exception as e:
                logger.warning(f"[PIPELINE] Kite ingestion failed (missing token?): {e}")

    def _ingest_indices_yahoo(self, target_date: date) -> None:
        """Helper to fetch NIFTY and VIX index data via yfinance for the target date."""
        import yfinance as yf
        import pandas as pd
        from sqlalchemy import text
        from datetime import timedelta
        from data.db.connection import engine

        index_map = {"^NSEI": "NIFTY50_INDEX", "^INDIAVIX": "INDIA_VIX"}
        # yfinance historical needs end_date = target + 1 for a single day fetch
        end_date = target_date + timedelta(days=1)

        for yf_ticker, db_symbol in index_map.items():
            df = yf.download(yf_ticker, start=target_date, end=end_date, progress=False)
            if df.empty:
                logger.warning(f"[PIPELINE] No index data from Yahoo for {db_symbol} on {target_date}")
                continue

            df.reset_index(inplace=True)
            df.columns = [c[0].strip().lower() if isinstance(c, tuple) else c.strip().lower() for c in df.columns]
            df.rename(columns={
                "date": "trade_date", "open": "open_raw", "high": "high_raw", 
                "low": "low_raw", "close": "close_raw"
            }, inplace=True)
            df["trade_date"] = pd.to_datetime(df["trade_date"], utc=True).dt.date
            
            df = df[df["trade_date"] == target_date].copy()
            if df.empty:
                continue

            df["symbol"] = db_symbol
            df["exchange"] = "NSE"
            df["volume_raw"] = 0

            keep = ["trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "symbol", "exchange"]
            df = df[[c for c in keep if c in df.columns]]

            self.session.execute(
                text("DELETE FROM market_data_lake WHERE symbol = :sym AND trade_date = :td"),
                {"sym": db_symbol, "td": target_date}
            )
            self.session.commit()
            df.to_sql("market_data_lake", con=engine, if_exists="append", index=False)
            logger.info(f"[PIPELINE] Ingested {db_symbol} via yfinance for {target_date}")

    def _run_screening(self, eval_date: date, results: dict) -> list:
        """Run UniverseScreener + RiskAndSizingEngine and return approved setups."""
        from engine_core.universe_screener import UniverseScreener
        from engine_core.risk_sizing import RiskAndSizingEngine

        # Screen universe
        screener = UniverseScreener(config=self.config, session=self.session)
        screening_results = screener.screen_all(eval_date)
        results["candidates_screened"] = len(screening_results)

        passed_symbols = [r.symbol for r in screening_results if r.passed]
        results["candidates_passed"] = len(passed_symbols)

        logger.info(
            f"[PIPELINE] Universe screening: {len(screening_results)} candidates, "
            f"{len(passed_symbols)} passed all gates."
        )

        if not passed_symbols:
            return []

        # Get current open positions for heat cap evaluation
        from engine_core.mode import current_mode
        mode = current_mode(self.config)
        current_positions = self._get_open_positions_for_heat_cap(mode)

        # Size and gate candidates
        from engine_core.equity import get_equity
        fallback_equity = float(os.getenv("ACCOUNT_EQUITY", "1000000"))
        account_equity = get_equity(self.session, self.config, mode, fallback_equity)
        sizing_engine = RiskAndSizingEngine(config=self.config)
        candidate_dicts = self._build_candidate_dicts(passed_symbols, eval_date)
        from engine_core.entry_filters import apply_entry_filters
        candidate_dicts = apply_entry_filters(candidate_dicts, self.config)
        setups = sizing_engine.compute_all(
            candidates=candidate_dicts,
            eval_date=eval_date,
            account_equity=account_equity,
            current_positions=current_positions,
            session=self.session,
        )

        approved = [s for s in setups if not s.blocked]
        results["new_setups_generated"] = len(approved)

        logger.info(
            f"[PIPELINE] Sizing & heat cap: {len(setups)} sized, "
            f"{len(approved)} approved, {len(setups) - len(approved)} blocked."
        )
        return setups

    def _build_candidate_dicts(self, symbols: list[str], eval_date: date) -> list[dict]:
        """Pre-fetch OHLCV and corporate actions for candidate symbols."""
        from engine_core.candidate_builder import build_candidate_dicts
        return build_candidate_dicts(self.session, self.config, symbols, eval_date)



    def _fetch_nifty_sma(self, eval_date: date, period: int) -> Optional[float]:
        """Fetch Nifty 50 SMA for the specified period as of eval_date."""
        from engine_core.regime_gates import nifty_sma as _nifty_sma
        return _nifty_sma(self.session, self.config, eval_date, period)


    def _get_open_positions_for_heat_cap(self, mode: Optional[str] = None) -> list[dict]:
        """Returns open positions as plain dicts for heat cap calculation."""
        from data.db.models import ActivePosition
        if mode is None:
            from engine_core.mode import current_mode
            mode = current_mode(self.config)
        positions = self.session.query(ActivePosition).filter(ActivePosition.mode == mode).all()
        return [
            {
                "symbol": p.symbol,
                "sector": p.sector,
                "shares": p.shares,
                "entry_price": p.entry_price,
                "live_stop_loss": p.live_stop_loss,
                "risk_amount": max(0.0, (getattr(p, "shares_remaining", None) or p.shares) * (p.entry_price - p.live_stop_loss)),
                "position_value": (getattr(p, "shares_remaining", None) or p.shares) * p.entry_price,
            }
            for p in positions
        ]

    def _persist_watchlist(self, eval_date: date, setups: list) -> None:
        """Persist today's approved and blocked setups to daily_watchlist table."""
        from data.db.models import DailyWatchlist

        # Clear today's pending entries (re-run scenario)
        self.session.query(DailyWatchlist).filter(
            DailyWatchlist.run_date == eval_date,
            DailyWatchlist.execution_status == "PENDING",
        ).delete()

        for setup in setups:
            entry = DailyWatchlist(
                run_date=eval_date,
                symbol=setup.symbol,
                entry_price=setup.entry_price,
                live_stop_loss=setup.live_stop_loss,
                stop_a=setup.stop_a,
                stop_b=setup.stop_b,
                initial_resistance_target=setup.initial_resistance_target,
                projected_rr=setup.projected_rr,
                shares=setup.shares,
                position_value=setup.position_value,
                risk_amount=setup.risk_amount,
                risk_pct_of_equity=setup.risk_pct_of_equity,
                sector=setup.sector,
                blocked=setup.blocked,
                block_reason=setup.block_reason,
                execution_status="PENDING",
            )
            self.session.add(entry)

        self.session.flush()
        logger.info(f"[PIPELINE] Watchlist persisted for {eval_date}: {len(setups)} entries.")

"""FInsight Trading Engine — ORM Models"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, BigInteger, Column, Date, DateTime, Float,
    Index, Integer, String, Text, UniqueConstraint,
    func
)
from sqlalchemy.orm import Mapped, mapped_column

from data.db.connection import Base


class MarketDataLake(Base):
    """Raw unadjusted EOD OHLCV. Adjusted prices are NEVER stored."""
    __tablename__ = "market_data_lake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_raw: Mapped[float] = mapped_column(Float, nullable=False)
    high_raw: Mapped[float] = mapped_column(Float, nullable=False)
    low_raw: Mapped[float] = mapped_column(Float, nullable=False)
    close_raw: Mapped[float] = mapped_column(Float, nullable=False)
    volume_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False, default="NSE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_mdl_symbol_date"),
        Index("idx_mdl_symbol_date", "symbol", "trade_date"),
    )


class SharesOutstanding(Base):
    """Raw shares outstanding per effective date — for PIT Market Cap calculation."""
    __tablename__ = "shares_outstanding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    shares_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("symbol", "effective_date"),)


class CorporateActionsLog(Base):
    """Corporate action events (splits, bonuses). Stored as events — NOT pre-applied."""
    __tablename__ = "corporate_actions_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ratio_numerator: Mapped[Optional[float]] = mapped_column(Float)
    ratio_denominator: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("symbol", "ex_date", "action_type"),)


class ASMGSMList(Base):
    """Current ASM/GSM surveillance list — refreshed daily."""
    __tablename__ = "asm_gsm_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    framework: Mapped[str] = mapped_column(String(10), nullable=False)
    stage: Mapped[Optional[str]] = mapped_column(String(50))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("symbol", "framework"),)


class EarningsCalendar(Base):
    """Forward earnings and corporate action calendar — refreshed daily."""
    __tablename__ = "earnings_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("symbol", "event_date", "event_type"),)


class RegimeState(Base):
    """Persisted macro regime state for hysteresis tracking."""
    __tablename__ = "regime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eval_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nifty_close: Mapped[Optional[float]] = mapped_column(Float)
    nifty_sma200: Mapped[Optional[float]] = mapped_column(Float)
    nifty_sma50: Mapped[Optional[float]] = mapped_column(Float)
    vix_close: Mapped[Optional[float]] = mapped_column(Float)
    reentry_consecutive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trigger_reason: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ActivePosition(Base):
    """Open positions — strict state machine with daily updates."""
    __tablename__ = "active_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    live_stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    initial_resistance_target: Mapped[float] = mapped_column(Float, nullable=False)
    projected_rr: Mapped[float] = mapped_column(Float, nullable=False)
    position_state: Mapped[str] = mapped_column(String(30), nullable=False, default="INITIAL_RISK")
    days_held: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    highest_high_since_breakout: Mapped[float] = mapped_column(Float, nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    earnings_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_earnings_date: Mapped[Optional[date]] = mapped_column(Date)
    account_equity_at_entry: Mapped[float] = mapped_column(Float, nullable=False)
    stop_a_at_entry: Mapped[float] = mapped_column(Float, nullable=False)
    stop_b_at_entry: Mapped[float] = mapped_column(Float, nullable=False)
    last_evaluated_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("symbol", "entry_date"),)


class TradeAnalyticsLog(Base):
    """Append-only closed trade log — NEVER deleted."""
    __tablename__ = "trade_analytics_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    projected_rr: Mapped[float] = mapped_column(Float, nullable=False)
    realized_rr: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_gross: Mapped[float] = mapped_column(Float, nullable=False)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(30))
    regime_at_entry: Mapped[Optional[str]] = mapped_column(String(20))
    regime_at_exit: Mapped[Optional[str]] = mapped_column(String(20))
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    days_held: Mapped[Optional[int]] = mapped_column(Integer)
    closed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PipelineRunLog(Base):
    """EOD pipeline run log — idempotency guard."""
    __tablename__ = "pipeline_run_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    kill_switch_active: Mapped[Optional[bool]] = mapped_column(Boolean)
    candidates_screened: Mapped[int] = mapped_column(Integer, default=0)
    candidates_passed: Mapped[int] = mapped_column(Integer, default=0)
    new_setups_generated: Mapped[int] = mapped_column(Integer, default=0)
    positions_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class DailyWatchlist(Base):
    """Approved trade setups from each EOD run."""
    __tablename__ = "daily_watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    live_stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    stop_a: Mapped[float] = mapped_column(Float, nullable=False)
    stop_b: Mapped[float] = mapped_column(Float, nullable=False)
    initial_resistance_target: Mapped[float] = mapped_column(Float, nullable=False)
    projected_rr: Mapped[float] = mapped_column(Float, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    position_value: Mapped[float] = mapped_column(Float, nullable=False)
    risk_amount: Mapped[float] = mapped_column(Float, nullable=False)
    risk_pct_of_equity: Mapped[float] = mapped_column(Float, nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_reason: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("run_date", "symbol"),)


class AccountLedger(Base):
    """Tracks deposits, withdrawals, and realized PnL."""
    __tablename__ = "account_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

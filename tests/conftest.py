"""
Pytest configuration and shared fixtures for all FInsight tests.

Provides:
- In-memory SQLite database with full schema for each test
- Populated market data fixtures (10 days of synthetic OHLCV)
- Mock config dict matching strategy_config.yaml structure
"""
from __future__ import annotations

import pytest
from datetime import date, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from pathlib import Path

from data.db.connection import Base
from data.db.models import (
    MarketDataLake, SharesOutstanding, CorporateActionsLog,
    ASMGSMList, EarningsCalendar, RegimeState, ActivePosition
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Strategy config dict matching strategy_config.yaml."""
    return {
        "universe": {
            "min_market_cap_cr": 5000,
            "min_adtv_cr": 25,
            "min_listing_age_trading_days": 252,
        },
        "macro": {
            "nifty_kill_sma_period": 200,
            "vix_kill_threshold": 20.0,
            "nifty_reentry_sma_period": 50,
            "vix_reentry_threshold": 18.0,
            "reentry_consecutive_sessions": 3,
        },
        "risk": {
            "atr_period": 14,
            "atr_stop_multiplier": 1.5,
            "donchian_period": 20,
            "trailing_stop_atr_period": 14,
            "trailing_stop_atr_multiplier": 2.0,
            "max_loss_pct_per_trade": 1.0,
            "min_rr_ratio": 1.5,
            "max_concurrent_positions": 10,
            "max_total_portfolio_risk_pct": 10.0,
            "max_sector_exposure_pct": 15.0,
        },
        "trade_management": {
            "time_decay_sessions": 15,
            "binary_event_block_days": 14,
            "earnings_alert_days": 7,
        },
        "data": {
            "adtv_sma_period": 20,
            "resistance_lookback_days": 252,
            "nifty_symbol": "NIFTY50_INDEX",
            "vix_symbol": "INDIA_VIX",
        },
        "backtest": {
            "initial_equity": 1_000_000,
            "pass_criteria": {
                "max_drawdown_pct": 15.0,
                "must_outperform_nifty": True,
                "include_tax_drag": True,
                "estimated_slippage_pct": 0.1,
                "estimated_stt_pct": 0.025,
            },
        },
    }


@pytest.fixture
def db_session():
    """
    Fresh in-memory SQLite database per test with full schema.
    Auto-rolls back after each test.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    # Apply schema
    schema_path = Path(__file__).resolve().parents[1] / "data" / "db" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with engine.connect() as conn:
        conn.connection.dbapi_connection.executescript(sql)

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def sample_ohlcv_data():
    """
    Returns 300 days of synthetic OHLCV data for 'TESTSTOCK'.
    Prices are realistic: starting at 1000, with small daily moves.
    Volume is constant at 1,000,000.
    """
    import pandas as pd
    import numpy as np

    np.random.seed(42)
    n = 300
    base = date(2024, 1, 2)
    dates = [base + timedelta(days=i) for i in range(n)]

    # Generate price series with random walk
    returns = np.random.normal(0.001, 0.02, n)
    close = 1000.0 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.full(n, 1_000_000)

    return pd.DataFrame({
        "symbol": "TESTSTOCK",
        "trade_date": dates,
        "open_raw": open_,
        "high_raw": high,
        "low_raw": low,
        "close_raw": close,
        "volume_raw": volume,
        "exchange": "NSE",
    })


@pytest.fixture
def populated_db(db_session, sample_ohlcv_data):
    """
    DB session with TESTSTOCK OHLCV, shares outstanding, and index data pre-populated.
    """
    import pandas as pd
    from datetime import date

    # Insert OHLCV
    for _, row in sample_ohlcv_data.iterrows():
        db_session.add(MarketDataLake(
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            open_raw=row["open_raw"],
            high_raw=row["high_raw"],
            low_raw=row["low_raw"],
            close_raw=row["close_raw"],
            volume_raw=int(row["volume_raw"]),
        ))

    # Shares outstanding: 10 crore shares (market cap = close × 10cr)
    db_session.add(SharesOutstanding(
        symbol="TESTSTOCK",
        effective_date=date(2020, 1, 1),
        shares_count=100_000_000,  # 10 crore
    ))

    db_session.flush()
    return db_session

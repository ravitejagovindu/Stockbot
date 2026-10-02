-- FInsight Trading Engine — Full Database Schema
-- Compatible with SQLite and MySQL.
-- IMPORTANT: Raw prices are NEVER stored adjusted. All adjustments happen in-memory.

-- ─────────────────────────────────────────────────────────────────────────────
-- RAW MARKET DATA
-- ─────────────────────────────────────────────────────────────────────────────

-- Raw unadjusted EOD OHLCV. Adjusted prices are NEVER stored here.
CREATE TABLE IF NOT EXISTS market_data_lake (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    trade_date     DATE    NOT NULL,
    open_raw       REAL    NOT NULL,
    high_raw       REAL    NOT NULL,
    low_raw        REAL    NOT NULL,
    close_raw      REAL    NOT NULL,
    volume_raw     BIGINT  NOT NULL,
    exchange       TEXT    NOT NULL DEFAULT 'NSE',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_mdl_symbol_date ON market_data_lake(symbol, trade_date DESC);

-- Raw shares outstanding per effective date (for PIT Market Cap)
-- Market Cap = raw_close × shares_count   (never use adjusted close)
CREATE TABLE IF NOT EXISTS shares_outstanding (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    effective_date DATE    NOT NULL,
    shares_count   BIGINT  NOT NULL,
    source         TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, effective_date)
);

CREATE INDEX IF NOT EXISTS idx_shares_symbol ON shares_outstanding(symbol, effective_date DESC);

-- Corporate actions event log (splits, bonuses, dividends)
-- Stored as events, NOT pre-applied. In-memory adjuster reads this.
CREATE TABLE IF NOT EXISTS corporate_actions_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT    NOT NULL,
    ex_date             DATE    NOT NULL,
    action_type         TEXT    NOT NULL CHECK(action_type IN ('SPLIT', 'BONUS', 'DIVIDEND', 'RIGHTS', 'MERGER')),
    ratio_numerator     REAL,           -- e.g., for 1:2 split: numerator=1 (new shares)
    ratio_denominator   REAL,           -- e.g., for 1:2 split: denominator=2 (old shares)
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, ex_date, action_type)
);

CREATE INDEX IF NOT EXISTS idx_corp_symbol_date ON corporate_actions_log(symbol, ex_date DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- SURVEILLANCE & COMPLIANCE
-- ─────────────────────────────────────────────────────────────────────────────

-- ASM/GSM surveillance list — refreshed daily from NSE/BSE
CREATE TABLE IF NOT EXISTS asm_gsm_list (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    framework      TEXT    NOT NULL CHECK(framework IN ('ASM', 'GSM')),
    stage          TEXT,                -- e.g., 'Stage 1', 'Stage 2', 'Shortlisted'
    effective_date DATE    NOT NULL,
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, framework)
);

-- Forward earnings and corporate action calendar — refreshed daily
CREATE TABLE IF NOT EXISTS earnings_calendar (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    event_date     DATE    NOT NULL,
    event_type     TEXT    NOT NULL CHECK(event_type IN ('EARNINGS', 'AGM', 'DIVIDEND', 'RIGHTS', 'BOARD_MEETING', 'OTHER')),
    description    TEXT,
    source         TEXT,
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, event_date, event_type)
);

CREATE INDEX IF NOT EXISTS idx_earnings_symbol ON earnings_calendar(symbol, event_date ASC);

-- ─────────────────────────────────────────────────────────────────────────────
-- MACRO REGIME STATE
-- ─────────────────────────────────────────────────────────────────────────────

-- Persisted regime state for hysteresis tracking across sessions
CREATE TABLE IF NOT EXISTS regime_state (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date                   DATE    NOT NULL UNIQUE,
    kill_switch_active          BOOLEAN NOT NULL DEFAULT 0,
    nifty_close                 REAL,
    nifty_sma200                REAL,
    nifty_sma50                 REAL,
    vix_close                   REAL,
    reentry_consecutive_count   INTEGER NOT NULL DEFAULT 0,  -- Counts toward 3-session re-entry
    trigger_reason              TEXT,   -- 'NIFTY_BELOW_SMA200' | 'VIX_ABOVE_20' | 'BOTH' | NULL
    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- POSITION MANAGEMENT
-- ─────────────────────────────────────────────────────────────────────────────

-- Active open positions — operates as a strict state machine
CREATE TABLE IF NOT EXISTS active_positions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol                      TEXT    NOT NULL,
    entry_date                  DATE    NOT NULL,
    entry_price                 REAL    NOT NULL,
    shares                      INTEGER NOT NULL,
    initial_stop_loss           REAL    NOT NULL,  -- Stop at entry (never changes)
    live_stop_loss              REAL    NOT NULL,  -- Current stop (moves up only)
    initial_resistance_target   REAL    NOT NULL,  -- First major resistance (1:1.5 R:R minimum)
    projected_rr                REAL    NOT NULL,  -- R:R at entry
    position_state              TEXT    NOT NULL DEFAULT 'INITIAL_RISK'
                                CHECK(position_state IN ('INITIAL_RISK', 'RISK_FREE_1_TO_1', 'TRAILING_ATR', 'PENDING_MANUAL_EXIT')),
    days_held                   INTEGER NOT NULL DEFAULT 0,
    highest_high_since_breakout REAL    NOT NULL,  -- Ratchet reference for trailing stop
    sector                      TEXT,
    earnings_alert              BOOLEAN NOT NULL DEFAULT 0,
    next_earnings_date          DATE,
    account_equity_at_entry     REAL    NOT NULL,
    stop_a_at_entry             REAL    NOT NULL,  -- ATR-based stop at entry (for audit)
    stop_b_at_entry             REAL    NOT NULL,  -- Donchian-based stop at entry (for audit)
    last_evaluated_date         DATE,              -- Date of last state machine evaluation
    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, entry_date)
);

CREATE INDEX IF NOT EXISTS idx_positions_state ON active_positions(position_state);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON active_positions(symbol);

-- ─────────────────────────────────────────────────────────────────────────────
-- ANALYTICS & PERFORMANCE TRACKING
-- ─────────────────────────────────────────────────────────────────────────────

-- Append-only closed trade log — NEVER deleted
CREATE TABLE IF NOT EXISTS trade_analytics_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id    INTEGER NOT NULL,    -- References the active_positions row (kept for audit)
    symbol         TEXT    NOT NULL,
    entry_date     DATE    NOT NULL,
    exit_date      DATE    NOT NULL,
    entry_price    REAL    NOT NULL,
    exit_price     REAL    NOT NULL,
    shares         INTEGER NOT NULL,
    initial_stop_loss REAL NOT NULL,
    projected_rr   REAL    NOT NULL,    -- R:R calculated at entry
    realized_rr    REAL    NOT NULL,    -- (exit - entry) / (entry - initial_stop_loss)
    pnl_gross      REAL    NOT NULL,    -- (exit_price - entry_price) × shares
    exit_reason    TEXT    CHECK(exit_reason IN ('MANUAL', 'STOP_HIT', 'TIME_DECAY', 'EARNINGS_EXIT', 'OTHER')),
    regime_at_entry TEXT,               -- 'ACTIVE' | 'KILL_SWITCH'
    regime_at_exit  TEXT,
    sector         TEXT,
    days_held      INTEGER,
    closed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────────────────────
-- PIPELINE OPERATIONS
-- ─────────────────────────────────────────────────────────────────────────────

-- EOD pipeline run log — idempotency guard
CREATE TABLE IF NOT EXISTS pipeline_run_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date             DATE    NOT NULL UNIQUE,   -- UNIQUE enforces one run per day
    status               TEXT    NOT NULL CHECK(status IN ('RUNNING', 'COMPLETE', 'FAILED')),
    kill_switch_active   BOOLEAN,
    candidates_screened  INTEGER DEFAULT 0,
    candidates_passed    INTEGER DEFAULT 0,
    new_setups_generated INTEGER DEFAULT 0,
    positions_evaluated  INTEGER DEFAULT 0,
    error_message        TEXT,
    started_at           TIMESTAMP,
    completed_at         TIMESTAMP
);

-- Daily watchlist (approved trade setups — generated each EOD run, cleared next day)
CREATE TABLE IF NOT EXISTS daily_watchlist (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date                DATE    NOT NULL,
    symbol                  TEXT    NOT NULL,
    entry_price             REAL    NOT NULL,
    live_stop_loss          REAL    NOT NULL,
    stop_a                  REAL    NOT NULL,
    stop_b                  REAL    NOT NULL,
    initial_resistance_target REAL  NOT NULL,
    projected_rr            REAL    NOT NULL,
    shares                  INTEGER NOT NULL,
    position_value          REAL    NOT NULL,
    risk_amount             REAL    NOT NULL,
    risk_pct_of_equity      REAL    NOT NULL,
    sector                  TEXT,
    blocked                 BOOLEAN NOT NULL DEFAULT 0,
    block_reason            TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_date, symbol)
);

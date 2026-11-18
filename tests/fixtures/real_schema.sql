-- Schema of the real finsight.db as of 2026-11-17 (tables, indexes, the two native triggers); NO data. Used by the guard tests (tests/unit/test_db_guard*.py).

CREATE TABLE account_ledger (
	id INTEGER NOT NULL, 
	transaction_date DATE NOT NULL, 
	transaction_type VARCHAR(20) NOT NULL, 
	amount_inr FLOAT NOT NULL, 
	notes TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE active_positions (
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
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP, original_shares INTEGER, shares_remaining INTEGER, total_realized_pnl_partial FLOAT DEFAULT 0.0, partial_exit_count INTEGER DEFAULT 0, last_partial_exit_rr FLOAT, next_partial_exit_rr FLOAT, mode VARCHAR(5) NOT NULL DEFAULT 'LIVE', pending_close_reason VARCHAR(30), fill_source VARCHAR(14), entry_costs FLOAT NOT NULL DEFAULT 0, risk_inr FLOAT, applied_corp_actions TEXT, manual_review_ca VARCHAR(200),
    UNIQUE(symbol, entry_date)
);

CREATE TABLE asm_gsm_daily_snapshot (
    snapshot_date TEXT NOT NULL, framework TEXT NOT NULL, symbol TEXT NOT NULL, isin TEXT, company_name TEXT,
    stage TEXT, surv_code TEXT, surv_desc TEXT, nse_time TEXT, srno INTEGER, fetched_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, framework, symbol));

CREATE TABLE asm_gsm_list (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    framework      TEXT    NOT NULL CHECK(framework IN ('ASM', 'GSM')),
    stage          TEXT,                -- e.g., 'Stage 1', 'Stage 2', 'Shortlisted'
    effective_date DATE    NOT NULL,
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, framework)
);

CREATE TABLE asm_gsm_snapshot_log (
    run_at TEXT NOT NULL, snapshot_date TEXT NOT NULL, endpoint TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT);

CREATE TABLE asm_gsm_snapshot_raw (
    snapshot_date TEXT NOT NULL, endpoint TEXT NOT NULL, fetched_at TEXT NOT NULL,
    http_status INTEGER NOT NULL, row_count INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, endpoint));

CREATE TABLE bhavcopy_fetch_log (
    trade_date  DATE PRIMARY KEY,
    status      TEXT NOT NULL,      -- OK | HOLIDAY_OR_MISSING | ERROR
    n_rows      INTEGER,
    url         TEXT,
    fetched_at  TEXT,
    note        TEXT
);

CREATE TABLE corporate_actions_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT    NOT NULL,
    ex_date             DATE    NOT NULL,
    action_type         TEXT    NOT NULL CHECK(action_type IN ('SPLIT','BONUS','DIVIDEND','RIGHTS','MERGER','DEMERGER','OTHER')),
    ratio_numerator     REAL,
    ratio_denominator   REAL,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source              TEXT,
    loaded_at           TEXT,
    evidence_tier       TEXT,
    evidence            TEXT,
    UNIQUE(symbol, ex_date, action_type)
);

CREATE TABLE daily_watchlist (
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
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP, execution_status VARCHAR(20) NOT NULL DEFAULT 'PENDING', execution_note VARCHAR(80), position_id INTEGER,
    UNIQUE(run_date, symbol)
);

CREATE TABLE earnings_api_raw (
    endpoint TEXT NOT NULL, query_symbol TEXT NOT NULL, fetched_at TEXT NOT NULL, http_status INTEGER NOT NULL,
    row_count INTEGER NOT NULL, body_zlib BLOB NOT NULL, PRIMARY KEY (endpoint, query_symbol));

CREATE TABLE earnings_board_meeting (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query_symbol TEXT NOT NULL, symbol TEXT, isin TEXT, company_name TEXT,
    bm_date TEXT, purpose TEXT, description TEXT, intimation_ts TEXT, sys_ts TEXT, attachment TEXT,
    is_results_meeting INTEGER NOT NULL, results_rule TEXT NOT NULL, row_hash TEXT NOT NULL,
    UNIQUE (query_symbol, row_hash));

CREATE TABLE earnings_calendar (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    event_date     DATE    NOT NULL,
    event_type     TEXT    NOT NULL CHECK(event_type IN ('EARNINGS', 'AGM', 'DIVIDEND', 'RIGHTS', 'BOARD_MEETING', 'OTHER')),
    description    TEXT,
    source         TEXT,
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, event_date, event_type)
);

CREATE TABLE earnings_collect_log (
    at TEXT NOT NULL, endpoint TEXT NOT NULL, query_symbol TEXT NOT NULL, http_status INTEGER, rows INTEGER, note TEXT);

CREATE TABLE earnings_results_filing (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query_symbol TEXT NOT NULL, symbol TEXT, isin TEXT, company_name TEXT,
    period TEXT, relating_to TEXT, from_date TEXT, to_date TEXT, audited TEXT, consolidated TEXT, cumulative TEXT, format TEXT,
    filing_ts TEXT, broadcast_ts TEXT, exch_dissem_ts TEXT, seq_number TEXT, params TEXT, xbrl TEXT, row_hash TEXT NOT NULL,
    UNIQUE (query_symbol, row_hash));

CREATE TABLE earnings_symbol_map (
    lake_symbol TEXT NOT NULL, query_symbol TEXT NOT NULL, how TEXT NOT NULL, PRIMARY KEY (lake_symbol, query_symbol));

CREATE TABLE index_gap_fill(symbol text, trade_date text, open_raw real, high_raw real, low_raw real, close_raw real, source text, primary key(symbol, trade_date));

CREATE TABLE isin_symbol_map (isin TEXT, symbol TEXT, first_date TEXT, last_date TEXT, isin_class TEXT, canonical_symbol TEXT, applied_at TEXT);

CREATE TABLE market_data_lake (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    trade_date     DATE    NOT NULL,
    open_raw       REAL    NOT NULL,
    high_raw       REAL    NOT NULL,
    low_raw        REAL    NOT NULL,
    close_raw      REAL    NOT NULL,
    volume_raw     BIGINT  NOT NULL,
    exchange       TEXT    NOT NULL DEFAULT 'NSE',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP, source TEXT, loaded_at TEXT, source_symbol TEXT,
    UNIQUE(symbol, trade_date)
);

CREATE TABLE market_data_lake_staging (
    symbol      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open_raw    REAL NOT NULL,
    high_raw    REAL NOT NULL,
    low_raw     REAL NOT NULL,
    close_raw   REAL NOT NULL,
    volume_raw  BIGINT NOT NULL,
    prev_close  REAL,
    isin        TEXT,
    series      TEXT,
    source      TEXT,
    UNIQUE(symbol, trade_date)
);

CREATE TABLE market_data_lake_yahoo_archive (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, trade_date DATE NOT NULL, open_raw REAL NOT NULL, high_raw REAL NOT NULL, low_raw REAL NOT NULL, close_raw REAL NOT NULL, volume_raw BIGINT NOT NULL, exchange TEXT, created_at TIMESTAMP, archived_at TEXT, UNIQUE(symbol, trade_date));

CREATE TABLE pipeline_run_log (
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

CREATE TABLE regime_state (
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

CREATE TABLE securities_master (
                symbol          VARCHAR(20) PRIMARY KEY,
                company_name    VARCHAR(200),
                series          VARCHAR(10) NOT NULL DEFAULT 'EQ',
                listing_date    DATE NOT NULL,
                isin            VARCHAR(30),
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE shares_outstanding (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT    NOT NULL,
    effective_date DATE    NOT NULL,
    shares_count   BIGINT  NOT NULL,
    source         TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, effective_date)
);

CREATE TABLE trade_analytics_log (
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
, mode VARCHAR(5) NOT NULL DEFAULT 'LIVE', costs_total FLOAT NOT NULL DEFAULT 0, pnl_net FLOAT, tax_est FLOAT NOT NULL DEFAULT 0, is_partial BOOLEAN NOT NULL DEFAULT 0, risk_inr FLOAT, excluded_ca BOOLEAN NOT NULL DEFAULT 0);

CREATE INDEX idx_corp_symbol_date ON corporate_actions_log(symbol, ex_date);

CREATE INDEX idx_earnings_symbol ON earnings_calendar(symbol, event_date ASC);

CREATE INDEX idx_mdl_symbol_date ON market_data_lake(symbol, trade_date DESC);

CREATE INDEX idx_mdl_trade_date ON market_data_lake (trade_date);

CREATE INDEX idx_mdls_date ON market_data_lake_staging(trade_date);

CREATE INDEX idx_mdls_isin ON market_data_lake_staging(isin, trade_date);

CREATE INDEX idx_positions_state ON active_positions(position_state);

CREATE INDEX idx_positions_symbol ON active_positions(symbol);

CREATE INDEX idx_securities_listing_date ON securities_master(listing_date);

CREATE INDEX idx_shares_symbol ON shares_outstanding(symbol, effective_date DESC);

CREATE INDEX ix_ebm_isin ON earnings_board_meeting (isin, bm_date);

CREATE INDEX ix_erf_isin ON earnings_results_filing (isin, to_date);

CREATE TRIGGER trg_tal_no_delete BEFORE DELETE ON trade_analytics_log
            BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;

CREATE TRIGGER trg_tal_no_update BEFORE UPDATE ON trade_analytics_log
            BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;

-- non-eq-series: BE/BZ/BL rows (added by scripts/backfill_non_eq.py)
CREATE TABLE IF NOT EXISTS market_data_non_eq (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    series        TEXT NOT NULL,
    isin          TEXT,
    open_raw      REAL NOT NULL,
    high_raw      REAL NOT NULL,
    low_raw       REAL NOT NULL,
    close_raw     REAL NOT NULL,
    prev_close    REAL,
    volume_raw    INTEGER NOT NULL,
    trades        INTEGER,
    traded_value  REAL,
    source_file   TEXT,
    created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    UNIQUE(symbol, trade_date, series)
);
CREATE INDEX IF NOT EXISTS idx_non_eq_date ON market_data_non_eq(trade_date);
CREATE INDEX IF NOT EXISTS idx_non_eq_isin ON market_data_non_eq(isin, trade_date);

"""
FInsight Trading Engine — README
"""

# FInsight Trading Engine

A local, SEBI-compliant end-of-day stock screening and trade management system for Indian equities.

## ⚠️ Compliance Notice

This engine is designed in full compliance with **SEBI's April 2026 algorithmic trading regulations**. It **never routes automated orders**. It generates Trade Tickets which the user executes manually in their Kite terminal. There is no "Buy" or "Invest" button.

---

## Architecture

```
finsight/
├── engine_core/          # Shared stateless quant logic (imported by both backtest + live runner)
├── data/                 # Data ingestion pipelines and DB layer
├── backtest/             # Bifurcated backtest pipeline (Pass 1 → Scrape → Verify → Pass 2)
├── live_runner/          # FastAPI EOD runner (fires at 5 PM IST daily)
├── ui/                   # React dashboard (Trade Tickets, portfolio, analytics)
├── strategy_config.yaml  # All numeric parameters — Git-tracked
├── authorize_live.py     # Deployment authorization script
└── authorized_deployment.json  # Git-SHA lock file (committed after authorization)
```

---

## Quick Start

### 1. Setup

```bash
# Clone and enter project
git clone <repo>
cd finsight

# Install Python dependencies
python -m pip install -r requirements.txt

# Copy and fill environment variables
copy .env.template .env
# Edit .env with your Kite API key, access token, and account equity
```

### 2. Initialize Database

```bash
python -c "from data.db.connection import init_db; init_db()"
```

### 3. Ingest Historical Data

```bash
# Ingest full historical OHLCV (2010–present)
python -m data.ingestion.ohlcv_ingestor --from 2010-01-01 --to today

# Refresh surveillance and earnings data
python -m data.ingestion.asm_gsm_refresher
python -m data.ingestion.earnings_calendar_ingestor
```

### 4. Run Backtest

```bash
# Pass 1: Naive run (ignores ASM/GSM and earnings)
python backtest/run_backtest.py --pass1

# Bifurcated scrape (get historical ASM/GSM and earnings data)
python backtest/run_backtest.py --scrape

# MANUAL STEP: Open backtest/outputs/pending_asm_gsm_matches.csv
# Review each PDF URL, verify/reject dates, set status to VERIFIED or REJECTED

# Pass 2: Compliant run (using verified data)
python backtest/run_backtest.py --pass2

# Generate audit ledger
python backtest/run_backtest.py --audit
```

### 5. Authorize for Live Trading

```bash
# Only run this after Pass 2 passes the dual gate (< 15% drawdown, beats Nifty)
python authorize_live.py --confirm-ledger=backtest/outputs/audit.json
```

### 6. Start Live Engine

```bash
# Start the FastAPI EOD runner (verifies Git-SHA lock on startup)
python -m live_runner.main

# Start the React dashboard
cd ui
npm run dev
# Open http://localhost:5173
```

---

## Daily Workflow

1. **5:00 PM IST** — Engine fires automatically
2. Check the **Dashboard** for kill switch status and portfolio heat
3. Check the **Watchlist** for today's approved Trade Tickets
4. If setups are approved: manually enter them in **Kite terminal**
5. Monitor **Portfolio** page for position state changes and earnings alerts
6. When closing a position: use the **Close Position** button in the Portfolio page (for analytics tracking)

---

## Re-Authorization After Code Changes

Any change to `engine_core/`, `strategy_config.yaml`, or `data/` requires:

```bash
# 1. Run the backtest again (or at minimum Pass 2)
python backtest/run_backtest.py --pass2 --audit

# 2. Re-authorize
python authorize_live.py --confirm-ledger=backtest/outputs/audit.json
```

---

## Strategy Parameters

All parameters are in [`strategy_config.yaml`](strategy_config.yaml). Key values:

| Parameter | Value |
|---|---|
| Min Market Cap | ₹5,000 cr |
| Min 20-day ADTV | ₹25 cr |
| Min Listing Age | 252 trading days |
| Nifty Kill Switch | Below 200-day SMA OR VIX > 20 |
| Re-entry Hysteresis | 3 sessions: Nifty > 50-SMA AND VIX < 18 |
| Stop Loss | Max of: Entry − 1.5×ATR14 or Donchian Low(20) |
| Max Loss Per Trade | 1% of total equity |
| Min R:R | 1:1.5 |
| Max Positions | 10 |
| Max Portfolio Risk | 10% of equity |
| Max Sector Exposure | 15% of allocated capital |
| Time Decay | 15 sessions to 1:1 → manual exit flag |
| Trailing Stop | 2×ATR below highest high (ratchet) |

---

## Running Tests

```bash
python -m pytest tests/ -v --cov=engine_core --cov=live_runner
```

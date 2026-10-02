"""
FInsight Trading Engine — FastAPI Application Entry Point

Boots the live EOD runner. On startup:
1. Verifies the Git-SHA deployment lock
2. Initializes the database
3. Starts the APScheduler for the 5 PM IST daily pipeline

The engine is SEBI-compliant by design — it generates Trade Tickets only.
No order routing or automated trading is implemented.
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# Configure logging first
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: runs startup and shutdown logic."""
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("FInsight Trading Engine — Starting Up")
    logger.info("=" * 60)

    # Step 1: Verify Git-SHA lock (kills process if violated)
    from live_runner.git_lock import verify_git_lock
    verify_git_lock()

    # Step 2: Initialize database
    from data.db.connection import init_db
    init_db()
    logger.info("[STARTUP] Database initialized.")

    # Step 3: Start APScheduler for 5 PM IST daily pipeline
    from live_runner.scheduler import start_scheduler
    start_scheduler()
    logger.info("[STARTUP] EOD scheduler started. Pipeline fires daily at 17:00 IST.")

    logger.info("[STARTUP] FInsight Engine ready.")
    logger.info("=" * 60)

    yield  # App runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    from live_runner.scheduler import stop_scheduler
    stop_scheduler()
    logger.info("[SHUTDOWN] Scheduler stopped. FInsight Engine shut down cleanly.")


app = FastAPI(
    title="FInsight Trading Engine",
    description=(
        "Local EOD stock screening and trade management system. "
        "SEBI-compliant — generates Trade Tickets only. No automated order routing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow React dev server to call the API in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
from live_runner.routers import health, regime, watchlist, portfolio, analytics, positions

app.include_router(health.router)
app.include_router(regime.router, prefix="/regime", tags=["Regime"])
app.include_router(watchlist.router, prefix="/watchlist", tags=["Watchlist"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["Portfolio"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(positions.router, prefix="/positions", tags=["Positions"])


if __name__ == "__main__":
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(
        "live_runner.main:app",
        host=host,
        port=port,
        reload=False,  # Never use reload=True in production
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )

"""Add paper-mode columns to active_positions, trade_analytics_log, daily_watchlist.

Run once: python -m data.db.migration_phase3_paper
Idempotent: safe to run multiple times; skips columns that already exist.
"""
from sqlalchemy import text
from data.db.connection import get_session


ADDS = [
    # active_positions
    ("active_positions", "mode",                   "VARCHAR(5) NOT NULL DEFAULT 'LIVE'"),
    ("active_positions", "pending_close_reason",   "VARCHAR(30)"),
    ("active_positions", "fill_source",            "VARCHAR(14)"),
    ("active_positions", "entry_costs",            "FLOAT NOT NULL DEFAULT 0"),
    # trade_analytics_log
    ("trade_analytics_log", "mode",        "VARCHAR(5) NOT NULL DEFAULT 'LIVE'"),
    ("trade_analytics_log", "costs_total", "FLOAT NOT NULL DEFAULT 0"),
    ("trade_analytics_log", "pnl_net",     "FLOAT"),
    ("trade_analytics_log", "tax_est",     "FLOAT NOT NULL DEFAULT 0"),
    ("trade_analytics_log", "is_partial",  "BOOLEAN NOT NULL DEFAULT 0"),
    # daily_watchlist
    ("daily_watchlist", "execution_status", "VARCHAR(20) NOT NULL DEFAULT 'PENDING'"),
    ("daily_watchlist", "execution_note",   "VARCHAR(80)"),
    ("daily_watchlist", "position_id",      "INTEGER"),
]


def main() -> None:
    with get_session() as s:
        for table, col, ddl in ADDS:
            have = {r[1] for r in s.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if col not in have:
                s.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                print(f"  added {table}.{col}")
            else:
                print(f"  skip  {table}.{col}  (already exists)")

        # Back-fill pnl_net for existing closed trades that pre-date this migration
        s.execute(text("UPDATE trade_analytics_log SET pnl_net = pnl_gross WHERE pnl_net IS NULL"))

        # Mark any old PENDING watchlist entries as EXPIRED so the paper trader
        # never tries to fill tickets that were generated before the migration.
        s.execute(text(
            "UPDATE daily_watchlist SET execution_status='EXPIRED' "
            "WHERE execution_status='PENDING'"
        ))

        # Append-only triggers
        s.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_tal_no_update BEFORE UPDATE ON trade_analytics_log
            BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;
        """))
        s.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_tal_no_delete BEFORE DELETE ON trade_analytics_log
            BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;
        """))

        s.commit()
        print("Migration complete.")


if __name__ == "__main__":
    main()

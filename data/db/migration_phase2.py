import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.append(str(Path(__file__).resolve().parents[2]))

from data.db.connection import engine, Base
import data.db.models  # Ensures models are loaded

def run_migration():
    print("Running Phase 2 Migrations...")
    Base.metadata.create_all(engine)
    
    # SQLite doesn't support adding multiple columns at once or adding columns with NOT NULL (if missing defaults).
    # We will execute ALTER TABLE directly for each column.
    # Ignore errors if the column already exists.
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = [
            "original_shares INTEGER",
            "shares_remaining INTEGER",
            "total_realized_pnl_partial FLOAT DEFAULT 0.0",
            "partial_exit_count INTEGER DEFAULT 0",
            "last_partial_exit_rr FLOAT",
            "next_partial_exit_rr FLOAT"
        ]
        for col in cols:
            try:
                conn.execute(text(f"ALTER TABLE active_positions ADD COLUMN {col}"))
                print(f"Added column {col}")
            except Exception as e:
                if "duplicate column name" in str(e).lower():
                    print(f"Column {col} already exists, skipping.")
                else:
                    print(f"Error adding {col}: {e}")
                    
        # Seed original_shares with existing shares
        try:
            conn.execute(text("UPDATE active_positions SET original_shares = shares, shares_remaining = shares WHERE original_shares IS NULL"))
        except Exception:
            pass

    print("Migrations complete.")

if __name__ == "__main__":
    run_migration()

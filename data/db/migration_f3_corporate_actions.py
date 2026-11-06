"""F3 migration: columns that let open positions survive splits/bonuses and keep R invariant.

active_positions:    risk_inr, applied_corp_actions, manual_review_ca
trade_analytics_log: risk_inr, excluded_ca
Idempotent. Usage:  py -3 -m data.db.migration_f3_corporate_actions
(ALTER TABLE ADD COLUMN is allowed on trade_analytics_log despite its append-only triggers: they only block UPDATE/DELETE.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text

COLUMNS = {
    "active_positions": [
        "risk_inr FLOAT",
        "applied_corp_actions TEXT",
        "manual_review_ca VARCHAR(200)",
    ],
    "trade_analytics_log": [
        "risk_inr FLOAT",
        "excluded_ca BOOLEAN NOT NULL DEFAULT 0",
    ],
}


def run_migration(engine) -> list[str]:
    added = []
    with engine.begin() as conn:
        for table, cols in COLUMNS.items():
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col in cols:
                name = col.split()[0]
                if name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col}"))
                added.append(f"{table}.{name}")
    return added


if __name__ == "__main__":
    from data.db.connection import engine

    print("added:", run_migration(engine))

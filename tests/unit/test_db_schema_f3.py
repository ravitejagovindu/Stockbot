"""F3 database columns: the migration adds them idempotently and schema.sql carries them (the Simulator / PositionLifecycle corporate-action tests that used to live here left with those
modules in Phase 10; the generic behaviour is tested in test_engine_corporate.py)."""
from __future__ import annotations

from sqlalchemy import create_engine, text


def test_f3_migration_adds_columns_idempotently(tmp_path):
    from scripts.provenance.migrations.migration_f3_corporate_actions import run_migration

    eng = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE active_positions (id INTEGER PRIMARY KEY, symbol TEXT)"))
        c.execute(text("CREATE TABLE trade_analytics_log (id INTEGER PRIMARY KEY, symbol TEXT)"))
    first = run_migration(eng)
    assert "active_positions.risk_inr" in first and "trade_analytics_log.excluded_ca" in first
    assert run_migration(eng) == []


def test_schema_sql_contains_f3_columns():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[2] / "stockbot" / "data" / "db" / "schema.sql").read_text(encoding="utf-8")
    for col in ("applied_corp_actions", "manual_review_ca", "excluded_ca", "risk_inr"):
        assert col in sql

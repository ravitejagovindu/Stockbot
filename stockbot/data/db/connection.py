"""
FInsight Trading Engine — Database Connection & Session Management
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./finsight.db")


def _get_engine():
    """Create and configure the SQLAlchemy engine."""
    kwargs = {}
    if DATABASE_URL.startswith("sqlite"):
        # SQLite-specific: enable WAL mode and foreign keys
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(DATABASE_URL, echo=False, **kwargs)

    if DATABASE_URL.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _get_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""
    pass


@contextmanager
def get_session() -> Session:
    """
    Context manager that yields a DB session and handles commit/rollback.

    Usage:
        with get_session() as session:
            session.add(some_model)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """
    Initialize the database by running schema.sql.
    Safe to run multiple times (uses CREATE IF NOT EXISTS).
    """
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")

    with engine.connect() as conn:
        # Execute each statement individually (SQLite doesn't support multi-statement executescript via SQLAlchemy)
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()

    print(f"[DB] Database initialized at: {DATABASE_URL}")

"""The database guard command line (db-guard design; docs/shared/db-guard/GUARD.md).

  py -3 scripts/guard.py [--db PATH] install [--seal max|none]
  py -3 scripts/guard.py [--db PATH] status [--json]
  py -3 scripts/guard.py [--db PATH] seal TABLE DATE
  py -3 scripts/guard.py [--db PATH] correct --reason TEXT -- FILE.sql        (one transaction: open, run, re-checksum, close)
  py -3 scripts/guard.py [--db PATH] open-correction REASON                    (window lives at most 15 minutes)
  py -3 scripts/guard.py [--db PATH] close-correction
  py -3 scripts/guard.py [--db PATH] audit
  py -3 scripts/guard.py [--db PATH] uninstall --yes-remove-guard

``--db`` defaults to STOCKBOT_DB or <repo>/finsight.db. Every command except status/audit writes to the database; status and audit open it read-only.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.paths import lake_path  # noqa: E402
from stockbot.data import guard  # noqa: E402
from stockbot.data.guard import core  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Database guard: install, status, seal, correct, open/close-correction, audit, uninstall.")
    ap.add_argument("--db", help="database file (default: STOCKBOT_DB or <repo>/finsight.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("install", help="create the guard state and triggers; seal every DATED table through its last date")
    p.add_argument("--seal", choices=("max", "none"), default="max")
    p = sub.add_parser("status", help="classes, sealed dates, correction counter, window (read-only)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("seal", help="seal a DATED table through a loaded date")
    p.add_argument("table")
    p.add_argument("date")
    p = sub.add_parser("correct", help="run a SQL file inside ONE correction transaction (logged)")
    p.add_argument("--reason", required=True)
    p.add_argument("sqlfile", help="the SQL file (put it after --)")
    p = sub.add_parser("open-correction", help="open a correction window (at most 15 minutes)")
    p.add_argument("reason")
    sub.add_parser("close-correction", help="close the correction window")
    sub.add_parser("audit", help="recompute the per-day checksums of sealed days and compare triggers (read-only)")
    p = sub.add_parser("uninstall", help="remove the guard (data untouched)")
    p.add_argument("--yes-remove-guard", action="store_true")
    return ap


def _ro(path):
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    return con


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    db = Path(a.db) if a.db else lake_path()
    if not db.exists():
        print(f"database not found: {db}", file=sys.stderr)
        return 2
    try:
        if a.cmd in ("status", "audit"):
            con = _ro(db)
            try:
                res = guard.status(con) if a.cmd == "status" else guard.audit(con)
            finally:
                con.close()
            print(json.dumps(res, indent=1, default=str))
            return 0 if a.cmd == "status" or res.get("ok") else 1
        con = sqlite3.connect(str(db), timeout=120, isolation_level=None)
        try:
            if a.cmd == "install":
                res = guard.install(con, seal=a.seal)
            elif a.cmd == "seal":
                res = guard.seal_table(con, a.table, a.date)
            elif a.cmd == "correct":
                res = guard.correct(con, a.reason, Path(a.sqlfile).read_text(encoding="utf-8"))
            elif a.cmd == "open-correction":
                res = guard.open_window(con, a.reason)
            elif a.cmd == "close-correction":
                res = guard.close_window(con)
            else:
                res = guard.uninstall(con, yes_remove_guard=a.yes_remove_guard)
        finally:
            con.close()
        print(json.dumps(res, indent=1, default=str))
        return 0
    except guard.GuardError as e:
        print(f"guard: {e}", file=sys.stderr)
        return 1
    except sqlite3.Error as e:
        print(f"guard: database error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""stockbot/data/ingestion/merge_asm_gsm_snapshots.py — merge the frozen standalone ASM/GSM snapshot database into the main store (run at STOP 5 or later).

Source: F:\\Projects\\Ravi\\StockBotSnapshot\\asm_gsm_snapshot.db (written by the frozen copy of snapshot_asm_gsm.py; this script never writes there).
Target: finsight.db, tables asm_gsm_daily_snapshot / asm_gsm_snapshot_raw / asm_gsm_snapshot_log (created if missing, same schema).
Rows are copied with INSERT OR IGNORE on the primary keys, so rows already in the target (for example the day-1 snapshot taken before the split) are kept as they are.
Default is a dry run that only prints counts; pass --apply to write.

    py stockbot/data/ingestion/merge_asm_gsm_snapshots.py [--src PATH] [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
from stockbot.data.ingestion.snapshot_asm_gsm import DDL                      # schema only

DEFAULT_SRC = r"F:\Projects\Ravi\StockBotSnapshot\asm_gsm_snapshot.db"
TABLES = (("asm_gsm_daily_snapshot", "snapshot_date, framework, symbol"),
          ("asm_gsm_snapshot_raw", "snapshot_date, endpoint"),
          ("asm_gsm_snapshot_log", None))


def merge(src: str, db: str, apply: bool) -> dict:
    if not Path(src).exists():
        raise FileNotFoundError(f"snapshot database not found: {src}")
    out: dict = {}
    # dry run opens the target read-only, so it cannot create tables or write anything
    con = sqlite3.connect(db, timeout=120) if apply else sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=120)
    try:
        if apply:
            con.executescript(DDL)
        con.execute("ATTACH DATABASE ? AS src", (src,))
        have = {r[0] for r in con.execute("select name from main.sqlite_master where type='table'")}
        for t, key in TABLES:
            n_src = con.execute(f"select count(*) from src.{t}").fetchone()[0]
            exists = t in have
            before = con.execute(f"select count(*) from main.{t}").fetchone()[0] if exists else 0
            if not exists:
                new = n_src
            elif key:
                new = con.execute(f"select count(*) from src.{t} s where not exists (select 1 from main.{t} m where " +
                                  " and ".join(f"m.{k.strip()}=s.{k.strip()}" for k in key.split(",")) + ")").fetchone()[0]
            else:                                                          # log table has no key: rows not already identical
                new = con.execute(f"select count(*) from (select * from src.{t} except select * from main.{t})").fetchone()[0]
            if apply:
                if key:
                    con.execute(f"insert or ignore into main.{t} select * from src.{t}")
                else:
                    con.execute(f"insert into main.{t} select * from (select * from src.{t} except select * from main.{t})")
            out[t] = dict(source_rows=n_src, target_before=before, would_add=new)
        if apply:
            con.commit()
            for t, _ in TABLES:
                out[t]["target_after"] = con.execute(f"select count(*) from main.{t}").fetchone()[0]
    finally:
        con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    res = merge(a.src, a.db, a.apply)
    for t, r in res.items():
        print(t, r)
    print("APPLIED" if a.apply else "dry run (no writes); pass --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())

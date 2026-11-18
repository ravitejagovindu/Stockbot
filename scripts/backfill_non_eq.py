"""scripts/backfill_non_eq.py - load the BE, BZ and BL rows of the archived original Bhavcopy files into ``market_data_non_eq`` (non-eq-series, stage 2).

  py -3 scripts/backfill_non_eq.py --db PATH [--raw F:\\Projects\\Ravi\\StockBotData\\raw_bhavcopy] [--end 2026-10-16] [--verify-only] [--report FILE.json]

What it does, in this order (it stops at the first problem; nothing is written before every check of step 1 and 2 passed):
  1. every file up to --end is hashed (sha256) and compared with MANIFEST.csv: a mismatch refuses the whole run;
  2. every file is parsed and the rows with series BE, BZ or BL are counted a second, independent way (plain csv, no pandas): the two counts must be equal for every day; a duplicate
     (symbol, series) in a file or an unparsable price refuses the run (nothing is zero-filled);
  3. (unless --verify-only) the table is created if missing, opened through ``guard.connect_writer`` (the guard triggers of the new table are installed by ``ensure``), the rows are inserted in
     one transaction per year, the per-day row counts in the table are compared with the expected counts, and the table is sealed through --end (guard ``seal``);
  4. the WAL is checkpointed (so the ``-wal`` file is empty).
The table must be empty (or absent) when step 3 starts. The lake (``market_data_lake``) and every other table are never written. A report (JSON) is written with --report.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stockbot.data import guard  # noqa: E402
from stockbot.data import non_eq as NE  # noqa: E402

RAW = Path(r"F:\Projects\Ravi\StockBotData\raw_bhavcopy")


def manifest_ok(raw: Path, end: str) -> dict:
    last = {}
    with open(raw / "MANIFEST.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            last[r["date"]] = r
    return {d: r for d, r in sorted(last.items()) if r["status"] == "OK" and d <= end}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    raw = Path(a.raw)
    t0 = time.time()
    files = manifest_ok(raw, a.end)
    print(f"files to load: {len(files)} ({min(files)} .. {max(files)})", flush=True)

    # 1) sha256 against the manifest
    bad = []
    for i, (d, r) in enumerate(files.items()):
        p = raw / d[:4] / r["file_name"]
        if not p.exists() or sha256_file(p) != r["sha256"]:
            bad.append(d)
        if i % 500 == 0:
            print(f"  sha256 {i}/{len(files)}", flush=True)
    if bad:
        print(f"REFUSED: {len(bad)} file(s) missing or with a sha256 different from MANIFEST.csv: {bad[:10]}", flush=True)
        return 2
    print(f"1) sha256: all {len(files)} files match MANIFEST.csv ({time.time() - t0:.0f} s)", flush=True)

    # 2) parse, independent count, duplicates
    rows_by_day, expected = {}, {}
    for i, (d, r) in enumerate(files.items()):
        p = raw / d[:4] / r["file_name"]
        rows = NE.parse_rows(p, date.fromisoformat(d), r["file_name"])
        n = NE.file_series_count(p)
        if len(rows) != n:
            print(f"REFUSED: {d} parsed {len(rows)} rows but the file has {n} BE+BZ+BL rows", flush=True)
            return 2
        keys = [(x[0], x[2]) for x in rows]
        if len(set(keys)) != len(keys):
            print(f"REFUSED: {d} has a duplicate (symbol, series)", flush=True)
            return 2
        rows_by_day[d], expected[d] = rows, n
        if i % 500 == 0:
            print(f"  parsed {i}/{len(files)}", flush=True)
    total = sum(expected.values())
    by_series: dict = {}
    for rows in rows_by_day.values():
        for x in rows:
            by_series[x[2]] = by_series.get(x[2], 0) + 1
    print(f"2) parsed: {total} rows {by_series}; per-day counts equal the independent count on all {len(files)} days ({time.time() - t0:.0f} s)", flush=True)
    report = {"files": len(files), "first": min(files), "last": max(files), "rows": total, "by_series": by_series, "per_day_count_check": "equal on every day", "sha256_check": "all files match MANIFEST.csv"}
    if a.verify_only:
        print("verify-only: nothing written", flush=True)
        if a.report:
            Path(a.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
        return 0

    # 3) write through the guard
    con = guard.connect_writer(a.db)
    try:
        if con.execute("select 1 from sqlite_master where type='table' and name=?", (NE.TABLE,)).fetchone():
            n = con.execute(f"select count(*) from {NE.TABLE}").fetchone()[0]
            if n:
                print(f"REFUSED: {NE.TABLE} already holds {n} rows", flush=True)
                return 2
        con.executescript(NE.DDL)
        ens = guard.ensure(con, strict=True)
        print(f"3) table ready; guard ensure: {ens}", flush=True)
        cols = ",".join(NE.COLUMNS)
        marks = ",".join("?" * len(NE.COLUMNS))
        by_year: dict = {}
        for d in files:
            by_year.setdefault(d[:4], []).append(d)
        for y, days in by_year.items():
            con.execute("BEGIN IMMEDIATE")
            try:
                for d in days:
                    con.executemany(f"INSERT INTO {NE.TABLE}({cols}) VALUES ({marks})", rows_by_day[d])
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            print(f"  loaded {y}: {sum(expected[d] for d in days)} rows ({time.time() - t0:.0f} s)", flush=True)
        got = dict(con.execute(f"select trade_date, count(*) from {NE.TABLE} group by trade_date").fetchall())
        wrong = {d: (got.get(d, 0), expected[d]) for d in files if got.get(d, 0) != expected[d] and expected[d] > 0}
        extra = [d for d in got if d not in files]
        if wrong or extra:
            print(f"FAILED per-day check: {list(wrong.items())[:5]} extra {extra[:5]}", flush=True)
            return 3
        n_rows = con.execute(f"select count(*) from {NE.TABLE}").fetchone()[0]
        if n_rows != total:
            print(f"FAILED: table holds {n_rows} rows, expected {total}", flush=True)
            return 3
        print(f"   per-day counts in the table equal the files' BE+BZ+BL counts on all days ({n_rows} rows)", flush=True)
        sealed = guard.seal_table(con, NE.TABLE, a.end)
        print(f"   sealed: {sealed}", flush=True)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        report.update(table_rows=n_rows, sealed=sealed)
    finally:
        con.close()
    print(f"4) done in {time.time() - t0:.0f} s", flush=True)
    if a.report:
        Path(a.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

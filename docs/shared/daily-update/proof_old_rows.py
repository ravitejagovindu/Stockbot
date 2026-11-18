"""Per-table proof that everything that existed before the daily job is unchanged (daily-data-update).

  py -3 docs/shared/daily-update/proof_old_rows.py proof --db PATH --max-rowid-from BEFORE.json|none --out FILE.json     (read-only: mode=ro, immutable)
  py -3 docs/shared/daily-update/proof_old_rows.py compare BEFORE.json AFTER.json

For every table of the BEFORE file: row count and sha256 over every column of every row with rowid <= the table's max rowid in BEFORE (rows the job added get higher rowids), the schema text,
and for the dated tables the digest of the rows dated on or before the cutoff. ``compare`` exits 0 only when each BEFORE table is present in AFTER with the same schema and the same digests;
it also lists the rows added per table. The guard's own tables (``_guard_*``) and ``sqlite_sequence`` are left out (the guard rows change by design: new seals and day checksums).
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from stockbot.data.guard.runcheck import _feed  # noqa: E402

CUTOFF = "2026-10-16"
DATED = {"market_data_lake": "trade_date", "market_data_non_eq": "trade_date", "asm_gsm_daily_snapshot": "snapshot_date", "asm_gsm_snapshot_raw": "snapshot_date", "index_gap_fill": "trade_date",
         "shares_outstanding": "effective_date"}


def digest(con, sql, args=()):
    h, n = hashlib.sha256(), 0
    for row in con.execute(sql, args):
        _feed(h, row)
        n += 1
    return n, h.hexdigest()


def proof(db, before):
    con = sqlite3.connect(f"file:{Path(db).resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    out = {"db": str(db), "cutoff": CUTOFF, "tables": {}}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        if t.startswith("_guard_") or t == "sqlite_sequence":
            continue
        t0 = time.time()
        schema = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
        total = con.execute(f'SELECT count(*), max(rowid) FROM "{t}"').fetchone()
        lim = (before["tables"][t]["max_rowid"] if before and t in before["tables"] else total[1])
        n, h = digest(con, f'SELECT * FROM "{t}" WHERE rowid<=? ORDER BY rowid', (lim if lim is not None else -1,))
        e = {"max_rowid": total[1], "rows_total": total[0], "rows_old": n, "sha256_old": h, "schema_sha256": hashlib.sha256((schema or "").encode()).hexdigest()}
        if t in DATED:
            e["rows_to_cutoff"], e["sha256_to_cutoff"] = digest(con, f'SELECT * FROM "{t}" WHERE {DATED[t]}<=? ORDER BY rowid', (CUTOFF,))
            e["rows_after_cutoff"] = con.execute(f'SELECT count(*) FROM "{t}" WHERE {DATED[t]}>?', (CUTOFF,)).fetchone()[0]
        out["tables"][t] = e
        print(f"{t}: total {total[0]} old {n} ({round(time.time() - t0, 1)} s)", flush=True)
    out["integrity_check"] = [list(r) for r in con.execute("PRAGMA integrity_check").fetchall()]
    con.close()
    return out


def compare(a, b):
    bad, added = [], {}
    for t, x in a["tables"].items():
        y = b["tables"].get(t)
        if y is None:
            bad.append(f"{t}: missing after")
            continue
        for k in ("schema_sha256", "rows_old", "sha256_old", "rows_to_cutoff", "sha256_to_cutoff"):
            if k in x and x[k] != y.get(k):
                bad.append(f"{t}: {k} {x[k]} -> {y.get(k)}")
        added[t] = y["rows_total"] - x["rows_total"]
    for t in b["tables"]:
        if t not in a["tables"]:
            bad.append(f"{t}: new table")
    return bad, added


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["proof", "compare"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--db")
    ap.add_argument("--max-rowid-from", default="none")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "proof":
        before = None if a.max_rowid_from == "none" else json.load(open(a.max_rowid_from))
        json.dump(proof(a.db, before), open(a.out, "w"), indent=1)
        return 0
    x, y = json.load(open(a.files[0])), json.load(open(a.files[1]))
    bad, added = compare(x, y)
    print("tables compared:", len(x["tables"]), "| integrity before:", x["integrity_check"], "after:", y["integrity_check"])
    for t, n in added.items():
        print(f"  {t}: identical old rows, rows added {n}" if not any(b.startswith(t + ":") for b in bad) else f"  {t}: DIFFERENT")
    print("IDENTICAL" if not bad and y["integrity_check"] == [["ok"]] else "DIFFERENCES: " + "; ".join(bad))
    return 0 if not bad and y["integrity_check"] == [["ok"]] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Per-table content proof for the guard migration (db-guard Part 2, step 6): row count and a sha256 over every column of every row of every table, plus the schema text of each table.

  py -3 docs/shared/db-guard/table_proof.py proof --db PATH --out FILE.json     (read-only: mode=ro, immutable)
  py -3 docs/shared/db-guard/table_proof.py compare BEFORE.json AFTER.json      (exit 0 only when every table the two files share is identical and nothing is missing)

The tables of the guard itself (``_guard_*``) and ``sqlite_sequence`` rows of guard tables are left out of the comparison: they are the only thing the migration adds. A table present in BEFORE
must be present in AFTER with the same schema text, row count and row digest.
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


def proof(db: str) -> dict:
    con = sqlite3.connect(f"file:{Path(db).resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    out = {"db": str(db), "tables": {}}
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for t in names:
        t0 = time.time()
        schema = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
        h, n = hashlib.sha256(), 0
        order = "" if t == "sqlite_sequence" else " ORDER BY rowid"
        for row in con.execute(f'SELECT * FROM "{t}"{order}'):
            if t == "sqlite_sequence" and str(row[0]).startswith("_guard_"):
                continue
            _feed(h, row)
            n += 1
        out["tables"][t] = {"rows": n, "sha256": h.hexdigest(), "schema_sha256": hashlib.sha256((schema or "").encode()).hexdigest(), "seconds": round(time.time() - t0, 1)}
        print(f"{t}: {n} rows {out['tables'][t]['sha256'][:16]} ({out['tables'][t]['seconds']} s)", flush=True)
    out["integrity_check"] = [list(r) for r in con.execute("PRAGMA integrity_check").fetchall()]
    with open(db, "rb") as f:
        out["journal_mode_header"] = list(f.read(20)[18:20])           # (1,1) rollback journal, (2,2) WAL
    con.close()
    return out


def compare(a: dict, b: dict) -> list:
    bad = []
    for t, x in a["tables"].items():
        if t.startswith("_guard_"):
            continue
        y = b["tables"].get(t)
        if y is None:
            bad.append(f"{t}: missing after")
            continue
        for k in ("rows", "sha256", "schema_sha256"):
            if x[k] != y[k]:
                bad.append(f"{t}: {k} {x[k]} -> {y[k]}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("proof")
    p.add_argument("--db", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare")
    p.add_argument("before")
    p.add_argument("after")
    a = ap.parse_args(argv)
    if a.cmd == "proof":
        res = proof(a.db)
        Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(f"tables {len(res['tables'])}; integrity_check {res['integrity_check']}")
        return 0
    A, B = json.loads(Path(a.before).read_text(encoding="utf-8")), json.loads(Path(a.after).read_text(encoding="utf-8"))
    bad = compare(A, B)
    shared = [t for t in A["tables"] if not t.startswith("_guard_")]
    print(f"compared {len(shared)} tables: " + ("ALL IDENTICAL" if not bad else "DIFFERENCES"))
    for x in bad:
        print("  " + x)
    print(f"integrity_check before {A['integrity_check']} after {B['integrity_check']}")
    return 0 if not bad and B["integrity_check"] == [["ok"]] else 1


if __name__ == "__main__":
    sys.exit(main())

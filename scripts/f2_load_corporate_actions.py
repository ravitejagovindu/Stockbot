"""scripts/f2_load_corporate_actions.py — F2 Step 7: append-only load of corporate actions into ``corporate_actions_log``.

Rules (reviewer, 2026-11-07):
  * ``symbol`` = the lake symbol that holds the PRE-ex-date prices (evidence ``lake_symbol``; else the ISIN map; else the feed symbol);
    the feed symbol is kept in ``notes``.
  * STRONG / WEAK / WEAK_DIRECTIONAL SPLIT/BONUS rows are stored as such; UNSUPPORTED ones are stored as ``OTHER`` (no ratio columns,
    the original ratio is in ``notes``).
  * Colliding ``OTHER`` rows (same symbol, ex-date) are merged by concatenating their notes; the merged keys are logged.
    Collisions of any other type are NOT merged: the first row is kept and the rest are logged as dropped duplicates.
  * Events listed in ``data/reference/held_events.csv`` are held out and appended later (``--include-held``) once verified.
  * A check lists every event with no lake row under its lake symbol before the ex-date.
One transaction; the per-type counts are asserted before COMMIT.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.f2_load_plan import lake_symbol      # noqa: E402

OUT = ROOT / "docs" / "data_audit"
SOURCE = "NSE corporates-corporateActions API (F2 Step 7)"
Result = namedtuple("Result", "rows merged_log dropped_duplicates held no_prior_rows")
PRICE_TIERS = ("STRONG", "WEAK", "WEAK_DIRECTIONAL")


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def build_rows(con, ev: pd.DataFrame, hold: set[tuple[str, str]] | None = None) -> Result:
    hold = hold or set()
    imap = pd.read_sql_query("select isin, symbol, canonical_symbol, first_date, last_date from isin_symbol_map", con)
    first_row = dict(con.execute("select symbol, min(trade_date) from market_data_lake group by symbol").fetchall())
    ev = ev.copy().reset_index(drop=True)
    is_held = [(r.symbol, r.ex_date) in hold for r in ev.itertuples()]
    held = ev[is_held][["symbol", "ex_date", "action_type"]].drop_duplicates()
    ev = ev[[not h for h in is_held]]
    now = datetime.now().isoformat(timespec="seconds")
    out = []
    for r in ev.itertuples():
        price = r.action_type in ("SPLIT", "BONUS")
        unsupported = price and r.tier == "UNSUPPORTED"
        stored = "OTHER" if unsupported else r.action_type
        ls = r.lake_symbol if isinstance(r.lake_symbol, str) and r.lake_symbol else lake_symbol(imap, r.isin if isinstance(r.isin, str) else None, r.symbol, r.ex_date)
        if unsupported:
            note = (f"UNSUPPORTED {r.action_type} {r.num:g}:{r.den:g} (factor {float(r.factor_logged):.4f}); feed_symbol={r.symbol}; "
                    f"{_s(r.subject)}; evidence: {_s(r.evidence)}")
            tier = "UNSUPPORTED"
        else:
            note = f"feed_symbol={r.symbol}; {_s(r.note) or _s(r.subject)}"
            tier = r.tier if price else "NOT_PRICE_MOVING"
        ratio = stored in ("SPLIT", "BONUS", "RIGHTS")
        out.append({"symbol": ls, "ex_date": r.ex_date, "action_type": stored,
                    "ratio_numerator": float(r.num) if ratio and pd.notna(r.num) else None,
                    "ratio_denominator": float(r.den) if ratio and pd.notna(r.den) else None,
                    "notes": note[:2000], "source": SOURCE, "loaded_at": now, "evidence_tier": tier,
                    "evidence": _s(r.evidence)[:1000] if price else None, "feed_symbol": r.symbol})
    df = pd.DataFrame(out)
    # ---- collisions on UNIQUE(symbol, ex_date, action_type)
    merged_log, dropped, keep = [], [], []
    for key, g in df.groupby(["symbol", "ex_date", "action_type"], sort=False):
        if len(g) == 1:
            keep.append(g.iloc[0])
        elif key[2] == "OTHER":
            m = g.iloc[0].copy()
            m["notes"] = " || ".join(g["notes"])
            m["evidence"] = " || ".join(e for e in g["evidence"] if isinstance(e, str)) or None
            m["evidence_tier"] = "UNSUPPORTED" if (g["evidence_tier"] == "UNSUPPORTED").any() else "NOT_PRICE_MOVING"
            keep.append(m)
            merged_log.append({"symbol": key[0], "ex_date": key[1], "n_rows": len(g), "feed_symbols": ",".join(sorted(set(g["feed_symbol"]))),
                               "tiers": ",".join(g["evidence_tier"]), "original_notes": " || ".join(g["notes"])})
        else:
            keep.append(g.iloc[0])
            for _, d in g.iloc[1:].iterrows():
                dropped.append({"symbol": key[0], "ex_date": key[1], "action_type": key[2], "feed_symbol": d["feed_symbol"], "notes": d["notes"]})
    rows = pd.DataFrame(keep).reset_index(drop=True)
    # ---- events with no lake row under their lake symbol before the ex-date
    miss = rows[[(first_row.get(s) is None) or (first_row[s] >= x) for s, x in zip(rows["symbol"], rows["ex_date"])]]
    no_prior = miss[["symbol", "ex_date", "action_type", "evidence_tier", "feed_symbol"]].copy()
    no_prior["reason"] = ["symbol not in the lake" if first_row.get(s) is None else f"first lake row {first_row[s]} is not before the ex-date"
                          for s in no_prior["symbol"]]
    return Result(rows, pd.DataFrame(merged_log), pd.DataFrame(dropped), held, no_prior)


COLS = ["symbol", "ex_date", "action_type", "ratio_numerator", "ratio_denominator", "notes", "source", "loaded_at", "evidence_tier", "evidence"]


def load(db: str, rows: pd.DataFrame, expect: dict | None = None) -> dict:
    """Append ``rows`` in one transaction; assert every row was new and (optionally) the per-type counts."""
    con = sqlite3.connect(db, timeout=120, isolation_level=None)
    con.execute("BEGIN IMMEDIATE")
    try:
        before = con.execute("select count(*) from corporate_actions_log").fetchone()[0]
        recs = [tuple(None if (isinstance(v, float) and pd.isna(v)) else v for v in r) for r in rows[COLS].itertuples(index=False, name=None)]
        con.executemany(f"INSERT OR IGNORE INTO corporate_actions_log ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})", recs)
        after = con.execute("select count(*) from corporate_actions_log").fetchone()[0]
        assert after - before == len(rows), f"inserted {after - before} of {len(rows)} rows (some already present)"
        by_type = dict(con.execute("select action_type, count(*) from corporate_actions_log where loaded_at = ? group by 1", (rows["loaded_at"].iloc[0],)).fetchall())
        for t, n in (expect or {}).items():
            assert by_type.get(t, 0) == n, f"{t}: loaded {by_type.get(t, 0)}, expected {n}"
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return {"before": before, "inserted": after - before, "after": after, "by_type": by_type}


def read_hold(path: Path) -> set[tuple[str, str]]:
    return {(r.symbol, r.ex_date) for r in pd.read_csv(path).itertuples()} if path.exists() else set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--evidence", default=str(ROOT / "data/reference/corporate_actions_evidence.csv"))
    ap.add_argument("--hold-file", default=str(ROOT / "data/reference/held_events.csv"))
    ap.add_argument("--include-held", action="store_true", help="load the held events too (after verification)")
    ap.add_argument("--only-held", action="store_true", help="append ONLY the held events (the table already holds the rest)")
    ap.add_argument("--expect-price-rows", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tag", default="real")
    a = ap.parse_args()
    ev = pd.read_csv(a.evidence)
    held_keys = read_hold(Path(a.hold_file))
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=120)
    res = build_rows(con, ev, hold=set() if (a.include_held or a.only_held) else held_keys)
    con.close()
    rows = res.rows
    if a.only_held:
        rows = rows[[(f, x) in held_keys for f, x in zip(rows["feed_symbol"], rows["ex_date"])]]
    OUT.mkdir(parents=True, exist_ok=True)
    res.merged_log.to_csv(OUT / f"merged_other_keys_{a.tag}.csv", index=False)
    res.dropped_duplicates.to_csv(OUT / f"dropped_duplicate_rows_{a.tag}.csv", index=False)
    res.no_prior_rows.to_csv(OUT / f"events_without_prior_rows_{a.tag}.csv", index=False)
    counts = rows.groupby("action_type").size().to_dict()
    price = counts.get("SPLIT", 0) + counts.get("BONUS", 0)
    print("rows to load by stored type:", counts, "| total", len(rows), "| price-moving", price)
    print("merged OTHER keys:", len(res.merged_log), "| dropped non-OTHER duplicates:", len(res.dropped_duplicates),
          "| held out:", len(res.held), "| events with no lake row before the ex-date:", len(res.no_prior_rows))
    print(res.no_prior_rows.groupby("action_type").size().to_dict())
    if a.expect_price_rows is not None:
        assert price == a.expect_price_rows, f"price-moving rows {price} != expected {a.expect_price_rows}"
    if a.dry_run:
        return 0
    rep = load(a.db, rows, expect=counts)
    print("LOADED:", rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())

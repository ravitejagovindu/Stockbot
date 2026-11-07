"""scripts/f2_copy_detector.py — flag any date whose rows copy the previous session (holiday copies).

A date is a COPY when, for the symbols present on both days, the close AND volume are identical for at least
``--share`` (default 0.9) of them.  Read-only.  Works on any table with (symbol, trade_date, close_raw, volume_raw):
``--table market_data_lake_staging`` or ``--table market_data_lake`` (index symbols excluded).

Also compares the table's dates with the Nifty dates (NIFTY50_INDEX rows of the lake) and the approved special
sessions (data/reference/special_sessions.csv) and reports both directions (dates without Nifty, Nifty dates without rows).

Writes docs/data_audit/copy_detector_<table>.csv and exits non-zero if anything is flagged.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data_audit"
SPECIAL = ROOT / "data" / "reference" / "special_sessions.csv"
IDX = ("NIFTY50_INDEX", "INDIA_VIX")


def special_sessions() -> set[str]:
    if not SPECIAL.exists():
        return set()
    return set(pd.read_csv(SPECIAL, comment="#")["date"].astype(str))


def copy_dates(con: sqlite3.Connection, table: str, share: float = 0.9) -> pd.DataFrame:
    dates = [r[0] for r in con.execute(f"select distinct trade_date from {table} order by 1")]
    rows = []
    for prev, d in zip(dates, dates[1:]):
        n, eq = con.execute(
            f"select count(*), sum(a.close_raw = b.close_raw and a.volume_raw = b.volume_raw) from {table} a "
            f"join {table} b on b.symbol = a.symbol and b.trade_date = ? where a.trade_date = ? "
            f"and a.symbol not in ('NIFTY50_INDEX','INDIA_VIX')", (prev, d)).fetchone()
        if n and eq and eq / n >= share:
            rows.append({"table": table, "trade_date": d, "previous_session": prev, "symbols_compared": n,
                         "identical": int(eq), "identical_share": round(eq / n, 4)})
    return pd.DataFrame(rows, columns=["table", "trade_date", "previous_session", "symbols_compared",
                                       "identical", "identical_share"])


def calendar_check(con: sqlite3.Connection, table: str) -> dict:
    nifty = {r[0] for r in con.execute("select trade_date from market_data_lake where symbol='NIFTY50_INDEX'")}
    have = {r[0] for r in con.execute(f"select distinct trade_date from {table}")}
    lo = min(nifty) if nifty else None
    special = special_sessions()
    in_range = {d for d in have if lo and d >= lo}
    return {"nifty_start": lo,
            "dates_without_nifty_and_not_special": sorted(in_range - nifty - special),
            "nifty_dates_without_rows": sorted(d for d in nifty if d not in have and d <= max(have))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--table", default="market_data_lake_staging")
    ap.add_argument("--share", type=float, default=0.9)
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    cd = copy_dates(con, a.table, a.share)
    OUT.mkdir(parents=True, exist_ok=True)
    cd.to_csv(OUT / f"copy_detector_{a.table}.csv", index=False)
    cal = calendar_check(con, a.table)
    print(f"{a.table}: {len(cd)} copy dates")
    if len(cd):
        print(cd.to_string(index=False))
    print("Nifty starts:", cal["nifty_start"])
    print("dates in the table (from Nifty start) without a Nifty row and not special:", len(cal["dates_without_nifty_and_not_special"]),
          cal["dates_without_nifty_and_not_special"][:40])
    print("Nifty dates without rows in the table:", len(cal["nifty_dates_without_rows"]), cal["nifty_dates_without_rows"][:40])
    return 1 if len(cd) else 0


if __name__ == "__main__":
    sys.exit(main())

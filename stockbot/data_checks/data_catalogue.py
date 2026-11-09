"""stockbot/data_checks/data_catalogue.py - read-only generator of docs/guides/data_catalogue.md: every fact in it is MEASURED from the lake at run time.

``py scripts/gen_data_catalogue.py [--out PATH] [--no-coverage]``

What it writes (all from ``sqlite_master`` and SELECTs; the lake is opened with ``stockbot.data.lake.open_lake`` = ``mode=ro`` + ``query_only``):
  1. the object list (tables, views, indexes, triggers) with the CREATE statement of each trigger;
  2. per table: columns (type, NOT NULL, default, primary-key position, measured non-null count and one example), indexes, row count, first/last value of the
     table's main date column, distinct symbols, three sample rows (first, second and last by rowid);
  3. coverage tables: rows, sessions and symbols of ``market_data_lake`` per year; corporate actions by type and source; earnings and ASM/GSM snapshot coverage.
Nothing is written to the database. The only file written is the markdown output. The measurement time and the file's size and mtime are printed at the top,
so a reader can tell how old the numbers are. DATA_GUIDE.md links this file for the numbers; ``tests/unit/test_guides_consistent.py`` checks that every table
in ``sqlite_master`` is described in the guide.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from stockbot.config.paths import lake_path, repo_root
from stockbot.data.lake import open_lake

# first match wins: the date column used for "first/last" of a table
DATE_COLUMNS = ("trade_date", "ex_date", "snapshot_date", "event_date", "effective_date", "eval_date", "run_date", "transaction_date", "entry_date", "bm_date",
                "listing_date", "first_date", "run_at", "at", "fetched_at", "created_at")
INDEX_SYMBOLS = ("NIFTY50_INDEX", "INDIA_VIX")
# payload columns that hold whole API responses: counting their non-null rows would read every payload page, so they are reported as not counted
BIG_COLUMNS = {("earnings_api_raw", "body_zlib"), ("asm_gsm_snapshot_raw", "body")}
# on a table above this many rows only index-assisted facts are measured (the file is read from a slow disk; a full scan of a multi-million-row table takes minutes)
BIG_TABLE_ROWS = 1_000_000
NOT_COUNTED = "not counted (large table)"


def _q(con: sqlite3.Connection, sql: str, args: Sequence = ()) -> list:
    return con.execute(sql, args).fetchall()


def objects(con) -> list:
    return _q(con, "select type, name, tbl_name, coalesce(sql, '') from sqlite_master order by type, name")


def table_names(con) -> list:
    return [r[0] for r in _q(con, "select name from sqlite_master where type in ('table','view') and name not like 'sqlite_%' order by name")]


def _short(v, n: int = 48) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    s = str(v).replace("\n", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 3] + "..."


def table_facts(con, name: str) -> dict:
    cols = _q(con, f'pragma table_xinfo("{name}")')
    names = [c[1] for c in cols]
    f: dict = {"name": name, "columns": cols}
    f["rows"] = _q(con, f'select count(*) from "{name}"')[0][0]
    big = f["rows"] > BIG_TABLE_ROWS
    small = [c for c in names if (name, c) not in BIG_COLUMNS and not big]
    counts = _q(con, "select " + ",".join(f'count("{c}")' for c in small) + f' from "{name}"')[0] if f["rows"] and small else [0] * len(small)
    f["nonnull"] = {c: (NOT_COUNTED if big else "not counted") if (big or (name, c) in BIG_COLUMNS) else None for c in names}
    f["nonnull"].update(dict(zip(small, counts)))
    f["big"] = big
    sample = []
    if f["rows"]:
        first = _q(con, f'select * from "{name}" order by rowid limit 2') if _has_rowid(con, name) else _q(con, f'select * from "{name}" limit 2')
        last = _q(con, f'select * from "{name}" order by rowid desc limit 1') if _has_rowid(con, name) else []
        sample = list(first) + [r for r in last if r not in first]
    f["sample"] = sample
    f["example"] = {}
    for i, c in enumerate(names):
        ex = next((r[i] for r in sample if r[i] is not None), None)
        if ex is None and isinstance(f["nonnull"][c], int) and f["nonnull"][c]:
            r = _q(con, f'select "{c}" from "{name}" where "{c}" is not null limit 1')
            ex = r[0][0] if r else None
        f["example"][c] = ex
    f["indexes"] = []
    for idx in _q(con, f'pragma index_list("{name}")'):
        f["indexes"].append((idx[1], bool(idx[2]), idx[3], [x[2] for x in _q(con, f'pragma index_info("{idx[1]}")')]))
    leading = {cols[0] for _, _, _, cols in f["indexes"] if cols}
    f["date_col"] = next((c for c in DATE_COLUMNS if c in names), None)
    f["date_range"], f["distinct_dates"], f["symbols"] = None, None, None
    dc = f["date_col"]
    if dc and f["rows"] and (not big or dc in leading):
        f["date_range"] = _q(con, f'select min("{dc}"), max("{dc}") from "{name}"')[0]
        # a DATE column holds plain 'YYYY-MM-DD' text: count it directly (uses the index); timestamp columns are cut to the day
        expr = f'"{dc}"' if dc.endswith("_date") else f'substr("{dc}",1,10)'
        f["distinct_dates"] = _q(con, f'select count(distinct {expr}) from "{name}"')[0][0]
    if "symbol" in names and f["rows"] and (not big or "symbol" in leading):
        f["symbols"] = _q(con, f'select count(distinct symbol) from "{name}"')[0][0]
    return f


def _has_rowid(con, name: str) -> bool:
    try:
        con.execute(f'select rowid from "{name}" limit 1')
        return True
    except sqlite3.OperationalError:
        return False


def coverage(con) -> dict:
    out: dict = {}
    idx = ",".join(f"'{s}'" for s in INDEX_SYMBOLS)
    out["lake_by_year"] = _q(con, f"select substr(trade_date,1,4) y, count(*), count(distinct trade_date), count(distinct case when symbol not in ({idx}) then symbol end) "
                                  f"from market_data_lake group by y order by y")
    out["index_rows"] = _q(con, f"select symbol, count(*), min(trade_date), max(trade_date) from market_data_lake where symbol in ({idx}) group by symbol")
    out["equity_rows"] = _q(con, f"select count(*), count(distinct symbol), min(trade_date), max(trade_date) from market_data_lake where symbol not in ({idx})")
    out["symbol_class"] = _q(con, f"""select case when n_last_gap>0 then 'last bar before the last session of the lake' else 'trades on the last session' end cls, count(*), min(first_d), max(last_d)
                                      from (select symbol, min(trade_date) first_d, max(trade_date) last_d,
                                                   (select max(trade_date) from market_data_lake) > max(trade_date) n_last_gap
                                            from market_data_lake where symbol not in ({idx}) group by symbol) group by cls""")
    out["actions_by_type"] = _q(con, "select action_type, count(*), count(distinct symbol), min(ex_date), max(ex_date) from corporate_actions_log group by action_type order by 2 desc")
    out["actions_by_source"] = _q(con, "select coalesce(source,'(null)'), coalesce(evidence_tier,'(null)'), count(*) from corporate_actions_log group by 1,2 order by 3 desc")
    out["fetch_log"] = _q(con, "select status, count(*), min(trade_date), max(trade_date) from bhavcopy_fetch_log group by status order by 2 desc")
    # `source` is not in any index, so a whole-table breakdown would read the entire table: measure it where an index narrows the rows
    out["lake_sources_index"] = _q(con, f"select coalesce(source,'(null)'), symbol, count(*), min(trade_date), max(trade_date) from market_data_lake where symbol in ({idx}) group by 1, 2 order by 2, 3 desc")
    out["lake_sources_edge_days"] = _q(con, f"select trade_date, substr(coalesce(source,'(null)'),1,60), count(*) from market_data_lake where symbol not in ({idx}) and trade_date in "
                                            f"((select min(trade_date) from market_data_lake), (select max(trade_date) from market_data_lake)) group by 1, 2 order by 1, 3 desc")
    out["earnings_by_year"] = _q(con, "select substr(bm_date,1,4) y, count(*), count(distinct symbol) from earnings_board_meeting where is_results_meeting=1 and bm_date is not null group by y order by y")
    out["earnings_symbols"] = _q(con, "select (select count(distinct lake_symbol) from earnings_symbol_map), (select count(distinct query_symbol) from earnings_symbol_map), "
                                      "(select count(distinct query_symbol) from earnings_api_raw where row_count>0)")
    out["asm_days"] = _q(con, "select snapshot_date, framework, count(*) from asm_gsm_daily_snapshot group by 1,2 order by 1,2")
    out["asm_log"] = _q(con, "select run_at, snapshot_date, endpoint, outcome, substr(coalesce(detail,''),1,80) from asm_gsm_snapshot_log order by run_at")
    return out


def _md_table(head: Sequence[str], rows: Sequence[Sequence]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(_short(x, 60) for x in r) + " |")
    return "\n".join(lines)


def render(con, db_path: Path, with_coverage: bool = True) -> str:
    st = db_path.stat()
    out = ["# finsight.db - machine-measured catalogue", "",
           f"Generated by `py scripts/gen_data_catalogue.py` (`stockbot/data_checks/data_catalogue.py`). **Read-only**: the lake is opened with `mode=ro`.",
           f"* Measured at: {datetime.now().strftime('%Y-%m-%d %H:%M')} (local time)",
           f"* File: `{db_path.name}`, size {st.st_size:,} bytes, modified {datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}", "",
           "Every number below was counted from the file at the time above; run the script again to refresh.", "", "## 1. Objects in `sqlite_master`", ""]
    objs = objects(con)
    out.append(_md_table(["type", "name", "table"], [(t, n, tb) for t, n, tb, _ in objs]))
    trig = [(n, s) for t, n, _, s in objs if t == "trigger"]
    for n, s in trig:
        out += ["", f"Trigger `{n}`:", "", "```sql", s.strip(), "```"]
    views = [n for t, n, _, _ in objs if t == "view"]
    out += ["", f"Views: {', '.join(views) if views else 'none'}.", "", "## 2. Tables", ""]
    names = table_names(con)
    facts = []
    for n in names:
        print(f"measuring {n} ...", file=sys.stderr, flush=True)
        facts.append(table_facts(con, n))
    out.append(_md_table(["table", "rows", "main date column", "first", "last", "distinct dates", "distinct symbols"],
                         [(f["name"], f"{f['rows']:,}", f["date_col"] or "-", (f["date_range"] or ("-", "-"))[0], (f["date_range"] or ("-", "-"))[1],
                           f["distinct_dates"] if f["distinct_dates"] is not None else ("-" if not f["big"] else "n/c"), f["symbols"] if f["symbols"] is not None else ("-" if not f["big"] else "n/c")) for f in facts]))
    for f in facts:
        out += ["", f"### `{f['name']}`", "", f"{f['rows']:,} rows."]
        if f["date_range"]:
            out.append(f"Main date column `{f['date_col']}`: {f['date_range'][0]} to {f['date_range'][1]} ({f['distinct_dates']} distinct dates)." + (f" {f['symbols']} distinct symbols." if f["symbols"] is not None else ""))
        out += ["", _md_table(["#", "column", "type", "NOT NULL", "default", "pk", "non-null rows", "example"],
                              [(c[0], c[1], c[2] or "-", "yes" if c[3] else "no", c[4] if c[4] is not None else "-", c[5] or "-", (f"{f['nonnull'][c[1]]:,}" if isinstance(f["nonnull"][c[1]], int) else f["nonnull"][c[1]]), _short(f["example"][c[1]]))
                               for c in f["columns"]])]
        if f["indexes"]:
            out += ["", "Indexes: " + "; ".join(f"`{n}` ({'unique, ' if u else ''}{', '.join(cols)})" for n, u, _, cols in f["indexes"]) + "."]
        else:
            out += ["", "Indexes: none."]
        if f["sample"]:
            out += ["", "Sample rows (first two and last by rowid):", "", _md_table([c[1] for c in f["columns"]], f["sample"])]
    if with_coverage:
        print("measuring coverage ...", file=sys.stderr, flush=True)
        cov = coverage(con)
        out += ["", "## 3. Coverage", "", "### `market_data_lake` per calendar year", "",
                _md_table(["year", "rows", "sessions (distinct trade_date)", "distinct equity symbols"], cov["lake_by_year"]), "",
                "Index series:", "", _md_table(["symbol", "rows", "first", "last"], cov["index_rows"]), "",
                "Equity rows (index series excluded): rows, distinct symbols, first date, last date:", "", _md_table(["rows", "symbols", "first", "last"], cov["equity_rows"]), "",
                "Equity symbols by whether they trade on the lake's last session:", "", _md_table(["class", "symbols", "earliest first bar", "latest last bar"], cov["symbol_class"]), "",
                "`market_data_lake.source` for the index series (Nifty 50, India VIX):", "", _md_table(["source", "symbol", "rows", "first", "last"], cov["lake_sources_index"]), "",
                "`market_data_lake.source` for equity rows on the first and the last date of the lake (a whole-table breakdown is not measured: `source` is not indexed):", "", _md_table(["trade_date", "source (first 60 characters)", "rows"], cov["lake_sources_edge_days"]), "",
                "### `bhavcopy_fetch_log`", "", _md_table(["status", "rows", "first", "last"], cov["fetch_log"]), "",
                "### `corporate_actions_log`", "", "By action_type:", "", _md_table(["action_type", "rows", "symbols", "first ex_date", "last ex_date"], cov["actions_by_type"]), "",
                "By source and evidence tier:", "", _md_table(["source", "evidence_tier", "rows"], cov["actions_by_source"]), "",
                "### Earnings", "", "Results board meetings (`is_results_meeting=1`) by year of `bm_date`:", "", _md_table(["year", "meetings", "lake symbols"], cov["earnings_by_year"]), "",
                "Symbol map: lake symbols mapped, query symbols mapped, query symbols with at least one API response that had rows:", "", _md_table(["lake symbols", "query symbols", "query symbols with rows"], cov["earnings_symbols"]), "",
                "### ASM/GSM daily snapshot (in this file)", "", _md_table(["snapshot_date", "framework", "rows"], cov["asm_days"]) if cov["asm_days"] else "No rows.", "",
                "Snapshot log:", "", _md_table(["run_at", "snapshot_date", "endpoint", "outcome", "detail"], cov["asm_log"]) if cov["asm_log"] else "No rows."]
    return "\n".join(out) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Write docs/guides/data_catalogue.md from the lake (read-only on the database).")
    ap.add_argument("--out", help="output markdown file (default: docs/guides/data_catalogue.md)")
    ap.add_argument("--db", help="lake file (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--no-coverage", action="store_true", help="skip the coverage section (faster)")
    a = ap.parse_args(argv)
    db = Path(a.db) if a.db else lake_path()
    out = Path(a.out) if a.out else repo_root() / "docs" / "guides" / "data_catalogue.md"
    con = open_lake(db)
    try:
        text = render(con, db, with_coverage=not a.no_coverage)
    finally:
        con.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

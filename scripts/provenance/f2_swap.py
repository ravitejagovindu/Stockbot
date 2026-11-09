"""scripts/provenance/f2_swap.py — F2: replace the Yahoo-adjusted lake rows with raw NSE Bhavcopy rows (three separate transactions).

    py -3 -m scripts.provenance.f2_swap schema   --db finsight.db      # 1. schema-only migrations (F3 columns, F2 columns, archive table, relaxed CHECK)
    py -3 -m scripts.provenance.f2_swap swap     --db finsight.db      # 2. archive + replace 2020-01-01..2026-09-30, special sessions, index gaps
    py -3 -m scripts.provenance.f2_swap map      --db finsight.db      # 3. ISIN -> canonical symbol relabel (all years), source_symbol kept
    py -3 -m scripts.provenance.f2_swap checks   --db finsight.db      # read-only post-swap report

Every stage is one transaction; any failed assertion rolls the whole stage back.  Nothing is ever deleted without first being
copied to ``market_data_lake_yahoo_archive``.  ``source_symbol`` NULL means "symbol is the traded symbol".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
INDEX_SYMBOLS = ("NIFTY50_INDEX", "INDIA_VIX")
WINDOW = ("2020-01-01", "2026-09-30")
LAKE_COLS = ["id", "symbol", "trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "exchange", "created_at"]
F3_COLUMNS = {
    "active_positions": ["risk_inr FLOAT", "applied_corp_actions TEXT", "manual_review_ca VARCHAR(200)"],
    "trade_analytics_log": ["risk_inr FLOAT", "excluded_ca BOOLEAN NOT NULL DEFAULT 0"],
}
CA_DDL = """CREATE TABLE corporate_actions_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT    NOT NULL,
    ex_date             DATE    NOT NULL,
    action_type         TEXT    NOT NULL CHECK(action_type IN ('SPLIT','BONUS','DIVIDEND','RIGHTS','MERGER','DEMERGER','OTHER')),
    ratio_numerator     REAL,
    ratio_denominator   REAL,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source              TEXT,
    loaded_at           TEXT,
    evidence_tier       TEXT,
    evidence            TEXT,
    UNIQUE(symbol, ex_date, action_type)
)"""


def _con(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=120, isolation_level=None)      # explicit BEGIN/COMMIT
    c.execute("PRAGMA foreign_keys=OFF")
    return c


def _cols(c, table):
    return [r[1] for r in c.execute(f"pragma table_info({table})")]


def checksum(db: str, where: str) -> tuple[int, str]:
    """(row count, sha256) over (coalesce(source_symbol, symbol), date, OHLCV) for rows matching ``where``, ordered by id."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=120)
    try:
        sym = "coalesce(source_symbol, symbol)" if "source_symbol" in _cols(c, "market_data_lake") else "symbol"
        h, n = hashlib.sha256(), 0
        for r in c.execute(f"select {sym}, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw from market_data_lake "
                           f"where {where} order by id"):
            h.update(repr(r).encode())
            n += 1
        return n, h.hexdigest()
    finally:
        c.close()


# ---------------------------------------------------------------- 1. schema
def stage_schema(db: str) -> dict:
    c = _con(db)
    added = []
    c.execute("BEGIN IMMEDIATE")
    try:
        have = _cols(c, "market_data_lake")
        for col in ("source TEXT", "loaded_at TEXT", "source_symbol TEXT"):
            if col.split()[0] not in have:
                c.execute(f"ALTER TABLE market_data_lake ADD COLUMN {col}")
                added.append("market_data_lake." + col.split()[0])
        c.execute("CREATE TABLE IF NOT EXISTS market_data_lake_yahoo_archive ("
                  "id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, trade_date DATE NOT NULL, open_raw REAL NOT NULL, high_raw REAL NOT NULL, "
                  "low_raw REAL NOT NULL, close_raw REAL NOT NULL, volume_raw BIGINT NOT NULL, exchange TEXT, created_at TIMESTAMP, "
                  "archived_at TEXT, UNIQUE(symbol, trade_date))")
        for table, cols in F3_COLUMNS.items():
            have = _cols(c, table)
            for col in cols:
                if col.split()[0] not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
                    added.append(f"{table}.{col.split()[0]}")
        sql = c.execute("select sql from sqlite_master where name='corporate_actions_log'").fetchone()[0]
        if "DEMERGER" not in sql:                                    # rebuild with relaxed CHECK + provenance columns
            old = _cols(c, "corporate_actions_log")
            c.execute("ALTER TABLE corporate_actions_log RENAME TO corporate_actions_log_old")
            c.execute("DROP INDEX IF EXISTS idx_corp_symbol_date")
            c.execute(CA_DDL)
            cl = ", ".join(old)
            c.execute(f"INSERT INTO corporate_actions_log ({cl}) SELECT {cl} FROM corporate_actions_log_old")
            n_old = c.execute("select count(*) from corporate_actions_log_old").fetchone()[0]
            assert n_old == c.execute("select count(*) from corporate_actions_log").fetchone()[0], "corporate_actions_log copy lost rows"
            c.execute("DROP TABLE corporate_actions_log_old")
            c.execute("CREATE INDEX idx_corp_symbol_date ON corporate_actions_log(symbol, ex_date)")
            added.append("corporate_actions_log: CHECK relaxed (+DEMERGER, OTHER), +source, loaded_at, evidence_tier, evidence")
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
    return {"changes": added}


# ---------------------------------------------------------------- 2. swap
def stage_swap(db: str, window=WINDOW, special_csv: Path | None = None, expect_special: int | None = None,
               expect_index: int | None = None) -> dict:
    special_csv = special_csv or ROOT / "data" / "reference" / "special_sessions.csv"
    lo, hi = window
    specials = sorted(d for d in pd.read_csv(special_csv, comment="#").query("kind == 'special_session'")["date"].astype(str) if d < lo)
    now = datetime.now().isoformat(timespec="seconds")
    ph = ",".join("?" * len(INDEX_SYMBOLS))
    c = _con(db)
    rep: dict = {}
    c.execute("BEGIN IMMEDIATE")
    try:
        max_id = c.execute("select max(id) from market_data_lake").fetchone()[0]
        rep["max_id_before"] = max_id
        cols = "id, symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange, created_at"
        c.execute(f"INSERT INTO market_data_lake_yahoo_archive ({cols}, archived_at) SELECT {cols}, ? FROM market_data_lake "
                  f"WHERE trade_date BETWEEN ? AND ? AND symbol NOT IN ({ph})", (now, lo, hi, *INDEX_SYMBOLS))
        rep["archived"] = c.execute("select count(*) from market_data_lake_yahoo_archive").fetchone()[0]
        c.execute(f"DELETE FROM market_data_lake WHERE trade_date BETWEEN ? AND ? AND symbol NOT IN ({ph})", (lo, hi, *INDEX_SYMBOLS))
        left = c.execute(f"select count(*) from market_data_lake where trade_date between ? and ? and symbol not in ({ph})",
                         (lo, hi, *INDEX_SYMBOLS)).fetchone()[0]
        assert left == 0, f"{left} window rows left after delete"
        ins = ("INSERT INTO market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange, "
               "created_at, source, loaded_at) SELECT symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, 'NSE', ?, "
               "'nse_bhavcopy_raw', ? FROM market_data_lake_staging")
        c.execute(ins + " WHERE trade_date BETWEEN ? AND ? AND series = 'EQ'", (now, now, lo, hi))
        rep["inserted_window"] = c.execute("select count(*) from market_data_lake where source='nse_bhavcopy_raw' and trade_date between ? and ?",
                                           (lo, hi)).fetchone()[0]
        n_stage = c.execute("select count(*) from market_data_lake_staging where trade_date between ? and ? and series='EQ'", (lo, hi)).fetchone()[0]
        assert rep["inserted_window"] == n_stage, f"inserted {rep['inserted_window']} != staged {n_stage}"
        # pre-window special sessions (append-only)
        q = ",".join("?" * len(specials)) or "''"
        c.execute(ins + f" WHERE trade_date IN ({q}) AND series='EQ' AND NOT EXISTS (select 1 from market_data_lake m "
                  f"where m.symbol = market_data_lake_staging.symbol and m.trade_date = market_data_lake_staging.trade_date)",
                  (now, now, *specials))
        rep["special_inserted"] = c.execute("select count(*) from market_data_lake where source='nse_bhavcopy_raw' and trade_date < ?", (lo,)).fetchone()[0]
        if expect_special is not None:
            assert rep["special_inserted"] == expect_special, f"special-session rows {rep['special_inserted']} != expected {expect_special}"
        # Nifty / VIX gap fill (append-only, labelled)
        c.execute("INSERT INTO market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange, created_at, source, loaded_at) "
                  "SELECT symbol, trade_date, open_raw, high_raw, low_raw, close_raw, 0, 'NSE', ?, source, ? FROM index_gap_fill g "
                  "WHERE NOT EXISTS (select 1 from market_data_lake m where m.symbol=g.symbol and m.trade_date=g.trade_date)", (now, now))
        rep["index_inserted"] = c.execute(f"select count(*) from market_data_lake where symbol in ({ph}) and loaded_at = ?", (*INDEX_SYMBOLS, now)).fetchone()[0]
        if expect_index is not None:
            assert rep["index_inserted"] == expect_index, f"index rows {rep['index_inserted']} != expected {expect_index}"
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
    return rep


# ---------------------------------------------------------------- 3. symbol mapping
def stage_map(db: str, map_csv: Path | None = None) -> dict:
    map_csv = map_csv or ROOT / "data" / "reference" / "isin_symbol_map.csv"
    m = pd.read_csv(map_csv)
    ren = m[(m["isin_class"] == "pure_rename") & (m["symbol"] != m["canonical_symbol"])]
    before = checksum(db, "1=1")
    c = _con(db)
    rep = {"rows_before": before[0], "checksum_before": before[1], "segments": len(ren)}
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute("CREATE TABLE IF NOT EXISTS isin_symbol_map (isin TEXT, symbol TEXT, first_date TEXT, last_date TEXT, "
                  "isin_class TEXT, canonical_symbol TEXT, applied_at TEXT)")
        if not c.execute("select count(*) from isin_symbol_map").fetchone()[0]:
            now = datetime.now().isoformat(timespec="seconds")
            c.executemany("INSERT INTO isin_symbol_map VALUES (?,?,?,?,?,?,?)",
                          [(r.isin, r.symbol, r.first_date, r.last_date, r.isin_class, r.canonical_symbol, now) for r in m.itertuples()])
        n = 0
        for r in ren.itertuples():
            cur = c.execute("UPDATE market_data_lake SET source_symbol = symbol, symbol = ? WHERE symbol = ? "
                            "AND trade_date BETWEEN ? AND ? AND source_symbol IS NULL",
                            (r.canonical_symbol, r.symbol, r.first_date, r.last_date))
            n += cur.rowcount
        rep["rows_relabelled"] = n
        dup = c.execute("select count(*) from (select symbol, trade_date from market_data_lake group by 1,2 having count(*) > 1)").fetchone()[0]
        assert dup == 0, f"{dup} duplicate (symbol, date) pairs after mapping"
        after = checksum_in_tx(c)
        assert after[0] == before[0], f"row count changed {before[0]} -> {after[0]}"
        assert after[1] == before[1], "checksum over (source_symbol, date, OHLCV) changed"
        rep.update(rows_after=after[0], checksum_after=after[1])
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
    return rep


def checksum_in_tx(c) -> tuple[int, str]:
    h, n = hashlib.sha256(), 0
    for r in c.execute("select coalesce(source_symbol, symbol), trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw "
                       "from market_data_lake order by id"):
        h.update(repr(r).encode())
        n += 1
    return n, h.hexdigest()


# ---------------------------------------------------------------- pre-swap guard + CLI
def verify_backup(backup: Path) -> str:
    side = Path(str(backup) + ".sha256")
    want = side.read_text().split()[0].lower()
    h = hashlib.sha256()
    with open(backup, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    assert h.hexdigest() == want, f"backup checksum mismatch: {h.hexdigest()} != {want}"
    c = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    ok = c.execute("PRAGMA quick_check").fetchone()[0]
    c.close()
    assert ok == "ok", f"backup quick_check: {ok}"
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["schema", "swap", "map", "verify-backup"])
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--backup", default=r"F:\Projects\Ravi\Backups\finsight_pre_F2_2026-11-06.db")
    ap.add_argument("--expect-special", type=int, default=8034)
    ap.add_argument("--expect-index", type=int, default=None)
    ap.add_argument("--pre-swap-checksums", help="json file to write/read pre-swap untouched-row checksums")
    a = ap.parse_args()
    if a.stage == "verify-backup":
        print("backup ok, sha256", verify_backup(Path(a.backup)))
    elif a.stage == "schema":
        print(json.dumps(stage_schema(a.db), indent=1))
    elif a.stage == "swap":
        print("backup ok, sha256", verify_backup(Path(a.backup)))
        c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        max_id = c.execute("select max(id) from market_data_lake").fetchone()[0]
        n_index = c.execute("select count(*) from index_gap_fill").fetchone()[0]
        c.close()
        groups = {"pre2020": f"trade_date < '{WINDOW[0]}' and id <= {max_id}",
                  "post_window": f"trade_date > '{WINDOW[1]}'",
                  "index_existing": f"symbol in {INDEX_SYMBOLS} and id <= {max_id}"}
        before = {k: checksum(a.db, w) for k, w in groups.items()}
        rep = stage_swap(a.db, expect_special=a.expect_special, expect_index=a.expect_index if a.expect_index is not None else n_index)
        after = {k: checksum(a.db, w) for k, w in groups.items()}
        rep["untouched_checksums_equal"] = {k: before[k] == after[k] for k in groups}
        rep["untouched_rows"] = {k: before[k][0] for k in groups}
        print(json.dumps(rep, indent=1, default=str))
        assert all(rep["untouched_checksums_equal"].values()), "untouched rows changed — investigate (the stage is already committed!)"
    elif a.stage == "map":
        print(json.dumps(stage_map(a.db), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

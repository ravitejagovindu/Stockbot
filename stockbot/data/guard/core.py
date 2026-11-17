"""The database guard (db-guard design R2, R3, R5, R6): sealed history and logged corrections, enforced INSIDE the database with triggers, so it holds for any script.

State (all in the same file, ``_guard_*``):  ``_guard_registry`` (class of every table), ``_guard_seal`` (sealed-through date per DATED table), ``_guard_day_checksum`` (R6, one row per sealed day),
``_guard_window`` (the one correction window), ``_guard_counter`` (corrections, only ever increases), ``_guard_change_log`` (every change made while a window is open, never edited).

Triggers (names ``g_*``): a DATED table refuses UPDATE, DELETE and an INSERT dated on or before its sealed date; an INSERT_ONLY table refuses UPDATE, DELETE and an insert that would replace a row
with a different one (an identical re-insert is ignored, so idempotent writers keep working). While a correction window is open (and not expired) the refusals are lifted and every changed row
goes to the change log. Reads are never touched: a trigger fires only on INSERT, UPDATE or DELETE.

What it cannot prevent is listed in docs/shared/db-guard/GUARD.md (DROP TRIGGER / DROP TABLE, replacing the file, opening a window with a plain UPDATE: that one still leaves a counter change and a log entry).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import Iterable, Optional

from stockbot.data.guard.registry import DATED, EXEMPT, GUARD_PREFIX, INSERT_ONLY, RULES, Rule, is_guard_object

WINDOW_MINUTES = 15            # hard maximum life of a correction window
NEVER = "0000-00-00"           # sealed_through of a DATED table with nothing sealed
YES_REMOVE = "--yes-remove-guard"

NOW = "strftime('%Y-%m-%dT%H:%M:%f','now')"
WIN = f"((SELECT is_open FROM _guard_window WHERE id=1)=1 AND (SELECT expires_at FROM _guard_window WHERE id=1) > {NOW})"


class GuardError(Exception):
    pass


class UnregisteredTables(GuardError):
    pass


STATE_TABLES = {
    "_guard_registry": "CREATE TABLE _guard_registry(tbl TEXT PRIMARY KEY, class TEXT NOT NULL, date_col TEXT, key_cols TEXT, volatile_cols TEXT, reason TEXT)",
    "_guard_seal": "CREATE TABLE _guard_seal(tbl TEXT PRIMARY KEY, sealed_through TEXT NOT NULL, sealed_at TEXT)",
    "_guard_day_checksum": "CREATE TABLE _guard_day_checksum(tbl TEXT NOT NULL, day TEXT NOT NULL, n_rows INTEGER NOT NULL, sha256 TEXT NOT NULL, sealed_at TEXT, PRIMARY KEY(tbl, day))",
    "_guard_window": "CREATE TABLE _guard_window(id INTEGER PRIMARY KEY CHECK(id=1), is_open INTEGER NOT NULL, reason TEXT, opened_at TEXT, expires_at TEXT)",
    "_guard_counter": "CREATE TABLE _guard_counter(id INTEGER PRIMARY KEY CHECK(id=1), corrections INTEGER NOT NULL)",
    "_guard_change_log": ("CREATE TABLE _guard_change_log(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, tbl TEXT, op TEXT, key TEXT, before_json TEXT, after_json TEXT, "
                          "reason TEXT, correction_no INTEGER)"),
}


# ------------------------------------------------------------------------------------------------------------------------------------------ helpers
def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def tables_in(con) -> list:
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def user_tables(con) -> list:
    return [t for t in tables_in(con) if not is_guard_object(t)]


def installed(con) -> bool:
    return "_guard_registry" in tables_in(con)


def columns(con, table: str) -> list:
    return [(r[1], (r[2] or "").upper()) for r in con.execute(f"PRAGMA table_info({q(table)})")]


@contextmanager
def tx(con):
    """One transaction: BEGIN IMMEDIATE unless the caller already has one (then it is theirs to commit)."""
    if con.in_transaction:
        yield
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def _json(prefix: str, cols: list) -> str:
    parts = []
    for name, typ in cols:
        ref = f"{prefix}.{q(name)}"
        parts.append(f"'{name}', " + (f"hex({ref})" if "BLOB" in typ else ref))
    return "json_object(" + ", ".join(parts) + ")"


def _key_text(prefix: str, key: Iterable) -> str:
    return "||'|'||".join(f"ifnull({prefix}.{q(k)},'')" for k in key) or "''"


# --------------------------------------------------------------------------------------------------------------------------------- trigger text
def _log(op: str, table: str, rule: Rule, cols: list, before: Optional[str], after: Optional[str], key_prefix: str) -> str:
    return (f"INSERT INTO _guard_change_log(at,tbl,op,key,before_json,after_json,reason,correction_no) VALUES ({NOW},'{table}','{op}',{_key_text(key_prefix, rule.key)},"
            f"{before or 'NULL'},{after or 'NULL'},(SELECT reason FROM _guard_window WHERE id=1),(SELECT corrections FROM _guard_counter WHERE id=1));")


def _msg(table: str, what: str) -> str:
    return f"guard: {table} {what}. A deliberate change needs: py -3 scripts/guard.py correct --reason TEXT -- FILE.sql (it is logged)."


def table_triggers(con, rule: Rule) -> dict:
    """{trigger name: CREATE TRIGGER sql} for one registered table, generated from its current columns."""
    t, cols = rule.table, columns(con, rule.table)
    if rule.cls == EXEMPT or not cols:
        return {}
    qt = q(t)
    out: dict = {}
    names = {c for c, _ in cols}
    for k in tuple(rule.key) + tuple(rule.date_col and (rule.date_col,) or ()):
        if k not in names:
            raise GuardError(f"registry names column {k!r} that table {t} does not have")
    old_j, new_j = _json("OLD", cols), _json("NEW", cols)
    key_new = " AND ".join(f"{qt}.{q(k)} = NEW.{q(k)}" for k in rule.key)
    non_vol = [c for c, _ in cols if c not in rule.volatile and c not in rule.key]
    same_cols = " AND ".join(f"{qt}.{q(c)} IS NEW.{q(c)}" for c in non_vol)
    conflict = f"EXISTS (SELECT 1 FROM {qt} WHERE {key_new})"
    identical = f"EXISTS (SELECT 1 FROM {qt} WHERE {key_new}" + (f" AND {same_cols}" if same_cols else "") + ")"
    existing_json = f"(SELECT {_json(qt, cols)} FROM {qt} WHERE {key_new} LIMIT 1)"
    if rule.cls == DATED:
        d = q(rule.date_col)
        sealed = f"(SELECT sealed_through FROM _guard_seal WHERE tbl='{t}')"
        ins_in = f"substr(NEW.{d},1,10) <= {sealed}"
        old_in = f"substr(OLD.{d},1,10) <= {sealed}"
        upd_in = f"(substr(OLD.{d},1,10) <= {sealed} OR substr(NEW.{d},1,10) <= {sealed})"
        out[f"g_{t}_bi"] = f"CREATE TRIGGER g_{t}_bi BEFORE INSERT ON {qt} WHEN {ins_in} AND NOT {WIN} BEGIN SELECT RAISE(ABORT, '{_msg(t, 'is sealed through its sealed date; insert refused')}'); END"
        out[f"g_{t}_bu"] = f"CREATE TRIGGER g_{t}_bu BEFORE UPDATE ON {qt} WHEN {upd_in} AND NOT {WIN} BEGIN SELECT RAISE(ABORT, '{_msg(t, 'row is sealed; update refused')}'); END"
        out[f"g_{t}_bd"] = f"CREATE TRIGGER g_{t}_bd BEFORE DELETE ON {qt} WHEN {old_in} AND NOT {WIN} BEGIN SELECT RAISE(ABORT, '{_msg(t, 'row is sealed; delete refused')}'); END"
        out[f"g_{t}_lc"] = (f"CREATE TRIGGER g_{t}_lc BEFORE INSERT ON {qt} WHEN {ins_in} AND {WIN} AND {conflict} BEGIN "
                            + _log("REPLACE", t, rule, cols, existing_json, new_j, "NEW") + " END")
        out[f"g_{t}_li"] = f"CREATE TRIGGER g_{t}_li AFTER INSERT ON {qt} WHEN {ins_in} AND {WIN} BEGIN " + _log("INSERT", t, rule, cols, None, new_j, "NEW") + " END"
        out[f"g_{t}_lu"] = f"CREATE TRIGGER g_{t}_lu AFTER UPDATE ON {qt} WHEN {upd_in} AND {WIN} BEGIN " + _log("UPDATE", t, rule, cols, old_j, new_j, "OLD") + " END"
        out[f"g_{t}_ld"] = f"CREATE TRIGGER g_{t}_ld AFTER DELETE ON {qt} WHEN {old_in} AND {WIN} BEGIN " + _log("DELETE", t, rule, cols, old_j, None, "OLD") + " END"
    else:                                                                                                                  # INSERT_ONLY
        out[f"g_{t}_bu"] = f"CREATE TRIGGER g_{t}_bu BEFORE UPDATE ON {qt} WHEN NOT {WIN} BEGIN SELECT RAISE(ABORT, '{_msg(t, 'is insert-only; update refused')}'); END"
        out[f"g_{t}_bd"] = f"CREATE TRIGGER g_{t}_bd BEFORE DELETE ON {qt} WHEN NOT {WIN} BEGIN SELECT RAISE(ABORT, '{_msg(t, 'is insert-only; delete refused')}'); END"
        out[f"g_{t}_bi"] = (f"CREATE TRIGGER g_{t}_bi BEFORE INSERT ON {qt} WHEN {conflict} AND NOT {identical} AND NOT {WIN} BEGIN "
                            f"SELECT RAISE(ABORT, '{_msg(t, 'is insert-only; a different row with the same key already exists, insert (or replace) refused')}'); END")
        out[f"g_{t}_bs"] = f"CREATE TRIGGER g_{t}_bs BEFORE INSERT ON {qt} WHEN {identical} BEGIN SELECT RAISE(IGNORE); END"
        out[f"g_{t}_lc"] = (f"CREATE TRIGGER g_{t}_lc BEFORE INSERT ON {qt} WHEN {WIN} AND {conflict} AND NOT {identical} BEGIN "
                            + _log("REPLACE", t, rule, cols, existing_json, new_j, "NEW") + " END")
        out[f"g_{t}_li"] = f"CREATE TRIGGER g_{t}_li AFTER INSERT ON {qt} WHEN {WIN} BEGIN " + _log("INSERT", t, rule, cols, None, new_j, "NEW") + " END"
        out[f"g_{t}_lu"] = f"CREATE TRIGGER g_{t}_lu AFTER UPDATE ON {qt} WHEN {WIN} BEGIN " + _log("UPDATE", t, rule, cols, old_j, new_j, "OLD") + " END"
        out[f"g_{t}_ld"] = f"CREATE TRIGGER g_{t}_ld AFTER DELETE ON {qt} WHEN {WIN} BEGIN " + _log("DELETE", t, rule, cols, old_j, None, "OLD") + " END"
    return out


def state_triggers() -> dict:
    """Triggers that protect the guard's own tables, and that make opening a window leave a counter change and a log entry however it was opened."""
    def ro(name, tbl, what, when):
        return f"CREATE TRIGGER {name} BEFORE {what.upper()} ON {tbl} WHEN {when} BEGIN SELECT RAISE(ABORT, 'guard: {tbl} is protected; {what} refused'); END"
    nw = f"NOT {WIN}"
    out = {
        "g__seal_bd": ro("g__seal_bd", "_guard_seal", "delete", nw),
        "g__seal_bu": ro("g__seal_bu", "_guard_seal", "update", f"NEW.sealed_through < OLD.sealed_through AND {nw}"),
        "g__registry_bu": ro("g__registry_bu", "_guard_registry", "update", nw),
        "g__registry_bd": ro("g__registry_bd", "_guard_registry", "delete", nw),
        "g__day_bu": ro("g__day_bu", "_guard_day_checksum", "update", nw),
        "g__day_bd": ro("g__day_bd", "_guard_day_checksum", "delete", nw),
        "g__log_bu": ro("g__log_bu", "_guard_change_log", "update", "1"),
        "g__log_bd": ro("g__log_bd", "_guard_change_log", "delete", "1"),
        "g__counter_bu": ro("g__counter_bu", "_guard_counter", "update", "NEW.corrections < OLD.corrections"),
        "g__counter_bd": ro("g__counter_bd", "_guard_counter", "delete", "1"),
        "g__window_bd": ro("g__window_bd", "_guard_window", "delete", "1"),
        "g__window_open": ("CREATE TRIGGER g__window_open AFTER UPDATE ON _guard_window WHEN NEW.is_open=1 AND (OLD.is_open=0 OR OLD.expires_at <= " + NOW + ") BEGIN "
                           "UPDATE _guard_counter SET corrections = corrections + 1 WHERE id=1; "
                           f"INSERT INTO _guard_change_log(at,tbl,op,key,before_json,after_json,reason,correction_no) VALUES ({NOW},'_guard_window','OPEN','',NULL,NULL,NEW.reason,"
                           "(SELECT corrections FROM _guard_counter WHERE id=1)); END"),
        "g__window_close": ("CREATE TRIGGER g__window_close AFTER UPDATE ON _guard_window WHEN NEW.is_open=0 AND OLD.is_open=1 BEGIN "
                            f"INSERT INTO _guard_change_log(at,tbl,op,key,before_json,after_json,reason,correction_no) VALUES ({NOW},'_guard_window','CLOSE','',NULL,NULL,OLD.reason,"
                            "(SELECT corrections FROM _guard_counter WHERE id=1)); END"),
    }
    return out


def expected_triggers(con) -> dict:
    exp = state_triggers()
    for t in user_tables(con):
        r = RULES.get(t)
        if r is not None:
            exp.update(table_triggers(con, r))
    return exp


def existing_triggers(con) -> dict:
    return {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'g!_%' ESCAPE '!'")}


# ------------------------------------------------------------------------------------------------------------------------------------ install etc.
def install(con, *, seal: str = "max", strict: bool = True) -> dict:
    """Create the guard state, register every table, create every trigger, and seal each DATED table.
    ``seal='max'`` seals each DATED table through its own last date (decision D8); ``seal='none'`` leaves everything unsealed. Refuses a database holding an unregistered table
    (``strict``); idempotent."""
    unreg = [t for t in user_tables(con) if t not in RULES]
    if unreg and strict:
        raise UnregisteredTables(f"tables with no class in stockbot/data/guard/registry.py: {unreg}")
    with tx(con):
        for name, ddl in STATE_TABLES.items():
            if name not in tables_in(con):
                con.execute(ddl)
        con.execute("INSERT OR IGNORE INTO _guard_window(id,is_open) VALUES (1,0)")
        con.execute("INSERT OR IGNORE INTO _guard_counter(id,corrections) VALUES (1,0)")
        _register(con)
        for name, sql in state_triggers().items():
            if name not in existing_triggers(con):
                con.execute(sql)
        for t in user_tables(con):
            r = RULES.get(t)
            if r is not None:
                for name, sql in table_triggers(con, r).items():
                    if name not in existing_triggers(con):
                        con.execute(sql)
    sealed = {}
    if seal == "max":
        for t in user_tables(con):
            r = RULES.get(t)
            if r is not None and r.cls == DATED:
                top = con.execute(f"SELECT max({q(r.date_col)}) FROM {q(t)}").fetchone()[0]
                if top is not None and top > current_seal(con, t):
                    sealed[t] = seal_table(con, t, top)["sealed_through"]
    return {"installed": True, "unregistered": unreg, "sealed": sealed}


def _register(con) -> None:
    for t in user_tables(con):
        r = RULES.get(t)
        if r is None:
            continue
        con.execute("INSERT OR IGNORE INTO _guard_registry(tbl,class,date_col,key_cols,volatile_cols,reason) VALUES (?,?,?,?,?,?)",
                    (t, r.cls, r.date_col, ",".join(r.key), ",".join(r.volatile), r.reason or None))
        if r.cls == DATED:
            con.execute("INSERT OR IGNORE INTO _guard_seal(tbl,sealed_through) VALUES (?,?)", (t, NEVER))


def ensure(con, *, strict: bool = False) -> dict:
    """What a writer calls right after connecting (R5): if the guard is installed, register and protect any registered table that lacks its triggers, and report an unregistered table."""
    if not installed(con):
        return {"installed": False}
    unreg = [t for t in user_tables(con) if t not in RULES]
    if unreg and strict:
        raise UnregisteredTables(f"tables with no class in stockbot/data/guard/registry.py: {unreg}")
    missing = [n for n in expected_triggers(con) if n not in existing_triggers(con)]
    if missing:
        install(con, seal="none", strict=False)
    return {"installed": True, "unregistered": unreg, "created_triggers": missing}


def uninstall(con, *, yes_remove_guard: bool = False) -> dict:
    """Remove the guard (triggers and ``_guard_*`` tables); the data tables are untouched. Needs the explicit flag."""
    if not yes_remove_guard:
        raise GuardError(f"refusing to remove the guard: pass {YES_REMOVE}")
    names = list(existing_triggers(con))
    with tx(con):
        for n in names:
            con.execute(f"DROP TRIGGER IF EXISTS {q(n)}")
        for t in list(STATE_TABLES):
            con.execute(f"DROP TABLE IF EXISTS {t}")
    return {"removed_triggers": len(names), "removed_tables": len(STATE_TABLES)}


# ------------------------------------------------------------------------------------------------------------------------------------ seal / checksums
def current_seal(con, table: str) -> str:
    r = con.execute("SELECT sealed_through FROM _guard_seal WHERE tbl=?", (table,)).fetchone()
    return r[0] if r else NEVER


def _row_text(row) -> str:
    return "\x1f".join(repr(v) for v in row)


def day_checksums(con, table: str, lo: Optional[str] = None, hi: Optional[str] = None) -> dict:
    """{day: (n_rows, sha256)} for the rows of ``table`` with lo < date <= hi, over every column except the rule's volatile ones, ordered by key (decision D9)."""
    r = RULES[table]
    cols = [c for c, _ in columns(con, table) if c not in r.volatile]
    d = q(r.date_col)
    where, args = [], []
    if lo is not None:
        where.append(f"{d} > ?")
        args.append(lo)
    if hi is not None:
        where.append(f"{d} <= ?")
        args.append(hi)
    order = ", ".join([d] + [q(k) for k in r.key if k != r.date_col])
    sql = f"SELECT {d}, {', '.join(q(c) for c in cols)} FROM {q(table)}" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}"
    out: dict = {}
    cur_day, h, n = None, None, 0
    for row in con.execute(sql, args):
        day = row[0]
        if day != cur_day:
            if cur_day is not None:
                out[cur_day] = (n, h.hexdigest())
            cur_day, h, n = day, hashlib.sha256(), 0
        h.update(_row_text(row[1:]).encode("utf-8", "surrogatepass"))
        h.update(b"\n")
        n += 1
    if cur_day is not None:
        out[cur_day] = (n, h.hexdigest())
    return out


def day_checksum_one(con, table: str, day: str):
    """(n_rows, sha256) of one day of a DATED table, or None when the table has no row for it (same recipe as ``day_checksums``)."""
    r = RULES[table]
    cols = [c for c, _ in columns(con, table) if c not in r.volatile]
    d = q(r.date_col)
    order = ", ".join([d] + [q(k) for k in r.key if k != r.date_col])
    h, n = hashlib.sha256(), 0
    for row in con.execute(f"SELECT {', '.join(q(c) for c in cols)} FROM {q(table)} WHERE {d} = ? ORDER BY {order}", (day,)):
        h.update(_row_text(row).encode("utf-8", "surrogatepass"))
        h.update(b"\n")
        n += 1
    return (n, h.hexdigest()) if n else None


def seal_table(con, table: str, through: str, *, allow_beyond: bool = False) -> dict:
    """Seal ``table`` through the date ``through`` (ISO), storing the per-day checksums of the days newly sealed. Moves forward only; a date beyond the table's last date is refused
    (sealing a day that has not been loaded would block its load) unless ``allow_beyond``."""
    r = RULES.get(table)
    if r is None or r.cls != DATED:
        raise GuardError(f"{table} is not a DATED_APPEND_ONLY table")
    if not installed(con):
        raise GuardError("the guard is not installed in this database")
    old = current_seal(con, table)
    if through < old:
        raise GuardError(f"{table} is already sealed through {old}; moving the seal back needs a correction window")
    top = con.execute(f"SELECT max({q(r.date_col)}) FROM {q(table)}").fetchone()[0]
    if top is None or (through > top and not allow_beyond):
        raise GuardError(f"{table} has no rows dated up to {through} (last date {top}); seal through a loaded date")
    sums = day_checksums(con, table, old if old != NEVER else None, through)
    now = con.execute(f"SELECT {NOW}").fetchone()[0]
    with tx(con):
        con.executemany("INSERT INTO _guard_day_checksum(tbl,day,n_rows,sha256,sealed_at) VALUES (?,?,?,?,?)", [(table, d, n, s, now) for d, (n, s) in sums.items()])
        con.execute("UPDATE _guard_seal SET sealed_through=?, sealed_at=? WHERE tbl=?", (through, now, table))
    return {"table": table, "sealed_through": through, "days_sealed": len(sums), "rows": sum(n for n, _ in sums.values())}


# ------------------------------------------------------------------------------------------------------------------------------------ correction window
def window_state(con) -> dict:
    if not installed(con):
        return {"installed": False}
    r = con.execute(f"SELECT is_open, reason, opened_at, expires_at, (is_open=1 AND expires_at > {NOW}) FROM _guard_window WHERE id=1").fetchone()
    c = con.execute("SELECT corrections FROM _guard_counter WHERE id=1").fetchone()[0]
    return {"installed": True, "flag": int(r[0]), "open": bool(r[4]), "reason": r[1], "opened_at": r[2], "expires_at": r[3], "corrections": c}


def open_window(con, reason: str) -> dict:
    if not reason or not reason.strip():
        raise GuardError("a correction window needs a reason")
    if not installed(con):
        raise GuardError("the guard is not installed in this database")
    with tx(con):
        con.execute(f"UPDATE _guard_window SET is_open=1, reason=?, opened_at={NOW}, expires_at=strftime('%Y-%m-%dT%H:%M:%f','now','+{WINDOW_MINUTES} minutes') WHERE id=1", (reason.strip(),))
    return window_state(con)


def close_window(con) -> dict:
    with tx(con):
        con.execute("UPDATE _guard_window SET is_open=0 WHERE id=1")
    return window_state(con)


def _statements(sql: str) -> list:
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise GuardError(f"the SQL ends in an incomplete statement: {buf.strip()[:80]!r}")
    return out


def correct(con, reason: str, sql: str) -> dict:
    """ONE transaction: open the window, run ``sql`` (statements separated by ';'), refresh the day checksums of the sealed days that changed, close the window, commit. Any error rolls
    everything back (the window never exists outside the transaction). Returns what changed (from the change log)."""
    if con.in_transaction:
        raise GuardError("guard correct needs a connection with no open transaction")
    if not installed(con):
        raise GuardError("the guard is not installed in this database")
    stmts = _statements(sql)
    if not stmts:
        raise GuardError("no SQL to run")
    if not reason or not reason.strip():
        raise GuardError("a correction needs a reason")
    con.execute("BEGIN IMMEDIATE")
    try:
        first = con.execute("SELECT coalesce(max(id),0) FROM _guard_change_log").fetchone()[0]
        con.execute(f"UPDATE _guard_window SET is_open=1, reason=?, opened_at={NOW}, expires_at=strftime('%Y-%m-%dT%H:%M:%f','now','+{WINDOW_MINUTES} minutes') WHERE id=1", (reason.strip(),))
        for s in stmts:
            con.execute(s)
        touched = _refresh_days(con, first)
        con.execute("UPDATE _guard_window SET is_open=0 WHERE id=1")
        n_changed = con.execute("SELECT count(*) FROM _guard_change_log WHERE id>? AND tbl NOT LIKE '\\_guard\\_%' ESCAPE '\\'", (first,)).fetchone()[0]
        counter = con.execute("SELECT corrections FROM _guard_counter WHERE id=1").fetchone()[0]
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return {"reason": reason.strip(), "statements": len(stmts), "rows_logged": n_changed, "days_refreshed": touched, "correction_counter": counter}


def _refresh_days(con, first_log_id: int) -> int:
    """Recompute the checksum of every sealed day a correction touched (inside the open window)."""
    days: dict = {}
    for tbl, b, a in con.execute("SELECT tbl, before_json, after_json FROM _guard_change_log WHERE id>? AND tbl NOT LIKE '\\_guard\\_%' ESCAPE '\\'", (first_log_id,)):
        r = RULES.get(tbl)
        if r is None or r.cls != DATED:
            continue
        for js in (b, a):
            if js:
                d = json.loads(js).get(r.date_col)
                if d is not None and d <= current_seal(con, tbl):
                    days.setdefault(tbl, set()).add(d)
    n = 0
    now = con.execute(f"SELECT {NOW}").fetchone()[0]
    for tbl, ds in days.items():
        for d in sorted(ds):
            got = day_checksum_one(con, tbl, d)
            if got is None:
                con.execute("DELETE FROM _guard_day_checksum WHERE tbl=? AND day=?", (tbl, d))
            else:
                con.execute("INSERT OR REPLACE INTO _guard_day_checksum(tbl,day,n_rows,sha256,sealed_at) VALUES (?,?,?,?,?)", (tbl, d, got[0], got[1], now))
            n += 1
    return n


# ------------------------------------------------------------------------------------------------------------------------------------ status / audit
def status(con) -> dict:
    if not installed(con):
        return {"installed": False, "tables": {t: {"registered": t in RULES} for t in user_tables(con)}, "unregistered": [t for t in user_tables(con) if t not in RULES]}
    w = window_state(con)
    tabs = {}
    for t in user_tables(con):
        r = RULES.get(t)
        row = {"registered": r is not None, "class": r.cls if r else None}
        if r is not None and r.cls == DATED:
            row["sealed_through"] = current_seal(con, t)
        if r is not None and r.cls == EXEMPT:
            row["reason"] = r.reason
        tabs[t] = row
    missing = [n for n in expected_triggers(con) if n not in existing_triggers(con)]
    return {"installed": True, "correction_counter": w["corrections"], "window_open": w["open"], "window_reason": w["reason"], "window_expires_at": w["expires_at"], "tables": tabs,
            "unregistered": [t for t in user_tables(con) if t not in RULES], "missing_triggers": missing, "change_log_rows": con.execute("SELECT count(*) FROM _guard_change_log").fetchone()[0]}


def audit(con) -> dict:
    """R6: recompute every stored day checksum and report any difference; report missing or altered triggers and unregistered tables. Reads only."""
    problems: list = []
    if not installed(con):
        return {"installed": False, "problems": ["the guard is not installed"]}
    exp, have = expected_triggers(con), existing_triggers(con)
    for n in sorted(set(exp) - set(have)):
        problems.append({"kind": "missing_trigger", "name": n})
    for n in sorted(set(exp) & set(have)):
        if " ".join(exp[n].split()) != " ".join((have[n] or "").split()):
            problems.append({"kind": "altered_trigger", "name": n})
    for t in user_tables(con):
        if t not in RULES:
            problems.append({"kind": "unregistered_table", "table": t})
    checked_days = checked_rows = 0
    for t in user_tables(con):
        r = RULES.get(t)
        if r is None or r.cls != DATED:
            continue
        sealed = current_seal(con, t)
        if sealed == NEVER:
            continue
        stored = {d: (n, s) for d, n, s in con.execute("SELECT day, n_rows, sha256 FROM _guard_day_checksum WHERE tbl=?", (t,))}
        now = day_checksums(con, t, None, sealed)
        for d in sorted(set(stored) | set(now)):
            if d not in stored:
                problems.append({"kind": "sealed_day_without_checksum", "table": t, "day": d, "rows_now": now[d][0]})
            elif d not in now:
                problems.append({"kind": "sealed_day_missing_rows", "table": t, "day": d, "rows_stored": stored[d][0]})
            elif stored[d] != now[d]:
                problems.append({"kind": "sealed_day_changed", "table": t, "day": d, "rows_stored": stored[d][0], "rows_now": now[d][0]})
        checked_days += len(now)
        checked_rows += sum(n for n, _ in now.values())
    w = window_state(con)
    if w["open"]:
        problems.append({"kind": "window_open", "reason": w["reason"], "expires_at": w["expires_at"]})
    return {"installed": True, "ok": not problems, "problems": problems, "days_checked": checked_days, "rows_checked": checked_rows, "correction_counter": w["corrections"]}


# ------------------------------------------------------------------------------------------------------------------------------------ writers
def connect_writer(path, *, timeout: float = 60.0) -> sqlite3.Connection:
    """The one way a writer should open the database: a plain read-write connection, then ``ensure`` (R5). It never changes the journal mode."""
    con = sqlite3.connect(str(path), timeout=timeout, isolation_level=None)
    ensure(con)
    return con

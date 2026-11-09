"""The live state database (decision D8): a SEPARATE SQLite file, written only by the live adapter, schema versioned, with an append-only journal.

Tables:
  meta(key, value)                     schema_version, initial_cash
  journal(seq, kind, session, key, payload)   append-only (UPDATE and DELETE are refused by triggers): kinds "init", "effect" (an operator report's ReportEffect),
                                       "decisions" (one session's Decisions). ``key`` is unique per kind (a report id / a session date), so the same report or session
                                       cannot be journaled twice.
  snapshot(id=1, as_of, state)         the latest State as JSON (a cache: ``rebuild`` recomputes it from the journal alone and must agree)
State is rebuilt by folding the journal: ``init`` -> State.initial(cash), ``effect`` -> reports.apply_effect, ``decisions`` -> apply.apply_decisions.
finsight.db is never opened here. Schema migration is not designed in Part B: a different schema_version is refused.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from stockbot.engine.apply import apply_decisions
from stockbot.engine.reports import ReportEffect, apply_effect
from stockbot.engine.types import Decisions, State, to_plain

SCHEMA_VERSION = 1
_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, session TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
                                    UNIQUE (kind, key));
CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK (id = 1), as_of TEXT, state TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
"""


class StateStoreError(RuntimeError):
    pass


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.name.lower() == "finsight.db":
            raise StateStoreError("the state store is separate from the lake: refusing to open finsight.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path)
        self._con.executescript(_DDL)
        row = self._con.execute("select value from meta where key='schema_version'").fetchone()
        if row is None:
            self._con.execute("insert into meta values ('schema_version', ?)", (str(SCHEMA_VERSION),))
            self._con.commit()
        elif int(row[0]) != SCHEMA_VERSION:
            raise StateStoreError(f"state store schema_version {row[0]} is not supported by this build ({SCHEMA_VERSION}); no migration is designed yet")

    def close(self) -> None:
        self._con.close()

    # ------------------------------------------------------------------ journal
    def _append(self, kind: str, session: str, key: str, payload: str, state: State) -> None:
        with self._con:                                              # one transaction: journal row + snapshot
            self._con.execute("insert into journal (kind, session, key, payload) values (?,?,?,?)", (kind, session, key, payload))
            self._con.execute("insert or replace into snapshot (id, as_of, state) values (1, ?, ?)", (state.as_of.isoformat() if state.as_of else None, state.to_json()))

    def initialise(self, cash: float) -> State:
        if self.journal_count():
            raise StateStoreError("already initialised")
        st = State.initial(cash)
        self._append("init", "0000-00-00", "init", json.dumps({"cash": cash}), st)
        self._con.execute("insert or replace into meta values ('initial_cash', ?)", (repr(float(cash)),))
        self._con.commit()
        return st

    def append_effect(self, effect: ReportEffect, state_after: State) -> None:
        self._append("effect", effect.date.isoformat(), effect.report_id, json.dumps(to_plain(effect), sort_keys=True), state_after)

    def append_decisions(self, dec: Decisions, state_after: State) -> None:
        self._append("decisions", dec.as_of.isoformat(), dec.as_of.isoformat(), dec.to_json(), state_after)

    def has_effect(self, report_id: str) -> bool:
        return self._con.execute("select 1 from journal where kind='effect' and key=?", (report_id,)).fetchone() is not None

    def decisions_for(self, session) -> Optional[Decisions]:
        r = self._con.execute("select payload from journal where kind='decisions' and key=?", (session.isoformat(),)).fetchone()
        return Decisions.from_json(r[0]) if r else None

    def journal_count(self) -> int:
        return self._con.execute("select count(*) from journal").fetchone()[0]

    # ------------------------------------------------------------------ state
    def load(self) -> State:
        r = self._con.execute("select state from snapshot where id=1").fetchone()
        if r is None:
            raise StateStoreError("not initialised")
        return State.from_json(r[0])

    def rebuild(self) -> State:
        """Fold the journal from the beginning; independent of the snapshot."""
        st: Optional[State] = None
        for kind, payload in self._con.execute("select kind, payload from journal order by seq"):
            if kind == "init":
                st = State.initial(json.loads(payload)["cash"])
            elif st is None:
                raise StateStoreError("journal does not start with init")
            elif kind == "effect":
                st = apply_effect(st, ReportEffect.from_plain(json.loads(payload)))
            elif kind == "decisions":
                st = apply_decisions(st, Decisions.from_json(payload))
            else:
                raise StateStoreError(f"unknown journal kind {kind!r}")
        if st is None:
            raise StateStoreError("empty journal")
        return st

"""stockbot/data/ingestion/daily_update.py - the daily data job: one NSE session date at a time, oldest first, each day sealed only after every writer and every check of that day passed.

Entry point: ``py -3 scripts/daily_data_update.py`` (thin wrapper). Plain rules, in order, for one date D:
  1. the ORIGINAL bhavcopy of D is downloaded (same URL patterns and order as ``scripts/archive_raw_bhavcopy.py``), saved UNMODIFIED under <data root>\\raw_bhavcopy\\YYYY\\ (never overwritten) and a row is
     added to MANIFEST.csv (date, file_name, url, bytes, sha256, pattern, status). The date INSIDE the file must equal D, else the file is not accepted (a holiday file of the previous session is not D's);
  2. the file is parsed completely BEFORE anything is written (an unparsable price refuses the day; nothing is zero-filled, nothing is written);
  3. EQ rows -> ``market_data_lake`` through ``BhavcopyIngestor.store_day``; BE/BZ/BL rows -> ``market_data_non_eq`` through ``store_day_non_eq``; Nifty 50 and India VIX rows (NSE index file, Yahoo fallback)
     -> ``market_data_lake`` (they make D a session for the engine). Every write opens the database through ``guard.connect_writer``; a sealed date is refused before anything is deleted;
  4. checks (``run_checks``): row count per table and series equals the file's independent count, no (symbol, date) in both the lake and the BE/BZ rows, prices parse and are positive, every date in the file
     equals D, EQ count within a sane range of the previous session (reported, blocks only when zero);
  5. only if all writers finished and all checks passed: ``market_data_lake`` and ``market_data_non_eq`` are sealed through D in ONE transaction. A failed day stays unsealed and is retried; the run
     STOPS at the first failed day (a later day is never loaded over a gap that could still be filled, because the seal moves forward only).
Calendar: a session is any date for which NSE publishes a file (weekdays AND Saturdays/Sundays are tried). No file after every URL = NO_FILE (holiday assumption), journalled in <data root>\\daily\\calendar.csv, and
re-checked on each of the next 3 days; after that it stays a holiday. Today's date before the end of the daily window is PENDING (not NO_FILE).
Locks: see ``stockbot.data.guard.runlock``. ASM/GSM snapshot and corporate actions run after the price days; neither can block a price load.
Exit codes: 0 done (or nothing to do), 1 a day failed or an error, 3 today's file is not published yet (the scheduler retries), 4 locked by a run (retry), 5 stale lock (report, stop).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_START = (19, 30)                 # first attempt of the day
WINDOW_END = (23, 45)                   # no attempt for today's date after this (the task stops at 23:30)
RECHECK_DAYS = 3                        # a NO_FILE date is re-checked on each of the next 3 days
EQ_RANGE = (0.80, 1.25)                 # sane EQ row count versus the previous session (reported, not blocking)
INDEX_SYMBOLS = {"Nifty 50": "NIFTY50_INDEX", "India VIX": "INDIA_VIX"}
LAKE, NON_EQ = "market_data_lake", "market_data_non_eq"
ASM_TABLES = ("asm_gsm_snapshot_raw", "asm_gsm_daily_snapshot")
EQ_SOURCE = "nse_bhavcopy_raw"
INDEX_URL = "https://archives.nseindia.com/content/indices/ind_close_all_{d}.csv"
CA_SOURCE = "NSE corporates-corporateActions API (daily job)"
MANIFEST_FIELDS = ["date", "file_name", "url", "bytes", "sha256", "pattern", "status"]
STATE_FIELDS = ["date", "checked_at", "outcome", "detail"]
DEFAULT_ROOT = Path(r"F:\Projects\Ravi\StockBotData")


class DayRefused(Exception):
    """The day cannot be loaded as it stands (unparsable price, wrong date, duplicate symbol ...): nothing was written."""


def _archive():
    """scripts/archive_raw_bhavcopy.py (the URL patterns, their order, the date-in-file rule). Loaded by path so this module and the archive script can never disagree."""
    import importlib.util
    p = Path(__file__).resolve().parents[3] / "scripts" / "archive_raw_bhavcopy.py"
    spec = importlib.util.spec_from_file_location("archive_raw_bhavcopy", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("archive_raw_bhavcopy", mod)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------------------------------------------ context
class Downloader:
    """get(url) -> (status | None, bytes, note). 404 -> (404, b'', '404'); a network error or another status after retries -> (None, b'', note). Paced (>= 1 s between requests)."""

    def __init__(self, gap: float = 1.0, tries: int = 4, headers: Optional[dict] = None):
        import requests
        a = _archive()
        self.sess = requests.Session()
        self.sess.headers.update(headers or a.HEADERS)
        self.pacer = a.Pacer(gap)
        self.tries = tries
        self._fetch = a.fetch

    def get(self, url: str):
        return self._fetch(self.sess, self.pacer, url, self.tries)


@dataclass
class Ctx:
    db: Path
    root: Path = DEFAULT_ROOT
    download: Optional[Callable] = None              # url -> (status, bytes, note)
    now: Callable = field(default=lambda: datetime.now(IST))
    index_fetch: Optional[Callable] = None            # (ctx, day) -> ({symbol: (o, h, l, c, source)}, note)
    ca_fetch: Optional[Callable] = None               # (from_date, to_date) -> list[dict] | None
    asm_run: Optional[Callable] = None                # (db, iso_date) -> rc
    lock_dir: Optional[Path] = None
    out: Callable = field(default=print)

    @property
    def raw(self) -> Path:
        return self.root / "raw_bhavcopy"

    @property
    def raw_index(self) -> Path:
        return self.root / "raw_index"

    @property
    def state(self) -> Path:
        return self.root / "daily"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def get(self, url):
        if self.download is None:
            self.download = Downloader().get
        return self.download(url)


# ------------------------------------------------------------------------------------------------------------------------------ results
@dataclass
class DayResult:
    day: date
    status: str                                       # LOADED, ALREADY_SEALED, NO_FILE, NO_FILE_FINAL, PENDING, REFUSED, FAILED, SKIPPED_RECHECKED_TODAY
    detail: str = ""
    file: str = ""
    downloaded: bool = False
    rows: dict = field(default_factory=dict)          # table / series -> rows
    checks: list = field(default_factory=list)        # (name, ok, detail, blocking)
    sealed: bool = False

    def line(self) -> str:
        r = " ".join(f"{k}={v}" for k, v in self.rows.items())
        bad = [c[0] for c in self.checks if not c[1]]
        return f"{self.day} {self.status:<10} {self.file or '-':<46} {r} checks={'ok' if not bad else 'FAILED ' + ','.join(bad)} sealed={self.sealed} {self.detail}".rstrip()


# ------------------------------------------------------------------------------------------------------------------------------ small helpers
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _append_csv(path: Path, fields: list, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def _read_csv(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seal_of(con, table: str) -> Optional[str]:
    from stockbot.data.guard.writers import sealed_through, sqlite_fetch
    return sealed_through(sqlite_fetch(con), table)


def file_dates(path: Path) -> set:
    """Every distinct trade date written inside the file (TIMESTAMP / DATE1 / TradDt), as dates; a value that cannot be read is returned as the string itself so the check fails."""
    from stockbot.data import non_eq as NE
    rows = csv.reader(io.StringIO(NE.csv_text(path)))
    head = [h.strip().upper() for h in next(rows)]
    key = next((k for k in ("TRADDT", "TIMESTAMP", "DATE1") if k in head), None)
    if key is None:
        return {"no date column"}
    i = head.index(key)
    out = set()
    for r in rows:
        if len(r) <= i or not r[i].strip():
            continue
        v = r[i].strip()
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d-%b-%y"):
            try:
                out.add(datetime.strptime(v, fmt).date())
                break
            except ValueError:
                continue
        else:
            out.add(v)
    return out


# ------------------------------------------------------------------------------------------------------------------------------ step 1: the original file
def locate_or_download(ctx: Ctx, day: date) -> tuple:
    """-> ('FILE', path, name, downloaded: bool) | ('NO_FILE', note) | ('ERROR', note). An accepted file is saved byte for byte, never overwritten, journalled in MANIFEST.csv."""
    a = _archive()
    folder = ctx.raw / str(day.year)
    mpath = ctx.raw / "MANIFEST.csv"
    manifest = [r for r in _read_csv(mpath) if r["date"] == day.isoformat() and r["status"] == "OK"]
    cands = a.candidates(day)
    # a file of this date already in the archive (earlier attempt, or the archive script): reuse it after checking it against the manifest
    for pat, name, url in cands:
        p = folder / name
        if p.exists() and a.valid_file(p, day):
            known = [r for r in manifest if r["file_name"] == name]
            if known and known[-1]["sha256"] != sha256_bytes(p.read_bytes()):
                return ("ERROR", f"{p} differs from its MANIFEST.csv sha256: not used")
            if not known:
                c = p.read_bytes()
                _append_csv(mpath, MANIFEST_FIELDS, {"date": day.isoformat(), "file_name": name, "url": url, "bytes": len(c), "sha256": sha256_bytes(c), "pattern": pat, "status": "OK"})
            return ("FILE", p, name, False)
    note, errors = "", False
    for pat, name, url in cands:
        code, content, why = ctx.get(url)
        if code == 404:
            note += f"{pat}:404 "
            continue
        if code is None:
            note += f"{pat}:{why} "
            errors = True
            continue
        try:
            dd = a.declared_date(name, content)
        except Exception as e:  # noqa: BLE001
            note += f"{pat}:unreadable({e}) "
            errors = True
            continue
        if len(content) <= 200 or dd != day:
            note += f"{pat}:file declares {dd} "
            continue
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if target.exists():                                   # an invalid file of that name is kept; the new one gets a suffix (never overwrite)
            target = folder / (name + f".new{int(time.time())}")
        with open(target, "xb") as f:
            f.write(content)
        _append_csv(mpath, MANIFEST_FIELDS, {"date": day.isoformat(), "file_name": target.name, "url": url, "bytes": len(content), "sha256": sha256_bytes(content), "pattern": pat, "status": "OK"})
        return ("FILE", target, target.name, True)
    return ("ERROR", note.strip()) if errors else ("NO_FILE", note.strip())


# ------------------------------------------------------------------------------------------------------------------------------ step 2: parse everything first
@dataclass
class Prepared:
    eq: object                     # DataFrame in market_data_lake columns
    non_eq: list                   # tuples in non_eq.COLUMNS order
    n_eq_file: int                 # independent counts (plain csv)
    n_non_eq_file: int
    by_series: dict
    file_dates: set


def prepare_day(path: Path, name: str, day: date) -> Prepared:
    import pandas as pd
    from stockbot.data import non_eq as NE
    dates = file_dates(path)
    if dates != {day}:
        raise DayRefused(f"the dates inside {name} are {sorted(map(str, dates))[:4]}, not {day}")
    try:
        eq_rows = NE.parse_rows(path, day, name, series=("EQ",))
        ne_rows = NE.parse_rows(path, day, name)
    except ValueError as e:
        raise DayRefused(f"unparsable file: {e}") from e
    n_eq, n_ne = NE.file_series_count(path, ("EQ",)), NE.file_series_count(path)
    if len(eq_rows) != n_eq or len(ne_rows) != n_ne:
        raise DayRefused(f"parsed {len(eq_rows)} EQ / {len(ne_rows)} non-EQ rows but the file has {n_eq} / {n_ne}")
    if n_eq == 0:
        raise DayRefused("the file holds no EQ rows")
    syms = [r[0] for r in eq_rows]
    if len(set(syms)) != len(syms):
        raise DayRefused("duplicate EQ symbol in the file")
    keys = [(r[0], r[2]) for r in ne_rows]
    if len(set(keys)) != len(keys):
        raise DayRefused("duplicate (symbol, series) among the non-EQ rows")
    cols = ["symbol", "trade_date", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "exchange", "source"]
    df = pd.DataFrame([(r[0], day, r[4], r[5], r[6], r[7], r[9], "NSE", EQ_SOURCE) for r in eq_rows], columns=cols)
    by_series: dict = {}
    for r in ne_rows:
        by_series[r[2]] = by_series.get(r[2], 0) + 1
    return Prepared(df, ne_rows, n_eq, n_ne, by_series, dates)


# ------------------------------------------------------------------------------------------------------------------------------ step 3: writers
def write_lake_and_non_eq(ctx: Ctx, day: date, prep: Prepared) -> None:
    from stockbot.data.guard.writers import writer_session
    from stockbot.data.ingestion.bhavcopy_ingestor import BhavcopyIngestor
    ing = BhavcopyIngestor({})
    for fn, payload in ((ing.store_day, prep.eq), (ing.store_day_non_eq, prep.non_eq)):
        s = writer_session(ctx.db)
        try:
            fn(s, payload, day)
        finally:
            eng = s.get_bind()
            s.close()
            eng.dispose()


def default_index_fetch(ctx: Ctx, day: date) -> tuple:
    """NSE index file (original saved unmodified under <root>\\raw_index), Yahoo as fallback. -> ({symbol: (o, h, l, c, source)}, note); an empty dict means unavailable."""
    from stockbot.data.ingestion.f2_index_gap_fill import parse
    dmy = day.strftime("%d%m%Y")
    url = INDEX_URL.format(d=dmy)
    name = f"ind_close_all_{dmy}.csv"
    p = ctx.raw_index / str(day.year) / name
    note = ""
    content = p.read_bytes() if p.exists() else None
    if content is None:
        code, body, why = ctx.get(url)
        if code == 200 and len(body) > 100:
            content = body
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "xb") as f:
                f.write(body)
            _append_csv(ctx.raw_index / "MANIFEST.csv", MANIFEST_FIELDS, {"date": day.isoformat(), "file_name": name, "url": url, "bytes": len(body), "sha256": sha256_bytes(body), "pattern": "NSE_INDEX", "status": "OK"})
        else:
            note = f"NSE index file: {code} {why}"
    got = {}
    if content is not None:
        try:
            got = {s: (v[1], v[2], v[3], v[4], url) for s, v in parse(content.decode("utf-8", "replace"), day.isoformat()).items()}
        except Exception as e:  # noqa: BLE001
            note += f" NSE index file unreadable: {e}"
    if len(got) < 2:
        try:
            import yfinance as yf
            for sym, tk in (("NIFTY50_INDEX", "^NSEI"), ("INDIA_VIX", "^INDIAVIX")):
                if sym in got:
                    continue
                df = yf.download(tk, start=day.isoformat(), end=(day + timedelta(days=1)).isoformat(), progress=False, auto_adjust=False)
                if len(df):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    r = df.iloc[0]
                    got[sym] = (float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), f"yahoo:{tk}")
        except Exception as e:  # noqa: BLE001
            note += f" yahoo fallback failed: {type(e).__name__}: {e}"
    return got, note.strip()


def write_index(ctx: Ctx, day: date, rows: dict) -> None:
    """Nifty 50 / India VIX rows of ``day`` -> market_data_lake: refused on a sealed date; delete-and-insert of the two rows in one transaction."""
    from stockbot.data.guard.core import connect_writer, tx
    from stockbot.data.guard.writers import refuse_if_sealed, sqlite_fetch
    con = connect_writer(ctx.db)
    try:
        refuse_if_sealed(sqlite_fetch(con), LAKE, day)
        with tx(con):
            con.execute("DELETE FROM market_data_lake WHERE trade_date=? AND symbol IN ('NIFTY50_INDEX','INDIA_VIX')", (day.isoformat(),))
            con.executemany("INSERT INTO market_data_lake (symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, exchange, source) VALUES (?,?,?,?,?,?,?,?,?)",
                            [(s, day.isoformat(), o, h, l, c, 0, "NSE", src) for s, (o, h, l, c, src) in rows.items()])
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------------------------------------ step 4: checks
def run_checks(con, day: date, prep: Prepared) -> list:
    """[(name, ok, detail, blocking)] for the day as it now stands in the database."""
    d = day.isoformat()
    out = []

    def add(name, ok, detail, blocking=True):
        out.append((name, bool(ok), detail, blocking))
    n_eq = con.execute("SELECT count(*) FROM market_data_lake WHERE trade_date=? AND symbol NOT IN ('NIFTY50_INDEX','INDIA_VIX')", (d,)).fetchone()[0]
    add("eq_rows_equal_file", n_eq == prep.n_eq_file, f"table {n_eq} / file {prep.n_eq_file}")
    n_ne = con.execute(f"SELECT count(*) FROM {NON_EQ} WHERE trade_date=?", (d,)).fetchone()[0]
    add("non_eq_rows_equal_file", n_ne == prep.n_non_eq_file, f"table {n_ne} / file {prep.n_non_eq_file}")
    by = dict(con.execute(f"SELECT series, count(*) FROM {NON_EQ} WHERE trade_date=? GROUP BY series", (d,)).fetchall())
    add("non_eq_rows_per_series_equal_file", by == prep.by_series, f"table {by} / file {prep.by_series}")
    idx = dict(con.execute("SELECT symbol, close_raw FROM market_data_lake WHERE trade_date=? AND symbol IN ('NIFTY50_INDEX','INDIA_VIX')", (d,)).fetchall())
    add("index_and_vix_rows", set(idx) == {"NIFTY50_INDEX", "INDIA_VIX"} and all(v and v > 0 for v in idx.values()), f"{idx}")
    both = con.execute(f"SELECT count(*) FROM market_data_lake l JOIN {NON_EQ} n ON n.symbol=l.symbol AND n.trade_date=l.trade_date WHERE l.trade_date=? AND n.series IN ('BE','BZ')", (d,)).fetchone()[0]
    add("no_symbol_in_both_tables", both == 0, f"{both} (symbol, date) in the lake and in BE/BZ rows")
    bl = con.execute(f"SELECT count(*) FROM market_data_lake l JOIN {NON_EQ} n ON n.symbol=l.symbol AND n.trade_date=l.trade_date WHERE l.trade_date=? AND n.series='BL'", (d,)).fetchone()[0]
    add("bl_overlap_info", True, f"{bl} BL rows share a symbol with an EQ row (block-deal window rows coexist with EQ rows by design; not a bar)", False)
    badp = con.execute("SELECT count(*) FROM market_data_lake WHERE trade_date=? AND (open_raw IS NULL OR high_raw IS NULL OR low_raw IS NULL OR close_raw IS NULL OR open_raw<=0 OR high_raw<=0 OR low_raw<=0 OR close_raw<=0)", (d,)).fetchone()[0]
    badn = con.execute(f"SELECT count(*) FROM {NON_EQ} WHERE trade_date=? AND (open_raw<=0 OR high_raw<=0 OR low_raw<=0 OR close_raw<=0)", (d,)).fetchone()[0]
    add("prices_positive", badp == 0 and badn == 0, f"{badp} lake rows and {badn} non-EQ rows with a missing or non-positive price")
    add("date_inside_file_equals_requested", prep.file_dates == {day}, f"{sorted(map(str, prep.file_dates))}")
    prev = con.execute("SELECT trade_date, count(*) FROM market_data_lake WHERE trade_date<? AND symbol NOT IN ('NIFTY50_INDEX','INDIA_VIX') GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1", (d,)).fetchone()
    if prev and prev[1]:
        ratio = n_eq / prev[1]
        add("eq_count_vs_previous_session", EQ_RANGE[0] <= ratio <= EQ_RANGE[1], f"{n_eq} vs {prev[1]} on {prev[0]} (ratio {ratio:.3f}, sane {EQ_RANGE}); reported, not blocking", False)
    add("eq_count_not_zero", n_eq > 0, f"{n_eq}")
    return out


# ------------------------------------------------------------------------------------------------------------------------------ one day
def process_day(ctx: Ctx, day: date, *, today_pending: bool = False) -> DayResult:
    from stockbot.data.guard import core
    from stockbot.data.guard.core import connect_writer
    res = DayResult(day, "FAILED")
    con = connect_writer(ctx.db)
    try:
        if not core.installed(con):
            res.detail = "the guard is not installed in this database: refused"
            return res
        sealed = seal_of(con, LAKE)
        if sealed is not None and day.isoformat() <= sealed:
            res.status, res.detail = "ALREADY_SEALED", f"{LAKE} is sealed through {sealed}: not reloaded"
            return res
        got = locate_or_download(ctx, day)
        if got[0] == "NO_FILE":
            if today_pending:
                res.status, res.detail = "PENDING", "no file yet: " + got[1]
            else:
                res.status, res.detail = "NO_FILE", got[1]
            return res
        if got[0] == "ERROR":
            res.detail = "download error: " + got[1]
            return res
        _, path, name, downloaded = got
        res.file, res.downloaded = name, downloaded
        try:
            prep = prepare_day(path, name, day)
        except DayRefused as e:
            res.status, res.detail = "REFUSED", f"{e} (nothing written)"
            return res
        idx, note = (ctx.index_fetch or default_index_fetch)(ctx, day)
        # writers: all three must finish before any seal
        try:
            write_lake_and_non_eq(ctx, day, prep)
            if len(idx) < 2:
                res.detail = f"index/VIX rows unavailable ({note}); the day is left UNSEALED and is retried"
                res.rows = {"EQ": prep.n_eq_file, "NON_EQ": prep.n_non_eq_file}
                return res
            write_index(ctx, day, idx)
        except Exception as e:  # noqa: BLE001
            res.detail = f"writer failed: {type(e).__name__}: {e}; the day is left UNSEALED and is retried"
            return res
        res.checks = run_checks(con, day, prep)
        res.rows = {"EQ": prep.n_eq_file, "NON_EQ": prep.n_non_eq_file, **{k: v for k, v in sorted(prep.by_series.items())}, "INDEX": len(idx)}
        blocking = [c for c in res.checks if not c[1] and c[3]]
        if blocking:
            res.detail = "check failed: " + "; ".join(f"{c[0]} ({c[2]})" for c in blocking) + "; the day is left UNSEALED and is retried"
            return res
        with core.tx(con):                                    # both seals or neither
            core.seal_table(con, LAKE, day.isoformat(), allow_beyond=True)
            core.seal_table(con, NON_EQ, day.isoformat(), allow_beyond=True)
        res.sealed, res.status = True, "LOADED"
        warn = [c for c in res.checks if not c[1] and not c[3]]
        if warn:
            res.detail = "WARNING: " + "; ".join(f"{c[0]} ({c[2]})" for c in warn)
        return res
    except Exception as e:  # noqa: BLE001
        res.detail = f"{type(e).__name__}: {e}"
        return res
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------------------------------------ calendar
def journal_rows(ctx: Ctx, day: date) -> list:
    return [r for r in _read_csv(ctx.state / "calendar.csv") if r["date"] == day.isoformat()]


def journal(ctx: Ctx, day: date, outcome: str, detail: str) -> None:
    _append_csv(ctx.state / "calendar.csv", STATE_FIELDS, {"date": day.isoformat(), "checked_at": ctx.now().isoformat(timespec="seconds"), "outcome": outcome, "detail": detail[:300]})


def candidates(ctx: Ctx, today: date, through: Optional[date]) -> list:
    """Every calendar date after the lake's sealed-through date up to ``through`` (default: today), weekdays AND weekends, oldest first."""
    from stockbot.data.guard.core import connect_writer
    con = connect_writer(ctx.db)
    try:
        s = seal_of(con, LAKE)
    finally:
        con.close()
    if s is None:
        return []
    d, end = date.fromisoformat(s) + timedelta(days=1), min(through or today, today)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def include_today(now: datetime, *, catch_up_only: bool, scheduled: bool) -> bool:
    if catch_up_only:
        return False
    t = (now.hour, now.minute)
    return not scheduled or WINDOW_START <= t <= WINDOW_END


def should_check(ctx: Ctx, day: date, today: date) -> tuple:
    """(check?, why not). A NO_FILE date is re-checked on each of the next RECHECK_DAYS days (at most once per calendar day); after that it stays a holiday."""
    rows = [r for r in journal_rows(ctx, day) if r["outcome"] == "NO_FILE"]
    if not rows:
        return True, ""
    if today > day + timedelta(days=RECHECK_DAYS):
        return False, "NO_FILE_FINAL"
    if rows[-1]["checked_at"][:10] == today.isoformat():
        return False, "SKIPPED_RECHECKED_TODAY"
    return True, ""


# ------------------------------------------------------------------------------------------------------------------------------ corporate actions and ASM/GSM (after the price days; never block them)
def default_ca_fetch(from_date: date, to_date: date):
    import requests
    from stockbot.data.ingestion import nse_corporate_actions_history as H
    s = requests.Session()
    s.headers.update(H.HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=20)
    except requests.RequestException:
        pass
    u = f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={from_date.strftime('%d-%m-%Y')}&to_date={to_date.strftime('%d-%m-%Y')}"
    for k in range(4):
        try:
            r = s.get(u, timeout=40)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (k + 1))
    return None


def split_known_prefix_differences(diff: list) -> tuple:
    """(still_different, n_prefix_only). A stored row whose ONLY difference from the fetched row is the ``feed_symbol=<SYM>; `` prefix that f2_load_corporate_actions.py writes in front of ``notes``
    (ratios equal, notes equal after removing that prefix) is the same event: neither a difference nor a warning (the 85 known rows, Claude_Docs/CA_DIFFERENCES_REPORT.md). Stored rows are never changed."""
    rest, n = [], 0
    for key, stored, offered in diff:
        prefix = f"feed_symbol={key[0]}; "
        s_notes, o_notes = stored[2], offered[2]
        if stored[:2] == offered[:2] and isinstance(s_notes, str) and s_notes.startswith(prefix) and s_notes[len(prefix):] == (o_notes or ""):
            n += 1
        else:
            rest.append((key, stored, offered))
    return rest, n


def load_corporate_actions(ctx: Ctx, raw: list) -> dict:
    """NSE rows -> corporate_actions_log (INSERT_ONLY): new events are added, identical ones skipped, a stored event with other values is reported and NOT changed (guard correct)."""
    from stockbot.data.guard.core import connect_writer, tx
    from stockbot.data.guard.writers import split_new, sqlite_fetch
    from stockbot.data.ingestion import nse_corporate_actions_history as H
    loaded_at = datetime.now().isoformat(timespec="seconds")
    names = ("symbol", "ex_date", "action_type", "ratio_numerator", "ratio_denominator", "notes", "source", "loaded_at")
    recs, unresolved = [], 0
    for r in raw:
        ex = H._parse_ex(r.get("exDate"))
        sym = str(r.get("symbol") or "").strip()
        if ex is None or not sym:
            unresolved += 1
            continue
        for a in H.parse_subject(str(r.get("subject") or "")):
            recs.append(dict(zip(names, (sym, ex.isoformat(), a["action_type"], a["num"], a["den"], a["note"][:500], CA_SOURCE, loaded_at))))
    con = connect_writer(ctx.db)
    try:
        new, same, diff = split_new(sqlite_fetch(con), "corporate_actions_log", recs, ("symbol", "ex_date", "action_type"), ("ratio_numerator", "ratio_denominator", "notes"))
        diff, prefix_only = split_known_prefix_differences(diff)
        same += prefix_only
        with tx(con):
            con.executemany("INSERT OR IGNORE INTO corporate_actions_log (symbol, ex_date, action_type, ratio_numerator, ratio_denominator, notes, source, loaded_at) VALUES (?,?,?,?,?,?,?,?)",
                            [tuple(r[c] for c in names) for r in new])
    finally:
        con.close()
    return {"fetched": len(raw), "parsed": len(recs), "inserted": len(new), "identical": same, "differ_not_applied": len(diff), "unresolved": unresolved}


def corporate_actions_step(ctx: Ctx, first: date, today: date) -> str:
    stamp = ctx.state / "corporate_actions.json"
    try:
        if stamp.exists() and json.loads(stamp.read_text())["date"] == today.isoformat():
            return "corporate actions: already fetched today"
        raw = (ctx.ca_fetch or default_ca_fetch)(first, today + timedelta(days=45))
        if raw is None:
            return "corporate actions: SOURCE UNAVAILABLE (reported; prices are not affected; retried on the next run)"
        res = load_corporate_actions(ctx, raw)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({"date": today.isoformat(), **res}))
        return f"corporate actions: {res}"
    except Exception as e:  # noqa: BLE001
        return f"corporate actions: FAILED {type(e).__name__}: {e} (reported; prices are not affected)"


def asm_step(ctx: Ctx, today: date) -> str:
    """ASM/GSM snapshot of today (the source returns only the current list), after today's lake day is sealed. Both tables are sealed through today only when BOTH lists were stored."""
    from stockbot.data.guard import core
    from stockbot.data.guard.core import connect_writer
    con = connect_writer(ctx.db)
    try:
        lake = seal_of(con, LAKE)
        if lake != today.isoformat():
            return f"ASM/GSM: skipped (today's session {today} is not loaded and sealed)"
        if (seal_of(con, ASM_TABLES[0]) or "") >= today.isoformat():
            return "ASM/GSM: already stored and sealed for today"
    finally:
        con.close()
    try:
        if ctx.asm_run:
            rc = ctx.asm_run(str(ctx.db), today.isoformat())
        else:
            from stockbot.data.ingestion import snapshot_asm_gsm
            rc = snapshot_asm_gsm.run(str(ctx.db), today.isoformat())
        con = connect_writer(ctx.db)
        try:
            n = con.execute("SELECT count(*) FROM asm_gsm_snapshot_raw WHERE snapshot_date=?", (today.isoformat(),)).fetchone()[0]
            if rc == 0 and n == 2:
                with core.tx(con):
                    for t in ASM_TABLES:
                        core.seal_table(con, t, today.isoformat(), allow_beyond=True)
                return "ASM/GSM: stored and sealed"
            return f"ASM/GSM: SOURCE UNAVAILABLE or incomplete (rc {rc}, {n}/2 lists stored); reported; prices are not affected; not sealed, retried on the next run"
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return f"ASM/GSM: FAILED {type(e).__name__}: {e} (reported; prices are not affected)"


# ------------------------------------------------------------------------------------------------------------------------------ the run
@dataclass
class RunReport:
    started: str
    days: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    exit_code: int = 0


def run(ctx: Ctx, *, through: Optional[date] = None, catch_up_only: bool = False, scheduled: bool = False, plan_only: bool = False, steps: bool = True) -> RunReport:
    now = ctx.now()
    today = now.date()
    rep = RunReport(now.isoformat(timespec="seconds"))
    cands = candidates(ctx, today, through)
    use_today = include_today(now, catch_up_only=catch_up_only, scheduled=scheduled)
    if not use_today:
        cands = [d for d in cands if d != today]
    failed = pending = False
    first_loaded = None
    for day in cands:
        ok, why = should_check(ctx, day, today)
        if not ok:
            rep.days.append(DayResult(day, why))
            continue
        if plan_only:
            rep.days.append(DayResult(day, "WOULD_CHECK"))
            continue
        pending_ok = day == today and (now.hour, now.minute) <= WINDOW_END
        r = process_day(ctx, day, today_pending=pending_ok)
        rep.days.append(r)
        ctx.out(r.line())
        if r.status == "NO_FILE":
            journal(ctx, day, "NO_FILE", r.detail)
        elif r.status == "LOADED":
            journal(ctx, day, "LOADED", r.file)
            first_loaded = first_loaded or day
        elif r.status == "PENDING":
            pending = True
        elif r.status in ("FAILED", "REFUSED"):
            failed = True
            break                                            # never load a later day over a day that could still be filled (the seal moves forward only)
    if plan_only:
        return rep
    if steps:
        if not failed:
            rep.notes.append(asm_step(ctx, today))
        first = first_loaded or (today - timedelta(days=7))
        rep.notes.append(corporate_actions_step(ctx, min(first, today - timedelta(days=7)), today))
    rep.exit_code = 1 if failed else (3 if pending else 0)
    return rep


# ------------------------------------------------------------------------------------------------------------------------------ command line
def summary(rep: RunReport, ctx: Ctx, files: list) -> str:
    n = lambda s: sum(1 for d in rep.days if d.status == s)  # noqa: E731
    lines = [f"=== daily data update {rep.started} (IST) db={ctx.db} ===",
             f"days loaded {n('LOADED')} | already sealed {n('ALREADY_SEALED')} | no file {n('NO_FILE')} | pending {n('PENDING')} | refused/failed {n('REFUSED') + n('FAILED')} | skipped {n('NO_FILE_FINAL') + n('SKIPPED_RECHECKED_TODAY')}",
             f"files downloaded: {', '.join(d.file for d in rep.days if d.downloaded) or 'none'}"]
    lines += ["  " + d.line() for d in rep.days if d.status not in ("NO_FILE_FINAL", "SKIPPED_RECHECKED_TODAY")]
    lines += ["  " + x for x in rep.notes]
    lines.append(f"exit code {rep.exit_code}")
    return "\n".join(lines)


def main(argv=None) -> int:
    from stockbot.config.paths import lake_path
    from stockbot.data.guard import runlock
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=None, help="database file (default: STOCKBOT_DB or <repo>/finsight.db)")
    ap.add_argument("--data-root", default=os.environ.get("STOCKBOT_DATA_ROOT") or str(DEFAULT_ROOT))
    ap.add_argument("--through", help="last date to process, YYYY-MM-DD (default: today)")
    ap.add_argument("--catch-up-only", action="store_true", help="never try today's date (the morning re-check)")
    ap.add_argument("--scheduled", action="store_true", help="the Task Scheduler run: today's date is attempted only between 19:30 and 23:45 IST")
    ap.add_argument("--plan", action="store_true", help="list the dates that would be checked; no network, no write, no lock")
    ap.add_argument("--no-extras", action="store_true", help="skip the corporate-actions and ASM/GSM steps")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between requests")
    a = ap.parse_args(argv)
    ctx = Ctx(db=Path(a.db) if a.db else lake_path(), root=Path(a.data_root))
    ctx.download = Downloader(gap=a.sleep).get if not a.plan else None
    through = date.fromisoformat(a.through) if a.through else None
    ctx.logs.mkdir(parents=True, exist_ok=True)
    log_path = ctx.logs / f"daily_update_{ctx.now().strftime('%Y%m%d_%H%M%S')}.log"
    logf = open(log_path, "a", encoding="utf-8")

    def out(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()
    ctx.out = out
    lock = None
    try:
        if not a.plan:
            try:
                lock = runlock.acquire_daily(ctx.db, ctx.lock_dir)
            except runlock.LockRefused as e:
                out(f"[{ctx.now().isoformat(timespec='seconds')}] {e.message}")
                return e.code
        rep = run(ctx, through=through, catch_up_only=a.catch_up_only, scheduled=a.scheduled, plan_only=a.plan, steps=not a.no_extras)
        out(summary(rep, ctx, []))
        out(f"log: {log_path}")
        return rep.exit_code
    except Exception:  # noqa: BLE001
        out("ERROR\n" + traceback.format_exc())
        return 1
    finally:
        runlock.release(lock)
        logf.close()


if __name__ == "__main__":
    sys.exit(main())

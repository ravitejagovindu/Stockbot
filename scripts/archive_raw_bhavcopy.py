"""scripts/archive_raw_bhavcopy.py - download the ORIGINAL NSE cash-market Bhavcopy file for every trading day and keep it UNMODIFIED.

Why: the lake keeps EQ rows only; the other series (BE, BZ, BL, SM, ST ...) are in the original daily file and nowhere else on this machine.
The old loader (stockbot/data/ingestion/ingest_raw_bhavcopy_range.py) is NOT touched and saves no raw file; this script is separate.

Output (default F:\\Projects\\Ravi\\StockBotData\\raw_bhavcopy):
  YYYY/<original file name>      the bytes exactly as served (never rewritten; an existing valid file is skipped)
  MANIFEST.csv                   date,file_name,url,bytes,sha256,pattern,status   (append-only journal; the last row of a date wins)

Trading days = every distinct trade_date in market_data_lake (read-only, open_lake) up to --end (default 2026-10-16), plus --extra dates.
URL patterns, tried in the order valid for the date (UDiFF first from 2024-07-01, legacy first before):
  UDIFF   https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
  FULL    https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
  LEGACY  https://archives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
A file is accepted only if it is readable and the trade date INSIDE it equals the requested date (NSE serves the previous session's file for sec_bhavdata_full on holidays).
Pacing: >= 1 s between any two requests; retries with exponential backoff; a block (403/429 or repeated failures on several dates in a row) STOPS the run with the exact error - no workaround.

  py -3 scripts/archive_raw_bhavcopy.py [--out DIR] [--end 2026-10-16] [--limit N] [--sleep 1.0]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_OUT = Path(r"F:\Projects\Ravi\StockBotData\raw_bhavcopy")
UDIFF_FROM = date(2024, 7, 1)
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/all-reports",
}
FIELDS = ["date", "file_name", "url", "bytes", "sha256", "pattern", "status"]
STOP_AFTER_BLOCKED_DATES = 5


def candidates(d: date) -> list[tuple[str, str, str]]:
    """[(pattern, file_name, url)] in the order valid for d."""
    ymd, dmy, mon = d.strftime("%Y%m%d"), d.strftime("%d%m%Y"), d.strftime("%b").upper()
    u = (f"BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip", )[0]
    udiff = ("UDIFF", u, f"https://nsearchives.nseindia.com/content/cm/{u}")
    f = f"sec_bhavdata_full_{dmy}.csv"
    full = ("FULL", f, f"https://nsearchives.nseindia.com/products/content/{f}")
    lg = f"cm{d.strftime('%d')}{mon}{d.year}bhav.csv.zip"
    legacy = ("LEGACY", lg, f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/{mon}/{lg}")
    return [udiff, full, legacy] if d >= UDIFF_FROM else [legacy, udiff, full]


def _csv_bytes(name: str, content: bytes) -> bytes:
    if name.lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(content))
        if z.testzip() is not None:
            raise ValueError("zip member fails its CRC")
        members = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise ValueError("zip holds no csv")
        return z.read(members[0])
    return content


def declared_date(name: str, content: bytes) -> date | None:
    """The trade date the file itself declares (TIMESTAMP / DATE1 / TradDt), None if it cannot be read."""
    rows = csv.reader(io.StringIO(_csv_bytes(name, content).decode("utf-8", "replace")))
    head = [h.strip().upper() for h in next(rows)]
    first = next(rows)
    for key in ("TRADDT", "TIMESTAMP", "DATE1"):
        if key in head:
            v = first[head.index(key)].strip()
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    pass
    return None


def valid_file(path: Path, d: date) -> bool:
    try:
        c = path.read_bytes()
        return len(c) > 200 and declared_date(path.name, c) == d
    except Exception:  # noqa: BLE001
        return False


class Blocked(Exception):
    pass


class Pacer:
    def __init__(self, gap: float):
        self.gap, self.last = gap, 0.0

    def wait(self):
        w = self.last + self.gap - time.monotonic()
        if w > 0:
            time.sleep(w)
        self.last = time.monotonic()


def fetch(sess, pacer, url, tries=4):
    """(status_code | None, content, note). Retries network errors / 5xx / 403 / 429 with backoff 2,4,8 s."""
    note = ""
    for k in range(tries):
        pacer.wait()
        try:
            r = sess.get(url, timeout=40)
        except requests.RequestException as e:
            note = f"{type(e).__name__}: {e}"
            time.sleep(2 ** (k + 1))
            continue
        if r.status_code == 200:
            return 200, r.content, ""
        if r.status_code == 404:
            return 404, b"", "404"
        note = f"HTTP {r.status_code}"
        time.sleep(2 ** (k + 1))
    return None, b"", note


def load_manifest(p: Path) -> dict:
    out = {}
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                out[row["date"]] = row
    return out


def trading_days(end: date, extra: list[str]) -> list[date]:
    from stockbot.data.lake import open_lake
    con = open_lake()
    try:
        ds = {r[0] for r in con.execute("SELECT DISTINCT trade_date FROM market_data_lake WHERE trade_date<=?", (end.isoformat(),))}
    finally:
        con.close()
    ds |= set(extra)
    return sorted(date.fromisoformat(x) for x in ds)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--end", default="2026-10-16")
    ap.add_argument("--extra", default="", help="comma-separated extra session dates (e.g. special Saturday sessions)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N dates (test)")
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "MANIFEST.csv"
    done = load_manifest(mpath)
    days = trading_days(date.fromisoformat(a.end), [x for x in a.extra.split(",") if x])
    print(f"trading days {len(days)} ({days[0]} .. {days[-1]}); manifest rows {len(done)}", flush=True)
    new = not mpath.exists()
    mf = open(mpath, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(mf, fieldnames=FIELDS)
    if new:
        w.writeheader()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    pacer = Pacer(a.sleep)
    n_new = n_skip = n_miss = 0
    blocked_run = 0
    t0 = time.time()

    def journal(d, name, url, size, sha, pat, status):
        w.writerow({"date": d.isoformat(), "file_name": name, "url": url, "bytes": size, "sha256": sha, "pattern": pat, "status": status})
        mf.flush()

    for i, d in enumerate(days):
        if a.limit and i >= a.limit:
            break
        folder = out / str(d.year)
        prev = done.get(d.isoformat())
        # resume: a file already present and valid is skipped (and journalled once if the manifest lacks it)
        cands = candidates(d)
        present = next((c for c in cands if (folder / c[1]).exists()), None)
        if present and valid_file(folder / present[1], d):
            if not prev or prev["status"] != "OK" or prev["file_name"] != present[1]:
                c = (folder / present[1]).read_bytes()
                journal(d, present[1], present[2], len(c), hashlib.sha256(c).hexdigest(), present[0], "OK")
            n_skip += 1
            continue
        got = None
        note = ""
        saw_block = False
        for pat, name, url in cands:
            code, content, why = fetch(sess, pacer, url)
            if code == 404:
                note += f"{pat}:404 "
                continue
            if code is None:
                note += f"{pat}:{why} "
                saw_block = saw_block or ("403" in why or "429" in why)
                continue
            try:
                dd = declared_date(name, content)
            except Exception as e:  # noqa: BLE001
                note += f"{pat}:unreadable({e}) "
                continue
            if len(content) <= 200 or dd != d:
                note += f"{pat}:file declares {dd} "
                continue
            got = (pat, name, url, content)
            break
        if got:
            pat, name, url, content = got
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            if target.exists():                      # never overwrite: an existing but invalid file stays, the new one gets a suffix
                target = folder / (name + f".new{int(time.time())}")
            with open(target, "xb") as f:
                f.write(content)
            journal(d, target.name, url, len(content), hashlib.sha256(content).hexdigest(), pat, "OK")
            n_new += 1
            blocked_run = 0
        else:
            only404 = all(x.endswith(":404") for x in note.split())
            journal(d, "", "", 0, "", "", "MISSING_404" if only404 else "ERROR " + note.strip())
            n_miss += 1
            blocked_run = blocked_run + 1 if (saw_block or not only404) else 0
            print(f"{d} NOT FETCHED: {note.strip()}", flush=True)
            if blocked_run >= STOP_AFTER_BLOCKED_DATES:
                print(f"STOP: {blocked_run} dates in a row failed with errors other than 404 (last: {note.strip()}). Not working around it.", flush=True)
                mf.close()
                return 2
        if (n_new + n_skip + n_miss) % 100 == 0:
            print(f"{d} new={n_new} skipped={n_skip} not_fetched={n_miss} elapsed={time.time() - t0:.0f}s", flush=True)
    mf.close()
    print(f"DONE new={n_new} skipped={n_skip} not_fetched={n_miss} elapsed={time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

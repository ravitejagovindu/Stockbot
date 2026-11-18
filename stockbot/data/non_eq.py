"""Non-EQ series rows (BE, BZ, BL) of the NSE equity Bhavcopy: the table, the switch, and the parsing of an archived original file.

Owner rule (fixed): buy only on EQ. A held position in a BE/BZ stock may be held or sold. The table exists so that a HELD position can be marked, stopped and sold on the days its stock trades
in BE/BZ; the universe, eligibility, ADTV, ranking and entries never read it (see ``stockbot.data.asof``, ``stockbot.engine.series_rule``).

Switch: ``STOCKBOT_NON_EQ=held`` makes the as-of view read this table for held positions. Default OFF: with the switch off nothing in this table is read by any engine code.
Standard library + pandas only (no stockbot imports), so ``stockbot.data.asof`` can import it.
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import date

TABLE = "market_data_non_eq"
LOAD_SERIES = ("BE", "BZ", "BL")               # owner decision Q1: only these are loaded
BAR_SERIES = ("BE", "BZ")                      # the series whose rows are bars of a held stock; BL (block-deal window) rows coexist with EQ/BE rows of the same day and never form a bar
BAR_PRIORITY = {"EQ": 0, "BE": 1, "BZ": 2}     # one bar per (symbol, day): EQ first, then BE, then BZ
COLUMNS = ("symbol", "trade_date", "series", "isin", "open_raw", "high_raw", "low_raw", "close_raw", "prev_close", "volume_raw", "trades", "traded_value", "source_file")

DDL = """
CREATE TABLE IF NOT EXISTS market_data_non_eq (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    series        TEXT NOT NULL,
    isin          TEXT,
    open_raw      REAL NOT NULL,
    high_raw      REAL NOT NULL,
    low_raw       REAL NOT NULL,
    close_raw     REAL NOT NULL,
    prev_close    REAL,
    volume_raw    INTEGER NOT NULL,
    trades        INTEGER,
    traded_value  REAL,
    source_file   TEXT,
    created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    UNIQUE(symbol, trade_date, series)
);
CREATE INDEX IF NOT EXISTS idx_non_eq_date ON market_data_non_eq(trade_date);
CREATE INDEX IF NOT EXISTS idx_non_eq_isin ON market_data_non_eq(isin, trade_date);
"""

_PICK = {
    "symbol": ("SYMBOL", "TckrSymb"), "series": ("SERIES", "SctySrs"), "open_raw": ("OPEN", "OPEN_PRICE", "OpnPric"), "high_raw": ("HIGH", "HIGH_PRICE", "HghPric"),
    "low_raw": ("LOW", "LOW_PRICE", "LwPric"), "close_raw": ("CLOSE", "CLOSE_PRICE", "ClsPric"), "prev_close": ("PREVCLOSE", "PREV_CLOSE", "PrvsClsgPric"),
    "volume_raw": ("TOTTRDQTY", "TTL_TRD_QNTY", "TtlTradgVol"), "trades": ("TOTALTRADES", "NO_OF_TRADES", "TtlNbOfTxsExctd"), "isin": ("ISIN",),
    "traded_value": ("TOTTRDVAL", "TtlTrfVal"),
}


def switch_on() -> bool:
    """True when STOCKBOT_NON_EQ=held. The one place the variable is read."""
    return os.environ.get("STOCKBOT_NON_EQ", "").strip().lower() == "held"


def switch_name() -> str:
    return "held" if switch_on() else "off"


def csv_text(path) -> str:
    """The csv text of an archived original file (a .zip holds one csv; a .csv is read as is)."""
    raw = open(path, "rb").read()
    if str(path).lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read([n for n in z.namelist() if n.lower().endswith(".csv")][0])
    return raw.decode("utf-8", "replace")


def file_series_count(path, series=LOAD_SERIES) -> int:
    """INDEPENDENT row count: the number of data rows of the file whose series is in ``series`` (plain csv module, no pandas), used to check a day's load."""
    import csv
    rows = csv.reader(io.StringIO(csv_text(path)))
    head = [h.strip() for h in next(rows)]
    col = next(head.index(c) for c in _PICK["series"] if c in head)
    return sum(1 for r in rows if len(r) > col and r[col].strip() in series)


def parse_rows(path, day: date, source_file: str, series=LOAD_SERIES) -> list:
    """The rows (tuples in COLUMNS order) of the file with a series in ``series``. Raises on a missing column or an unparsable price: nothing is zero-filled."""
    import pandas as pd
    df = pd.read_csv(io.StringIO(csv_text(path)), dtype=str, skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    col = {}
    for k, opts in _PICK.items():
        c = next((o for o in opts if o in df.columns), None)
        col[k] = c
    need = ("symbol", "series", "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw")
    miss = [k for k in need if col[k] is None]
    if miss:
        raise ValueError(f"{source_file}: unrecognised layout, missing {miss}: {list(df.columns)}")
    sel = df[df[col["series"]].astype(str).str.strip().isin(series)]

    def column(k, integer=False, required=True):
        c = col[k]
        if c is None:
            if required:
                raise ValueError(f"{source_file}: no column for {k}")
            return [None] * len(sel)
        raw = sel[c].astype(str).str.strip().str.replace(",", "", regex=False)
        blank = raw.isin(["", "nan", "-", "None"])
        if required and blank.any():
            raise ValueError(f"{source_file}: {sel.loc[blank, col['symbol']].tolist()[:3]} have no {k}")
        num = pd.to_numeric(raw.where(~blank), errors="coerce")
        if required and num.isna().any():
            raise ValueError(f"{source_file}: unparsable {k} for {sel.loc[num.isna(), col['symbol']].tolist()[:3]}")
        if integer:
            return [None if pd.isna(v) else int(round(v)) for v in num]
        return [None if pd.isna(v) else float(v) for v in num]

    tv = column("traded_value", required=False)
    if col["traded_value"] is None and "TURNOVER_LACS" in df.columns:
        lacs = pd.to_numeric(sel["TURNOVER_LACS"].astype(str).str.strip(), errors="coerce")
        tv = [None if pd.isna(v) else float(v) * 100000.0 for v in lacs]
    isin = sel[col["isin"]].astype(str).str.strip() if col["isin"] else pd.Series([""] * len(sel), index=sel.index)
    isins = [v if len(v) == 12 else None for v in isin]
    cols = [list(sel[col["symbol"]].astype(str).str.strip()), [day.isoformat()] * len(sel), list(sel[col["series"]].astype(str).str.strip()), isins,
            column("open_raw"), column("high_raw"), column("low_raw"), column("close_raw"), column("prev_close", required=False),
            column("volume_raw", integer=True), column("trades", integer=True, required=False), tv, [source_file] * len(sel)]
    return list(zip(*cols))

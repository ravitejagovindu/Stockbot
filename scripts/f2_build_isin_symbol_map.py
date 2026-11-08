"""scripts/f2_build_isin_symbol_map.py — deterministic ISIN -> canonical symbol map (reviewer: Option A).

Reads staging (read-only) and the NSE corporate-actions dump.  For every ISIN that traded under more than one
symbol it classifies each symbol-change boundary and the ISIN as a whole:

  pure_rename      same ISIN, no overlap, short gap, raw close continuous (0.8..1.25) and no demerger/merger/arrangement
                   in the NSE feed within +-45 days  -> canonical_symbol = the ISIN's latest symbol, applied to ALL years
  demerger_merger  NSE feed has a DEMERGER/MERGER/arrangement for either symbol near the boundary -> stays split
  other            overlapping dates, gap > 20 sessions (relisting/suspension) or a price step without a feed event
                   -> stays split, listed for hand review

Output: data/reference/isin_symbol_map.csv (one row per ISIN x symbol segment) and a summary on stdout.
The ISIN-less rows are not touched.  Deterministic: same inputs -> same file.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stockbot.data.ingestion.nse_corporate_actions_history import _parse_ex, parse_subject  # noqa: E402

CONT_LO, CONT_HI = 0.8, 1.25
MAX_GAP_SESSIONS = 20
EVENT_WINDOW_DAYS = 45
OUT = ROOT / "data" / "reference" / "isin_symbol_map.csv"


def structural_events(csv_path: Path) -> dict[str, list[tuple[date, str]]]:
    raw = pd.read_csv(csv_path)
    ev: dict[str, list[tuple[date, str]]] = {}
    for r in raw.itertuples():
        ex = _parse_ex(r.exDate)
        if ex is None:
            continue
        for a in parse_subject(str(r.subject)):
            if a["action_type"] in ("DEMERGER", "MERGER"):
                for key in {str(r.symbol).strip(), str(r.query_symbol).strip()}:
                    ev.setdefault(key, []).append((ex, a["action_type"]))
    return ev


def build(db: str, actions_csv: Path) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=ON")
    seg = pd.read_sql("select isin, symbol, min(trade_date) first_date, max(trade_date) last_date, count(*) n_days "
                      "from market_data_lake_staging where isin is not null and isin not in ('nan','') "
                      "group by isin, symbol", con)
    multi = seg.groupby("isin")["symbol"].nunique()
    seg = seg[seg["isin"].isin(multi[multi > 1].index)].sort_values(["isin", "first_date", "symbol"]).reset_index(drop=True)
    sessions = [r[0] for r in con.execute("select trade_date from bhavcopy_fetch_log where status='OK' order by 1")]
    pos = {d: i for i, d in enumerate(sessions)}
    events = structural_events(actions_csv)

    def close(sym: str, d: str):
        r = con.execute("select close_raw from market_data_lake_staging where symbol=? and trade_date=?", (sym, d)).fetchone()
        return r[0] if r else None

    rows = []
    for isin, g in seg.groupby("isin", sort=True):
        g = g.sort_values(["first_date", "symbol"]).reset_index(drop=True)
        bounds = []
        for i in range(len(g) - 1):
            a, b = g.iloc[i], g.iloc[i + 1]
            gap = pos.get(b["first_date"], 0) - pos.get(a["last_date"], 0) - 1
            ca, cb = close(a["symbol"], a["last_date"]), close(b["symbol"], b["first_date"])
            ratio = (cb / ca) if (ca and cb) else float("nan")
            bd = date.fromisoformat(b["first_date"])
            struct = [t for s in (a["symbol"], b["symbol"]) for (d, t) in events.get(s, [])
                      if abs((d - bd).days) <= EVENT_WINDOW_DAYS]
            if struct:
                cls, why = "demerger_merger", f"feed {sorted(set(struct))} within {EVENT_WINDOW_DAYS}d"
            elif b["first_date"] <= a["last_date"]:
                cls, why = "other", "dates overlap (two symbols trade at once)"
            elif gap > MAX_GAP_SESSIONS:
                cls, why = "other", f"gap of {gap} sessions"
            elif not (CONT_LO <= ratio <= CONT_HI):
                cls, why = "other", f"price step {ratio:.3f} without a feed event"
            else:
                cls, why = "pure_rename", "continuous"
            bounds.append((cls, why, gap, ratio))
        order = {"pure_rename": 0, "other": 1, "demerger_merger": 2}
        worst = max((b[0] for b in bounds), key=lambda c: order[c])
        canonical = g.iloc[-1]["symbol"]  # latest start
        for i in range(len(g)):
            r = g.iloc[i]
            nb = bounds[i] if i < len(bounds) else (None, "", None, None)
            rows.append({
                "isin": isin, "symbol": r["symbol"], "segment": i + 1, "first_date": r["first_date"],
                "last_date": r["last_date"], "n_days": int(r["n_days"]),
                "isin_class": worst,
                "canonical_symbol": canonical if worst == "pure_rename" else r["symbol"],
                "boundary_to_next": nb[0] or "", "boundary_reason": nb[1],
                "gap_sessions": nb[2] if nb[2] is not None else "",
                "close_ratio_next_over_this": round(nb[3], 4) if nb[3] == nb[3] and nb[3] is not None else "",
            })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--actions-csv", default=str(ROOT / "data" / "reference" / "nse_corporate_actions_raw.csv"))
    a = ap.parse_args()
    df = build(a.db, Path(a.actions_csv))
    df.to_csv(OUT, index=False)
    isins = df.drop_duplicates("isin")
    print("ISINs with more than one symbol:", len(isins))
    print(isins["isin_class"].value_counts().to_string())
    print("segments remapped to a different symbol:", int((df["canonical_symbol"] != df["symbol"]).sum()),
          "rows written to", OUT)


if __name__ == "__main__":
    main()

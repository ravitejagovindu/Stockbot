"""stockbot/data_checks/f2_engine_scan.py - post-adjustment scan of large moves through the engine's real adjustment path, read through the AS-OF VIEW.

Adjusts with ``stockbot.data.adjustments.get_adjusted_series`` from ``corporate_actions_log`` rows keyed by lake symbol (the view does exactly that), as of 2026-09-30.
Counts |adjusted close-to-close move| > 40% on ADTV-eligible equity names (raw price >= Rs5), 2013-01-01..2026-09-30. Read-only.
Output: docs/data_audit/engine_scan_<tag>.md (+ csv).

Since restructure Phase 10 the old equivalence check against ``engine_core.candidate_builder`` is gone with that module. Its place is taken by FROZEN results committed under
``tests/golden`` (written while the old path still existed, with their sha256): this scan must reproduce ``engine_scan.csv`` and ``engine_scan_summary.json`` exactly.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "data_audit"
GOLD = ROOT / "tests" / "golden"
THR, MIN_PX, AS_OF, LO = 0.40, 5.0, date(2026, 9, 30), date(2013, 1, 1)


def scan(conn, as_of: date = AS_OF, eligible_csv: Path = OUT / "eligible_symbols.csv", unadjusted_csv: Path = ROOT / "data/reference/unadjusted_events.csv") -> tuple:
    """Return (residual dataframe, summary dict). ``conn`` is a read-only lake connection."""
    from stockbot.data.asof import AsOfView
    view = AsOfView(conn, as_of)
    el = pd.read_csv(eligible_csv)
    funds = set(el[el["eligible"] & el["is_fund_or_etf"]]["symbol"])
    elig = set(el[el["eligible"]]["symbol"]) - funds
    imap = pd.read_sql_query("select isin, symbol, canonical_symbol from isin_symbol_map", conn)
    syms = sorted(set(imap[imap["symbol"].isin(elig)]["canonical_symbol"]) | {x for x in elig if x not in set(imap["symbol"])})
    ua = pd.read_csv(unadjusted_csv)
    ua_dates = ua.groupby("lake_symbol")["date"].apply(list).to_dict()
    raw_n = adj_n = fixed = created = scanned = 0
    resid = []
    for sym in syms:
        raw = view.raw_bars(sym, None, start=LO)
        if raw is None or len(raw) < 2:
            continue
        adj = view.adjusted_bars(sym, None, start=LO)
        r_raw = raw["close_raw"] / raw["close_raw"].shift(1)
        r_adj = adj["close_adj"] / adj["close_adj"].shift(1)
        ok_px = np.minimum(raw["close_raw"], raw["close_raw"].shift(1)) >= MIN_PX
        big_raw, big_adj = ((r_raw - 1).abs() > THR) & ok_px, ((r_adj - 1).abs() > THR) & ok_px
        raw_n += int(big_raw.sum()); adj_n += int(big_adj.sum())
        fixed += int((big_raw & ~big_adj).sum()); created += int((~big_raw & big_adj).sum())
        idx = list(raw.index)
        for j in np.flatnonzero(big_adj.values):
            d, pd_ = idx[j], idx[j - 1]
            gap = (d - pd_).days
            near = any(abs((pd.Timestamp(d) - pd.Timestamp(x)).days) <= 30 for x in ua_dates.get(sym, []))
            resid.append((sym, str(d), round(float(r_adj.iloc[j] - 1), 3), round(float(r_raw.iloc[j] - 1), 3), gap,
                          "after_gap_in_EQ_series" if gap > 30 else ("near_unadjusted_event" if near else "residual_no_explanation"), bool(big_raw.iloc[j])))
        scanned += 1
    rdf = pd.DataFrame(resid, columns=["symbol", "date", "adjusted_move", "raw_move", "gap_days", "category", "was_big_before_adjustment"])
    summary = {"names_scanned": scanned, "large_before": raw_n, "large_after": adj_n, "removed": fixed, "created": created, "as_of": as_of.isoformat(), "threshold": THR,
               "min_price": MIN_PX, "remaining_by_category": {k: int(v) for k, v in rdf.groupby("category").size().items()}}
    return rdf, summary


def compare_with_frozen(rdf: pd.DataFrame, summary: dict, gold: Path = GOLD) -> list:
    """Differences between this scan and the frozen result of the old path (empty list = identical)."""
    diffs = []
    frozen = json.loads((gold / "engine_scan_summary.json").read_text(encoding="utf-8"))
    for k, v in frozen.items():
        if summary.get(k) != v:
            diffs.append(f"summary[{k}]: now {summary.get(k)!r}, frozen {v!r}")
    fcsv = pd.read_csv(gold / "engine_scan.csv")
    if not fcsv.equals(pd.read_csv(pd.io.common.StringIO(rdf.to_csv(index=False)))):
        diffs.append(f"residual list differs from the frozen csv ({len(rdf)} rows now, {len(fcsv)} frozen)")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().partition(chr(10))[0])
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    ap.add_argument("--tag", default="real")
    a = ap.parse_args()
    from stockbot.data.lake import open_lake
    rdf, summary = scan(open_lake(a.db))
    rdf.to_csv(OUT / f"engine_scan_{a.tag}.csv", index=False)
    diffs = compare_with_frozen(rdf, summary)
    lines = [f"# Engine-path scan ({a.tag})\n", f"Database: `{a.db}`.  Read through the as-of view; adjusted with `stockbot.data.adjustments.get_adjusted_series` from `corporate_actions_log` rows keyed by lake symbol.\n",
             f"Names scanned: {summary['names_scanned']}.\n", "```", f"large moves before adjustment : {summary['large_before']}", f"large moves after adjustment  : {summary['large_after']}",
             f"  removed by adjusting        : {summary['removed']}", f"  created by adjusting        : {summary['created']}", "```\n", "Remaining by category:\n", "```",
             rdf.groupby("category").size().to_string(), "```\n",
             "Comparison with the FROZEN result of the old path (tests/golden): " + ("identical.\n" if not diffs else "DIFFERENT: " + "; ".join(diffs) + "\n")]
    (OUT / f"engine_scan_{a.tag}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())

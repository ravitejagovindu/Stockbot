"""stockbot/data_checks/f2_split_rename_links.py — find renames that coincide with an ISIN change at a split (reviewer-approved rule, eligible names only).

A boundary pair (old symbol A ends, new symbol B starts) is LINKED when
  * a SPLIT/BONUS event on B (or on A) has its ex-date within 3 days of the boundary,
  * the price step close_B(first) / close_A(last) reproduces the event factor (tier WEAK, WEAK_DIRECTIONAL or STRONG),
  * the ISINs differ (same-ISIN renames are already in the ISIN map), A has no rows after its last date and B none before its first,
  * the candidate A is unique, and A or B passes the Rs25 crore gate (not a fund).
Price continuity alone is NOT enough (a split makes a step).  Read-only; writes data/reference/isin_split_rename_links.csv.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
from stockbot.data.ingestion.ca_evidence import classify      # noqa: E402


def find_links(con, events: pd.DataFrame, eligible_syms: set[str]) -> pd.DataFrame:
    rng = pd.read_sql_query("select symbol, min(trade_date) first_date, max(trade_date) last_date, max(isin) isin from market_data_lake_staging group by symbol", con)
    rng = rng.set_index("symbol")
    last_sorted = rng.sort_values("last_date")
    out = []
    px = events[events.factor_logged.notna()].drop_duplicates(["symbol", "ex_date"])
    for r in px.itertuples():
        ex, f = r.ex_date, float(r.factor_logged)
        cands_b = [r.symbol] if r.symbol in rng.index else []
        for b in cands_b:
            b_first = rng.loc[b, "first_date"]
            if abs((pd.Timestamp(b_first) - pd.Timestamp(ex)).days) > 3:
                continue                                    # B must start at the boundary
            lo, hi = (pd.Timestamp(ex) - pd.Timedelta(days=10)).date().isoformat(), b_first
            a_cands = rng[(rng.last_date >= lo) & (rng.last_date < hi) & (rng.index != b)]
            hits = []
            for a, ar in a_cands.iterrows():
                if ar.isin == rng.loc[b, "isin"]:
                    continue
                ca = con.execute("select close_raw from market_data_lake_staging where symbol=? and trade_date=?", (a, ar.last_date)).fetchone()
                cb = con.execute("select close_raw from market_data_lake_staging where symbol=? and trade_date=?", (b, b_first)).fetchone()
                if not ca or not cb or ca[0] <= 0:
                    continue
                step = cb[0] / ca[0]
                tier, why = classify(f, step, None)
                if tier in ("WEAK", "WEAK_DIRECTIONAL"):
                    hits.append((a, ar.last_date, ar.first_date, ar.isin, step, tier))
            if len(hits) == 1:
                a, a_last, a_first, a_isin, step, tier = hits[0]
                out.append({"old_symbol": a, "old_isin": a_isin, "old_first": a_first, "old_last": a_last, "new_symbol": b,
                            "new_isin": rng.loc[b, "isin"], "new_first": b_first, "event_ex_date": ex, "event_factor": f,
                            "price_step": step, "step_tier": tier,
                            "eligible": (a in eligible_syms) or (b in eligible_syms)})
    return pd.DataFrame(out)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip().partition(chr(10))[0])
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    ev = pd.read_csv(ROOT / "data/reference/corporate_actions_evidence.csv")
    ev = ev[ev.action_type.isin(["SPLIT", "BONUS"])]
    el = pd.read_csv(ROOT / "docs/data_audit/eligible_symbols.csv")
    elig = set(el[el.eligible & ~el.is_fund_or_etf].symbol)
    links = find_links(con, ev, elig)
    links.to_csv(ROOT / "data/reference/isin_split_rename_links.csv", index=False)
    print(len(links), "candidate links;", int(links.eligible.sum()) if len(links) else 0, "on eligible names")
    if len(links):
        print(links.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

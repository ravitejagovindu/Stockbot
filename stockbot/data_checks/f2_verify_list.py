"""stockbot/data_checks/f2_verify_list.py — F2 Step 6: add result columns to data/reference/verified_corporate_actions.csv and extend it.

Result columns: logged_factor (group product for same-day events), observed_raw_ratio, yahoo_factor, tier, result (PASS/FAIL), result_note.
Rules: price-moving rows (SPLIT/BONUS) PASS when the logged factor equals the expected factor (1%) and the tier is STRONG or WEAK;
DEMERGER/RIGHTS rows PASS when the feed has the event and it is stored as non-price-moving (never as a SPLIT/BONUS);
the symbol_change row PASSES when the ISIN map keeps the demerger pair split (class demerger_merger).
Rows added automatically (deterministic): a liquid name with a split and a bonus in the same year on DIFFERENT dates, and a
name that was suspended/relisted (ISIN class 'other') with a price-moving event after the gap.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V = ROOT / "data/reference/verified_corporate_actions.csv"
E = ROOT / "data/reference/corporate_actions_evidence.csv"
BASIS = "added in Step 6 (deterministic pick from the evidence file)"


def main() -> int:
    v = pd.read_csv(V)
    keep = [c for c in v.columns if c not in ("logged_factor", "observed_raw_ratio", "yahoo_factor", "tier", "result", "result_note")]
    v = v[keep]
    ev = pd.read_csv(E)
    elig = pd.read_csv(ROOT / "docs/data_audit/eligible_symbols.csv")
    liquid = set(elig[elig.eligible & ~elig.is_fund_or_etf].symbol)
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True)
    imap = pd.read_sql_query("select isin, symbol, canonical_symbol, isin_class from isin_symbol_map", con)

    # ---- extend (only once)
    if not v.category.isin(["same_year_split_and_bonus_different_dates", "relisted_or_suspended"]).any():
        pm = ev[ev.action_type.isin(["SPLIT", "BONUS"]) & ev.tier.isin(["STRONG", "WEAK"])].copy()
        pm["year"] = pm.ex_date.str[:4]
        add = []
        for (sym, yr), g in pm.groupby(["symbol", "year"]):
            if sym in liquid and set(g.action_type) == {"SPLIT", "BONUS"} and g[g.action_type == "SPLIT"].ex_date.iloc[0] != g[g.action_type == "BONUS"].ex_date.iloc[0] \
                    and (g.tier == "STRONG").all():
                add.append(g)
        for g in add[:2]:
            for r in g.itertuples():
                v.loc[len(v)] = [r.symbol, r.ex_date, r.action_type, r.num, r.den, round(r.factor_logged, 6), "same_year_split_and_bonus_different_dates",
                                 "rebase", f"{r.subject[:80]}", BASIS]
        gapmap = imap[imap['isin_class'] == "other"]
        gap_isins = set(gapmap['isin'])
        cand = ev[ev.action_type.isin(["SPLIT", "BONUS"]) & ev.tier.isin(["STRONG", "WEAK"]) & ev['isin'].isin(gap_isins) & ev.symbol.isin(liquid)].sort_values(["symbol", "ex_date"])
        for r in cand.head(2).itertuples():
            v.loc[len(v)] = [r.symbol, r.ex_date, r.action_type, r.num, r.den, round(r.factor_logged, 6), "relisted_or_suspended",
                             "rebase", f"{r.subject[:80]}; ISIN class 'other' (gap in the EQ series)", BASIS]

    # ---- results
    res = []
    evk = ev.set_index(["symbol", "ex_date", "action_type"])
    for r in v.itertuples():
        key = (r.symbol, r.ex_date, r.action_type)
        row = evk.loc[key] if key in evk.index else None
        if row is not None and isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        if r.action_type in ("SPLIT", "BONUS"):
            if row is None:
                res.append((np.nan, np.nan, np.nan, "MISSING", "FAIL", "event not in the evidence file")); continue
            f_ok = abs(row.factor_logged / r.expected_factor - 1) < 0.01 or (str(r.category).startswith("same_date") and True)
            if str(r.category).startswith("same_date"):
                same = ev[(ev.symbol == r.symbol) & (ev.ex_date == r.ex_date) & ev.action_type.isin(["SPLIT", "BONUS"])]
                prod = float(np.prod(v[(v.symbol == r.symbol) & (v.ex_date == r.ex_date)].expected_factor))
                f_ok = abs(row.factor_logged / prod - 1) < 0.01 and set(same.action_type) == {"SPLIT", "BONUS"}
            ok = bool(f_ok) and row.tier in ("STRONG", "WEAK")
            res.append((row.factor_logged, row.raw_ratio, row.yahoo_factor, row.tier, "PASS" if ok else "FAIL",
                        "" if ok else f"factor ok={bool(f_ok)}; {str(row.evidence)[:160]}"))
        elif r.category == "symbol_change":
            cls = imap[imap.symbol.isin([r.symbol, "TMPV"])].groupby("symbol")["isin_class"].first().to_dict()
            ok = cls.get("TATAMOTORS") == "demerger_merger" and cls.get("TMPV") == "demerger_merger"
            res.append((np.nan, np.nan, np.nan, "NOT_PRICE_MOVING", "PASS" if ok else "FAIL", f"ISIN map classes: {cls}"))
        else:   # demerger / rights: present in the feed and never stored as a price-moving type
            ok = row is not None and r.action_type in ("DEMERGER", "RIGHTS") and row.stored_action_type == r.action_type
            res.append((np.nan, np.nan, np.nan, "NOT_PRICE_MOVING", "PASS" if ok else "FAIL",
                        "feed has the event; stored as " + (str(row.stored_action_type) if row is not None else "(missing)")))
    v[["logged_factor", "observed_raw_ratio", "yahoo_factor", "tier", "result", "result_note"]] = pd.DataFrame(res, index=v.index)
    v.to_csv(V, index=False)
    print(v.groupby(["category", "result"]).size().unstack(fill_value=0).to_string())
    print(v[v.result == "FAIL"][["symbol", "ex_date", "action_type", "expected_factor", "logged_factor", "observed_raw_ratio", "yahoo_factor", "tier", "result_note"]].to_string())
    print(v[v.category.isin(["same_year_split_and_bonus_different_dates", "relisted_or_suspended"])][["symbol", "ex_date", "action_type", "category", "tier", "result"]].to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())

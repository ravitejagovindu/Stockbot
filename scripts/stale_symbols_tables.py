"""Second step of the stale-symbol inventory (read-only): turns the CSV files written by scripts/stale_symbols_inventory.py into the directed feed_symbol pair table, the
lead classification, the Q4 counts under two definitions of "rename lead", and the gap distributions. Counts and lists only, no returns.

  py -3 scripts/stale_symbols_tables.py --dir docs/data_audit/stale_symbols
"""
import argparse
import ast
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stockbot.data.adjustments import action_factor  # noqa: E402

DB = "F:/Projects/Ravi/StockBot/finsight.db"
sys.path.insert(0, str(ROOT / "scripts"))
from stale_symbols_inventory import STORED_RUNS  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args(argv)
    d = ROOT / args.dir
    con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    cal = pd.Index(sorted(r[0] for r in con.execute("select distinct trade_date from market_data_lake")))
    pos = {x: i for i, x in enumerate(cal)}
    stale = pd.read_csv(d / "stale_symbols.csv").set_index("symbol")
    pairs = pd.read_csv(d / "rename_pairs_feed_symbol.csv")
    price = pd.read_csv(d / "rename_candidates_price.csv")
    gaps = pd.read_csv(d / "gaps_over_20_sessions.csv")
    ism = pd.read_csv(ROOT / "data/reference/isin_symbol_map.csv")
    ca = pd.read_sql("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator from corporate_actions_log where action_type in ('SPLIT','BONUS')", con)
    ca_by = {s: g for s, g in ca.groupby("symbol")}

    def bar_info(sym):
        r = con.execute("select min(trade_date), max(trade_date), count(*) from market_data_lake where symbol=?", (sym,)).fetchone()
        fc = con.execute("select close_raw from market_data_lake where symbol=? order by trade_date limit 1", (sym,)).fetchone()
        lc = con.execute("select close_raw from market_data_lake where symbol=? order by trade_date desc limit 1", (sym,)).fetchone()
        return {"first": r[0], "last": r[1], "bars": r[2], "first_close": fc[0] if fc else None, "last_close": lc[0] if lc else None}

    # ---- directed feed_symbol pairs (unordered pair; old = earlier last bar)
    rows = []
    seen = set()
    for r in pairs.itertuples():
        key = tuple(sorted((r.log_symbol, r.feed_symbol)))
        if key in seen:
            continue
        seen.add(key)
        sub = pairs[(pairs.log_symbol.isin(key)) & (pairs.feed_symbol.isin(key))]
        ia, ib = bar_info(key[0]), bar_info(key[1])
        (old, io), (new, inew) = sorted(((key[0], ia), (key[1], ib)), key=lambda t: (t[1]["last"], t[1]["first"]))
        between = pos[inew["first"]] - pos[io["last"]]
        f = 1.0
        if between > 0:
            for s in (old, new):
                if s in ca_by:
                    for x in ca_by[s].itertuples():
                        if io["last"] < x.ex_date <= inew["first"]:
                            try:
                                f *= action_factor({"action_type": x.action_type, "ratio_numerator": x.ratio_numerator, "ratio_denominator": x.ratio_denominator})
                            except Exception:
                                pass
        ratio_raw = inew["first_close"] / io["last_close"] if between > 0 else None
        ratio_adj = inew["first_close"] / (io["last_close"] * f) if between > 0 else None
        im_old, im_new = ism[ism.symbol == old], ism[ism.symbol == new]
        same_isin = bool(len(set(im_old["isin"]) & set(im_new["isin"])))
        rows.append({"old_symbol": old, "new_symbol": new, "old_first": io["first"], "old_last": io["last"], "new_first": inew["first"], "new_last": inew["last"],
                     "sessions_old_last_to_new_first": between, "old_is_stale": old in stale.index, "new_continues_after_old_last": inew["last"] > io["last"],
                     "old_last_close": io["last_close"], "new_first_close": inew["first_close"], "logged_split_bonus_factor": f, "ratio_raw": ratio_raw, "ratio_after_logged_action": ratio_adj,
                     "within_2pct": (abs(ratio_adj - 1) <= 0.02) if ratio_adj is not None else None, "feed_note_ex_dates": ";".join(sorted({str(v) for v in sub.ex_date})[:6]), "feed_note_types": ";".join(sorted({str(v) for v in sub.action_type})),
                     "note_example": sub.notes.iloc[0][:160], "same_isin_in_isin_symbol_map": same_isin, "old_boundary_in_map": ";".join(sorted({f"{a} / {b}" for a, b in zip(im_old.boundary_reason, im_old.boundary_to_next)})),
                     "old_ever_eligible": bool(stale.loc[old, "ever_eligible"]) if old in stale.index else None})
    dp = pd.DataFrame(rows).sort_values(["old_is_stale", "sessions_old_last_to_new_first"], ascending=[False, True])
    dp.to_csv(d / "rename_pairs_feed_symbol_directed.csv", index=False)
    sp = dp[dp.old_is_stale]
    strict_pairs = sp[(sp.sessions_old_last_to_new_first > 0) & (sp.sessions_old_last_to_new_first <= 5)]

    # ---- leads for the stale symbols
    w = price[price.within_2pct]
    price_old = set(w.old_symbol)
    note_old = set(sp.old_symbol)                                   # any timing; direction by dates
    note_any_member = set(pairs.log_symbol) | set(pairs.feed_symbol)
    note_member_stale = note_any_member & set(stale.index)
    note_and_price = set(strict_pairs.old_symbol) & price_old
    strict_old = (set(strict_pairs.old_symbol) | price_old)
    leads = {"price_rule_2pct_old_symbols": len(price_old), "feed_note_pair_old_symbol_any_timing": len(note_old), "feed_note_pair_old_symbol_first_bar_within_5_sessions": int(strict_pairs.old_symbol.nunique()),
             "feed_note_names_stale_symbol_as_either_member": len(note_member_stale), "both_price_rule_and_note_within_5": len(note_and_price),
             "price_rule_only": len(price_old - set(strict_pairs.old_symbol)), "union_price_or_note_within_5": len(strict_old)}
    wl = w.copy()
    wl["also_named_by_feed_note"] = wl.apply(lambda r: bool(((strict_pairs.old_symbol == r.old_symbol) & (strict_pairs.new_symbol == r.new_symbol)).any()), axis=1)
    wl.to_csv(d / "rename_candidates_price_within_2pct.csv", index=False)

    # ---- Q4 under two definitions
    def q4(no_lead: set) -> dict:
        nl = stale.loc[sorted(no_lead)]
        held = {}
        union = set()
        for label, p in STORED_RUNS.items():
            trades = json.loads((ROOT / p).read_text(encoding="utf-8"))
            syms = {t["symbol"] for t in trades if t["symbol"] in no_lead}
            union |= syms
            opened = sum(1 for t in trades if t["symbol"] in no_lead and t["exit_date"] > stale.loc[t["symbol"], "last_bar"])
            held[label] = {"symbols": len(syms), "trades": sum(1 for t in trades if t["symbol"] in no_lead), "trades_with_exit_after_the_last_bar": opened}
        return {"symbols": len(nl), "ever_eligible": int(nl.ever_eligible.sum()), "eligible_in_window_2016": int(nl.eligible_in_window_2016.sum()), "fund_etf": int(nl.is_fund_etf.sum()),
                "held_in_any_stored_run_distinct_symbols": len(union), "held_by_run": held}
    all_stale = set(stale.index)
    def_a = all_stale - (price_old | note_member_stale)              # any lead: price rule, or named by any feed_symbol note
    def_b = all_stale - strict_old                                   # strict lead: price rule, or note-named successor starting within 5 sessions
    isin_succ = {r.symbol: (str(r.boundary_to_next), str(r.boundary_reason)) for r in ism.itertuples() if r.symbol in all_stale and isinstance(r.boundary_to_next, str) and r.boundary_to_next.strip()}
    def_c = def_a - set(isin_succ)                                   # A, and no same-ISIN successor row in data/reference/isin_symbol_map.csv
    q = {"definition_A_any_lead": q4(def_a), "definition_B_strict_lead": q4(def_b), "definition_C_A_and_no_isin_map_successor": q4(def_c)}
    leads["stale_with_same_isin_successor_in_isin_symbol_map"] = len(isin_succ)
    leads["isin_map_successor_by_boundary_type"] = pd.Series([v[0] for v in isin_succ.values()]).value_counts().to_dict()
    pd.DataFrame([{"symbol": k, "boundary_to_next": v[0], "boundary_reason": v[1]} for k, v in sorted(isin_succ.items())]).to_csv(d / "stale_with_isin_map_successor.csv", index=False)

    # ---- gap distributions
    g = gaps.copy()
    g["len_bucket"] = pd.cut(g.missing_sessions, [20, 40, 60, 120, 250, 10000], labels=["21-40", "41-60", "61-120", "121-250", ">250"])
    g["ratio_bucket"] = pd.cut(g.ratio_after_over_before, [0, 0.5, 0.9, 1.1, 2.0, 1e9], labels=["<0.5", "0.5-0.9", "0.9-1.1", "1.1-2.0", ">2.0"])
    both = g[g.eligible_before_gap & g.eligible_after_gap]
    both.sort_values("missing_sessions", ascending=False).to_csv(d / "gaps_symbol_eligible_before_and_after.csv", index=False)
    gd = {"runs": int(len(g)), "symbols": int(g.symbol.nunique()), "by_length": g.len_bucket.value_counts().sort_index().to_dict(), "by_ratio": g.ratio_bucket.value_counts().sort_index().to_dict(),
          "eligible_before_and_after_runs": int(len(both)), "eligible_before_and_after_symbols": int(both.symbol.nunique()), "eligible_before_and_after_by_length": both.len_bucket.value_counts().sort_index().to_dict(),
          "eligible_before_and_after_by_ratio": both.ratio_bucket.value_counts().sort_index().to_dict(),
          "runs_starting_by_year": g.gap_start.str[:4].value_counts().sort_index().to_dict()}
    out = {"leads": leads, "q4": q, "gaps": gd, "directed_pairs": {"distinct_pairs": int(len(dp)), "old_symbol_stale": int(len(sp)), "old_stale_new_first_within_5_sessions": int(len(strict_pairs)),
                                                                  "old_stale_new_first_1_session": int((sp.sessions_old_last_to_new_first == 1).sum()), "old_stale_new_first_6_to_20": int(((sp.sessions_old_last_to_new_first > 5) & (sp.sessions_old_last_to_new_first <= 20)).sum()),
                                                                  "old_stale_new_first_over_20": int((sp.sessions_old_last_to_new_first > 20).sum()), "old_stale_overlapping_history": int((sp.sessions_old_last_to_new_first <= 0).sum()),
                                                                  "strict_pairs_within_2pct_after_logged_action": int(strict_pairs.within_2pct.sum()), "strict_pairs_same_isin_in_map": int(strict_pairs.same_isin_in_isin_symbol_map.sum())}}
    (d / "tables_summary.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""scripts/f2_load_plan.py — what would go into corporate_actions_log, and what the chosen tiers do to the price history.  Read-only.

1. Reconciliation: events (symbol, ex-date) vs parsed rows vs rows that survive the table's UNIQUE(symbol, ex_date, action_type),
   by tier and by stored type.
2. data/reference/unadjusted_events.csv: events NOT adjusted (unsupported price events, demergers, mergers, large rights, manual
   dispositions) on ADTV-eligible equity names -> input for the 'no entries for 252 sessions' rule.
3. Post-adjustment scan: >40% close-to-close moves on eligible names (price >= Rs5) in the lake, raw vs after back-adjusting with the
   STRONG / WEAK / WEAK_DIRECTIONAL events, and what remains.
Outputs: docs/data_audit/load_plan.md (+ csv files).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stockbot.data.ingestion.lake_symbols import lake_symbol        # noqa: E402  (moved to the package in Phase 8)

OUT = ROOT / "docs" / "data_audit"
PRICE_TIERS = ("STRONG", "WEAK", "WEAK_DIRECTIONAL")
THR, MIN_PX = 0.40, 5.0


def main() -> int:
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    ev = pd.read_csv(ROOT / "data/reference/corporate_actions_evidence.csv")
    el = pd.read_csv(OUT / "eligible_symbols.csv")
    funds = set(el[el["eligible"] & el["is_fund_or_etf"]]["symbol"])
    elig = set(el[el["eligible"]]["symbol"]) - funds
    imap = pd.read_sql_query("select isin, symbol, canonical_symbol, first_date, last_date from isin_symbol_map", con)
    isin_syms = imap.groupby("isin")["symbol"].apply(set).to_dict()
    ev["eligible"] = [bool(({r.symbol} | isin_syms.get(r.isin, set())) & elig) for r in ev.itertuples()]
    lines = ["# Load plan, unadjusted events and post-adjustment scan\n"]

    # ---- 1. reconciliation
    pm = ev[ev["action_type"].isin(["SPLIT", "BONUS"])]
    g = pm.groupby(["symbol", "ex_date"]).agg(tier=("tier", "first")).reset_index()
    t_ev = g.groupby("tier").size().rename("events")
    t_rows = pm.groupby(["tier", "action_type"]).size().unstack(fill_value=0)
    t = pd.concat([t_ev, t_rows], axis=1).fillna(0).astype(int)
    t["rows"] = t_rows.sum(axis=1)
    t.loc["TOTAL"] = t.sum()
    lines += ["## 1. Events vs rows (SPLIT/BONUS only)\n",
              "An event = one (symbol, ex-date); a same-day split+bonus is one event and two rows.\n", "```", t.to_string(), "```\n"]
    ev["stored_type"] = np.where(ev["tier"] == "UNSUPPORTED", "OTHER", ev["action_type"])
    parsed = ev.groupby("stored_type").size().rename("parsed_rows")
    uniq = ev.drop_duplicates(["symbol", "ex_date", "stored_type"]).groupby("stored_type").size().rename("after_UNIQUE")
    rec = pd.concat([parsed, uniq], axis=1)
    rec["collapsed"] = rec["parsed_rows"] - rec["after_UNIQUE"]
    rec.loc["TOTAL"] = rec.sum()
    lines += ["Rows by stored type, and what survives the table's UNIQUE(symbol, ex_date, action_type) with INSERT OR IGNORE "
              "(two OTHER rows on one date collapse into one):\n", "```", rec.to_string(), "```\n"]
    by_tier_type = ev[ev["tier"] != "NOT_PRICE_MOVING"].groupby(["tier", "stored_type"]).size().unstack(fill_value=0)
    lines += ["Price-moving feed rows by tier and stored type:\n", "```", by_tier_type.to_string(), "```\n"]

    # ---- 2. unadjusted events list (eligible equity names)
    ua = []
    for r in ev[ev["eligible"]].itertuples():
        nodata_out = isinstance(r.no_data_reason, str) and r.no_data_reason.startswith(("before", "after"))
        if r.action_type in ("SPLIT", "BONUS") and r.tier == "UNSUPPORTED" and not nodata_out:
            ua.append((r.symbol, r.isin, r.ex_date, "unsupported_" + r.action_type.lower(), f"factor {r.factor_logged:.4f}; {str(r.evidence)[:160]}"))
        elif r.action_type in ("DEMERGER", "MERGER"):
            ua.append((r.symbol, r.isin, r.ex_date, r.action_type.lower(), str(r.subject)[:120]))
        elif r.action_type == "RIGHTS" and r.den and r.num / r.den >= 0.2:
            ua.append((r.symbol, r.isin, r.ex_date, "large_rights", f"{r.num:g}:{r.den:g} {str(r.subject)[:100]}"))
    manual = OUT / "manual_move_dispositions.csv"
    if manual.exists():
        for r in pd.read_csv(manual).query("disposition == 'UNADJUSTED_EVENT'").itertuples():
            ua.append((r.symbol, None, r.date, "manual_unadjusted_event", r.evidence))
    uadf = (pd.DataFrame(ua, columns=["symbol", "isin", "date", "kind", "detail"])
            .drop_duplicates(["symbol", "date", "kind"]).sort_values(["symbol", "date"]))
    lsmap = {(r.symbol, r.ex_date): r.lake_symbol for r in ev.itertuples() if isinstance(r.lake_symbol, str)}
    uadf["lake_symbol"] = [lsmap.get((r.symbol, r.date)) or lake_symbol(imap, r.isin, r.symbol, r.date) for r in uadf.itertuples()]
    uadf.to_csv(ROOT / "data/reference/unadjusted_events.csv", index=False)
    lines += ["## 2. Unadjusted-event list (eligible equity names; `data/reference/unadjusted_events.csv`)\n", "```",
              uadf.groupby("kind").size().to_string(), "```\n"]

    # ---- 3. post-adjustment scan
    traded_in_map = set(imap["symbol"])
    lake_syms = set(imap[imap["symbol"].isin(elig)]["canonical_symbol"]) | {s for s in elig if s not in traded_in_map}
    adj: dict[str, list[tuple[str, float]]] = {}
    for (sym, ex), grp in pm[pm["tier"].isin(PRICE_TIERS)].groupby(["symbol", "ex_date"]):
        ls = grp["lake_symbol"].iloc[0] if isinstance(grp["lake_symbol"].iloc[0], str) else lake_symbol(imap, grp["isin"].iloc[0], sym, ex)
        adj.setdefault(ls, []).append((ex, float(grp["factor_logged"].iloc[0])))
    ua_dates = uadf.groupby("lake_symbol")["date"].apply(list).to_dict()
    raw_n = adj_n = created = fixed = 0
    resid = []
    syms = sorted(lake_syms)
    for i in range(0, len(syms), 150):
        chunk = syms[i:i + 150]
        q = ",".join("?" * len(chunk))
        d = pd.read_sql_query(f"select symbol, trade_date, close_raw from market_data_lake where symbol in ({q}) "
                              f"and trade_date between '2013-01-01' and '2026-09-30' order by symbol, trade_date", con, params=chunk)
        for s, h in d.groupby("symbol"):
            h = h.reset_index(drop=True)
            ret = h["close_raw"] / h["close_raw"].shift(1)
            ra = ret.copy()
            for ex, f in adj.get(s, []):
                idx = h.index[h["trade_date"] >= ex]
                if len(idx) and idx[0] > 0:
                    ra.iloc[idx[0]] = ra.iloc[idx[0]] / f
            ok_px = np.minimum(h["close_raw"], h["close_raw"].shift(1)) >= MIN_PX
            big_raw = ((ret - 1).abs() > THR) & ok_px
            big_adj = ((ra - 1).abs() > THR) & ok_px
            raw_n += int(big_raw.sum())
            adj_n += int(big_adj.sum())
            fixed += int((big_raw & ~big_adj).sum())
            created += int((~big_raw & big_adj).sum())
            for j in h.index[big_adj]:
                gap = (pd.Timestamp(h["trade_date"][j]) - pd.Timestamp(h["trade_date"][j - 1])).days
                near_ua = any(abs((pd.Timestamp(h["trade_date"][j]) - pd.Timestamp(x)).days) <= 30 for x in ua_dates.get(s, []))
                cat = "after_gap_in_EQ_series" if gap > 30 else ("near_unadjusted_event" if near_ua else "residual_no_explanation")
                resid.append((s, h["trade_date"][j], round(float(ra[j] - 1), 3), round(float(ret[j] - 1), 3), gap, cat, bool(big_raw[j])))
    rdf = pd.DataFrame(resid, columns=["symbol", "date", "adjusted_move", "raw_move", "gap_days", "category", "was_big_before_adjustment"])
    rdf.to_csv(OUT / "post_adjustment_large_moves.csv", index=False)
    lines += ["## 3. Post-adjustment scan (eligible equity names, price >= Rs5, |move| > 40%, lake 2013-01-01..2026-09-30)\n",
              f"Eligible names scanned: {len(syms)}. Events applied: {sum(len(v) for v in adj.values())} (tiers {', '.join(PRICE_TIERS)}), "
              "applied on the first session on/after the ex-date.\n",
              "```", f"large moves before adjustment : {raw_n}", f"large moves after adjustment  : {adj_n}",
              f"  removed by adjusting        : {fixed}", f"  created by adjusting        : {created}", "```\n",
              "Remaining moves by category:\n", "```", rdf.groupby("category").size().to_string(), "```\n"]
    (OUT / "load_plan.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

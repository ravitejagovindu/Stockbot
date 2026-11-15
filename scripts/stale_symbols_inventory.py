"""Inventory of symbols that stop having bars in the lake. READ-ONLY: no engine, no rule, no mapping is built; counts and lists only (no returns).

  py -3 scripts/stale_symbols_inventory.py --out-dir docs/data_audit/stale_symbols

Reads finsight.db through sqlite mode=ro&immutable=1 (market_data_lake, corporate_actions_log, isin_symbol_map), data/reference/fund_etf_symbols.csv, the shared config thresholds
(universe.min_adtv_cr, universe.min_listing_age_trading_days) and the stored trades.json of four stored runs. Writes CSV/JSON files into --out-dir.

Definitions (all stated again in Claude_Docs/STALE_SYMBOLS_INVENTORY.md):
  * calendar: every distinct trade_date in market_data_lake (3,416 dates; each has >= 1,142 symbols). "Sessions" are positions in this calendar.
  * last session: 2026-10-16. A symbol is STALE when more than 20 calendar sessions lie after its last bar.
  * ADTV: mean of raw close x raw volume over the last 20 bars (stockbot.data.adjustments.compute_adtv semantics), in crore (1e7).
  * eligible on a date = the shared eligibility rules (stockbot/universe/eligibility.py) evaluated on every bar date of the symbol: not in fund_etf_symbols.csv, listing age >= 252
    (F2 rule of AsOfView.symbol_info), 20-session ADTV > min_adtv_cr crore. ASM/GSM exclusion is NOT applied (no historical ASM/GSM data exists, KI-003).
"""
import argparse
import csv
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.adjustments import action_factor  # noqa: E402

DB = "F:/Projects/Ravi/StockBot/finsight.db"
LAST_SESSION = "2026-10-16"
STALE_MIN_SESSIONS = 20
INDEX_SERIES = ("NIFTY50_INDEX", "INDIA_VIX")
RENAME_WINDOW_SESSIONS = 5
RENAME_PRICE_TOL = 0.02
GAP_MIN = 20
CRORE = 1e7
STORED_RUNS = {
    "near_52w_high 4B": "docs/strategies/near_52w_high/results_4B/run/trades.json",
    "family_batch1 run1: pullback_uptrend": "docs/strategies/pullback_uptrend/results_run1/run/trades.json",
    "family_batch1 run1: short_term_reversal": "docs/strategies/short_term_reversal/results_run1/run/trades.json",
    "riskadj_momentum run1": "docs/strategies/riskadj_momentum/results_run1/run/trades.json",
}


def load_bars() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    df = pd.read_sql("select symbol, trade_date, close_raw, volume_raw from market_data_lake order by symbol, trade_date", con)
    ca = pd.read_sql("select symbol, ex_date, action_type, ratio_numerator, ratio_denominator, notes, source, evidence_tier from corporate_actions_log order by symbol, ex_date", con)
    ism = pd.read_sql("select isin, symbol, first_date, last_date, isin_class, canonical_symbol from isin_symbol_map", con)
    nifty_first = con.execute("select min(trade_date) from market_data_lake where symbol='NIFTY50_INDEX'").fetchone()[0]
    con.close()
    return df, ca, ism, nifty_first


def fund_symbols() -> set:
    with open(ROOT / "data/reference/fund_etf_symbols.csv", newline="", encoding="utf-8") as f:
        return {r["symbol"].strip().upper() for r in csv.DictReader(f) if r.get("symbol")}


def eligibility_frame(df: pd.DataFrame, cal: pd.Index, nifty_first: str, funds: set, min_adtv_cr: float, min_age: int) -> pd.DataFrame:
    df = df.copy()
    df["tv"] = df["close_raw"] * df["volume_raw"]
    g = df.groupby("symbol", sort=False)
    df["adtv20"] = g["tv"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["nbar"] = g.cumcount() + 1
    first = g["trade_date"].transform("first")
    cal_days = (pd.to_datetime(df["trade_date"]) - pd.to_datetime(first)).dt.days
    seasoned_from_start = first <= nifty_first
    age = np.where(seasoned_from_start, 252 + np.maximum(cal_days - 365, 0), np.where(cal_days >= 550, 252 + cal_days - 365, df["nbar"]))
    df["age"] = age
    df["is_fund"] = df["symbol"].str.upper().isin(funds)
    df["eligible"] = (~df["is_fund"]) & (df["age"] >= min_age) & (df["adtv20"] / CRORE > min_adtv_cr) & (~df["symbol"].isin(INDEX_SERIES))
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    out = ROOT / args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    cfg = load_shared_config().universe
    min_adtv, min_age = float(cfg.min_adtv_cr), int(cfg.min_listing_age_trading_days)
    df, ca, ism, nifty_first = load_bars()
    funds = fund_symbols()
    cal = pd.Index(sorted(df["trade_date"].unique()))
    pos = {d: i for i, d in enumerate(cal)}
    df["sidx"] = df["trade_date"].map(pos)
    last_idx = pos[LAST_SESSION]
    el = eligibility_frame(df, cal, nifty_first, funds, min_adtv, min_age)
    syms = el.groupby("symbol", sort=True)
    summ = syms.agg(first_bar=("trade_date", "min"), last_bar=("trade_date", "max"), bars=("trade_date", "size"), first_sidx=("sidx", "min"), last_sidx=("sidx", "max"))
    summ["sessions_after_last_bar"] = last_idx - summ["last_sidx"]
    lastrow = el.groupby("symbol", sort=True).tail(1).set_index("symbol")
    summ["last_close"] = lastrow["close_raw"]
    summ["adtv20_last_cr"] = lastrow["adtv20"] / CRORE
    summ["is_fund_etf"] = summ.index.str.upper().isin(funds)
    ever = el[el["eligible"]].groupby("symbol")
    summ["ever_eligible"] = summ.index.isin(ever.size().index)
    summ["eligible_sessions"] = ever.size().reindex(summ.index).fillna(0).astype(int)
    summ["first_eligible"] = ever["trade_date"].min().reindex(summ.index)
    summ["last_eligible"] = ever["trade_date"].max().reindex(summ.index)
    win = el[(el["eligible"]) & (el["trade_date"] >= "2016-01-01")].groupby("symbol")
    summ["eligible_in_window_2016"] = summ.index.isin(win.size().index)
    summ = summ[~summ.index.isin(INDEX_SERIES)]
    stale = summ[summ["sessions_after_last_bar"] > STALE_MIN_SESSIONS].copy()

    # ---- corporate actions within 30 calendar days of the last bar
    ca["ex"] = pd.to_datetime(ca["ex_date"])
    ca_by = {s: g for s, g in ca.groupby("symbol")}
    rows = []
    for sym, r in stale.iterrows():
        g = ca_by.get(sym)
        near = []
        if g is not None:
            lb = pd.Timestamp(r["last_bar"])
            for x in g.itertuples():
                if abs((x.ex - lb).days) <= 30:
                    near.append({"ex_date": x.ex_date, "action_type": x.action_type, "num": x.ratio_numerator, "den": x.ratio_denominator, "tier": x.evidence_tier, "notes": x.notes})
        rows.append(near)
    stale["ca_within_30d"] = rows
    stale["n_ca_within_30d"] = [len(x) for x in rows]
    stale["feed_symbol_in_notes"] = [sorted({m for n in x for m in re.findall(r"feed_symbol=([A-Za-z0-9&\-_.]+)", n["notes"] or "")}) for x in rows]

    # ---- Q2: rename candidates
    first_info = summ[["first_bar", "first_sidx", "last_bar", "last_sidx"]]
    first_close = el.groupby("symbol", sort=True).head(1).set_index("symbol")["close_raw"]
    cand_rows = []
    by_first = {}
    for s, r in summ.iterrows():
        by_first.setdefault(int(r["first_sidx"]), []).append(s)
    lake_syms = set(summ.index)
    for a, r in stale.iterrows():
        li = int(r["last_sidx"])
        for k in range(1, RENAME_WINDOW_SESSIONS + 1):
            for b in by_first.get(li + k, []):
                if b == a:
                    continue
                ev = [x for x in (ca_by.get(a, pd.DataFrame()).itertuples() if a in ca_by else []) if x.action_type in ("SPLIT", "BONUS") and pd.Timestamp(r["last_bar"]) < x.ex <= pd.Timestamp(summ.loc[b, "first_bar"])]
                ev += [x for x in (ca_by.get(b, pd.DataFrame()).itertuples() if b in ca_by else []) if x.action_type in ("SPLIT", "BONUS") and pd.Timestamp(r["last_bar"]) < x.ex <= pd.Timestamp(summ.loc[b, "first_bar"])]
                f = 1.0
                for x in ev:
                    try:
                        f *= action_factor({"action_type": x.action_type, "ratio_numerator": x.ratio_numerator, "ratio_denominator": x.ratio_denominator})
                    except Exception:
                        pass
                ratio_raw = float(first_close[b] / r["last_close"])
                ratio_adj = float(first_close[b] / (r["last_close"] * f))
                cand_rows.append({"old_symbol": a, "old_last_bar": r["last_bar"], "old_last_close": r["last_close"], "new_symbol": b, "new_first_bar": summ.loc[b, "first_bar"], "new_first_close": float(first_close[b]),
                                  "sessions_between": k, "logged_split_bonus_factor": f, "ratio_raw": ratio_raw, "ratio_after_logged_action": ratio_adj, "within_2pct": abs(ratio_adj - 1) <= RENAME_PRICE_TOL,
                                  "new_symbol_ever_eligible": bool(summ.loc[b, "ever_eligible"]), "old_symbol_ever_eligible": bool(r["ever_eligible"])})
    cands = pd.DataFrame(cand_rows)
    price_cands = cands[cands["within_2pct"]] if len(cands) else cands
    # feed_symbol pairs: any log row (any symbol) whose notes name another symbol; kept when the old or the named symbol is stale
    pair_rows = []
    for x in ca.itertuples():
        for m in re.findall(r"feed_symbol=([A-Za-z0-9&\-_.]+)", x.notes or ""):
            if m != x.symbol and (x.symbol in stale.index or m in stale.index):
                pair_rows.append({"log_symbol": x.symbol, "feed_symbol": m, "ex_date": x.ex_date, "action_type": x.action_type, "notes": x.notes,
                                  "log_symbol_in_lake": x.symbol in lake_syms, "feed_symbol_in_lake": m in lake_syms,
                                  "log_symbol_first_last": [summ.loc[x.symbol, "first_bar"], summ.loc[x.symbol, "last_bar"]] if x.symbol in lake_syms else None,
                                  "feed_symbol_first_last": [summ.loc[m, "first_bar"], summ.loc[m, "last_bar"]] if m in lake_syms else None})
    pairs = pd.DataFrame(pair_rows)
    all_feed = int(sum(1 for x in ca.itertuples() for m in re.findall(r"feed_symbol=([A-Za-z0-9&\-_.]+)", x.notes or "") if m != x.symbol))

    # ---- Q3: gaps
    gap_rows = []
    for s, g in el.groupby("symbol", sort=True):
        if s in INDEX_SERIES:
            continue
        si = g["sidx"].to_numpy()
        d = np.diff(si) - 1
        for j in np.nonzero(d > GAP_MIN)[0]:
            gap_rows.append({"symbol": s, "gap_start": cal[si[j] + 1], "gap_end": cal[si[j + 1] - 1], "missing_sessions": int(d[j]), "close_before": float(g["close_raw"].iloc[j]),
                             "first_close_after": float(g["close_raw"].iloc[j + 1]), "ratio_after_over_before": float(g["close_raw"].iloc[j + 1] / g["close_raw"].iloc[j]),
                             "is_fund_etf": s.upper() in funds, "ever_eligible": bool(summ.loc[s, "ever_eligible"]),
                             "eligible_before_gap": bool(g["eligible"].iloc[: j + 1].any()), "eligible_after_gap": bool(g["eligible"].iloc[j + 1:].any())})
    gaps = pd.DataFrame(gap_rows)

    # ---- Q4
    renamed = set(price_cands["old_symbol"]) if len(price_cands) else set()
    named = set(pairs["log_symbol"]) | set(pairs["feed_symbol"]) if len(pairs) else set()
    no_rename = stale[~stale.index.isin(renamed | (named & set(stale.index)))]
    held = {}
    for label, p in STORED_RUNS.items():
        trades = json.loads((ROOT / p).read_text(encoding="utf-8"))
        held[label] = {"trades": len(trades), "per_symbol": {}}
        for t in trades:
            if t["symbol"] in stale.index:
                lb = stale.loc[t["symbol"], "last_bar"]
                e = held[label]["per_symbol"].setdefault(t["symbol"], {"trades": 0, "open_after_last_bar": 0})
                e["trades"] += 1
                if t["exit_date"] > lb:
                    e["open_after_last_bar"] += 1
    q4 = {"terminal_symbols_total": int(len(stale)), "with_price_rename_candidate": int(stale.index.isin(renamed).sum()), "named_by_feed_symbol_note": int(stale.index.isin(named).sum()),
          "no_rename_candidate": int(len(no_rename)), "no_rename_ever_eligible": int(no_rename["ever_eligible"].sum()), "no_rename_eligible_in_window_2016": int(no_rename["eligible_in_window_2016"].sum()),
          "no_rename_fund_etf": int(no_rename["is_fund_etf"].sum())}
    held_summary = {}
    any_sets = {"all_terminal": set(stale.index), "no_rename": set(no_rename.index)}
    for tag, sset in any_sets.items():
        per = {}
        union = set()
        for label, v in held.items():
            syms_held = {s for s in v["per_symbol"] if s in sset}
            union |= syms_held
            per[label] = {"symbols_held": len(syms_held), "trades": int(sum(v["per_symbol"][s]["trades"] for s in syms_held)),
                          "trades_still_open_after_the_last_bar": int(sum(v["per_symbol"][s]["open_after_last_bar"] for s in syms_held)), "symbols": sorted(syms_held)}
        per["any_stored_run_distinct_symbols"] = len(union)
        per["any_stored_run_symbols"] = sorted(union)
        held_summary[tag] = per
    q4["held"] = held_summary

    # ---- outputs
    cols = ["first_bar", "last_bar", "bars", "sessions_after_last_bar", "last_close", "adtv20_last_cr", "is_fund_etf", "ever_eligible", "eligible_sessions", "first_eligible", "last_eligible", "eligible_in_window_2016", "n_ca_within_30d"]
    st = stale[cols].copy()
    st["ca_within_30d"] = [json.dumps(x, default=str) for x in stale["ca_within_30d"]]
    st["feed_symbol_in_notes"] = [";".join(x) for x in stale["feed_symbol_in_notes"]]
    st["in_isin_symbol_map"] = st.index.isin(set(ism["symbol"]))
    st.to_csv(out / "stale_symbols.csv")
    cands.to_csv(out / "rename_candidates_price.csv", index=False)
    pairs.to_csv(out / "rename_pairs_feed_symbol.csv", index=False)
    gaps.to_csv(out / "gaps_over_20_sessions.csv", index=False)
    isim = ism[ism["symbol"].isin(stale.index)]
    isim.to_csv(out / "stale_symbols_in_isin_symbol_map.csv", index=False)
    summary = {"lake": {"rows": int(len(df)), "symbols_excluding_index_series": int(len(summ)), "calendar_sessions": len(cal), "first_date": cal[0], "last_session": LAST_SESSION},
               "thresholds": {"min_adtv_cr": min_adtv, "min_listing_age_trading_days": min_age, "stale_min_sessions": STALE_MIN_SESSIONS},
               "stale": {"count": int(len(stale)), "ever_eligible": int(stale["ever_eligible"].sum()), "ever_eligible_in_window_2016": int(stale["eligible_in_window_2016"].sum()), "fund_etf": int(stale["is_fund_etf"].sum()),
                         "with_ca_row_within_30d": int((stale["n_ca_within_30d"] > 0).sum()), "with_feed_symbol_note_within_30d": int((stale["feed_symbol_in_notes"].map(len) > 0).sum()),
                         "last_bar_year_counts": stale["last_bar"].str[:4].value_counts().sort_index().to_dict()},
               "rename": {"price_candidates_all_rows": int(len(cands)), "price_candidates_within_2pct": int(len(price_cands)), "feed_symbol_pairs_involving_a_stale_symbol": int(len(pairs)), "feed_symbol_notes_total_in_log_with_other_symbol": all_feed},
               "gaps": {"runs": int(len(gaps)), "symbols": int(gaps["symbol"].nunique()) if len(gaps) else 0, "runs_ever_eligible_symbol": int(gaps["ever_eligible"].sum()) if len(gaps) else 0,
                        "runs_eligible_before_and_after": int((gaps["eligible_before_gap"] & gaps["eligible_after_gap"]).sum()) if len(gaps) else 0, "runs_fund_etf": int(gaps["is_fund_etf"].sum()) if len(gaps) else 0},
               "q4": q4, "stale_in_isin_symbol_map": int(stale.index.isin(set(ism["symbol"])).sum())}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""scripts/provenance/f2_eligibility_triage.py — F2 Step 5.  Read-only.

1. Eligible symbols = ADTV (SMA(raw close x raw volume, 20 sessions), same definition as stockbot.data.adjustments.compute_adtv)
   >= Rs25 crore on at least one session in the staged raw data.  (Market cap needs F2b and is NOT applied here.)
2. Automated triage of the large close-to-close moves (>40%) that have no logged corporate action within 3 days.
3. Counts of unsupported corporate-action events and placeholder listing dates on eligible symbols.
Outputs (docs/data_audit/): eligible_symbols.csv, large_moves_triage.csv, step5_summary.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "data_audit"
CRORE = 1e7
STD = [1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 2 / 3, 3 / 4, 4 / 5, 2 / 5, 1 / 20]


def eligible(con, gate_cr: float = 25.0, period: int = 20) -> pd.DataFrame:
    q = f"""select symbol, max(isin) isin, max(adtv) max_adtv, min(case when adtv >= {gate_cr * CRORE} then trade_date end) first_eligible,
                   max(case when adtv >= {gate_cr * CRORE} then trade_date end) last_eligible
            from (select symbol, isin, trade_date,
                         avg(close_raw * volume_raw) over (partition by symbol order by trade_date rows between {period - 1} preceding and current row) adtv,
                         count(*) over (partition by symbol order by trade_date rows between {period - 1} preceding and current row) n
                  from market_data_lake_staging) where n = {period} group by symbol"""
    df = pd.read_sql_query(q, con)
    df["max_adtv_cr"] = df.pop("max_adtv") / CRORE
    df["eligible"] = df.max_adtv_cr >= gate_cr
    df["is_fund_or_etf"] = df["isin"].fillna("").str.startswith("INF")     # mutual-fund / ETF ISINs start INF, companies INE
    return df


def triage(con, moves: pd.DataFrame, npx: dict, price_events: dict) -> pd.DataFrame:
    cat, note = [], []
    for r in moves.itertuples():
        s, d = r.symbol, r.trade_date
        hist = pd.read_sql_query("select trade_date, close_raw, volume_raw from market_data_lake_staging where symbol=? and trade_date between date(?, '-40 day') and date(?, '+6 day') order by trade_date",
                                 con, params=(s, d, d))
        i = hist.index[hist.trade_date == d]
        i = int(i[0]) if len(i) else None
        prevd = con.execute("select max(trade_date) from market_data_lake_staging where symbol=? and trade_date<?", (s, d)).fetchone()[0]
        gap = (pd.Timestamp(d) - pd.Timestamp(prevd)).days if prevd else 0
        near = [f"{t}:{x}" for x, t in npx.get(s, []) if abs((pd.Timestamp(d) - pd.Timestamp(x)).days) <= 30]
        lo_d = min(pd.Timestamp(prevd) if prevd else pd.Timestamp(d), pd.Timestamp(d) - pd.Timedelta(days=3))
        hit = [x for x in price_events.get(s, []) if lo_d <= pd.Timestamp(x) <= pd.Timestamp(d) + pd.Timedelta(days=3)]
        ratio = r.close_raw / r.pc
        vr = None
        if i and i >= 3:
            base = hist.volume_raw[max(0, i - 20):i].median()
            vr = hist.volume_raw[i] / base if base else None
        nxt = hist.close_raw[i + 1] if i is not None and i + 1 < len(hist) else None
        std = min(STD, key=lambda x: abs(np.log(ratio / x))) if ratio < 1 else min(STD, key=lambda x: abs(np.log(ratio * x)))
        mis = [x for x in price_events.get(s, []) if 3 < abs((pd.Timestamp(d) - pd.Timestamp(x)).days) <= 30]
        if hit:
            cat.append("explained_by_logged_split_bonus_under_another_symbol"); note.append("logged ex-date " + ",".join(hit))
        elif near:
            cat.append("near_demerger_merger_rights_or_other"); note.append(",".join(near))
        elif mis:
            cat.append("logged_split_bonus_on_a_different_date"); note.append("logged ex-date(s) " + ",".join(mis))
        elif gap > 30:
            cat.append("after_gap_in_EQ_series_or_suspension"); note.append(f"{gap} calendar days since the previous EQ-series row")
        elif nxt and abs(nxt / r.pc - 1) < 0.15:
            cat.append("one_day_spike_reverted"); note.append(f"next close {nxt:.2f} vs previous {r.pc:.2f}")
        elif (((ratio < 1 and abs(np.log(ratio / std)) < 0.06) or (ratio > 1 and abs(np.log(ratio * std)) < 0.06))
              and vr is not None and ((ratio < 1 and vr >= 0.6 / std) or (ratio > 1 and vr <= 1.5 * std))):
            cat.append("probable_unlogged_split_or_consolidation")
            note.append(f"ratio {ratio:.3f} ~ {std:.3f}; volume vs 20d median x{vr:.1f}")
        else:
            cat.append("large_move_no_pattern"); note.append(f"ratio {ratio:.3f}; volume x{vr:.1f}" if vr else f"ratio {ratio:.3f}")
    moves = moves.copy()
    moves["category"], moves["note"] = cat, note
    # relevance: did the stock pass the Rs25 crore gate in the 20 sessions before the move or in the 252 sessions after it?
    adtv_before, adtv_after = [], []
    for r in moves.itertuples():
        h = pd.read_sql_query("select trade_date, close_raw * volume_raw v from market_data_lake_staging where symbol=? and trade_date between date(?, '-60 day') and date(?, '+400 day') order by trade_date",
                              con, params=(r.symbol, r.trade_date, r.trade_date))
        h["adtv"] = h.v.rolling(20, min_periods=20).mean()
        i = int((h.trade_date < r.trade_date).sum())
        adtv_before.append(h.adtv.iloc[i - 1] / CRORE if i >= 1 and pd.notna(h.adtv.iloc[i - 1]) else np.nan)
        adtv_after.append(h.adtv.iloc[i:i + 252].max() / CRORE if len(h) > i else np.nan)
    moves["adtv_before_cr"], moves["max_adtv_next_252_cr"] = adtv_before, adtv_after
    moves["relevant"] = (moves.adtv_before_cr >= 25) | (moves.max_adtv_next_252_cr >= 25)
    return moves


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "finsight.db"))
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=120)
    el = eligible(con)
    el.to_csv(OUT / "eligible_symbols.csv", index=False)
    elig = set(el[el.eligible].symbol)
    funds = set(el[el.eligible & el.is_fund_or_etf].symbol)
    lines = ["# Step 5 summary\n",
             f"Traded symbols in staging with a full 20-session ADTV: {len(el)}; eligible (ADTV >= Rs25 crore on at least one session): **{len(elig)}**, "
             f"of which {len(funds)} have an INF ISIN (ETFs / funds, to be excluded from the equity universe).\n"]
    # map to ISINs / canonical names
    m = pd.read_sql_query("select isin, symbol, canonical_symbol, isin_class from isin_symbol_map", con)
    canon = m[m.symbol.isin(elig)]
    lines.append(f"Distinct ISINs among eligible symbols: {canon['isin'].nunique()}; canonical names: {canon.canonical_symbol.nunique()}; "
                 f"in classes demerger_merger: {canon[canon.isin_class == 'demerger_merger']['isin'].nunique()}, other: {canon[canon.isin_class == 'other']['isin'].nunique()}.\n")
    # large moves
    um = pd.read_csv(OUT / "unexplained_moves.csv")
    openm = um[(um.disposition == "OPEN") & (~um.penny_or_illiquid.astype(bool))].reset_index(drop=True)
    from scripts.provenance.f2_validate_staging import load_actions
    acts = load_actions(ROOT / "data/reference/nse_corporate_actions_raw.csv")
    evp = pd.read_csv(ROOT / "data/reference/corporate_actions_evidence.csv")
    evp = evp[evp.action_type.isin(["SPLIT", "BONUS"])]
    ism = m.groupby("isin")["symbol"].apply(set).to_dict()
    price_events: dict = {}
    for r in evp.itertuples():
        for sy in {r.symbol} | ism.get(r.isin, set()):
            price_events.setdefault(sy, []).append(r.ex_date)
    npx: dict = {}
    for r in pd.read_csv(ROOT / "data/reference/corporate_actions_evidence.csv").query("action_type in ['DEMERGER','MERGER','RIGHTS','OTHER']").itertuples():
        for sy in {r.symbol} | ism.get(r.isin, set()):
            npx.setdefault(sy, []).append((r.ex_date, r.action_type))
    tri = triage(con, openm, npx, price_events)
    tri["eligible_symbol"] = tri.symbol.isin(elig - funds)
    tri["is_fund_or_etf"] = tri.symbol.isin(funds)
    tri["relevant_equity"] = tri.relevant & ~tri.is_fund_or_etf

    def disposition(r):
        vol = None
        if isinstance(r.note, str) and "volume x" in r.note:
            vol = float(r.note.split("volume x")[1].split()[0])
        return {
            "explained_by_logged_split_bonus_under_another_symbol": "EXPLAINED: logged split/bonus (matched through the ISIN/rename history)",
            "near_demerger_merger_rights_or_other": "UNADJUSTED_EVENT: demerger/merger/rights near the move; goes on the no-entry-after-unadjusted-event list",
            "after_gap_in_EQ_series_or_suspension": "REAL_MOVE_ACROSS_GAP: stock was outside the EQ series (or suspended) for >30 days; the move accumulated over the gap, no adjustment",
            "logged_split_bonus_on_a_different_date": "MANUAL: logged ex-date differs from the observed price step; event tier is UNSUPPORTED until the date is overridden",
            "probable_unlogged_split_or_consolidation": "MANUAL: ratio and volume look like a split but the feed has no row",
        }.get(r.category, "REAL_MOVE: no corporate action in the feed, volume surge" if (vol and vol >= 3) else "MANUAL: no corporate action in the feed and no volume surge (or no volume history)")

    tri["disposition"] = [disposition(r) for r in tri.itertuples()]
    tri.to_csv(OUT / "large_moves_triage.csv", index=False)
    t = tri.groupby(["category", "relevant_equity"]).size().unstack(fill_value=0)
    dsp = tri[tri.relevant_equity].disposition.str.split(":").str[0].value_counts()
    lines += [f"\n## Large moves (>40%, no logged action within 3 days, price >= Rs5): {len(tri)}\n", "```", t.to_string(), "```\n",
              "Dispositions of the relevant equity moves (the stock passed the gate within 20 sessions before to 252 after):\n", "```", dsp.to_string(), "```\n"]
    # events
    ev = pd.read_csv(ROOT / "data/reference/corporate_actions_evidence.csv")
    pm = ev[ev.action_type.isin(["SPLIT", "BONUS"])].copy()
    isin_syms = m.groupby("isin")["symbol"].apply(set).to_dict()
    pm["eligible_symbol"] = [bool(({r.symbol} | isin_syms.get(r.isin, set())) & (elig - funds)) for r in pm.itertuples()]
    g = pm.groupby(["symbol", "ex_date"]).agg(tier=("tier", "first"), reason=("no_data_reason", "first"), elig=("eligible_symbol", "first")).reset_index()
    lines += ["\n## Split/bonus events (grouped by symbol and ex-date) by tier and eligibility\n", "```", g.groupby(["tier", "elig"]).size().unstack(fill_value=0).to_string(), "```\n",
              "No-price-data events on eligible symbols:\n", "```", g[g.reason.notna() & g.elig].groupby("reason").size().to_string(), "```\n"]
    # listing-date placeholders on eligible canonical names
    sm = pd.read_sql_query("select symbol, listing_date from securities_master", con)
    can = set(canon.canonical_symbol) | elig
    ph = sm[sm.symbol.isin(can) & (sm.listing_date >= "2026-04-01")]
    nom = len(can - set(sm.symbol))
    lines.append(f"\n## Listing-age input for eligible names\n\nEligible canonical/traded names: {len(can)}; placeholder `securities_master.listing_date` (>= 2026-04-01): {len(ph)}; no master row: {nom}.\n")
    (OUT / "step5_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

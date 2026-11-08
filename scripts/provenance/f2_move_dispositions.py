"""scripts/provenance/f2_move_dispositions.py — evidence and recorded disposition for the large moves that automation could not settle.

For every relevant equity move whose triage disposition starts with MANUAL it records: the previous session and whether it is a
special (weekend/holiday) session with a thin print, the move against the last REGULAR close, the Nifty return that day, the sector
peers' and the whole eligible universe's median return, and a disposition with its evidence.  Reviewer-decided cases are fixed in
REVIEWER_DECISIONS.  Read-only.  Output: docs/data_audit/manual_move_dispositions.csv
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "data_audit"
NAMED = [("PGIL", "2024-01-20"), ("JYOTISTRUC", "2024-01-20"), ("SCHNEIDER", "2024-05-18")]   # the reviewer's 2024-01-22 / 2024-05-20 moves, now under their true dates
REVIEWER_DECISIONS = {                       # (symbol, date): (disposition, reason)  — reviewer's instruction 2026-11-07
    ("MAJESCO", "2020-12-23"): ("UNADJUSTED_EVENT", "reviewer: looks like an unadjusted corporate event; added to the unadjusted-event list"),
    ("STAR", "2013-12-19"): ("UNADJUSTED_EVENT", "reviewer: looks like an unadjusted corporate event; added to the unadjusted-event list"),
}


def main() -> int:
    con = sqlite3.connect(f"file:{ROOT / 'finsight.db'}?mode=ro", uri=True, timeout=120)
    tri = pd.read_csv(OUT / "large_moves_triage.csv")
    um = pd.read_csv(OUT / "unexplained_moves.csv")                      # every >40% move, used for the cluster rule
    named = pd.DataFrame(NAMED, columns=["symbol", "trade_date"])          # reviewer-named moves are always recorded
    todo = pd.concat([tri[tri.relevant_equity & tri.disposition.str.startswith("MANUAL")][["symbol", "trade_date"]], named]).drop_duplicates()
    special = set(pd.read_csv(ROOT / "data/reference/special_sessions.csv", comment="#").query("kind == 'special_session'")["date"].astype(str))
    sect = pd.read_csv(ROOT / "data/reference/sector_map.csv").set_index("symbol")["sector"].to_dict()
    el = pd.read_csv(OUT / "eligible_symbols.csv")
    elig = set(el[el.eligible & ~el.is_fund_or_etf].symbol)
    rows = []
    for r in todo.itertuples():
        s, d = r.symbol, r.trade_date
        prev = con.execute("select trade_date, close_raw, volume_raw from market_data_lake_staging where symbol=? and trade_date<? order by trade_date desc limit 2", (s, d)).fetchall()
        med = con.execute("select avg(volume_raw) from (select volume_raw from market_data_lake_staging where symbol=? and trade_date<? order by trade_date desc limit 40 offset 2)", (s, prev[0][0])).fetchone()[0] if prev else None
        pd_, pc, pv = prev[0]
        prev_special = pd_ in special
        thin = bool(prev_special and med and pv < 0.5 * med)
        reg = None
        if prev_special:
            reg = con.execute("select trade_date, close_raw from market_data_lake_staging where symbol=? and trade_date<? and trade_date not in (%s) order by trade_date desc limit 1" % ",".join("?" * len(special)), (s, d, *sorted(special))).fetchone()
        close = con.execute("select close_raw from market_data_lake_staging where symbol=? and trade_date=?", (s, d)).fetchone()[0]
        nf = con.execute("select trade_date, close_raw from market_data_lake where symbol='NIFTY50_INDEX' and trade_date<=? order by trade_date desc limit 2", (d,)).fetchall()
        nifty = nf[0][1] / nf[1][1] - 1 if len(nf) == 2 and nf[0][0] == d else np.nan
        day = pd.read_sql_query("select a.symbol, a.close_raw / b.close_raw - 1 ret from market_data_lake_staging a join market_data_lake_staging b on b.symbol = a.symbol and b.trade_date = "
                                "(select max(trade_date) from market_data_lake_staging where trade_date < ?) where a.trade_date = ?", con, params=(d, d))
        day = day[day.symbol.isin(elig)]
        peers = day[day.symbol.isin([k for k, v in sect.items() if v == sect.get(s) and k != s])]
        mkt_med = float(day.ret.median()) if len(day) else np.nan
        mv = close / pc - 1
        key = (s, d)
        gap_days = (pd.Timestamp(d) - pd.Timestamp(pd_)).days
        nxt = [x[0] for x in con.execute("select close_raw from market_data_lake_staging where symbol=? and trade_date>? order by trade_date limit 3", (s, d))]
        persists = bool(nxt) and all(abs(x / close - 1) < 0.20 for x in nxt)
        cluster = um[(um.symbol == s) & ((pd.to_datetime(um.trade_date) - pd.Timestamp(d)).abs() <= pd.Timedelta(days=22)) & (um.trade_date != d)]
        same_sign = not np.isnan(nifty) and np.sign(nifty) == np.sign(mv)
        if key in REVIEWER_DECISIONS:
            disp, why = REVIEWER_DECISIONS[key]
        elif d in special and gap_days > 30:
            disp, why = "REAL_MOVE_ACROSS_GAP (artefact of re-entry on a special-session print)", (
                f"first EQ-series row after {gap_days} calendar days, and it is the special session {d} (volume {con.execute('select volume_raw from market_data_lake_staging where symbol=? and trade_date=?', (s, d)).fetchone()[0]:,} "
                f"vs {pv:,} on the last pre-gap row); the {mv:+.1%} is measured against the close of {pd_} and is not an overnight move")
        elif prev_special and reg and abs(close / reg[1] - 1) < 0.4:
            disp, why = "ARTEFACT_SPECIAL_SESSION_PRINT", f"previous session {pd_} is a special session; move vs last regular close {reg[0]} is only {close / reg[1] - 1:+.1%}"
        elif gap_days > 14:
            disp, why = "REAL_MOVE_ACROSS_GAP", f"previous EQ-series row is {gap_days} calendar days earlier ({pd_}); the move accumulated over the gap"
        elif len(cluster) >= 1:
            disp, why = "REAL_STOCK_SPECIFIC (volatility cluster)", (f"{len(cluster)} other >40% move(s) in the same stock within 22 days ({', '.join(cluster.trade_date.astype(str))}: "
                                                                 f"{', '.join(format(m, '+.0%') for m in cluster.move)}); Nifty {nifty:+.1%} that day, stock {mv:+.1%}; no corporate action in the feed")
        elif same_sign and not np.isnan(mkt_med) and abs(mkt_med) >= 0.04 and persists:
            disp, why = "REAL_MARKET_STRESS (provisional)", (f"same direction as the market: Nifty {nifty:+.1%}, eligible-universe median {mkt_med:+.1%}, sector peers median "
                                                          f"{peers.ret.median() if len(peers) else float('nan'):+.1%}; the new level persists (next 3 closes within 20%); no corporate action in the feed")
        else:
            disp, why = "OPEN_NEEDS_REVIEW", f"Nifty {nifty:+.1%}, eligible-universe median {mkt_med:+.1%}, {len(peers)} sector peers; level persists: {persists}"
        rows.append({"symbol": s, "date": d, "move": round(mv, 4), "prev_session": pd_, "prev_is_special": prev_special, "prev_print_thin": thin,
                     "last_regular_close_date": reg[0] if reg else None, "move_vs_regular_close": round(close / reg[1] - 1, 4) if reg else None,
                     "nifty_return": round(nifty, 4) if not np.isnan(nifty) else None, "universe_median_return": round(mkt_med, 4),
                     "sector": sect.get(s), "n_peers": len(peers), "peer_median_return": round(float(peers.ret.median()), 4) if len(peers) else None,
                     "disposition": disp, "evidence": why})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "manual_move_dispositions.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 110)
    print(df.drop(columns=["last_regular_close_date"]).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

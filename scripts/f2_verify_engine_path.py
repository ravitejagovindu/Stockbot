"""scripts/f2_verify_engine_path.py — run every row of data/reference/verified_corporate_actions.csv through the engine's real
adjustment code path (corporate_actions_log -> get_adjusted_series) on the real database.  Read-only.

A SPLIT/BONUS row PASSES when
  1. the log holds the event under the lake symbol (found through ``feed_symbol=<SYM>;`` in notes) with the expected factor (1%),
  2. the engine's factor on the last bar before the ex-date equals the expected product (1%),
  3. the adjusted close-to-close move across the ex-date is within +-25% (the raw move is shown for comparison).
A DEMERGER / RIGHTS row PASSES when the log holds it with that type and the engine's factor on the bar before the ex-date is 1.0.
The TATAMOTORS symbol_change row also needs both TATAMOTORS and TMPV to have lake rows and a DEMERGER row in the log.
Writes docs/data_audit/verification_engine_path.csv.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.db.models import CorporateActionsLog, MarketDataLake       # noqa: E402
from engine_core.adjustments import action_factor                    # noqa: E402
from scripts.f2_engine_scan import engine_frames, session_for        # noqa: E402

V = ROOT / "data/reference/verified_corporate_actions.csv"
OUT = ROOT / "docs" / "data_audit" / "verification_engine_path.csv"


def verify_row(session, r, expected_product: float) -> dict:
    ex = date.fromisoformat(r.ex_date)
    res = {"symbol": r.symbol, "ex_date": r.ex_date, "action_type": r.action_type, "category": r.category, "result": "FAIL", "note": ""}
    logs = session.execute(select(CorporateActionsLog).where(CorporateActionsLog.ex_date == ex)
                           .where(CorporateActionsLog.notes.like(f"%feed_symbol={r.symbol};%"))).scalars().all()
    mine = [c for c in logs if c.action_type == r.action_type]
    if not mine:
        res["note"] = "no log row of that type for this feed symbol and ex-date"
        return res
    lake_sym = mine[0].symbol
    res["lake_symbol"] = lake_sym
    raw, adj = engine_frames(session, lake_sym, as_of=ex, lo=ex - timedelta(days=60), hi=ex + timedelta(days=30))
    if raw is None:
        res["note"] = f"no lake rows for {lake_sym}"
        return res
    before = [d for d in raw.index if d < ex]
    after = [d for d in raw.index if d >= ex]
    if not before or not after:
        res["note"] = "no bars on both sides of the ex-date in the lake"
        return res
    p, o = before[-1], after[0]
    eng_factor = float(adj.loc[p, "close_adj"] / raw.loc[p, "close_raw"])
    raw_move = float(raw.loc[o, "close_raw"] / raw.loc[p, "close_raw"])
    adj_move = float(adj.loc[o, "close_adj"] / adj.loc[p, "close_adj"])
    res.update(engine_factor_prev_bar=round(eng_factor, 6), raw_move=round(raw_move, 4), adjusted_move=round(adj_move, 4),
               log_rows=",".join(f"{c.action_type}:{c.ratio_numerator}/{c.ratio_denominator}:{c.evidence_tier}" for c in logs))
    if r.action_type in ("SPLIT", "BONUS"):
        prod = float(np.prod([action_factor({"action_type": c.action_type, "ratio_numerator": c.ratio_numerator, "ratio_denominator": c.ratio_denominator})
                              for c in logs if c.action_type in ("SPLIT", "BONUS")]))
        ok1 = abs(prod / expected_product - 1) < 0.01
        ok2 = abs(eng_factor / expected_product - 1) < 0.01
        ok3 = abs(adj_move - 1) < 0.25
        res["note"] = f"log factor ok={ok1}; engine factor ok={ok2}; adjusted move within 25%={ok3}"
        res["result"] = "PASS" if (ok1 and ok2 and ok3) else "FAIL"
    else:
        ok = abs(eng_factor - 1.0) < 1e-9 and not any(c.action_type in ("SPLIT", "BONUS") for c in logs)
        res["note"] = f"engine factor on the bar before the ex-date = {eng_factor:.6f} (not price-moving)"
        if r.category == "symbol_change":
            n = {s: session.execute(select(func.count(MarketDataLake.id)).where(MarketDataLake.symbol == s)).scalar() for s in ("TATAMOTORS", "TMPV")}
            ok = ok and all(v > 0 for v in n.values())
            res["note"] += f"; lake rows {n}"
        res["result"] = "PASS" if ok else "FAIL"
    return res


def run(db: str) -> pd.DataFrame:
    s = session_for(db)
    v = pd.read_csv(V)
    out = []
    for r in v.itertuples():
        same = v[(v.symbol == r.symbol) & (v.ex_date == r.ex_date) & v.action_type.isin(["SPLIT", "BONUS"])]
        out.append(verify_row(s, r, float(np.prod(same["expected_factor"])) if r.action_type in ("SPLIT", "BONUS") else 1.0))
    return pd.DataFrame(out)


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "finsight.db")
    df = run(db)
    df.to_csv(OUT, index=False)
    print(df.groupby(["category", "result"]).size().unstack(fill_value=0).to_string())
    print(df[df.result != "PASS"][["symbol", "ex_date", "action_type", "note"]].to_string())
    return 0 if (df.result == "PASS").all() else 1


if __name__ == "__main__":
    sys.exit(main())

"""NOT USED (F2b closed 2026-11-08: failed its pre-registered spot-check bar; the table is not loaded and the screener does not read it). Kept for the record - see docs/data_audit/DATA_KNOWN_ISSUES.md KI-001.

F2b spot-check: derived shares vs shareholding filings for 20 fixed (symbol, date) pairs.  Pass bar fixed in advance (reviewer D3):
median |error| <= 5% and 90th percentile <= 15%.  Also reports whether the Rs5,000 cr market-cap gate decision would differ.  Read-only."""
import sqlite3, sys
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.f2b_build_pit_shares import build, lake_symbols
from data.ingestion.pit_shares import shares_on

BAR_MEDIAN, BAR_P90, GATE_CR = 5.0, 15.0, 5000.0

def main() -> int:
    con = sqlite3.connect(f"file:{ROOT/'finsight.db'}?mode=ro", uri=True, timeout=120)
    rows, segs, how = build(con, lake_symbols(con))
    f = pd.read_csv(ROOT / "data/reference/pit_shares_spotcheck_filings.csv")
    out = []
    for r in f.itertuples():
        x = shares_on(segs[r.symbol], date.fromisoformat(r.date)) if r.symbol in segs else None
        px = con.execute("select close_raw from market_data_lake where symbol=? and trade_date<=? order by trade_date desc limit 1", (r.symbol, r.date)).fetchone()
        model = x[0] if x else np.nan
        err = (model / r.actual_shares - 1) * 100
        mc_m, mc_a = (px[0] * model / 1e7 if px else np.nan), (px[0] * r.actual_shares / 1e7 if px else np.nan)
        out.append(dict(symbol=r.symbol, date=r.date, group=r.group, actual=r.actual_shares, model=model, error_pct=round(err, 2), abs_error_pct=round(abs(err), 2),
                        model_marked_reliable=x[1] if x else None, basis=r.basis, close_raw=px[0] if px else None,
                        mcap_cr_model=round(mc_m), mcap_cr_actual=round(mc_a), gate_flip=bool((mc_m > GATE_CR) != (mc_a > GATE_CR))))
    d = pd.DataFrame(out)
    d.to_csv(ROOT / "docs/data_audit/pit_spotcheck_results.csv", index=False)
    a = d["abs_error_pct"]
    med, p90 = float(a.median()), float(np.percentile(a, 90))
    ok = med <= BAR_MEDIAN and p90 <= BAR_P90
    pd.set_option("display.width", 250)
    print(d[["symbol", "date", "group", "actual", "model", "error_pct", "mcap_cr_actual", "mcap_cr_model", "gate_flip"]].to_string(index=False))
    print(f"\nmedian |error| = {med:.2f}% (bar <= {BAR_MEDIAN}%); p90 = {p90:.2f}% (bar <= {BAR_P90}%); within 5%: {(a<=5).sum()}/20; within 15%: {(a<=15).sum()}/20; gate flips: {int(d.gate_flip.sum())}/20")
    for g, s in d.groupby("group"):
        print(f"  {g}: n={len(s)} median={s.abs_error_pct.median():.1f}% max={s.abs_error_pct.max():.1f}%")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())

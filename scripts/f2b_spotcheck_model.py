"""Model values for the F2b spot-check: derived shares for fixed (symbol, date) pairs, built from the snapshot anchor exactly as the table will be."""
import sqlite3, sys
from datetime import date
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.f2b_build_pit_shares import build, lake_symbols
from data.ingestion.pit_shares import shares_on
PAIRS = [("BHARTIARTL","2018-12-31","large_rights"),("M&MFIN","2020-03-31","large_rights"),("IDEA","2020-03-31","large_rights"),("SUZLON","2022-03-31","large_rights"),
         ("YESBANK","2019-03-31","qip_pref"),("OLECTRA","2021-03-31","qip_pref"),("RPOWER","2019-03-31","qip_pref"),("SOUTHBANK","2020-03-31","qip_pref"),
         ("RBLBANK","2019-03-31","qip_pref"),("JPPOWER","2019-03-31","qip_pref"),("JINDALSTEL","2019-03-31","qip_pref"),
         ("RELIANCE","2019-03-31","plain"),("TCS","2018-03-31","plain"),("INFY","2018-03-31","plain"),("HDFCBANK","2019-03-31","plain"),("BAJFINANCE","2018-03-31","plain"),
         ("ASIANPAINT","2019-03-31","plain"),("WIPRO","2018-03-31","plain"),("TITAN","2019-03-31","plain"),("ESCORTS","2019-03-31","plain")]
if __name__ == "__main__":
    con = sqlite3.connect(f"file:{ROOT/'finsight.db'}?mode=ro", uri=True, timeout=120)
    rows, segs, how = build(con, lake_symbols(con))
    out = []
    for s, d, k in PAIRS:
        x = shares_on(segs[s], date.fromisoformat(d)) if s in segs else None
        out.append((s, d, k, x[0] if x else None, x[1] if x else None))
    df = pd.DataFrame(out, columns=["symbol","date","group","model_shares","model_reliable"])
    df.to_csv(ROOT/"docs/data_audit/pit_spotcheck_model.csv", index=False); print(df.to_string(index=False))

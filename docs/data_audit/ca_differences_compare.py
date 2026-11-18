"""Compare re-fetched NSE rows with corporate_actions_log using the daily job's own parse + split_new. Read-only (open_lake)."""
import json, sys, csv
from datetime import date
from pathlib import Path
from stockbot.data.lake import open_lake
from stockbot.data.guard.writers import split_new, sqlite_fetch
from stockbot.data.ingestion import nse_corporate_actions_history as H
raw = json.load(open(sys.argv[1], encoding="utf-8"))
names = ("symbol", "ex_date", "action_type", "ratio_numerator", "ratio_denominator", "notes", "source", "loaded_at")
recs, isin, unres = [], {}, 0
for r in raw:
    ex = H._parse_ex(r.get("exDate")); sym = str(r.get("symbol") or "").strip()
    if ex is None or not sym: unres += 1; continue
    for a in H.parse_subject(str(r.get("subject") or "")):
        rec = dict(zip(names, (sym, ex.isoformat(), a["action_type"], a["num"], a["den"], a["note"][:500], "x", "x")))
        rec["_raw"] = r; recs.append(rec)
con = open_lake()
new, same, diff = split_new(sqlite_fetch(con), "corporate_actions_log", recs, ("symbol", "ex_date", "action_type"), ("ratio_numerator", "ratio_denominator", "notes"))
print("raw", len(raw), "recs", len(recs), "unresolved", unres, "new", len(new), "same", same, "diff", len(diff))
out = []
for k, st, of in diff:
    rr = [x["_raw"] for x in recs if (x["symbol"], x["ex_date"], x["action_type"]) == k]
    out.append(dict(symbol=k[0], ex_date=k[1], action_type=k[2], st_num=st[0], st_den=st[1], st_notes=st[2], f_num=of[0], f_den=of[1], f_notes=of[2],
                    isin=";".join(sorted({x.get("isin") or "" for x in rr})), rec_date=";".join(sorted({x.get("recDate") or "" for x in rr})), series=";".join(sorted({x.get("series") or "" for x in rr})), nraw=len(rr)))
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)

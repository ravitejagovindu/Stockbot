"""Re-fetch NSE corporate actions with the daily job's own fetch (read-only w.r.t. the database) and save UNMODIFIED to raw_corporate_actions."""
import json, sys
from datetime import date, timedelta
from pathlib import Path
from stockbot.data.ingestion.daily_update import default_ca_fetch
today = date.today()
out = Path(r"F:\Projects\Ravi\StockBotData\raw_corporate_actions") / f"ca_{today.isoformat()}.json"
if out.exists():
    sys.exit(f"{out} exists: never overwrite")
raw = default_ca_fetch(date(2026, 10, 17), today + timedelta(days=45))
if raw is None:
    sys.exit("FETCH FAILED: default_ca_fetch returned None (4 attempts)")
out.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
print(out, len(raw))

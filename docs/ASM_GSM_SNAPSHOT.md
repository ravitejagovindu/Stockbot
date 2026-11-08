# Forward ASM/GSM daily snapshot (Step 12, KI-003)

`scripts/snapshot_asm_gsm.py` stores NSE's current ASM (long-term, short-term) and GSM lists into new tables in `finsight.db`
(`asm_gsm_daily_snapshot`, `asm_gsm_snapshot_raw`, `asm_gsm_snapshot_log`). It is point-in-time only from the day it starts and fills nothing in the past.
Run it once a day after the evening update (NSE refreshes the lists during the day; evening is safest). Same-day re-runs change nothing.

## Schedule on Windows (Task Scheduler, one command, run in a normal Command Prompt)
```
schtasks /Create /TN "StockBot ASM GSM snapshot" /SC DAILY /ST 19:00 /F /TR "cmd /c cd /d F:\Projects\Ravi\StockBot && py scripts\snapshot_asm_gsm.py >> logs\asm_gsm_snapshot.log 2>&1"
```
- Test it now: `schtasks /Run /TN "StockBot ASM GSM snapshot"`; check `logs\asm_gsm_snapshot.log`.
- Remove it: `schtasks /Delete /TN "StockBot ASM GSM snapshot" /F`.
- If the PC is off at 19:00 the day is missed (a missing date shows in `asm_gsm_snapshot_log`); in Task Scheduler > task > Settings tick "Run task as soon as possible after a scheduled start is missed".
- Do not run it while another process holds a long write lock on `finsight.db` (a 120 s lock timeout applies; a failure is logged and exits 1).

## Check
```
py -c "import sqlite3;c=sqlite3.connect('finsight.db');print(c.execute('select snapshot_date,framework,count(*) from asm_gsm_daily_snapshot group by 1,2 order by 1 desc limit 9').fetchall())"
```

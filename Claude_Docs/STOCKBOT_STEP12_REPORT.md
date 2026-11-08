# Step 12 report — KI-002/3/4, earnings collection, forward ASM/GSM snapshot

Date 2026-11-08. No config, gate or budget change. No strategy or universe design. Nothing wired into any backtest. AMD-002 and the six-config re-run not started. Stopped for review. Full suite: 329 passed, 63 env-gated skips, 0 failed.

## 1. Known issues recorded (687d81d)
KI-002 (test power ~+0.25 R floor at ~210 trades, size 0.0555-0.063 vs 0.05), KI-003 (no historical ASM/GSM), KI-004 (earnings; updated after collection with the limits below) in `docs/data_audit/DATA_KNOWN_ISSUES.md`.

## 2. Earnings collection (d2216ab, results commit after) — details in `docs/EARNINGS_COLLECTION.md`
- Backup first: `F:\Projects\Ravi\Backups\finsight_pre_step12_2026-11-08.db`, sha256 identical to the live file (ccb83061...), integrity_check ok.
- Only `api/corporates-financial-results` and `api/corporate-board-meetings`; 0.6 s delay; stop after 8 consecutive failures (never triggered). 3,238 query symbols (lake symbols + canonical rename targets from `isin_symbol_map`), 6,476 stored responses, all HTTP 200 (no 403/429); one network error, retried on re-run. Ran about 98 minutes.
- New tables only: `earnings_api_raw` (lossless compressed raw), `earnings_results_filing` 173,410 rows, `earnings_board_meeting` 164,819 rows (145,035 results meetings), `earnings_symbol_map`, `earnings_collect_log`. Intimation and broadcast timestamps kept.
- **Coverage:** a results row exists for 96-99% of symbol-years every year 2013-2026; 145 of 2,900 lake symbols (5.0%) have nothing from either API (list in `docs/data_audit/earnings_no_data_symbols.csv`; 72 of them active in 2026, including liquid names such as MCX, HEG, GUJGASLTD, ICICIPRULI; re-query returned 0 rows again; cause unknown). Renamed names missing from `isin_symbol_map` (TATAMOTORS) are not joined.
- **Three findings you must know before any use:**
  1. The results API has **no filings after January 2025** (2025-26 rests on board-meeting rows only).
  2. **`broadcast_ts` is not the announcement date**: it lags (INFY Q4 FY18: meeting 13-Apr-2018, timestamp 8-Jun-2018). Within 3 days of the meeting: 6-65% by year 2013-2019, 81% 2020, 94-97% 2021-2025. The results **board-meeting date** is the announcement date.
  3. Intimation lead before the meeting: median 9 days; >= 7 days in 84% overall but only 71% (2025) and 67% (2026), 78% (2020), 83% (2024). A strict "known 7 days ahead" rule drops a growing minority.
- **Validation (10 symbols):** 7 matched against outside sources found in this session (ETERNAL ex-ZOMATO, HDFCBANK, **HDFC Ltd delisted**, **MINDTREE merged**, BAJFINANCE, ITC, SUZLON), all exact; INFY, TCS, RELIANCE matched published dates from my memory, not re-fetched. Mostly large caps; no small-cap checked externally.

## 3. Forward ASM/GSM snapshot (57cd015) — `docs/ASM_GSM_SNAPSHOT.md`
`scripts/snapshot_asm_gsm.py`, standalone (no engine imports), new tables `asm_gsm_daily_snapshot` (date, framework ASM_LT/ASM_ST/GSM, symbol, isin, stage, surveillance code/description, NSE time field), `asm_gsm_snapshot_raw`, `asm_gsm_snapshot_log`. Idempotent per day; a failed or empty response writes nothing and exits 1; 403/429 stops. First snapshot stored today: 179 ASM rows (130 long-term + 49 short-term) and 76 GSM rows. No circular enumeration or reconstruction attempted. It fills nothing in the past.

**Schedule on Windows** (run once in Command Prompt):
```
schtasks /Create /TN "StockBot ASM GSM snapshot" /SC DAILY /ST 19:00 /F /TR "cmd /c cd /d F:\Projects\Ravi\StockBot && py scripts\snapshot_asm_gsm.py >> logs\asm_gsm_snapshot.log 2>&1"
```
Test: `schtasks /Run /TN "StockBot ASM GSM snapshot"`. Remove: `schtasks /Delete /TN "StockBot ASM GSM snapshot" /F`. If the PC is off at 19:00 that day is missed (visible in `asm_gsm_snapshot_log`); tick "run as soon as possible after a missed start" in the task's Settings. I did not create the scheduled task myself.

## Decisions for you
1. Earnings: accept the results board-meeting date as the announcement date, given the broadcast_ts lag? Accept 2025-26 resting on board meetings only? What to do about the 145 no-data names (a different symbol master, a user file, or exclude and report)?
2. Do you want the daily task created by me, or will you run the `schtasks` line?
3. KI-003 stays open: only a user-supplied history file closes it.

Working tree note: untracked scratch files remain (`data/f9/trade_library.npz`, `power_results_quick.json`, rehearsal CSVs); not committed.

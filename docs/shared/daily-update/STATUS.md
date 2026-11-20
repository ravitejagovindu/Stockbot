# daily-update: status

- BUILT and run: `scripts/daily_data_update.py` (logic in `stockbot/data/ingestion/daily_update.py`). Branch `daily-data-update`; the owner merges. Report: `Claude_Docs/DAILY_DATA_UPDATE_REPORT.md`. Task Scheduler commands: `SCHEDULER.md` (the task is NOT registered).
- Real `finsight.db`: caught up 2026-10-19 to 2026-11-18 (22 session days loaded and sealed; 11 calendar dates with no file). Every date up to 2026-10-16 is byte-identical (per-table proof in the report).
- What one day is: original bhavcopy saved unmodified under `F:\Projects\Ravi\StockBotData\raw_bhavcopy\YYYY\` (+ `MANIFEST.csv` row) -> EQ rows (`store_day`), BE/BZ/BL rows (`store_day_non_eq`), Nifty and VIX rows -> checks -> `market_data_lake` and `market_data_non_eq` sealed in ONE transaction. A failed day stays unsealed; the run stops at the first failed day.
- Calendar: weekdays and weekends are tried; no file = NO_FILE (journal `F:\Projects\Ravi\StockBotData\daily\calendar.csv`), re-checked on each of the next 3 days. Today's date before 23:45 IST is PENDING (exit 3).
- Locks: `F:\Projects\Ravi\StockBotData\locks\daily_update.lock` and `run_<pid>_<time>.lock`; stale = older than 12 h and no live process (reported, exit 5, never deleted).
- Exit codes: 0 done, 1 failed day, 3 today's file not published yet, 4 locked, 5 stale lock.
- Not done: no task registered, no paper trading, no backtest run, no strategy folder / pre-registration / ledger row / stored result touched.
- 2026-11-20 (branch paper-setup): the 85 known `corporate_actions_log` differences (stored notes carry the `feed_symbol=<SYM>; ` prefix) no longer count as differences (`split_known_prefix_differences`; ratios or other wording still do). Replacement task action `scripts/daily_job.py` (data step, then the momentum_calm paper step) documented in `SCHEDULER.md`; the task is NOT changed by the build.

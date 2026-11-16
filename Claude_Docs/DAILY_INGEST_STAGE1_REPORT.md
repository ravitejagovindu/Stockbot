# Daily data update, stage 1: inventory and design

Branch `daily-ingest` from master e2a6a82. Docs only: `docs/shared/daily-ingest/INVENTORY.md`, `DESIGN.md`, `PLAN.md`, `STATUS.md`. No code changed, nothing written to `finsight.db` or any lake table (opened read-only, immutable, for counts and one timed read), nothing downloaded. `finsight.db` sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after.

## Summary
- **Nothing in the running system writes to the lake.** The one tool that fetches Bhavcopy (`ingest_raw_bhavcopy_range.py`) writes only to staging; `BhavcopyIngestor` (the old daily writer, no caller since commit 337f71d) **deletes the whole day's rows before inserting and turns missing prices into 0.0**, so it must not be reused; the Kite and NSE ingestors have no callers; the one scheduler (APScheduler, 19:00) only calls `run_eod`.
- **Staging ends 2026-09-30, the lake ends 2026-10-16.** The 12 lake sessions 2026-10-01 to 2026-10-16 were written by the old pipeline: `source` is NULL, no staging rows, never compared with the raw Bhavcopy.
- **The session calendar is the NIFTY50_INDEX dates.** A day needs Bhavcopy EQ rows plus a Nifty and a VIX row (from the NSE index file `ind_close_all_DDMMYYYY.csv`, Yahoo as fallback) or `check_freshness` fails.
- **`py scripts/run_eod.py` processes nothing today**: the default book is empty (`runner.py:60`, `eod_cli.py:24`), riskadj_momentum's spec says `research` (PAPER mode skips it), and its exit policy is not in the library. A paper book needs `status=paper`, the strategy-owned policy passed as `extra_policies`, and a state file. First signal after the data is current: the first session of December 2026.
- **No ASM/GSM data can be obtained for 2026-10-17 to 2026-11-07** (and the sessions up to the day the daily snapshot starts): the endpoints return only today's list; the table holds one day, 2026-11-08.
- **Design (fixed direction kept):** snapshot 1 keeps `F:\Projects\Ravi\StockBot\finsight.db` (read-only attribute; an unset `STOCKBOT_DB` still means research); the working database is a byte copy at `F:\Projects\Ravi\StockBotData\working\finsight_working.db` found only through `STOCKBOT_DB` set by the 19:30 task; a role marker table (`ingest_meta`) makes backtests refuse the working file and the paper run refuse a snapshot; insert-only is enforced in code and by triggers, and a SHA-256 over all rows up to the previous last id is compared before and after every run (**23 s measured on the 5.63 million rows**, about 1 minute a run); one rolling verified backup (about 3.4 GB); corrections go through explicit commands that log before and after; one task, one chain (data, ASM/GSM snapshot, paper only if the data step succeeded), catch-up of missed days in order because the laptop's sleep state has no network, status file plus exit codes plus toast, no dashboard.
- **Paper spec hash:** `dataclasses.replace(SPEC, status="paper")` gives `78bfb856de37ff6a71f647e6114773d160d600ab481fe0a00e2e9846df8a8e02` (registered research hash `72dbec2c...` unchanged, params equal). Editing `paper_criteria` in `shared.yaml` (min_closed_trades 30, max_drawdown_pct 35.0) would change **every** run's `shared_config_hash` from `da459624...` to `73c8a04c...` and require updating one pinned test; the gates hash `e9b6407f...` and all spec hashes stay. `paper_criteria` has no consumer on the new state store anyway. Recommended: leave `shared.yaml` alone.
- **Plan:** ten small stages; the only shared files touched are `symbol_links.py` and `asof.py` (a path override that changes nothing when unset), `backtest/runner.py` (a refusal guard) and optionally `live/runner.py` (a `late` ticket marker). Each has a test that proves unchanged behaviour with the new variable unset or the guard not triggered.

## Facts worth knowing before deciding
- WAL: the database header says WAL; `-wal` is empty, `-shm` is touched by every read-only open (main file unchanged; its sha256 re-checked). Free disk 117 GB; three copies of 3.4 GB fit easily; growth about 1 to 2 MB a day (estimate).
- Window of missing sessions: 21 weekdays 2026-10-19 to 2026-11-16 plus 10 weekend dates to try for special sessions (Muhurat). NSE's holiday list is not in the repo and I did not look it up; the job decides by file existence, declared date and previous-close continuity.
- The machine is a laptop whose standby has no network: waking it at 19:30 would not help, so every start catches up from the last loaded session.
- `fund_etf_symbols.csv`, `symbol_links.csv` and `sector_map.csv` are read from the repo at run time and are not in the database: the working copies must be kept current or a new ETF or renamed stock is mishandled.
- A missed signal day produces a late ticket (entry assumed at a next open that has passed).

## Decisions needed (recommended default first)
1. **Production checkout:** a dedicated clean worktree pinned to a tag (not `F:\Projects\Ravi\StockBot`, which is on master `de36639`, behind origin).
2. **Locations:** snapshot 1 stays, read-only attribute; working file and paper state under a new `F:\Projects\Ravi\StockBotData\` outside git.
3. **2026-10-01 to 2026-10-16 rows (source NULL):** compare with the raw file during backfill, never change them.
4. **Weekend special sessions:** stop and confirm by hand.
5. **Late tickets after a missed day:** process, mark `late`, list in the status file.
6. **Price corrections after the fact:** flag and stop; `correct-prices` only by explicit command.
7. **Renames:** link automatically under the strict build rule, reported daily.
8. **Paper pass marks:** keep `shared.yaml` unchanged, evaluate the owner's marks (drawdown below 35%, at least 30 closed trades) from the state journal at the end of the paper phase.
9. **Retry schedule:** 19:30, every 20 minutes, give up at 23:30 (exit 3, not an error), tuned after one week of logs; three pending weekdays in a row becomes an error.
10. **Backups:** keep the single rolling pre-run copy (the owner's one-local-backup policy).
11. **Backfill go:** stage 9 downloads from NSE and needs a separate instruction.

## What ran and what did not
Ran: read-only inventory (counts, schema, one timed scan of the lake, `sha256sum`), computing the paper spec hash and the shared-config hash effect in memory. Did not run: any ingest, any download, any write, any test suite (docs-only task, no new code files).

# Golden-check baseline (Phase 0)

Taken 2026-11-08 on branch `restructure`, created from `master` at `41b22ce`; tag `pre-restructure` (annotated, pushed) points at the same commit. No code was changed to take these numbers.

| check | baseline |
|---|---|
| G1 unit suite (`py -m pytest tests -q`) | **329 passed, 63 skipped, 0 failed**, 4 warnings (42 s) |
| G2 env-gated suite (`STOCKBOT_DATA_TESTS=1 py -m pytest tests -q`) | **392 passed, 0 skipped, 0 failed** (21 min 44 s). Includes the 58 verification rows through the engine path (+ log-loaded test), the calendar integrity tests and both real-DB baseline tests. Log: `baseline/g2_env_gated_suite.log` |
| G2 engine scan (`py scripts/f2_engine_scan.py --tag restructure_baseline`) | names scanned 1,607; large moves before adjustment 764; **after adjustment 267; removed 499; created 2**; equivalence with `build_candidate_dicts` **120 samples, 0 mismatches**. Output: `baseline/engine_scan_restructure_baseline.{md,csv}` (identical numbers to `docs/data_audit/engine_scan_real_with_dolphin.md`) |
| G3 fixture-lake baseline (`tests/unit/test_baseline_reproducibility.py`) | 6 passed (hand-derived trade: fill 177.177, 553 shares, exit stop × 0.999) |
| G4 `finsight.db` | sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`; mtime `2026-11-08 12:38:02 +0530`; size 3,432,767,488 bytes. Re-checked after the G1, G2 and scan runs: unchanged. |
| Trial ledgers (for Phase 7) | `backtest/outputs/trial_ledger.csv` sha256 `bc6927bf4de1e14924d06d42cc19a4a4fa18a5721c61775e67545dfd685d25e6`, `verify_ledger` → chain OK (3 lines). `trial_ledger_exploratory.csv` sha256 `090c1c178bc434a1fa0778a97aa94b5f0abe320f03513090cab0891f8dbe2049`: **has no hash chain** (`verify_ledger` refuses it: "run select_candidate.py --register"); it was like this before the restructure, so "chain intact after the move" can only be checked for `trial_ledger.csv`; the exploratory file can be compared by sha256 only. |

Notes
- The collected-test count is 392 (329 + 63); G2 runs all 392.
- `finsight.db` includes the Step 12 tables (`earnings_*`, `asm_gsm_*`). If the daily ASM/GSM snapshot runs during the restructure it changes the file (see UNDECIDED.md, "Things I noticed" 1).
- Backups: the newest is `F:\Projects\Ravi\Backups\finsight_pre_step12_2026-11-08.db` (3,224,616,960 bytes, sha256 `ccb83061…0e210`, verified equal to the live file at the time and `integrity_check` = ok). **It predates the Step 12 tables** (the earnings collection took 98 minutes and is not in any backup). Earlier: `finsight_pre_F2_2026-11-06.db` (sha256 file present). Per your single-backup policy I did not make another copy; say if you want one.

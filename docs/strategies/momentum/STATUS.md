# Momentum strategy: STATUS

Documentation only: no code, no parameters used in a run, no results. A session picking this strategy up must read `BRIEF.md` (the task text, never edited) and this file first.

Last updated: 2026-11-09 (end of the pre-registration groundwork task). Branch `claude/momentum-prereg-groundwork-z93w6m`.

## Done (with commits)

* `b945756`: BRIEF.md saved verbatim; counts-only signal study `stockbot/data_checks/momentum_signal_count.py` with wrapper `scripts/signal_count_momentum.py`; fixture lake `tests/fixtures/momentum_lake.py` and 12 tests `tests/unit/test_momentum_signal_count.py` (no price after the as-of date is read; no return computed); two rows in `docs/guides/CODEBASE_GUIDE.md`.
* The next commit on the branch (head of the branch when you read this): `Claude_Docs/STOCKBOT_MOMENTUM_GROUNDWORK_REPORT.md` and this file.
* Part 2 engine design check answered from the code (report section 3). No engine, config, data, universe, risk, validation or ledger file changed. No strategy file exists. Nothing registered in any ledger.

## Open items

1. **Part 1 is not measured.** `finsight.db` was not available in the cloud session. Run `py scripts/signal_count_momentum.py --out-md ... --out-json ...` on the owner's machine (report section 2.5) and report the tables. Until then nobody knows whether the rule produces enough trades.
2. G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`) could not run for the same reason; the real-database tests and the `finsight.db` sha256 / mtime check (G4) are still to be done on the owner's machine.
3. Two G1 tests fail on a Linux checkout only because their recorded sha256 values are for CRLF files (`test_golden_files`, `test_ledger_yaml_hash::test_the_exploratory_ledger...`); they failed before this work. Not caused by it.
4. Decisions needed from the owner/reviewer before registration (report section 4): home of a production exit policy under the import rules; number of proposals per session (K); the interaction of a 3 x ATR stop and 1% risk with the shared sector and cash caps; the stop anchored on the signal close (the entry price is unknown at proposal); whether a gap/absence guard is wanted (PRE_LIVE_LIST item 11); the pre-registration vehicle and the success bar (PRE_LIVE_LIST items 2 and 3).

## Decisions by owner or reviewer

None recorded yet (as of 2026-11-09). Add each with its date.

## Next

1. Owner runs the study on the real lake; the figures go into a report for the reviewer.
2. Owner and reviewer decide the items in "Open items" 4 and set the success bar.
3. Only then: write the strategy, its exit policy and the pre-registration (a separate task). Do not start before that.

## Limitations found

* The draft rule is silent on: what "session" means when a name has gaps, how many names to propose each session, the entry anchor of the stop, gaps and re-entry after absences.
* The shared engine can express the rule's logic; it cannot place a concrete exit policy inside a strategy folder under the current import rules.
* Prices in the lake are adjusted for splits and bonuses only; demergers, mergers, rights and unsupported split-like events stay as price steps inside the windows.
* ASM/GSM history does not exist (KI-003) and the market-cap gate is parked (KI-001), so the shared universe is the same for any strategy as it was for the old one.

# low_volatility: status

Last updated: 2026-11-12 (stage 1 done; waiting for the owner's decisions below).

## Done
- Branch `low_volatility` from origin/master 055c703 (`family-prep` merged state), in its own worktree `F:\Projects\Ravi\StockBot_wt_lowvol` (see "Incident" below).
- Strategy `stockbot/strategies/low_volatility/` (`SPEC`, `LowVolatilityStrategy`, `register`), research status, not registered anywhere; `default_registry` stays empty.
- Tests `tests/unit/test_low_volatility_strategy.py` (23, fixture lakes only): spec numbers and hash, first-session-of-month signal, vol60 against an independent computation (with a split inside the window), 252 bars, tie order by ADTV then symbol, top-25 cut and ordinal rank, stop 0.90 x signal close in the as-of basis, no look-ahead, isolation, import boundary, and through the engine: `fixed_hold_21` exits at the open of session 22, the stop, the one-per-sector effect of the 15% cap at 10% sizing, and a month shorter than the hold leaving the slots full.
- Counts-only study `scripts/signal_count_low_volatility.py` (strategy-owned path, so no guide is edited): `Claude_Docs/LOW_VOLATILITY_SIGNAL_COUNTS.json`; report `Claude_Docs/LOW_VOLATILITY_STAGE1_REPORT.md`.
- Draft `PREREGISTRATION.md` (NOT registered), `power_calc.py` and `PREREGISTRATION_power_output.txt`.
- finsight.db: sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, size 3,432,767,488, mtime 2026-11-08 12:38:02.892612 +0530, identical before and after the study.
- Spec hash today (`expected_trade_rate`, `smallest_edge_of_interest`, `prereg_ref` unset): `399ac830d3335b992a400361c2464b4af9de966164dafcce366ae62be69e2c76`.
- Tests: G1 902 passed / 8 skipped / 1 failed; full folder with the real database 1,031 passed / 1 failed; G3 2 passed. The one failure is the stale `test_near_52w_high_strategy.py` assertion (open item 6), the same in both runs. finsight.db unchanged after.

## Result in one paragraph
The rule trades, but not as written on the label. At 1% risk and a 10% stop each position is 10% of equity, so the shared 15% sector cap allows one position per sector. The top 25 sit in a median of 9 distinct sectors (6 to 12), so a median of 16 of the 25 proposals are blocked by the cap and at most about 9 positions fit. Separately, `fixed_hold_21` exits at the open of session 22 while a calendar month has 17 to 23 sessions, so in 74% of months the previous cohort is still open at the next signal and that signal buys little or nothing. Modelled entries: 697 in 130 months, 5.4 a month (about 7 in a month that follows an exit, 0 to 2 in a month that does not), 7 signals with no entry at all. The counts do not make the rule impossible; they change what it is. Not changed, per the owner's instruction.

## Open items (owner decisions; nothing below was decided here)
1. **Sector cap effect** (limitation 1 of the pre-registration): accept "lowest-volatility name per sector within the top 25" as the strategy under test, or decide otherwise. Not worked around.
2. **Hold against month length:** accept that 74% of signals meet an open previous cohort, or decide otherwise. Not worked around.
3. `expected_trade_rate`: the counts say 5.4 per month (ignores stops, which add entries, and the gap-up and cash caps, which remove some). Not set in the spec.
4. `smallest_edge_of_interest`: for the owner to supply (not invented); see the power table.
5. Family membership (allow-list has five ids, `FAMILY.md` assumes four) and the window.
6. **Shared-file / other-branch issue (not edited):** `tests/unit/test_near_52w_high_strategy.py::test_the_strategy_package_imports_only_what_a_strategy_may_import` asserts that no folder other than `near_52w_high` exists under `stockbot/strategies/`. It fails as soon as any other approved strategy folder exists (it fails on this branch, and will on the other three and on master after merging). Suggested one-line fix by the owner: replace the final assertion with `unlisted_strategy_folders` / `APPROVED_STRATEGY_IDS`.
7. Stage 2 (not started): research wiring script, B1/B2 scripts for this id, registration commit.

## Incident (this session)
The main working tree `F:\Projects\Ravi\StockBot` is shared with another session. That session ran `git checkout short_term_reversal` from this branch while my first commit was the HEAD, so my first commit (7f9efb0) became an ancestor of its branch, and my second (72ab050) landed on `short_term_reversal` too. I created a separate worktree for `low_volatility` and cherry-picked both commits (now 00215ae and 0a55aed); this branch holds only low_volatility work. **I did not touch the `short_term_reversal` branch**: it still contains my two commits (7f9efb0 below its own 46a4f64, and 72ab050 on top). The clean fix, for the owner of that branch, is to rebuild it from origin/master and cherry-pick only 46a4f64 (low_volatility files must not travel with it). The study run itself was read-only and its results do not depend on the branch state (the strategy file it loaded was the committed one).

## Decisions made (dated)
- 2026-11-12: vol60 uses ddof = 1 (ranking-invariant); `min_bars` 252 read as 252 own adjusted bars plus a bar on the signal date; no gap guard on the 61-close window (counted instead); the study tool lives in `scripts/` under a strategy-owned name (the guides are not edited).
- 2026-11-12: window-gap diagnostic fixed (calendar shorter than 61 sessions in Jan and Feb 2016); the study was re-run in full after the fix so the committed JSON matches the committed code.

## Next step
None until the owner replies. Then: stage 2 (research script, baselines) only after the family registration is agreed.

## Limitations
See `PREREGISTRATION.md` section 11 (sector cap, hold against month length, no historical ASM/GSM, UNKNOWN sector, unadjusted corporate actions, EQ-only gaps, dividends not adjusted, counts model ignores stops/costs/gap-up/cash).

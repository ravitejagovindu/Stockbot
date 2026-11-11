# near_52w_high: status

Last updated: 2026-11-11 (STOP 4A done, waiting for the reviewer and the owner's approval of STOP 4B).

## Done
- Branch `near-52w-high` from origin/master 4bfc188 (the exit-policies merge).
- STOP 0: aebad25 brief; 689469b status and baseline.
- STOP 1 (accepted): f8c81c2 study tool, wrapper, fixture and tests; 8055906; 470217f guide entries; 7fccb69 counts, report, status.
- STOP 2 so far: 1b7df8b study tool re-done for the owner's tie-break (ADTV, then symbol) with cacheable candidate lists; 9f72dd7 tests first (failing at import) and the deliberate change to `test_no_strategy_in_the_tree.py` (exactly one strategy folder, one class); ef49cc8 strategy package, spec, registration function, research script, guides.

- STOP 2 (accepted 2026-11-11): 1b7df8b, 9f72dd7, ef49cc8, 656af0e, 402dc21.
- STOP 3: draft pre-registration `docs/strategies/near_52w_high/PREREGISTRATION.md` (NOT registered), `power_calc.py` and its output, report `Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP3_REPORT.md`. G1 819 passed / 8 skipped; G3 2 passed; full folder 948 passed; finsight.db unchanged.

- STOP 3 accepted with decisions D1 to D7 and the drawdown gate (2026-11-11).
- STOP 4A: **7b5b20b** shared gate change (`validation_gates.max_drawdown_pct` 15.0 to 20.0; paper stays 12.0), own commit; a9e9db7 tests first; **45db2e4da31de4ceee0a9b84195584dbe1225c84** finalisation commit (four scripts, `SPEC.prereg_ref`, final `PREREGISTRATION.md`, guides). Report: `Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP4A_REPORT.md`. Nothing registered, nothing run on real data.
- Final hashes: spec `359c8331091abf15f14cfaaf47f4fcf49f65835d876b6fb1ece56fa78287ab26` (with prereg_ref; was `e157b0bb...`), shared validation_gates `805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f` (was `d70800991ed5e6550fe8a89c050e6b3f989ac99f2a2d6cfaa133761771ab9e64`).
- Tests at 45db2e4: G1 856 passed / 8 skipped; G3 2 passed; full folder (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`) 985 passed; finsight.db unchanged.

## Owner decisions at the STOP 3 review (2026-11-11)
D1 prereg_ref set to the pre-registration path; D2 smallest edge stays 0.15 R with the plain-words power statement (central 61%, range 28% to 90%); D3 T1/T2/T3 as proposed with limits 0.075 and 0.025; D4 B1 and B2 as proposed, no full-engine replicates; D5 exploratory ledger untouched (section 12 is the record); D6 keep the TEST/TUNE note; D7 STOP 4B run approved, detached; a restart of the IDENTICAL registered run after a crash (same spec hash, shared-config hash, data snapshot, seeds, no results looked at) is not a new trial, any other rerun is; drawdown gate 20% in backtest (paper stays 12.0); decision rule as drafted.

## Owner decisions at the STOP 2 review (2026-11-11)
1. Registration stays explicit (`register(registry)`); `default_registry` stays empty until the strategy passes validation.
2. The ordinal rank is accepted.
3. The TEST/TUNE labels in shared.yaml do not apply (nothing tuned, one registered run). Pre-register the single run 2016-01-01 to 2026-10-16 plus two DESCRIPTIVE sub-period reports (2016-2019, 2020-2026) never used to select, change or stop anything.
4. smallest_edge_of_interest 0.15 R is confirmed only if the power numbers support it (STOP 3 finding: they do not robustly; central detectable edge about 0.18 R, power at 0.15 R about 61%).

## Owner decisions at the STOP 1 review (2026-11-10)
1. Tie-break: nearness, then higher 20-session raw ADTV (AsOfView), then symbol; explicit ordinal rank.
2. Window A: 2016-01-01 to 2026-10-16.
3. expected_trade_rate 6.2 per month (revisit if the tie-break rerun moves it by more than 5%).
4. Sector map: accept the UNKNOWN bucket as live behaves (limitation, below).
5. Unadjusted actions inside the window (demerger, merger, rights, OTHER): accept, no extra guard (limitation, below).
6. smallest_edge_of_interest 0.15 R per trade net of costs (to be confirmed at STOP 3 against the power numbers).
7. Full G2 at STOP 2: `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`, whole folder (643 passed was the last full run).

- 656af0e tie-break rerun (counts only, cached candidate lists in `Claude_Docs/near_high_tiebreak_parts/`): entries unchanged at 6.17 a month (0.0% move, so expected_trade_rate stays 6.2); A-names 36.9% to 9.0% of entries.
- Report: `Claude_Docs/STOCKBOT_NEAR_52W_HIGH_STOP2_REPORT.md`.

## Tests and database at STOP 2
- G1 819 passed / 8 skipped; G3 2 passed; full folder with `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`: 948 passed (1713 s). finsight.db sha256 and mtime unchanged.

## Open items
- The reviewer checks the final `PREREGISTRATION.md` against the owner's decisions; then the owner approves STOP 4B in writing.
- Open question: drawdown gate strict `<` (as in the archived plan) or `<=` (as drafted, implemented).

## Decisions made (dated)
- 2026-11-10: branch based on origin/master (local master was stale).
- 2026-11-10: gap guard = at least 250 of the last 252 calendar sessions.
- 2026-11-10: `version` is "1.0.0" (the spec schema requires MAJOR.MINOR.PATCH; "version 1").
- 2026-11-10: rank is an explicit ordinal (top_n for the first proposal, down to 1) because a float nearness cannot carry the ADTV and symbol tie-break; nearness and ADTV are in the proposal metadata. This replaces "rank = nearness" in the brief, per the owner's tie-break decision.
- 2026-11-10: registration is an explicit `register(registry)` call; the default registry stays empty so `test_the_default_registry_and_the_default_live_book_are_empty` and the live default book are unchanged. Nothing in the live package can see the strategy and `strategies_for_mode` never runs a research strategy.
- 2026-11-10: `tests/unit/test_no_strategy_in_the_tree.py` changed on purpose. It used to assert that no strategy exists; it now allows exactly the folder `stockbot/strategies/near_52w_high/` and exactly the class `NearHighStrategy` in `strategy.py`, and nothing else. Every other rule in the file is unchanged (top-level files of the strategies package, empty default registry and live book, exit policies only in their two homes, any other strategy or overlay forbidden everywhere). A second strategy must be added to that file on purpose.

## Next step
STOP 4B only after written approval: register with the finalisation commit SHA (`register_family`, then `verify_ledger` and `family_budget == 1`), run the backtest ONCE (detached), B1, T1/T2/T3, gates, report as measured.

## Limitations (carried into the pre-registration, section 11)
- Sector map: about a third of the selected symbols have no sector and share one UNKNOWN bucket, which the shared 15% cap holds to two positions at a time. Accepted; same as live.
- Corporate actions the engine does not adjust (demerger, merger, rights, OTHER) sit inside the 252-bar window for a median of about 13 valid names a session. No extra guard (owner decision); a price jump from such an action can create or hide a new high.
- The gap guard drops about 4% to 6% of eligible names in 2022 and 2024 to 2026 (EQ-only lake, PRE_LIVE_LIST item 11).
- The backtest supplies no ASM/GSM ranges for the historical window (snapshots exist only for recent dates), so that shared exclusion is not applied in the research run.
- `backtest.regimes` in shared.yaml labels 2015-2019 as an untouched TEST window and 2020-2026 as TUNE windows; this strategy is not tuned (fixed numbers, one run), but the owner should say at STOP 3 how that labelling applies to window A.
- The effective sample is smaller than the nominal 786 trades (overlapping 40-session holds); the power figures are assumption-based.
- No historical ASM/GSM exclusion (KI-003); the UNKNOWN sector bucket; unadjusted corporate actions inside the window; EQ-only lake gaps; cap-bound trade count; backtest drawdown gate 20% against paper 12%.
- Runtime: about 4.8 s per session for eligibility plus scoring; a 2016-2026 backtest is projected at 3.5 hours or more before the engine's own work.
- The occupancy and sector-cap numbers are a counts model: stops, risk cap, costs, gap-up cap, cash cap and fill blocks are ignored.

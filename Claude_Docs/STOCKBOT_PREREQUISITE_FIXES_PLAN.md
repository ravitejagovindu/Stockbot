# Plan: Prerequisite fixes F1, F2, F2b, F3, F4, F6, F9 (reviewer list `STOCKBOT_PREREQUISITE_FIXES.md`)

## Step 0 (this approval covers ONLY this): publish for review, then stop
Plan mode only lets me edit this plan file, so I could not write the reviewer copy directly. On approval I will:
1. Copy this plan, unchanged in content, to `F:\Projects\Ravi\Claude_Docs\STOCKBOT_PREREQUISITE_FIXES_PLAN.md` (open points O1–O7 are at the bottom).
2. **Make no other change** (no repo edits, no DB backup/ingest, no commits) and wait for the reviewer's feedback on the plan.
Implementation (everything below) starts only after the reviewer/owner responds.

## Context
The reviewer froze all strategy work until measurement/data defects are fixed. Owner scope for this round: **F1, F2, F2b, F3, F4, F6, F9**
(F5, F7, F8, F10 deferred). Owner decisions: work on `master`; use the real DB directly (with a backup); F2 = re-ingest true raw prices from NSE Bhavcopy.
Hard rules from the reviewer: no new strategy/configs, no TEST-window runs, no `strategy_config.yaml` tuning, one task per commit with the task ID, every fix has a test that fails first then passes (I report both runs), no Simulator run on the real DB before F4.

### Answers to the owner's questions
- **Why a DB copy?** Only because `Simulator.run` currently *writes* `regime_state` (reviewer rule 3). Data-loading tasks (F2/F2b) write to the real DB directly after a verified backup. After F4 the Simulator is write-free, so runs can use the real DB read-only; I will additionally open run-scripts with `PRAGMA query_only=ON`. Until F4 lands, any Simulator run uses a scratch copy.
- **Will I delete table data before re-ingesting?** No blanket delete. (1) Verified backup of `finsight.db` first (copy + size/hash + `PRAGMA integrity_check`). (2) Bhavcopy goes into a *staging* table, validated against the existing rows. (3) Only then one transaction: move the old Yahoo-sourced equity rows for 2020-01-01..2026-09-30 into archive table `market_data_lake_yahoo_archive` and insert the staged raw rows. Pre-2020 rows, 2026-10-01+ rows, and `NIFTY50_INDEX`/`INDIA_VIX` are not touched. Nothing is lost (archive + backup).

### New finding that reshapes F2 [RUN, read-only]
The 2020-01-01..2026-09-28 lake rows are the Yahoo CSVs (already split/bonus/dividend-adjusted): RELIANCE 2019-12-31 close 1514.05 → 2020-01-01 672.22 (a fake −55% step; HDFCBANK −53%, KOTAKBANK −80% at 2020-01-01), no bonus drop on 2024-10-28; only 2026-10-01+ (11 pipeline days) and ≤2019 are true raw. So the lake mixes three bases and loading corporate actions on top would double-adjust. It also means Step 3 results (2020+) ran on adjusted-with-dividends prices and with a basis break at the W1 start (affects 252-day lookbacks, ADTV, stops).

## Execution order (one commit per task, on master)
1. **F1** (small, first) → 2. **F4** (needed before any Simulator run) → 3. **F3** → 4. **F2** (start Bhavcopy download in background right after backup; longest) → 5. **F2b** → 6. **F6** → 7. **F9** (report + test; implementation of the chosen option waits for owner/reviewer decision).
Each commit ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Progress report per task goes in `F:\Projects\Ravi\Claude_Docs\STOCKBOT_PREREQUISITE_FIXES_REPORT.md` using the reviewer's 5-point format (what was wrong w/ file:line, commit ID, failing→passing run, decisions to review, extra findings).

## F1 — R metric
- `engine_core/trade_metrics.py`: new `compute_trade_r(entry, stop, shares_initial, pnl_gross, pnl_net, tax, risk_inr=None)` → `gross_r`, `net_r`, `net_r_after_tax`; R base = initial risk INR = `shares_initial × (entry − stop)` (recorded at entry as `risk_inr` so it survives splits, see F3); partial exits counted by summing all exits' P&L over the initial risk. `metrics_from_trades` uses it.
- `backtest/simulator.py`: trade rows write `risk_inr`, `gross_r`, `net_r`, `net_r_after_tax` (keep `realized_r` as a deprecated alias of `gross_r`, documented). Same for the end-of-window close path.
- `scripts/redesigned_random_baseline.py`: use `compute_trade_r` for actual and random trades.
- `scripts/select_candidate.py`, `engine_core/max_t_bootstrap.py`: explicit `r_col` parameter (default `net_r`), raise if column missing, raise if `net_r == gross_r` on rows with non-zero costs, and refuse legacy CSVs that only carry the orphan column.
- New `scripts/recompute_step3_net_r.py`: derives the three columns from the existing Step 3 trade CSVs (all inputs already present: `pnl_gross/costs/pnl_net/entry_price/stop/shares`) into `backtest/outputs_recomputed_net/` (copy equity curves; `select_candidate.py` gets `--outputs-dir` and `--no-ledger`); old outputs and `trial_ledger.csv` untouched. Writes a side-by-side old-vs-recomputed table (expectancy, PF, gate results, six configs) into the report.
- Tests (fail first): hand-computed fixture incl. a partial exit; select_candidate raises on missing column / `net_r==gross_r`; baseline vs simulator same R on same fixture.

## F4 — Backtest isolation
- `engine_core/regime_filter.py`: `RegimeFilter(config, session, persist=True, seed_state=None)`; with `persist=False` it keeps previous state in memory and never touches `regime_state`.
- `Simulator`: always `persist=False`; start state = deterministic replay of the regime from a warm-up of N sessions before the window (starting inactive), recorded in `SimResult.regime_seed` (value + derivation); optional explicit `regime_seed` argument.
- Guard: `Simulator` refuses a session whose bind URL resolves to the live DB path (`DATABASE_URL`/`finsight.db`) unless `allow_live_db=True` (CLI flag `--allow-live-db`); run scripts additionally set `PRAGMA query_only=ON`. (Open point O3 below.)
- `scripts/redesigned_random_baseline.py` switches to `persist=False` too.
- Tests: same window twice with different pre-existing `regime_state` rows → identical trades; `regime_state` row count + checksum unchanged after a run; guard raises on live path.

## F3 — Corporate action during an open position
- `engine_core/adjustments.py`: expose `action_factor(action)`; `engine_core/lifecycle_rules.py`: pure `rescale_for_action(pos, factor)` scaling entry, initial/live stop, target, highest_high, partial-limit state and shares (÷ factor; floor, fractional remainder as cash-in-lieu at ex-price — decision flagged O4), preserving `risk_inr` and P&L/R.
- Simulator step 2 and `PositionLifecycleManager.process_single` call one shared helper `apply_actions_for_bar(pos, actions, last_date, bar_date)`; live side records applied actions per position (migration adds `applied_corp_actions` text column to `active_positions`, updates `schema.sql` and ORM together).
- RIGHTS/MERGER/unparseable → position flagged `MANUAL_REVIEW_CA`, trade marked `excluded_ca=True` and excluded from statistics; count reported.
- Tests: split / bonus / no-event; pure split gives same R and exit date as the unsplit series; identical outcome through Simulator and PLM on one fixture; existing scratch repro becomes a committed regression.

## F2 — Raw prices + corporate actions
1. Backup + verification (see above). 2. `scripts/ingest_raw_bhavcopy_range.py`: date-range Bhavcopy download (reuse `BhavcopyIngestor` URL candidates/parsing, EQ series) into `market_data_lake_staging`; resumable, polite rate limit, 404 = holiday; background run. 3. Validate staging vs old rows (per-date symbol counts, volume agreement, symbols missing either side) and report; 4. atomic swap with archive table (above). 5. Corporate actions: add `source`, `loaded_at` columns (migration + ORM + schema.sql); extend/fix `CorporateActionsIngestor._fetch_from_nse` parsing (face-value split, bonus N:M) and add a range backfill over the whole symbol universe, 2010→present, documenting source, retrieval date, limits; log stays append-only (insert-or-ignore, no updates). 6. Independent verification: `data/reference/verified_corporate_actions.csv` (≥30 hand-picked splits/bonuses, different years/symbols, each with the known ratio) + integration test: adjusted close continuous across ex-date within tolerance, raw unchanged, ratio in log equals known ratio. 7. Data-quality scan (`data/quality_checker.py` extension): |day move| > 40% without a logged action → `docs/data_audit/unexplained_moves.csv` with disposition column. 8. Written confirmation + grep-test that ADTV/market cap use raw only.
- Not-in-lake caveat: lake starts ~2013 per symbol (Nifty 2015); "2010 to present" is limited by available prices.

## F2b — PIT shares outstanding
- Source of history is an open point (O1). Planned primary method: current NSE `issuedSize` + back-derivation through the corporate-action log (split/bonus factors), which captures structural changes but not issues/buybacks/ESOPs; store with `effective_date` per change and `source`. Coverage table by year (eligible symbols with valid PIT count, share of screened pool, share of traded value) → report. Symbols without usable history: rule proposed in writing, **owner approves before use** (O2). `UniverseScreener._get_latest_price_and_shares` stays fail-closed (no row ≤ eval_date → excluded, counted). Test: two share counts for one symbol across a date, correct one used on each side.

## F6 — Baseline integrity + pre-registration locks
- Extract `Simulator._bar` into a shared function (candidate_builder) so baseline and simulator use the identical adjusted per-day path and the F3 rescale helper; baseline forward path no longer reads raw prices.
- Remove hardcoded dates (take window start/end from config `backtest.regimes`/CLI).
- Pre-reg text vs code: dated, documented amendment appended to `pre_registered_configs.yaml` (`amendments:` list) describing the actual draw rule (`max(500, 5×n)`), rather than editing history; owner reviews (O5).
- Hash lock: new ledger columns `prev_hash,row_hash`; a registration row stores SHA of `pre_registered_configs.yaml` and of the gate-parameter block + budget (6); `select_candidate.py` refuses on YAML/gates hash mismatch, config-count ≠ budget, or broken chain; `--dry-run` writes to `trial_ledger_exploratory.csv` (counted). Existing single ledger row is kept and becomes the chain's first link.
- Tests: tamper YAML → refusal; delete/alter ledger row → detection; baseline R == simulator R on same fixture.

## F9 — Max-T revalidation
- `scripts/validate_max_t.py` (seeded, vectorised): size and power by ρ ∈ {0, 0.2, 0.4, 0.6}, K=6, W ∈ {100, 250}, block ∈ {2,4,8}, plus an overlapping-trades (long-hold) data-generating process; reports where control fails. Output `docs/MAXT_VALIDATION.md`.
- Replace the flaky `test_empirical_fwer_with_ar1_autocorrelation` with a deterministic seeded test whose bound matches the measured result and the documented nominal.
- Recommendation among {fix procedure, tighten thresholds, portfolio-level periodic returns} presented for owner/reviewer decision; I implement the chosen one only after decision.

## Verification
- Per task: write test → run (record failure) → implement → run (record pass); full pure suite `py -3 -m pytest tests -q` each time (tests that need the real DB are listed and tracked until F10).
- F1/F4/F3: in-memory SQLite fixtures only. F2/F2b: backup verified, staging validated before swap, post-swap checks (row counts per year vs archive, no change to pre-2020 / index / 2026-10-01+ rows, RELIANCE 2019-12-31→2020-01-01 continuity, verified-list test, unexplained-move report).
- No Simulator run on the real DB until F4 is committed; afterwards read-only with `PRAGMA query_only=ON` and checksum test.

## Open points to report to the owner/reviewer
- **O1** Source of historical shares outstanding (NSE shareholding filings vs derivation from current size + actions); needs your OK and NSE reachability/rate limits.
- **O2** Rule for symbols lacking PIT shares (exclude vs approximate) — owner approval needed.
- **O3** Guard semantics: Simulator refuses `finsight.db` unless `--allow-live-db`; confirm you want that friction since all data lives in that file.
- **O4** Fractional shares after bonus/odd splits: floor + cash-in-lieu proposed.
- **O5** Pre-reg amendment wording for the draw rule (text amended, code kept).
- **O6** Because the lake was Yahoo-adjusted, all earlier Step 3 numbers (not just net_r) are suspect; F8 re-baseline will move them. Dividends are not applied by design (gross returns); Yahoo included dividend adjustment, which the Bhavcopy re-ingest removes.
- **O7** Pre-2020 raw provenance/universe (survivorship) still unverified beyond spot checks.

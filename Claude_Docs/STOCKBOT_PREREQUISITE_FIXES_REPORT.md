# StockBot — Prerequisite fixes: progress report

Scope this round: **F1, F2, F2b, F3, F4, F6, F9** (F5, F7, F8, F10 deferred). Reviewer's 5-point format per task.
Safety tag: `pre-prereq-fixes` = `be4295a` (state before any change). Work is on `master`, one task per commit.
Pure test suite (everything except `tests/unit/test_baseline_reproducibility.py`, which needs the real DB): **236 passed** at commit `05f37ac`.

| Task | Status | Commit |
|---|---|---|
| F1 R metric | **done** | `a87e9a5` |
| F4 backtest isolation | **done** | `2678950` |
| F3 split/bonus during a hold | **done** | `ab1abca` |
| F6 baseline integrity + pre-reg lock | **done** (fixture fix `05f37ac`) | `9dee784` |
| F2 raw prices + corporate actions | **STOP-1 reached: staging + validation delivered; NO SWAP, awaiting reviewer** | `bdd8b99` (+ helper in `9dee784`) |
| F2b PIT shares | not started (after the swap and the corporate-action load) | — |
| F9 Max-T revalidation | **report + deterministic test done; decision needed** | `c8ff09b`, `ebef11d` |

---

## Commits (all pushed to `origin/master`; base `be4295a` = tag `pre-prereq-fixes`)

| # | Commit | Task | What it contains |
|---|---|---|---|
| 1 | `a87e9a5` | F1 | `engine_core/trade_metrics.py` (single R definition: `compute_trade_r`, `add_r_columns`); Simulator writes `risk_inr`, `gross_r`, `net_r`, `net_r_after_tax`; `select_candidate.py` and `max_t_bootstrap.py` refuse a missing or fake net column; `scripts/recompute_step3_net_r.py` and its output folder `backtest/outputs_recomputed_net/` (labelled as flawed-data results); `tests/unit/test_r_metric.py`. |
| 2 | `2678950` | F4 | `RegimeFilter(persist=False, seed_state=...)` (in-memory hysteresis); Simulator regime warm-up seed and the live-DB guard (`allow_live_db`, `PRAGMA query_only`); `--allow-live-db` on the run scripts; diagnostic scripts switched to `persist=False`; `tests/unit/test_backtest_isolation.py`; baseline-reproducibility test passes the override. |
| 3 | `ab1abca` | F3 | `engine_core/corporate_action_events.py` and `lifecycle_rules.rescale_for_action` (rebase of an open position across split/bonus; others flagged `MANUAL_REVIEW_CA` and excluded); used by Simulator and `PositionLifecycleManager`; schema + ORM + `data/db/migration_f3_corporate_actions.py` (**not applied to `finsight.db` yet**); `tests/unit/test_corporate_action_hold.py`. |
| 4 | `9dee784` | F6 (+ F2/F9 helpers) | `backtest/path_sim.py` and `candidate_builder.bar_context` (baseline walks adjusted paths with the real sizing); rewritten `scripts/redesigned_random_baseline.py`; `engine_core/prereg_lock.py` (YAML/gate hash lock, hash-chained ledger); `select_candidate.py --register`; amendment AMD-001 in `pre_registered_configs.yaml`; registered `trial_ledger.csv` and `trial_ledger_exploratory.csv`; `tests/unit/test_f6_baseline_and_locks.py`. **Also swept in** (should have been separate commits): `scripts/ingest_raw_bhavcopy_range.py` + `test_bhavcopy_range.py` (F2), `scripts/validate_max_t.py` (F9), 39 lines of parser tests. |
| 5 | `05f37ac` | F6 fix | The four ledger tests in commit 4 failed because they copied the live, just-registered ledger; they now use a synthetic legacy ledger. |
| 6 | `c8ff09b` | F9 | `docs/MAXT_VALIDATION.md` and `docs/maxt_validation.json` (size/power study); deterministic seeded FWER test and a reproducibility test in `tests/unit/test_max_t_bootstrap.py`. Procedure code unchanged. |
| 7 | `ebef11d` | F9 | One sentence in `docs/MAXT_VALIDATION.md` softened (autocorrelation claim that was not measured). |
| 8 | `4922a53` | F6 follow-up | `Simulator._bar` now calls the shared `candidate_builder.bar_context` (the refactor commit 4 depends on); refreshed `outputs_recomputed_net/selection_decision.json`. |
| 9 | `bdd8b99` | F2 (staging only, **no swap**) | `data/ingestion/nse_corporate_actions_history.py` (NSE feed fetch + subject parser, not yet loaded into `corporate_actions_log`); raw dump `data/reference/nse_corporate_actions_raw.csv` (33,773 rows) with its done/failed logs and `f2_symbols.txt` (3,945 symbols); `data/reference/verified_corporate_actions.csv` (50-row verification list); `scripts/f2_validate_staging.py` (read-only); `docs/data_audit/` (validation report + 5 CSVs); parser regression tests. |
| 10 | `5cb136a`, `486171b`, `3f347f5`, `dbbd761` | docs / evidence | Claude_Docs folder, pre-2020 lake-vs-staging comparison, clean-clone test log, Step 1 confirmations, backup decision. |
| 11 | `4ae7091` | F2 ingester | Bhavcopy file accepted only if its own date equals the requested date (holiday copies); `--all-days`, `--redo`; 3 tests (2 failed before). |
| 12 | `1fb7028` | F2 parser | NCRPS / preference-share bonus is NON_PRICE; "Split From x To Face Value y"; 5 tests failed before. |
| 13 | `459dd77`, `0603e09`, `be278ba` | F2 map + calendar | ISIN to canonical-symbol map (334 pure rename / 12 demerger-merger / 53 other), copy detector, special sessions list, permanent calendar data test, Step 1 results. |
| 14 | `0655254` | docs | Status and open points for the reviewer. |
| 15 | `2b03a6e` | F2 | Volume-unit continuity check across the Bhavcopy format change (pass). |
| 16 | `4f8f2a1` | F2 | Nifty/VIX gap fill into `index_gap_fill` (39 NSE index file rows, 12 Yahoo fallback rows). |
| 17 | `a0c6fc7`, `ef46661` | F2 swap | `scripts/f2_swap.py` (schema, swap, symbol mapping as three transactions), post-swap checks, rehearsal and **real run**; data tests fail loudly without a database. Report: `STOCKBOT_STEP3_SWAP_REPORT.md`. |
| 18 | `750015c` | F2 parser | Abbreviated subjects ("Fv Splt Frm", "Bon x:y", "Spl Rs.5tors.2", "Right Issue") were dropped silently; 11 tests failed before. |
| 19 | `a050132` | F2 Step 4 | Evidence tiers for split/bonus events; 6 tests failed before. |
| 20 | `63c2882` | F2 Step 5 | ADTV-eligible symbols, triage and dispositions of the large moves. |
| 21 | `bebd08f` | F2 Step 6 | Verification list result columns (58/58 PASS). |
| 22 | `4692d7b` | docs | Steps 4-6 report (`STOCKBOT_STEP4_6_REPORT.md`). |

Not in git: `finsight.db` (ignored) including the new `market_data_lake_staging` and `bhavcopy_fetch_log` tables, and the backup `F:\Projects\Ravi\Backups\finsight_pre_F2_2026-11-06.db`. Working tree clean after commit 9. Pure suite at commit 9: **235 passed** (the 236 quoted above was counted before the last edits; not reconciled).

---

## F1 — R metric (done)
1. **What was wrong.** `net_r` in `trades_candidate_CFG-0x.csv` was written by no checked-in code and equals `realized_r` (gross of fees). `select_candidate.py` (`_compute_trade_stats`) and `max_t_bootstrap.build_weekly_*_series` consumed it; the baseline (`redesigned_random_baseline.py:89,393`) computed true net R. Measured on CFG-01 (508 trades): stored +0.0519 vs true net +0.0293.
2. **What changed (`a87e9a5`).** `engine_core/trade_metrics.compute_trade_r / add_r_columns` is the single definition: R base = initial risk in INR (`risk_inr = shares × (entry − stop)`, recorded at entry so it survives splits); partial exits are not measured against remaining risk — all exits' P&L of the position are summed over the one initial risk. `gross_r = pnl_gross/risk`, `net_r = pnl_net/risk`, `net_r_after_tax = (pnl_net − tax)/risk`. The Simulator writes `risk_inr, gross_r, net_r, net_r_after_tax` (`realized_r` kept as a documented alias of `gross_r`). `select_candidate.require_r_columns` and `max_t_bootstrap._require_col` raise if the explicit column is missing, if a legacy file lacks `gross_r`, or if `net_r == gross_r` on rows with non-zero costs. The baseline uses the same function. `select_candidate` gained `--outputs-dir` / `--no-ledger`.
3. **Tests.** `tests/unit/test_r_metric.py`. Before: collection error (`cannot import name 'add_r_columns'`) → all fail. After: 9 passed. Includes the hand-computed partial-exit fixture (gross 0.56 / net 0.51 / after-tax 0.408), `risk_inr` override after rebasing, Simulator columns, refusal tests.
4. **Recomputed Step 3 outputs** → `backtest/outputs_recomputed_net/` (old outputs and ledger untouched; produced by `scripts/recompute_step3_net_r.py`).

   **COMPUTED ON FLAWED YAHOO-ADJUSTED DATA — shows the gross-versus-net effect only; not valid strategy results.**

   | config | trades | legacy "net_r" mean (= gross) | true net R mean | legacy PF | net PF |
   |---|---|---|---|---|---|
   | CFG-01 | 508 | +0.0519 | +0.0293 | 1.154 | 1.084 |
   | CFG-02 | 473 | +0.0426 | +0.0199 | 1.118 | 1.054 |
   | CFG-03 | 408 | +0.0639 | +0.0425 | 1.189 | 1.122 |
   | CFG-04 | 395 | +0.0422 | +0.0127 | 1.110 | 1.031 |
   | CFG-05 | 342 | −0.0173 | −0.0428 | 0.959 | 0.902 |
   | CFG-06 | 264 | −0.0132 | −0.0394 | 0.967 | 0.906 |

   Gate result with the explicit net column: all six still fail Gate 2 (99% block-bootstrap CI lower bound: −0.21 … −0.15 R) → `NO CANDIDATE SELECTED` (written to `outputs_recomputed_net/selection_decision.json`; not appended to the ledger; recorded in `trial_ledger_exploratory.csv`).
5. **For owner review / found outside the document.** (a) `realized_r` still exists as an alias — remove once old scripts are gone. (b) The random-baseline files used by this recompute are the old ones (generated with true net R but the pre-F6 procedure).

## F4 — Backtest isolation (done)
1. **What was wrong.** `Simulator.run` → `RegimeFilter.evaluate` upserted `regime_state` in the shared DB and read the previous state from it (`regime_filter._load_previous_state/_persist`); the diagnostic scripts did the same.
2. **What changed (`2678950`).** `RegimeFilter(persist=False, seed_state=…)` keeps hysteresis in memory. The Simulator always uses it; the starting state is a deterministic in-memory warm-up replay over up to 250 sessions before the window (or an explicit `regime_seed`), recorded in `SimResult.regime_seed` (value + derivation text). `Simulator.__init__` refuses a session bound to the live DB file (`data.db.connection.DATABASE_URL`) unless `allow_live_db=True` (`--allow-live-db` on `run_backtest.py` / `run_candidate_simulations.py`); with the override it runs under `PRAGMA query_only=ON` (restored afterwards), so nothing can be written. All diagnostic scripts now use `persist=False`.
3. **Tests.** `tests/unit/test_backtest_isolation.py`: 5 failed before, 5 pass after (stale "kill-switch active" row before the window changes nothing; `regime_state` rows and content unchanged after a run; seed recorded; guard raises without the override).
4. **Decision to review.** Warm-up length 250 sessions (code constant `REGIME_WARMUP_SESSIONS`, not a config value). Reading the live DB read-only needs `--allow-live-db` (O3: friction kept as you asked; the stricter "open the file with `mode=ro`" variant is not implemented yet — `query_only=ON` gives the same guarantee for the session).
5. **Found outside the document.** `UniverseScreener._get_listing_age` can write `securities_master` via an on-demand NSE fetch (`fetch_and_save_symbol_listing_date`) during a backtest. Under `query_only` this now fails safely (warning), but it is a hidden network call inside a simulation; it should be removed in F10.

## F3 — Corporate action during an open position (done)
1. **What was wrong.** A held position + 1:2 split gave `STOP_HIT, GAP_THROUGH_STOP` on the ex-date (reproduced earlier): history is re-adjusted as of today while entry, stops, target and highest-high stay in the old basis; the Simulator computed `has_ca` and ignored it for open positions.
2. **What changed (`ab1abca`).** Approach (preferred option): on an ex-date inside a holding period every price-denominated state field × factor, shares ÷ factor (floor; the fractional remainder is cash-in-lieu at the ex-date open — O4 approved). One shared implementation: `lifecycle_rules.rescale_for_action` + `engine_core/corporate_action_events.py` (`due_actions`, `apply_actions_to_position`), used by `Simulator` and `PositionLifecycleManager`. SPLIT/BONUS are rebased; DIVIDEND ignored; RIGHTS/MERGER/DEMERGER/other or unparseable ratios flag `MANUAL_REVIEW_CA` and the trade is marked `excluded_ca` and excluded from `metrics_from_trades` and `select_candidate` statistics (count printed). `risk_inr` keeps R invariant; the live side persists `applied_corp_actions` per position. Schema: ORM + `schema.sql` + `data/db/migration_f3_corporate_actions.py` (adds `risk_inr`, `applied_corp_actions`, `manual_review_ca` to `active_positions`; `risk_inr`, `excluded_ca` to `trade_analytics_log`). **The migration has not been applied to `finsight.db` yet** (those tables are empty); it will be applied together with the F2 changes.
3. **Tests.** `tests/unit/test_corporate_action_hold.py`: 7 failed before; after: split and bonus during a hold give the same exit date, P&L, `gross_r`, `net_r`, `risk_inr` as the unsplit control through the Simulator; the PLM (PAPER) gives the same exit date and P&L as the Simulator and the control; fractional-share maths; RIGHTS flagged and excluded; migration idempotent; the earlier scratch repro is a committed regression test.
4. **Decisions to review.** Fractional shares are credited at the ex-date open without transaction costs. Aggregation of partial-exit log rows across a split in `trades_from_log` now uses `MAX(risk_inr)`.
5. **Found outside the document.** (a) `PositionLifecycleManager` swallowed per-position exceptions (`process_all`) — F5. (b) `position_lifecycle.process_single` fetches only 220 bars; fine for ATR but short for 252-day features if ever reused.

## F6 — Baseline integrity and pre-registration locks (done)
1. **What was wrong.** The baseline walked **raw** prices (wrong across splits), hard-coded dates (`2019-10-01`, `2026-10-16`, window ends), re-implemented sizing/target without the "price discovery" ATR-projected target (so it could never draw a stock at a new high, which is exactly what breakout trades are), ran the regime with persistence, and nothing protected `pre_registered_configs.yaml` or the ledger.
2. **What changed (`9dee784`, `05f37ac`).** `backtest/path_sim.simulate_position_path` + `candidate_builder.bar_context` (shared with `Simulator._bar`): identical adjusted per-session path, real `RiskAndSizingEngine.compute_setup` gating, `plan_entry_fill`, `advance_one_bar`, F3 rebasing, `compute_trade_r`. Windows come from `strategy_config.yaml` (TUNE only). `engine_core/prereg_lock.py` + `select_candidate.py --register`: REGISTRATION row (SHA-256 of the YAML with line endings normalised, SHA of the gate-parameter block, config budget 6); every ledger row hash-chained (`prev_hash`/`row_hash`); the legacy row kept and chained to `GENESIS`; selection refuses on YAML/gate-hash mismatch, budget mismatch or broken chain; dry runs and diagnostic folders go to `trial_ledger_exploratory.csv`. Dated amendment **AMD-001** appended to the YAML (original text untouched; states it was made before any new selection run, and records the actual draw rule). The real ledger is registered: yaml `18931c4f9640…`, gates `5c040abd4153…`, budget 6.
3. **Tests.** `tests/unit/test_f6_baseline_and_locks.py`. On the pre-F6 tree (`git worktree` at `ab1abca`): 4 failed + 4 errors (missing `engine_core.prereg_lock`, `backtest.path_sim`, `tune_windows`). After: 9 passed — baseline path R equals Simulator R (with and without a split), YAML tamper / seventh config / row deletion / row alteration / silent re-registration are all refused or detected, CRLF does not change the hash, no hard-coded dates remain.
4. **Decisions to review.** (a) The random draws no longer record forward-return diagnostics (`ret_1..20` are NaN): they were computed from raw closes and are used by no gate. (b) My first F6 commit went in with 4 failing tests (the ledger tests copied the live, just-registered ledger); fixed in `05f37ac` — flagging it because of the "no unrelated edits per commit" rule: that first commit also swept in the F2/F9 helper scripts that were already in the working tree.
5. **Found outside the document.** The old baseline accepted entries on dates with a corporate action; `path_sim` now skips them like the Simulator.

---

## F9 — Max-T revalidation (report done; decision needed)
1. **What was wrong.** `test_empirical_fwer_with_ar1_autocorrelation` used unseeded bootstraps (`seed=None`): non-deterministic (12.5% > 12% in one run, pass in others). More fundamentally the procedure was pre-registered as controlling FWER at 5%.
2. **What changed (`c8ff09b`, `ebef11d`).** `scripts/validate_max_t.py` (seeded Monte-Carlo, 600 reps/cell, B=2000) → `docs/MAXT_VALIDATION.md` + json. Test made deterministic, documents measured sizes, plus a reproducibility test. Procedure code unchanged.
3. **Result (size, nominal 5%).** rho=0: 4–5.5% (fine). AR(1) rho=0.4: block-4 11%/9% (80/250 weeks), dual rule (4 AND 8) 8%/7%. rho=0.6: dual 11.5%/10%. Overlapping holds L=4 weeks: dual 9%; **L=12 weeks: dual ~20%, block-4 ~35–38%.** Power (dual, 250 weeks, edge 0.3 SD): 99.7% iid, 81% at rho 0.4, **41% at L=12**.
4. **Decision for owner/reviewer.** Recommended: portfolio-level periodic (monthly) returns versus the matched baseline portfolio, same step-down, blocks in months, re-validated with the same script before use. Alternatives: longer blocks (A), calibrated tighter alpha (B). Nothing is implemented until you choose.
5. **Test before/after.** Before: failed in the earlier run (`0.125 <= 0.12` false). After: 15 passed, deterministic.

## F2 / F2b — STOP-1 reached (raw prices staged and validated; nothing swapped)
> **Superseded as of 2026-11-07 (later):** the swap and symbol mapping HAVE run on the real database (`STOCKBOT_STEP3_SWAP_REPORT.md`), and the open points below were answered by the reviewer and worked through (`STOCKBOT_STEP4_6_REPORT.md`). This section is kept as the STOP-1 record.

Status date 2026-11-07. **No row of `market_data_lake`, `corporate_actions_log` or `shares_outstanding` has been changed.** Only two new tables exist in `finsight.db`: `market_data_lake_staging` and `bhavcopy_fetch_log`. Backup before any F2 work: `F:\Projects\Ravi\Backups\finsight_pre_F2_2026-11-06.db` (+ `.sha256`, integrity ok).

1. **What was wrong (established).** The lake mixes three price bases: pre-2020 rows are raw, 2020-01-01 … 2026-09-xx rows are Yahoo split/bonus/dividend-adjusted, the last ~11 days are raw again. `shares_outstanding` holds *current* Yahoo share counts (source `yahoo_finance_current`, loaded 2026-10-02) stamped 2020-01-01. Both distort ADTV, market cap, gaps and adjustment factors.
2. **What was done.**
   - `scripts/ingest_raw_bhavcopy_range.py`: raw NSE Bhavcopy (EQ series, true unadjusted OHLC, volume, previous close, ISIN) for 2013-01-01 … 2026-09-30 into `market_data_lake_staging`; per-day log in `bhavcopy_fetch_log`. Downloaded strictly one range after another after parallel runs hit "database is locked".
   - `data/ingestion/nse_corporate_actions_history.py`: NSE corporates-corporateActions feed dumped for all 3,945 staged symbols (**33,773 rows, 0 failed symbols**) to `data/reference/nse_corporate_actions_raw.csv`. The free-text subject is parsed conservatively (split / bonus / rights / demerger / merger; bonus debentures and preference shares are not price-moving; anything unreadable becomes `OTHER`). Not loaded into `corporate_actions_log` yet.
   - `scripts/f2_validate_staging.py` (read-only) → `docs/data_audit/F2_staging_validation_report.md` and CSVs `staging_vs_lake_by_year`, `factor_crosscheck`, `symbol_map`, `historical_universe`, `unexplained_moves`. The first two runs were killed by low machine memory; the large-move scan now filters inside SQLite; the third run completed.
   - `data/reference/verified_corporate_actions.csv`: 50-row verification list (standard splits and bonuses, same-date split+bonus for BAJFINANCE/BAJAJFINSV/TECHM, demergers, rights issues, symbol change TATAMOTORS). Selected by the team from well-known events; the price evidence is the independent check.
3. **Evidence delivered (details in the validation report).**
   - Download: **3,476 trading days OK, 111 holiday/missing days, 0 errors**, 2013-2026. Calendar versus the lake's Nifty dates: only 12 Nifty dates without Bhavcopy = the 11 sessions after 2026-09-30 (out of range) + 2025-02-01 (Saturday Budget session).
   - Old lake versus true raw, 2020-2026: the old rows equal the raw close within 0.2% on only 19% of rows in 2020, rising to 64% in 2026 (mean old/raw 0.82 → 0.99); Yahoo volume equals NSE volume on 63% (2020) … 97% (2026). This confirms the mixed bases. All 2,317 lake symbols are in staging; staging has ~1,000 more (delisted or newly listed).
   - **A1 factor cross-check, 1,116 split/bonus ex-dates from the NSE feed.** NSE's `PrevClose` field is **not adjusted by the exchange** (e.g. TATASTEEL 2022-07-28: close 100.35, PrevClose 959.4 = the unadjusted prior close), so the "previous-close factor" in the plan carries no information (2/1116 agree). I replaced it with the raw close-to-close ratio across the ex-date: **764 of 776 agree within 20%**. **Yahoo-implied factor: 407 of 413 agree** (2020-2026 only). 340 ex-dates have no price evidence in staging (actions before a rename, non-EQ series).
   - A3 symbol continuity (ISIN map): **399 ISINs trade under more than one symbol (853 segments)**, e.g. CADILAHC → ZYDUSLIFE, MICROSEC → SASTASUNDR → HEALTHX.
   - A4 historical universe from the daily files: **3,946 EQ symbols; 2,207 with raw data before 2020; 1,198 stop trading before the end** (delisted/renamed). Symbols per year: 1,608 (2013) … 2,935 (2026).
4. **Open points and decisions for the reviewer.**
   1. **Factor disagreements (A1), parser false positives suspected.** 12 ex-dates fail the close-ratio check. Six look like genuine moves just outside the 20% band (ANMOL, CGCL, EASEMYTRIP, PRAKASHSTL, TALBROAUTO, VISHWARAJ: price ratio 0.24 vs 0.20, 0.30 vs 0.25 …; Yahoo agrees on 4 of them). Six need review. For TVSMOTOR 2025-08-25 (log 0.2, price ratio 1.00, Yahoo 1.00), TVSHLTD 2026-09-08 (log 0.021, ratio 0.97), SIYSIL 2026-08-21 and DVL 2021-08-05 **no price change occurred although the log says split/bonus**. SHARONBIO 2014-02-20 (log 0.5, price ratio 0.12) and VCL 2023-02-15 show a different move than the log. Proposed rule: a SPLIT/BONUS row is loaded as price-moving only if the raw price evidence supports it; otherwise it is stored as `OTHER` for manual review. **Needs reviewer confirmation.** (RADIOCITY and MARINE: close ratio agrees, Yahoo does not — a Yahoo problem, not the log's.)
   2. **Large moves (>40%) in staging: 2,472, of which 1,823 have no logged action within 3 days and 889 have a price of at least Rs5 on both days.** The rest are penny/illiquid prints. These have not been classified yet (rights issues, relistings, call auctions and data errors are candidates). **Question: must all 889 be dispositioned before the swap, or only those on symbols that pass the universe screens?** I recommend the second.
   3. **The verification list still lacks a split+bonus in the same year on different dates** (the reviewer's hard case). I will add one from the feed; not done yet.
   4. **The corporate-action history is keyed by the current symbol.** Actions before a rename may be missing for renamed names (399 ISINs, see the symbol map). Proposed: query the old symbols too (the ISIN map gives them) before loading and report how many rows that adds. **Needs confirmation that this extra pass is wanted.**
   5. **Second off-machine backup (A6): owner decision, 2026-11-07.** The owner decided that no external-drive or cloud copy is needed; the single checksummed backup `F:\Projects\Ravi\Backups\finsight_pre_F2_2026-11-06.db` (1,005,137,920 bytes, `.sha256` beside it) is accepted, and no extra full-database backup is taken before the swap. Reviewer to confirm that this waives housekeeping item 2 and condition 4's extra copy (the backup will still be integrity-checked and its checksum verified immediately before the swap).
   6. **Commit state.** Everything is committed and pushed (see the Commits table: staging work is `bdd8b99`, the leftover F6 refactor is `4922a53`). Working tree is clean. No database change is in git.
   7. **F8 prerequisites:** historical ASM/GSM lists and earnings dates are not in the lake; nothing here changes that.
5. **After the reviewer's answer (not started).**
   (a) Apply the F3 migration and the F2 migration (source/loaded_at columns; relax the `corporate_actions_log` CHECK to allow DEMERGER/OTHER; the table is empty).
   (b) One atomic transaction: archive the existing Yahoo rows 2020-01-01 … 2026-09-30 into `market_data_lake_yahoo_archive`, insert the staged raw rows. Pre-2020 rows, rows from 2026-10-01, `NIFTY50_INDEX` and `INDIA_VIX` stay untouched.
   (c) Load corporate actions (append-only `INSERT OR IGNORE`).
   (d) Verification integration test on the real DB for every row of the verification list, written confirmation that ADTV/market cap use raw prices only, unexplained-moves report.
   (e) F2b: derive point-in-time shares from the current issued size back through the corporate-action log, spot-check ~20 symbols against quarterly filings, coverage table by year, exclusion counts (STOP-2 if excluded symbols are a large share of traded value), test with two share counts across one date.
   F9 is still awaiting the Option A/B/C decision.

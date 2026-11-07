# StockBot — Prerequisite Fixes Before Any New Strategy Work

Status: issued after review of the team's codebase understanding and onboarding answers (repo HEAD `be4295a`).
Purpose: remove the measurement and data defects that make any backtest result untrustworthy. **No new strategy code, no new configs, and no new backtests of any strategy until the Readiness Gate (section 5) is passed and signed off by the owner.**

---

## 1. Ground rules

1. **Do not touch the rejected breakout configs' decision.** Do not add configs, loosen gates, or run the 2015–2019 TEST window. That window is reserved for one single-shot test of a future pre-registered strategy.
2. **Do not tune `strategy_config.yaml` values** (positions, heat, VIX, ATR multipliers, decay). Fix code, data, and tests only. If you believe a config value is wrong, raise it; don't change it.
3. **Do not run the Simulator against the real `finsight.db`** until task F4 is done, because it writes `regime_state`. Use a copy of the database for all runs.
4. **Every fix needs a test that fails before the fix and passes after it**, committed with the fix. Report the failing run and the passing run.
5. **One task per commit** where possible. Commit messages state the task ID. No unrelated edits in the same commit.
6. **Ignore CRLF and `.gitattributes` issues** (Windows-only git).
7. Tax stays `stcg_tax_pct: 0.0` until the owner reports back from his CA. Do not change it. Make sure the code handles a non-zero value correctly (task F1 covers net-after-tax reporting).
8. If code, spec, and this document disagree, the code is evidence, the spec is intent, and the owner decides. Report the conflict; don't silently pick.

## 2. Order of work and dependencies

```
F1 net-R metric ─┐
F2 corp actions ─┼─► F3 split-during-hold ─► F8 re-baseline
F2b PIT shares ──┘                           ▲
F4 regime_state isolation ───────────────────┤
F5 DB constraints ───────────────────────────┤
F6 baseline integrity + pre-reg locks ───────┤
F7 exclusions fail-closed (live + pass-2) ───┘
F9 Max-T revalidation  (parallel, needed before F8 conclusions)
F10 hygiene (any time, after F1–F7)
```

Do F1 first. It is small and everything else reports through it. F2 is the longest task and gates the rest, so start the data sourcing for it in parallel with F1.

---

## 3. Tasks

### F1. Correct the R metric (gross vs net)

**Problem.** The candidate trade CSVs contain a `net_r` column that no checked-in code writes. It equals `realized_r`, which is price-based and includes slippage but not fees. Selection gates (G2, G4, G5) and the Max-T "actual" series use it. The random baseline uses true net (`pnl_net / (shares × one_r)`). The paired difference is therefore biased in favour of the strategy by about one trade's cost. Measured: CFG-01 pooled expectancy +0.0519 stored vs +0.0293 true net.

**Required.**
- Define, in one place (`engine_core/trade_metrics.py`), `gross_r`, `net_r` (= `pnl_net / (shares × (entry − stop))`) and `net_r_after_tax`.
- The Simulator writes all three explicitly into its trade output. Remove the orphan column behaviour. `select_candidate.py` and `max_t_bootstrap.py` must read an explicitly named column and fail if it is missing.
- Rename the old column wherever it is consumed, so nothing silently reads the wrong one.
- Use the **same function** to compute R for actual trades and random-baseline trades.
- Document that R is measured against initial risk (`entry − stop`), not partial remaining risk, and say how partial exits are counted.

**Acceptance tests.**
- A fixture trade with known fees: assert `gross_r`, `net_r`, `net_r_after_tax` against hand-computed values, including a partial exit.
- A test that `select_candidate` raises if the R column is absent or if `net_r == gross_r` on a fixture with non-zero costs.
- Regenerate Step 3 outputs into a **new, clearly labelled folder** (`backtest/outputs_recomputed_net/`). Do not overwrite the old outputs or the trial ledger. Report the recomputed expectancy, PF and gate results for all six configs next to the old ones.

---

### F2. Populate corporate actions and verify them

**Problem.** `corporate_actions_log` has 0 rows in the real database. All backtests ran on unadjusted prices, so splits and bonuses look like crashes and gaps. This affects indicators, breakouts, stops, and trade P&L.

**Required.**
- Source split and bonus history (and, for completeness, dividends, rights, mergers) for the full price history in the database, 2010 to present, for every symbol the universe can include. Document the source, the retrieval date, and its limits.
- Load through the existing ingestor into `corporate_actions_log`. The log stays append-only. Record the source and load date per row if the schema allows; if not, add the column through a migration.
- **Independent verification, not just load.** For a list of at least 30 known splits and bonuses across different years and symbols (the team must pick and document them), assert that the adjusted close series is continuous across the ex-date to within a stated tolerance, and that the raw series is unchanged.
- A data-quality check that flags any day-over-day move beyond a threshold (for example ±40%) that has no logged corporate action. Report the list. These are either missing actions or real events and each needs a disposition.

**Acceptance tests.**
- Unit tests for `compute_row_factors` already exist; add an integration test on a real symbol/date pair from the verified list.
- A report listing every unexplained large move after the load, with a disposition column (explained, data error, still open).
- Confirm in writing that ADTV and market cap still use raw values only after the load.

---

### F2b. Point-in-time shares outstanding

**Problem.** `shares_outstanding` has 2,217 rows, all with `effective_date` 2020-01-01. Market cap on any date uses a 2020 share count, and any date before 2020 returns `NO_PRICE_DATA`, so pre-2020 windows (including the reserved TEST window) cannot run.

**Required.**
- Source share-count history that changes over time (splits, bonuses, issues, buybacks), covering at least 2014 to present. Document the source and its limits.
- If a full history cannot be obtained for some symbols, define in writing how those symbols are treated (excluded, or market cap approximated from the nearest filing), and count how many symbols and how much of the traded value is affected. The owner approves the rule before it is used.
- Market cap must use `effective_date <= eval_date`, and a raw close with the raw share count. Add a test with two share counts for one symbol across a date and assert the right one is used on each side.

**Acceptance.** A coverage table: by year, how many universe-eligible symbols have a valid PIT share count, and what fraction of the screened pool that represents.

---

### F3. Splits and bonuses during an open position

**Problem.** Reproduced by the team: a held position plus a 1:2 split produces `STOP_HIT, GAP_THROUGH_STOP` on the ex-date. History is re-adjusted as of today, but `entry_price`, stops, target and `highest_high` remain in the old price basis. The Simulator computes `has_ca` for open positions and ignores it.

**Required.** Choose one approach, document it, and implement it identically in the Simulator and `PositionLifecycleManager`:
- **Preferred:** on an ex-date inside a holding period, rescale all price-denominated position state (entry, stops, target, highest high, partial limits) and share count by the action's factor, and record the action on the position. P&L, R and costs must be unchanged by a pure split or bonus.
- Cash-neutral actions only. For anything not cleanly handled (mergers, demergers, rights), flag the position for manual review and exclude the symbol's trade from statistics. Count them.

**Acceptance tests.**
- Split, bonus, and no-event cases. A pure split during a hold produces the same R and the same exit date as the same series with no split.
- A test through the Simulator **and** through `PositionLifecycleManager` with the same fixture, asserting identical outcomes.
- The team's existing scratch repro becomes a committed regression test.

---

### F4. Isolate backtests from the shared database state

**Problem.** `Simulator.run` calls `RegimeFilter.evaluate`, which writes `regime_state` into the same database that live trading reads. Hysteresis at the start of a window depends on whichever run last wrote the preceding date.

**Required.**
- The Simulator keeps regime state in memory, or in a separate scratch store, seeded explicitly at the window start. A backtest must never write to the production tables.
- Make the starting regime state an explicit, recorded input of each run (value and how it was derived).
- A guard: the Simulator refuses to run if pointed at the live database path without an explicit override flag.

**Acceptance tests.** Run the same window twice, with a different pre-existing `regime_state` in the database before each, and assert identical trade lists. Assert that the production `regime_state` row count and checksum are unchanged after a backtest.

---

### F5. Database schema versus state machine

**Problem.** The real database has CHECK constraints allowing only four position states and five exit reasons. The code writes `PARABOLIC_TRAILING` and `PARTIAL_PROFIT`. `process_all` catches the exception and only logs it, so PAPER positions can silently fail to update.

**Required.**
- A migration that brings the database in line with the state machine. `schema.sql` and the ORM must agree, and a test must prove it.
- Stop swallowing exceptions in `process_all`. A failed position update must fail loudly and be visible in the pipeline result and in the health check.
- Resolve the three equity definitions: PAPER (net minus tax, realized only), LIVE (gross, realized only), pipeline guard (net), and the Simulator (mark-to-market). Pick a definition per purpose, name each clearly, and document where each is used. The owner approves.

**Acceptance tests.** A test that creates the schema from `schema.sql` and writes every state and exit reason the code can produce. A test that a deliberately failing update makes the pipeline report failure.

---

### F6. Random-baseline integrity and pre-registration locks

**Problem.**
- The baseline reads **raw** prices for forward paths, unlike the main simulator.
- It hardcodes dates (`2019-10-01`, `2026-10-16`, window ends).
- Pre-registered text claims 198 trades and 1000 draws matched to entry dates; the code uses `max(500, n_trades × 5)` draws.
- Nothing prevents editing `pre_registered_configs.yaml` or the trial ledger after the fact.

**Required.**
- The baseline uses the same adjusted price path and the same lifecycle code as the main simulator, with true net R from the F1 function.
- Remove hardcoded dates; take them from the window definition.
- Make the pre-registered text and the code agree, or amend the text through a **documented, dated amendment** (do not edit history silently).
- Hash-lock: write the SHA of `pre_registered_configs.yaml` and of the selection gate parameters into the first ledger row. `select_candidate.py` refuses to run if the hash differs or if the number of configs differs from the registered budget. Ledger rows carry a running hash chain so edits are detectable.
- Include `--dry-run` runs in a separate exploratory log so that exploration is counted.

**Acceptance tests.** Tamper tests: edit the YAML and assert refusal; delete a ledger row and assert detection. A test that the baseline and the Simulator produce the same R for the same entry on the same fixture.

---

### F7. Exclusions: fail closed, and consistent between simulation and live

**Problem.**
- Live ASM/GSM and earnings gates are **fail-open**: empty tables block nothing, and the real tables are empty.
- Live uses a current ASM snapshot and a 14-day earnings window; the Simulator uses historical intervals and a 7-day known-ahead window.
- Step 3 ran Pass 1 only.

**Required.**
- Live: if the surveillance list or earnings calendar is empty or stale beyond a stated age, the pipeline blocks new tickets and raises a visible alert. It does not proceed silently.
- Populate ASM/GSM and earnings history for the backtest windows, or state clearly which windows cannot run Pass 2. Every future strategy test uses a Pass-2-style run; Pass 1 is for diagnostics only and must be labelled so in outputs.
- Record the exclusion windows (14 vs 7 days) as a documented difference with the reason. The owner decides whether to align them.

**Acceptance tests.** A pipeline test with empty tables expects a blocked run and an alert. A Simulator test that a Pass-1 output cannot be passed to the selection script as a Pass-2 result (the label is carried in the output and checked).

---

### F9. Revalidate the Max-T procedure

**Problem.** `test_empirical_fwer_with_ar1_autocorrelation` fails in the team's run (12.5% against a 12% bound at ρ=0.4). The dual-block rule mitigates it but the procedure was pre-registered as controlling FWER at 0.05. Longer holds also change the dependence structure, and the weekly statistic is keyed on **entry week**, which breaks when trades overlap for weeks or months.

**Required.**
- Re-run the FWER and power simulations under stated assumptions (autocorrelation levels, number of configs, trade overlap) and report the results honestly, including where control fails.
- Decide, with the owner, one of: fix the procedure, tighten the pre-registered thresholds to compensate, or switch the statistic for long-hold strategies to **portfolio-level periodic returns** (for example, weekly or monthly net portfolio return versus the matched baseline portfolio).
- Document the chosen test and its demonstrated error rates **before** any new strategy is tested.

**Acceptance.** A written validation report with simulated size and power, plus a passing, deterministic (seeded) test that matches the stated error bound.

---

### F10. Hygiene (after F1–F7)

- `authorized_deployment.json` is stale and unlinked from the current config. Leave it unauthorized, and add a clear marker in the file or docs that no strategy is currently authorized. Add the `mode` key and compare it to `runtime.mode`.
- Add the missing `live_guardrails` config section, or remove the dead drawdown-guard code. Do not set values without the owner's approval.
- Move the hard-coded `atr_projection_mult = 3.0` and the `/3` in log text into config.
- Bring README and docstrings in line with the code (kill-switch thresholds, stop and decay parameters, 19:00 scheduler, 20-session decay). List each change.
- Make `test_baseline_reproducibility` independent of the real database and hash files (fixture data instead).
- The regulatory-barrier test scans only `live_runner` and `engine_core`. Extend it to the whole repository, and add an outbound-host allow-list check.
- Idempotency: add a documented recovery procedure for a run stuck in `RUNNING`, and make the scheduler's catch-up delete of `pipeline_run_log` rows explicit and logged.
- Sector cap: the spec says percent of allocated capital; the code uses total equity. Ask the owner which is intended, then align the code or the spec.

---

## 4. Reporting format (per task)

For each task, report:
1. What was wrong (with the file and line references).
2. What changed (commit ID).
3. The failing test before and the passing test after.
4. Anything you decided that the owner should review.
5. Anything you found that is **not** in this document.

Report open questions early, not at the end. If a data source is unavailable or unreliable, stop and say so. Do not substitute a guess.

## 5. Readiness Gate (all must be true)

- [ ] F1: R metrics are explicit and consistent; Step 3 outputs recomputed in a separate folder with a side-by-side report.
- [ ] F2 and F2b: corporate actions and PIT shares loaded, with the verification list, the unexplained-move report, and the coverage table delivered.
- [ ] F3: split-during-hold handled identically in the Simulator and live code, with regression tests.
- [ ] F4: backtests cannot write to production tables.
- [ ] F5: schema matches the state machine; no swallowed exceptions.
- [ ] F6: baseline uses the same price path and R function; pre-registration is hash-locked.
- [ ] F7: live exclusions fail closed; Pass-2-style runs are possible for the new windows.
- [ ] F9: a validated multiple-testing procedure with documented error rates for the intended holding periods.
- [ ] Full test suite passes on a clean checkout, with no dependence on the real database.
- [ ] A short written summary of the effect of F1–F3 on the old Step 3 results, so the owner can see how much the earlier conclusions moved.

After sign-off, the next document will be the pre-registered specification for the new strategy family. Nothing in the strategy phase starts before then.

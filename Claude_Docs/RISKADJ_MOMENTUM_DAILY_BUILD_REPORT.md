# riskadj_momentum_daily: build report

Branch `riskadj_momentum_daily` (from origin/master e2a6a82). Nothing registered, nothing run on the real lake except the counts study. **No return, P&L or forward price of this strategy was computed or looked at.**

## Summary
| Item | Result |
|---|---|
| Final spec hash | **`5b06f092df061bff1532093d21ea21c88c3f2db64ddd66e0cbe81bd5c0446e19`** (`expected_trade_rate` 8.1 included) |
| Gates hash | `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`, unchanged; `shared_config_hash` `da459624...` unchanged; riskadj_momentum's spec hash `72dbec2c...` and lowvol_uptrend's `52e7ee3c...` unchanged |
| Shared change (commit 433b1e1) | opt-in engine-owned exit history; proof below; full G2 on that commit alone 1,422 passed |
| Allow-list commit (125d44d) | eight ids, one policy class |
| Strategy, counts, scripts, tests, docs (cd7f7bd) | built; counts over the real lake (memory view, 5,875 s) |
| Gates at the end | G1 1,372 passed, 9 skipped; full G2 1,502 passed, 0 failed; G3 2 passed; `finsight.db` sha256 `dcade465...b752` before and after |
| Rule workable? | Yes: 2,458 of 2,459 sessions with a calendar have a full top 25 (one has 23); the engine sees only the top 25, and on 447 sessions (18%) fewer than 12 of them can pass the sector cap |
| Proposed `expected_trade_rate` | **8.1** a month (12 slots, 30-session hold); 12.0 at 20 sessions, 6.1 at 40 |

## 1. The shared change (own commit, before any strategy code)
**What was missing:** `propose()` received only the view, the eligible list, its own previous state and overlay signals; closed trades went only into `Decisions.closed`; an exit policy is not called on the bar where the stop is hit; reported exits in live bypass `decide`.
**What was built:**
- `stockbot/engine/exit_history.py` (new): the reserved key `"_exits"`, `history_sessions`, `entries`, `merged` (prune to the last N sessions of the view's calendar, as-of day included), `with_history`.
- `stockbot/engine/decide.py`: before proposals, for each strategy with a class attribute `exit_history_sessions > 0`, the engine appends `[canonical symbol, exit session, exit reason]` for that strategy's trades closed this session (STOP_HIT, SYMBOL_NO_BARS, policy and target exits), prunes, writes the key into that strategy's state, calls `propose`, then restores its own copy of the key whatever `propose` returned (also when `propose` fails). Canonical name = `view.resolve_symbol`.
- `stockbot/engine/reports.py` (`apply_effect`): for a reported exit that closes a position of a strategy whose state already carries the key, the same record is appended (canonical name through `symbol_links.resolve`); pruning waits for the next `decide`. Nothing is added to `ReportEffect`, so journaled effects are byte-identical.
- `stockbot/strategies/base.py`: docstring only.
- Guide only where tests required it: `docs/guides/CODEBASE_GUIDE.md` (a row for `exit_history.py`; a row for `scripts/addendum_lowvol_uptrend_run1.py`, missing on master since the lowvol merge) and the rebuilt `codebase_guide.html`.
- **No hash can change:** the opt-in is a class attribute, not a spec field; `StrategySpec` is untouched; a test pins `"exit_history_sessions" not in SPEC.__dict__` and the gates hash is asserted by an existing test.

**Shared files touched and why:** `stockbot/engine/decide.py` (record and restore), `stockbot/engine/reports.py` (reported exits), `stockbot/engine/exit_history.py` (new, the logic), `stockbot/strategies/base.py` (docstring), `docs/guides/CODEBASE_GUIDE.md` and `codebase_guide.html` (rows a test requires). Allow-list commit: `tests/fixtures/boundaries.py`, `tests/unit/test_no_strategy_in_the_tree.py` (approved, step 1).

**Proof (all required items):**
1. *riskadj_momentum and lowvol_uptrend on a fixture, before and after, byte-identical:* the harness `docs/shared/exit-history/proof/byte_identity_harness.py` runs both strategies' research scripts on a fixture lake (32 rising names plus 6 falling names so that stops are hit) and then the live adapter with a state store through every session; it hashes `trades.json`, `daily.json`, `equity_curve.json`, `blocked.json`, every journal row (kind, session, key, payload) and the final state. Before (`before_change.json`) and after (`after_change.json`) are byte-identical for both strategies, and again identical on the final tree after the new strategy was added (19 trades, 48 journal rows for riskadj_momentum; 11 trades, 48 journal rows for lowvol_uptrend).
2. *Every existing golden, digest and parity test byte-identical:* the full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`) on the commit 433b1e1 alone, run in a clean detached worktree: **1,422 passed, 0 failed**. It includes, among others: `tests/unit/test_golden_files.py` and `tests/golden/*` (SHA256SUMS, `asof_120_samples.json`, `engine_scan.csv`, `engine_scan_summary.json`, `legacy_equivalence.json.gz`), `tests/data_integrity/test_golden_frozen.py`, `test_asof_view_real_db.py`, `test_corporate_actions_real_db.py`, `test_entry_bar_real_lake.py`, `test_calendar_integrity.py`, `tests/unit/test_asof_memory.py` (SQL = memory digests), `test_market_switch.py` (default-overlay run byte-identical to master, shared-config hash), `test_engine_live.py` (backtest and live give identical decisions day by day; journal rebuild equals the snapshot), `test_exit_policy_journal.py`, `test_engine_decide.py`, `test_engine_backtest.py`, `test_stale_positions.py`, `test_fast_view_followup.py`, `test_g3_fixture_baseline.py`.
3. *New tests (`tests/unit/test_exit_history.py`, 14):* exit recorded on the exit session and visible to that session's proposals; a strategy that does not opt in gets exactly the previous state (no key; every other part of every Decisions identical); pruning to the last N sessions (the 4th session back is dropped); the key restored when a strategy drops or alters it, and when it fails to propose; two strategies get only their own exits; the canonical symbol after linking (position opened under the old name, rename afterwards); SYMBOL_NO_BARS recorded with its reason; a position open at the window end (END_OF_WINDOW) is not in the history; an operator-reported exit recorded and visible, journal rebuild equals the snapshot; a reported exit of a non-opt-in strategy adds no key; the live adapter and the backtest record the same assumed exit; SQL = memory byte for byte.
4. G1 after the commit: covered by the full G2 above (a superset); G1 on the final tree below.

## 2. The strategy (`stockbot/strategies/riskadj_momentum_daily/`)
Copied from riskadj_momentum (nothing imported from that folder; a test checks the imports), then: every session is a signal session; `params` = riskadj_momentum's plus `{"signal": "every_session", "reentry_cooldown_sessions": 21}`; class attribute `exit_history_sessions = 25`; `cooldown_symbols` blocks a canonical symbol whose history has a `STOP_HIT` exit inside the last 22 sessions of the calendar (exit session = day 0; days 0 to 21 blocked, day 22 allowed); blocked names are removed before the ranking; status `research`, no overlay. Exit policy `RmdTrailingAtr3Floor8` (id `rmd_trailing_atr3_floor8`), a copy of `TrailingAtr3Floor8`.

**Tests (`test_riskadj_momentum_daily_strategy.py`, 57; `test_riskadj_momentum_daily_scripts.py`, 22; fixture lakes only):** on the first session of a month (four dates on the fixture) the proposals (symbols, order, stops, ranks, reference prices, metadata) equal riskadj_momentum's; every other session also proposes; the cooldown edges (exit session through the 21st session after it blocked, the 22nd allowed; unit and through the engine with the real strategy, the stopped name absent for 22 sessions and back on the 22nd); only STOP_HIT starts a cooldown (SYMBOL_NO_BARS, END_OF_WINDOW, operator reasons, TIME_EXIT do not); linked names; blocked names skipped before the ranking with the top 25 refilled; END_OF_WINDOW from a real backtest starts none; the state key equals the engine's; SQL = memory through the engine; the ATR function equal to riskadj_momentum's; the exit policy giving the same `PolicyActions` and stops session by session on a random path with a corporate action; the baseline pool (held, cooldown edges 21/22, END_OF_WINDOW and SYMBOL_NO_BARS start none, linked names, draws not blocking each other, filter from stored trades only, meta counts); equivalence of the strategy-side draw loop with the shared helper when given the shared stop rule and no pool filter; end-of-window closure and counting for trades and draws; stale exits; `validate_family.py --expect-k 1` dry run; refusal without `--execute`; SQL = memory byte for byte.

## 3. Counts (2,674 sessions, 2016-01-01 to 2026-10-16; `docs/strategies/riskadj_momentum_daily/counts/`)
Cooldown not applied (it needs engine exits). Eligible names per session median 275. Qualifying: 215 empty sessions (no 252-session calendar yet), median 171 over all sessions; fewer than 25 in 216 sessions (the 215 and one with 23). No score ties in 532,328 qualifying name-sessions. **Day-to-day overlap of the top 25:** mean 23.0 names (92.1%), range 18 to 25. **Top 12 changes on 81.3% of sessions**, mean 1.15 new names, maximum 6. **Stop distance:** median 11.8%, p5 8.0%, p95 19.6%, 15.9% at the floor; position size median 8.5%, mean 8.8% of equity. **Sectors:** 76.8% mapped; median 8 distinct mapped sectors in the top 25; **depth to find 12 names under the 15% sector cap: median rank 17, p95 41, max 55; more than 25 needed on 447 of 2,459 sessions (18%).** Slot arithmetic with 12 slots: 20-session hold 12.0 entries a month (about 1,405), 30 sessions 8.1 (about 952), 40 sessions 6.1 (about 720); proposed 8.1 (the 30-session midpoint, because the 20-session median understates the mean hold of a trailing-stop rule; riskadj_momentum run 1's median hold of 20 sessions is a result already seen and is cited as such). Capital allows about 11 positions at a mean size of 8.8%.

## 4. Baseline (decision C) and the cooldown exclusions
`PoolExclusions` in `scripts/baseline_matched_random_riskadj_momentum_daily.py` drops, for each actual entry's signal session: the symbols the strategy held (entry date <= session < exit date) and those in its own cooldown (STOP_HIT exit 0 to 21 sessions before), from the stored run's trades, by canonical name; the trade's own symbol is dropped as in the shared helper; draws never block each other. **How many pool exclusions come from the cooldown cannot be reported yet:** it needs the stored trades of the registered run (this task runs no backtest); the count appears in `baseline_meta.json` under `pool_exclusions` (`checked`, `kept`, `held`, `cooldown`, `own_symbol_per_entry`) and will be reported with the run. **Observation for the review:** the shared helper excludes only the trade's own symbol, not "symbols it held" as the task text says ("as the baseline does today"), so the held exclusion is new relative to the earlier registered baselines; I implemented what option C says and flagged it in BRIEF and PREREGISTRATION.

## 5. Readings (for you to overrule)
1. Cooldown removes names before the ranking (the top 25 is refilled); reading B ranks first and drops.
2. Day 0 (the exit session) is blocked: the strategy decides on that session's close and sees that session's exits.
3. As riskadj_momentum: calendar-window "240 of 252", own-bar offsets, ATR over 252 bars, log returns across gaps between consecutive available closes.
4. An exit reported by the operator in live with a reason other than STOP_HIT (free text) starts no cooldown, even if it was in fact a stop; the history stores the reason as reported.
5. In live, the canonical name of a reported exit is resolved with the link table in force when the report is applied; `StateStore.rebuild()` re-resolves with the table in force at rebuild time, so a link added later could make a rebuild differ from the stored snapshot for that one record (the strategy resolves both sides on read, so decisions are not affected).

## 6. Gates and the database
| gate | result |
|---|---|
| G1 (`pytest tests/unit tests/integration`, final tree) | **1,372 passed, 9 skipped, 0 failed** (24 min) |
| full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`, final tree) | **1,502 passed, 0 failed** (27 min) |
| full G2 on the engine commit alone | 1,422 passed, 0 failed |
| G3 (`tests/unit/test_g3_fixture_baseline.py`) | 2 passed |
| byte-identity harness, final tree | identical to before the change |
| `finsight.db` sha256 | `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after |

## 7. Decisions needed
1. **Shared change as built:** review commit 433b1e1 (it is the only engine change). Reading 4 and 5 above are the two places where reported exits in live behave in a way you might want different.
2. **`expected_trade_rate` 8.1** (30-session hold) versus 12.0 (20 sessions) or 6.1 (40 sessions): it changes the spec hash and the power section only.
3. **Baseline held-symbol exclusion** is new relative to earlier baselines (see section 4); confirm it is wanted.
4. **Cooldown before ranking** (reading 1).
5. **Concentration:** on 18% of sessions the top 25 holds fewer than 12 names that pass the sector cap, so fewer entries than the slot arithmetic says.
6. Registration of `family_batch4` (K = 1) on master at the commit carrying the pre-registration, and authorisation of the registered run.

## 8. What ran and what did not
Ran: unit and fixture tests; the counts study on the real lake (memory view, read-only, DB hash unchanged); the full G1, G2 and G3. Did not run: the registered backtest, baseline, benchmark, gates script and `validate_family` on the real lake. Nothing is registered.

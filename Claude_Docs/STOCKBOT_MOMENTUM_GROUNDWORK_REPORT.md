# StockBot: momentum strategy, pre-registration groundwork (report)

Written 2026-11-09 for the owner and for a reviewer who has not seen the session. Branch `claude/momentum-prereg-groundwork-z93w6m`. Task text: `docs/strategies/momentum/BRIEF.md` (saved verbatim, not edited). Status file: `docs/strategies/momentum/STATUS.md`.

## 0. Read this first

1. **Part 1 could NOT be measured. No Part 1 figure exists in this report.** `finsight.db` is git-ignored (3.4 GB) and is not in the cloud container this session ran in (`ls finsight.db`: no such file; `find / -name finsight.db`: nothing; no computer was attached: `list_computer_folders` returned an empty list). I did not substitute any other data. What was delivered for Part 1 is the study tool, its wrapper and a test on a synthetic fixture lake, plus the exact command that produces every Part 1 table on the owner's machine (section 2.5). The tables in 2.6 are empty on purpose and marked NOT MEASURED.
2. **Part 2 is answered in full from the code** (section 3), with one measurement made on a synthetic lake (Q5), labelled as such.
3. **No forward return, P&L, win rate or forward price change was computed, read or looked at.** No strategy file, no ledger entry, no edit to shared engine/validation/config/universe/risk/data code.
4. **Findings the owner/reviewer must decide before registration** are collected in section 4. The most important: (a) a concrete exit policy has no allowed home under the current import rules; (b) the rule does not say how many names to propose per session, and the answer changes the trade count; (c) with a 3 x ATR stop and 1% risk sizing, the shared sector cap and cash cap will probably limit how many of the 12 slots can be used, and in live every symbol missing from `sector_map.csv` shares one 15% "UNKNOWN" bucket; (d) "entry minus 3 x ATR" cannot be anchored on the entry, only on the signal-day close.
5. **Tests:** G1 503 passed / 2 failed / 2 skipped before, 516 passed / 2 failed / 2 skipped after. The same two tests fail before and after (line-ending pins, section 6). G2 cannot run here for lack of the database (section 6).

## 1. What was done, and every deviation

| item | state |
|---|---|
| `docs/strategies/momentum/BRIEF.md` | saved first, verbatim |
| `stockbot/data_checks/momentum_signal_count.py` | new: the study logic (counts only) |
| `scripts/signal_count_momentum.py` | new: wrapper; also injects the shared eligibility rule (see deviation 1) |
| `tests/unit/test_momentum_signal_count.py`, `tests/fixtures/momentum_lake.py` | new: 12 tests on a synthetic file-backed lake |
| `docs/guides/CODEBASE_GUIDE.md` | two table rows added (see deviation 2) |
| this report, `docs/strategies/momentum/STATUS.md` | new |

Deviations and additions, stated plainly:

1. **The wrapper is slightly more than "thin".** The task says the logic goes in `stockbot/data_checks/` and the rule uses the shared `universe.eligibility`. `data_checks` may import only `config` and `data` (`tests/fixtures/boundaries.py`, `ALLOWED`), so it cannot import `stockbot.universe`. The logic module therefore takes the eligibility function as an argument; the wrapper builds it from `stockbot.universe.eligibility.eligible_symbols` and the shared config, and passes the shared position cap, risk per trade and sector cap. No boundary rule was touched.
2. **`docs/guides/CODEBASE_GUIDE.md` was edited** (a row for the new module in C.10 and one for the new script in D). `tests/unit/test_guides_consistent.py` fails if a module or script is not named in the guide. Documentation only.
3. **Two EXTRA figures are in the tool, flagged "EXTRA, not in the task"** (tables x and xx): the share of candidates whose 1%-risk position at a 3 x ATR(14) stop would alone exceed the shared sector cap, and the cash the top-12 candidates would need as a % of equity. They use only the signal-date close/high/low (backward-looking) and are counts. I added them because the task asks "does the rule produce enough trades" and section 4 item 3 depends on them. They can be ignored or dropped.
4. **Part 1 (a) to (h) were not measured** (section 0, item 1).
5. **Environment, not repository:** to run the tests in the container I installed `pytest`, `sqlalchemy`, the packages in `requirements.txt` and `yfinance` with pip. Nothing in the repository changed because of it.
6. **One timing measurement** (Q5) was made on a throw-away synthetic lake kept in the scratchpad, not committed.

## 2. Part 1: counts-only signal study

### 2.1 What the tool does

`py scripts/signal_count_momentum.py [--lake PATH] [--start D] [--end D] [--out-json F] [--out-md F] [--no-hash] [--max-sessions N]`

For every session `t` from the first calendar session (2015-11-09, the first Nifty row) to `--end`, it builds `AsOfView(conn, t)` (so every query is bounded by `t`), asks the shared eligibility rule for the eligible names, and for each eligible name reads `view.adjusted_bars(sym, lookback=200)` and `view.corporate_actions(sym)`. The lake is opened only by `stockbot.data.lake.open_lake`. It records per session: eligible count; names with fewer than 200 bars; names meeting the trend condition; names with trend and a finite score; split/bonus actions inside the 132-bar and 200-bar windows; gaps; the ranked list. A second pass over the same sessions runs the occupancy model. Output is markdown tables, each stamped `measured <date>`, plus optional JSON with every simulated entry. The tool hashes `finsight.db` (sha256, size, mtime) before and after and exits non-zero if they differ.

It does not compute a return. The only numbers taken from prices are the signal-date score (looks back from `t`), the signal-date trend flag, the ATR/close for the two EXTRA tables, and nothing that follows `t`.

### 2.2 How the rule's words were turned into code (interpretations to confirm)

| rule text | implemented as | note |
|---|---|---|
| "126 sessions, skipping the most recent 5" | `close[-1-5] / close[-132] - 1` on the last 200 adjusted bars; `-1` is the symbol's bar on the as-of date | the task text says "131 for the score": 131 is the offset `t-5-126`; **132 bars** are needed (indexes `t-131 .. t`). The 200-bar average is the binding requirement either way |
| "sessions" | the symbol's own last N bars (what `adjusted_bars(lookback=N)` returns), not calendar sessions | a name with missing sessions has a window that spans more calendar time. The rule says nothing about gaps; the tool reports how many names are affected (h4 to h6) |
| trend | `close_adj[t] > sma(close_adj, 200)[t]` using the shared `indicators.sma`, bar `t` included | |
| valid score | finite and strictly positive closes at `t`, `t-5`, `t-131` | names that fail are counted in "unusable adjustment or non-positive price" |
| ranking | score descending, ties by symbol | the engine does this itself: `risk/arbitration.py::admission_order` sorts by `(-rank, symbol)`; a strategy would set `rank = score` |
| universe | `eligible_symbols(view, cfg.universe)`, no overrides, **no ASM/GSM ranges** | no historical ASM/GSM exists (KI-003), as in any backtest |
| first valid date | first session where at least one eligible name has 200 bars and a finite score | the view reads bars from before 2015-11-09 (the lake holds rows from 2013), so this can be the first calendar session itself. The tool also prints the date if only calendar sessions counted (the 200th calendar session) |

### 2.3 Occupancy model (item e), exactly as built

Signal at the close of session `j`; entry at the open of `j+1`; that bar is session 1 of the hold (the engine steps the entry bar, `engine/stepping.py::step_position`, so `days_held` is 1 at the end of the entry day); the market exit is requested at the close of session 20 and executes at the open of session 21 (`test_time_exit_request_executes_at_the_next_open`: "3rd bar held requests; next open executes"). In the engine's order of work (`decide`: fills, then exits, then proposals) the slot is free for a signal at the close of the exit session, so one slot cycle is **21 sessions** (entry to next entry). Each session the free slots (12 minus open positions) are filled from the ranked list in order, skipping symbols already held (`risk/arbitration.py::arbitrate` returns `ALREADY_HELD` for them without using a slot). A naive 20-session cycle (slot re-used at the open of the exit session) is also counted as a sensitivity, although the engine cannot do it.

**This is an UPPER-BOUND OCCUPANCY MODEL, not a trade forecast.** It ignores stops (which end holds early, freeing slots, so they RAISE the count), the 15% risk cap, costs, the 3% gap-up cap and the other fill blocks (`engine/fills.py::fill_ticket`: gap through stop, corporate action on the execution date, no bar), the sector cap, the cash cap, and assumes the name has a bar the next session. Those blocks would LOWER the count. Neither direction is bounded by this table.

One piece of pure arithmetic needs no data: with the engine-order cycle of 21 sessions, 12 slots cannot produce more than 12 x 252/21 = **144 entries a year (12 a month)** if every slot is always full and no stop is hit. Stops can push the real number above that. For scale, the previous strategy ran at about 2.6 trades a month (KI-002 in `docs/guides/DATA_GUIDE.md`).

### 2.4 Verification on the fixture lake (this is not a result about the market)

`tests/unit/test_momentum_signal_count.py` builds a 300-session synthetic lake (`tests/fixtures/momentum_lake.py`: five rising names, a rising name with a 1:5 split inside the window, a rising name with a 10-session gap, a name that returns after an absence with fewer than 200 bars, two falling names). It checks:

* the first valid date is the 200th bar; scores equal an independent computation from the generator's own series to 1e-12; ranking order; the falling names fail the trend test;
* the split case: the score uses the **adjusted** series (positive, equal to the independent value), the split is flagged inside both windows after its ex-date, and is neither flagged nor applied the session before;
* the gap name is counted only in the gap tables, the returning name only in the short-history table; the 132 to 199 bar range is counted as "score computable, trend not";
* occupancy timing: entries for one symbol at sessions 200, 221, 242 (21-session cycle), occupancy 7, 0 at the exit session, 7 again; the cap and held-symbol rules on a toy input; the naive cycle is 20;
* **no price after the as-of date is read**, three independent ways: (1) the SQL actually issued is traced with `set_trace_callback`; for every statement, every date literal is `<=` the session being evaluated, and every `market_data_lake` statement carries a `trade_date <=` / `=` bound (the single exception is `AsOfView.symbol_info`'s existing `select min(trade_date)` probe of the Nifty start, which is a calendar fact, not a price); more than 1,000 such statements were checked; (2) every row after a cut date was multiplied by 7 (and a 1:50 split added the next day) in a copy of the file: all counts, ranked entries and distinct-name sets up to the cut are identical; (3) a long run and a truncated run agree on every session up to the cut;
* a static scan: the module imports only `stockbot.data.*` and `stockbot.config.*`, and contains no `pct_change`, no negative `shift`, nothing from `stockbot.strategies`;
* the database file is byte-identical after the command-line path ran (sha256, size, mtime).

### 2.5 How to produce the real Part 1 tables (owner's machine, Windows)

```
py scripts/signal_count_momentum.py --out-md Claude_Docs\MOMENTUM_SIGNAL_COUNTS.md --out-json Claude_Docs\MOMENTUM_SIGNAL_COUNTS.json
```

* Needs `finsight.db` in the repository folder (or `--lake PATH`). Reads it read-only; hashes it before and after (about a minute for 3.4 GB each way; `--no-hash` skips the hash but still compares size and mtime).
* **Run time is not measured on the real lake.** On the synthetic lake the per-session cost was about 1 ms per trading symbol for eligibility plus about 3 ms per eligible symbol for this tool's work (section 3, Q5). For roughly 2,000 trading symbols and 800 eligible names that is about 4.4 s per session, so **roughly 3 hours for 2,700 sessions**; treat it as "a few hours". Progress goes to stderr every 50 sessions. There is no checkpointing; use `--start/--end` to split a run (the occupancy model restarts at `--start`).
* The output contains tables (a) to (h), the two EXTRA tables, and the before/after fingerprint of the database. Paste it into a report; every table is already stamped with the date it was measured.

### 2.6 Part 1 tables: NOT MEASURED

| item | content | state |
|---|---|---|
| a | first date the rule can produce a valid score | NOT MEASURED (lake absent). Not derivable from the documents either: the guide says the Nifty calendar starts 2015-11-09 and the lake has equity rows from 2013, but how many names have 200 earlier bars is a lake fact |
| b, c, d | eligible / trend / trend-and-score per session, median, p5, p95, per year 2016 to 2026 and total | NOT MEASURED |
| e | occupancy-model entries per year and total | NOT MEASURED (ceiling by arithmetic only: 144 a year, section 2.3) |
| f | concentration, top-10 share, sector split, symbols without sector | NOT MEASURED. Known from the repository: `data/reference/sector_map.csv` has 501 rows; the guide counts 3,625 equity symbols ever in the lake and 2,691 trading on the last session. Most eligible names will have no sector; the tool counts them |
| g | distinct symbols selected, median and maximum positions at once | NOT MEASURED |
| h | names dropped for under 200 bars; names with a split/bonus inside the 132 or 200-bar window; names with a gap of more than 5 sessions | NOT MEASURED |

## 3. Part 2: engine design check (from the code)

**Q1. Which `ExitPolicy` implementations exist in `stockbot/engine/exit_policy.py`?** None. The file holds the `ExitPolicy` Protocol (`initial_state`, `step`, `on_corporate_action`) and the data types `Bar`, `MarketAtNextOpen`, `Limit`, `StepContext`, `PolicyActions`. The `policies` mapping that `run_backtest` and `decide` take is supplied by the caller; `live/runner.py::default_book()` has none. The only concrete policies are test doubles in `tests/fixtures/dummies.py`: `FixedPolicy` (stop stays; optional time exit after `max_days`, optional limit target, optional breakeven), `ViewReadingPolicy`, `LoweringPolicy`. `tests/unit/test_no_strategy_in_the_tree.py::test_no_class_outside_tests_implements_the_strategy_or_overlay_or_exit_policy_interface` fails if any class outside tests implements the exit-policy interface other than the three interface definitions.

**Q2. Can they express a fixed N-session time exit plus the initial stop?** The engine can; no production class does. The initial stop needs no policy: `engine/fills.py::fill_ticket` puts the ticket's stop into `Position.initial_stop` and `live_stop`, and `engine/stepping.py::step_position` checks `bar.low <= live_stop` first on every bar including the entry bar, filling at `min(open, stop)` times the exit slippage. The time exit is what `tests/fixtures/dummies.py::FixedPolicy(max_days=N)` already does and `tests/unit/test_engine_decide.py::test_time_exit_request_executes_at_the_next_open` proves. The addition needed, not implemented:

* a class, for example `FixedHoldPolicy(hold_sessions: int)`, with `id` derived from N (for example `fixed_hold_20`; this id goes in `StrategySpec.exit_policy` and into `Position.exit_policy_id`);
* **state needed: none.** `initial_state(position, view)` returns `{}`; `on_corporate_action(exit_state, factor)` returns `dict(exit_state)` because it holds no price;
* **counting sessions held:** `step` reads `ctx.days_held` (`StepContext.days_held`, "sessions held including this bar"; `step_position` increments `Position.days_held` before calling the policy, so it is 1 on the entry bar). When `ctx.days_held >= hold_sessions` it returns `PolicyActions(requests=(MarketAtNextOpen(position.shares_remaining, "TIME_EXIT"),))`; otherwise `PolicyActions()` (no stop change, so the stop stays at the initial level);
* **how it requests the exit:** the `MarketAtNextOpen` is stored as `Position.pending_exit`; on the next bar `step_position` step 1 executes it at the open times `(1 - exit slippage)`, before the stop check. So with N = 20 the exit is at the open of session 21, as the task states;
* because the policy returns `PolicyActions()` when it has nothing to say, the engine's rule "a stop can never move down" is untouched.

*Where it can live is a problem, see Q8 item 1.* Hold is counted in bars stepped: a session in which the symbol has no bar (`decide` flags `NO_BAR_POSITION_NOT_STEPPED`) does not count, and a pending exit waits for the next bar.

**Q3. Does ctx or position state expose sessions held and the entry date; does it survive the journal and `rebuild()`?** Yes to both. `StepContext.days_held`; `Position.days_held`, `Position.entry_date`, `Position.exit_state`, `Position.pending_exit` (`engine/types.py`). `Decisions.position_updates` carries the complete `Position` each session (`PositionUpdate`), `Decisions.to_json/from_json` round-trips it, `engine/apply.py::apply_decisions` folds it into `State`, and `live/state_store.py::StateStore.rebuild()` folds the journal with `apply_decisions`. Existing tests cover it with a time-exit policy: `tests/unit/test_engine_decide.py::test_state_is_the_fold_of_the_decisions` (rebuild through the JSON form equals the live state, position with `days_held > 5`) and `tests/unit/test_engine_live.py` lines 163 to 176 (`store.rebuild().to_json() == store.load().to_json()`). A split or bonus rescales prices and shares but leaves `days_held` and `risk_inr` unchanged (`ENGINE_CONTRACT.md` section 7). One caveat: positions put on HOLD by an unrescalable action (merger, demerger, rights) are still stepped and would still be time-exited, but are excluded from trade statistics.

**Q4. ATR(14) and lookahead.** `stockbot/data/indicators.py`:
```
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series
```
Pure; Wilder smoothing via `rma` (seeded with the simple average of the first 14 true ranges; first bar's true range is high minus low). It computes on whatever series it is given. Fed with `view.adjusted_bars(sym, lookback=L)[["high_adj","low_adj","close_adj"]]` it is on prices adjusted to the as-of date, using only actions with `ex_date <= as_of` (`AsOfView.corporate_actions`, `adjustments.compute_row_factors`). Two cautions: (a) ATR is recursive, so its value depends slightly on how many bars are fetched (the seed's weight after 186 more bars is about 1e-6); the strategy must fix one lookback so backtest and live agree; (b) the rule's stop would be `reference_price - 3 x ATR`, in the as-of price basis, which the engine later rescales on splits.

*Lookahead with corporate actions inside the 126 or 200-bar window:* none from the adjustment. `compute_row_factors` scales a bar only if an action with `ex_date <= as_of` falls after it; an action after `t` is not in the view (`AsOfView.corporate_actions` filters in SQL), and even if it were, it would scale every bar in the window equally and cancel in the score ratio. Tested: `tests/unit/test_engine_decide.py::test_lookahead_changing_every_later_row_does_not_change_earlier_decisions` (every later row altered and a future split inserted: identical decisions), and the same property for this study (section 2.4). What is NOT solved by the adjustment, and matters for a ranking rule (from `docs/guides/DATA_GUIDE.md` section E): only SPLIT and BONUS move prices. 259 split/bonus-like rows whose evidence disagreed are stored as `OTHER` and not applied; 108 demergers, 91 mergers and 341 rights issues are never adjusted. A price step from any of those inside the window is a fake return in the score, in either direction; a missed reverse split or a merger-driven jump would rank a name first for no reason. The study counts only the events the adjustment does handle (h2, h3). A count of large single-bar moves inside the windows (as `data_checks/f2_engine_scan.py` does for the whole lake) would measure the residual; I did not add it. Also, the log's rows were loaded on 2026-11-07, but only the ex-date is used, so that is not a lookahead for adjustments.

**Q5. Ranking across all eligible symbols: efficient, or one `AsOfView` call per symbol?** One call per symbol. There is no bulk or cross-sectional API: `AsOfView.adjusted_bars(symbol, lookback)` runs two SQL queries (bars, corporate actions) and builds the frame in Python. `universe/eligibility.py::eligible_symbols` itself loops over every symbol that traded on the as-of date, with `symbol_info` (2 queries) and `adtv` (1 query) each, and `decide` calls it every session whatever the strategy. A strategy receives the eligible tuple and the view, and loops.
*Measurement, on a synthetic lake, not the real one:* 1,800 symbols x 330 sessions (594,330 rows) built in the scratchpad, the same schema and indexes, hot cache, this Linux container. One session at the last date: `eligible_symbols` 1.78 s (about 1.0 ms per trading symbol); `adjusted_bars(lookback=200)` for 1,800 eligible names 3.26 s (1.8 ms per name; that is the scoring read a strategy would need); this tool's full per-session work (bars, corporate actions, SMA, ATR, gap and adjustment flags) 5.22 s (2.9 ms per name).
*Projection for a 2016 to 2026 backtest (2,674 sessions, from the per-year counts in the guide):* cost per session is about 1.0 ms x (trading symbols T) for the shared eligibility, which every strategy pays, plus about 1.8 ms x (eligible names E) for scoring. T was 1,632 in 2016 and 2,931 in 2026 (guide section F). E is unknown until Part 1 is run. With the illustrative T = 2,000, E = 800: 3.4 s per session, **about 2.5 hours per backtest run**; with T = 2,900, E = 1,500: 5.6 s, about 4 hours. Those are unmeasured on the real lake, which is larger, on another disk and not cache-hot; treat them as order of magnitude. K configurations multiply it. No shared change was made or is proposed here; if the cost matters later, a per-session cache or a bulk read in `AsOfView` would be a shared-code decision.

**Q6. `StrategySpec.expected_trade_rate`.** Optional positive number, unit **trades per month** (`strategies/spec.py`, field comment). The only code that touches it is `StrategySpec.__post_init__` (rejects zero, negatives, booleans, non-numbers) and `config_hash()` (it is part of the hash). Nothing else reads it: not the engine, not validation, not a power calculation, not a gate (searched all `.py`, `.yaml`, `.md` outside the reports). `smallest_edge_of_interest` (R per trade, net of costs) is in the same position. They are declarations for the pre-registration and the reviewer; changing either changes the spec hash.

**Q7. Pre-registration fields.** Listed, not filled. The old pre-registration is sealed: `stockbot/validation/ledger/records/pre_registered_configs.yaml` belongs to the rejected CFG-01..06 search, its sha256 is recorded in `trial_ledger.csv` and pinned by `tests/unit/test_ledger_yaml_hash.py`, so it cannot be edited for a new strategy. Two vehicles exist:

*(A) `StrategySpec` (`strategies/spec.py`):* `id` (lower-case name), `version`, `params` (the strategy's own numbers; no shared section allowed), `universe_overrides` (may only raise `min_adtv_cr`, `min_listing_age_trading_days`), `exit_policy` (id, required), `status` (`research`, `paper`, `live`), `prereg_ref` (reference to the pre-registration record), `validation_ref` (required for `live`), `expected_trade_rate` (trades per month), `smallest_edge_of_interest` (R per trade net of costs), `overlays` (id to version). `config_hash()` hashes all of them.

*(B) Ledger (`validation/ledger/__init__.py`, `validation/prereg_lock.py`):*
* family route, no yaml: `register_family(path, family_id, members=[specs], gate_params, git_sha, reason)` writes a `FAMILY_REGISTRATION` row: `timestamp_utc`, `commit_sha`, `family_id`, `members_json` (each member's id, version, `config_hash`), `budget` (= number of members, the count a multiplicity correction must use), `gates_sha256` (hash of `gate_params`), `reason`, chained by `prev_hash`/`row_hash`. `record_family_results(...)` must then cover exactly the registered members. `FAMILY_LEDGER` (`family_ledger.csv`) does not exist yet; the first call creates it.
* yaml route (what the old search used): `register(ledger, yaml_path, gate_params, candidate_ids, git_sha, reason)` writes a `REGISTRATION` row with `yaml_sha256`, `gates_sha256` and `budget` = number of candidate ids; `prereg_lock.enforce` refuses to run unless the chain, both hashes and the budget match. The old yaml shows what such a file holds: `metadata`, `definitions` (formulas, universe, tie rule, random baseline), `selection_criteria` (volume floors, significance tests, plateau rule, benchmark rule, official gates), `configs` (each with id, role, entry filters, execution), `selection_automation`.
* `gate_params`: the thresholds being registered. Today these are the shared `validation_gates` in `config/shared.yaml` (`max_drawdown_pct` 15.0, `min_alpha_after_tax_pct` -2.0, `min_expectancy_r` 0.15, `min_profit_factor` 1.3, `min_trades` 40, `ltcg_tax_pct`, `risk_free_pct`) and `paper_criteria` (`min_days` 90, `min_closed_trades` 60, ...). `docs/restructure/PRE_LIVE_LIST.md` item 2 says these are to be re-pre-registered with the first strategy (KI-002: 40 trades and a 0.15 R bar are not testable at about 2.6 trades a month); item 3 (12 positions and 15% risk versus the mandate's 10 and 10%) is also open. **The success bar is the owner's and the reviewer's to set; nothing was filled.** No code compares a run to these gates yet (`CODEBASE_GUIDE.md` section C.9).

**Q8. Does this rule need anything in the shared engine changed?** Read as "does the engine logic need a change to express the rule": **no.** Proposal with stop and rank, next-open fill, time exit, stop, corporate-action rescaling and journal round trip all work through existing interfaces. Read as "is anything in the shared tree an obstacle or a trap for this rule": **yes, five things, none changed** (details in section 4):

1. *Import rules block a production exit policy.* A `FixedHoldPolicy` must return `PolicyActions` and `MarketAtNextOpen` from `stockbot.engine.exit_policy` (stepping tests them with `isinstance`, so look-alikes will not do). `stockbot.strategies` may import only `data` (`boundaries.py::ALLOWED`), and engine, backtest, live and validation are not places a strategy-owned policy belongs. Either the policy lives in the shared `engine` package (a shared-code addition) or the boundary table gets an explicit, reviewed exception (for example strategy modules may import `stockbot.engine.exit_policy`). Also `tests/unit/test_no_strategy_in_the_tree.py` pins `stockbot/strategies` to exactly four files and forbids exit-policy classes outside the interface; it must be updated, on purpose, when the first strategy lands. These are decisions, not edits to make now.
2. *Sector cap and cash cap against 1% risk sizing with a 3 x ATR stop.* `risk/sizing.py` sizes shares as `equity x 1% / (entry - stop)`, so position value is `1% / (3 x ATR/close)` of equity: 16.7% of equity at ATR/close of 2%, 11% at 3%, 8% at 4%. `risk/caps.py::check_caps` blocks a position whose sector value would exceed 15% of equity, so any candidate with ATR/close below about 2.2% is blocked **by itself** (when it has a sector), and two or three positions in one sector are impossible. At fill time sizing is capped by cash (`fill_ticket` passes `cash`), so twelve positions each worth 8% to 17% of equity cannot all be funded: later fills get fewer shares (less than 1% risk), or `SIZE_ZERO`. The 15% total-risk cap, by contrast, cannot bind at 12 x 1% = 12%. The EXTRA tables x and xx quantify this from the real lake when the study is run.
3. *Unmapped symbols are one sector.* In live, `live/runner.py::SectorLookup` returns `"UNKNOWN"` for any symbol not in `data/reference/sector_map.csv` (501 rows), and `check_caps` treats `UNKNOWN` as a sector with the same 15% cap, so all unmapped names together are limited to about 15% of equity. A backtest uses whatever `EventData.sectors` its script supplies; a plain `{}` means `sector=None` and no sector cap at all. Backtest and live would differ unless the research script uses `SectorLookup`. How many selected names lack a sector is item f of the study.
4. *Number of proposals.* `decide` hands the strategy only `eligible`, not the held positions. If the strategy proposes only its top K and those are already held (`ALREADY_HELD`), free slots stay empty although lower-ranked candidates exist. Proposing every candidate avoids that, but then every session writes hundreds of `Blocked` records (`BLOCKED_BY_RISK` once the cap is full) into the decisions, the journal and the live ticket file. K is a parameter of the rule that the draft does not fix. The occupancy model assumes the full ranked list is available.
5. *Documentation mismatch, no effect:* the module docstring of `risk/arbitration.py` says each strategy's proposals are ordered by `(rank, symbol)`; the code in `admission_order` sorts `(-rank, symbol)` (higher rank first), and the tests rely on the code. `rank = score` gives the rule's order.

## 4. Findings that need a decision (and rule observations)

The rule's numbers were not changed and no variant was run. Where I think a number or a gap matters, I say so; none of this uses any outcome data.

1. **Where does the exit policy live?** (Q8.1.) Needs an owner/reviewer decision on the boundary table before implementation.
2. **Fix K, the number of proposals per session,** before registration (Q8.4). It changes the trade count and the size of the blocked list.
3. **3 x ATR stop + 1% risk + 15% sector cap + cash:** the combination probably leaves much of the 12-slot capacity unusable and shrinks risk per trade below 1% (Q8.2). I regard "3 x ATR" and "1% risk" as the numbers most likely to interact badly with the shared caps; the study's tables x and xx measure how badly. I have not varied them.
4. **"Stop = entry minus 3 x ATR(14)" cannot be anchored on the entry.** A strategy proposes at the signal close and `Proposal.stop` is a price; the fill is the next open (plus slippage) and is unknown at proposal time (`fill_ticket` uses the ticket's stop as given). The only possible implementation is `stop = reference_price - 3 x ATR(14)`, with `reference_price` the signal-day close. The distance from the fill to the stop then differs by the overnight gap. (`fill_ticket` skips the entry if the open is at or below that stop, or more than 3% above the signal close.)
5. **The rule has no guard for absences or gaps** (PRE_LIVE_LIST item 11). A name returning from a non-EQ spell, or with a stale window, gets a score from bars that span more calendar time. The 200-bar requirement drops names with a short history; gaps inside the window are only counted (h4 to h6). Decide whether the pre-registered rule needs a gap guard.
6. **Unadjusted events inside the windows** (Q4): demergers, mergers, rights and 259 unsupported split/bonus-like rows are not adjusted and distort scores. Consider asking for the residual-move count before registering.
7. **Pre-registration vehicle and bar** (Q7): family ledger or a new yaml; gates re-set; the 12/15% versus 10/10% question.
8. **First-date definition** (2.2): the tool reports both the first session with a valid score using pre-calendar bars and the 200th calendar session; the reviewer may want the second one if the pre-2015-11-09 rows are not trusted (the guide says those dates have no Nifty row and cannot be decided by the engine).
9. **Run the study on the real lake** (section 2.5) before registering anything; the whole point of the task (does the rule produce enough trades) is still unanswered.

## 5. Limitations, plainly

* No real-lake figure exists in this report (section 0).
* The occupancy model is mechanical and is neither a lower nor an upper bound on the real trade count (section 2.3).
* The fixture-lake tests prove the code is right on a constructed case and read no future price; they say nothing about the market.
* The timing numbers are from a synthetic lake in a different environment; the study's own run time on the real lake is an estimate.
* "Sessions" are the symbol's own bars (2.2). A calendar-aligned reading would give different windows for names with gaps.
* ASM/GSM surveillance exclusions are not applied (no history, KI-003); the market-cap gate is parked (KI-001); both are shared-universe facts and apply to any strategy.
* `finsight.db` was never opened, so no hash or mtime could be recorded (section 6).
* Adjustments cover only split and bonus; dividends are ignored (gross returns), as everywhere in the repository.
* The two failing G1 tests are not mine (section 6).

## 6. Tests, counts, and the database hash

Commands as given in the task. `finsight.db` is absent from the container (see 0.1).

| run | before my changes | after my changes |
|---|---|---|
| G1: `pytest tests/unit tests/integration -q` | **503 passed, 2 failed, 2 skipped** | **516 passed, 2 failed, 2 skipped** (+12 new tests, +1 `--help` case for the new wrapper) |
| import-boundary test (`test_import_boundaries.py`, `test_every_module_imports_alone.py`) | passed | passed |
| G2: `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests -q` | **cannot run**: 3 collection errors, `RuntimeError: STOCKBOT_DATA_TESTS=1 but the database .../finsight.db does not exist` (`tests/data_integrity/*`) | same. Not a pass. G2 is NOT satisfied by this session |
| G2 with `--ignore=tests/data_integrity` (everything else under `tests/`, env flags set, including the allowlist-empty check) | see the line below | see the line below |

G2 without the real-database modules: **517 passed, 3 failed, 0 skipped** (the two skipped G1 tests, including the allowlists-must-be-empty check, run and pass with the flags set). The 3 failures: the same two line-ending pins, and `tests/unit/test_guides_consistent.py::test_every_object_in_sqlite_master_is_described_in_the_data_guide`, which needs the real database. This is a partial run and does not replace G2.

The two G1 failures are identical before and after and are not caused by this work: `tests/unit/test_golden_files.py::test_every_golden_file_matches_its_recorded_sha256_and_nothing_is_unlisted` and `tests/unit/test_ledger_yaml_hash.py::test_the_exploratory_ledger_is_unchanged_and_has_no_chain`. Both pin the sha256 of a file as it is on the owner's Windows checkout (CRLF line endings; `git ls-files --eol` shows `i/lf w/lf` here). Checked: the exploratory ledger hashes to the pinned `090c1c17...` and `asof_120_samples.json` to the recorded `d59222bb...` once their line feeds are converted to CRLF; here they hash to `89518e6b...` and `1598c355...`. (Four tests failed on the first run in this container, two more because `yfinance` was not installed; installing it fixed those.)

**`finsight.db` sha256 / mtime: not recordable, the file does not exist in the container, so it could not have been changed.** The tool records them itself on every real run.

## 7. Commits

* `b945756`: BRIEF.md, study module, wrapper, fixture lake and tests, two guide rows.
* The commit that adds this report and `STATUS.md` follows it on the same branch (`git log` shows it as the head).

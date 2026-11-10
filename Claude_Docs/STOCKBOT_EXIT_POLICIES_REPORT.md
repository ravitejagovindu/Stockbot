# Exit policies library: STOP B report

Branch `exit-policies` (from `origin/master` ab6ae5b). Not merged. Written for a reviewer who has not seen the session.

## 0. Verdict and what is NOT verified
Built and tested **in a cloud container, not on the owner's machine**, as instructed. **`finsight.db` is absent here**, so:
- **G2 was NOT run and is NOT reported as passed.**
- **No sha256/mtime fingerprint of `finsight.db` exists** (before or after). The owner or a local session must run G2 and the fingerprint comparison before merge. Nothing in this work opens the database: the new code and tests use only the fixture lake (`open_lake` on temp files).
- `yfinance` was installed here (pip allowed it), which removed two of the four environmental failures from the STOP A baseline.

## 1. Counts (G1, G3, G5, G6 as run by `py scripts/check_all.py`)
| | before (STOP A, no yfinance) | before (yfinance installed, branch start) | after |
|---|---|---|---|
| G1 `tests/unit tests/integration` | 548 passed, 8 skipped, 4 failed | 550 passed, 8 skipped, 2 failed | **771 passed, 8 skipped, 2 failed** |
| G3 fixture baseline | 2 passed | 2 passed | **2 passed** (test file untouched; same 553-share trade) |
| G5 import boundaries | n/a | n/a | PASS (21 passed, 1 skipped; the skip is the `STOCKBOT_FINAL_CHECK` test) |
| G6 engine properties | n/a | n/a | PASS (72 passed) |
| G2 real database | not run | not run | **NOT RUN (no database)** |

The 2 remaining G1 failures are identical before and after and are not caused by this work: `test_golden_files::test_every_golden_file_matches_its_recorded_sha256_and_nothing_is_unlisted` and `test_ledger_yaml_hash::test_the_exploratory_ledger_is_unchanged_and_has_no_chain`. Both compare file hashes; in this checkout the files are LF (`git ls-files --eol`: `i/lf w/lf`). I suspect the recorded hashes were taken on a CRLF checkout (Windows) but did not verify that. The 4 failures at STOP A were these 2 plus the 2 `yfinance` ones (`test_every_module_imports_alone`, `test_script_wrappers_help[f2_index_gap_fill_yahoo.py]`), fixed by `pip install yfinance`.
G1 grew by 221 tests (550 -> 771 passed): 8 pending-exit, 20+ boundary/tree, and the rest the exit-policy files.

## 2. Commits (plain messages, no trailers)
| SHA | what |
|---|---|
| ba284c8 | brief saved as `docs/exit_policies/BRIEF.md` |
| aac4f4b | STOP A design note and STATUS |
| 2c7eac9 | **engine fix, own commit**: `_rescale` scales `pending_exit` (+ `tests/unit/test_engine_pending_exit_split.py`) |
| a4071c9 | boundaries: carve-out for `stockbot.engine.exit_policy`, `spec` excluded from strategy names (+ fixtures and tests) |
| 701a1dc | all exit-policy tests, written first, failing at import |
| a6be7e0 | the library and the two wiring edits |
| 1328855 | docs: EXIT_POLICIES.md, ARCHITECTURE.md row, guide md/json/html |

(The boundary commit carries both approved edits, because the test file changes for the two are interleaved; the message says so.)

## 3. What was added
- `stockbot/engine/exit_policies/`: `__init__.py` (5 lines), `fixed_hold.py` (35), `trailing_stop.py` (40), `registry.py` (72). Frozen dataclasses; `id` is a property computed from the parameter, so it cannot drift.
- `resolve(policy_id)`: anchored `fullmatch` on `fixed_hold_([1-9][0-9]*)` and `trailing_pct_([1-9][0-9]?)`, ASCII digits only (so `040`, `+5`, `4.0`, trailing newline, full-width digits, case changes are all rejected), percent 1..99, `UnknownExitPolicyError(ValueError)` with a message listing both formats. Constructors also validate (`type(x) is int`, so `True`/`2.0` are rejected).
- `policies_for(specs, extra=None)`: library ids through `resolve`, strategy-owned ids from `extra` (objects). Fails loudly (`ExitPolicyRegistrationError` / `UnknownExitPolicyError`, both `ValueError`) for: unknown id; two extras with one id (also when no spec uses it); an extra not implementing `ExitPolicy` or with an empty/non-string id; an extra id starting with `fixed_hold_` or `trailing_pct_` (approved A6; includes valid library ids). Keys equal `policy.id`. No `also=` (approved).
- Specs: FixedHold state `{}`; TrailingStop state `{"highest_close": float}` seeded from `position.entry_price`; `step` proposes a stop only when `candidate > position.live_stop` (strict), `on_corporate_action` multiplies `highest_close` by the factor.

### Files touched outside the new package (every one)
| file | change |
|---|---|
| `stockbot/engine/corporate.py` | **shared, approved**: new `_rescaled_pending`, one argument added to the `replace(...)` in `_rescale`; docstring sentence. +10/-1 lines of code. |
| `stockbot/backtest/runner.py` | import `policies_for`; `policies: Optional[Mapping]`; 2 lines: `if policies is None: policies = policies_for([s.spec for s in strategies])`. Callers passing a mapping are unchanged. |
| `stockbot/live/runner.py` | import; new `Book.from_strategies(strategies, overlays=None, extra_policies=None)` classmethod. `default_book()` and fields unchanged. |
| `tests/fixtures/boundaries.py` | `STRATEGY_ENGINE_ALLOWED = ("stockbot.engine.exit_policy",)` and its use in `check()`; `"spec"` added to both strategy-name exclusions. Nothing else relaxed. |
| `tests/unit/test_no_strategy_in_the_tree.py` | rewritten deliberately (see 5). |
| `tests/unit/test_import_boundaries.py` | new cases only. |
| `tests/fixtures/boundary_violations/` | 7 new fixture trees (and none changed). |
| `docs/ARCHITECTURE.md`, `docs/guides/CODEBASE_GUIDE.md`, `codebase_guide_data.json`, `codebase_guide.html` (rebuilt with `scripts/build_guide_html.py`) | minimal: modules, permission, Add-a-strategy view, `spec` wording. Existing guide tests pass unchanged. |
| `docs/exit_policies/{BRIEF,STATUS,EXIT_POLICIES}.md`, `Claude_Docs/STOCKBOT_EXIT_POLICIES_{DESIGN,REPORT}.md` | new. |
No strategy file was added to `stockbot/strategies/`. `Claude_Docs/CODEBASE_GUIDE.md` and `Claude_Docs/codebase_guide.html` (older copies of the guide) were **not** updated; they are stale copies (decision below).

## 4. The engine fix, exactly
`engine/corporate.py`:
```python
def _rescaled_pending(pos, factor, new_shares):
    if pos.pending_exit <= 0: return pos.pending_exit
    if pos.pending_exit >= pos.shares_remaining: return new_shares            # full exit stays full: exactly the new shares
    return min(new_shares, int(math.floor(pos.pending_exit / factor + 1e-9))) # partial: floored, capped
```
and `pending_exit=_rescaled_pending(pos, factor, n)` in `_rescale`. `pending_reason` is unchanged. Several same-day actions chain through the same function (each uses the previous result).
Tests (`test_engine_pending_exit_split.py`, 8): full exit under a 1:5 split (100 -> 500 shares, pending 500) and a 1:1 bonus (200), no leftover for an inexact bonus (101 shares, 2/3 factor: 151 and 151), a partial exit stays partial (40 -> 200 of 500; 51 -> 76), none stays none, and the whole position exits at the ex-date open through `step_position` (500 and 200 shares). **Failing before the fix: 7 failed, 1 passed** (the "none stays none" test passes either way). After: all pass; G3 and all existing engine tests unchanged and passing.

## 5. Boundaries and the tree test
- `check()`: `strategies -> engine` is permitted only when the dotted name equals or starts with `stockbot.engine.exit_policy.` (prefix includes the dot, so `exit_policies` is not matched). Rejected and tested: the library (`exit_policies.registry`, `exit_policies`), `engine.stepping`, `engine.types`, `engine.decide`, bare `from stockbot.engine import ...`, `import stockbot.engine.decide`, plus another strategy's real module, `stockbot.backtest`, `sqlite3`, `requests` from a strategy folder with an own-policy class.
- `spec` fix: before the change `test_a_strategy_may_import_the_shared_spec_module` **failed**; after, it passes. A folder merely named `specs` is still caught (fixture `strategy_imports_spec_lookalike`), as is `stockbot.strategies.beta.rules` (fixture `strategy_imports_other_strategy_module`).
- `test_no_strategy_in_the_tree.py`: exit-policy-shaped classes (`initial_state` + `on_corporate_action`) are allowed only in `stockbot/engine/exit_policies/<file>.py` and `stockbot/strategies/<name>/...`; strategy (`propose`) and overlay shapes are allowed nowhere; the expected hit list is exactly the 3 interface Protocols plus `FixedHold` and `TrailingStop`. New tests: no strategy folder or strategy/overlay class exists under `stockbot/strategies` today; the path rule on seeded snippets (allowed homes and 8 denied paths); a class that is both a strategy and a policy is forbidden even in an allowed home; a seeded policy inside a strategy folder is allowed by the path rule but its import of the library is caught by the boundary scan. Before the package existed this file's main test **failed** (expected hit list lacked the two policies).
- The AST scan remains `ast.walk` over `stockbot/` and `scripts/`. The library's own imports are pinned by a test (only `stockbot.engine.exit_policy`; the registry may import its siblings).

## 6. Tests required by the brief, and where they are
| required | file / tests |
|---|---|
| resolve(): valid, every malformed id, determinism | `test_exit_policy_registry.py` (6 valid, 52 malformed ids, 6 non-strings, 300+99 id round trips, constructor and immutability tests) |
| FixedHold: exit when days_held reaches N, executed next open; stop earlier; no-bar session; pending before stop; stop untouched | `test_exit_policy_fixed_hold.py` (hand bars and fixture-lake `decide`; the no-bar session uses a lake with FIXCO's row deleted: `NO_BAR_POSITION_NOT_STEPPED`, `days_held` 1,1,2,3; a pending exit waits through a missing bar) |
| TrailingStop: rises, never lowers, next bar only, gap down, entry bar, equals-current, stop above the close | `test_exit_policy_trailing_stop.py` (hand-derived prices, real `step_position`) |
| corporate actions: 1:5, 1:10, 1:1 bonus, unsupported -> HOLD, same trade with/without a split | `test_exit_policy_corporate.py` (3 factors x 10 policy/ex-date cases on bars, including the ex-date = exit session; the same on lakes with a real action row through `decide`; RIGHTS/MERGER/unparsable hold) |
| journal round trip with each policy | `test_exit_policy_journal.py` (Decisions JSON + `apply_decisions`; `StateStore.rebuild()` equals `load()` at every session; a pending exit seen in the stored state; split case) for `fixed_hold_3`, `trailing_pct_5`, a strategy-owned policy |
| determinism / idempotency | same file (byte-identical decisions, replay of one session) |
| isolation | `test_exit_policy_isolation.py` (two strategies, different policies and symbols = same results alone and together; each position keeps its policy id; a strategy cannot import another) |
| strategy-owned policy under tests/ + negative boundary test | `tests/fixtures/own_policy.py`; boundary scan of a real seeded tree passes, 10 forbidden imports fail |
| spec hash changes with the policy id | registry test |
| lookahead | isolation file (every bar after the as-of date x7 plus a future split; JSON identical) |
| policies_for | registry test (unknown, duplicate, library + owned, library-prefix ids, invalid extras, both wiring points) |
**Failing-before evidence:** all six new exit-policy files `ERROR ... ModuleNotFoundError: No module named 'stockbot.engine.exit_policies'` at collection (6 errors); the tree test, boundary tests and pending-exit tests as stated in 4 and 5. Mutation checks beyond that were not run.

## 7. Deviations and limitations (plain)
1. G2 and the `finsight.db` fingerprint not done (section 0).
2. The spec and carve-out boundary edits are in **one** commit, not two.
3. `Claude_Docs/` copies of the guide not updated; they were not part of the brief.
4. **Reference seed**: `highest_close` starts at the fill price (entry price incl. slippage), as confirmed. Consequence: a position that never closes above its fill price trails from the fill price, not from a close.
5. **N meaning**: entry session = session 1, exit at the open of session N+1; documented in EXIT_POLICIES.md.
6. **Closed-out strategy with open positions**: `policies_for` covers only the strategies it is given; `decide` then raises `EngineInputError` (loud). Tested (`test_a_position_whose_policy_is_missing...`) and documented. No `also=`.
7. Percent integer only (no 7.5); prices are floats, no tick rounding; a session without a bar is invisible to the policy and the next bar updates `highest_close` with its own close only.
8. `TrailingStop.step` tolerates a state without `highest_close` (falls back to the entry price) instead of raising; this exists only so an old journal cannot crash a live session. Tested. It is a mild departure from "state is exactly the schema".
9. `from stockbot.engine import exit_policy` (bare) is rejected by the scanner on purpose; the dotted form must be used. Stated in the docs.
10. The strategy-owned path rule cannot tell a real policy from any class with both `initial_state` and `on_corporate_action` inside a strategy folder. Accepted at STOP A.
11. Other `engine`/`risk`/... rules that read `stockbot.strategies.<x>` still list only `base`/`registry` (not `spec`); I changed only the strategy-folder rule as approved.
12. No backtest on real data, no returns, no P&L anywhere.

## 8. Momentum report (Part 2, Q1 to Q3, Q8) against this design
Read via `git show origin/claude/momentum-prereg-groundwork-z93w6m:...`; nothing merged or cherry-picked. **No contradiction.** Consistent: Q2 (`FixedHold` with `{}` state, `days_held >= N`, `MarketAtNextOpen`, exit at the open of session 21 for N=20, no-bar sessions not counted, pending exit waits), Q3 (journal/rebuild coverage), Q8 item 1 (the proposed boundary exception is exactly the one built). Not mentioned there and found here: the `pending_exit` split bug (fixed) and the `spec`-as-strategy boundary bug (fixed); Q8 item 1's note that the tree test pins the folder to four files is now reflected (new "no strategy folder" test).

## 9. Decisions needed
**Owner / reviewer, before merge**
1. Run G2 and the `finsight.db` sha256/mtime before-and-after check on the owner's machine (or a local session) and record them; the report cannot.
2. Re-run `check_all.py` there; the 2 hash-mismatch G1 failures should pass on a CRLF checkout if my suspicion is right. If they still fail, they are pre-existing and unrelated.
3. Approve the engine fix as committed (2c7eac9) and the one-commit boundaries edit.
4. Refresh or retire the stale guide copies in `Claude_Docs/`.
**For the later strategy task:** the first strategy needs `expected_trade_rate` etc.; none of that is touched here. Keep the strategy in the live book while it has open positions (limitation 6).

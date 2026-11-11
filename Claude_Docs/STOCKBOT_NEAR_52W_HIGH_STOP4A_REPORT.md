# near_52w_high: STOP 4A report (finalise; nothing registered; nothing run on real data)

Date: 2026-11-11. Branch `near-52w-high`. **Nothing was registered in any ledger. The backtest, the baselines and the tests were not run on real data.** No return, P&L, win rate or forward price change of this strategy exists. All new code was tested on synthetic data and fixture lakes only; `finsight.db` was opened only by the existing real-lake test suites (G2) and by nothing else.

## 1. Commits
| commit | what |
|---|---|
| **7b5b20b** | **The shared gate change, in its own commit:** `validation_gates.max_drawdown_pct` 15.0 to 20.0 in `stockbot/config/shared.yaml`. Plain message; the body explains that it applies to every strategy, that `paper_criteria.max_drawdown_pct` stays 12.0, and what tests and docs changed. |
| a9e9db7 | Tests first for the validation scripts. Its message says 36 fail; that was measured before I added one more test (the command-line test), so 37 fail at this commit (see section 4). |
| **45db2e4da31de4ceee0a9b84195584dbe1225c84** | **The finalisation commit:** the four scripts, the research script's two new outputs, `SPEC.prereg_ref`, the final `PREREGISTRATION.md`, the guides. This is the commit whose SHA goes into `register_family`. |
| (this report's commit) | The report and STATUS.md only. |
No trailer, signature or attribution in any commit message. Not merged.

## 2. The shared gate change (done FIRST, as ordered)
- `stockbot/config/shared.yaml`: `validation_gates.max_drawdown_pct: 20.0` (was 15.0), with a comment; `paper_criteria.max_drawdown_pct` is still 12.0. The file's "carried over UNCHANGED" header now names this one reviewed change.
- Tests: `tests/unit/test_shared_config.py` compared every shared value with the frozen legacy config. It now has an explicit `REVIEWED_CHANGES = {"validation_gates.max_drawdown_pct": (15.0, 20.0)}` (legacy value 15.0 stays frozen; current value must be 20.0) and a new test that this is the only reviewed change, that the paper gate is still 12.0 (equal to its legacy value), that 20.0 > 12.0, and that the old gates hash is no longer the shared one.
- Docs: `docs/restructure/CONFIG_KEYS.csv` (value 20.0 and the dated note), `CONFIG_DIFF.md` (row marked as a reviewed change), `UNDECIDED.md` (dated note on Q11).
- Not changed on purpose: `stockbot/validation/ledger/records/pre_registered_configs.yaml` and the legacy `scripts/provenance/select_candidate.py` (they pin the rejected CFG-01..06 family's own 15.0 gates; the yaml is hash-pinned), `tests/conftest.py`'s legacy fixture, `docs/archive/*`, and `backtest/outputs/*` (historical outputs).
- **Hashes.** Old shared `validation_gates` hash (15.0): `d70800991ed5e6550fe8a89c050e6b3f989ac99f2a2d6cfaa133761771ab9e64`. **New: `805efac844810c62d6f5d74b706d7cfb0b042c5fbc3cf217add54116d783cd2f`** (sha256 of the canonical JSON of the seven gate values via `prereg_lock.gates_hash`).

## 3. Final hashes
- **Spec config hash, with `prereg_ref` set: `359c8331091abf15f14cfaaf47f4fcf49f65835d876b6fb1ece56fa78287ab26`.** Before `prereg_ref` was set: `e157b0bb2bc0c7ca4853c4756473bc46be74b17bee85194a78eec40319ebd245`. No rule parameter changed; only `prereg_ref` (owner decision D1). A test checks that the pre-registration text states exactly `SPEC.config_hash()` and the current shared gates hash.
- **Shared validation_gates hash: `805efac8...cd2f`** (above).
- Data snapshot: `finsight.db` sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02 +0530.

## 4. Scripts (new), and how each was tested
All in `scripts/`; named in `docs/guides/CODEBASE_GUIDE.md`; none touches shared code. Tests: `tests/unit/test_near_52w_high_validation_scripts.py` (36 tests), fixtures `tests/fixtures/near_high_run_dir.py` (synthetic runs and baselines, no lake) and the existing series lake.
- **`benchmark_nifty_matched_near_52w_high.py` (B2).** Daily benchmark = s(t-1) x Nifty return + (1 - s(t-1)) x 6.5% / 252, s from the run's own cash and equity; constant-share variant; annualised alpha with the shared tax rate (0.0). Tests: a hand-worked example, s = 0 gives only the risk-free rate, s = 1 only the index, alpha formula, tax hook. Reads the `NIFTY50_INDEX` series only.
- **`evaluate_validation_gates_near_52w_high.py`.** Computes all five gates (min_trades, min_expectancy_r, min_profit_factor, max_drawdown_pct, min_alpha_after_tax_pct) from a run, prints each beside the gate value read from the shared config at run time (the drawdown row shows 20.0), with 95% circular block-bootstrap intervals (3-month blocks) and the descriptive sub-periods (values only, no pass or fail). `--t1` adds the registered conclusion. Tests: a good run meets all gates; **deliberately bad runs fail the relevant gate** (all-loss trades fail expectancy and profit factor; 39 trades fail min_trades; a 35% equity fall fails the 20.0 drawdown gate; a benchmark far ahead fails alpha), while the control gates still pass; END_OF_WINDOW and excluded trades are not counted; gate values come from the config (a custom value changes the verdict); deterministic for a fixed seed (only the intervals move with the seed); sub-periods carry no `met` or `pass`; **on a fixture lake the SQL touches only `NIFTY50_INDEX` and no date after the window end.**
- **`baseline_matched_random_near_52w_high.py` (B1).** 20 draws per usable trade through the unchanged `draw_matched_random` and `FixedHold(40)` (resolved from the spec's exit policy), seed 20261111, a pair needs at least 10 filled draws, more than 5% of pairs dropped is flagged. The shared helper's open-ended forward read is capped by a small `ForwardCappedView`, and the forward returns are then recomputed bounded to 20 sessions after entry and blanked across a split or bonus. Tests: same entry date, same relative stop (14% to 16%), the trade's own symbol excluded, library exit (all draws exit at session 41 with 40 sessions held), deterministic for a seed and different for another seed, short pairs dropped and counted, **no stock price read after the draws' exit** (SQL date check on a fixture lake whose window runs 10 sessions past the exit), the forward helper is bounded and blank across a split, a used output directory is never overwritten.
- **`validate_near_52w_high.py` (T1, T2, T3).** T1: monthly entry-month sums of paired differences (130 months, empty months 0), `WestfallYoungMaxTBootstrap`, K = 1, B = 10,000, alpha 0.05, seed 20261111, blocks 2 and 3, significant at both. T2: `paired_statistics`, reported only. T3: placebo size check on the B1 draws (1,000 replications), limits 0.025 and 0.075 ("size unreliable" is a label; nothing is recalibrated). Intervals and descriptive sub-periods. Tests: pairs use the mean of the draws and drop short pairs; the monthly series has the 130 registered months and zeros for empty months; T1 significant at both blocks for a strong synthetic edge and not for the null; the dual rule needs both blocks; T1 deterministic for a seed; the size-limit boundaries (0.0749, 0.075, 0.0751, 0.0249, 0.025, 0.0251, 0.0); the placebo is deterministic; the conclusion text is never "no edge"; **end to end with `sqlite3.connect` replaced by an error: the script opens no database** and its sub-period results are descriptive.
- **`research_near_52w_high.py` (existing, extended).** It now also writes `daily.json` (equity and cash at every close) and `blocked.json` (the shared caps' blocks), which B2 and the gates need. Its tests were updated first.

**Tests first, shown failing (honest account).** I wrote the tests before the scripts, but did not run them before writing the scripts. To show the failing state I afterwards moved the four scripts away and stashed the research-script and spec edits, and ran the three test files: **36 failed, 25 passed** (the failures are the missing scripts, the spec without `prereg_ref`, and the research script without `daily.json`; the 25 passes are the older tests and the final-text test, which passed already because I had finalised the document first). The scripts and edits were then restored. One CLI test (`test_the_command_lines_...`) was written after the scripts. Tests count: 36 in the new file, 3 research-script tests, 23 strategy tests.

## 5. The finalised PREREGISTRATION.md (what changed from the draft)
Header and a new section 0 (the approval record: "approved by the owner on 2026-11-11", who decided what: D1 to D7, the drawdown gate and the decision rule; owner and reviewer). Every PROPOSED number fixed as written (T1, T2, T3, the 0.075 and 0.025 limits, 20 draws, at least 10 filled, seed 20261111, B = 10,000, blocks 2 and 3, B2 with 6.5%). The new gates hash and the new spec hash. The drawdown gate at 20.0 with the paper 12.0 note ("a strategy that passes 20% in backtest can still fail 12% in paper"). The D2 wording in section 9, in plain words: **central-case power at 0.15 R about 61%; range 28% to 90% across the assumptions (sd_pair 1.2 to 1.5, DEFF 1 to 3, dual-block rule; 99% only in the most favourable corner of the full grid, sd_pair 0.9 with DEFF 1); a non-significant result is "not demonstrated" and never "no edge"; the power figures are replaced by observed dispersion and dependence only after the registered decision is made.** The note that the TEST/TUNE labels do not apply (D6). The D5 statement (the registration does not touch the exploratory ledger; section 12 is the record). The restart rule (D7). The limitations (section 11), including the five you listed and the 20% versus 12% drawdown note. The scripts' names and the order of operations at STOP 4B. No "PROPOSED" or "DRAFT" remains (a test checks).

## 6. The register_family call (do not run; STOP 4B)
```python
import dataclasses
from stockbot.config.shared import load_shared_config
from stockbot.strategies.near_52w_high import SPEC
from stockbot.validation.ledger import FAMILY_LEDGER, register_family

cfg = load_shared_config()
register_family(path=FAMILY_LEDGER, family_id="near_52w_high", members=[SPEC],
                gate_params=dataclasses.asdict(cfg.validation_gates),
                git_sha="45db2e4da31de4ceee0a9b84195584dbe1225c84")     # the finalisation commit
```
**The placeholder.** `PREREGISTRATION.md` shows `<PREREG_COMMIT_SHA>` because a file cannot contain the SHA of the commit that contains it. The value is the finalisation commit, `45db2e4da31de4ceee0a9b84195584dbe1225c84`, which holds the final text, the scripts and the spec with `prereg_ref`. Commits after it (this report) change only `Claude_Docs/` and `docs/strategies/near_52w_high/STATUS.md`; the reviewer can check with `git diff 45db2e4 HEAD --stat`. If any registered content changes, the SHA changes and the call must use the new one. The row will record that SHA, `near_52w_high`, `1.0.0`, the spec hash `359c8331...`, budget 1 and the gates hash `805efac8...`. Then `verify_ledger(FAMILY_LEDGER)` and `family_budget(FAMILY_LEDGER, "near_52w_high") == 1`.

## 7. Test counts and the database
| check | STOP 3 | after the gate commit (7b5b20b) | at the finalisation commit (45db2e4) |
|---|---|---|---|
| G1 `tests/unit tests/integration` | 819 passed, 8 skipped | 820 passed, 8 skipped | G1_FINAL |
| G3 `test_g3_fixture_baseline.py` | 2 passed | 2 passed | G3_FINAL |
| full folder, `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests` | 948 passed | 949 passed (1941 s) | G2_FINAL |
`finsight.db` before and after each run: sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, mtime 2026-11-08 12:38:02.892612 +0530, 3,432,767,488 bytes. FINAL_DB_NOTE

## 8. Deviations and things to know
1. **Drawdown comparison.** I implemented the gate as `observed <= 20.0` (the draft's wording). The archived pre-registration of the old family used a strict `<`. Say if you want strict.
2. **Research script extended after STOP 2 acceptance** (daily.json, blocked.json), because B2 and the gates need cash and equity at every close. No rule or config change; it is part of the finalisation commit and its test was updated first.
3. **Private import.** The gates and validate scripts import `_block_resample` from `stockbot.validation.max_t_bootstrap` (a private helper) for the circular block indices. No shared file was edited.
4. **B1 forward returns.** The shared `draw_matched_random` still computes its own forward returns; through `ForwardCappedView` they are bounded, and then my bounded, split-aware version overwrites them. T2 therefore uses raw closes with split-affected trades blanked and left out of T2 (they stay in T1). T2 is reported only.
5. **Unmeasured:** B1's per-path time (an estimate: 1.5 to 3 hours in total), the design effect and sd_pair behind the power figures, and the whole real-data behaviour of the new scripts (never run on real data).
6. **Not touched, still 15.0 in old provenance:** `pre_registered_configs.yaml`, `select_candidate.py`, archive documents.
7. T3 runs the T1 pipeline 2,000 times (two blocks, 1,000 replications) on a 130-month series; its cost was not measured on real data (fixture scale: seconds).
8. Hold on `paper_report.py`: it still reads the old paper tables (PRE_LIVE_LIST item 7); nothing here changes that.
9. Git rules followed: branch `near-52w-high`, no trailers, plain messages, not merged.

## 9. For the reviewer: owner decisions against the text
| decision | where it is in the final text | pinned by |
|---|---|---|
| D1 `prereg_ref`, new spec hash stated | sections 0, 2, 13 | `test_the_spec_names_its_preregistration_and_the_document_states_the_same_hashes` |
| D2 0.15 R stays; 61% and 28% to 90%; "not demonstrated"; replaced only after the decision | section 9 | `test_the_preregistration_is_final_and_carries_the_owner_decisions` |
| D3 T1, T2, T3 and the limits | sections 0, 8 | `test_t1_*`, `test_the_placebo_size_limits_*`, the dual-rule test |
| D4 B1 and B2, no full-engine replicates | sections 0, 7 | the baseline and benchmark tests |
| D5 exploratory ledger untouched; section 12 | sections 0, 12 | the final-text test |
| D6 TEST/TUNE note | sections 0, 3 | the final-text test |
| D7 detached run; restart rule | sections 0, 14 | no test (a statement of procedure) |
| Drawdown gate 20.0, paper 12.0 note, new gates hash | sections 0, 2, 10 | `test_the_only_reviewed_change_*` and the hash test |
| Decision rule as drafted, drawdown at 20 | sections 0, 10 | the conclusion-text test and the all-gates test |

## 10. Decisions needed
- **The reviewer** checks the final text against the owner's decisions (section 9 above).
- **The owner** then approves STOP 4B in writing: register with `45db2e4...`, run once (6 to 8 hours, detached), baselines, tests, gates, and report as measured.
- **Open question for you:** strict `<` or `<=` for the drawdown gate (deviation 1).

I have stopped here. STOP 4B starts only on written approval.

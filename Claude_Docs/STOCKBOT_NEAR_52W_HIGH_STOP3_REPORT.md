# near_52w_high: STOP 3 report (pre-registration package, draft)

Date: 2026-11-11. Branch `near-52w-high`. **Nothing was registered and no backtest was run.** No return, P&L, win rate or forward price change of this strategy was computed or looked at. The only calculation run was the power arithmetic (`docs/strategies/near_52w_high/power_calc.py`, standard library, reads no data). Every pass or fail number below is marked PROPOSED; none is decided.

The package is `docs/strategies/near_52w_high/PREREGISTRATION.md` (draft; 15 sections) with `power_calc.py` and its output `PREREGISTRATION_power_output.txt`. This report gives the answers to your four additions and the exact registration call, and lists the decisions needed.

## 1. What is in the draft
Exact rule and spec (hash `e157b0bb...ebd245`); the window (one run, 2016-01-01 to 2026-10-16, with the two descriptive sub-period reports 2016-2019 and 2020-2026 stated as never used to select, change or stop anything, and the TEST/TUNE labels stated as not applying); cost, slippage, execution and risk settings quoted from `shared.yaml`; the data snapshot id (`finsight.db` sha256 `dcade465...ceb752`, 3,432,767,488 bytes, mtime 2026-11-08 12:38:02 +0530, last session 2026-10-16); baselines; tests; power; gates; limitations; what was looked at before the draft; the registration call; the run-time plan.

## 2. (a) Power, with overlapping trades
- **Nominal trades:** about 786 (STOP 1 counts model, 6.17 a month, 2016 to 2026).
- **Effective sample:** a trade is open about 1.9 months and about 12 are open at once (mean 11.7, full on 85% of sessions), so each trade overlaps about two dozen others. In time: 130 monthly observations, about 68 non-overlapping hold-length blocks, or 43 blocks of the 3-month length I propose for T1. In trades: the nominal 786 divided by a design effect (DEFF) of 1 to 3, so **about 260 to 790 effective trades, central 390 (DEFF 2)**.
- **Method and assumptions:** normal approximation, one-sided alpha 0.05, SE = sd_pair / sqrt(n / DEFF), MDE at 80% power = (c + 0.842) x SE, where sd_pair is the SD of one trade's net R minus its matched random mean (assumed 0.9, 1.2 or 1.5 R; nothing measured) and DEFF is assumed. c = 1.645 for an ideal test; c = 2.2 is fitted to the F9 table for the monthly dual-block rule. These assumptions cannot be checked without looking at returns.
- **Result, central case (sd_pair 1.2, DEFF 2):** smallest edge detected at 80% power **0.18 R** with the dual-block rule (0.15 R for an ideal test); power at 0.15 R **61%** (80% for an ideal test); power at 0.20 R 87%. Favourable corner (sd 0.9, DEFF 2): 0.14 R, 87% at 0.15 R. Unfavourable corner (sd 1.5, DEFF 3): 0.28 R, 28% at 0.15 R. A cross-check scaling the F9 monthly result by the higher trade rate and longer window gives 0.13 R, but it assumes F9's shorter holds and ignores its liberal size (0.0625 to 0.063), so I treat it as optimistic.
- **Plain statement: 0.15 R is not reliably detectable.** It reaches 80% power only if the test is ideal and sd_pair <= 1.2 with DEFF <= 1.5. Under the central assumptions the detectable edge is about 0.18 R. To detect 0.15 R at 80% with sd_pair 1.2 and DEFF 2 takes about 790 nominal trades for an ideal test and about 1,180 for the dual rule (16 years at 74 trades a year). A non-significant result is not evidence of no edge (KI-002 still applies).
- **Your rule on smallest_edge_of_interest:** 0.15 R is confirmed only if the power numbers support it. They do not robustly. Options: keep 0.15 R as the economic threshold and register about 60% power there; or set 0.20 R (central power 87%). I did not change the spec (it still says 0.15).

## 3. (b) Baselines, exact matching, draws, runtime
- **B1, matched random through the same eligibility, exit and stop, matched to the strategy's occupancy.** `draw_matched_random`: for each actual trade, on the same signal session, **20 random draws** (seed 20261111) from the shared-eligible pool excluding the trade's own symbol, each with the actual trade's relative stop distance (about 15%) applied to the draw's signal close, simulated by `simulate_ticket` with `FixedHold(40)`: same next-open fill, slippage, gap rule, corporate-action rebasing, stepping and costs. A pair needs at least 10 filled draws (PROPOSED); drops are counted by reason. Occupancy is matched by construction: every draw has its actual trade's entry date, so the baseline has the strategy's own timing (and, apart from stops, the same 40-session window). The draws do not pass through the 12-slot, sector and cash caps.
- **B2, Nifty matched to the invested share.** Daily benchmark return = s(t-1) x Nifty return + (1 - s(t-1)) x 6.5% / 252, with s the strategy's invested share from the run itself (1 - cash_after / equity); the run's mean invested share is also reported. Price index on both sides, tax 0.
- **Why not full random portfolios.** Each would be one full backtest (4 to 5 hours; 100 replicates = 400 to 500 hours). **Cheaper valid design:** the trade-level pairing above, plus a monthly paired series by entry month tested with the block bootstrap. **What it gives up:** no caps for the random side, no random equity curve (so no drawdown or monthly-return comparison with random portfolios), attribution by entry month rather than accrual month. An optional 3 to 5 full-engine random replicates (12 to 25 hours) for drawdown and utilisation context only is listed as not proposed.
- **Runtime estimate (nothing run).** Strategy run 4 to 5 hours (at least 3.5; STOP 2 measured about 3.7 s eligibility and 1.1 s scoring per session). B1: eligibility per trade about 50 minutes plus 15,720 simulated paths at an unmeasured 0.15 to 0.5 s each (0.7 to 2.2 hours), so 1.5 to 3 hours. Tests, benchmark and gates: minutes. About 6 to 8 hours of wall time single-process, run detached. The path time is an estimate; measuring it on the real lake would read prices after the signal date, so I did not.
- **Tests (PROPOSED):** T1 primary: monthly paired series (130 months), `WestfallYoungMaxTBootstrap`, K = 1, B = 10,000, alpha 0.05, seed 20261111, blocks 2 and 3 months, significant at both. T2 secondary, reported only: `paired_statistics` (horizons 1, 5, 10, 20; clustered bootstrap; permutation). T3 placebo size check on the B1 draws (1,000 replications): if the empirical size is above 0.075 or below 0.025 T1 is labelled "size unreliable" and you decide; I do not recalibrate. 95% block-bootstrap intervals; trade count; occupancy and capital use seen; largest drawdown.

## 4. (c) Limitations to carry into the pre-registration (all in section 11 of the draft)
1. No historical ASM/GSM exclusion (KI-003; snapshots from 2026-11-08 only).
2. The UNKNOWN sector bucket: a quarter of picked symbols (75 of 302; a third under the first ordering) share one bucket that the 15% cap holds to two positions.
3. Unadjusted corporate actions (demerger, merger, rights, OTHER) inside the window: median about 13 valid names a session, no extra guard.
4. EQ-only lake gaps: the gap guard drops about 4% to 6% of eligible names in 2022 and 2024 to 2026; the lake keeps 934 symbols whose last bar is before the last session (cause not examined).
5. Cap-bound trade count: 6.17 a month comes from 12 slots and a 40-session hold; overlap makes the effective sample smaller than the nominal one.
Also recorded: price-only returns (no dividends) on both sides; the market-cap gate is parked (KI-001); the baseline has no portfolio effects; the power figures are assumption-based; F9 found the monthly dual rule liberal; the strategy and the study tool are two implementations of one rule; the run is slow and single-process.

## 5. (d) Gates: testable at this trade count? (KI-002), values as they exist today
`validation_gates`: **min_trades 40** testable as a count (about 790 nominal; only a floor); **min_expectancy_r 0.15** testable only as a point estimate (SE about 0.05 to 0.08 R; a 95% lower bound above 0.15 needs a true value of about 0.23 to 0.28 R); **min_profit_factor 1.3** point estimate only, no sampling distribution defined; **max_drawdown_pct 15.0** computable, one path, no test; **min_alpha_after_tax_pct -2.0** computable but not testable (alpha's sampling error is of the order of 4 percentage points on my assumptions); **ltcg_tax_pct 0.0** and **risk_free_pct 6.5** are inputs. `paper_criteria`: **min_days 90** and **min_closed_trades 60** are counts (60 trades takes about 9.7 months at 6.2 a month, so it sets the length); **max_expectancy_gap_r 0.25** weak (noise alone breaches it about one time in four at 60 trades); **max_win_rate_gap_pts 12** weak (about 1.9 SE); **min_profit_factor 1.2** very noisy at 60 trades; **max_drawdown_pct 12.0** computable, one path; **max_skipped_ticket_rate 0.40** an operational count. No code evaluates `validation_gates` today: a new, clearly named script is proposed (`scripts/evaluate_validation_gates_near_52w_high.py`, committed with fixture-lake tests before registration). The PROPOSED decision rule is T1 significant at both block lengths and every gate met on its point estimate; anything else is "not demonstrated", never "no edge".

## 6. Family route: the exact call (do not run)
```python
import dataclasses
from stockbot.config.shared import load_shared_config
from stockbot.strategies.near_52w_high import SPEC          # the spec as committed in the registration commit
from stockbot.validation.ledger import FAMILY_LEDGER, register_family

cfg = load_shared_config()
register_family(path=FAMILY_LEDGER, family_id="near_52w_high", members=[SPEC],
                gate_params=dataclasses.asdict(cfg.validation_gates), git_sha="<PREREG_COMMIT_SHA>")
```
Then `stockbot.validation.prereg_lock.verify_ledger(FAMILY_LEDGER)` and `family_budget(FAMILY_LEDGER, "near_52w_high") == 1`; after the run `record_family_results(...)`. One member, budget 1, no multiplicity correction (honest: one configuration). It uses the ledger path built for strategies and leaves the old CFG-01..06 trial ledger and its chain untouched. The shared-gates hash it will record is `d70800991ed5e6550fe8a89c050e6b3f989ac99f2a2d6cfaa133761771ab9e64`. **Note on the hash:** the spec's `config_hash` covers `prereg_ref`; if `prereg_ref` is set in the registration commit (PROPOSED) the hash changes from `e157b0bb...` to `359c8331...ab26` and the registered hash must be that one.

## 7. Tests and database
| check | STOP 2 | STOP 3 |
|---|---|---|
| G1 | 819 passed, 8 skipped | **819 passed, 8 skipped** (368 s) |
| G3 | 2 passed | **2 passed** |
| full folder, `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests` | 948 passed | **948 passed, 0 failed, 0 skipped** (3218 s; not killed, not timed out) |

finsight.db sha256, mtime and size before STOP 3: dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752, 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes; after the runs: identical (sha256, mtime and size re-read).

## 8. Deviations and limitations of this STOP
- The power numbers are assumption-based; the only measured evidence is F9 (random entries, 2.6 trades a month, shorter holds). They will be replaced by the observed dispersion and dependence at STOP 4, which I will not look at before.
- B1's path time is an estimate (not measured, to avoid looking at post-signal prices).
- The pre-registered statistic T1 (entry-month sums, 2 and 3 month blocks, K = 1) is not the statistic F9 simulated (accrual-period portfolio returns), so F9's size and power are guides only; T3 exists to measure the size on this strategy's own structure. If you prefer the accrual-period statistic it needs daily paths from the engine, which `simulate_ticket` does not return; that would be new code.
- Registration is not done; `prereg_ref` is still empty and the spec is unchanged since STOP 2.
- Git rules followed: no trailers, branch `near-52w-high`, not merged.

## 9. Decisions needed from the owner and reviewer
- **D1.** Set `prereg_ref` in the spec in the registration commit (changes the config hash to `359c8331...`), or leave it empty and rely on the ledger's commit SHA?
- **D2.** Smallest edge of interest: keep 0.15 R (about 60% power, central case) or 0.20 R (87%)? Or accept the detectable edge of about 0.18 R as the stated limit.
- **D3.** Primary statistic T1 (entry-month sums, blocks 2 and 3 months, K = 1), the placebo thresholds 0.075 and 0.025, and "size unreliable" handling.
- **D4.** Baseline design (B1 at 20 draws per trade, 10-draw minimum, seed 20261111; B2 with the daily invested share) and whether to add the optional full-engine reference runs.
- **D5.** Record the counts-only studies in the exploratory ledger (`record_exploratory`)?
- **D6.** Confirm the PROPOSED decision rule (section 10 of the draft) and every number marked PROPOSED.
- **D7.** Whether to proceed to STOP 4 at about 6 to 8 hours of run time, run detached.

I have stopped here. STOP 4 starts only when you approve the pre-registration in writing.

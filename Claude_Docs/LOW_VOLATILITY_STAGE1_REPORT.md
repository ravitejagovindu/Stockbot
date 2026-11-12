# low_volatility: stage 1 report

Branch `low_volatility` (from origin/master 055c703). Written 2026-11-12. Counts only: no return, P&L, win rate or forward price change was computed or looked at. Nothing was registered. No backtest ran.

## 1. Result first (the sector cap and the hold, plainly)
- **Signals:** 130 monthly signals, 2016-01-01 to 2026-10-01 (12 a year, 10 in 2026 so far). The top 25 is always full (25 proposed at every signal).
- **The 15% sector cap holds this rule to one position per sector.** At 1% risk and a 10% stop a position is 10% of equity (`size_position`, checked at ticket time on the signal close); a second name in a sector would be 20% > 15%, so it is blocked. Cap 12 positions and the 15% total-risk cap are never the binding limits.
- **The top 25 sits in a median of 9 distinct sectors** (p5 7, p95 10.5, min 6, max 12) of 14 mapped sectors plus UNKNOWN. So **a median of 16 of the 25 proposals (min 13, max 19) cannot be held**; the model blocks a median of 17 per signal once held names are counted (mean 16.4). With every slot free, **9 positions fit (median; p5 7, p95 10.5, range 6 to 12)**.
- **Sector concentration of the top 25** (all 3,250 name-sessions): CONSUMER 26.5%, FINANCIALS 15.0%, HEALTHCARE 12.2%, ENERGY 10.3%, AUTO 9.4%, IT 8.0%, METALS 5.0%, UNKNOWN 4.2%, CHEMICALS 3.8%, TELECOM 1.7%, REALTY 1.4%, INDUSTRIALS 1.3%, SERVICES 1.0%, TEXTILES 0.3%. (The sector map has no "FMCG", "pharma" or "utilities" label: they sit in CONSUMER, HEALTHCARE and ENERGY; the four largest sectors hold 64%.) In a median signal the largest single sector has 7 of the 25 names (max 12).
- **What the strategy under test therefore is:** the best-ranked low-volatility name in each sector of the top 25, not the 25 lowest-volatility names. **I did not change the rule to work around it.**
- **A second effect the cap does not cause: the hold is shorter than a month.** `fixed_hold_21` exits at the open of session 22; a calendar month has 17 to 23 sessions (median 21; 17: 1, 18: 4, 19: 21, 20: 30, 21: 39, 22: 26, 23: 8). In **95 of 129 intervals (74%) the previous cohort is still open at the next signal close**: its sectors and symbols are taken, so that signal buys little. Modelled entries per signal: **mean 5.4, median 7, p5 0.45, range 0 to 11; 7 signals buy nothing**; 3.96 on average when positions are still open (91 signals), 8.64 when none are (39). Positions held right after a signal's entries: median 9, mean 9.5, range 7 to 12.
- **expected_trade_rate: 5.4 per month** (697 modelled entries in 130 months; 68, 64, 62, 54, 70, 59, 64, 68, 68, 67, 53 in 2016 to 2026). Model limits below. Not written into the spec (owner's decision).

Does the count make the rule unworkable? It trades 5.4 a month and the engine will accept it, so I did not stop for that reason, but the label and the behaviour differ (above). **Decisions 1 and 2 in section 7 are the owner's.**

## 2. What ran
| item | result |
|---|---|
| `scripts/signal_count_low_volatility.py` over 2016-01-01 to 2026-10-16 (130 signal sessions) | ran once, then ran again in full after a diagnostic fix (see section 6); 4,636 s; read-only through `open_lake` and `AsOfView` |
| finsight.db before and after | sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` both times; size 3,432,767,488; mtime 2026-11-08 12:38:02.892612 +0530 both times; `unchanged: true` |
| strategy tests `tests/unit/test_low_volatility_strategy.py` | 23 passed (fixture lakes only) |
| G1, G2, G3 | section 5 |
| finsight.db after all tests (G4) | sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, size 3,432,767,488, mtime 2026-11-08 12:38:02.892612300 +0530: unchanged |

## 3. Counts (all measured 2026-11-12 on the snapshot above; per signal session unless said)
| measure | median | p5 | p95 | min | max |
|---|---|---|---|---|---|
| eligible names (shared rule) | 274.5 | 146 | 580 | 125 | 635 |
| valid (252 own bars, a bar on the date, finite prices) | 274.5 | 146 | 580 | 123 | 635 |
| proposed (top 25) | 25 | 25 | 25 | 25 | 25 |
| distinct sectors in the top 25 | 9 | 7 | 10.5 | 6 | 12 |
| names in the largest sector of the 25 | 7 | 5 | 10.5 | 4 | 12 |
| UNKNOWN-sector names in the top 25 | 1 | 0 | 3 | 0 | 5 |
| proposals blocked by the sector cap alone (25 minus distinct sectors) | 16 | 14.5 | 18 | 13 | 19 |
| proposals blocked in the occupancy model (cap, held, no slot) | sector 17, held 1, no slot 0 | | | | |
| positions open at the signal close, before entries | 2 | 0 | 9 | 0 | 11 |
| entries per signal | 7 | 0.45 | 9.55 | 0 | 11 |
| vol60 of the top-25 median name (daily log-return SD) | 0.0127 | 0.0099 | 0.0166 | 0.0091 | 0.0328 |
| vol60 of the median eligible name | 0.0218 | 0.0185 | 0.0270 | 0.0175 | 0.0461 |

Data-quality counts: names short of 252 bars (median 0, max 3); names with no bar on the signal date: 0; non-finite or non-positive prices: 0; **names with zero volatility: 0 at every signal**; names with a missing calendar session inside the 61-close window: median 1 (max 16), **1 such name in any top 25 over all 130 signals** (so the rule's lack of a gap guard has not mattered); exact vol60 ties were not counted separately (the ADTV then symbol tie-break is in the code and tested, but no zero-volatility group exists to create one). Eligible names per signal, median by year: 146 (2016), 198 (2017), 214 (2018), 186 (2019), 188 (2020), 304 (2021), 302 (2022), 372 (2023), 514 (2024), 494 (2025), 576 (2026).

Concentration in the occupancy model (697 entries): 136 distinct symbols; largest PIDILITIND 38 (5.5%), HDFCBANK 37 (5.3%), LT 29 (4.2%), BHARTIARTL 25, MRF 22; top 10 = 34%. UNKNOWN-sector entries 53 (7.6%). Entries by sector: CONSUMER 73, ENERGY 71, FINANCIALS 70, AUTO 69, HEALTHCARE 66, CHEMICALS 62, IT 60, UNKNOWN 53, METALS 52, TELECOM 34, REALTY 31, INDUSTRIALS 24, SERVICES 23, TEXTILES 8, DIVERSIFIED 1 (the cap flattens the sector mix).

Runtime: shared eligibility 23 s and scoring 12.6 s per signal session on average (max 103 s and 423 s on a cold cache); the whole study 77 minutes with other work running.

## 4. The occupancy model and its limits
Signal at the close of session j, entry at the open of j+1 (session 1), market exit executed at the open of session 22, a position still open at the signal close keeps its slot and its sector, a symbol already held is skipped, sector value after the trade above 15% of equity blocks a candidate (position = 1% / 10% = 10% of equity; unmapped symbols share UNKNOWN, as live), 12 positions. **It ignores stops (which free slots earlier and would raise the count), the 15% total-risk cap, costs, the 3% gap-up cap and cash (which remove entries), and missing bars; a fill that gaps changes the realised size (the engine re-sizes at the fill) while the cap is checked at ticket time on the signal-close size.** None of the directions is bounded by this report, because bounding them needs forward prices, which were not read.

## 5. Tests (full results)
- **G1** `py -m pytest tests/unit tests/integration -q`: **902 passed, 8 skipped, 1 failed** in 2,485 s. The failure is `tests/unit/test_near_52w_high_strategy.py::test_the_strategy_package_imports_only_what_a_strategy_may_import`: its last line asserts that `stockbot/strategies/` holds no folder other than `near_52w_high`; `low_volatility` exists, so it fails. It is a stale assertion from before the allow-list (`fcd88b3`) and will fail on every strategy branch and on master after a merge. It is not in a file I may edit (another strategy's test; the allow-list change left it). The identical assertion passes with the folder absent. Suggested fix for the owner: replace that line with a check against `APPROVED_STRATEGY_IDS` (`unlisted_strategy_folders`).
- **G2 (whole folder, `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1`, real database read-only):** **1,031 passed, 1 failed, 0 skipped** in 3,398 s (56 min; the whole folder includes G1 and G5/G6). The one failure is the same stale near_52w_high test as in G1; nothing else failed. The real-database tests (`tests/data_integrity`) all passed, and the database is unchanged afterwards (hash below).
- **G3** (`tests/unit/test_g3_fixture_baseline.py`): **2 passed** (run alone, and inside the full folder).
- Before this branch (`family-prep` report): G1 880 passed / 8 skipped; full G2 1,009 passed; G3 2 passed.

## 6. Deviations, mistakes and limits (plainly)
1. **A diagnostic bug found and fixed.** The first run flagged 129 and 142 names as having window gaps in January and February 2016, because the Nifty calendar starts on 2015-11-09 and holds fewer than 61 sessions then; the counter compared against 61 sessions. It affected only that diagnostic (never the ranking or the entries). Fixed in the strategy (`0a55aed`, with a test) and the **full study was re-run**; the new JSON is the committed one, and every other count is identical to the first run.
2. **Git incident.** The main working tree is shared with another session (`short_term_reversal`). That session switched the tree's branch while my first commit was the HEAD, so my first two commits ended up on its branch. I moved my work to its own worktree (`F:\Projects\Ravi\StockBot_wt_lowvol`, branch `low_volatility`, cherry-picked clean) and did not touch the other branch, which still holds my two commits (7f9efb0, 72ab050). Its owner needs to rebuild it from origin/master with only its own commit. Nothing was pushed from the shared tree.
3. "Block 1" was not in my session; the pre-registration follows `near_52w_high` and `FAMILY.md`. The strategy, its tests and the counts script are in this stage because `FAMILY.md` puts them in stage 1; there is no research wiring script, no B1/B2 script and no gate script for this id yet (stage 2).
4. The study tool lives in `scripts/` under a strategy-owned name, not in `stockbot/data_checks/` as the near_52w_high study did, so that no guide changes (I may not edit the guides). The strategy and the study are one implementation (the study calls `LowVolatilityStrategy.score`), unlike near_52w_high's two implementations tied by a test.
5. Not run: any backtest, the matched-random baseline, any validation test, registration. `expected_trade_rate` and `smallest_edge_of_interest` are not set in the spec; the spec hash is `399ac830d3335b992a400361c2464b4af9de966164dafcce366ae62be69e2c76` today and will change.
6. vol60 uses the sample standard deviation (ddof = 1); this cannot change the ranking. "min_bars 252" was read as 252 own adjusted bars and a bar on the signal date; no 250-of-252 gap guard like near_52w_high's (the rule does not state one).

## 7. Decisions needed from the owner and reviewer
1. **Sector cap:** is "the best-ranked low-volatility name per sector within the top 25 (about 9 positions)" the strategy to register? Not worked around.
2. **Hold against month length:** 74% of signals meet the previous cohort still open (`fixed_hold_21` against 17 to 23 session months); modelled entries 5.4 a month, 7 signals with none. Accept, or decide otherwise. Not worked around.
3. **expected_trade_rate:** 5.4 a month (set in the spec, or another figure).
4. **smallest_edge_of_interest:** yours to supply (power table in the pre-registration: 80% power needs about 0.20 to 0.24 R for one strategy and 0.23 to 0.29 R in the K = 4 family at design effect 2 to 3, sd 1.2).
5. Family membership (`FAMILY.md` assumes four of the five allow-listed ids) and the window.
6. Fix or waive the stale near_52w_high test (section 5), and tell the owner of `short_term_reversal` about the two stray commits.
7. Approval to start stage 2 (research script, baselines, gates) only after the family registration is agreed.

## 8. Files
`stockbot/strategies/low_volatility/{__init__,strategy}.py`; `tests/unit/test_low_volatility_strategy.py`; `scripts/signal_count_low_volatility.py`; `docs/strategies/low_volatility/{BRIEF,STATUS,PREREGISTRATION}.md`, `power_calc.py`, `PREREGISTRATION_power_output.txt`; `Claude_Docs/LOW_VOLATILITY_SIGNAL_COUNTS.json` (per-signal rows included), this report. Commits: 00215ae, 0a55aed, 8062271 and the report commit. No shared file was edited.

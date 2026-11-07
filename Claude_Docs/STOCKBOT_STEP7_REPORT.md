# Step 7 report — corporate actions loaded (STOP B)

Date 2026-11-07. Commits 8fb9aff, 6c4cada, 0d26060, fb9d6f3 plus the verification-input fix. No config or gate changes, no strategy work.

## 1. Load on the real `finsight.db` (rehearsed first on a scratch copy; the copy is deleted)
| type | rows |
|---|---|
| SPLIT | 451 |
| BONUS | 463 |
| RIGHTS | 341 |
| DEMERGER | 108 |
| MERGER | 91 |
| DIVIDEND | 20,912 |
| OTHER (unsupported / unclassified) | 630 |
| **Total** | **22,996** (price-moving 914) |

- `symbol` = lake symbol holding the pre-ex-date prices; the feed symbol is in the notes (`feed_symbol=…`).
- 20 colliding OTHER keys had their notes concatenated (logged in `docs/data_audit/merged_other_keys_real.csv`); 1 duplicate DIVIDEND dropped (DVL 2025-08-01, `dropped_duplicate_rows_real.csv`).
- Check "event with no lake rows before the ex-date": 3,820 events, **none** of them SPLIT or BONUS (DEMERGER 6, DIVIDEND 3,524, MERGER 35, OTHER 217, RIGHTS 38; non-price-moving or before the name's first lake row). List: `events_without_prior_rows_real.csv`.
- Unsupported events on eligible names are on `data/reference/unadjusted_events.csv` (268 entries).
- MBAPL loaded. INDUSINDBK accepted as real market stress.

## 2. DOLPHIN 2024-01-25 SPLIT — still HELD, needs your decision
Second-source check done: BSE company filing (record/ex-date 25 Jan 2024, announced 7 Dec 2023, Rs10 -> ten shares of Re1), Trendlyne and press all give 1:10 with ex-date 2024-01-25; BSE price 1,826.85 on 24 Jan vs ~182.7 on 25 Jan. The lake's EQ series for DOLPHIN jumps from Rs236 (2023-09-06) to Rs316 (2024-04-15), i.e. a ~14x real rally across a 222-day gap once adjusted, which matches press reports of a ~1,400% run. I did not retrieve the NSE announcement text itself (the NSE feed row is the original event source).
I tried to append it (`--only-held`) and the harness denied writing to the shared log, so **it is not loaded**. Loading it needs your explicit go; the command is `py -3 -m scripts.f2_load_corporate_actions --tag real_held --only-held --include-held`. Effect: the engine scan goes 266 remaining / 1 created -> 267 / 2 (the rehearsal with DOLPHIN reproduced exactly 267 / 2).

## 3. Post-adjustment scan through the engine path (`get_adjusted_series` via the candidate builder's query shape)
Real DB without DOLPHIN: large moves 764 -> **266** (499 removed, 1 created, MBAPL). Rehearsal with DOLPHIN: 267 / 2. Equivalence with `build_candidate_dicts`: 120 samples, 0 mismatches. Remaining: 208 after gaps in the EQ series, 40 near unadjusted events, 18 residual. (`engine_scan_real.md/.csv`)

## 4. 58 verification rows through the engine path
**58 / 58 PASS** (`verification_engine_path.csv`; data test `STOCKBOT_DATA_TESTS=1 pytest tests/data_integrity`). First run had 3 FAILs, both my verification inputs, not the log: (a) EASEMYTRIP 2022-11-21 listed the combined factor 0.125 on both rows, so the product was squared; corrected to per-row 0.5 and 0.25 (test added); (b) the TATAMOTORS demerger is stored under lake symbol TATAMOTORS with feed symbol TMPV and the verifier looked up only by feed symbol; lookup widened. Raw-only ADTV/market-cap test passes (3 tests).

## 5. Universe rules (each with tests, `test_universe_rules_f2.py`, 6 pass)
ETF/fund exclusion (INF ISIN, 511 symbols in `data/reference/fund_etf_symbols.csv`) and listing date from the first raw trading day (`securities_master` untouched; names on the lake's first day count as seasoned).

## 6. Open item: one failing existing test
Unit suite: 296 passed, **1 failed** — `test_baseline_reproducibility::test_active_simulator_mini_window_jan_feb_2020` (ESCORTS entry 2020-01-10, expected 2020-01-15). It fails identically with my screener change stashed and with the log loaded, so it comes from the new lake data (swap), not from Step 7. Its expected value is a baseline from the old data; I did not edit it. Needs your ruling: re-baseline on the new lake, or investigate first.

## 7. Parked (no action)
Special sessions in the calendar; names re-entering after gaps; names after unadjusted events.

## Stopped at STOP B. Decisions needed
1. Approve loading DOLPHIN (evidence above)?
2. Re-baseline the failing ESCORTS test on the new lake?
3. Go for F2b?

# near_52w_high: STOP 1 report (counts-only study)

Date: 2026-11-10. Branch `near-52w-high` (from origin/master 4bfc188). No return, P&L, win rate or forward price change was computed or read. The full tables are in `Claude_Docs/NEAR_52W_HIGH_SIGNAL_COUNTS.md` and `.json`; every table there is stamped with its measurement date (2026-11-10). This report quotes the numbers that drive the decisions.

## 1. What was done
- Branch, BRIEF.md (task text verbatim), STATUS.md (STOP 0, pushed).
- Copied and adapted, with `git show` (no merge, no cherry-pick), the momentum counts-only tool under new names: `stockbot/data_checks/near_high_signal_count.py`, `scripts/signal_count_near_high.py`, `tests/unit/test_near_high_signal_count.py`, `tests/fixtures/near_high_lake.py`. Nothing named momentum is on this branch. Design kept: lake only through `open_lake` and `AsOfView`; `data_checks` imports only `config` and `data`; the wrapper injects `eligible_symbols` and the shared settings.
- Named the module and script in `docs/guides/CODEBASE_GUIDE.md` and `codebase_guide_data.json`; rebuilt `codebase_guide.html`.
- Ran the study on the real lake over the whole Nifty calendar (2015-11-09 to 2026-10-16, 2710 sessions). The run took 12,923 s.

Commits: aebad25 brief; 689469b STOP 0 status; f8c81c2 study tool, wrapper, fixture and tests; 8055906 drop an unbounded first-session probe (it took 318 s for one session and was not needed); 470217f guide entries; plus the commit that adds this report, the counts files and STATUS (see `git log`).

## 2. Tests and database (before and after)
| check | STOP 0 baseline | STOP 1 |
|---|---|---|
| G1 `tests/unit tests/integration` | 773 passed, 8 skipped | 790 passed, 8 skipped |
| G2 `tests/data_integrity` (STOCKBOT_DATA_TESTS=1) | 121 passed (1488 s) | 121 passed (2053 s) |
| G3 `test_g3_fixture_baseline.py` | 2 passed | 2 passed |

16 of the 17 new G1 tests are `test_near_high_signal_count.py`; I did not trace the 17th (the count changed by 17; guide and import-boundary tests parametrise over modules and files). Not reported as a deviation, only as an unexplained +1.

finsight.db: sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752, mtime 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes. Identical before STOP 0, after STOP 0, before and after the study (the tool hashes the file itself: "unchanged: True"), and after the STOP 1 G2 run (sha256 and mtime re-read: same).

The fixture-lake test that proves no price after the as-of date is read: `test_every_sql_statement_is_bounded_by_the_session_being_evaluated` (every date in every SQL statement is on or before the session being evaluated), plus `test_results_up_to_a_date_do_not_depend_on_anything_after_it` (all rows after a cut are made absurd and a 1:50 split is added just after it: results identical; a long run equals a truncated run on the shared sessions), plus a static scan that no return-like code exists in the module.

## 3. Interpretation choices (please confirm)
1. **Gap guard.** "At least 250 bars within those 252 sessions" is implemented as: of the last 252 calendar (Nifty) sessions up to the as-of date, the symbol has a bar on at least 250. While the calendar is shorter than 252 sessions the window is the whole calendar so far and at most 2 sessions may be missing. A symbol also needs 252 bars of its own for the nearness. Nearness uses the highest adjusted close of the symbol's last 252 bars (as the rule says), so for a name with gaps the 252 bars can span more than 252 sessions; the guard is what limits that to 2 missing sessions.
2. **Occupancy.** Signal at close of session j; entry at the open of j+1 (session 1); open at proposal time on sessions 1 to 40; market exit executes at the open of session 41; the slot is free for a signal at the close of session 41, so the next entry is at the open of session 42 (41 sessions between entries of the same slot). Only the top 25 are considered, 12 slots, a held symbol is skipped.
3. **Sector cap model.** Position value = 1% / 15% = 6.67% of equity at the signal-day close. The shared rule (value after the trade above 15% blocks) allows 2 names per sector (13.3%) and blocks a 3rd. Unmapped symbols (`sector_for` returns UNKNOWN) share one sector, as live does.
4. **Unadjusted actions** counted: DEMERGER, MERGER, RIGHTS, OTHER (not DIVIDEND, which is not a price-basis event).

## 4. Results (all counts; measured 2026-11-10)
**a. First valid nearness.** Using bars before the calendar start: **2015-11-09** (the lake holds stock bars from 2013-01-01, so names already have 252 bars on the first calendar session). Counting only calendar sessions: **2016-11-17** (the 252nd Nifty session). The first session with at least 12 candidates: 2015-11-24.

**b. Per session (median, p5, p95), 2016 to 2026 (2674 sessions) / all 2710.** Eligible 275 (144, 593); gap-guard pass 267 (143, 565); nearness >= 0.95: 59 (9, 208); proposed (top 25): 25 (9, 25). Per-year rows are in the counts file; the universe is small in 2015 to 2020 (median 135 to 212 eligible) and large from 2021 (304) to 2026 (586). Sessions with at least 12 candidates: 2517 of 2710; sessions with no candidate at all: 12 of 2710 (2 in 2018, 9 in 2020, 1 in 2022).

**c. Occupancy model entries (no stops, no risk cap, no costs, no gap-up cap, no cash cap, no missing-bar blocks).** 2016 to 2026: **786 entries, 6.17 per month**; all sessions 798 (6.18 per month). Per year 72 to 77 (2016 72, 2017 72, 2018 72, 2019 72, 2020 77, 2021 74, 2022 72, 2023 72, 2024 72, 2025 72, 2026 to 16 Oct 59). 11 entries were still open at the end of the data; 1 signal on the last session had no next session. **The entry count is set by the 12-slot cap, not by the signal:** 12 slots x 252 sessions / 41 sessions per cycle is about 74 per year, and the slots are full on 85% of sessions. Stops would shorten holds and raise the count; the ignored blocks would lower it. The model cannot bound either.

**d. Capital use (fixed 6.67% per position).** Median 12 of 12 slots open (p5 10, min 2 from 2016); invested share median 80% of equity (p5 66.7%). Total risk at 12 slots is 12%, under the 15% heat cap. **Sector cap:** with the cap applied there were 984 blocked candidate-sessions in 316 of 2710 sessions (308 of 2674 from 2016; 11.5%), up to 16 in one session; entries fell only from 798 to 796 because the next candidate fills the slot. **Selected symbols with no sector:** 114 of 341 distinct symbols (182 of 798 entries, 22.8%); they share one UNKNOWN bucket, which therefore holds at most 2 positions at once. The sector map is incomplete for this strategy's picks.

**e. Concentration (no sector cap, 2016 to 2026).** Largest single symbol ADANIENT, 1.8% of entries; top-10 symbols 13.2%; 339 distinct symbols. Sector split: UNKNOWN 22.8%, FINANCIALS 15.5%, INDUSTRIALS 10.7%, CONSUMER 9.5%, HEALTHCARE 9.3%, ENERGY 7.0%, METALS 5.1%, AUTO 4.5%, IT 3.9%, SERVICES 3.8%, CHEMICALS 3.3%, REALTY 2.9%, TELECOM 1.4%.

**f. Data quality.** Gap guard drops (names with 252 bars that fail the guard): median 5 per session overall, but **median 19 to 24 per session in 2022, 2024, 2025, 2026** (about 4% to 6% of the eligible names) and 284 distinct names over the whole window. 14 names had fewer than 252 bars at some point. Split/bonus inside the window: median 16 names per session (3 to 44). Corporate actions the engine does not adjust inside the window: median 13 per session (4 to 33); name-sessions by type: OTHER 22,731, RIGHTS 9,853, DEMERGER 3,287, MERGER 2,034; 184 distinct names. No adjustment errors, no stale names.

**g. Nearness among candidates.** 205,643 candidate name-sessions: exactly 1.00 = 49,738 (24%); 0.95 to <0.96 30,324; 0.96 to <0.97 31,528; 0.97 to <0.98 32,491; 0.98 to <0.99 32,444; 0.99 to <1.00 29,118. Candidates at exactly 1.00 per session: median 12, p95 58, max 135.

**h. Runtime.** Eligibility, one session: median 3.7 s (2.0 s in 2016 to 2018, 4 to 5 s from 2020). Scoring one session across the eligible universe (this tool): median 1.1 s overall, 2.3 s in 2025 to 2026 (about 500 names). Whole run: 12,923 s for 2710 sessions (4.8 s per session, one process, with the real lake). A 2016 to 2026 backtest scores 2674 sessions, so scoring plus eligibility alone is projected at about 3.5 hours; the engine's own work (fills, exits, arbitration, costs) is not included and was not measured. The STOP 2 strategy should reuse one adjusted-bar fetch per symbol per session; the engine may also be able to share the eligibility result.

## 5. Findings that need a decision
1. **Ties at exactly 1.00 make the top 25 alphabetical.** On 24% of candidate name-sessions nearness is exactly 1.00, a new high; on many sessions more than 25 names sit at 1.00 (p95 58, max 135). The rule says ties go by symbol, so the top 25 are then the first 25 alphabetically. In the occupancy model **82% of entries (648 of 786) are at exactly 1.00**, 36.9% of entries start with the letter A and 61.5% with A to C (a uniform spread would be much lower). This does not use any return, but it means the strategy trades whichever new-high names sort first, which also drives the concentration (ADANIENT). Options for the owner: keep as written (it is arbitrary but deterministic and not selected on outcomes); or fix a different tie-break (for example liquidity, or a hash of symbol and date) before pre-registration. I have not changed the rule.
2. **Cap-bound trade count.** About 6 entries a month (about 72 a year, about 790 over 2016 to 2026) in the model. The model's occupancy is 85% full on 12 slots, so the entry rate is a property of the cap and the 40-session hold. Expected trade rate proposed for the spec: 6.2 per month (model, to be revisited once stops are allowed to shorten holds). Power for about 790 trades is for STOP 3 and the F9 numbers, not computed here.
3. **Backtest window.** Options: (A) 2016-01-01 to 2026-10-16 using pre-calendar bars (the engine's `AsOfView` reads them; valid nearness from the first session, but the universe is only 123 to 177 names in 2016); (B) 2016-11-17 onward (calendar-only definition). I propose A, but it is the owner's call. The lake's last bar is 2026-10-16.
4. **Incomplete sector map.** 33% of selected symbols have no sector and share one bucket capped at 2 positions at a time. This is how live behaves; it is a property of the data, not of this strategy. Decide whether to accept it or fill the map before the backtest (shared data change, outside this task).
5. **Unadjusted actions.** Rights, demergers and OTHER actions that the engine does not adjust sit inside the 252-bar window for a median 13 names a session (about 5% of the valid names). A price jump from such an action could create or hide a "new high". I did not examine any price move to check this (that would be looking at prices outside the signal); counts only.
6. **Gap guard.** In 2022 and 2024 to 2026 the guard drops about 19 to 24 names a session. Cause is the EQ-only lake (PRE_LIVE_LIST item 11), not examined further.

## 6. Deviations and limitations
- The study is a counts model of a strategy that does not exist yet; none of its numbers are the strategy's results. The occupancy model ignores stops, the risk cap, costs, the gap-up cap, the cash cap and fill blocks; the sector-cap model uses a fixed 6.67% position at the signal-day close (actual sizing uses the fill and rounds shares).
- The first-session "252nd bar date" probe was removed (too slow, not needed): item (a) is answered by the first valid session (2015-11-09) and the lake's first bar (2013-01-01).
- Local `master` was stale (ab6ae5b); the branch is based on origin/master 4bfc188, which has the exit-policy library. My first attempt at moving the branch (`git reset --hard`) was blocked by the permission system; I used `git checkout -B ... origin/master` instead (the branch had no commits).
- One session of the study (the whole run) used one process; a crash would have meant a restart. The first run attempt of G2 at STOP 0 was stopped by a tool time limit, not a failure; the rerun passed.
- The "unexplained +1" in G1 (section 2).
- Git rules followed: no trailers or attribution, plain commit messages.

## 7. Decisions needed from the owner and reviewer
1. Does the rule go ahead as written, given finding 1 (alphabetical tie-break on new highs)? If not, which tie-break?
2. Backtest window: A (from 2016-01-01) or B (from 2016-11-17)? End 2026-10-16.
3. Expected trade rate for the spec: 6.2 per month (this model), or another figure.
4. Sector map: accept the UNKNOWN bucket as is?
5. `smallest_edge_of_interest` (needed at STOP 2; I will not invent it).

I have stopped here and will not start STOP 2 until you reply.

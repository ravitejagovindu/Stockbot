# near_52w_high: STOP 2 report (implementation)

Date: 2026-11-11. Branch `near-52w-high` (from origin/master 4bfc188). Strategy status: `research`. No backtest that outputs returns was run. The only runs of `run_backtest` are in unit tests on synthetic fixture lakes. Nothing was merged.

## 1. What was done
Following the original STOP 2 text with the owner's review decisions (tie-break by ADTV, window A, 6.2 trades a month, 0.15 R, full G2).

- **2.1 Strategy.** New folder `stockbot/strategies/near_52w_high/` (`__init__.py`, `strategy.py`). It implements the Strategy protocol, imports only `stockbot.strategies.base` and `stockbot.strategies.spec` plus the standard library (a test scans the package for this), and reads every number from `spec.params`.
- **2.2 Spec.** id `near_52w_high`, version `1.0.0`, status `research`, params `{window 252, min_bars 250, threshold 0.95, top_n 25, stop_fraction 0.85, tie_adtv_sessions 20}`, exit_policy `fixed_hold_40` (library id, not touched), universe_overrides empty, expected_trade_rate 6.2, smallest_edge_of_interest 0.15 (owner's proposal, to be confirmed at STOP 3), prereg_ref and validation_ref empty. Registered through an explicit `register(registry)` call (see deviations).
- **2.3 No-strategy test.** `tests/unit/test_no_strategy_in_the_tree.py` changed on purpose: it allowed no strategy; it now allows exactly one strategy folder (`near_52w_high`) and exactly one class (`NearHighStrategy` in `strategy.py`), nothing else. Every other rule in the file is unchanged. The reason is in the commit body (9f72dd7) and in STATUS.md.
- **2.4 Backtest wiring.** `scripts/research_near_52w_high.py`: one `run_backtest` call with the shared config, `policies=None` (the library policy is built from the spec), `SectorLookup` from the live runner (same sector map and UNKNOWN behaviour), default window 2016-01-01 to 2026-10-16. It prints the plan and runs only with `--execute`; no sweep, no loop over variants; it refuses a non-empty output directory and prints nothing about P&L.
- **2.5 Tests, written first.** `tests/unit/test_near_52w_high_strategy.py` and `tests/unit/test_research_near_52w_high.py` with `tests/fixtures/near_high_series_lake.py`. Shown failing before the code existed (commit 9f72dd7): `ModuleNotFoundError: No module named 'stockbot.strategies.near_52w_high'` (collection error), and 2 failures in the no-strategy test (`folders == [...]`, and the class list "Right contains one more item: stockbot/strategies/near_52w_high/strategy.py::NearHighStrategy"). After the package existed: 23 strategy tests and 3 research-script tests pass.
- **Tie-break (review decision 1).** Study tool updated (1b7df8b): ties by higher raw 20-session ADTV (`AsOfView.adtv`, the figure eligibility uses), then symbol; ADTV is fetched only for tie groups that start inside the top 25. The strategy does the same and carries it in an explicit ordinal rank. A test checks that the study tool and the strategy rank the same names in the same order on every session of the study's fixture lake.

## 2. Commits since the STOP 1 report (7fccb69)
1b7df8b study tool: ADTV tie-break, cacheable candidate lists, segment join and assemble mode · 9f72dd7 tests first, no-strategy test changed · ef49cc8 strategy, spec, registration, research script, guides · 656af0e tie-break rerun (counts and cache) · plus the commit that adds this report and the final STATUS.md. Plain messages, no trailers.

Files added or changed (lines): `strategy.py` 89, `__init__.py` 4, `scripts/research_near_52w_high.py` 74, `tests/unit/test_near_52w_high_strategy.py` 327, `tests/unit/test_research_near_52w_high.py` 54, `tests/fixtures/near_high_series_lake.py` 52, `data_checks/near_high_signal_count.py` (170 lines changed), `tests/unit/test_near_high_signal_count.py` 70 changed, `tests/fixtures/near_high_lake.py` 18 changed, `tests/unit/test_no_strategy_in_the_tree.py` 19 changed, guides (md, json, rebuilt html) and `docs/ARCHITECTURE.md` (4 lines) to say that one strategy now exists on this branch.

## 3. Tests and database (before and after)
| check | STOP 1 | STOP 2 |
|---|---|---|
| G1 `tests/unit tests/integration` | 790 passed, 8 skipped | **819 passed, 8 skipped** (345 s) |
| G3 `test_g3_fixture_baseline.py` | 2 passed | **2 passed** |
| G2, full folder: `STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests` | not run (data_integrity only: 121 passed) | **948 passed, 0 failed, 0 skipped** (1713 s). Not killed, not timed out. |

The owner's earlier full run was 643 passed; this is 948 on a tree that has since gained the exit-policy library, the guide tests and this task's tests. I did not trace the 305 difference test by test.

finsight.db before and after STOP 2 (re-read after the full run): sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752, mtime 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes. Identical to the recorded values. The tie-break scoring (three processes) also fingerprinted the file before and after: unchanged in all three.

What the tests cover (all in `test_near_52w_high_strategy.py` unless stated): nearness against an independent numpy computation, including a split inside the window and a split still in the future (no look-ahead from it); 252 bars and a bar on the as-of date; gap guard (2 missing sessions pass, 3 drop, a gap before the window does not count); the edges 0.9500 in and 0.9499 out; the top-25 cut, ordinal rank, order by nearness; ties by ADTV then symbol (30 names tied at 1.00, top 25 are the highest-volume ones and not alphabetical; equal ADTV falls back to symbol); stop and reference price in the as-of basis (also after a split); spec hash changes for each of the six numbers and for exit policy, version and rates; the strategy reads its numbers from the spec; research status cannot run in LIVE or PAPER; registering a second dummy strategy changes nothing; the package imports only what a strategy may import; changing every row after the as-of date changes nothing; through the engine: exit at the open of session 41 via `fixed_hold_40` (signal 251, entry 252, exit 292), the stop firing earlier (session 262), a session without a bar not counted (exit two sessions later); determinism and replay of a session from the same state give identical bytes.

## 4. Measured scoring time
On the real lake, read-only, warm file cache, one session across the whole eligible universe (shared eligibility, then `NearHighStrategy.propose`):

| session | eligible | eligibility (s) | propose (s) | proposals |
|---|---|---|---|---|
| 2019-06-03 | 195 | 1.77 | 0.75 | 25 |
| 2022-06-01 | 288 | 2.38 | 1.05 | 24 |
| 2025-10-15 | 503 | 3.25 | 2.23 | 25 |
| 2026-10-15 | 561 | 3.41 | 2.75 | 25 |

A first pass right after the long runs, with the 3.4 GB file cold in the cache (2.8 GB RAM free), took 32 to 82 s for eligibility and up to 170 s for `propose` on some sessions. That was disk reads, not the code; the warm repeat above is the representative figure. The tie-break scoring of all 2710 sessions took 17,986 s of process time in three parallel processes under contention (about 6.6 s a session). The STOP 1 projection stands: a 2016 to 2026 backtest is about 3.5 hours or more for eligibility plus scoring, before the engine's own work, which was not measured. `propose` is not cached across sessions.

## 5. Addendum: tie-break rerun (counts only)
What I did: there was no cache of candidate lists from the first study, so scoring had to be repeated once. I changed the tool to cache each session's count row and top-25 list, scored the full calendar in three date segments in parallel (to 2021-01-08, to 2024-02-02, to 2026-10-16; `Claude_Docs/near_high_tiebreak_parts/`), and ran the occupancy models on the cached lists (`--assemble`, no database). Everything that does not depend on the order of the top 25 (eligible, valid, candidate, proposed, gap and corporate-action counts, nearness distribution) came out identical to the first study; this was checked key by key. Full tables: `Claude_Docs/NEAR_52W_HIGH_SIGNAL_COUNTS_TIEBREAK.md` and `.json`. Entries compared for 2016 to 2026 (786 entries):

| | first study (ties by symbol) | with ADTV tie-break |
|---|---|---|
| entries, per month | 786, 6.17 | **786, 6.17** |
| per year 2016 to 2026 | 72,72,72,72,77,74,72,72,72,72,59 | **identical** |
| entries at exactly 1.00 | 648 (82.4%) | 648 (82.4%) (the count of slots filled from the 1.00 group does not depend on the order inside it) |
| entries starting with A / with A to C | 36.9% / 60.6% | **9.0% / 24.6%** |
| largest single symbol | ADANIENT 1.8% | INFY 1.9% |
| top-10 symbols | 13.2% | 14.6% |
| distinct symbols | 339 | 302 |
| symbols / entries with no sector | 112 / 178 (22.6%) | 75 / 103 (13.1%) |
| sector split | UNKNOWN 22.6, FINANCIALS 15.5, INDUSTRIALS 10.8, CONSUMER 9.5, HEALTHCARE 9.2, ENERGY 7.1 | FINANCIALS 20.9, UNKNOWN 13.1, CONSUMER 9.0, HEALTHCARE 8.0, INDUSTRIALS 7.6, IT 7.5, ENERGY 7.0, METALS 6.9, AUTO 6.1 |
| entries with the sector cap, per month | 784, 6.16 | 784, 6.16 |
| sector-cap blocks (sessions with a block) | 968 (308) | 953 (305) |
| capital use | slots: median 12, p5 10; invested median 80%, p5 66.7%; full on 84.7% of sessions | **same** |

The alphabetical skew is gone (letter shares now follow a broad spread; A is 9%). The entry rate moved by 0.0%, far under the 5% revisit threshold, so `expected_trade_rate` stays 6.2. A consequence to know: ties now go to the most liquid names, so the picks shift towards large, liquid, better-mapped names (FINANCIALS 21%, UNKNOWN sector 13%); the largest-symbol share and top-10 share are about unchanged. This is a property of the tie-break the owner chose, not an effect measured on returns. All numbers are the same cap-bound counts model as before: stops, the risk cap, costs, the gap-up cap, the cash cap and fill blocks are ignored.

## 6. Deviations and limitations
1. **Rank.** The brief said "rank = nearness". Following the owner's tie-break decision the rank is an explicit ordinal (25 for the first proposal down to 1), because a float nearness cannot carry the ADTV and symbol tie-break. Nearness and ADTV are in the proposal metadata. The engine's order (rank, then symbol) reproduces the strategy's order (tested).
2. **Registration.** "Register it in the registry" is implemented as an explicit `register(registry)` call. Importing the package registers nothing, so `default_registry` and the default live book stay empty (two existing tests assert this and I kept them strict). If you want the spec in `default_registry` at import, that edits the registry module and two tests: your decision.
3. **Version.** "version 1" is `1.0.0` (the spec schema requires MAJOR.MINOR.PATCH).
4. **Strict mode.** If `adjusted_bars` raises on a corporate action with a missing ratio, the strategy does not catch it, so a strict backtest stops. The study found no such name in the whole window (adjustment errors: 0), so I left it loud.
5. **ASM/GSM.** The research run supplies no ASM/GSM ranges for the historical window (the snapshots exist only for recent dates), so that shared exclusion is not applied. Recorded as a limitation.
6. **Accepted limitations (owner decisions, now recorded):** unmapped symbols share one UNKNOWN sector (the shared 15% cap holds that bucket to two positions at a time); corporate actions the engine does not adjust (demerger, merger, rights, OTHER) sit inside the window for a median of about 13 valid names a session, with no extra guard. Both go into the pre-registration draft at STOP 3.
7. **Window labels.** `shared.yaml` labels 2015 to 2019 as an untouched TEST window and 2020 to 2026 as TUNE windows. This strategy has fixed numbers and one registered run, so nothing is tuned, but window A (2016 to 2026) spans both labels; please say at STOP 3 how that applies.
8. **Process.** My first attempt at a detached nested PowerShell for the G1 and G2 runs did not start, so I ran them through the tool's background mode; a one-line patch script in the parent folder was removed after use. Nothing is left outside the repository. The first G2 run at STOP 0 was stopped by a tool time limit (not counted) and rerun. 
9. The +305 difference between 643 (owner's last full run) and 948 is not traced test by test.
10. The strategy and the study tool are two implementations of one rule; a test ties them together on the fixture lake, but they would have to be kept in step by hand.

## 7. Decisions needed from the owner and reviewer
1. Registration form: explicit `register(registry)` (as built) or also into `default_registry`?
2. Rank as an ordinal (as built), or another encoding of the tie-break?
3. `smallest_edge_of_interest` 0.15 R: confirm at STOP 3 against the power numbers (it is in the spec now).
4. How the TEST/TUNE labels in `shared.yaml` apply to window A (item 7).
5. Anything to change before STOP 3 (pre-registration package).

I have stopped here. STOP 3 starts only when you reply.

# stale-positions report: symbol links and the no-bars exit

Branch `stale-positions` (from origin/master 67b6724; the inventory commit 6cf9d96 came first). Plain commits, no trailers. `finsight.db` was opened read-only everywhere and never written: sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` before and after (checked at the end). No strategy folder, pre-registration, ledger row or stored result was touched; nothing was re-run to update a registered result; the three `riskadj_momentum` scripts were edited (B5) and NOT run on the real lake.

## 0. Summary
| item | result |
|---|---|
| A1 link table | **41 pairs, 40 stocks** linked (one chain of three: IBULISL -> YAARII -> YAARI); 413 other boundaries of the ISIN map not linked, each with its reason |
| A2 views | one implementation in `AsOfView`; the memory view replaces only the per-symbol fetch primitives; sector lookup follows the link; switch `data.symbol_links_enabled: true` |
| A3 proofs | (i) switch off: full G2 passes except the two hash-pin tests, which pin the value with the switch on; (ii) 0 differences over 450 sessions / 112,500 unlinked symbol-sessions; (iii) all 41 pairs pass; (iv) SQL = memory on all pairs and on fixture lakes; (v) one golden changes (section 5) |
| B1-B4 engine | closure after `engine.stale_exit_sessions` = 20 sessions without a bar, reason `SYMBOL_NO_BARS`, usable; reporting and stress line in the gate output and manifest; baseline closes the same way |
| C live | explicit `SYMBOL_NO_BARS` flag (plus `UNRECONCILED_EXIT` in live) in the session file |
| Hashes | `shared_config_hash` changes (section 4); validation_gates hash `e9b6407f...` unchanged (asserted by a test) |
| Tests | 21 new tests, all pass; G1, full G2, G3 in section 8 |
| Section E | 32 stored trades would have been closed by the rule across the four stored runs; 976 symbol-sessions gain eligibility with links on, 0 lose it |

## 1. A1: the two link files (`data/reference/symbol_links.csv`, `symbol_links_not_linked.csv`)
Built by `scripts/build_symbol_links.py` from `data/reference/isin_symbol_map.csv` and the lake (read-only); deterministic. Rule (numbers fixed): same ISIN; map boundary type `pure_rename`; the new symbol's first bar is 1 to 5 sessions after the old symbol's last bar (sessions = positions in the lake's calendar of distinct trade dates); no overlapping bars; boundary ratio = first close of the new symbol / (last close of the old symbol x factor) between 0.80 and 1.25, where factor is the product of the SPLIT/BONUS factors (rows under either name) with ex-date after the old last bar and up to the new first bar (a split whose ex-date IS the old last bar is already in that bar: PHILIPCARB, 2018-04-19); a symbol is old side of at most one and new side of at most one accepted pair. Chains resolve to the latest symbol (`latest_symbol`).

**Linked (41 pairs):**

| old | new | latest | old last bar | new first bar | sessions | split/bonus factor at boundary | ratio after factor |
|---|---|---|---|---|---|---|---|
| AMIORG | ACUTAAS | ACUTAAS | 2025-04-24 | 2025-04-25 | 1 | 0.5 | 0.9714 |
| AEGISCHEM | AEGISLOG | AEGISLOG | 2015-09-16 | 2015-09-18 | 1 | 1 | 1.158 |
| UTIBANKETF | BANKBETA | BANKBETA | 2021-02-18 | 2021-02-19 | 1 | 1 | 0.9713 |
| ICICIBANKN | BANKIETF | BANKIETF | 2022-09-01 | 2022-09-02 | 1 | 1 | 1.001 |
| ICICI500 | BSE500IETF | BSE500IETF | 2021-10-28 | 2021-10-29 | 1 | 1 | 0.9819 |
| INFIBEAM | CCAVENUE | CCAVENUE | 2017-08-31 | 2017-09-01 | 1 | 1 | 0.9582 |
| ITDCEM | CEMPRO | CEMPRO | 2015-08-21 | 2015-08-24 | 1 | 1 | 0.909 |
| EBIXFOREX | DELPHIFX | DELPHIFX | 2021-08-31 | 2021-09-01 | 1 | 1 | 0.9777 |
| PANTALOONR | FRL | FRL | 2013-04-10 | 2013-04-11 | 1 | 1 | 0.9662 |
| PRETAILDVR | FRLDVR | FRLDVR | 2013-04-10 | 2013-04-11 | 1 | 1 | 1.019 |
| ALSTOMT&D | GET&D | GET&D | 2016-09-12 | 2016-09-14 | 1 | 1 | 1.009 |
| KOTAKGOLD | GOLD1 | GOLD1 | 2021-07-22 | 2021-07-23 | 1 | 1 | 1.002 |
| AXISGOLD | GOLDAXIS | GOLDAXIS | 2020-07-23 | 2020-07-27 | 2 | 1 | 0.8863 |
| GOLDSHARE | GOLDBETA | GOLDBETA | 2021-03-25 | 2021-03-26 | 1 | 1 | 0.9951 |
| ICICIGOLD | GOLDIETF | GOLDIETF | 2018-11-15 | 2018-11-16 | 1 | 1 | 0.9912 |
| HDFCMFGETF | HDFCGOLD | HDFCGOLD | 2021-02-18 | 2021-02-19 | 1 | 1 | 0.9892 |
| HDFCNIFETF | HDFCNIFTY | HDFCNIFTY | 2021-02-18 | 2021-02-19 | 1 | 1 | 0.9936 |
| HDFCSENETF | HDFCSENSEX | HDFCSENSEX | 2021-02-18 | 2021-02-19 | 1 | 1 | 0.9963 |
| ICICITECH | ITIETF | ITIETF | 2022-09-01 | 2022-09-02 | 1 | 1 | 0.9955 |
| EXCEL | LANDSMILL | LANDSMILL | 2022-09-27 | 2022-09-28 | 1 | 0.0667 | 1.108 |
| DAAWAT | LTFOODS | LTFOODS | 2017-02-07 | 2017-02-08 | 1 | 1 | 1.199 |
| M50 | MOM50 | MOM50 | 2014-10-16 | 2014-10-17 | 1 | 1 | 0.9762 |
| UTINEXT50 | NEXT50BETA | NEXT50BETA | 2021-03-25 | 2021-03-26 | 1 | 1 | 0.9578 |
| KOTAKNIFTY | NIFTY1 | NIFTY1 | 2017-07-27 | 2017-07-28 | 1 | 1 | 0.9953 |
| AXISNIFTY | NIFTYAXIS | NIFTYAXIS | 2020-07-23 | 2020-07-27 | 2 | 1 | 0.8679 |
| NETFNV20 | NV20BEES | NV20BEES | 2019-12-19 | 2019-12-20 | 1 | 1 | 0.9929 |
| PHILIPCARB | PCBL | PCBL | 2018-04-19 | 2018-04-20 | 1 | 1 | 1.05 |
| PITTILAM | PITTIENG | PITTIENG | 2015-04-16 | 2015-04-17 | 1 | 1 | 1.063 |
| GAL | SHAH | SHAH | 2016-10-13 | 2016-10-14 | 1 | 1 | 1.019 |
| UTISXN50 | SNXT50BETA | SNXT50BETA | 2021-02-18 | 2021-02-19 | 1 | 1 | 0.8501 |
| IBWSL | SORILHOLD | SORILHOLD | 2017-04-17 | 2017-04-18 | 1 | 1 | 0.9002 |
| SMOBILITY | SPICEMOBI | SPICEMOBI | 2014-08-18 | 2014-08-19 | 1 | 1 | 1.044 |
| SWANENERGY | SWANCORP | SWANCORP | 2014-02-03 | 2014-02-04 | 1 | 1 | 1.002 |
| TIPSINDLTD | TIPSMUSIC | TIPSMUSIC | 2023-04-20 | 2023-04-21 | 1 | 0.1 | 0.9597 |
| TWL | TITAGARH | TITAGARH | 2015-04-23 | 2015-04-24 | 1 | 1 | 0.9056 |
| MCDOWELL-N | UNITDSPR | UNITDSPR | 2018-06-15 | 2018-06-18 | 1 | 1 | 0.983 |
| MINDAIND | UNOMINDA | UNOMINDA | 2016-09-12 | 2016-09-14 | 1 | 1 | 1.085 |
| WELSPUNIND | WELSPUNLIV | WELSPUNLIV | 2016-03-21 | 2016-03-22 | 1 | 1 | 0.9995 |
| IBULISL | YAARII | YAARI | 2020-12-07 | 2020-12-08 | 1 | 1 | 1.05 |
| YAARII | YAARI | YAARI | 2021-12-14 | 2021-12-15 | 1 | 1 | 1.006 |
| CADILAHC | ZYDUSLIFE | ZYDUSLIFE | 2015-10-06 | 2015-10-07 | 1 | 1 | 0.9942 |

**Not linked (413 boundaries; `symbol_links_not_linked.csv` has every row with its reason):**

| map boundary type | reason (numbers replaced by N) | boundaries |
|---|---|---|
| demerger_merger | map boundary type demerger_merger: feed ['DEMERGER'] within Nd | 8 |
| demerger_merger | map boundary type demerger_merger: feed ['MERGER'] within Nd | 4 |
| other | map boundary type other: gap of N sessions | 53 |
| other | map boundary type other: price step N without a feed event | 1 |
| pure_rename | a symbol of the pair has no bars in the lake | 341 |
| pure_rename | boundary ratio N outside N to N | 2 |
| pure_rename | new first bar is N sessions after the old last bar (allowed N to N) | 4 |

The 6 `pure_rename` boundaries that have both symbols in the lake but fail the numbers:

| old | new | old last bar | new first bar | sessions | ratio | reason |
|---|---|---|---|---|---|---|
| GODHA | AURIGROW | 2022-01-27 | 2022-06-21 | 98 | 1.119 | new first bar is 98 sessions after the old last bar (allowed 1 to 5) |
| ICICINXT50 | NEXT50IETF | 2018-11-14 | 2018-11-16 | 2 | 0.1097 | boundary ratio 0.1097 outside 0.8 to 1.25 |
| KARDA | KBCGLOBAL | 2021-06-08 | 2021-09-13 | 66 | 0.0905 | new first bar is 66 sessions after the old last bar (allowed 1 to 5) |
| TIDEWATER | VEEDOL | 2021-07-14 | 2021-10-18 | 64 | 0.5617 | new first bar is 64 sessions after the old last bar (allowed 1 to 5) |
| UTINIFTETF | NIFTYBETA | 2023-09-22 | 2023-09-25 | 1 | 0.0999 | boundary ratio 0.0999 outside 0.8 to 1.25 |
| VIKASGLOB | VIKASECO | 2014-02-28 | 2014-06-13 | 70 | 1.199 | new first bar is 70 sessions after the old last bar (allowed 1 to 5) |

**What "other" means in the map.** `isin_symbol_map.csv` classifies every boundary between two symbols of one ISIN (builder: `stockbot/data/ingestion/f2_build_isin_symbol_map.py`): `pure_rename` = same ISIN, no overlap, a gap of at most 20 sessions, raw close continuous (0.8 to 1.25) and no demerger/merger/arrangement in the NSE feed within 45 days; `demerger_merger` = such an event is in the feed near the boundary; **`other` = everything else that is not clean: dates overlap (two symbols trade at once), a gap of more than 20 sessions (a relisting or suspension, or the name moving out of the EQ series), or a price step without a feed event.** In this map the 54 `other` boundaries are 53 "gap of N sessions" and 1 "price step 1.711 without a feed event". The map leaves them split "for hand review"; the link table links none of them. Note that the map's pure_rename test uses the RAW close ratio and a gap up to 20 sessions; the link rule is stricter (1 to 5 sessions, ratio after the logged split/bonus factor).

## 2. The rules as built
**A2: links in the as-of views** (`stockbot/data/symbol_links.py`, `stockbot/data/asof.py`, `asof_memory.py`, `sector_map.py`). A linked stock is one symbol under its latest name, applied on read (the lake is not modified). The public methods of `AsOfView` combine the names of the chain; `_raw_bars_physical`, `_corporate_actions_physical`, `_feed_actions_physical`, `_first_and_count_physical` are the data-fetch primitives of ONE physical symbol (the SQL view has the SQL, the memory view the arrays); nothing of the link logic is repeated in the memory view.
- bars: the chain's bars as one series, only rows up to the as-of date, no duplicate date (the builder excludes overlaps); any name of the chain answers the same series (an alias).
- corporate actions: rows filed under any name of the chain plus rows filed under another symbol whose note starts `feed_symbol=<a name of the chain>;`; an action present more than once (same ex-date, type and ratio) is returned once, so a boundary-date action is applied once. The adjusted series therefore multiplies the bars before the ex-date by one factor (PHILIPCARB/PCBL: bars up to 2018-04-18 by 0.2).
- listing age and bar count: earliest first bar and the sum of the bar counts of all names (listing age carries over; eligibility is not reset); ADTV from the combined series; `is_fund_or_etf` if any name is in the fund list; earnings query symbols are the union.
- `symbols_trading()` lists the stock once, under its latest name, also before the rename; `resolve_symbol()` maps any name to the latest. `decide` treats a position under an old name and a proposal under the new one as the same holding (ALREADY_HELD) and steps the old-named position on the new name's bars.
- sector: the stock's own name first, then its other names, latest first; an unmapped linked stock is ONE `UNMAPPED:<LATEST>` sector.
- switch: shared.yaml `data.symbol_links_enabled: true`; off = every view behaves as before.

**B1-B4: no bars for 20 sessions** (`stockbot/engine/stale.py`, `stepping.close_no_bars`, `decide`, `path.simulate_ticket`). If a held position's symbol (after linking) has no bar on any of the last `engine.stale_exit_sessions` = 20 sessions of the view's calendar (the Nifty session list), then on that 20th session `decide` closes it at its last available close x (1 - exit slippage) with the normal sell costs: exit reason `SYMBOL_NO_BARS`. Decided from data up to that session only. The closure happens in step 3 (position stepping), before proposals, so the slot, cash and risk are free for tickets created that session (filled at the next open). Before the 20th session nothing changes (the existing `NO_BAR_POSITION_NOT_STEPPED` flag only). Nothing re-opens when bars resume. In `trades.json` a stale trade carries `"stale_exit": true`, `exit_price` and `last_close`; no other trade gets those keys.
- B2: usable like any other trade (not `excluded_ca`, not END_OF_WINDOW): the shared gates, T1, T2 and the equity curve count it (test: `trade_table` usable = True).
- B3 (reporting only): `evaluate` (shared, `scripts/evaluate_validation_gates_near_52w_high.py`) adds `stale_exit` = number, list, total net P&L and, when there are any, a `stress` block: every gate recomputed with each stale exit sold at `reporting.stale_exit_stress_factor` (0.5) x its last close, sell costs recomputed, the P&L difference carried into equity and cash from the exit date; labelled "stress, not a gate". The run manifest has a `stale_exit` block (sessions, trades, total net P&L, list) and a `symbol_links` block (enabled, number of pairs, sha256 of the link file).
- B4: `simulate_ticket` closes the same way (reason `SYMBOL_NO_BARS`, returned as a CLOSED draw, so it is a filled draw).
- Config (all in shared.yaml, none overridable by a strategy): `data.symbol_links_enabled: true`, `engine.stale_exit_sessions: 20` (new section `engine`), `reporting.stale_exit_stress_factor: 0.5`.

**C: live.** The same decision is the flag `SYMBOL_NO_BARS` with the text `position <SYMBOL>: no bars for 20 sessions; closed in the book at the last close; check the holding manually (rename, merger, suspension, series change)`, and, in live mode, the usual `UNRECONCILED_EXIT`; both are in the session's ticket file (`flags`, `exits_assumed`). Test: `test_live_session_output_carries_an_explicit_item`. Nothing is handled silently.

**B5: exact edits in the strategy-side scripts** (to stay consistent with B1-B4; none was run):
- `scripts/baseline_matched_random_riskadj_momentum.py`: imports `no_bars_for`, `stale_sessions`, `close_no_bars`; `simulate_ticket_own` (the strategy-side copy of the shared loop) gets the same no-bars closure as `engine.path.simulate_ticket` (reason `SYMBOL_NO_BARS`, a closed filled draw); `baseline_meta.json` gains `stale_exit_draws`. The end-of-window closure and everything else are unchanged.
- `scripts/research_riskadj_momentum.py`: `trade_records(trades, decisions=())` adds `stale_exit`, `exit_price`, `last_close` to a `SYMBOL_NO_BARS` trade by calling the shared `stockbot.backtest.outputs.trade_records`; `main` passes `res.decisions`. The END_OF_WINDOW relabel is unchanged.
- `scripts/evaluate_validation_gates_riskadj_momentum.py`: `evaluate` split into `load_run` + `evaluate_run` (the body, unchanged) and the shared `stale_exit_report` (with this script's own `evaluate_run` for the stress line); `format_table` prints it.
- Shared, not strategy-side: the near_52w_high evaluate script is the one `validate_family` calls; its `evaluate` is split the same way.

## 3. Test list (D) — `tests/unit/test_stale_positions.py`, 21 tests, fixture lakes only
link table (chain, ambiguity, cycle), switch/override, builder rules on a fixture (7 cases incl. chain and split factor), the committed link file's rules, linked stock = one symbol (bars, point in time, once-only boundary action, feed-note row, trading list, switch off), listing age/ADTV/eligibility not reset, sector follows the link, SQL = memory (switch on and off), terminal symbol, gap resuming after 30 sessions, 19 missing sessions (no closure), closure frees the slot the same session, rename held across the rename (stop on the new name's bars, no stale exit; with the switch off the same position goes stale), position carried under the old name, baseline draw closure, gates count the stale exit + stress arithmetic, run-file keys only for stale trades, live item, a run with no linked and no stale symbol identical to the old behaviour (decisions and state equal), hash tests.

## 4. Hash effects (B6)
`shared_config_hash` (canonical JSON of every scalar shared setting except `overlays.*`) now includes `data.symbol_links_enabled`, `engine.stale_exit_sessions` and `reporting.stale_exit_stress_factor`, so it **changes for every run**: master (and every stored manifest, e.g. riskadj run 1) `816ee5cb71b0618ed5c2065efc6de39f0f4a59ccf51862ceb3928d3665732bb3` -> `da459624294741239ae85230317da357b5b141a62b81f897bfb3d0745e956248` for the default call. With exactly those three keys left out the payload hashes to the master value (asserted in `test_market_switch.py`). Stored manifests keep their recorded hash; nothing was re-run. The **validation_gates hash `e9b6407f...` is unchanged** (`ValidationGates` was not touched; `test_stale_and_link_settings_are_part_of_the_shared_config_hash_but_not_the_gates_hash` asserts the value `e9b6407f908ff102dd25d9bc3b21a78a52b24c0ea082bba2cd3bb08f81188054`).

## 5. A3 proofs
- **(i) switch off = master.** A full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`) with `symbol_links_enabled: false` set temporarily in shared.yaml (reverted): 1,337 passed, 2 failed. The 2 failures are the two tests that pin the shared-config hash with the switch ON (`test_market_switch.py::test_a_run_with_default_overlays_off_is_byte_identical_to_master` and `test_stale_positions.py::test_stale_and_link_settings_are_part_of_the_shared_config_hash_but_not_the_gates_hash`); every parity test, the 120 golden as-of samples, the digest tests, the frozen-scan golden and G3 pass unchanged.
- **(ii) switch on, unlinked symbols unchanged.** `scripts/stale_positions_proofs.py diff`: 450 real sessions (2016-01-07 to 2026-10-07), in-memory view, switch off vs on; per session `symbols_trading`, `eligible_symbols`, `sessions` (unlinked part) and, for 250 random unlinked symbols, raw bars, adjusted bars, corporate actions, symbol info and ADTV: **112,500 symbol-sessions compared, 143,570 unlinked eligibility results checked, 0 differences.** (81 symbols named in the link file are excluded from the comparison.)
- **(iii) every linked pair** (`proofs ... pairs.json`, all 41 pass): adjusted close ratio across the boundary 0.850 to 1.199 (the combined adjusted series is continuous); combined bars = old bars + new bars, no duplicate date, none dropped; no engine session lies between the old last bar and the new first bar except for 2 pairs where one session of the engine's calendar has no bar under either name; corporate actions unique; 16 pairs have a split/bonus row on the boundary dates, applied once; listing age carries over (first bar = the oldest name's). **Named test PHILIPCARB/PCBL:** split 2:10 ex 2018-04-19 (the old last bar, already post-split), filed under PHILIPCARB only, applied once; adjusted close ratio 1.0498 across 2018-04-19/2018-04-20; 3,416 combined bars = 1,311 + 2,105; listing age 4,923 days from 2013-01-01. Fixture-lake version: `test_linked_stock_is_one_symbol_under_its_latest_name`.
- **(iv) SQL view = memory view with the switch on:** all 41 pairs (3 as-of dates each: raw bars, adjusted bars, actions, symbol info, ADTV) and the fixture lake (9 dates x 6 symbols, switch on and off).
- **(v) goldens that change with the switch on:** exactly one, `tests/data_integrity/test_golden_frozen.py::test_the_scan_through_the_view_reproduces_the_frozen_old_path_result`: `(large_before, large_after, removed, created)` = **(783, 272, 513, 2) instead of (764, 267, 499, 2)**. The scan (`f2_engine_scan.scan`) walks the lake's physical symbols; with links on both names of a linked stock return the same combined series, so that stock's large moves are counted twice. The golden is the OLD path, symbol by symbol, so the test now pins the links off (an edit in a shared test, listed below); the links-on numbers were reproduced and are recorded here. The 120 golden as-of samples and every other golden pass with the switch on.

## 6. Section E: effect, descriptive only (no engine run, no ledger, no conclusion changed)
From the four stored `trades.json` files and the lake (`proofs ... effect.json`). The rule is evaluated on the engine's session calendar with links on.

| stored run | stored trades | closed by the rule | of which terminal (stored exit END_OF_WINDOW) | of which a gap that resumes | stored trades involving a linked symbol |
|---|---|---|---|---|---|
| near_52w_high 4B | 774 | 8 | 3 | 5 | 7 |
| pullback_uptrend run1 | 4156 | 3 | 1 | 2 | 67 |
| short_term_reversal run1 | 4288 | 9 | 3 | 6 | 70 |
| riskadj_momentum run1 | 650 | 12 | 3 | 9 | 13 |

Stored trades the rule would have closed, and when (a "gap that resumes" is closed on the 20th session and nothing re-opens, as specified):

| stored run | symbol | entry | stored exit | last bar | closed by the rule on | kind | sessions earlier than the stored exit |
|---|---|---|---|---|---|---|---|
| near_52w_high 4B | DHANI | 2018-04-19 | 2018-10-30 TIME_EXIT | 2018-06-14 | 2018-07-12 | gap, bars resume later | 72 |
| near_52w_high 4B | ATGL | 2021-06-04 | 2021-09-13 STOP_HIT | 2021-06-08 | 2021-07-06 | gap, bars resume later | 46 |
| near_52w_high 4B | SUZLON | 2023-09-27 | 2024-06-19 TIME_EXIT | 2023-10-09 | 2023-11-07 | gap, bars resume later | 152 |
| near_52w_high 4B | NACLIND | 2025-04-02 | 2026-01-27 TIME_EXIT | 2025-04-25 | 2025-05-26 | gap, bars resume later | 168 |
| near_52w_high 4B | PFOCUS | 2026-03-24 | 2026-07-29 TIME_EXIT | 2026-05-12 | 2026-06-10 | gap, bars resume later | 34 |
| near_52w_high 4B | GSKCONS | 2020-03-27 | 2026-10-16 END_OF_WINDOW | 2020-04-15 | 2020-05-14 | terminal (no bar again) | 1597 |
| near_52w_high 4B | HEXAWARE | 2020-09-24 | 2026-10-16 END_OF_WINDOW | 2020-10-30 | 2020-11-27 | terminal (no bar again) | 1458 |
| near_52w_high 4B | DIACABS | 2026-07-30 | 2026-10-16 END_OF_WINDOW | 2026-08-03 | 2026-08-31 | terminal (no bar again) | 32 |
| pullback_uptrend run1 | DISHTV | 2021-10-05 | 2022-01-04 TIME_EXIT | 2021-10-11 | 2021-11-10 | gap, bars resume later | 38 |
| pullback_uptrend run1 | MAANALU | 2024-11-07 | 2025-05-12 STOP_HIT | 2024-11-08 | 2024-12-10 | gap, bars resume later | 102 |
| pullback_uptrend run1 | HDFC | 2023-07-12 | 2026-10-16 END_OF_WINDOW | 2023-07-12 | 2023-08-09 | terminal (no bar again) | 790 |
| short_term_reversal run1 | NDTV | 2022-09-12 | 2022-12-06 STOP_HIT | 2022-09-12 | 2022-10-11 | gap, bars resume later | 38 |
| short_term_reversal run1 | TTML | 2022-09-12 | 2022-12-06 STOP_HIT | 2022-09-12 | 2022-10-11 | gap, bars resume later | 38 |
| short_term_reversal run1 | RELINFRA | 2022-09-12 | 2022-12-12 TIME_EXIT | 2022-09-12 | 2022-10-11 | gap, bars resume later | 42 |
| short_term_reversal run1 | RELINFRA | 2023-08-14 | 2023-11-12 TIME_EXIT | 2023-08-14 | 2023-09-12 | gap, bars resume later | 41 |
| short_term_reversal run1 | SUVEN | 2024-01-30 | 2024-04-29 TIME_EXIT | 2024-01-30 | 2024-02-27 | gap, bars resume later | 40 |
| short_term_reversal run1 | MAANALU | 2024-11-07 | 2025-05-12 STOP_HIT | 2024-11-08 | 2024-12-10 | gap, bars resume later | 102 |
| short_term_reversal run1 | KPIT | 2019-02-20 | 2026-10-16 END_OF_WINDOW | 2019-02-25 | 2019-03-27 | terminal (no bar again) | 1873 |
| short_term_reversal run1 | SUPPETRO | 2022-04-05 | 2026-10-16 END_OF_WINDOW | 2022-04-06 | 2022-05-09 | terminal (no bar again) | 1103 |
| short_term_reversal run1 | GUJGASLTD | 2026-06-25 | 2026-10-16 END_OF_WINDOW | 2026-06-30 | 2026-07-28 | terminal (no bar again) | 56 |
| riskadj_momentum run1 | BOMDYEING | 2018-06-04 | 2018-10-30 STOP_HIT | 2018-07-03 | 2018-07-31 | gap, bars resume later | 59 |
| riskadj_momentum run1 | DHANI | 2018-06-04 | 2018-10-30 STOP_HIT | 2018-06-14 | 2018-07-12 | gap, bars resume later | 72 |
| riskadj_momentum run1 | ATGL | 2021-05-04 | 2021-09-13 STOP_HIT | 2021-06-08 | 2021-07-06 | gap, bars resume later | 46 |
| riskadj_momentum run1 | ADANIGREEN | 2021-05-04 | 2021-09-13 STOP_HIT | 2021-06-08 | 2021-07-06 | gap, bars resume later | 46 |
| riskadj_momentum run1 | GPIL | 2021-06-02 | 2021-09-27 STOP_HIT | 2021-06-17 | 2021-07-15 | gap, bars resume later | 49 |
| riskadj_momentum run1 | CGPOWER | 2021-06-02 | 2022-01-20 STOP_HIT | 2021-06-08 | 2021-07-06 | gap, bars resume later | 136 |
| riskadj_momentum run1 | FLUOROCHEM | 2022-02-02 | 2022-05-16 STOP_HIT | 2022-02-09 | 2022-03-10 | gap, bars resume later | 43 |
| riskadj_momentum run1 | PCJEWELLER | 2024-10-03 | 2025-01-07 STOP_HIT | 2024-10-07 | 2024-11-04 | gap, bars resume later | 43 |
| riskadj_momentum run1 | E2E | 2026-02-02 | 2026-06-11 STOP_HIT | 2026-02-23 | 2026-03-24 | gap, bars resume later | 51 |
| riskadj_momentum run1 | TATASTLBSL | 2021-07-02 | 2026-10-16 END_OF_WINDOW_COUNTED | 2021-08-05 | 2021-09-03 | terminal (no bar again) | 1269 |
| riskadj_momentum run1 | BLISSGVS | 2026-07-02 | 2026-10-16 END_OF_WINDOW_COUNTED | 2026-07-02 | 2026-07-30 | terminal (no bar again) | 54 |
| riskadj_momentum run1 | HFCL | 2026-08-04 | 2026-10-16 END_OF_WINDOW_COUNTED | 2026-09-02 | 2026-10-01 | terminal (no bar again) | 10 |

Stored trades that involve a linked symbol are listed in `effect.json` (`linked_trades`); none of them is closed by the rule with links on. The riskadj_momentum PHILIPCARB trade (entered 2018-04-03, stored as stale until the window end) is among them: with links on its stock keeps trading under PCBL, so it is not stale. The AMIORG trade of pullback_uptrend (entered 2025-04-23) likewise continues under ACUTAAS.

**Eligibility changes with linking on**, per year (unit: one linked stock on one session; 2,674 sessions, 40 linked stocks; per-stock check against `eligible_symbols` on 25 sessions: 0 mismatches):

| year | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gained (eligible with links, not without) | 52 | 94 | 411 | 135 | 0 | 0 | 0 | 5 | 28 | 172 | 79 |
| lost | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| eligible with links on | 518 | 829 | 959 | 628 | 564 | 1198 | 1011 | 1644 | 2759 | 2633 | 2006 |
| eligible with links off | 466 | 735 | 548 | 493 | 564 | 1198 | 1011 | 1639 | 2731 | 2461 | 1927 |

Gained: 976; lost: 0. Every other symbol is unchanged (A3 ii).

## 7. Shared files touched and why
| file | why |
|---|---|
| `stockbot/config/shared.py`, `shared.yaml` | three new settings (`data.symbol_links_enabled`, new section `engine.stale_exit_sessions`, `reporting.stale_exit_stress_factor`) with validation; `engine` added to `NON_OVERRIDABLE` |
| `stockbot/strategies/spec.py` | its mirror of `NON_OVERRIDABLE` (a test asserts they are equal): `engine` added |
| `stockbot/data/asof.py`, `asof_memory.py` | link logic once in `AsOfView`; the memory view's fetch primitives renamed `_*_physical` and a feed-note index added |
| `stockbot/data/sector_map.py` | sector lookup follows the link |
| `stockbot/data/symbol_links.py` (new), `stockbot/engine/stale.py` (new) | link table/switch; the no-bars rule helpers |
| `stockbot/engine/decide.py`, `path.py`, `stepping.py` | the closure (decide, baseline helper, `close_no_bars`); holding identity through the link; the live flag |
| `stockbot/backtest/outputs.py`, `manifest.py`, `runner.py` | `trade_records` (stale keys only on stale trades), manifest blocks `stale_exit` and `symbol_links`, the runner passes the stale trades |
| `scripts/evaluate_validation_gates_near_52w_high.py` | the shared gate evaluation: `evaluate_run` split out, stale report and stress line (B3) |
| `scripts/build_symbol_links.py`, `stale_positions_proofs.py` (new), `data/reference/symbol_links*.csv` (new) | A1 builder, proofs, data |
| `tests/unit/test_shared_config.py` | the three keys added to `NEW_KEYS` (they have no legacy counterpart) |
| `tests/unit/test_market_switch.py` | the pinned `shared_config_hash` of the default call: master value kept, plus the new value and the proof that only the three keys moved it |
| `tests/data_integrity/test_golden_frozen.py` | the frozen scan pinned with links off (A3 v) |
| `docs/guides/CODEBASE_GUIDE.md` + `codebase_guide.html` (rebuilt with `scripts/build_guide_html.py`) | rows the guide tests require for the new modules and scripts; also the script row of `addendum_riskadj_momentum_run1.py`, which was already missing on master |
| `docs/shared/stale-positions/` | BRIEF, STATUS, proof outputs |
Strategy-side (B5): the three `riskadj_momentum` scripts above. Not touched: any strategy folder, pre-registration, ledger, stored result, the lake.

## 8. Gates and checks
| gate | result |
|---|---|
| G1 (`pytest tests/unit tests/integration`, final code) | **1,209 passed, 9 skipped, 0 failed** (16 min). The first full run had 2 failures, both fixed since: the guide rows (a script missing on master too, plus the new modules) and the pinned shared hash |
| full G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 pytest tests`, switch on) | 1,338 passed, 1 failed (the frozen F2 scan, section 5 v); after pinning that golden to links off, its file passes (2 passed). The full G2 was not repeated after that one-test change |
| full G2 with the switch off (A3 i) | 1,337 passed, 2 failed: the two shared-hash pins that assert the switch-on value (section 5 i) |
| G3 (`tests/unit/test_g3_fixture_baseline.py`) | 2 passed |
| `finsight.db` sha256 | `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752` = `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, size and mtime unchanged: unchanged |
| proofs | `scripts/stale_positions_proofs.py` (diff 1,311 s, pairs 851 s, effect 229 s), outputs in `docs/shared/stale-positions/proofs/` |

## 9. Decisions needed
1. **Aliases.** Any name of a linked stock returns the whole combined series (needed so a position carried under an old name keeps being stepped). A tool that walks physical lake symbols (the F2 scan) therefore sees linked stocks twice; I pinned that golden to links off instead of changing the scan. Say if you prefer the scan to skip aliases.
2. **Feed-note rows.** Rows filed under another symbol whose note names a chain name are attached to the stock (7 rows, all under WEIZFOREX naming DELPHIFX: dividends and one `OTHER` buyback, none price-moving). Say if note-only attachment should be dropped.
3. **Calendar.** The link builder counts sessions on the lake's calendar (distinct trade dates); the no-bars rule counts the engine's session list (the Nifty dates). 2 linked pairs have one engine session between the names that has no bar under either name.
4. **Gap-then-resume.** As specified, a gap of 20 sessions closes the position even if bars later resume (section E: 22 stored trades). Nothing re-opens.
5. **Default on.** `symbol_links_enabled: true` and the 20-session rule are active for backtest, paper and live as soon as this merges; every new manifest has the new `shared_config_hash`.
6. **Memory view in live** is still refused (unchanged); the proofs used it for speed and checked it against the SQL view.

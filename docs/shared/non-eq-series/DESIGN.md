# non-eq-series: design note (PROPOSAL ONLY, nothing is built)

Owner rule (fixed): buy only on EQ series. NEVER buy a stock in BE, BZ or any other restricted series. A held position in such a stock may be held or sold. Eligibility, ADTV, liquidity filters and ranking use EQ rows only.
Evidence is in `Claude_Docs/NON_EQ_SERIES_STAGE1_REPORT.md` (archive of 3,416 original files; inventory tables in `Claude_Docs/non_eq_series/`).

## 1. The tables at a glance

| # | Item | Proposal |
|---|---|---|
| 1 | New table | `market_data_non_eq` in the same `finsight.db` |
| 2 | Columns | `id` INTEGER PK AUTOINCREMENT, `symbol` TEXT, `trade_date` TEXT (ISO), `series` TEXT, `isin` TEXT, `open_raw` `high_raw` `low_raw` `close_raw` REAL, `prev_close` REAL, `volume_raw` INTEGER, `trades` INTEGER, `traded_value` REAL, `source_file` TEXT (original file name), `created_at` |
| 3 | Key | UNIQUE (`symbol`, `trade_date`); indexes (`trade_date`), (`isin`, `trade_date`) |
| 4 | Series column | `series` holds the code exactly as filed (BE, BZ, BL, SM, ST, ...). Which codes count as "restricted" is a short list in config, not a filter at load time, so no data is dropped |
| 5 | ISIN column | `isin`, 12 characters; the only reliable link across renames (the lake stores the latest name on old dates for 353,096 rows, the raw file the name of the day) |
| 6 | What is loaded | Every non-EQ row of the equity section of the file, except index and non-INE-ISIN debt/fund codes if the owner wants them left out (open question Q1). EQ rows stay where they are, in `market_data_lake`, unchanged |
| 7 | Guard class | DATED_APPEND_ONLY, `date_col=trade_date`, key (`symbol`, `trade_date`), volatile (`id`, `created_at`); one `Rule(...)` in `stockbot/data/guard/registry.py` (R5: `install`/`ensure` refuse a table with no class) |
| 8 | Seal at backfill | Sealed through 2026-10-16 (the lake's last date) after the load is verified against the archive: per-day row count equals the file's non-EQ rows |
| 9 | One series per symbol per day | Enforced by the key, and by a check that no (symbol, date) exists in both tables (test + audit query) |

### Writer and daily job (proposal)
- Backfill: a one-off script reads the archived files (`MANIFEST.csv` gives file name and sha256; the loader refuses a file whose sha256 differs), inserts non-EQ rows through `guard.connect_writer`, then `seal market_data_non_eq 2026-10-16`. It runs only after approval, with the usual backup and per-table proof.
- Daily: the existing downloader (`stockbot/data/ingestion/bhavcopy_ingestor.py`) already fetches the whole file and throws the non-EQ rows away. It would (a) save the original file to the raw archive, (b) pass EQ rows to `store_day` as today, (c) pass non-EQ rows to a new `store_day_non_eq` (same pattern: `refuse_if_sealed`, delete+insert in one transaction on an unsealed day), (d) seal BOTH tables for the day only after both writers finished (the rule already in GUARD.md: seal once all writers of a day are done).
- Gap to note: the lake and the archive both end on 2026-10-16; days after that are in neither.

## 2. How the engine reads it

| Read | Source | Change |
|---|---|---|
| Universe (`symbols_trading`), eligibility, ADTV (`adtv`), listing age (`symbol_info`), strategy signals (`raw_bars`, `adjusted_bars`) | `market_data_lake` only (EQ) | NONE. These methods keep their SQL; the non-EQ table is never joined into them. This is what makes "eligibility, ADTV, ranking use EQ only" structural, not a rule someone has to remember |
| Marks, stops, exits, corporate actions of a HELD position | EQ bars plus non-EQ bars of the same stock, merged by date | NEW methods only (below) |
| Entry candidates, fills of new tickets | EQ bars only | NEW explicit series gate (section 3) |

Files and functions to change (stage 2, after approval):
- `stockbot/data/asof.py` (`AsOfView`): add `held_raw_bars(symbol, lookback, start, end)` (EQ rows UNION non-EQ rows for the symbol chain, sorted by date, a duplicate date keeps the EQ row and is a test failure), `held_adjusted_bars(...)` (same corporate-action code on the merged raw series), `series_on(symbol)` (series of the stock's bar on `as_of`: "EQ", a code, or None), `_non_eq_bars_physical(symbol, ...)` (SQL primitive). All gated by a switch (below); with the switch off or the table absent they return exactly `raw_bars`/`adjusted_bars`.
- `stockbot/data/asof_memory.py`: `_Tables` loads the non-EQ table lazily (only when the switch is on); `MemoryAsOfView` overrides `_non_eq_bars_physical` (same pattern as `_raw_bars_physical`). The SQL/memory equivalence test is extended.
- `stockbot/engine/decide.py`: `bar_of(view, symbol)` stays EQ-only (used for fills). Add `held_bar_of(view, symbol)` and use it in step 3 (stepping open positions) and in the stale test.
- `stockbot/engine/stale.py`: `no_bars_for` reads `held_raw_bars`, so a bar in ANY series counts as a bar.
- `stockbot/engine/path.py` (`simulate_ticket`, used by the matched-random baseline): same two substitutions.
- `stockbot/strategies/*/exits.py` (ATR of a held position uses `view.adjusted_bars(position.symbol)`): unchanged in the first build, so the ATR comes from EQ history only (open question Q4).
- Switch: environment `STOCKBOT_NON_EQ=held` (default off), printed in the run and written into the manifest like `asof_view`; it is NOT part of `shared_config_hash` so existing hashes do not move. With it off, every stored result reproduces byte-identically (test: golden fixtures).

## 3. The never-buy rule, in the SHARED engine

| Layer | Where | What it does |
|---|---|---|
| L1 structural | `eligible_symbols` (`stockbot/universe/eligibility.py`) | reads `symbols_trading()` = EQ lake rows only: a stock with no EQ bar on the day is not even offered to a strategy. Unchanged |
| L2 proposal gate | `stockbot/engine/decide.py`, proposal loop (next to the `NOT_ELIGIBLE` check) | `if view.series_on(p.symbol) != "EQ"`: `Blocked(sid, p.symbol, "NOT_EQ_SERIES", "propose")`. Covers a strategy that proposes a symbol it was not handed |
| L3 fill gate | `decide.py` step 2, before `fill_ticket`; same check inside `engine/path.py` for the baseline | the ticket made on T is filled at the open of T+1 only if the stock is EQ on T+1: else `Blocked(..., "NOT_EQ_SERIES_AT_FILL", "fill")`. A stock that moved to BE overnight is never bought |
| One function | `stockbot/engine/series_rule.py: is_buyable(view, symbol)` | used by L2, L3 and `path.py`; no strategy code is involved or can bypass it |

Test that proves it (`tests/unit/test_never_buy_non_eq.py`, fixture lake + non-EQ table):
1. Stub strategy proposes every symbol every day, including a symbol that is BE on the as-of day: no `Ticket` for it, `Blocked` has `NOT_EQ_SERIES`.
2. A symbol EQ on T and BE on T+1 with a ticket from T: no `Fill`, `Blocked` has `NOT_EQ_SERIES_AT_FILL`.
3. Property: over a randomised fixture (stocks switching series at random dates), for every `Fill` in the run, the (symbol, fill date) row is series EQ in the series source.
4. A position held BEFORE the switch is still marked, stopped and sold on BE/BZ bars (the rule is about buying only).
5. Static test: `Position(` is constructed only in `engine/fills.py::fill_ticket`, so no other path can open a position.

## 4. EQ to BE/BZ and back

- One bar per (symbol, date) across both tables (key + check). `held_raw_bars` is therefore a plain merge: no double counting, no gap while the stock trades in any series.
- Corporate actions and adjusted prices: the existing adjustment code runs on the merged raw series (same ISIN chain, same ex-dates).
- Stale rule (20 sessions without a bar): unchanged in form; a BE/BZ bar now counts as a bar, so a stock that trades in BE is not stale. SYMBOL_NO_BARS then fires only when NO series has a bar for 20 sessions (merger, delisting, suspension: for example GSKCONS and JBCHEPHARM in the stored results, which have no row in any series after their last EQ date). The closing price is the last available close of either series.
- Coming back to EQ: eligibility reads the last 20 EQ bars wherever they are in time, so a stock back in EQ after a long BE spell can pass the ADTV test on old EQ bars. That is existing behaviour and is not changed here (open question Q3).

## 5. Fill model for BE/BZ sells (PROPOSED fixed rule; numbers are the owner's to confirm)

| Item | Proposal | Assumes / unknown |
|---|---|---|
| Order type | A sell exit is a limit order at the stop price (stop exits) or at the open (policy exits) | the stop is a trigger the bot places and watches; real execution unknown |
| Fill condition | Fills only if the bar traded at that price: stop exit needs `low <= stop <= high`; if the bar opens below the stop, fills at the open (existing gap rule) | prints in the file are real trades; queue position unknown |
| Locked bar | If `high == low` and volume small (single-price bar, typical of a circuit lock) the sell does not fill that session | the files carry NO price-band column; band at the time is unknown (5% is common but not given) |
| Size cap | Sell at most 10% of the bar's volume per session (proposed); the rest carries to the next session; a position of zero volume days waits | the 10% is a proposal, not evidence; trade-for-trade volume is thin (median BE row 16,015 shares, 78 trades; p10 525 shares) |
| Slippage | Twice the normal exit slippage (proposed) | no data on the spread |
| Costs | The existing sell cost model (delivery) | same charges as EQ assumed |
| Delivery only | A held position is a delivery holding, so no intraday rule applies | in trade-for-trade, buy and sell cannot net within a day |

## 6. What a re-evaluation would be
- A NEW registered trial per strategy (a new family row, e.g. family batch 5), run once under the same rules as before; every stored result and ledger row stays as recorded; no old run is re-run.
- Differences from the registered runs, stated in a new pre-registration: the switch `STOCKBOT_NON_EQ=held`, the BE/BZ fill model above, and nothing else (same windows, parameters, gates).
- Needs: table loaded and sealed; the engine changes in sections 2 and 3 with tests; the fill model implemented in `engine/stepping.py` (sell path) and `engine/path.py`; the comparison defined in advance (which gates move, how K counts the new trials).
- Not run in stage 1.

## 7. Risks and open questions for the owner

| # | Question or risk |
|---|---|
| Q1 | Load all non-EQ series or only BE/BZ (+ BL, SM, ST)? Debt/ETF-like codes (N*, GB, TB ...) are rows of no use to a stock engine |
| Q2 | Fill-model numbers (10% of volume, double slippage, lock rule): accept, change, or require data first (the band file is a separate NSE download, not archived here) |
| Q3 | A stock back in EQ after a long BE spell: should eligibility require 20 RECENT EQ sessions? (changes the universe, so it would be a separate approved change) |
| Q4 | Held-position ATR (exit policies) reads EQ history only: accept, or read held bars |
| Q5 | Lake symbol names vs raw file names differ for 353,096 rows (renamed stocks carry the latest name); the loader must join by ISIN. Confirm this is intended |
| Q6 | The archive and lake end on 2026-10-16; the daily job has not loaded later days: backfill before any stage 2 |
| R1 | Several stale exits in the stored runs happened on the same few dates for many names (for example 2021-06-08/09), so BE periods cluster; a re-evaluation changes many trades at once |
| R2 | In the stored stale cases the stock traded in BE for 20+ sessions at prices both above and below the last EQ close: a re-evaluation can improve or worsen individual trades; stage 1 makes no claim either way |
| R3 | The guard seals the new table; a late correction of the archive means a guard `correct` |

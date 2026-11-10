# StockBot: interactive data guide (report)

Documentation only. No change to the engine, config, schema, data or any shared package. `finsight.db` was opened only through `open_lake` (`mode=ro`) and is byte-identical before and after (sha256 below). The data-guide HTML was the only thing built; nothing else was started.

## 1. What was built

`docs/guides/data_guide.html`: one self-contained file, everything inline (CSS, JavaScript, SVG, data). Double-click opens it; no network request, no external font, script, image or library. Same build approach as the codebase guide: the page is a pure function of `docs/guides/data_guide_data.json` (the content, a `source` on every item), `docs/guides/data_catalogue.json` (the measured numbers, dated) and `docs/guides/data_guide_template.html`.

| file | size |
|---|---|
| `docs/guides/data_guide.html` | 250,787 bytes |
| `docs/guides/data_guide_data.json` (146 `source` fields) | 87,504 bytes |
| `docs/guides/data_catalogue.json` (machine-measured export) | 90,182 bytes |
| `docs/guides/data_guide_template.html` | 77,627 bytes |
| `stockbot/data_checks/data_guide_html.py` (builder, standard library) | 3,989 bytes |
| `scripts/build_data_guide_html.py` (wrapper) | 443 bytes |
| `tests/unit/test_data_guide_html.py`, `tests/unit/test_data_catalogue_json.py` | 20,672 and 4,586 bytes |
| `docs/guides/screenshots/data_*.png` (47 files, palette-compressed) | 1.47 MB |

### Per view (12 tabs, all built as written)

1. **Big picture.** Red banner "The lake (finsight.db) is read-only for the engine" and a "READ-ONLY FOR THE ENGINE" ribbon on the lake box. A "Heads up" strip of 6 dated facts (lake's last session; no daily loader, marked Missing; ASM/GSM only from the first snapshot day; calendar start; raw prices and EQ only; actions already announced for later). Seven boxes (lake, `state/live_state.db`, the ASM/GSM snapshot database, `data/reference/`, the trial ledgers, ticket files, backups); each opens a panel with where it lives, size, who writes it, who reads it, and whether the engine may touch it.
2. **Table map.** All 26 objects (25 tables plus `sqlite_sequence`) as cards in 8 colour groups, each with a row-count badge and its measured date. Filter "Used by the engine" (6 tables) versus "Everything"; a search box that matches table and column names and says which column matched. The panel has the plain purpose, rows, first and last date, distinct dates and symbols (each dated), keys and indexes, every column (type, meaning, measured example), where the data came from, who reads it, known issues, triggers, and three sample rows.
3. **How tables relate.** Interactive ER diagram of 14 tables and 14 links. Selecting a table lights its links; five link types (`symbol`, `isin`, `trade_date`, `ex_date`, `query_symbol`) can be picked and each has a one-line meaning. Every line is dashed and labelled "logical link, not an enforced key" (the env-gated test confirms the database declares no foreign keys).
4. **Source to engine.** Animated flow: 5 NSE sources, scripts, tables, AsOfView methods, engine. Back / Next / Play / Reset over 7 steps; moving dashes show data arriving at the current step. Two nodes are drawn red-dashed and labelled MISSING: the daily loader (staging to lake) and the daily ASM/GSM scheduler. The one-time swap is an amber dotted edge, never a daily one. Click any node for detail.
5. **One price row.** A made-up row ("EXAMPLE, NOT REAL DATA") followed through 6 stages: raw file line, checks, staging row, fetch-log row, lake row, freshness check. Changed fields are highlighted.
6. **Time travel (AsOfView).** A slider over 12 made-up sessions of a made-up share with a 1:10 split. Visible bars are solid, hidden bars are dashed outlines; `raw_bars(..., lookback=5)` shows the rows returned; `corporate_actions()` shows the split as **not applied** before its ex-date and as applied from it; "Ask for a later bar" shows the real error text (`FutureDataError: end 2030-01-03 is after the as-of date 2030-01-02`). Presets: before the split, on the ex-date, after.
7. **Corporate actions.** Before/after chart (Raw / Adjusted / Both) and the table of the 7 action types with measured, dated counts, symbols and ex-date ranges, and a Yes/No column for "engine adjusts prices": SPLIT and BONUS yes, the other five no. A plain line says what that means. Each type opens a panel (effect on history prices, effect on an open position, measured evidence-tier counts).
8. **Coverage.** Four charts from measured data, each labelled with its measured date and with a "Show the numbers" table: rows, sessions and equity symbols per year 2013 to 2026 (years that include sessions before the Nifty calendar starts are hatched) and results board meetings per year. Also the first Nifty date, the last date in the lake, earnings coverage, ASM/GSM snapshot days and how many equity symbols still trade.
9. **Known issues.** 8 cards: KI-001 to KI-004, EQ-series-only gaps, missing announcement dates, missing daily loader, and the calendar start. Each has an icon, what it is, "What this means for a backtest" in one sentence, and a plain-text pointer to the DATA_GUIDE section.
10. **Other databases.** `state/live_state.db` (meta, journal, snapshot, the two append-only triggers) with a 4-event animation of a journal folded into state, a button that tries an UPDATE (refused with `journal is append-only`) and one that rebuilds from the journal. The ASM/GSM snapshot database. The `data/reference/` files with measured row counts, purpose and readers.
11. **Ask the data.** 11 questions, each answered with its table(s) (click to open the table). The five read-only SQL examples with a "Copy SQL" and a "Copy as command" button each, and the exact command pattern (`sqlite3.connect('file:finsight.db?mode=ro', uri=True)`).
12. **Glossary.** 36 terms, searchable, with the same hover / focus / tap definitions as the codebase guide (underlined once per container). The file is self-contained (its own terms, not a shared list).

Light, dark and auto theme; one colour per data group, used in the legend, cards, diagrams and panels; keyboard accessible (tabs with arrow keys, every drawing node focusable, Esc closes panels, arrow keys step the steppers); breadcrumb and Back button; usable at 390 px.

## 2. Numbers: where they come from

* `py scripts/gen_data_catalogue.py --json` (new flag; `--json-only` leaves the markdown untouched) writes `docs/guides/data_catalogue.json` from `sqlite_master` and read-only SELECTs: objects, every table (columns, indexes, counts, date range, distinct dates and symbols, sample rows), per-year coverage, action counts by type and tier, earnings and ASM/GSM coverage, and row counts of the `data/reference` CSVs. It carries `measured_at` (**2026-11-10 08:56**), the database size and modified time. It took 5 min 9 s. The markdown output of the generator is unchanged and was not regenerated.
* In `data_guide_data.json` a measured number is a token such as `{{m:coverage.lake_last_date}}`, filled from that export when the page is shown. Numbers I quoted by hand carry a `when` label (`measured 2026-11-09 (DATA_GUIDE)`, `from report ...`, `code searched ...`). A test fails if a number of three digits or more appears without a token or a label.
* The measurement date is 2026-11-10; the DATA_GUIDE was measured 2026-11-09 on the same file (unchanged since 2026-11-08 12:38:02). Every number I compared is equal (see the spot-checks).

## 3. Tests

| check | before | after | note |
|---|---|---|---|
| G1 (`tests/unit` + `tests/integration`) | 520 passed, 2 skipped (from my previous report, at 412a298) | 551 passed, 8 skipped, 1 failed (the git-tracking test, which passes once the wrapper is added; 29 passed in that file with it staged) | +4 export tests, +27 guide tests; the 6 new env-gated tests are skipped in G1 |
| G3 (`tests/unit/test_g3_fixture_baseline.py`) | 2 passed | 2 passed | |
| G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 py -m pytest tests`) | 643 passed, 0 skipped | **NOT RUN to completion.** The run was killed by the system for low memory; per the standing rule it was not restarted. The 6 env-gated guide tests were run on their own against the real lake (33 passed in the guide test file, 57 s). Pushed with G2 not run, on the owner's instruction | the 6 env-gated guide tests ran against the real lake, read-only |
| G4 `finsight.db` | sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, modified 2026-11-08 12:38:02, 3,432,767,488 bytes | **identical** (re-hashed after the killed G2 run) | hashed at the start, after the export, after the spot-checks, after G2 |

Counts did not fall. The one failure seen in a G1 run before the commit (`test_every_wrapper_and_the_provenance_readme_is_tracked_by_git`) is the "tracked by git" rule for the new wrapper; it passes once `scripts/build_data_guide_html.py` is added to git, and it was re-run and passed with the file staged.

**New tests.** `tests/unit/test_data_catalogue_json.py` (4 tests): written first and shown failing (4 failed with the function missing), then implemented. `tests/unit/test_data_guide_html.py` (27 offline tests + 6 env-gated): **written after the page existed**, not before. To show they can fail, I seeded 22 defects into the real files (restored afterwards, byte-identical) and a control run: the control passed and **22 of 22** defects were caught by the intended test: a table dropped from the guide; an invented column; a real column with no meaning; a missing path; a function not in its file; a number with no date label; an unresolved token; a 45-word panel; a SQL example with an invented column; a SQL example that writes; a command pattern that is not read-only; a missing glossary term; an ER edge to an undrawn table; a split series that shows no drop; the missing loader drawn as existing; the JSON edited without rebuilding; a web address added; an external script tag added; a table added to the catalogue; an index added to the catalogue; and (env-gated, with a tiny throw-away database via `STOCKBOT_DB`) a lake table the guide does not describe and a guide table the lake does not have.

What the tests check: every path, script, module and `path::name` named in the JSON exists; every table of the catalogue is in the guide and every guide table is in the catalogue; every column has a plain meaning and no meaning names a missing column; every measured token resolves; every number has a date label; panel text is 40 words or fewer; no `http://` or `https://` and no external resource in the HTML (script, link, image, frame, `fetch`, `@import`, `url()` except in-page markers, and so on); the HTML equals `build(JSON, template, catalogue)`; the SQL examples are SELECTs over columns that exist; the command pattern really runs read-only against a temporary database and refuses a write. Env-gated (`STOCKBOT_DATA_TESTS=1`): every table, view, index and trigger in `sqlite_master` appears in the guide; every table and column in the guide exists; the database declares no foreign keys; the catalogue's row counts equal the live counts; the five SQL examples run against the real lake and a write is refused.

## 4. Browser checks

Headless **Chrome 156** driven through the DevTools protocol (script in my scratchpad, not in the repository). **Only Chrome was tested** (not Edge or Firefox); the 390 px runs are an emulated phone viewport, not a real phone.

* **Screenshots (47)** in `docs/guides/screenshots/`: every one of the 12 views at 1280 px and 390 px (`data_<view>_desktop.png`, `data_<view>_phone.png`); panel-open or step states at both widths (`data_big_lake_*`, `data_tables_market_data_lake_*`, `data_relations_market_data_lake_*`, `data_flow_4_*`, `data_flow_node-g1_*`, `data_time_7_*`, `data_time_10_*`, `data_actions_SPLIT_*`, `data_ask_3_*`); and five dark-mode states (`data_big_x_dark`, `data_tables_corporate_actions_log_dark`, `data_relations_market_data_lake_dark`, `data_time_5_dark`, `data_coverage_x_dark`).
* **Console:** across all 47 states and 55 scripted interactions: **0 uncaught exceptions, 0 console errors or warnings, 0 browser log errors.** Also in every state: no horizontal overflow at 1280 or 390 px, and no leftover `{{`, `undefined`, `NaN`, `[object` or escaped tag text in the visible page.
* **Interactions scripted (55 of 55 passed):** heads-up strip has 6 dated items; 7 database boxes; the lake box opens a panel with the read-only badge; Esc closes; 26 table cards; the engine filter leaves the 6 engine tables; search by column name narrows and names the matching column; a nonsense search shows "no match"; the `corporate_actions_log` panel shows 22,997 rows, 12 columns and 3 sample rows with the measured date; the triggers are listed on `trade_analytics_log`; `sqlite_sequence` says "not measured"; the ER view has 14 nodes and 14 dashed edges, selecting the lake lights 8 links and a link type lights the right edges; the flow has 23 nodes with 2 marked missing; Next reaches step 7 and disables; Back; Reset; Play advances by itself; step 4 lights the missing link; the missing loader's panel carries the missing badge; the price-row steps and EXAMPLE label; the time slider hides and shows bars; the FutureDataError text (both for a middle date and for the last date); the split is "NOT applied" before its ex-date and "applied" on it; presets; the URL follows the slider; the action table says Yes for SPLIT and BONUS and No for the other five; the chart mode toggle; the SPLIT panel; 4 dated charts and 14 year bars; 8 issue cards with an icon and a backtest sentence; the journal animation (4 rows, cash 823,372.2 after the fill); an UPDATE is refused with `journal is append-only`; rebuild reports equality; every reference file has a measured row count; the question picker; Copy as command puts the full command text on the clipboard; the glossary search; a tooltip on a term; ArrowRight on a tab; the theme button; on a phone: flow becomes lane cards, ER becomes a list of 14 buttons, the time charts fit, the table panel is a bottom sheet.
* **I looked at 14 of the 47 screenshots by eye** (big picture, flow, relations light and dark, time 7, coverage, tables panel desktop and phone, corporate actions, known issues, other databases, ask, price row, flow phone, time phone). Two defects were found that way and fixed (arrowheads scaled with line width; an escaped `</code>` in the trigger line of the Other databases view). The other 33 were checked only by the automated overflow and leftover-text tests, not by eye.
* **Offline:** the browser's network log for the whole run contains **one request, the page itself** (`file:///.../data_guide.html`). The page text has no web address at all: the catalogue's sample rows contain real NSE file URLs, and the builder replaces them with "(a web address, not shown)" so the page names none (a test covers that).

## 5. Ten spot-checks (page against the live database and the code)

The facts were read out of the page's own embedded data, then checked read-only against `finsight.db` and the code. I ran a pool of 22 and all 22 matched; the ten below were drawn at random from the pool (fixed seed 20261110).

| # | fact on the page | checked against | result |
|---|---|---|---|
| 1 | First Nifty date (calendar start): 2015-11-09 | `select min(trade_date) ... symbol='NIFTY50_INDEX'` | match |
| 2 | 90 corporate actions have an ex-date after the lake's last session | `corporate_actions_log` where `ex_date` > `max(trade_date)` | 90, match |
| 3 | Trigger `trg_tal_no_update` on `trade_analytics_log` aborts with "append-only" | `sqlite_master` (table name and trigger SQL) | match |
| 4 | Results board meetings in 2025: 18,069 | `earnings_board_meeting` where `is_results_meeting=1`, year 2025 | match |
| 5 | ASM/GSM snapshot: GSM 76 rows on 2026-11-08 | `asm_gsm_daily_snapshot` | match |
| 6 | 934 equity symbols end before the last session | grouped `max(trade_date)` per symbol | 934, match |
| 7 | Query 3 returned 249 sessions in 2025 | the SQL on the page, run read-only now | 249, match |
| 8 | `sector_map.csv` has 501 data rows | the file | 501, match |
| 9 | The database declares no foreign keys | `pragma foreign_key_list` on every table | none, match |
| 10 | The state store refuses a file named `finsight.db` | `stockbot/live/state_store.py` lines 41 and 42 | match |

The other twelve in the pool also matched: the lake's row count; the last session date; 249 sessions in 2024; SPLIT rows; the real column list of `bhavcopy_fetch_log`; the real index names of `corporate_actions_log`; the `FutureDataError` text equals what `AsOfView.raw_bars` raises; the freshness check raises `DataFreshnessError` ("the lake's latest session is 2026-10-16, not 2026-10-20"); the factors (SPLIT 1:10 is 0.1, BONUS 1:1 is 0.5, DIVIDEND and RIGHTS 1.0) come from `adjustments._action_factor`; query 2 returns the SBIN split of 2014-11-20; the journal trigger message equals the code; and `BhavcopyIngestor` has no caller anywhere in the repository (so "daily loader: missing" is true of the code as it stands). The SQL command from the page was also run in PowerShell as printed: it returned the five RELIANCE rows of the DATA_GUIDE, and an INSERT passed the same way was refused with "attempt to write a readonly database".

## 6. Deviations, limits and things to know

* **One change outside the new files:** `stockbot/data_checks/data_catalogue.py` gained `--json` / `--json-only`, a JSON export, row counts of the reference CSVs, and five extra read-only queries in `coverage()` (lake first and last date, Nifty first date, action counts by type and tier, actions after the last session). It is a data-check tool I wrote in the guides task, not a shared package; its markdown output is unchanged (not regenerated). `docs/guides/CODEBASE_GUIDE.md` and `DATA_GUIDE.md` got the rows and a pointer sentence that the consistency tests require.
* **The command pattern differs from the DATA_GUIDE's.** The DATA_GUIDE writes the SQL inside the command text, which breaks for queries that contain single quotes (all five do). The page passes the SQL as an argument (`... print(c.execute(sys.argv[1]).fetchall())" "SELECT ..."`) and still opens with `mode=ro`.
* **Eight issue cards, not seven:** I added "The calendar starts 2015-11-09" because the DATA_GUIDE lists it as a known issue.
* **Grouping judgement:** the brief's eight groups are used. `isin_symbol_map` sits in "Corporate actions", `securities_master` and `shares_outstanding` in "Shares and listings", the empty legacy tables in "Legacy dashboard" (they show 0 rows), and `asm_gsm_list`, `earnings_calendar` and `sqlite_sequence` in "Empty or unused".
* **Table panels are longer than 40 words** (they list every column). The one-line card, the purpose text and every step or explanation panel are capped at 40 words by a test.
* **The adjusted series in the time-travel and corporate-action views is drawn by the page's own JavaScript** (earlier bars times 0.1 when the ex-date is on or before the as-of date). It is not the Python `get_adjusted_series`; the factor rule was checked against the code (spot-check above), the series itself is invented.
* **Made-up dates:** the example share, its prices and its dates (2030) are invented and labelled so, in every view that uses them.
* **Sample rows** in the catalogue export have floats rounded to 4 decimals and text cut at 80 characters; blobs show only their size.
* **Not measured by the generator, quoted from the DATA_GUIDE with their dates:** the ASM/GSM snapshot database's file size, the trial-ledger file sizes, the 57 verified events, the numbers in the known-issues cards that come from named reports. I did open the snapshot database read-only on 2026-11-10 to list its tables (the same three as the lake, with the same row counts 253, 2 and 2).
* **Phone layout:** the ER diagram and the flow diagram become lists of buttons (flow as one card per lane) at 700 px and narrower; the charts and the time-travel drawing stay graphical.
* **Not verified:** Edge and Firefox; a real phone; any screen reader; numeric colour contrast; 33 of the 47 screenshots by eye.
* **Footer commit:** the footer says "built from commit 412a298", the parent of the commit that contains the page (a page cannot contain its own commit id).
* The catalogue export has to be regenerated (about five minutes, read-only) when the lake changes; the env-gated tests fail if it is out of date.

## 7. Commits

COMMITS_PLACEHOLDER

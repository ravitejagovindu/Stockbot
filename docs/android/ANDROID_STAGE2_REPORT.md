# Android app, stage 2 report: the API contract is frozen

## Summary

The API contract for StockBot Paper is written, frozen as `apiVersion` 1, and the app now speaks it. The owner's five decisions are implemented as given: money in integer paise, footer figures from the server, Nifty sent rebased, the three enums (with the engine's real labels mapped onto them), and the new freshness rule. The app still has no backend and no INTERNET permission; its mock data is now the contract's example JSON files, parsed with the same code the network repository will use.

- Branch: `android-contract` (pushed, not merged). Only files under `android\` and `docs\android\` changed.
- Tests: 47 JVM tests, 0 failures. Lint: 0 errors, 5 warnings (the same 5 as stage 1, none new).
- The engine, scheduler, Python code, `finsight.db`, `state\` and every lock were only read, never run or changed. No Gradle ran in the 19:25 to 20:15 IST window.
- Serialisation: `kotlinx.serialization-json` 1.7.3 (it was in the local Gradle cache), so the `org.json` fallback was not needed.
- The main input for stage 3 is the "Gaps the backend must fill" list in `docs/android/contract/SOURCE_MAP.md`, summarised below.

## Contract files (`docs/android/contract/`)

| File | Content |
|---|---|
| `openapi.yaml` | OpenAPI 3.0: `GET /v1/health`, `/v1/today`, `/v1/account`, `/v1/positions`, `/v1/trades`; header `X-Paper-Token`; error body with `UNAUTHORIZED` (401), `NOT_READY` (503), `SERVER_ERROR` (500); nullable fields marked, lists never null. The file parses as YAML; it was not run through an OpenAPI validator (none installed) |
| `examples/` | 28 JSON files: `today_`, `account_`, `positions_`, `trades_` for each of EMPTY, SIGNAL_DAY, POSITIONS, TRADES, DEEP_DRAWDOWN, STALE (24), plus `health_ok.json` and `error_unauthorized.json`, `error_not_ready.json`, `error_server_error.json` |
| `CONTRACT.md` | The frozen contract: one table per response (field, type, unit, null, screen), conventions, error codes, enums with the engine mapping, versioning rule, refresh rule |
| `SOURCE_MAP.md` | For every field, where the backend gets it, and the gaps |

The EMPTY examples match the real state: starting capital and equity 20,000,000 paise, no tickets, no positions, no trades. (The real tickets file `state/tickets/tickets_2026-11-23.json`, read only, has empty lists; EMPTY therefore uses data date 2026-11-23.) Every scenario's figures reconcile, and a test checks it (equity = cash + positions marked at last close; returns from equity and start; curve starts at the starting capital and ends at equity; drawdowns match the curve; footers match the trade list). DEEP_DRAWDOWN has its own 25 closed trades (9 wins, 16 losses, profit factor 0.79) whose sum is exactly the fall from the starting capital to the equity, and whose running total is the curve: peak 260,000 rupees after the 10th trade, trough 175,500, now 179,400 (31.0% below the peak, worst 32.5%). This fixes the stage 1 inconsistency.

## Engine enum mapping

Full tables with every label found are in `CONTRACT.md` (section "Engine mapping"). In short:

- **Exit reason.** The engine books `STOP_HIT` (and records a gap as a session flag `GAP_THROUGH_STOP`, not as a reason string): `STOP_HIT`, or `GAP_THROUGH_STOP` when that flag is set for the symbol that session. Everything else maps to `OTHER`: `TIME_EXIT` (library fixed-hold policy), `POLICY_EXIT`, `SYMBOL_NO_BARS`, `END_OF_WINDOW` (backtest only), `OPERATOR_EXIT`, `MANUAL`, `TIME_DECAY`, `EARNINGS_EXIT`, `OTHER`, `UNKNOWN`.
- **Block reason.** `BLOCKED_BY_RISK(sector_<S>:...)` is `SECTOR_CAP`; `BLOCKED_BY_RISK(positions:...)`, `(total_risk:...)` and plain `BLOCKED_BY_RISK` are `RISK_CAP`; `SIZE_ZERO` at the fill stage is `CASH` (the nearest the engine has); all others (`SIZE_ZERO` at sizing, `NONPOSITIVE_RISK`, `ALREADY_HELD`, `SYMBOL_HELD_BY_OTHER_STRATEGY`, `NO_BAR_OR_ALREADY_HELD`, `NOT_ELIGIBLE`, `DUPLICATE_PROPOSAL`, `NOT_EQ_SERIES`, `NOT_EQ_SERIES_AT_FILL`, `MARKET_SWITCH`, `STRATEGY_NOT_REGISTERED`, `CORP_ACTION_ON_EXEC_DATE`, `GAP_THROUGH_STOP` at entry, `GAP_UP_TOO_LARGE`, confirm-fill verdicts) are `OTHER`.
- **Side.** The engine has no side field: a pending ticket is a BUY, a position with a queued exit is a SELL.

## Gaps the backend must fill (input for stage 3)

Detail and reasoning are in `SOURCE_MAP.md`. None needs an engine change.

1. **Paise rounding.** The engine uses float rupees; round each stored value to paise and build totals from the rounded parts so the identities hold exactly.
2. **Start date and daily equity curve.** The account's start date is not stored (the `init` row has session `0000-00-00`); the first processed session (2026-11-23) is the proxy. No daily equity series is stored: fold the journal session by session and mark each state.
3. **Nifty rebasing.** Nothing computes it. Read `NIFTY50_INDEX` `close_raw` from the lake and rebase it to the starting capital on the start date, in paise.
4. **`GAP_THROUGH_STOP`.** Only a session flag in the engine; join the closed trade to the flags of its exit session by symbol.
5. **Block reasons.** Free text; the risk reasons need parsing. There is no cash reason, and `Blocked` carries no sector (look it up in `data/reference/sector_map.csv`).
6. **`expectedAsOf`.** No holiday-aware calendar and no time-of-day rule exist (`runner.expected_session` is "latest weekday"). Needed: a calendar and a rule for before and after the 19:30 job.
7. **Review marks and verdict.** The 35% mark, the 30 closed trades and "not demonstrated" are only in the paper README, not in any config.
8. **`isSignalDay` and `nextSignalRule`.** Computable from the lake calendar (`is_signal_session`) but stored nowhere; the rule text is a constant.
9. **Drawdown history.** Not stored; computed from the curve of gap 2.
10. **Closed-trade definition.** Decide whether rows flagged `excluded_ca` count (default proposed: exclude them from counts and stats).
11. **Reads during the jobs.** The state and lake databases can be locked while the 19:30 jobs write; read read-only with a timeout and answer `NOT_READY` rather than a partial result.
12. to 15. Held-by-hand positions, sector for a position (not needed), plain-words text for a pending exit, and the token check and hosting (stages 3 and 4).

Not gaps (the stage 1 draft guessed they might be): the trade R value (`net_pnl / risk_inr` is on the closed trade), the exit reason (on the closed trade), and the position sector (on the position).

## App changes

- `Models.kt`: `@Serializable` models in paise (`Long`), with the envelope fields; `Contract.kt`: parsing, the error body, `ApiException`, and the `Freshness` rule.
- Unknown enum values become `OTHER` (exit reason, block reason, side); an unknown error code becomes `SERVER_ERROR`; unknown JSON keys are ignored; another `apiVersion` or unreadable JSON is a calm error.
- `RupeeFormat` takes paise (exact `Long` arithmetic, tested up to `Long.MAX_VALUE`).
- `MockPaperRepository` loads the example JSON through an `ExampleSource` (assets on the phone, class path in tests). A Gradle task `copyContractExamples` copies `docs/android/contract/examples/*.json` into the debug assets and the unit-test resources, so there is one source; the APK contains the 28 files.
- Stale rule: "Updated N days ago" appears only when `dataAsOf` is before `expectedAsOf` (N = calendar days between them). The old `STALE_AFTER_DAYS` constant and `staleDays` function are deleted.
- Footer figures on Trades come from `stats`; the app no longer computes them.
- The UI design, screens and themes are unchanged.

## Tests and lint

Command: `gradlew test assembleDebug lintDebug --no-daemon`: BUILD SUCCESSFUL. CODEBASE_GUIDE test only: see the last section.

| Test class | Tests | What it checks |
|---|---|---|
| `ContractExamplesTest` | 15 | Every example file parses with the matching parser; envelope and +05:30 offset; reconciliation rules above; EMPTY matches the real state; signal-day ticket sizing; TRADES 5 wins and profit factor 1.4; DEEP_DRAWDOWN's own trades; error files are thrown |
| `EnumAndFreshnessTest` | 10 | Unknown exit reason, block reason and side become `OTHER`; unknown error code and keys; other `apiVersion` refused; garbage input is a calm error; stale rule: Friday data on a Monday morning is not stale when Friday is expected, two trading days behind is stale |
| `ScenarioStateTest` | 9 | Each scenario through the repository and screen loader gives the expected state; ERROR throws `NOT_READY` |
| `RupeeFormatTest` | 8 | Paise input, Indian grouping, signs, large values |
| `ThemeModeStoreTest` | 5 | Unchanged from stage 1 |

Lint: 0 errors, 5 warnings, none fixed on purpose: four `GradleDependency` notices (newer `activity-compose`, lifecycle and `datastore-preferences` exist; versions pinned to the cached AGP 8.7.3 / Compose BOM set) and one `DataExtractionRules` notice about `fullBackupContent` (backups are off and everything is excluded).

## Deviations from the brief

1. **Report location:** the report is under `docs\android\` (the only allowed place), not `Claude_Docs\`.
2. **`Side.OTHER` exists in the app** only, as the landing place for an unknown value; the contract's side values are BUY and SELL.
3. **`TIME_EXIT` is gone** as an exit reason (owner decision): library time exits map to `OTHER`. The paper strategy's own exit is a trailing stop, so it should rarely occur.
4. **Today's blocked line** counts only `SECTOR_CAP` items ("K more were blocked by the sector cap"); blocked items with other reasons are in the data but not shown, so the screen text stays true.
5. **Additions to the contract that the brief did not spell out:** `apiVersion` also in the error body; health `status` values `ok` and `not_ready`; `stats.tradeCount` and `stats.losses`; the verdict is a plain string; `PendingFill.note` is free text; `HTTP 503` for `NOT_READY`.
6. **Pending sell in the POSITIONS example** is now "Exit queued at the close" (an engine policy exit), not "Stop reached", because the engine tests a stop on the next bar and cannot know it in advance.
7. **Mock data changed with the examples:** dates are fixed calendar dates (weekends skipped, holidays ignored), not relative to today; Today shows exact paise (for example ₹1,972.10 and ₹1,999.80 instead of rounded rupees); the POSITIONS book was entered on 2 Dec 2026 with MARUTI at -₹810; TRADES and DEEP_DRAWDOWN curves are step lines (realised P&L by exit date); the STALE scenario reads "Updated 4 days ago" (Friday data, Tuesday expected).
8. **The generator** that wrote the example files was a throwaway script outside the repository; the committed files are the source, and the tests keep them consistent.
9. **No mock data in a release build** (assets are copied for debug and tests only), so a release build would show the error screen. No release build exists; stage 4 replaces the mock path.
10. **Emulator:** it hung once during the install and was restarted.
11. **The Pixel 7 installed in stage 1 was not updated** with the new APK (not asked); it still has the stage 1 build.

## Device and screenshots

- APK: `F:\Projects\Ravi\StockBotData\android\stockbot-paper-debug.apk` (rebuilt from this branch; `aapt2 dump permissions` shows no INTERNET permission).
- `adb devices` showed the Pixel 7 (wireless) and, after I started the configured AVD (`Nexus_5X_API_31`), the emulator. All screenshots were taken on the emulator with `-s emulator-5554`; the phone was not touched. The emulator hung during the first install (restarted), and showed a "Bluetooth keeps stopping" system dialog over the first set of screenshots; I switched Bluetooth off in the emulator and re-took all of them. The emulator was shut down afterwards.
- `docs/android/screens/` holds the 8 screenshots (light and dark of Today with SIGNAL_DAY, Account with TRADES, Positions with POSITIONS, Trades with TRADES), replacing the stage 1 files, plus two extras: `extra-light-stale-account.png` (the STALE scenario: "Updated 4 days ago") and `extra-dark-account-deep-drawdown.png`.
- The screens look the same as in stage 1 (same layout, colours, fonts, spacing, both themes). What differs is data, not design: Today shows exact paise on two cards (₹1,972.10, ₹1,999.80); the Positions book shows "since 2 Dec" on every card and MARUTI at -₹810; the Trades and Account curves for TRADES are step lines; the STALE screen shows paise in the equity figure (₹2,00,826.76) because paise are shown when they are not zero.

## CODEBASE_GUIDE test

`py -m pytest tests/unit/test_guides_consistent.py`: 11 passed, 1 skipped (the data test that needs `STOCKBOT_DATA_TESTS=1`). No full suite was run.

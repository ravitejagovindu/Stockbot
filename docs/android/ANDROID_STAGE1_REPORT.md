# Android app, stage 1 report

## Summary

Stage 1 is built: a native Android app ("StockBot Paper", `com.stockbot.paper`) with four screens on mock data only. It builds, all 27 unit tests pass, lint has 0 errors, and the debug APK ran on an emulator, where I took 8 screenshots (one per screen per theme). The app is read-only: no order buttons, no broker keys, no INTERNET permission (confirmed in the built APK). No Python file, scheduler file, database or lock was touched; the branch only adds files under `android\` and `docs\android\`.

- Branch: `android-app` (pushed). Not merged.
- APK: `F:\Projects\Ravi\StockBotData\android\stockbot-paper-debug.apk` (9.5 MB, debug build).
- Stack: Kotlin 2.0.21, Jetpack Compose (BOM 2024.12.01, Material 3 1.3.1), AGP 8.7.3, Gradle 8.11.1 wrapper, JDK 21, compileSdk and targetSdk 35 (the newest installed), minSdk 26, a single module `:app`.

## Screens built

| Screen | Main question | What it shows |
|---|---|---|
| Today | What should be bought tomorrow? | Signal day: "N suggestions", "Buy at tomorrow's open. Risk 1% each.", a card per ticket (symbol, shares, entry reference, stop, risk), and "K more were blocked by the sector cap". Non-signal day: "No signal today", "Next signal: first trading day of next month", and any pending fills. |
| Account | How is the account doing? | Equity (large), account return and Nifty return over the same dates, equity curve against Nifty (Canvas, solid account line, dashed muted Nifty line), drawdown card (now, worst, review mark, thin bar with a tick at the worst point), closed trades "N of 30" with a bar, footer "Verdict: not demonstrated". |
| Positions | What am I holding? | A card per position (symbol, shares, entry date, entry, stop, last close, unrealised P&L), footer with cash and "Idle cash earns nothing". |
| Trades | How have closed trades gone? | A card per closed trade, newest first (symbol, dates, exit reason, net P&L after costs in rupees and R), footer with win rate and profit factor. |

Every screen has a loading state, an empty state (an invitation), and a one-line error with Retry. A "SAMPLE DATA" tag sits in the top bar on every screen while the mock repository is active. Money uses Indian grouping and a real minus sign, with paise only when needed.

## Themes and scenarios

- **Themes:** "calm paper" (light) and "terminal" (dark), with every value in `theme/Theme.kt`. The app follows the phone's setting by default. The "Theme: ..." text at the right of the top bar opens Light / Dark / System; the choice is saved with DataStore.
- **Scenarios (debug builds only):** long-press the top-bar title (for example "Today") to open a list of EMPTY, SIGNAL_DAY, POSITIONS, TRADES, DEEP_DRAWDOWN, STALE and ERROR. Release builds have no such menu.
- **Scripted switching (debug builds only):** `adb shell am start -n com.stockbot.paper/.MainActivity --es scenario SIGNAL_DAY --es theme DARK --es tab ACCOUNT` (tabs: TODAY, ACCOUNT, POSITIONS, TRADES; themes: LIGHT, DARK, SYSTEM). Used for the screenshots. Run `am force-stop com.stockbot.paper` first for a reliable switch.

## Tests

Command: `gradlew test assembleDebug lintDebug` (run with `--no-daemon`). Result: BUILD SUCCESSFUL.

- 27 JVM unit tests, 0 failures:
  - `RupeeFormatTest` (11): Indian grouping up to 100 crore and beyond, signs, real minus, paise only when needed, rounding, values that round to zero, percent and R.
  - `ScenarioStateTest` (11): each scenario through the repository and the screen loader gives the expected state (EMPTY, SIGNAL_DAY 3 tickets and 12 blocked, POSITIONS 4 open with mixed P&L, TRADES 12 closed with 5 wins and profit factor exactly 1.4, DEEP_DRAWDOWN 31% with the warning colour, STALE 3 days, ERROR on every screen, switching scenario). It also checks that the account, positions and trades figures reconcile where they should.
  - `ThemeModeStoreTest` (5): default System, saves each mode, survives a restart, an unknown stored value falls back to System, parsing. It uses a real DataStore on a temporary file.
- CODEBASE_GUIDE test only (`tests/unit/test_guides_consistent.py`): 11 passed, 1 skipped (the skip is the test that needs `STOCKBOT_DATA_TESTS=1`). No full suite was run.

## Lint

0 errors, 5 warnings. Not fixed, on purpose:

- 4 x `GradleDependency`: newer versions exist for `activity-compose` (1.13.0), `lifecycle-runtime-compose` and `lifecycle-viewmodel-compose` (2.11.1), `datastore-preferences` (1.3.0). I kept the versions that match the AGP 8.7.3 / Compose BOM 2024.12.01 / Kotlin 2.0.21 set already cached on this laptop; newer ones would force an AGP and Kotlin upgrade. Revisit when the toolchain is upgraded.
- 1 x `DataExtractionRules`: asks for `android:fullBackupContent` too. The app already sets `allowBackup="false"` and excludes everything in the data extraction rules, so there is nothing to back up.

Fixed: obsolete `-v26` icon folder, missing monochrome icon, missing data extraction rules.

## Device

- `adb devices` at the start: no phone or emulator connected.
- An AVD was already configured (`Nexus_5X_API_31`, SDK at `F:\Installations\Android_Sdk`), so I started it, installed the APK, took the screenshots, then shut it down (`adb emu kill`). The emulator was slow (it showed one "System UI isn't responding" dialog before the first shot, dismissed with Wait); the screenshots were taken after that.
- 8 screenshots in `docs/android/screens/`: `light-` and `dark-` plus `today`, `account`, `positions`, `trades`. Scenarios: Today uses SIGNAL_DAY, Positions uses POSITIONS, Account and Trades use TRADES (it has the curve and the closed trades). One extra: `extra-dark-account-deep-drawdown.png` shows the DEEP_DRAWDOWN warning bar.
- No build or emulator ran between 19:25 and 20:15 (all work was done before 16:00).

## Deviations from the brief

1. **Report location.** The brief asks for `Claude_Docs/ANDROID_STAGE1_REPORT.md`, but the branch may only add files under `android\` and `docs\android\`. The committed report is this file; an untracked copy was left at `Claude_Docs/ANDROID_STAGE1_REPORT.md`.
2. **No `.gitignore` change at the repo root.** The Android ignore rules live in `android\.gitignore` (inside the allowed path), so the root `.gitignore` is unchanged.
3. **Extra models.** Beyond the models listed, I added `PendingFill`, `AccountSnapshot`, `PositionsState`, `TradesState`, `TradeStats` (computed in the app), `Verdict`, `ExitReason`, `Side` and `BlockReason`. All are in `CONTRACT_DRAFT.md`.
4. **Account never shows the "empty" state.** It always has figures to show, so on EMPTY it shows 200,000 and a flat curve with a one-line invitation under the chart. Today's empty state is the "No signal today" layout.
5. **Stale rule.** "Updated N days ago" appears when the data is 3 or more days old (one constant, `STALE_AFTER_DAYS`). A normal Friday-to-Monday gap will show it on Monday until the evening job runs; the threshold is easy to change.
6. **Mock data is not reconciled across every screen.** POSITIONS and TRADES reconcile (equity = cash + positions, or start + net P&L). DEEP_DRAWDOWN reuses the 12 trades from TRADES, so its trades do not add up to its equity; a 31% drawdown cannot come from 12 trades at 1% risk each.
7. **Window background colour.** The light and dark window backgrounds (`#F6F4EF`, `#0E1116`) are repeated in `res/values*/themes.xml` so there is no flash before Compose draws. Every other value is only in `Theme.kt`.
8. **Warning colour.** The brief gave no warning colour for the drawdown bar; I added `#B7791F` (light) and `#D29922` (dark) to the theme. The bar turns warning at 75% of the review mark and loss colour at or past it.
9. **Custom bottom bar.** The bottom navigation is a plain text bar (no icons), to avoid pulling in an icon library.
10. **Gradle wrapper** was generated from the Gradle 8.11.1 already cached on the laptop; Gradle ran with `--no-daemon` so no daemon was left behind.

## Files

- `android\` (Gradle project, app code under `app/src/main/java/com/stockbot/paper/{data,format,theme,ui}`, tests under `app/src/test`).
- `docs\android\CONTRACT_DRAFT.md` (DRAFT data contract), `docs\android\screens\` (screenshots), this report.

# Stage 3 report: the paper BFF

## Summary

The paper BFF is built and tested: a read-only FastAPI service in `bff\` that serves the frozen contract (apiVersion 1) from the paper state, the tickets folder and the lake, to the Android app (not connected yet; stage 4). A smoke run against the real data passed, and the service was stopped afterwards.

- **Part A (additive contract change, done):** every closed trade is listed and counted in `closedTrades` and toward the 30-trade mark, flagged or not. A trade the engine flagged (`excluded_ca`) carries `corporateActionFlag: true`; win rate and profit factor leave flagged trades out; `stats.excludedFromStats` says how many. A position held by hand (`hold`) carries `corporateActionFlag: true`. Fields default to false and 0, so v1 stays compatible. In `openapi.yaml`, `CONTRACT.md`, the examples (exactly one flagged trade, ASIANPAINT in `trades_trades.json`, and one flagged position, SBIN in `positions_positions.json`), the app models, the card note "Corporate action: figures may be off", the Trades footer line "1 trade excluded: corporate action" (only when above zero) and the tests. The Trades footer now reads "45% (5 of 11)" because it divides by the unflagged trades; the example's profit factor is 1.62 (it was 1.4 before one loss was flagged).
- **Part B (done):** `bff\app.py`, `run.py`, `sources.py`, `builders.py`, `models.py`, `config.py`, `smoke.py`, `paper_marks.yaml`; 212 new tests in `tests\bff\`; `docs\bff\README.md`; two rows in `docs\guides\CODEBASE_GUIDE.md`.
- **Nothing existing changed:** no existing Python file was touched; the branch adds files under `bff\`, `tests\bff\`, `docs\bff\` and changes files under `android\` and `docs\android\`, plus the two guide rows.
- **Left running:** nothing. The BFF is stopped. The token file is at `F:\Projects\Ravi\StockBotData\bff\token.txt` (created once, 32 random bytes as hex; never printed, logged or committed).

## What was built

| Piece | Notes |
|---|---|
| `GET /v1/health`, `/today`, `/account`, `/positions`, `/trades` | Exactly per `openapi.yaml`. Header `X-Paper-Token`, compared in constant time. 401 UNAUTHORIZED, 503 NOT_READY, 500 SERVER_ERROR, 404 (error body) for unknown routes, 405 for any write method. |
| Network | Binds `STOCKBOT_BFF_HOST` (default 127.0.0.1) and `STOCKBOT_BFF_PORT` (default 8765; checked free; `run.py` exits 3 if it is not). TrustedHostMiddleware (default localhost and 127.0.0.1). No CORS unless `STOCKBOT_BFF_CORS` lists origins. Rotating access log `F:\Projects\Ravi\StockBotData\logs\bff.log` (path, status, time; headers never logged). |
| Refusal to start | No token in `STOCKBOT_BFF_TOKEN` or the token file: exit 2. |
| Data layer | Read-only connections (`mode=ro` plus `query_only`), 3 s busy timeout, one retry, then 503; nothing held between requests; lock files never read or written. |
| Builders | Pure functions: fold the journal, rebuild positions, cash, closed trades and the daily curve; all money in whole paise. |
| Caching | Built responses cached on (mtime and size of `live_state.db`, lake sealed-through date); `expectedAsOf` and `generatedAt` refreshed per request. No threads, no scheduler. |
| `bff\smoke.py` | Calls every endpoint on a running instance, checks statuses, envelope, reconciliation, 401 and 404. |

## How each gap in `SOURCE_MAP.md` was resolved

(The map lists 15; the stage 2 report grouped the last four as "12 to 15".)

1. **Paise.** `to_paise` rounds half up on the decimal text of the float, once per stored value. Totals are sums of those integers: equity = cash + sum(shares x last-close paise); unrealised = shares x (last - entry) paise; ticket risk = shares x (reference - stop) paise. The identities hold exactly (tests).
2. **Start date and daily curve.** Start date = the first processed session (the earliest `decisions` row; the `init` row has no real date). The curve covers the lake's Nifty trading days from the start date to the data date; each day takes the state after the last processed session on or before it and marks open positions at that day's lake `close_raw` (falling back to the latest earlier close, then to the engine's own `last_close`). A missing Nifty close on the start or data date gives 503, not a guess.
3. **Nifty rebasing.** `rebase`: starting capital in paise x close / close on the start date, half up, in `Decimal`.
4. **GAP_THROUGH_STOP.** A `STOP_HIT` closed trade becomes `GAP_THROUGH_STOP` when the `decisions` row of its exit session holds a `GAP_THROUGH_STOP` flag for the same symbol; a flag for another symbol or another day does not count (tests).
5. **Block reasons.** `BLOCKED_BY_RISK(sector_...)` is SECTOR_CAP; `(positions:...)`, `(total_risk:...)` and plain `BLOCKED_BY_RISK` are RISK_CAP; `SIZE_ZERO` at stage fill is CASH; everything else is OTHER (the full table is tested label by label). Sector comes from `data\reference\sector_map.csv` through the repository's `sector_for`; an `UNMAPPED:` value is sent as null.
6. **expectedAsOf.** See the next section.
7. **Review marks.** `bff\paper_marks.yaml`: 35.0 percent, 30 trades, verdict `NOT_DEMONSTRATED`, sent as "not demonstrated". The risk per trade is read from `shared.yaml`.
8. **Signal day.** `isSignalDay` is true when there are tickets, else the repository's own `is_signal_session` run on the lake's last two Nifty dates (imported lazily and warmed at start; it takes about 9 s the first time). `nextSignalRule` is the constant "first trading day of next month".
9. **Drawdown history.** Now and worst come from the daily curve: running peak of the daily equity at the close, two decimals, positive.
10. **Closed-trade definition.** Owner decision (Part A): all trades listed and counted; flagged ones excluded from the win rate and profit factor.
11. **Reads during the jobs.** Read-only connections, 3 s timeout, one retry, then 503 NOT_READY; no lock is taken. Tested with an exclusive lock held on the lake.
12. **Held-by-hand positions.** Listed, with `corporateActionFlag: true`.
13. **Sector for a position.** Not sent (the app does not show it).
14. **Pending-exit text.** A position with `pending_exit > 0` is a pending SELL: "Time exit queued at the close", "Stop exit queued at the close" or "Exit queued at the close". There are no pending BUYs (a pending ticket is always the signal day's own ticket, already in `tickets`).
15. **Auth and hosting.** Token and trusted hosts are built; hosting and the Tailscale address are stage 4.

## The expectedAsOf rule and its limit

`expectedAsOf` = start from today if it is 20:30 IST or later, otherwise from yesterday; then step back over weekends and over days the daily data job recorded as having no file (`daily\calendar.csv`, outcome `NO_FILE` or `NO_FILE_FINAL`, unless a later row shows the day loaded). `dataAsOf` = the newest session the paper account has processed.

**Limit:** a holiday the data job has not recorded yet looks like a missing day. The job records a no-file day only after its attempts (a day stays PENDING until 23:45), so on a new weekday holiday the app can show "Updated N days ago" until the job has recorded it. Weekends and recorded holidays are never wrong. Before 20:30 on a day whose job has not run, data from the previous trading day is correct, not stale.

## Tests

- `py -m pytest tests\bff`: **212 passed** (about 20 s; 9 s of that is the one-time load of the strategy for the signal-day function). Temporary files only; the real state and lake are never opened.
- Covered: every endpoint for each of the six scenarios against the shape of its example (same keys and types, enums valid); every reconciliation rule; flagged trades and positions; GAP_THROUGH_STOP join; block and exit reason tables; `expectedAsOf` (Friday data on a Monday morning, 20:30 cutoff, weekends, recorded holidays, the documented limit); money rounding; Nifty rebasing; drawdowns; stats with flagged, empty and no-loss cases; 401 for a missing, empty or wrong token on every endpoint; 404 and 405 with the error body; 503 for a missing state, an uninitialised state, a locked lake and a missing Nifty day; 500 without leaking text; wrong Host refused; no CORS by default; read-only proof (create, insert, delete and drop all raise); no file in the state, tickets or lake folders changes while serving; the token never appears in the log or a repr; cache hit, rebuild on a changed key, fresh envelope times on a hit; refusal to start without a token; a static guard that `bff\*.py` has no write SQL, no lock code, no `stockbot.live` import and no broker or order code.
- `tests\bff\test_contract_models.py` validates every example file against the pydantic models, round-trips them, and checks that the models' fields and enums match `openapi.yaml`: the contract is the single source.
- Guide test only: `py -m pytest tests\unit\test_guides_consistent.py`: 11 passed, 1 skipped (needs `STOCKBOT_DATA_TESTS=1`). The full suite was not run.
- Android: `gradlew test assembleDebug lintDebug --no-daemon`: BUILD SUCCESSFUL; 49 JVM tests, 0 failures; lint 0 errors, 5 warnings (the same five as before). APK rebuilt to `F:\Projects\Ravi\StockBotData\android\stockbot-paper-debug.apk`.

## Smoke results (the only time real data was touched)

Run at 19:32 IST on 24 Nov 2026, with `STOCKBOT_BFF_HOST=127.0.0.1`, a new hidden process (`py -3 bff\run.py`), the real token file.

- Every check passed (`SMOKE PASSED`): health, today, account, positions, trades all 200 with the envelope, `+05:30` timestamps, curve starting at the starting capital and ending at equity, cash + positions = account equity; no token and a wrong token gave 401 UNAUTHORIZED; an unknown route gave 404 with the error body.
- `/v1/account`: start date **2026-11-23**, equity **20,000,000 paise (Rs 2,00,000)**, cash 20,000,000, return 0.0%, 0 closed trades, data as of 2026-11-23. `/v1/health`: status ok, latest sealed date 2026-11-23, expectedAsOf 2026-11-23 (before 20:30 IST, so the previous trading day).
- `/v1/today` matched the newest real ticket file (`state\tickets\tickets_2026-11-23.json`): not a signal day, no tickets, no blocked, no pending.
- **Read-only:** every connection to `live_state.db` and `finsight.db` was opened `mode=ro` with `query_only` (the code path has no other way to open them). The BFF created, modified or locked nothing in `state\` or `locks\`: the file names, sizes and modification times of both folders were identical before and after. **One thing to know:** the lake runs in WAL mode, so any reader, including the repository's own read-only opener, updates the modification time of the existing `finsight.db-shm` (and `-wal`) files; no new file appeared and `finsight.db` itself was not modified (same size and time). This is how SQLite readers work and cannot be avoided without reading a possibly inconsistent file.
- **Scheduler service:** pid **9100** before and after; no new line in `scheduler_service.log` from the smoke time (the job's own 19:30 attempt, exit 3 and a retry planned for 19:50, was logged before the smoke and is not related).
- The BFF was stopped by killing only its own pid (the listener and its launcher); port 8765 was free afterwards. The access log `bff.log` shows the nine smoke requests with no token.

## Deviations and notes

1. **Port:** 8765 was free; no other port was needed.
2. **`/v1/health` when the data is not ready** returns 200 with `status: "not_ready"` (not 503), and `dataAsOf` falls back to the sealed date, then the last processed session, then `expectedAsOf`, because the contract requires a date there.
3. **Error body for unknown routes and wrong methods** uses the code `SERVER_ERROR` with HTTP 404 or 405 (the contract has only three codes).
4. **The Today response has no pending BUY rows** (see gap 14).
5. **Win rate denominator** is the unflagged trades (`tradeCount - excludedFromStats`), so the app shows "5 of 11" for 12 trades with one flagged.
6. **Screens:** the Positions and Trades screens changed visibly (the new note and footer line), so those four screenshots were re-taken on the AVD, plus one extra (`extra-dark-trades-footer.png`). The other screens are unchanged.
7. **WAL files:** see the smoke section.
8. **The BFF reads the real `shared.yaml`** (a repository file) for the risk percent; tests use a temporary copy.

## For stage 4

- The INTERNET permission in the app (and nothing else new in the manifest).
- The app's network repository (replace the mock source; the parsing is already the real one), pull-to-refresh and the token entry on the phone.
- The Tailscale address: set `STOCKBOT_BFF_HOST` to the machine's Tailscale address (not 0.0.0.0) and `STOCKBOT_BFF_ALLOWED_HOSTS` to the hostnames the app will use; check the firewall.
- Starting the BFF on a schedule or at boot (today it is started by hand in its own window, like the scheduler service, and does not survive a reboot).
- TLS (Tailscale encrypts the link; the app would use plain HTTP over it, or Tailscale's HTTPS certificate if wanted).
- A real holiday calendar, if the "Updated N days ago" limit on an unrecorded holiday turns out to be annoying.

# StockBot Paper API contract, version 1 (FROZEN)

Frozen by the owner's decisions of stage 2. Files in this folder:

| File | What it is |
|---|---|
| `openapi.yaml` | The contract in OpenAPI 3.0 (paths, schemas, errors) |
| `examples/` | One JSON file per response per mock scenario (28 files); the app's mock data and the tests read these |
| `CONTRACT.md` | This short form |
| `SOURCE_MAP.md` | Where the backend gets every field, and the gaps it must fill |

The Kotlin models in `android/app/src/main/java/com/stockbot/paper/data/Models.kt` follow this document field for field.

## Conventions

- Calls: `GET /v1/health`, `/v1/today`, `/v1/account`, `/v1/positions`, `/v1/trades`. Header `X-Paper-Token` on every call. The token is never stored in the repository. Read-only: no other methods exist.
- JSON keys are camelCase. Dates are `yyyy-MM-dd`. Timestamps are ISO 8601 with the `+05:30` offset.
- **Money is integer paise** (64-bit). 100 paise = 1 rupee. The app shows rupees. Percent values are decimal numbers in percent units (`1.5` means 1.5%). Drawdowns are positive numbers.
- Every response has `apiVersion` (the string `"1"`). Every success response also has `dataAsOf`, `expectedAsOf` and `generatedAt`.
- **List-valued fields are never null** (`[]` when empty). Fields marked nullable are always present and may be `null`.
- The server sends the footer figures (win rate, profit factor, wins, losses, drawdowns). The app does not recompute them.
- The Nifty line is sent already rebased to the account's starting value, in paise, one point per trading day, on the same dates as the account line.
- The app ignores unknown keys and maps any unknown enum value to `OTHER`; it never crashes on a newer server. An unknown error code is treated as `SERVER_ERROR`.
- Example data in `examples/` is illustrative: calendars skip weekends only, figures are made up except where a scenario says it is the real state (EMPTY).

## Freshness

| Field | Meaning |
|---|---|
| `dataAsOf` | The date of the data |
| `expectedAsOf` | The last trading day on which data is expected |
| `generatedAt` | When the server built the response |

The app shows **"Updated N days ago" only when `dataAsOf` is before `expectedAsOf`**, with N the calendar days from `dataAsOf` to `expectedAsOf` ("Updated 1 day ago" when N is 1). Friday data on a Monday morning is not stale when `expectedAsOf` is Friday. Data two trading days behind is stale. The old fixed "3 days" rule and its constant are gone.

## Refresh rule

The app asks again when it opens and on pull-to-refresh. There is no background polling and no push. Retry on the error screen asks again.

## Errors

Every non-200 response has this body (and `apiVersion`):

```json
{"apiVersion":"1","error":{"code":"NOT_READY","message":"Today's data is not ready yet."}}
```

| Code | HTTP | When |
|---|---|---|
| `UNAUTHORIZED` | 401 | `X-Paper-Token` missing or wrong |
| `NOT_READY` | 503 | No sealed data yet, or the state database has not been initialised |
| `SERVER_ERROR` | 500 | Anything else |

`message` is one short sentence: sentence case, no exclamation mark, no "please". The app shows its own calm one-line error with Retry and does not show the server's text on screen in stage 1 to 3.

## Versioning

Adding an optional field or an enum value is not a breaking change (clients ignore unknown keys and map unknown enum values to `OTHER`). Removing or renaming a field, changing a unit or a type, or making a nullable field non-null is breaking: it ships as `apiVersion` `"2"` on new paths under `/v2/...`, and `/v1` keeps working until the app no longer needs it. The app refuses a response whose `apiVersion` is not `"1"`.

## Responses

"Screen" is where the app uses the field. "Null" says whether the field can be null.

### `GET /v1/health`

| Field | Type | Unit | Null | Screen |
|---|---|---|---|---|
| `apiVersion` | string | `"1"` | no | none |
| `status` | string | `ok` or `not_ready` | no | none (stage 4 connection check) |
| `serverTime` | timestamp | +05:30 | no | none |
| `latestSealedDate` | date | | yes (before any data is sealed) | none |
| `dataAsOf` | date | same value as `latestSealedDate` | no | none |
| `expectedAsOf` | date | | no | none |
| `generatedAt` | timestamp | same value as `serverTime` | no | none |

### `GET /v1/today` (Today)

| Field | Type | Unit | Null | Screen |
|---|---|---|---|---|
| envelope | `apiVersion`, `dataAsOf`, `expectedAsOf`, `generatedAt` | see above | no | all (stale line) |
| `isSignalDay` | boolean | | no | Today: suggestions layout or "No signal today" |
| `riskPerTradePct` | number | percent of equity | no | Today: "Risk 1% each." |
| `tickets` | list of Ticket | | never null | Today: one card each; headline "N suggestions" |
| `blocked` | list of BlockedItem | | never null | Today: "K more were blocked by the sector cap" (K counts `SECTOR_CAP` items) |
| `pendingFills` | list of PendingFill | | never null | Today: cards on a non-signal day |
| `nextSignalRule` | string | plain words | no | Today: "Next signal: ..." |

Ticket: `symbol` (string), `sector` (string, null when unknown), `shares` (int), `entryReferencePaise` (paise per share; last close, the fill is at the next open), `stopPaise` (paise per share), `riskPaise` (paise lost if the stop is hit, before costs). Shown on Today.

BlockedItem: `symbol`, `sector` (null when unknown), `reason` (BlockReason). Shown on Today (counted only).

PendingFill: `symbol`, `side` (BUY or SELL), `shares` (int), `note` (short reason, plain words). Shown on Today.

### `GET /v1/account` (Account)

| Field | Type | Unit | Null | Screen |
|---|---|---|---|---|
| envelope | | | no | stale line |
| `summary.startDate` | date | | no | "Account since 16 Nov" |
| `summary.startingCapitalPaise` | int64 | paise | no | basis of returns (not shown) |
| `summary.equityPaise` | int64 | paise | no | large equity figure |
| `summary.cashPaise` | int64 | paise | no | not shown on Account (equity = cash + positions marked at last close) |
| `summary.returnPct` | number | percent since start | no | account return |
| `summary.niftyReturnPct` | number | percent over the same dates | no | Nifty return |
| `summary.drawdownNowPct` | number | percent below peak, positive | no | drawdown card and bar |
| `summary.drawdownWorstPct` | number | percent below peak, positive | no | drawdown card and bar tick |
| `summary.closedTrades` | int | count | no | "12 of 30" and bar |
| `curve` | list of point | | never null | equity curve |
| `curve[].date` | date | one per trading day, oldest first | no | curve |
| `curve[].accountPaise` | int64 | paise | no | solid line; first point is the starting capital, last point is `equityPaise` |
| `curve[].niftyPaise` | int64 | paise, rebased to the starting capital | no | dashed line; first point is the starting capital |
| `marks.drawdownReviewPct` | number | percent | no | drawdown bar scale (35 today) |
| `marks.closedTradesTarget` | int | count | no | closed-trades bar scale (30 today) |
| `marks.verdict` | string | the registered verdict, shown as it is | no | footer "Verdict: not demonstrated" |

### `GET /v1/positions` (Positions)

| Field | Type | Unit | Null | Screen |
|---|---|---|---|---|
| envelope | | | no | stale line |
| `cashPaise` | int64 | paise | no | footer "Cash" |
| `positions` | list of Position | | never null | one card each |
| `positions[].symbol` | string | | no | card |
| `positions[].shares` | int | shares | no | card |
| `positions[].entryDate` | date | | no | card ("since 2 Dec") |
| `positions[].entryPricePaise` | int64 | paise per share | no | card |
| `positions[].stopPaise` | int64 | paise per share; the stop in force now | no | card |
| `positions[].lastClosePaise` | int64 | paise per share | no | card |
| `positions[].unrealisedPnlPaise` | int64 | paise; (last close - entry) x shares | no | card |

### `GET /v1/trades` (Trades)

| Field | Type | Unit | Null | Screen |
|---|---|---|---|---|
| envelope | | | no | stale line |
| `trades` | list of ClosedTrade | newest exit first | never null | one card each |
| `trades[].symbol` | string | | no | card |
| `trades[].entryDate`, `exitDate` | date | | no | card |
| `trades[].exitReason` | ExitReason | | no | card |
| `trades[].netPnlPaise` | int64 | paise after costs | no | card |
| `trades[].netR` | number | net P&L / paise risked at entry | no | card |
| `stats.tradeCount` | int | count | no | footer "5 of 12" |
| `stats.wins` | int | net P&L above zero | no | footer |
| `stats.losses` | int | net P&L below zero | no | none yet |
| `stats.winRatePct` | number | percent = wins / tradeCount | yes (no trades) | footer "42%" |
| `stats.profitFactor` | number | gross profit / gross loss | yes (no losing trade) | footer "1.40" |

## Enums

The app maps any value it does not know to `OTHER`. `OTHER` is part of the contract for exit reason and block reason; for side it exists only in the app, as the landing place for an unknown value.

| Enum | Values |
|---|---|
| ExitReason | `STOP_HIT`, `GAP_THROUGH_STOP`, `OTHER` |
| BlockReason | `SECTOR_CAP`, `CASH`, `RISK_CAP`, `OTHER` |
| Side | `BUY`, `SELL` |
| ErrorCode | `UNAUTHORIZED`, `NOT_READY`, `SERVER_ERROR` |

### Engine mapping

Read from `stockbot/engine`, `stockbot/risk`, `stockbot/live`, `stockbot/overlays` and `stockbot/backtest/runner.py`. Every label found is listed.

**Exit reasons** (the `reason` of an `ExitRecord`, copied to `ClosedTrade.exit_reason`):

| Engine label | Where it comes from | Contract value |
|---|---|---|
| `STOP_HIT` | `engine/stepping.py` (stop touched; also the pending reason of a capped non-EQ stop exit) | `STOP_HIT`, or `GAP_THROUGH_STOP` when the session's flags contain `GAP_THROUGH_STOP` for the same symbol |
| `GAP_THROUGH_STOP` as a flag | `engine/stepping.py` adds flag `GAP_THROUGH_STOP` (with `STOP_HIT`) when the bar opens below the live stop. It is a flag in `Decisions.flags`, not an exit reason string | marks the `STOP_HIT` trade above as `GAP_THROUGH_STOP` |
| `TIME_EXIT` | `engine/exit_policies/fixed_hold.py` | `OTHER` |
| `POLICY_EXIT` | `engine/stepping.py` default when a queued exit has no reason | `OTHER` |
| `SYMBOL_NO_BARS` | `engine/stale.py` (no bars for 20 sessions) | `OTHER` |
| `END_OF_WINDOW` | `backtest/runner.py` only; never occurs in paper | `OTHER` |
| `OPERATOR_EXIT` | `engine/reports.py` default for an operator report (LIVE) | `OTHER` |
| `MANUAL`, `TIME_DECAY`, `EARNINGS_EXIT`, `OTHER` | `live/api/positions.py` operator report choices (LIVE, legacy router) | `OTHER` (a reported `STOP_HIT` is `STOP_HIT`) |
| `UNKNOWN` | `engine/decide.py` fallback when a closed trade has no exit record | `OTHER` |

**Block reasons** (`Blocked.reason` in the ticket file; `Blocked.stage` is `propose`, `overlay`, `sizing`, `risk` or `fill`):

| Engine label | Stage | Contract value |
|---|---|---|
| `BLOCKED_BY_RISK(sector_<S>:x.x%>y%)` | risk | `SECTOR_CAP` |
| `BLOCKED_BY_RISK(positions:n>max)` | risk | `RISK_CAP` |
| `BLOCKED_BY_RISK(total_risk:x.x%>y%)` | risk | `RISK_CAP` |
| `BLOCKED_BY_RISK` (plain) | risk | `RISK_CAP` |
| `SIZE_ZERO` | fill (sized with cash: fewer than one affordable share) | `CASH` |
| `SIZE_ZERO` | sizing (at the proposal, no cash limit: stop too wide for the risk budget) | `OTHER` |
| `NONPOSITIVE_RISK` | sizing, fill | `OTHER` |
| `ALREADY_HELD`, `SYMBOL_HELD_BY_OTHER_STRATEGY`, `NO_BAR_OR_ALREADY_HELD` | risk, fill | `OTHER` |
| `NOT_ELIGIBLE`, `DUPLICATE_PROPOSAL` | propose | `OTHER` |
| `NOT_EQ_SERIES`, `NOT_EQ_SERIES_AT_FILL` | propose, fill (never-buy rule) | `OTHER` |
| `MARKET_SWITCH` | overlay (entries blocked by the market switch) | `OTHER` |
| `STRATEGY_NOT_REGISTERED`, `CORP_ACTION_ON_EXEC_DATE`, `GAP_THROUGH_STOP` (entry gap below the stop), `GAP_UP_TOO_LARGE`, any `confirm_fill` verdict string, `CONFIRM_FILL_ERROR` | fill | `OTHER` |

**Side:** the engine has no side field. A ticket (`State.pending`) is a `BUY` at the next open; a position with `pending_exit > 0` is a `SELL` at the next open.

## Changes from the stage 1 draft

Money is integer paise; footer figures come from the server; Nifty is sent rebased; exit reasons are `STOP_HIT`, `GAP_THROUGH_STOP`, `OTHER` (the draft's `TIME_EXIT` is now `OTHER`); block reasons gained `CASH`, `RISK_CAP`, `OTHER`; freshness uses `dataAsOf`, `expectedAsOf`, `generatedAt` instead of one date and a fixed 3-day rule; every response carries `apiVersion`; the verdict is a plain string; `PendingFill.note` stays free text.

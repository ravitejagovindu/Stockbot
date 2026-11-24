# StockBot Paper app: data contract (DRAFT)

**Status: DRAFT. To be frozen after the owner approves the UI.** Until then any field may be renamed, added or removed.

Source of truth in code: `android/app/src/main/java/com/stockbot/paper/data/Models.kt` and `PaperRepository.kt`.

## Conventions

- Money: rupees, `Double` (JSON number). The UI rounds to the paise and hides paise when zero. A later backend may send integer paise instead; decide at freeze.
- Percent: percent units, `Double` (`1.5` means 1.5%). Drawdowns are positive numbers (31.0 means 31% below the peak).
- Dates: calendar dates, ISO `yyyy-MM-dd` (`LocalDate`), India trading calendar.
- Lists are ordered as stated in the field notes.
- Any call may fail; the UI shows a one-line error with Retry.

## Repository interface

| Call | Returns | Screen |
|---|---|---|
| `isSample` | Boolean, true while data is made up (drives the "SAMPLE DATA" tag) | all |
| `getToday()` | `TodayState` | Today |
| `getAccount()` | `AccountSnapshot` | Account |
| `getPositions()` | `PositionsState` | Positions |
| `getTrades()` | `TradesState` | Trades |

## TodayState (Today)

| Field | Type | Unit / note | Used for |
|---|---|---|---|
| `asOf` | date | Date of the data | "Updated N days ago" line when 3 or more days old |
| `isSignalDay` | boolean | | Chooses the suggestions layout or "No signal today" |
| `riskPerTradePct` | number | percent of equity | "Risk 1% each." |
| `tickets` | list of `Ticket` | | One card each; headline "N suggestions" |
| `blocked` | list of `BlockedItem` | | "K more were blocked by the sector cap" (K = list size) |
| `pendingFills` | list of `PendingFill` | | Cards on a non-signal day |
| `nextSignalRule` | string | plain language | "Next signal: ..." |

### Ticket

| Field | Type | Unit / note |
|---|---|---|
| `symbol` | string | NSE symbol |
| `sector` | string | |
| `shares` | int | whole shares |
| `entryReference` | number | rupees per share; last close, fill is at the next open |
| `stop` | number | rupees per share |
| `riskRupees` | number | rupees lost if the stop is hit, before costs |

### BlockedItem

| Field | Type | Note |
|---|---|---|
| `symbol` | string | |
| `sector` | string | |
| `reason` | enum `SECTOR_CAP` | Only value so far |

### PendingFill

| Field | Type | Note |
|---|---|---|
| `symbol` | string | |
| `side` | enum `BUY`, `SELL` | |
| `shares` | int | |
| `note` | string | Short reason, for example "Stop reached" |

## AccountSnapshot (Account)

Contains `summary: AccountSummary`, `curve: List<EquityPoint>`, `marks: ReviewMarks`.

### AccountSummary

| Field | Type | Unit / note | Used for |
|---|---|---|---|
| `asOf` | date | | Stale line |
| `startDate` | date | | "Account since 10 Jun" |
| `startingCapital` | number | rupees | Not shown yet; basis for returns |
| `equity` | number | rupees | Large equity figure |
| `cash` | number | rupees | Not shown on Account (shown on Positions) |
| `returnPct` | number | percent since start | Account return |
| `niftyReturnPct` | number | percent over the same dates | Nifty return |
| `drawdownNowPct` | number | percent below peak, positive | Drawdown card and bar |
| `drawdownWorstPct` | number | percent below peak, positive | Drawdown card and bar tick |
| `closedTrades` | int | count | "12 of 30" and bar |

### EquityPoint

| Field | Type | Note |
|---|---|---|
| `date` | date | One point per trading day, oldest first |
| `account` | number | Account equity, rupees |
| `nifty` | number | Nifty rebased to `startingCapital`, rupees, so both lines share one axis |

### ReviewMarks

| Field | Type | Note | Used for |
|---|---|---|---|
| `drawdownReviewPct` | number | percent, 35 today | Drawdown bar scale |
| `closedTradesTarget` | int | 30 today | Closed-trades bar scale |
| `verdict` | enum `NOT_DEMONSTRATED` | Registered verdict, always shown | Footer "Verdict: not demonstrated" |

## PositionsState (Positions)

| Field | Type | Unit / note | Used for |
|---|---|---|---|
| `asOf` | date | | Stale line |
| `cash` | number | rupees | Footer (with "Idle cash earns nothing") |
| `positions` | list of `Position` | | One card each |

### Position

| Field | Type | Unit / note |
|---|---|---|
| `symbol` | string | |
| `shares` | int | |
| `entryDate` | date | |
| `entryPrice` | number | rupees per share |
| `stop` | number | rupees per share |
| `lastClose` | number | rupees per share |
| `unrealisedPnl` | number | rupees; (lastClose - entryPrice) x shares |

## TradesState (Trades)

| Field | Type | Unit / note | Used for |
|---|---|---|---|
| `asOf` | date | | Stale line |
| `trades` | list of `ClosedTrade` | Newest exit first | One card each; footer figures are computed from this list |

### ClosedTrade

| Field | Type | Unit / note |
|---|---|---|
| `symbol` | string | |
| `entryDate` | date | |
| `exitDate` | date | |
| `exitReason` | enum `STOP_HIT`, `GAP_THROUGH_STOP`, `TIME_EXIT`, `OTHER` | Names follow the engine's exit reasons; more to be added at freeze |
| `netPnl` | number | rupees, after costs |
| `netR` | number | net P&L divided by the rupees risked at entry |

### TradeStats (computed in the app, not sent)

Win rate = wins / trades (percent). Profit factor = gross profit / gross loss, none when there are no losing trades.

## Open questions for the freeze

1. Money as rupees (`Double`) or integer paise.
2. Whether the server sends the footer figures (win rate, profit factor, drawdowns) or the app computes them.
3. Whether `EquityPoint.nifty` is sent rebased (as now) or as the raw index level.
4. Full list of exit reasons and block reasons.
5. The stale threshold (3 days now) and whether the server sends a data timestamp instead of a date.

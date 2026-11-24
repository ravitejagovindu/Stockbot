# Source map: where the backend gets every field

Written by reading the code only (`stockbot/live`, `stockbot/engine`, `stockbot/risk`, `stockbot/data`, `scripts/paper_run.py`, `scripts/daily_job.py`). No script was run against real state. The one real artifact read was `state/tickets/tickets_2026-11-23.json` (empty lists: no tickets, no blocked, no fills, no flags).

## Sources

| Short name | What | Where |
|---|---|---|
| **journal** | Append-only table `journal(seq, kind, session, key, payload)` in the state database. `kind` is `init` (payload `{"cash": 200000.0}`, session `0000-00-00`), `decisions` (one row per processed session, payload = `Decisions` JSON, key = session date) or `effect` (operator reports; none in PAPER) | `state/live_state.db` (`stockbot/live/state_store.py`; path from `stockbot.config.paths.state_db_path`) |
| **snapshot** | Table `snapshot(id=1, as_of, state)`: the latest `State` as JSON (cash, positions, pending tickets, realised P&L). A cache that `rebuild()` recomputes from the journal | `state/live_state.db` |
| **tickets file** | One file per processed session, written for every session including non-signal days. Keys: `as_of`, `tickets[]`, `blocked[]`, `flags[]`, `fills_assumed[]`, `exits_assumed[]`, `note` | `state/tickets/tickets_<date>.json` (`runner.write_tickets`) |
| **lake** | Table `market_data_lake(symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, ...)`. The Nifty series is `symbol = 'NIFTY50_INDEX'`; its dates are the trading calendar (`AsOfView.sessions`) | `finsight.db`, opened only through `stockbot.data.lake.open_lake` (read-only: `mode=ro` plus `query_only`) |
| **config** | `stockbot/config/shared.yaml` (`portfolio_risk.max_loss_pct_per_trade` 1.0, `max_concurrent_positions` 12, `max_total_portfolio_risk_pct` 15.0, `max_sector_exposure_pct` 15.0); `PAPER_START_CASH = 200000.0` in `stockbot/strategies/momentum_calm/paper.py`; sector map `data/reference/sector_map.csv` via `stockbot.data.sector_map.sector_for` | repository |
| **docs** | The review marks and the monthly rule are written in `docs/strategies/momentum_calm/paper/README.md` only | repository |

Rules for the backend: open the state database read-only with `sqlite3` (`file:...?mode=ro`); do not use `StateStore(...)` to read, because its constructor runs `CREATE TABLE IF NOT EXISTS` and may write. Open the lake only through `open_lake`. Never run `paper_run.py` or `daily_job.py`. Prices in the engine are floats in rupees; the backend converts to integer paise (see the first gap below).

## Envelope fields (every response)

| Field | Source |
|---|---|
| `apiVersion` | Constant `"1"` |
| `dataAsOf` | The newest date in the journal with a `decisions` row (`max(session)` where `kind='decisions'`, or `snapshot.as_of`). It must also be sealed in the lake (`stockbot.data.ingestion.daily_update.seal_of`) |
| `expectedAsOf` | No source today: see "Gaps the backend must fill", gap 6 |
| `generatedAt` | The server clock when the response is built, formatted with the +05:30 offset |

## /v1/health

| Field | Source |
|---|---|
| `status` | `ok` when the journal has at least one `decisions` row and the lake seal is readable, else `not_ready` |
| `serverTime`, `generatedAt` | Server clock |
| `latestSealedDate`, `dataAsOf` | `seal_of(con, LAKE)` on the read-only lake connection; null when it returns None |
| `expectedAsOf` | Gap 6 |

## /v1/today

| Field | Source |
|---|---|
| `isSignalDay` | `stockbot.strategies.momentum_calm.strategy.is_signal_session(view)` on an `AsOfView(lake, dataAsOf)`: the first trading session of a calendar month. Alternative with no lake read: the tickets file has tickets or blocked rows with stage `propose`, `sizing` or `risk` |
| `riskPerTradePct` | config: `portfolio_risk.max_loss_pct_per_trade` (1.0) |
| `tickets[]` | tickets file for `dataAsOf`, `tickets[]` (engine `Ticket`) |
| `tickets[].symbol` | `symbol` |
| `tickets[].sector` | `sector` (engine `Ticket.sector`, filled from `sector_for`). A value starting `UNMAPPED:` means the symbol is not in the sector map: send null |
| `tickets[].shares` | `shares_planned` |
| `tickets[].entryReferencePaise` | `reference_price` x 100, rounded |
| `tickets[].stopPaise` | `stop` x 100, rounded |
| `tickets[].riskPaise` | `risk_planned` x 100, rounded (equals `shares_planned` x (reference - stop); the app checks that identity in the examples). The fill later re-sizes on the equity of the fill day, so the position's real risk can differ slightly |
| `blocked[]` | tickets file `blocked[]` (engine `Blocked(strategy_id, symbol, reason, stage)`) |
| `blocked[].symbol` | `symbol` |
| `blocked[].sector` | `sector_for(symbol)`, null when it starts `UNMAPPED:` (`Blocked` has no sector field) |
| `blocked[].reason` | `reason` and `stage` mapped with the table in `CONTRACT.md` (gap 5) |
| `pendingFills[]` | SELL rows only in practice: every open position in the snapshot with `pending_exit > 0` (`symbol`, `side` SELL, `shares` = `pending_exit`, `note` from `pending_reason` in plain words). BUY rows would repeat the signal day's `tickets` (`State.pending` is exactly the last session's new tickets), so BUY is sent only when `isSignalDay` is false, which never has pending tickets: the list is empty then |
| `nextSignalRule` | No source: the rule "first trading session of each calendar month" is in `strategy.py` (`is_signal_session`) and in the README; the backend sends the constant `first trading day of next month` (gap 8) |

## /v1/account

| Field | Source |
|---|---|
| `summary.startDate` | Gap 1 |
| `summary.startingCapitalPaise` | journal `init` row, payload `cash` (200000.0) x 100. Same value as `meta.initial_cash` |
| `summary.equityPaise` | snapshot state: `cash` + sum over `positions` of `shares_remaining` x `last_close` (the engine's `_equity`), each term converted to paise first so that equity = cash + positions holds exactly |
| `summary.cashPaise` | snapshot state `cash` |
| `summary.returnPct` | (equity / starting capital - 1) x 100, two decimals |
| `summary.niftyReturnPct` | (last `curve[].niftyPaise` / starting capital - 1) x 100, two decimals |
| `summary.drawdownNowPct`, `drawdownWorstPct` | Computed from the account curve: peak-to-trough on `curve[].accountPaise` (gap 9) |
| `summary.closedTrades` | Count of `closed` entries over all `decisions` rows in the journal (the same list as `/v1/trades`) |
| `curve[].date` | Trading days from `startDate` to `dataAsOf`: the lake's `NIFTY50_INDEX` dates, which are also the dates of the `decisions` rows |
| `curve[].accountPaise` | Equity after each session: fold the journal row by row (`engine.apply.apply_decisions`, the same fold as `StateStore.rebuild`) and mark `cash + sum(shares_remaining x last_close)` after each `decisions` row. Nothing stores a daily equity series (gap 2) |
| `curve[].niftyPaise` | Nifty `close_raw` of that date x (starting capital / Nifty `close_raw` on `startDate`), in paise. No source for the rebasing (gap 3) |
| `marks.drawdownReviewPct` | 35.0. Only in `docs/strategies/momentum_calm/paper/README.md` (gap 7) |
| `marks.closedTradesTarget` | 30. Same document (gap 7) |
| `marks.verdict` | `not demonstrated`. No source in code or config: it is the registered verdict (gap 7) |

## /v1/positions

| Field | Source |
|---|---|
| `cashPaise` | snapshot state `cash` |
| `positions[]` | snapshot state `positions[]` (engine `Position`), skipping positions with `hold = true` only if the owner decides so (gap 12) |
| `symbol` | `symbol` |
| `shares` | `shares_remaining` |
| `entryDate` | `entry_date` |
| `entryPricePaise` | `entry_price` x 100 (this is the filled price, entry slippage of 0.10% included) |
| `stopPaise` | `live_stop` x 100 (the stop in force; `initial_stop` is the one at entry) |
| `lastClosePaise` | `last_close` x 100 |
| `unrealisedPnlPaise` | `shares_remaining` x (`last_close` - `entry_price`) in paise. Gross: entry costs (`costs_paid`) and any realised part of a partly sold position are not in it |

## /v1/trades

| Field | Source |
|---|---|
| `trades[]` | Every `closed` entry (engine `ClosedTrade`) in every `decisions` row of the journal, newest `exit_date` first |
| `symbol`, `entryDate`, `exitDate` | `symbol`, `entry_date`, `exit_date` |
| `exitReason` | `exit_reason` mapped with the table in `CONTRACT.md`; `STOP_HIT` becomes `GAP_THROUGH_STOP` when the `flags` of that session's `decisions` row (or tickets file) hold `GAP_THROUGH_STOP` for the symbol (gap 4) |
| `netPnlPaise` | `net_pnl` x 100 (after costs: gross P&L minus buy and sell costs) |
| `netR` | `net_pnl` / `risk_inr` (`risk_inr` = initial shares x (entry - initial stop), kept on the closed trade). Two decimals. Derivable today; the draft listed it as a possible gap and it is not one |
| `stats.tradeCount`, `wins`, `losses` | Counted from `trades[]` (net above zero, net below zero) |
| `stats.winRatePct` | wins / tradeCount x 100, two decimals; null when there are no trades |
| `stats.profitFactor` | gross profit / gross loss, two decimals; null when there is no losing trade |

## Gaps the backend must fill

Nothing below needs a change to the engine; each is something the backend (stage 3) has to compute, decide or add. Items 1, 3, 6 and 7 are the real ones.

1. **Money in paise.** The engine keeps floats in rupees. The backend must round each stored value to whole paise (half up) and build totals from the rounded parts, so `equityPaise = cashPaise + sum(shares x lastClosePaise)` and `unrealisedPnlPaise = shares x (lastClosePaise - entryPricePaise)` hold exactly (the examples and the tests check both).
2. **Start date and the daily equity curve.** The `init` journal row has session `0000-00-00`, so the account's start date is not stored; the first `decisions` row (the first processed session, 2026-11-23 on the real state read) is the best proxy. No daily equity or drawdown series is stored: the backend must fold the journal session by session and mark each state at its own `last_close` values. A session missing from the journal has no curve point (the runner processes every unseen session on the next run, so gaps close themselves).
3. **Nifty rebasing.** Nothing computes it. The backend reads `NIFTY50_INDEX` `close_raw` from the lake and rebases it to the starting capital on `startDate`, in paise, on the same dates as the account curve. It is a price index (no dividends) set against an account whose idle cash earns nothing; that is a property of the comparison, not a bug.
4. **GAP_THROUGH_STOP.** The engine books a stop exit as reason `STOP_HIT` and records the gap only as a session flag `GAP_THROUGH_STOP` (`Decisions.flags`, also in the tickets file). The backend must join the closed trade to the flags of its exit session by symbol. `ClosedTrade` has no field for it.
5. **Block reason mapping.** `Blocked.reason` is free text. Sector, position-count and total-risk blocks arrive as `BLOCKED_BY_RISK(...)` and must be parsed (`sector_` prefix inside the brackets means `SECTOR_CAP`). The engine has no cash reason: `SIZE_ZERO` at stage `fill` is the nearest thing and is mapped to `CASH`, but it also appears when the stop is too wide for the risk budget. No `Blocked` row carries a sector.
6. **expectedAsOf.** No trading calendar and no time-of-day rule exist. `runner.expected_session(today)` returns the latest weekday on or before today, so a weekday holiday would read as "data missing", and it does not know that today's data only arrives after the 19:30 IST job. The backend needs: a holiday-aware calendar (the lake's Nifty dates cover the past only, not future holidays) and a rule for before and after the job (before about 19:30 the last expected day is the previous trading day, after it is today, subject to retries up to the 08:30 catch-up).
7. **Review marks and verdict.** The 35% drawdown mark, the 30 closed trades and the "not demonstrated" verdict are written only in the paper README and the owner decision. They are not in `shared.yaml` or any spec. The backend needs one config file or constants for them (and for the verdict, which is the owner's registered statement, not a computed value).
8. **Signal-day fields.** `isSignalDay` is computable (`is_signal_session`) but not stored anywhere; `nextSignalRule` is prose in code comments. The backend sends the constant string and recomputes `isSignalDay` from the lake calendar.
9. **Drawdown history.** Drawdown now and worst are not stored. They come from the curve of gap 2 (running peak of daily equity at the close). Intraday lows and costs are not in it.
10. **Closed-trade definition.** `closedTrades` and the stats count every closed row. Rows with `excluded_ca = true` (a corporate action the engine could not rescale) are flagged in the engine as excluded from statistics. The owner should decide whether the app counts them; stage 3 should default to counting only rows with `excluded_ca = false` and say so.
11. **Reading while the jobs run.** The 19:30 data job holds a lock on `finsight.db` and `paper_run.py` writes `live_state.db`. A read during a write can fail with "database is locked". The backend should read with a timeout, retry once, and answer `NOT_READY` rather than a partial result; it must not take the job locks.
12. **Positions held by hand.** A position with `hold = true` (an action the engine cannot rescale) is flagged and excluded from statistics. Whether to list it on Positions is an owner decision; stage 3 should list it.
13. **Sector for a position.** Not needed by the app (Positions shows no sector). `Position.sector` exists in the snapshot if a later version wants it.
14. **Pending-exit text.** `pending_reason` is an engine label (`TIME_EXIT`, `STOP_HIT`, `POLICY_EXIT`); the backend turns it into the plain-words `note` (for example "Exit queued at the close"). Note that a plain stop is tested on the next bar (`engine/stepping.py`), so it is not a pending exit and never appears in `pendingFills`.
15. **Authentication and hosting.** The token check, the HTTP server and where it runs do not exist (stage 3 and 4). The token value stays out of the repository.

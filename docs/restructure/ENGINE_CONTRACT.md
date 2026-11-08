# Engine contract (Phase 6 Part A — DESIGN ONLY; approved at the STOP 3 review with corrections C1–C4 and rulings D1–D8, applied below)

No code is written for this part. It fixes the interfaces so that backtest and live run the same decision code, strategies stay isolated, and the matched-random baseline can reuse the identical exits. It designs no strategy, changes no gate, threshold, cost or budget, and keeps `finsight.db` read-only. Rulings D1–D8 and corrections C1–C4 from the STOP 3 review are recorded in section 11 and applied in the sections they affect.

## 1. Principles
1. One function, `engine.decide(...)`, makes every decision. Backtest and live call it; neither contains decision logic of its own.
2. `decide` is **pure**: no database, no network, no clock, no file access, no randomness it does not receive. Same inputs → same outputs, run twice.
3. All market data reaches it only through the as-of view (`AsOfView`, Phase 3): the future is unreachable by construction.
4. Everything it remembers is in a plain-data `State` passed in and returned. Nothing is stored on objects between calls.
5. A strategy only *proposes*. Sizing, caps, arbitration, fills, costs, corporate-action handling and the fixed assumptions (next-open fill, slippage, gap-up cap) belong to shared code, so no strategy can bypass them.
6. Exit behaviour is a separate, pluggable object (section 5), so the same exits can be applied to random entries.

## 2. Pure core and I/O shell
| pure (inside `decide`) | I/O (adapters, outside) |
|---|---|
| eligibility from shared rules and exclusions (given the exclusion data as arguments) | opening the read-only lake, building `AsOfView(conn, T)` |
| strategy `propose` calls | loading / saving `State` (backtest: in memory; live: the separate state database) |
| overlays, exit-policy `step`, corporate-action rescaling | reading exclusion / event tables into the plain data `decide` expects |
| sizing, caps, arbitration, fill rules, cost estimates | writing tickets, trade logs, run manifests; scheduling; idempotency per trading date (live) |
| producing the new `State` and `Decisions` | the network (ingestion runs as its own step before `decide`; live only checks freshness) |
The network guard stays: any network use inside the backtest adapter raises. No order-routing code path exists in any adapter.

## 3. Types (plain frozen dataclasses; sketches, not code)
```
State        schema_version, as_of (last processed session), cash, positions: tuple[Position], pending: tuple[Ticket],
             strategy_state: {strategy_id: plain mapping}, overlay_state: {overlay_id: plain mapping}, realised_pnl_net
Position     position_id, strategy_id, symbol, sector, entry_date, entry_price, initial_stop, live_stop, target: float|None,
             shares_initial, shares_remaining, risk_inr, exit_policy_id, exit_state: plain mapping   # exit_state belongs to the policy
Proposal     strategy_id, symbol, signal_date, reference_price, stop, target: float|None, rank: float = 0.0, metadata: plain mapping
Ticket       a Proposal that passed sizing and caps: shares_planned, planned risk/value, created_on
Decisions    fills (tickets filled at this bar's open), exits (per position: reason, price, shares), position_updates (stop / exit_state changes),
             new_tickets (for the next open), blocked (proposal + reason), corporate_actions_applied, flags, audit trail
```
`State` and `Decisions` serialise to JSON without loss (a test will assert round-trip equality). Prices in `State` are in the price basis of the day they were set; corporate actions rescale them (section 7).

## 4. Strategy interface
```
Strategy.spec           StrategySpec (Phase 4)         # id, version, params, exit_policy ref, status, ...
Strategy.propose(view, eligible, as_of, strategy_state, overlays) -> (list[Proposal], new_strategy_state)
Strategy.confirm_fill(proposal, fill_price, view) -> None | reject_reason          # per-strategy fill-time checks (e.g. a minimum R:R at the fill price)
```
- `view` is the as-of view; `eligible` is the symbol list that passed the shared universe rules and exclusions (the strategy cannot widen it; `universe_overrides` may only tighten two thresholds); `overlays` is the already-evaluated signals of the overlays the strategy declared (D1); `strategy_state` is plain data private to that strategy.
- A strategy never receives a connection, a session, a clock, other strategies' proposals, the portfolio caps or other strategies' state. It returns a stop (price) in every proposal; a target is optional (a strategy may have none).
- Parameters used only by one strategy (for example the old strategy's minimum R:R, maximum R:R cap, event-block days) live in its `params`, not in shared config (Stop-1 decisions Q3, Q10).

## 5. Exit policy (separate pluggable object)
```
ExitPolicy.id
ExitPolicy.initial_state(position, view)            -> exit_state
ExitPolicy.step(position, bar, view, ctx)                -> PolicyActions(new_live_stop, new_exit_state, requests: [ExitRequest], flags)
ExitPolicy.on_corporate_action(exit_state, factor)   -> exit_state          # rescales the price-valued parts of its own state
ExitRequest  = MARKET_AT_NEXT_OPEN(shares) | LIMIT(shares, limit_price)
bar          = adjusted OHLC of the session (as-of basis); ctx = (bar number, days held, overlay signals declared by the strategy)
view         = the as-of view (C3): anything the policy needs beyond the bar (ATR, closes N sessions back) is read through the view only, never through a connection
```
The policy decides **what** (new stop level, requested exits). The engine's generic stepping decides **how**, in one fixed order, identical for every policy and for random entries:
1. a market exit requested on the previous bar executes at this bar's open (× exit slippage);
2. the stop live at the previous close is checked against this bar's low; a hit fills at min(open, stop) × (1 − exit slippage) (gap-aware). **This applies to the ENTRY bar too (C1):** a position filled at this bar's open is stepped through the same bar, so if the bar's low is at or below the stop it exits at stop × (1 − exit slippage) on the day of entry. *Legacy check (done; `backtest/simulator.py` step 2 and `advance_one_bar`):* the legacy simulator already steps positions "filled this morning" through the same bar, so it already applies this rule. A fill needs open > stop, so the exit price is stop × (1 − slippage). The extra "floor at the bar's low" is NOT in the legacy code: when the low is within the slippage band of the stop, the legacy fill lies below the bar's low. A floor would RAISE the fill price (less conservative), so the contract keeps the legacy no-floor behaviour unless the reviewer says otherwise (question Q-C1 in the Part B report). Part B tests: a hand-derived entry-bar stop case on the fixture lake; G3's hand-derived trade (553 shares) must still reproduce; a count on a real-lake sample of how many trades the rule affects (expected: none differ from legacy);
3. the policy's `step` runs on this bar (stop moves, state changes, new requests);
4. limit requests fill at max(open, limit) × (1 − exit slippage) when this bar's high reaches the limit.
This is the order `advance_one_bar` uses today; the old strategy's exits (breakeven at +1R, ATR trailing, parabolic tightening, ratchet, 12% partial, 20-session time decay) become one policy implementation that leaves the shared tree (`OLD_STRATEGY_REFERENCE.md`); a dummy policy lives under `tests/`.
**Reuse:** the matched-random baseline calls the same `step_position` with the same policy; `backtest/path_sim.py` is replaced by that call (decision Q5). A test will run the same ticket through the baseline helper and the backtest and require identical fills and P&L.

## 6. `decide(as_of, state, view, strategies, shared_config, event_data) -> (Decisions, State)`
Order of work for session T (all of it deterministic):
1. **Check inputs (C2):** `decide` handles exactly ONE session. `view.as_of == as_of`, and `as_of` is the first session after `state.as_of` in the view's calendar; otherwise it raises. If `state.as_of` is more than one session behind, the ADAPTER calls `decide` once per missed session, in order, each with a view as of that session. There is no catch-up logic inside `decide`.
2. **Corporate actions** with ex-date in (state.as_of, as_of] are applied to open positions (section 7).
3. **Fills:** pending tickets from the previous session are filled at this bar's open under the shared rules: skip if open ≤ stop (gap through stop), skip if open > reference × (1 + max_entry_gap_up_pct) (shared), fill = open × (1 + entry slippage), then `Strategy.confirm_fill` (per-strategy); shares re-derived by `risk.sizing` from the *fill* price, equity and the proposal's stop, capped by cash.
4. **Exits:** every open position (including those just filled, from the next bar on) is stepped through bar T with its policy (section 5); closed positions leave `state.positions`; realised P&L and costs (`risk.costs`) are recorded.
5. **Overlays** evaluated once per session each (section 8).
6. **Universe:** `universe` applies the shared rules (price, raw ADTV, listing age, fund/ETF, ASM/GSM, event proximity as a shared *mechanism*) on the as-of view; the market-cap gate stays parked (KI-001).
7. **Proposals:** each strategy runs `propose`. **Strict mode (C4):** in backtest and validation runs an exception in a strategy, overlay or exit policy stops the run (it propagates). Only the LIVE adapter may catch it, record it in `Decisions.flags` and continue with the other strategies (isolation); `decide` takes `strict: bool` (default True) and only the live adapter passes False.
8. **Risk:** each proposal is sized with `risk.sizing`, then all proposals are admitted together by `risk.arbitrate` against the one set of caps. Order (D6): rank is meaningful only inside one strategy, so each strategy's proposals are ordered by (rank, symbol) and the strategies are interleaved round-robin in strategy-id order. Same symbol (D3): a symbol already held by one strategy (or admitted earlier in this round) cannot be opened by another; the later proposal is `blocked` with reason `SYMBOL_HELD_BY_OTHER_STRATEGY`; sector and total-risk caps see all positions. Accepted → `new_tickets` for the next open; others → `blocked` with the reason.
9. Return the new immutable `State` and the `Decisions`.
Exit slippage, entry slippage, the gap-up cap, costs and risk limits are read from the shared config; none is a strategy parameter.

## 7. Corporate actions on open positions (decided: generic, in the engine)
Splits and bonuses rescale the generic price fields (entry, initial stop, live stop, target, highest high), divide shares by the factor (floor; the fractional remainder is paid in cash at the ex-price) and call `ExitPolicy.on_corporate_action` for the policy-owned prices; R multiples (`risk_inr`, days held, partial counters) are unchanged. Events the engine cannot rescale (mergers, demergers, unparsed rows) put the position on a **hold**: it is flagged, kept out of trade statistics (existing `excluded_ca` behaviour) and surfaced in `Decisions.flags`. This is the existing `corporate_action_events` module plus `rescale_for_action`, both already generic.
**What "known" can mean for corporate actions:** see section 9 — the log has no announcement date, so only *past* ex-dates are known. Applying an action on its ex-date is correct (the price series itself has stepped on that day).

## 8. Macro regime — recommendation for Q4
The Nifty and VIX series and the generic indicator functions are shared data in the view (decided). The kill-switch **rule** (Nifty below its 200-day SMA or VIX above 22, with re-entry hysteresis of 3 sessions) is not a shared engine rule. **D1 (approved) — "overlay" is an optional declared contract component.** Part B builds the interface and a dummy overlay under `tests/` ONLY; the kill switch is NOT implemented and `regime_filter.py` / `regime_gates.py` stay where they are. Overlay ids and versions are part of the `StrategySpec` config hash:
```
Overlay.id, Overlay.version
Overlay.evaluate(view, overlay_state) -> (OverlaySignal: plain mapping, new_overlay_state)     # pure; hysteresis lives in overlay_state
StrategySpec.overlays: tuple[str, ...]      # a strategy DECLARES the overlays it uses; none by default
```
The engine evaluates each declared overlay once per session (shared by all strategies that declare it), persists `overlay_state` in `State`, and hands the signal only to the declaring strategies and their exit policies (for example, a policy that tightens its trailing stop while a kill switch is on). A strategy that declares nothing never sees a regime. The old kill switch (`regime_filter.py`, `regime_gates.py`, the `macro.*` values and `risk.max_concurrent_positions_bull`) would become one registered overlay when the first strategy needs it; until then those files stay where they are and nothing is deleted. **D2 (ruled):** `risk.max_concurrent_positions_bull` (12, equal to the normal cap, no behaviour change) is dropped and recorded in `OLD_STRATEGY_REFERENCE.md`.

## 9. Event knowledge: "known as of date"
- **Earnings:** known. The earnings tables hold the board-meeting *intimation timestamp*; a results meeting counts as known at date T only if `intimation_ts ≤ T` (rule from Stop-1 review Q10; in 2025–26 only 71% / 67% of results meetings had ≥ 7 days of notice, so the rule matters). The mechanism "is a results meeting within N days, known as of T" is shared (universe/data); whether to block entries, and N (14 today), are per-strategy parameters. **D5 (approved):** the view reads the `earnings_*` tables, enforces `intimation_ts ≤ as_of` inside the view, dedupes on (symbol, bm_date), and also exposes per-symbol coverage (has data / no data) so "no data" is never read as "no event".
- **Corporate actions:** the log stores `ex_date` only. `created_at` and `loaded_at` are the load times of 2026-11-07, not announcement dates. NSE's own record carries a `caBroadcastDate` field, but it was empty in all 19 rows with split or bonus wording that I sampled (INFY, RELIANCE, HDFCBANK, WIPRO, TCS, ITC, BAJFINANCE, TAALTECH) and our dump kept only 9 fields. So "known as of T" can mean only **ex_date ≤ T** (the event has happened; correct for price adjustment). It **cannot** mean "an upcoming ex-date was public by T": any rule such as "an ex-date within the next N days blocks entry" would use information of unknown lead time (look-ahead of unknown size). Until announcement timestamps exist (for example from board-meeting outcome filings, not collected), the corporate-action part of an event-proximity rule cannot be implemented point-in-time; the view returns corporate actions with ex-date ≤ as-of only, and the contract forbids any API that returns later ones. No replacement rule is designed here.
- **ASM/GSM:** no point-in-time history exists (KI-003); the daily forward snapshot starts 2026-11-08. A backtest Pass 2 stays fail-closed.

## 10. Where each component lives
| component | home | status |
|---|---|---|
| as-of view, indicators, adjustments, calendar, symbol info | `data` | done (Phase 3) |
| eligibility rules (price, ADTV, age, fund/ETF), ASM/GSM and event exclusions mechanism | `universe` | rules shared; event-block *value* per strategy; market cap parked |
| sizing, caps, arbitration, costs, R definitions | `risk` | done (Phase 5) |
| entry / next-open fill, entry and exit slippage, gap-up cap | engine (shared config `execution`) | decided Q3 |
| minimum R:R at fill, R:R gate, R:R cap | per-strategy (`params`, `confirm_fill`) | decided Q3 |
| exits | `ExitPolicy` objects; generic stepping in `engine` | this design |
| corporate actions on open positions | `engine` | decided (generic) |
| macro regime | overlay (recommended, D1) | Q4 open until approved |
| gates and paper criteria | shared validation / live config, never overridable | decided Q8/Q11 |
| validation, matched-random baseline, Max-T | `validation` (uses the same policy and stepping) | Phase 7 |

## 11. Reviewer rulings (STOP 3 review) and corrections
- **C1** Entry-bar stop: section 5, step 2 (the legacy simulator already does it; the floor question is open).
- **C2** `decide` handles exactly one session; the adapter loops over missed sessions (section 6.1).
- **C3** `ExitPolicy.step` receives the as-of view (section 5).
- **C4** Strict mode: backtest and validation stop on any exception in a strategy, overlay or exit policy; only the live adapter catches and flags (section 6.7).
- **D1** Approved: overlay as an optional declared component; interface plus dummy overlay under `tests/` only; kill switch not implemented; overlay ids and versions in the spec config hash (`StrategySpec.overlays` is added in Part B).
- **D2** `risk.max_concurrent_positions_bull` dropped; recorded in `OLD_STRATEGY_REFERENCE.md`.
- **D3** Block: first by arbitration order wins; the other is `SYMBOL_HELD_BY_OTHER_STRATEGY`; sector and total-risk caps see all positions. (The user may veto.)
- **D4** Approved, extended: in LIVE the operator reports actual fills, actual exits and "ticket not taken"; the adapter applies them to `State` before `decide`. The engine's inference (for example a probable stop hit from bar data) is a flagged suggestion that reality overrides; unreconciled items appear in `flags`. In PAPER and BACKTEST `decide` simulates fills.
- **D5** Approved: view reads `earnings_*`, `intimation_ts <= as_of`, dedupe (symbol, bm_date), per-symbol coverage.
- **D6** Rank is meaningful only inside one strategy: each strategy's proposals ordered by (rank, symbol); strategies interleaved round-robin in strategy-id order (replaces the global (-rank, strategy, symbol) order of `risk.arbitrate`; tests include arrival-order independence).
- **D7** Approved: assumed fills inside `decide`, overridden by real fills in LIVE (D4).
- **D8** Approved: separate SQLite state database written only by the live adapter, schema versioned, plus an append-only journal of tickets, fills and exits so state can be rebuilt.
- **Boundary table:** `validation` may import `risk` (approved).
- **Config note:** `shared.yaml` carries 12 max positions and 15% total portfolio risk unchanged; the original mandate said 10 and 10%. Not changed; listed in `CONFIG_DIFF.md` ("differs from original mandate; decide in strategy phase").

## 12. Tests planned for Part B (G6), each with a fail-before check
- **One test each, with a fail-before check:** entry-bar stop (C1), one-session rule (C2), view passed to the policy (C3), strict mode (C4), round-robin arbitration and symbol-held block (D6, D3), journal rebuild (D8), earnings view (D5).
- **Parity:** ≥ 60 fixture-lake sessions through the backtest adapter, and day by day through the live adapter against a temporary state store: entries, stops, exits, shares and P&L identical.
- **Lookahead:** change every lake row after T; decisions at T identical.
- **Idempotency:** the same live date twice changes nothing.
- **Determinism:** same inputs, same outputs, twice.
- **Isolation:** two dummy strategies together give each the same proposals as alone; caps applied only by `risk`.
- **Baseline reuse:** same ticket through the baseline helper and the backtest gives identical results (Q5).
- **JSON round-trip** of `State` and `Decisions`.
- Kept in their new places: the network guard test and the regulatory-barrier test (no order-routing endpoints).
- Dummy strategy and dummy exit policy exist only under `tests/`.

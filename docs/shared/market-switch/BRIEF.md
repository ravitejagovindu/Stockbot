# Market switch (shared overlay `market_switch_v1`): brief and exact semantics

Owner decisions of 2026-11-15: carry the OLD kill switch over EXACTLY (no tuning), as a shared overlay applied to every strategy by backtest, paper and live through one engine call.
Descriptive comparison only (Part B): not registered trials, no ledger rows, no registered conclusion changes.

## The rule (source: `scripts/provenance/regime/regime_filter.py`; values from the old `strategy_config.yaml` macro section, listed in `docs/restructure/OLD_STRATEGY_REFERENCE.md`)
Naming: **ACTIVE** = the switch is engaged and NEW ENTRIES ARE BLOCKED. **CLEAR** = entries allowed. ("On"/"off" are not used.)

| point | semantics |
|---|---|
| price | `close_raw` of `NIFTY50_INDEX` and `INDIA_VIX` (index series have no adjustments), read through `AsOfView.index_bars` only; the as-of session's close. |
| trigger (while CLEAR) | Nifty close **<** SMA200 of the Nifty closes, OR VIX close **>** 22.0. Strict: a close equal to SMA200, or VIX exactly 22.0, does not trigger. On a trigger the re-entry count is set to 0. |
| ACTIVE, re-entry | Looked at only while ACTIVE: Nifty close **>** its SMA20 AND VIX close **<** 20.0 (both strict). Each qualifying session adds 1 to the count; any session that misses either condition resets the count to 0. The switch releases on the session that makes the count reach **3** (that session is already CLEAR). The trigger conditions play no role while ACTIVE (Nifty above SMA200 with VIX 21 stays ACTIVE). |
| SMA window | `stockbot.data.indicators.sma` = rolling mean that is NaN until the FULL window of closes exists (`min_periods` = window). The old code fetched the last 210 Nifty closes; the overlay uses the same 210. |
| warm-up | Fewer than 200 closes: SMA200 is missing, so the Nifty trigger cannot fire (VIX still can). Fewer than 20 closes: SMA20 is missing, so the re-entry condition fails. First ever session: CLEAR, count 0. |
| missing VIX / Nifty | The old code raised `RuntimeError`. The overlay raises `MarketSwitchDataError` (a `RuntimeError`) if the as-of session has no Nifty row, no VIX row or a null close, in backtest, paper and live (not isolated by the live adapter). Counted first: 2,674 Nifty sessions 2016-01-01 to 2026-10-16, **0** with no VIX row or a null VIX close, so nothing is carried forward, interpolated or failed closed. |
| config vs docstring | The old module docstring and README say VIX 20 and Nifty SMA50 for re-entry. The code and config (what actually ran) say trigger VIX 22, re-entry Nifty SMA20 and VIX 20. The config values are carried over. |
| timing | Decided on the session close T (the view is as-of T). It applies to proposals made at T, which fill at the open of T+1. Tickets created earlier, while CLEAR, still fill. Open positions are never touched; exit policies run as before. |
| reasons logged | `NIFTY_BELOW_SMA200`, `VIX_ABOVE_22` (both joined with `+` if both hold), then `REENTRY_COUNT n/3` on every later ACTIVE session and on the releasing session (`3/3`, state CLEAR). |

## Where it lives
- `stockbot/overlays/market_switch.py` (the rule; state `{"active","count"}` plus a logged copy in `State.overlay_state["market_switch_v1"]`), `stockbot/overlays/__init__.py` (`resolve_default_overlays`).
- `shared.yaml` section `overlays`: `default: [market_switch_v1]` and the five numbers (`market_switch_v1_trigger_sma_period` 200, `_trigger_vix` 22.0, `_reentry_sma_period` 20, `_reentry_vix` 20.0, `_reentry_sessions` 3).
- `stockbot/engine/decide.py`: evaluates the shared default overlays once per session (step 1); while ACTIVE every proposal that passed the eligibility and duplicate checks is recorded in `Decisions.blocked` with reason `MARKET_SWITCH`, stage `overlay`, and is not sized or ticketed. `propose` still runs (so blocked proposals are visible and strategy state advances as before).
- Backtest and live adapters both call `decide(..., default_overlays=...)`; `None` = the shared default, `[]` = explicit opt-out (`run_backtest(..., default_overlays=[])`, the script flag `--overlays none`; the run prints `overlays: none (...)` and the manifest says `"overlays": []`).
- Run files: `stockbot/backtest/outputs.py` (`daily.json` gets `market_switch: {state, reason, reentry_count}` only when the overlay ran; `blocked.json` carries `MARKET_SWITCH`). Shared runner for comparisons: `scripts/run_with_market_switch.py`.

## Hash effects
- `StrategySpec.config_hash()` (every strategy, registered or not): **unchanged**. The switch is a shared default, not a strategy-declared overlay, so `spec.overlays` stays empty and the three registered spec hashes (near_52w_high 359c8331..., short_term_reversal 57b86c47..., pullback_uptrend 81db6427...) do not move.
- `validation_gates` hash (e9b6407f...): unchanged (section untouched).
- `shared_config_hash` in a run manifest: **changes for every run made on this code**, with or without the switch: it now hashes the shared config including the new `overlays` section plus the effective overlay list (id, version, numbers; `[]` when switched off). Stored manifests keep their old value and are not rewritten.
- Manifest: new key `overlays` (list of `{id, version, params}`; `[]` when switched off).
- Behaviour: a registered research script run on this code applies the switch by default (the default is shared). A comparable "without" run needs `default_overlays=[]` / `--overlays none`.

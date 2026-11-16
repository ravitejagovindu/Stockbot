"""lv_trailing_atr3_floor8: the strategy-owned exit policy of lowvol_uptrend. Imports only the interface from ``stockbot.engine.exit_policy``.

  reference  highest close since entry, seeded with the position's entry price (as the library ``trailing_pct`` does);
  each stepped bar:  reference = max(reference, bar.close);  distance = max(3 x ATR14 as of this session, 0.08 x reference);  candidate = reference - distance;
             new stop = max(live stop, candidate)  (proposed only when it is above the live stop; the stop never moves down; the engine also enforces it);
  timing     the stop set on bar T applies from bar T+1 (the engine tests the stop before it calls the policy); the initial stop (the strategy's own) is tested on the entry bar;
  no time exit, no requests: the stop does the exiting.
ATR14 is read through the as-of view (the symbol's last 252 adjusted bars up to the stepped session, ``indicators.atr_last``). If it cannot be computed the distance falls back to the
8% floor and the step is flagged ``ATR_UNAVAILABLE`` (it cannot happen for a position opened by the strategy, which needs 253 bars). State ``{"highest_close": float}`` in the position's
price basis; a corporate action rescales it with the stop's factor.
"""
from __future__ import annotations

from typing import Any, Mapping

from stockbot.engine.exit_policy import PolicyActions
from stockbot.strategies.lowvol_uptrend.indicators import ATR_BARS, atr_last

ID = "lv_trailing_atr3_floor8"
ATR_PERIOD, ATR_MULT, FLOOR = 14, 3.0, 0.08


class LvTrailingAtr3Floor8:
    id = ID

    def initial_state(self, position, view) -> dict:
        return {"highest_close": float(position.entry_price)}

    def step(self, position, bar, view, ctx) -> PolicyActions:
        highest = max(float(position.exit_state.get("highest_close", position.entry_price)), float(bar.close))
        a = atr_last(view.adjusted_bars(position.symbol, lookback=ATR_BARS), ATR_PERIOD)
        flags: tuple = ()
        if a is None:
            distance, flags = FLOOR * highest, ("ATR_UNAVAILABLE",)
        else:
            distance = max(ATR_MULT * a, FLOOR * highest)
        candidate = highest - distance
        return PolicyActions(new_live_stop=candidate if candidate > position.live_stop else None, new_exit_state={"highest_close": highest}, flags=flags)

    def on_corporate_action(self, exit_state: Mapping[str, Any], factor: float) -> dict:
        out = dict(exit_state)
        if "highest_close" in out:
            out["highest_close"] = out["highest_close"] * factor
        return out

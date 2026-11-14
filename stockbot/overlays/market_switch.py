"""market_switch_v1: the OLD kill switch (scripts/provenance/regime/regime_filter.py) as a shared overlay. Semantics are written down in docs/shared/market-switch/BRIEF.md.

State machine, evaluated once per session on the session CLOSE (the view is as-of that session only):
  CLEAR  -> ACTIVE   when Nifty close < SMA(trigger_sma_period) of the Nifty closes   OR   India VIX close > trigger_vix              (both strict)
  ACTIVE -> CLEAR    on the session that completes ``reentry_sessions`` CONSECUTIVE sessions with Nifty close > SMA(reentry_sma_period) AND VIX close < reentry_vix
                     (both strict); any session that misses either condition resets the count to 0. While ACTIVE only the re-entry condition is looked at.
ACTIVE means new entries are blocked (the engine applies it: proposals are recorded as MARKET_SWITCH). Open positions are not touched.
Warm-up as the old code: an SMA needs its full window of closes (``stockbot.data.indicators.sma`` is NaN before that); a missing trigger SMA cannot trigger, a missing re-entry
SMA fails the re-entry condition. Prices are ``close_raw`` of NIFTY50_INDEX and INDIA_VIX, read through the as-of view only. A missing Nifty or VIX close on the as-of session RAISES
(the old code raised RuntimeError); nothing is carried forward, interpolated or failed closed.
Pure: ``evaluate(view, overlay_state)`` returns (signal, new_overlay_state); the state is plain data and carries the hysteresis count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from stockbot.data.asof import NIFTY, VIX
from stockbot.data.indicators import sma

ID = "market_switch_v1"
VERSION = "1.0.0"
BLOCK_REASON = "MARKET_SWITCH"
ACTIVE, CLEAR = "ACTIVE", "CLEAR"
LOOKBACK = 210                      # the old code fetched 210 Nifty closes for the SMAs; the same series is used here so the numbers are bit-identical


class MarketSwitchDataError(RuntimeError):
    """The Nifty or VIX close of the as-of session is missing (or null). The old kill switch raised RuntimeError; so does this."""


@dataclass(frozen=True)
class MarketSwitchParams:
    trigger_sma_period: int = 200
    trigger_vix: float = 22.0
    reentry_sma_period: int = 20
    reentry_vix: float = 20.0
    reentry_sessions: int = 3

    @classmethod
    def from_shared(cls, shared_config) -> "MarketSwitchParams":
        o = shared_config.overlays
        return cls(int(o.market_switch_v1_trigger_sma_period), float(o.market_switch_v1_trigger_vix), int(o.market_switch_v1_reentry_sma_period),
                   float(o.market_switch_v1_reentry_vix), int(o.market_switch_v1_reentry_sessions))

    def as_dict(self) -> dict:
        return {"trigger_sma_period": self.trigger_sma_period, "trigger_vix": self.trigger_vix, "reentry_sma_period": self.reentry_sma_period,
                "reentry_vix": self.reentry_vix, "reentry_sessions": self.reentry_sessions}


class MarketSwitch:
    id = ID
    version = VERSION

    def __init__(self, params: MarketSwitchParams = None):
        self.params = params or MarketSwitchParams()

    def describe(self) -> dict:
        return {"id": self.id, "version": self.version, "params": self.params.as_dict()}

    def _closes(self, view):
        try:
            nb = view.index_bars(NIFTY, LOOKBACK)
            vb = view.index_bars(VIX, 1)
        except (TypeError, ValueError) as exc:                       # a null close: float(None)
            raise MarketSwitchDataError(f"market switch: unreadable Nifty/VIX close on {view.as_of}: {exc}") from exc
        if nb.empty or nb.index[-1] != view.as_of:
            raise MarketSwitchDataError(f"market switch: no Nifty close on {view.as_of}")
        if vb.empty or vb.index[-1] != view.as_of:
            raise MarketSwitchDataError(f"market switch: no VIX close on {view.as_of}")
        return nb["close_raw"].astype(float), float(vb["close_raw"].iloc[-1])

    def evaluate(self, view, overlay_state: Mapping[str, Any]) -> tuple[dict, dict]:
        p = self.params
        closes, vix = self._closes(view)
        close = float(closes.iloc[-1])
        s_trig, s_re = sma(closes, p.trigger_sma_period).iloc[-1], sma(closes, p.reentry_sma_period).iloc[-1]
        s_trig = None if pd.isna(s_trig) else float(s_trig)
        s_re = None if pd.isna(s_re) else float(s_re)
        prev_active, count = bool(overlay_state.get("active", False)), int(overlay_state.get("count", 0))
        reason = None
        if not prev_active:
            below = s_trig is not None and close < s_trig
            vix_hi = vix > p.trigger_vix
            active = below or vix_hi
            if active:
                count = 0
                reason = "+".join(r for r, on in (("NIFTY_BELOW_SMA%d" % p.trigger_sma_period, below), ("VIX_ABOVE_%g" % p.trigger_vix, vix_hi)) if on)
        else:
            active = True
            if (s_re is not None and close > s_re) and vix < p.reentry_vix:
                count += 1
                if count >= p.reentry_sessions:
                    active = False
            else:
                count = 0
            reason = f"REENTRY_COUNT {count}/{p.reentry_sessions}"
        state = {"active": active, "count": count}
        signal = {"state": ACTIVE if active else CLEAR, "active": active, "reason": reason, "block_entries": active, "block_reason": BLOCK_REASON,
                  "reentry_count": count, "nifty_close": close, "nifty_sma_trigger": s_trig, "nifty_sma_reentry": s_re, "vix_close": vix, "as_of": view.as_of.isoformat()}
        return signal, {**state, "state": signal["state"], "reason": reason}

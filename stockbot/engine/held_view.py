"""The view an exit policy sees for a HELD position: its ``adjusted_bars`` / ``raw_bars`` are the held bars (EQ + BE/BZ) when STOCKBOT_NON_EQ=held (owner decision Q4: the ATR of the strategy-owned
exit policies reads held bars). With the switch off ``exit_view`` returns the view itself, so nothing changes. Everything else is delegated to the real view.
The strategies' own files are untouched: the engine hands the policy this view."""
from __future__ import annotations

from stockbot.data.non_eq import switch_on


class HeldView:
    def __init__(self, view):
        self._view = view

    def __getattr__(self, name):
        return getattr(self._view, name)

    def adjusted_bars(self, *a, **k):
        return self._view.held_adjusted_bars(*a, **k)

    def raw_bars(self, *a, **k):
        return self._view.held_raw_bars(*a, **k)


def exit_view(view):
    return HeldView(view) if switch_on() and hasattr(view, "held_adjusted_bars") else view

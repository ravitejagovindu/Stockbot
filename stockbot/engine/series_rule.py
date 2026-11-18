"""The never-buy rule, in the SHARED engine (owner rule, fixed): buy only on EQ series. Never buy a stock in BE, BZ or any other restricted series. A held position may be held or sold.

One function used by every path that creates a new position: the proposal gate and the fill gate in ``engine.decide`` and the fill in ``engine.path`` (matched-random baseline).
No strategy code is involved and none can bypass it. ``blocking_series`` answers with the restricted series code the stock trades in TODAY (as of the view's date), else None.
A stock with no bar at all is not a series question (it cannot be filled anyway: ``fill_ticket`` says NO_BAR_OR_ALREADY_HELD), so it returns None. With the switch STOCKBOT_NON_EQ unset the
view shows EQ bars only, so this returns None and nothing about entries changes (a stock in BE has no EQ bar and can neither be eligible nor filled).
"""
from __future__ import annotations

from typing import Optional

REASON_PROPOSE = "NOT_EQ_SERIES"
REASON_FILL = "NOT_EQ_SERIES_AT_FILL"


def blocking_series(view, symbol: str) -> Optional[str]:
    """The non-EQ series code ("BE", "BZ") of the stock's bar on the view's date, or None (EQ, or no bar, or a view without series information)."""
    fn = getattr(view, "series_on", None)
    if fn is None:
        return None
    s = fn(symbol)
    return None if s in (None, "EQ") else str(s)


def is_buyable(view, symbol: str) -> bool:
    """False exactly when the stock trades in a restricted series on the view's date."""
    return blocking_series(view, symbol) is None

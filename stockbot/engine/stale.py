"""No bars for N sessions (shared rule engine.stale_exit_sessions, one code path for backtest, paper, live and the matched-random baseline).

If a held position's symbol (after symbol linking) has had NO bar for ``N`` consecutive sessions of the engine's session calendar (the view's ``sessions()``), then on that N-th session the
position is closed at its LAST AVAILABLE CLOSE with the normal exit slippage and costs: exit reason ``SYMBOL_NO_BARS`` (``stale_exit``). The decision uses only data up to the session. Before the
N-th session nothing changes; nothing re-opens if bars resume. The closure frees the slot, cash and risk like any other closed trade (a ticket created on that session can use them at the next open).
"""
from __future__ import annotations

REASON = "SYMBOL_NO_BARS"


def stale_sessions(shared_config) -> int:
    """``engine.stale_exit_sessions`` (0 when the config object has no such setting: the rule is then off)."""
    eng = getattr(shared_config, "engine", None)
    return int(getattr(eng, "stale_exit_sessions", 0) or 0)


def no_bars_for(view, symbol: str, n: int) -> bool:
    """True when ``symbol`` has no bar on any of the last ``n`` sessions up to ``view.as_of`` (so, evaluated every session, True first on the n-th consecutive session without a bar)."""
    if n < 1:
        return False
    ses = view.sessions(lookback=n)
    if len(ses) < n:
        return False
    b = getattr(view, "held_raw_bars", view.raw_bars)(symbol, lookback=1)       # held bars: a BE/BZ bar counts as a bar (switch STOCKBOT_NON_EQ=held); with the switch off this IS raw_bars
    return b.empty or b.index[-1] < ses[0]


def stale_detail(symbol: str, n: int) -> str:
    return f"position {symbol}: no bars for {n} sessions; closed in the book at the last close; check the holding manually (rename, merger, suspension, series change)"

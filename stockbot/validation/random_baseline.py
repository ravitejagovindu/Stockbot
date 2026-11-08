"""Matched-random baseline (restructure Phase 7, decision Q5): what would equally exposed random entries have earned under IDENTICAL execution and exits?

For every actual trade: take its signal session (the session before its entry), draw ``draws_per_trade`` symbols at random from the pool eligible on that
date (the shared universe rules, optionally narrowed by a caller-supplied ``pool_filter`` - the strategy's setup condition, if it has one - and never the
actual trade's own symbol), give each draw the actual trade's RELATIVE stop distance (entry - stop) / entry applied to the draw's signal close, and simulate it with
``stockbot.engine.path.simulate_ticket``: the same fill rule (next open, slippage, gap rules), corporate-action rebasing and generic stepping that ``decide`` uses,
with the strategy's own ExitPolicy object. No portfolio effects (no cash competition, no caps). Seeded: same seed, same draws.
Nothing here knows a strategy: the exit policy, the pool filter and the holding limit come from the caller (the spec).
The legacy script ``scripts/redesigned_random_baseline.py`` (trend filter, old stops, old exits) stays as provenance of the rejected CFG-01..06 comparison.
"""
from __future__ import annotations

import random
from datetime import date
from typing import Callable, Optional, Sequence

import pandas as pd

from stockbot.engine.decide import bar_of
from stockbot.engine.path import simulate_ticket
from stockbot.engine.types import Ticket
from stockbot.risk.r_metrics import compute_trade_r
from stockbot.universe.eligibility import eligible_symbols

FORWARD_HORIZONS = (1, 5, 10, 20)


def forward_returns_pct(view_end, symbol: str, entry_date: date, entry_price: float) -> dict:
    """Percent move of the raw close h sessions AFTER the entry session, from the fill price (NaN when the history ends first). ``view_end`` is an as-of view at
    the end of the evaluation window: this is evaluation, not decision making, so it may look past the entry date."""
    b = view_end.raw_bars(symbol, lookback=None, start=entry_date)
    after = [float(c) for d, c in b["close_raw"].items() if d > entry_date]
    return {f"ret_{h}": ((after[h - 1] / entry_price - 1.0) * 100.0 if len(after) >= h else float("nan")) for h in FORWARD_HORIZONS}


def draw_matched_random(actual: pd.DataFrame, *, sessions: Sequence[date], view_at: Callable[[date], object], shared_config, policy, equity: float, draws_per_trade: int,
                        seed: int, pool_filter: Optional[Callable] = None, asm_ranges=None) -> pd.DataFrame:
    """``actual``: unique_trade_id, symbol, entry_date, entry_price, stop, window. Returns one row per simulated draw with matched_trade_id, symbol, window, R columns,
    days_held and forward returns; unfilled draws are skipped (counted in ``attrs['unfilled']`` with their reasons)."""
    rng = random.Random(seed)
    sessions = sorted(sessions)
    index = {d: i for i, d in enumerate(sessions)}
    last = view_at(sessions[-1])
    rows: list = []
    unfilled: dict = {}
    for a in actual.sort_values(["entry_date", "unique_trade_id"]).itertuples(index=False):
        entry = a.entry_date
        if entry not in index or index[entry] == 0:
            unfilled["NO_SIGNAL_SESSION"] = unfilled.get("NO_SIGNAL_SESSION", 0) + 1
            continue
        signal_day = sessions[index[entry] - 1]
        view = view_at(signal_day)
        pool = [s for s in eligible_symbols(view, shared_config.universe, asm_ranges=asm_ranges) if s != a.symbol]
        if pool_filter is not None:
            pool = [s for s in pool if pool_filter(view, s)]
        frac = (a.entry_price - a.stop) / a.entry_price
        picks = rng.sample(pool, min(draws_per_trade, len(pool)))
        for sym in sorted(picks):
            bar = bar_of(view, sym)
            if bar is None:
                continue
            ref = bar.close
            t = Ticket(f"rand:{sym}:{signal_day.isoformat()}", "random", sym, None, signal_day, ref, ref * (1.0 - frac), None, 0, 0.0, 0.0, signal_day)
            trade, _exits, why = simulate_ticket(t, sessions, view_at, shared_config=shared_config, policy=policy, equity=equity)
            if trade is None:
                unfilled[why] = unfilled.get(why, 0) + 1
                continue
            r = compute_trade_r(entry_price=trade.entry_price, stop=trade.initial_stop, shares_initial=trade.shares_initial, pnl_gross=trade.gross_pnl, pnl_net=trade.net_pnl,
                                risk_inr=trade.risk_inr)
            rows.append({"matched_trade_id": a.unique_trade_id, "symbol": sym, "window": a.window, "entry_date": trade.entry_date, "exit_date": trade.exit_date,
                         "entry_price": trade.entry_price, "stop": trade.initial_stop, "exit_reason": trade.exit_reason, "gross_r": r["gross_r"], "net_r": r["net_r"],
                         "days_held": index[trade.exit_date] - index[trade.entry_date], **forward_returns_pct(last, sym, trade.entry_date, trade.entry_price)})
    out = pd.DataFrame(rows)
    out.attrs["unfilled"] = unfilled
    return out

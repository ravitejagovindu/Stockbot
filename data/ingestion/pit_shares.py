"""data/ingestion/pit_shares.py — point-in-time shares outstanding (F2b).

shares(t) = current issued size  x  product of the price factors of every SPLIT/BONUS with ex_date > t
(a 1:10 split has price factor 0.1 and ten times the shares afterwards, so the count before the ex-date is a tenth of the count after).

Only splits and bonuses are walked back.  Anything the log cannot adjust (merger, demerger, large rights, unsupported split/bonus:
``data/reference/unadjusted_events.csv``) changes the share count by an unknown amount, so every segment dated BEFORE the latest such event
is marked ``reliable = 0`` and the screener treats it as missing data.  Small rights issues, buy-backs, ESOPs and QIPs are not modelled.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

EPOCH = date(2013, 1, 1)


def derive_segments(shares_now: int, events: Iterable[tuple[date, float]], last_unadjusted: Optional[date] = None,
                    epoch: date = EPOCH) -> list[tuple[date, int, int]]:
    """[(effective_date, shares_count, reliable)] ascending.  ``events`` = (ex_date, price_factor) for SPLIT/BONUS rows."""
    by_date: dict[date, float] = {}
    for d, f in events:
        if f <= 0:
            raise ValueError(f"non-positive factor {f} on {d}")
        by_date[d] = by_date.get(d, 1.0) * f
    if last_unadjusted is not None:
        by_date.setdefault(last_unadjusted, 1.0)                      # breakpoint: counts before it are unreliable
    dates = sorted(d for d in by_date if d > epoch)
    after = float(shares_now)
    seg: list[tuple[date, float]] = []
    for d in reversed(dates):                                           # walk back from today
        seg.append((d, after))
        after = after * by_date[d]
    seg.append((epoch, after))
    seg.reverse()
    return [(d, int(round(v)), 0 if (last_unadjusted is not None and d < last_unadjusted) else 1) for d, v in seg]


def shares_on(segments: list[tuple[date, int, int]], when: date) -> Optional[tuple[int, int]]:
    """(shares, reliable) in force on ``when`` or None if before the first segment."""
    cur = None
    for d, n, r in segments:
        if d <= when:
            cur = (n, r)
        else:
            break
    return cur

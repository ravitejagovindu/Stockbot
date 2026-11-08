"""NOT USED (F2b closed 2026-11-08: failed its pre-registered spot-check bar; the table is not loaded and the screener does not read it). Kept for the record - see docs/data_audit/DATA_KNOWN_ISSUES.md KI-001.

scripts/provenance/pit_shares.py — point-in-time shares outstanding (F2b).

shares(t) = anchor shares  x  M(t) / M(anchor_date),  M(t) = product of 1/factor over every change dated <= t.
For the usual case the anchor is the current issued size (a Yahoo snapshot of 2026-10-02): the count before a 1:10 split (price factor 0.1) is a tenth of the count after.
Other anchors: a same-ISIN successor's count at the predecessor's last day, or a count read from a shareholding filing (``data/reference/pit_shares_anchors.csv``).

Modelled:  SPLIT / BONUS (price factor from the corporate-action log; change on the ex-date);  RIGHTS whose ratio parses from the feed text
(``Rights n:d`` = n new shares per d held, factor d/(n+d)); the new shares are allotted weeks after the ex-date, so the change is placed 45 days AFTER the ex-date
and the whole band [ex-45d, ex+45d) is marked unreliable;  demergers are share-neutral for the parent (reviewer D1).
Excluded (segments dated before them are ``reliable = 0``): mergers, unsupported split/bonus, manual unadjusted events, rights whose ratio does not parse.

NOT MODELLED (error source, measured by the spot-check, reviewer D3): QIPs, preferential allotments, ESOP allotments, warrant conversions, buy-backs,
and any rights issue below the "large" threshold of the unadjusted-event list or not fully subscribed.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Iterable, Optional

EPOCH = date(2013, 1, 1)
RIGHTS_BAND_DAYS = 45
_RATIO = re.compile(r"(\d+)\s*:\s*(\d+)")


def parse_rights_ratio(detail: str) -> Optional[tuple[int, int]]:
    """(new, held) from feed text such as '2:3 Rights 2:3@Prem Rs.345/-'.  None unless exactly one distinct n:d ratio appears."""
    found = {(int(a), int(b)) for a, b in _RATIO.findall(detail or "")}
    if len(found) != 1:
        return None
    n, d = next(iter(found))
    return (n, d) if n > 0 and d > 0 else None


def rights_factor(n: int, d: int) -> float:
    return d / (n + d)


def derive_segments(shares_now: int, events: Iterable[tuple[date, float]], last_unadjusted: Optional[date] = None,
                    epoch: date = EPOCH, *, rights: Iterable[tuple[date, float]] = (), band: int = RIGHTS_BAND_DAYS,
                    anchor_date: Optional[date] = None, anchor_reliable: bool = True) -> list[tuple[date, int, int]]:
    """[(effective_date, shares_count, reliable)] ascending.

    ``events``: (ex_date, price_factor) for SPLIT/BONUS.  ``rights``: (ex_date, factor) for parsed rights.
    ``anchor_date``: date at which ``shares_now`` holds (default: after every event).  ``last_unadjusted``: segments before it are unreliable.
    """
    change: dict[date, float] = {}
    bands: list[tuple[date, date]] = []
    for d, f in events:
        if f <= 0:
            raise ValueError(f"non-positive factor {f} on {d}")
        change[d] = change.get(d, 1.0) * f
    for d, f in rights:
        if f <= 0:
            raise ValueError(f"non-positive factor {f} on {d}")
        eff = d + timedelta(days=band)
        change[eff] = change.get(eff, 1.0) * f
        bands.append((d - timedelta(days=band), eff))
    points = {epoch} | {d for d in change if d > epoch}
    for a, b in bands:
        points |= {x for x in (a, b) if x > epoch}
    if last_unadjusted is not None and last_unadjusted > epoch:
        points.add(last_unadjusted)
    pts = sorted(points)

    def mult(t: date) -> float:                                   # shares proportional to prod(1/f) over changes <= t
        m = 1.0
        for d, f in change.items():
            if d <= t:
                m /= f
        return m

    m_anchor = mult(anchor_date) if anchor_date is not None else mult(date.max)
    out = []
    for p in pts:
        n = int(round(shares_now * mult(p) / m_anchor))
        rel = anchor_reliable and not (last_unadjusted is not None and p < last_unadjusted) and not any(a <= p < b for a, b in bands)
        out.append((p, n, 1 if rel else 0))
    return out


def shares_on(segments: list[tuple[date, int, int]], when: date) -> Optional[tuple[int, int]]:
    """(shares, reliable) in force on ``when`` or None if before the first segment."""
    cur = None
    for d, n, r in segments:
        if d <= when:
            cur = (n, r)
        else:
            break
    return cur

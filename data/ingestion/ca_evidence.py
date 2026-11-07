"""data/ingestion/ca_evidence.py — evidence tiers for split/bonus events (F2 Step 4).

STRONG       Yahoo-implied factor within 3% of the logged factor.
WEAK         raw close-to-close ratio (best day pair within +-2 sessions of the ex-date) within 25% of the logged factor AND
             closer (in log terms) to the logged factor than to any other standard ratio, so a 1:1 bonus (0.5) is never
             accepted on a price move that looks like a 1:2 bonus (0.667).
UNSUPPORTED  anything else (including no price data): the event is stored as ``OTHER`` and is not price-moving.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

STRONG_TOL = 0.03
WEAK_TOL = 0.25
WINDOW = 2


# The factors that occur at least three times in the NSE feed (1,111 split/bonus ex-dates), plus "no change".  A dense set
# (every 1/k and d/(d+n)) would make any 10% price move ambiguous; this one contains what companies actually do.
STANDARD_RATIOS = sorted({1.0, 1 / 2, 1 / 5, 1 / 10, 2 / 3, 1 / 3, 3 / 4, 2 / 5, 4 / 5, 10 / 11, 5 / 6, 1 / 4, 5 / 7, 1 / 6,
                          3 / 5, 4 / 7, 2 / 7, 1 / 11})


def nearest_standard(ratio: float, logged: float) -> float:
    """Standard ratio (or the logged factor itself) closest to ``ratio`` in log terms."""
    return min([*STANDARD_RATIOS, logged], key=lambda s: abs(math.log(ratio / s)))


def classify(f: float, raw_ratio: Optional[float], yahoo_factor: Optional[float]) -> tuple[str, str]:
    """Return (tier, evidence text) for a logged price factor ``f`` (<1 for splits/bonuses)."""
    ev = []
    if yahoo_factor is not None and yahoo_factor > 0:
        ok = abs(yahoo_factor / f - 1) <= STRONG_TOL
        ev.append(f"yahoo factor {yahoo_factor:.4f} vs logged {f:.4f} ({'within' if ok else 'outside'} 3%)")
        if ok:
            return "STRONG", "; ".join(ev)
    if raw_ratio is None or raw_ratio <= 0:
        return "UNSUPPORTED", "; ".join(ev + ["no price data around the ex-date"])
    near = abs(raw_ratio / f - 1) <= WEAK_TOL
    nearest = nearest_standard(raw_ratio, f)
    closest = math.isclose(nearest, f, rel_tol=1e-9)
    ev.append(f"raw close ratio {raw_ratio:.4f} vs logged {f:.4f} ({'within' if near else 'outside'} 25%; "
              f"{'logged factor is' if closest else 'nearer standard ratio is ' + format(nearest, '.4f') + ', not'} the closest)")
    if near and closest:
        return "WEAK", "; ".join(ev)
    return "UNSUPPORTED", "; ".join(ev)


def best_pair(dates: Sequence[str], close: Sequence[float], ex_index: int, f: float) -> tuple[Optional[float], Optional[int]]:
    """Close-to-close ratio of the day pair (t-1, t), t within +-WINDOW sessions of the ex-date index, closest to ``f``."""
    best = None
    for t in range(ex_index - WINDOW, ex_index + WINDOW + 1):
        if 1 <= t < len(close) and close[t - 1] > 0 and close[t] > 0:
            r = close[t] / close[t - 1]
            d = abs(math.log(r / f))
            if best is None or d < best[0]:
                best = (d, r, t - ex_index)
    return (best[1], best[2]) if best else (None, None)

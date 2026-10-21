# Stockbot — Remediation & Paper-Trade Implementation Plan

**Basis:** repo snapshot `Stockbot-master__1_` (updated 2026-10-16). File and function names below were read from that snapshot.
**Status of the code in this plan:** written against the snapshot but **not executed** by the author (no dependencies or data available). Treat every code block as a reviewed draft: run the acceptance test in each step before merging.
**Priority:** P0 = blocks the paper run · P1 = must be done before real money · P2 = hygiene. **Effort:** S (<½ day) · M (1–2 days) · L (3+ days).

---

## 0. Ground rules and gates

**Rules**
1. Anything that changes *what the system trades* must be merged **before** the paper-run freeze (Gate G3). Measurement-only work may run in parallel with the paper run.
2. One engine: live, paper and backtest all call the same pure functions (`engine_core/lifecycle_rules.py`). No copy-pasted lifecycle logic anywhere.
3. No broker order routing, ever (API, browser automation, scripted tickets). A pytest enforces it (Step 4.4).
4. Any change to `strategy_config.yaml` or engine code after authorization → re-run the backtest → re-authorize → paper count restarts.
5. Fail closed: missing data, missing files or unverified rows must stop the run, never "assume all clear".

**Gates**
| Gate | Meaning | Must be true |
|---|---|---|
| G1 | Engine correct | Phase 1 + Phase 2 tests green; golden-master test passes |
| G2 | Backtest honest | Phase 3 re-run done with costs, tax, correct metrics, out-of-sample window; meets criteria in `docs/PAPER_TRADE_CRITERIA.md` |
| G3 | Freeze | Phase 4 done; commit authorized; paper run starts |
| G4 | Paper passed | Phase 5 criteria met |
| G5 | Live small | Phase 6 checklist done |

---

## Phase 0 — Decisions and freeze (before any coding) — P0, S

### Step 0.1 — Owner decisions (write the answers into the repo)
| # | Decision | Recommended default |
|---|---|---|
| D1 | Price data for BOTH backtest and live | Raw NSE bhavcopy + `corporate_actions_log`, adjusted in memory (not Yahoo-adjusted CSVs) |
| D2 | Entry quality filters | Enable trend filter + 20-day breakout trigger (Step 1.5). If disabled, tickets will include falling-knife setups |
| D3 | Pass criteria numbers | See Step 0.3 |
| D4 | Paper duration | ≥ 3 months **and** ≥ 60 closed trades (whichever is longer) |
| D5 | Cost and tax rates | Put in config (Step 0.2); **verify current rates yourself** before use |
| D6 | Sector source | NSE sector classification CSV committed at `data/reference/sector_map.csv` |

### Step 0.2 — Config additions (`strategy_config.yaml`)
Add (do not remove existing keys yet; removals are in later steps):
```yaml
runtime:
  mode: PAPER                  # PAPER | LIVE. The ONLY switch. Never infer mode from anything else.
  paper_start_equity: 1000000  # INR

execution:
  entry_fill: NEXT_OPEN        # signal at close T -> fill at open T+1
  entry_slippage_pct: 0.10
  exit_slippage_pct: 0.10
  max_entry_gap_up_pct: 3.0    # skip ticket if open > ticket entry * (1 + 3%)
  min_rr_at_fill: 1.5          # re-check R:R at the actual fill

costs:                         # VERIFY CURRENT RATES. Values below are placeholders from late-2024 schedules.
  stt_buy_pct: 0.10            # delivery
  stt_sell_pct: 0.10           # delivery
  brokerage_per_order_inr: 0.0 # set to your broker's delivery brokerage
  exchange_txn_pct: 0.00297
  sebi_fee_pct: 0.0001
  stamp_duty_buy_pct: 0.015
  gst_pct: 18.0                # on brokerage + exchange + SEBI fees
  dp_charge_per_sell_inr: 15.34
  stcg_tax_pct: 20.0           # short-term capital gains; verify for your status

risk:
  max_rr_cap: 6.0              # block R:R above this: almost always a data artefact

entry_filters:
  trend_filter_enabled: true   # close > SMA(fast) and SMA(fast) > SMA(slow)
  trend_fast_sma: 50
  trend_slow_sma: 200
  breakout_required: true      # close >= highest high of the prior N sessions
  breakout_lookback: 20
  rs_lookback_days: 63         # used only for deterministic ranking

profit_ratchet:
  enabled: true
  active_in_bull: false        # REPLACES enabled_regimes (Step 1.4)
```

### Step 0.3 — Pass criteria file `docs/PAPER_TRADE_CRITERIA.md`
Write this **before** seeing any new results. Proposed defaults (owner may change, but only now):
```
Backtest (corrected engine, net of costs and tax), BOTH windows incl. one untouched out-of-sample window:
  max drawdown            < 15%
  CAGR minus after-tax Nifty buy-and-hold CAGR   >= +2.0%   (no underperformance tolerance)
  expectancy              >= +0.15 R per trade (net of costs)
  profit factor           >= 1.3
Paper run (>= 3 months AND >= 60 closed trades):
  expectancy within 0.25 R of backtest expectancy
  win rate (net P&L > 0, partial exits NOT counted as trades) within 12 points of backtest
  profit factor >= 1.2
  paper max drawdown < 12%
  skipped-ticket rate < 40% (otherwise fills are not representative)
```

---

## Phase 1 — Make the engine correct (P0)

### Step 1.1 — Fix corporate-action adjustment (P0, M)
**Bug:** `engine_core/adjustments.py::get_adjusted_series` applies one factor to every row and only counts actions with `ex_date > as_of_date`. With `as_of_date = today`, past splits/bonuses are never applied, so ATR, stops and the 52-week-high target break around splits.

**Change** in `engine_core/adjustments.py`. Keep `compute_cumulative_factor` unchanged (existing tests use it). Add imports `import numpy as np` at the top, then add and replace:
```python
def _as_date(d):
    """datetime.date passthrough; datetime/Timestamp -> date."""
    return d.date() if hasattr(d, "date") and callable(getattr(d, "date")) else d


def _action_factor(action: dict) -> float:
    """Price factor for ONE action (SPLIT/BONUS). Other types -> 1.0."""
    t = (action.get("action_type") or "").upper()
    num, den = action.get("ratio_numerator"), action.get("ratio_denominator")
    if t == "SPLIT":
        if not num or not den:
            raise ValueError(f"SPLIT missing ratio: num={num} den={den}")
        return num / den
    if t == "BONUS":
        if num is None or den is None:
            raise ValueError(f"BONUS missing ratio: num={num} den={den}")
        return den / (den + num)
    return 1.0


def compute_row_factors(index, corporate_actions: list[dict], as_of_date: date) -> pd.Series:
    """factor[d] = product of f(action) over actions with ex_date <= as_of_date AND d < ex_date.

    Meaning: history is expressed in the price basis in force on as_of_date.
    Bars before an ex-date are scaled; the ex-date bar and later bars are not.
    Actions after as_of_date are unknown yet and ignored (point-in-time safe).
    """
    dates = [_as_date(d) for d in index]
    factors = np.ones(len(dates), dtype="float64")
    for a in corporate_actions:
        ex = a["ex_date"]
        if isinstance(ex, str):
            ex = date.fromisoformat(ex)
        ex = _as_date(ex)
        if ex > as_of_date:
            continue
        f = _action_factor(a)
        if f == 1.0:
            continue
        mask = np.fromiter((d < ex for d in dates), dtype=bool, count=len(dates))
        factors[mask] *= f
    return pd.Series(factors, index=index)


def get_adjusted_series(raw_ohlcv: pd.DataFrame, corporate_actions: list[dict], as_of_date: date) -> pd.DataFrame:
    """Per-row backward adjustment. Returns open_adj/high_adj/low_adj/close_adj. Volume is NOT returned."""
    f = compute_row_factors(raw_ohlcv.index, corporate_actions, as_of_date)
    return pd.DataFrame(
        {
            "open_adj": raw_ohlcv["open_raw"] * f,
            "high_adj": raw_ohlcv["high_raw"] * f,
            "low_adj": raw_ohlcv["low_raw"] * f,
            "close_adj": raw_ohlcv["close_raw"] * f,
        },
        index=raw_ohlcv.index,
    )
```
Also delete the "Notes" paragraph in the old docstring that claims one factor is correct.

**Tests** (`tests/unit/test_adjustments.py`): delete `test_1_for_2_split_halves_all_ohlc` (it asserts the old behaviour) and add:
```python
def _df(dates, close):
    return pd.DataFrame({"open_raw": close, "high_raw": close, "low_raw": close, "close_raw": close}, index=dates)

SPLIT = {"ex_date": date(2024, 5, 31), "action_type": "SPLIT", "ratio_numerator": 1.0, "ratio_denominator": 2.0}
D = [date(2024, 5, 29), date(2024, 5, 30), date(2024, 5, 31), date(2024, 6, 3)]

def test_split_adjusts_only_bars_before_ex_date():
    adj = get_adjusted_series(_df(D, [200.0, 200.0, 100.0, 100.0]), [SPLIT], as_of_date=date(2024, 6, 3))
    assert list(adj["close_adj"]) == [100.0, 100.0, 100.0, 100.0]

def test_split_after_as_of_date_ignored():
    adj = get_adjusted_series(_df(D, [200.0, 200.0, 100.0, 100.0]), [SPLIT], as_of_date=date(2024, 5, 30))
    assert list(adj["close_adj"]) == [200.0, 200.0, 100.0, 100.0]

def test_bonus_and_split_compound():
    bonus = {"ex_date": date(2024, 5, 30), "action_type": "BONUS", "ratio_numerator": 1.0, "ratio_denominator": 1.0}  # x0.5
    adj = get_adjusted_series(_df(D, [400.0, 200.0, 100.0, 100.0]), [bonus, SPLIT], as_of_date=date(2024, 6, 3))
    assert list(adj["close_adj"]) == [100.0, 100.0, 100.0, 100.0]

def test_no_price_jump_across_split_after_adjustment():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
    close = [500.0] * 20 + [100.0] * 20            # 1:5 split on bar 20, flat economics
    act = {"ex_date": dates[20], "action_type": "SPLIT", "ratio_numerator": 1.0, "ratio_denominator": 5.0}
    adj = get_adjusted_series(_df(dates, close), [act], as_of_date=dates[-1])
    assert adj["close_adj"].pct_change().abs().max() < 1e-9
```
(add `from datetime import timedelta` to the test imports).

### Step 1.2 — One candidate builder + one data basis (P0, M)
**Goal:** live and backtest build candidates through the same function, with adjustment applied in both.

**New file `engine_core/candidate_builder.py`:**
```python
"""Single place that turns symbols into candidate dicts. Used by live pipeline AND backtest simulator."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select

from data.db.models import CorporateActionsLog, MarketDataLake
from engine_core.adjustments import get_adjusted_series
from engine_core.sector_map import sector_for


def build_candidate_dicts(session, config: dict, symbols: list[str], eval_date: date) -> list[dict]:
    lookback = int(config.get("data", {}).get("resistance_lookback_days", 252)) + 30
    out: list[dict] = []
    for sym in symbols:
        rows = session.execute(
            select(MarketDataLake.trade_date, MarketDataLake.open_raw, MarketDataLake.high_raw,
                   MarketDataLake.low_raw, MarketDataLake.close_raw, MarketDataLake.volume_raw)
            .where(MarketDataLake.symbol == sym)
            .where(MarketDataLake.trade_date <= eval_date)
            .order_by(MarketDataLake.trade_date.desc())
            .limit(lookback)
        ).all()
        if not rows:
            continue
        raw = pd.DataFrame(
            [{"trade_date": r.trade_date, "open_raw": float(r.open_raw), "high_raw": float(r.high_raw),
              "low_raw": float(r.low_raw), "close_raw": float(r.close_raw), "volume_raw": int(r.volume_raw)}
             for r in reversed(rows)]
        ).set_index("trade_date")
        corp = [
            {"ex_date": c.ex_date, "action_type": c.action_type,
             "ratio_numerator": c.ratio_numerator, "ratio_denominator": c.ratio_denominator}
            for c in session.execute(
                select(CorporateActionsLog).where(CorporateActionsLog.symbol == sym)
                .order_by(CorporateActionsLog.ex_date)).scalars().all()
        ]
        out.append({
            "symbol": sym,
            "raw_ohlcv": raw,
            "adjusted_ohlcv": get_adjusted_series(raw, corp, as_of_date=eval_date),
            "sector": sector_for(sym),
            "corporate_actions": corp,
        })
    return out
```
**Edits:** in `live_runner/pipeline.py` replace the whole body of `_build_candidate_dicts` (lines ~280-327) with
```python
        from engine_core.candidate_builder import build_candidate_dicts
        return build_candidate_dicts(self.session, self.config, symbols, eval_date)
```
`Pass1NaiveRun._build_candidate_dicts` is deleted in Step 3.4 (the simulator uses the shared builder).

**Data basis (decision D1):**
1. Backfill raw NSE bhavcopy into `market_data_lake` for every backtest window, and populate `corporate_actions_log` (splits, bonuses) for the same symbols.
2. Prove the two sources agree. Add `scripts/compare_price_sources.py`:
```python
import argparse, sys
from datetime import date
import pandas as pd
from sqlalchemy import create_engine, text
from engine_core.adjustments import get_adjusted_series

def load(engine, sym):
    df = pd.read_sql(text("SELECT trade_date, open_raw, high_raw, low_raw, close_raw FROM market_data_lake "
                          "WHERE symbol=:s ORDER BY trade_date"), engine, params={"s": sym}, parse_dates=["trade_date"])
    df["trade_date"] = df["trade_date"].dt.date
    return df.set_index("trade_date")

def actions(engine, sym):
    df = pd.read_sql(text("SELECT ex_date, action_type, ratio_numerator, ratio_denominator FROM corporate_actions_log "
                          "WHERE symbol=:s"), engine, params={"s": sym}, parse_dates=["ex_date"])
    df["ex_date"] = df["ex_date"].dt.date
    return df.to_dict("records")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yahoo-db", required=True); ap.add_argument("--bhav-db", required=True)
    ap.add_argument("--symbols", required=True); ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--tol", type=float, default=0.01)   # 1% (Yahoo may also adjust for dividends)
    a = ap.parse_args()
    ey, eb, since, bad = create_engine(a.yahoo_db), create_engine(a.bhav_db), date.fromisoformat(a.since), False
    for sym in a.symbols.split(","):
        y = load(ey, sym); b = load(eb, sym)
        badj = get_adjusted_series(b, actions(eb, sym), as_of_date=date.today())
        j = y[["close_raw"]].join(badj[["close_adj"]], how="inner").loc[since:]
        worst = ((j["close_raw"] - j["close_adj"]).abs() / j["close_adj"]).max()
        print(f"{sym:12s} rows={len(j):5d} worst_diff={worst:.3%}")
        bad |= worst > a.tol
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
```
**Acceptance:** run on ≥10 symbols including ≥3 with a split/bonus since 2023; exit code 0. Do not proceed to Step 3.4 until this passes or D1 is changed.

### Step 1.3 — One lifecycle engine: `engine_core/lifecycle_rules.py` (P0, L)
This module is the single source of truth for stops, state transitions, partial profits, time decay and entry fills. It has no DB and no pandas. It deliberately fixes three behaviours: **gap-aware stop fills**, **time-decay exit at the next open**, **entry at the next open**.

**New file:**
```python
"""engine_core/lifecycle_rules.py — pure lifecycle + execution rules (no DB, no pandas)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional

INITIAL_RISK, RISK_FREE_1_TO_1, TRAILING_ATR = "INITIAL_RISK", "RISK_FREE_1_TO_1", "TRAILING_ATR"
PARABOLIC_TRAILING, PENDING_MANUAL_EXIT = "PARABOLIC_TRAILING", "PENDING_MANUAL_EXIT"


@dataclass(frozen=True)
class LifecycleRules:
    time_decay_sessions: int
    trail_mult_normal: float
    trail_mult_kill: float
    parabolic_enabled: bool
    parabolic_thresh_atr: float
    parabolic_lookback: int
    parabolic_mult: float
    partial_enabled: bool
    partial_ladder: tuple          # ((rr_trigger, exit_pct), ...) ascending
    ratchet_enabled: bool
    ratchet_active_in_bull: bool
    ratchet_rungs: tuple           # ((trigger_rr, lock_rr), ...) ascending

    @staticmethod
    def from_config(cfg: dict) -> "LifecycleRules":
        risk, tm = cfg["risk"], cfg["trade_management"]
        par, pp, pr = cfg.get("parabolic_stop", {}), cfg.get("partial_profit", {}), cfg.get("profit_ratchet", {})
        ladder = tuple(sorted(((float(r["rr_trigger"]), float(r["exit_pct"])) for r in pp.get("exit_ladder", [])),
                              key=lambda x: x[0]))
        rungs = tuple(sorted(((float(r["trigger_rr"]), float(r["lock_rr"])) for r in pr.get("rungs", [])),
                             key=lambda x: x[0]))
        return LifecycleRules(
            time_decay_sessions=int(tm["time_decay_sessions"]),
            trail_mult_normal=float(risk.get("trailing_stop_atr_multiplier", 2.5)),
            trail_mult_kill=float(risk.get("trailing_stop_atr_multiplier_kill_switch", 2.0)),
            parabolic_enabled=bool(par.get("enabled", False)),
            parabolic_thresh_atr=float(par.get("acceleration_threshold_atr", 3.0)),
            parabolic_lookback=int(par.get("acceleration_lookback_days", 5)),
            parabolic_mult=float(par.get("parabolic_atr_multiplier", 1.0)),
            partial_enabled=bool(pp.get("enabled", False)),
            partial_ladder=ladder,
            ratchet_enabled=bool(pr.get("enabled", False)),
            ratchet_active_in_bull=bool(pr.get("active_in_bull", False)),
            ratchet_rungs=rungs,
        )


@dataclass
class PosState:
    entry_price: float
    initial_stop: float
    live_stop: float
    target: float
    state: str = INITIAL_RISK
    days_held: int = 0
    highest_high: float = 0.0
    shares_remaining: int = 0
    last_partial_rr: float = 0.0
    partial_count: int = 0

    @property
    def one_r(self) -> float:
        return self.entry_price - self.initial_stop


@dataclass(frozen=True)
class Bar:           # split-ADJUSTED prices, as of the evaluation date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class BarCtx:
    atr14: float
    kill_switch: bool
    is_bull: bool
    close_n_ago: Optional[float] = None   # see parabolic_ref_close()


@dataclass(frozen=True)
class Exit:
    reason: str       # STOP_HIT | TIME_DECAY | PARTIAL_PROFIT
    price: float
    shares: int


@dataclass
class BarResult:
    pos: PosState
    closed: bool
    exits: list = field(default_factory=list)
    flags: list = field(default_factory=list)


def parabolic_ref_close(closes: list, lookback: int) -> Optional[float]:
    """Same reference the live code used: closes[-lookback] with lookback=min(lookback, len)."""
    lb = min(lookback, len(closes))
    return float(closes[-lb]) if lb >= 2 else None


def advance_one_bar(pos: PosState, bar: Bar, ctx: BarCtx, rules: LifecycleRules,
                    exit_slippage_pct: float = 0.0) -> BarResult:
    """Advance one position by one trading bar. Never mutates `pos`.

    Order: (0) pending time-decay exit at today's OPEN -> (1) stop check vs the stop live at yesterday's close,
    gap-aware (fill = min(open, stop)) -> (2) age/high -> (3) state machine + trailing + ratchet ->
    (4) partial profit (limit sell: fill = max(open, limit)).
    """
    p = replace(pos)
    exits: list = []
    flags: list = []
    slip = 1.0 - exit_slippage_pct / 100.0

    if p.state == PENDING_MANUAL_EXIT:
        exits.append(Exit("TIME_DECAY", bar.open * slip, p.shares_remaining))
        p.shares_remaining = 0
        return BarResult(p, True, exits, ["TIME_DECAY_EXIT"])

    if bar.low <= p.live_stop:
        exits.append(Exit("STOP_HIT", min(bar.open, p.live_stop) * slip, p.shares_remaining))
        p.shares_remaining = 0
        return BarResult(p, True, exits, ["STOP_HIT"] + (["GAP_THROUGH_STOP"] if bar.open < pos.live_stop else []))

    p.days_held += 1
    p.highest_high = max(p.highest_high, bar.high)
    one_r = p.one_r
    mult = rules.trail_mult_kill if ctx.kill_switch else rules.trail_mult_normal

    if p.state == INITIAL_RISK:
        if p.highest_high >= p.entry_price + one_r:
            p.state, p.live_stop = RISK_FREE_1_TO_1, max(p.live_stop, p.entry_price)
        elif p.days_held >= rules.time_decay_sessions:
            p.state = PENDING_MANUAL_EXIT
            flags.append("TIME_DECAY_FLAGGED")
    elif p.state == RISK_FREE_1_TO_1:
        if p.highest_high > p.target:
            p.state = TRAILING_ATR
            p.live_stop = max(p.live_stop, p.highest_high - mult * ctx.atr14)

    if p.state == TRAILING_ATR:
        para = (rules.parabolic_enabled and ctx.atr14 > 0 and ctx.close_n_ago is not None
                and (bar.close - ctx.close_n_ago) >= rules.parabolic_thresh_atr * ctx.atr14)
        if para:
            p.state = PARABOLIC_TRAILING
        else:
            p.live_stop = max(p.live_stop, p.highest_high - mult * ctx.atr14)
    if p.state == PARABOLIC_TRAILING:
        p.live_stop = max(p.live_stop, p.highest_high - rules.parabolic_mult * ctx.atr14)

    ratchet_on = rules.ratchet_enabled and (rules.ratchet_active_in_bull or not ctx.is_bull)
    if ratchet_on and one_r > 0 and p.state != PENDING_MANUAL_EXIT:
        hi_rr = (p.highest_high - p.entry_price) / one_r
        for trig, lock in rules.ratchet_rungs:
            if hi_rr >= trig:
                p.live_stop = max(p.live_stop, p.entry_price + lock * one_r)

    if rules.partial_enabled and rules.partial_ladder and one_r > 0 and p.shares_remaining > 0:
        cur_rr = (bar.high - p.entry_price) / one_r
        for trig, pct in rules.partial_ladder:
            if trig > p.last_partial_rr and cur_rr >= trig:
                n = math.floor(p.shares_remaining * pct / 100.0)
                if n > 0:
                    limit = p.entry_price + trig * one_r
                    exits.append(Exit("PARTIAL_PROFIT", max(bar.open, limit) * slip, n))
                    p.shares_remaining -= n
                    p.last_partial_rr = trig
                    p.partial_count += 1
                    flags.append(f"PARTIAL_{n}_SHARES")
                break

    return BarResult(p, False, exits, flags)


@dataclass(frozen=True)
class EntryPlan:
    ok: bool
    reason: str
    fill_price: float = 0.0
    shares: int = 0
    rr_at_fill: float = 0.0


def plan_entry_fill(*, ticket_entry: float, stop: float, target: float, next_open: float, equity: float,
                    risk_pct: float, slippage_pct: float, max_gap_up_pct: float, min_rr: float,
                    cash: Optional[float] = None) -> EntryPlan:
    """Decide whether/how a ticket generated at close T is filled at open T+1 (paper + backtest)."""
    if next_open <= stop:
        return EntryPlan(False, "GAP_THROUGH_STOP")
    if next_open > ticket_entry * (1 + max_gap_up_pct / 100.0):
        return EntryPlan(False, "GAP_UP_TOO_LARGE")
    fill = next_open * (1 + slippage_pct / 100.0)
    risk_ps = fill - stop
    if risk_ps <= 0:
        return EntryPlan(False, "NONPOSITIVE_RISK")
    rr = (target - fill) / risk_ps
    if rr < min_rr:
        return EntryPlan(False, f"RR_AT_FILL_TOO_LOW({rr:.2f})", fill, 0, rr)
    shares = math.floor(equity * risk_pct / 100.0 / risk_ps)
    if cash is not None:
        shares = min(shares, math.floor(cash / fill))
    if shares < 1:
        return EntryPlan(False, "SIZE_ZERO", fill, 0, rr)
    return EntryPlan(True, "OK", fill, shares, rr)
```
**Tests** `tests/unit/test_lifecycle_rules.py`:
```python
from engine_core.lifecycle_rules import *

CFG = {"risk": {}, "trade_management": {"time_decay_sessions": 15},
       "partial_profit": {"enabled": True, "exit_ladder": [{"rr_trigger": 1.0, "exit_pct": 12}]},
       "profit_ratchet": {"enabled": True, "active_in_bull": False, "rungs": [{"trigger_rr": 2.0, "lock_rr": 1.0}]}}
R = LifecycleRules.from_config(CFG)
CTX = BarCtx(atr14=2.0, kill_switch=False, is_bull=True)

def pos(**k):
    d = dict(entry_price=100.0, initial_stop=95.0, live_stop=95.0, target=110.0, highest_high=100.0, shares_remaining=100)
    d.update(k); return PosState(**d)

def test_gap_down_fills_at_open_not_stop():
    r = advance_one_bar(pos(), Bar(90, 91, 88, 89), CTX, R)
    assert r.closed and r.exits[0].reason == "STOP_HIT" and r.exits[0].price == 90.0

def test_time_decay_flag_then_exit_at_next_open():
    p = pos(days_held=14)
    r1 = advance_one_bar(p, Bar(100, 101, 99, 100), CTX, R)
    assert r1.pos.state == PENDING_MANUAL_EXIT and not r1.closed
    r2 = advance_one_bar(r1.pos, Bar(101, 103, 100, 102), CTX, R)
    assert r2.closed and r2.exits[0].reason == "TIME_DECAY" and r2.exits[0].price == 101.0

def test_decay_never_fires_after_graduation():          # day 8 touches 1R, pullback, day 15+
    p = pos()
    r = advance_one_bar(p, Bar(100, 106, 99, 105), CTX, R)       # touches +1R
    assert r.pos.state == RISK_FREE_1_TO_1
    q = r.pos; q.days_held = 20
    r2 = advance_one_bar(q, Bar(103, 104, 100, 101), CTX, R)
    assert r2.pos.state != PENDING_MANUAL_EXIT

def test_partial_fills_at_max_of_open_and_limit():
    r = advance_one_bar(pos(), Bar(107, 108, 106, 107), CTX, R)  # gaps over the 1R limit (105)
    ex = [e for e in r.exits if e.reason == "PARTIAL_PROFIT"][0]
    assert ex.price == 107.0 and ex.shares == 12

def test_stop_never_moves_down():
    p = pos(state=TRAILING_ATR, live_stop=104.0, highest_high=112.0)
    r = advance_one_bar(p, Bar(108, 109, 107, 108), BarCtx(atr14=6.0, kill_switch=False, is_bull=True), R)
    assert r.pos.live_stop >= 104.0

def test_ratchet_off_in_bull_on_otherwise():
    p = pos(highest_high=110.0)
    on = advance_one_bar(p, Bar(109, 110, 108, 109), BarCtx(2.0, False, False), R).pos.live_stop
    off = advance_one_bar(p, Bar(109, 110, 108, 109), BarCtx(2.0, False, True), R).pos.live_stop
    assert on > off

def test_entry_skipped_when_open_gaps_through_stop_or_too_high():
    kw = dict(ticket_entry=100, stop=95, target=112, equity=1_000_000, risk_pct=1.0,
              slippage_pct=0.1, max_gap_up_pct=3.0, min_rr=1.5)
    assert plan_entry_fill(next_open=94, **kw).reason == "GAP_THROUGH_STOP"
    assert plan_entry_fill(next_open=104, **kw).reason == "GAP_UP_TOO_LARGE"
    assert plan_entry_fill(next_open=100, **kw).ok
```
**Acceptance:** all pass. Wiring into live happens in Step 2.5 and into the backtest in Step 3.4.

### Step 1.4 — Remove window-name logic; state-driven rules only (P0, S)
**Problem:** the backtest switches features on by window label (`regime_name == "bull_run"`, `enabled_regimes`); live uses market state. They cannot match.

**New file `engine_core/regime_gates.py`:**
```python
from typing import Optional

def is_bull(kill_switch_active: bool, nifty_close: Optional[float], nifty_sma200: Optional[float]) -> bool:
    return bool((not kill_switch_active) and nifty_close is not None and nifty_sma200 is not None
                and nifty_close > nifty_sma200)

def bull_correction_active(nifty_close, nifty_sma200, nifty_sma_entry) -> bool:
    """Above the 200-day (bull) but below the entry SMA (e.g. 50-day): pause NEW entries."""
    if nifty_close is None or nifty_sma200 is None or nifty_sma_entry is None:
        return False
    return bool(nifty_close > nifty_sma200 and nifty_close < nifty_sma_entry)
```
**Edits**
1. `live_runner/pipeline.py` `run()` lines ~109-116: replace the `is_bull_correction` block with
```python
            from engine_core.regime_gates import bull_correction_active
            sma_n = int(self.config.get("macro", {}).get("bull_entry_sma_period", 0))
            is_bull_correction = bool(sma_n > 0 and not regime_state.kill_switch_active and bull_correction_active(
                regime_state.nifty_close, regime_state.nifty_sma200, self._fetch_nifty_sma(eval_date, sma_n)))
```
2. `strategy_config.yaml`: in `profit_ratchet` delete `enabled_regimes`, add `active_in_bull: false` (done in Step 0.2).
3. Pass 1 / Pass 2 window-name code disappears with Step 3.4.

**Acceptance:** `grep -rnE "bull_run|sideways_inflation|enabled_regimes" --include=*.py .` returns nothing outside `tests/`.

### Step 1.5 — Entry quality, ranking, sector map, R:R cap, heat floor (P0, M)
**Why:** there is no breakout trigger; R:R is measured against the 52-week high, so stocks far below their highs score best (falling knives); candidates are filled in database order; sector is always `None`.

**New `engine_core/entry_filters.py`:**
```python
from __future__ import annotations
import pandas as pd


def passes_trend_filter(close: pd.Series, fast: int, slow: int) -> bool:
    if len(close) < slow:
        return False
    f, s, c = close.rolling(fast).mean().iloc[-1], close.rolling(slow).mean().iloc[-1], close.iloc[-1]
    return bool(c > f and f > s)


def passes_breakout(close: pd.Series, high: pd.Series, lookback: int) -> bool:
    if len(high) < lookback + 1:
        return False
    return bool(close.iloc[-1] >= high.iloc[-(lookback + 1):-1].max())


def rs_return(close: pd.Series, lookback: int) -> float:
    return float(close.iloc[-1] / close.iloc[-(lookback + 1)] - 1.0) if len(close) > lookback else float("nan")


def apply_entry_filters(cands: list, cfg: dict) -> list:
    """Filter + deterministic rank (RS desc, symbol asc). Same function in live and backtest."""
    ef = cfg.get("entry_filters", {})
    kept = []
    for c in cands:
        adj = c["adjusted_ohlcv"]
        close, high = adj["close_adj"], adj["high_adj"]
        if ef.get("trend_filter_enabled") and not passes_trend_filter(
                close, int(ef.get("trend_fast_sma", 50)), int(ef.get("trend_slow_sma", 200))):
            continue
        if ef.get("breakout_required") and not passes_breakout(close, high, int(ef.get("breakout_lookback", 20))):
            continue
        d = dict(c)
        d["rs_3m"] = rs_return(close, int(ef.get("rs_lookback_days", 63)))
        kept.append(d)
    kept.sort(key=lambda c: (-c["rs_3m"] if pd.notna(c["rs_3m"]) else 1e9, c["symbol"]))
    return kept
```
Note: `lookback` for the 200-day SMA needs ≥200 bars; the builder fetches 252+30, so this holds.

**Wire:** in `live_runner/pipeline.py::_run_screening`, after `candidate_dicts = self._build_candidate_dicts(...)` add
```python
        from engine_core.entry_filters import apply_entry_filters
        candidate_dicts = apply_entry_filters(candidate_dicts, self.config)
```
**Sector map:** create `data/reference/sector_map.csv` (`symbol,sector`, committed) and `engine_core/sector_map.py`:
```python
import csv
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "data" / "reference" / "sector_map.csv"

@lru_cache(maxsize=1)
def _load() -> dict:
    if not _PATH.exists():
        raise FileNotFoundError(f"{_PATH} missing — the sector cap cannot run without it")
    with open(_PATH, newline="", encoding="utf-8") as f:
        return {r["symbol"].strip().upper(): r["sector"].strip() for r in csv.DictReader(f)}

def sector_for(symbol: str) -> str:
    return _load().get(symbol.upper(), "UNKNOWN")      # UNKNOWN is its own capped bucket
```
**R:R cap:** `engine_core/risk_sizing.py`. In `__init__` after `self._min_rr = ...` add `self._max_rr_cap: float = float(risk.get("max_rr_cap", 0) or 0)`. In `compute_setup` immediately after `if projected_rr < self._min_rr: return TradeSetup(...)` (line ~309-326) add a second block with the same constructor arguments:
```python
        if self._max_rr_cap and projected_rr > self._max_rr_cap:
            return TradeSetup(symbol=symbol, eval_date=eval_date, entry_price=entry_price,
                live_stop_loss=live_stop_loss, stop_a=stop_a, stop_b=stop_b,
                initial_resistance_target=resistance_target, shares=0, position_value=0.0,
                risk_amount=0.0, risk_pct_of_equity=0.0, projected_rr=projected_rr, blocked=True,
                block_reason=f"RR_ABOVE_CAP({projected_rr:.2f}>{self._max_rr_cap})", sector=sector)
```
**Heat floor:** `pipeline._get_open_positions_for_heat_cap`: replace the two lines with
```python
                "risk_amount": max(0.0, (p.shares_remaining or p.shares) * (p.entry_price - p.live_stop_loss)),
                "position_value": (p.shares_remaining or p.shares) * p.entry_price,
```
(do the same in the simulator, Step 3.4). **Acceptance tests:** (a) a candidate with `close < SMA50` is dropped; (b) two candidates ranked by RS then symbol, identical across runs; (c) R:R 8.0 is blocked with `RR_ABOVE_CAP`; (d) sector cap: with 15% cap, sizing a second position in a sector already at 14% is `BLOCKED_BY_RISK`; (e) ≥95% of symbols passing liquidity have a non-`UNKNOWN` sector.

### Step 1.6 — Let the screener skip event gates on request (P0, S)
The backtest's "naive pass" never disabled ASM/earnings (skip strings never match the real reasons, which contain numbers). Replace string matching with an explicit switch.

`engine_core/universe_screener.py`: change the signature to
```python
    def screen_single(self, symbol: str, eval_date: date, apply_event_gates: bool = True) -> ScreeningResult:
```
and wrap the two gate blocks (the one returning `UNDER_ASM_GSM_SURVEILLANCE`, and the one returning `BINARY_EVENT_TOO_CLOSE(...)`) in `if apply_event_gates:`. Leave all other gates untouched. If the relative-strength gate is ever re-enabled, compute it on **adjusted** closes (currently raw, which distorts around splits) and set `_rs_threshold_return` inside `screen_single` callers too. **Acceptance:** unit test that `screen_single(sym, d, apply_event_gates=False)` passes a symbol that is currently in `asm_gsm_list`, while the default call rejects it.


---

## Phase 2 — Paper mode and live wiring (P0)

Design: one global switch `runtime.mode` (`PAPER` | `LIVE`). **One** `open_position()` function serves both modes: in PAPER the fill is simulated at the next open; in LIVE the user types the real broker fill. PAPER auto-opens and auto-closes. LIVE never auto-deletes anything: it raises alerts and the user records fills.

### Step 2.1 — Schema, models, mode helper (P0, S)
**`data/db/models.py`** — add columns (all other columns unchanged):
```python
# class ActivePosition
mode: Mapped[str] = mapped_column(String(5), nullable=False, default="LIVE", server_default="LIVE")
pending_close_reason: Mapped[Optional[str]] = mapped_column(String(30))
fill_source: Mapped[Optional[str]] = mapped_column(String(14))        # SIMULATED | BROKER_ENTERED
entry_costs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")

# class TradeAnalyticsLog
mode: Mapped[str] = mapped_column(String(5), nullable=False, default="LIVE", server_default="LIVE")
costs_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
pnl_net: Mapped[Optional[float]] = mapped_column(Float)
tax_est: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

# class DailyWatchlist
execution_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
execution_note: Mapped[Optional[str]] = mapped_column(String(80))
position_id: Mapped[Optional[int]] = mapped_column(Integer)
```
**New `data/db/migration_phase3_paper.py`** (idempotent; mirror the session/commit pattern used in `data/db/migration_phase2.py` — VERIFY whether `get_session()` commits on exit):
```python
"""Add paper-mode columns. Run once: python -m data.db.migration_phase3_paper"""
from sqlalchemy import text
from data.db.connection import get_session

ADDS = [
    ("active_positions", "mode", "VARCHAR(5) NOT NULL DEFAULT 'LIVE'"),
    ("active_positions", "pending_close_reason", "VARCHAR(30)"),
    ("active_positions", "fill_source", "VARCHAR(14)"),
    ("active_positions", "entry_costs", "FLOAT NOT NULL DEFAULT 0"),
    ("trade_analytics_log", "mode", "VARCHAR(5) NOT NULL DEFAULT 'LIVE'"),
    ("trade_analytics_log", "costs_total", "FLOAT NOT NULL DEFAULT 0"),
    ("trade_analytics_log", "pnl_net", "FLOAT"),
    ("trade_analytics_log", "tax_est", "FLOAT NOT NULL DEFAULT 0"),
    ("trade_analytics_log", "is_partial", "BOOLEAN NOT NULL DEFAULT 0"),
    ("daily_watchlist", "execution_status", "VARCHAR(20) NOT NULL DEFAULT 'PENDING'"),
    ("daily_watchlist", "execution_note", "VARCHAR(80)"),
    ("daily_watchlist", "position_id", "INTEGER"),
]

def main() -> None:
    with get_session() as s:
        for table, col, ddl in ADDS:
            have = {r[1] for r in s.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if col not in have:
                s.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                print(f"added {table}.{col}")
        s.execute(text("UPDATE trade_analytics_log SET pnl_net = pnl_gross WHERE pnl_net IS NULL"))
        s.execute(text("UPDATE daily_watchlist SET execution_status='EXPIRED' WHERE execution_status='PENDING'"))
        s.commit()

if __name__ == "__main__":
    main()
```
**New `engine_core/mode.py`:**
```python
def current_mode(config: dict) -> str:
    m = str(config.get("runtime", {}).get("mode", "")).upper()
    if m not in ("PAPER", "LIVE"):
        raise ValueError("strategy_config.yaml: runtime.mode must be PAPER or LIVE")
    return m
```
**Acceptance:** migration runs twice without error; app boots; a missing `runtime.mode` stops startup with the message above.

### Step 2.2 — Costs and tax model (P0, S)
**New `engine_core/costs.py`** (rates come from `costs:` in config; verify them):
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class CostModel:
    stt_buy_pct: float; stt_sell_pct: float; brokerage_per_order: float
    exch_pct: float; sebi_pct: float; stamp_buy_pct: float; gst_pct: float
    dp_sell_inr: float; stcg_pct: float

    @staticmethod
    def from_config(cfg: dict) -> "CostModel":
        c = cfg["costs"]
        return CostModel(float(c["stt_buy_pct"]), float(c["stt_sell_pct"]), float(c["brokerage_per_order_inr"]),
                         float(c["exchange_txn_pct"]), float(c["sebi_fee_pct"]), float(c["stamp_duty_buy_pct"]),
                         float(c["gst_pct"]), float(c["dp_charge_per_sell_inr"]), float(c["stcg_tax_pct"]))

    def _fees(self, value: float) -> float:
        return value * (self.exch_pct + self.sebi_pct) / 100.0

    def buy_cost(self, value: float) -> float:
        base = self.brokerage_per_order + self._fees(value)
        return value * (self.stt_buy_pct + self.stamp_buy_pct) / 100.0 + base * (1 + self.gst_pct / 100.0)

    def sell_cost(self, value: float) -> float:
        base = self.brokerage_per_order + self._fees(value)
        return value * self.stt_sell_pct / 100.0 + self.dp_sell_inr + base * (1 + self.gst_pct / 100.0)

    def tax_on_gain(self, net_gain: float) -> float:
        """Per-position approximation: no loss set-off across positions. Refine with annual netting later."""
        return max(0.0, net_gain) * self.stcg_pct / 100.0
```
**Acceptance test:** buy and sell ₹1,00,000 at your broker's schedule; result within ₹5 of the broker's contract-note calculator.

### Step 2.3 — Paper equity and cash (P0, S)
**New `engine_core/equity.py`:**
```python
from sqlalchemy import text

def paper_equity(session, config: dict) -> float:
    start = float(config["runtime"]["paper_start_equity"])
    realized = session.execute(text(
        "SELECT COALESCE(SUM(pnl_net - tax_est), 0) FROM trade_analytics_log WHERE mode='PAPER'")).scalar()
    return start + float(realized or 0.0)

def paper_cash(session, config: dict) -> float:
    invested = session.execute(text(
        "SELECT COALESCE(SUM(COALESCE(shares_remaining, shares) * entry_price), 0) "
        "FROM active_positions WHERE mode='PAPER'")).scalar()
    return paper_equity(session, config) - float(invested or 0.0)

def get_equity(session, config: dict, mode: str, live_fallback: float) -> float:
    if mode == "PAPER":
        return paper_equity(session, config)
    from engine_core.account_ledger import get_live_equity
    return get_live_equity(session, live_fallback)
```
**Edit** `engine_core/account_ledger.py::get_live_equity`: its realized-P&L query over `trade_analytics_log` must add `AND mode='LIVE'` (VERIFY by reading the function) so paper trades never leak into real equity. **Acceptance:** insert a PAPER log row; live equity is unchanged.

### Step 2.4 — One `open_position()` for both modes (P0, S)
**New `engine_core/position_service.py`:**
```python
from __future__ import annotations
from datetime import date
from data.db.models import ActivePosition, DailyWatchlist
from engine_core.costs import CostModel

def open_position(session, *, mode: str, ticket: DailyWatchlist, fill_date: date, fill_price: float,
                  shares: int, equity: float, rr_at_fill: float, fill_source: str, costs: CostModel) -> ActivePosition:
    pos = ActivePosition(
        symbol=ticket.symbol, entry_date=fill_date, entry_price=fill_price,
        shares=shares, original_shares=shares, shares_remaining=shares,
        initial_stop_loss=ticket.live_stop_loss, live_stop_loss=ticket.live_stop_loss,
        initial_resistance_target=ticket.initial_resistance_target, projected_rr=rr_at_fill,
        position_state="INITIAL_RISK", days_held=0, highest_high_since_breakout=fill_price,
        sector=ticket.sector, account_equity_at_entry=equity,
        stop_a_at_entry=ticket.stop_a, stop_b_at_entry=ticket.stop_b,
        mode=mode, fill_source=fill_source, entry_costs=costs.buy_cost(fill_price * shares),
    )
    session.add(pos)
    session.flush()
    ticket.execution_status = "OPENED"
    ticket.position_id = pos.id
    return pos
```
### Step 2.5 — Rewire `PositionLifecycleManager` onto the shared rules (P0, L)
File `engine_core/position_lifecycle.py`.

1. **Imports:** add `from sqlalchemy import func`, `from engine_core.lifecycle_rules import (Bar, BarCtx, LifecycleRules, PosState, advance_one_bar, parabolic_ref_close)`, `from engine_core.costs import CostModel`, `from data.db.models import TradeAnalyticsLog`, `from engine_core.mode import current_mode`.
2. **`__init__`:** add
```python
        self._rules = LifecycleRules.from_config(config)
        self._costs = CostModel.from_config(config)
        self._exit_slip = float(config.get("execution", {}).get("exit_slippage_pct", 0.0))
        self._mode = current_mode(config)
```
3. **`process_all`:** change the query to `select(ActivePosition).where(ActivePosition.mode == self._mode).order_by(ActivePosition.entry_date)`.
4. **Delete** `_evaluate_state_machine`, `_evaluate_partial_profits`, `_check_parabolic_acceleration` (logic now lives in `lifecycle_rules.py`). Keep `_is_kill_switch_active`, `_is_bull_regime`, `_check_earnings_alert`, `_fetch_raw_ohlcv`, `_fetch_corporate_actions`, `close_position`.
5. **Replace `process_single` body** (keep the signature). Keep the existing lines that fetch raw data, build `adj` via `get_adjusted_series(...)`, and compute `atr_14`; keep the existing `PositionUpdate(...)` construction (move it into a small `_build_update` helper that receives the final values). New core:
```python
        pos = self._session.get(ActivePosition, position_id)
        if pos is None:
            raise ValueError(f"Position {position_id} not found")
        # --- KEEP existing code: raw fetch, `adj` (get_adjusted_series), `atr_14` ---
        if pos.mode == "LIVE" and pos.pending_close_reason:
            return self._build_update(pos, pos.position_state, flags=[f"ACTION_REQUIRED_{pos.pending_close_reason}"])

        bar = Bar(float(adj.loc[eval_date, "open_adj"]), float(adj.loc[eval_date, "high_adj"]),
                  float(adj.loc[eval_date, "low_adj"]), float(adj.loc[eval_date, "close_adj"]))
        ks = kill_switch_active if kill_switch_active is not None else self._is_kill_switch_active(eval_date)
        ctx = BarCtx(atr14=float(atr_14), kill_switch=bool(ks), is_bull=self._is_bull_regime(eval_date),
                     close_n_ago=parabolic_ref_close(list(adj["close_adj"]), self._rules.parabolic_lookback))
        state = PosState(
            entry_price=pos.entry_price, initial_stop=pos.initial_stop_loss, live_stop=pos.live_stop_loss,
            target=pos.initial_resistance_target, state=pos.position_state, days_held=pos.days_held,
            highest_high=pos.highest_high_since_breakout,
            shares_remaining=pos.shares_remaining if pos.shares_remaining is not None else pos.shares,
            last_partial_rr=pos.last_partial_exit_rr or 0.0, partial_count=pos.partial_exit_count or 0)
        res = advance_one_bar(state, bar, ctx, self._rules, exit_slippage_pct=self._exit_slip)
        new, flags = res.pos, list(res.flags)
        earnings_alert, next_earnings = self._check_earnings_alert(pos.symbol, eval_date)   # keep existing unpacking
        old_state = pos.position_state

        pos.position_state, pos.live_stop_loss = new.state, new.live_stop
        pos.days_held, pos.highest_high_since_breakout = new.days_held, new.highest_high
        pos.last_partial_exit_rr, pos.partial_exit_count = (new.last_partial_rr or None), new.partial_count
        pos.earnings_alert, pos.next_earnings_date, pos.last_evaluated_date = earnings_alert, next_earnings, eval_date

        if pos.mode == "PAPER":
            for i, ex in enumerate(res.exits):
                self._log_exit(pos, ex, eval_date, new.days_held, final=(res.closed and i == len(res.exits) - 1))
                if ex.reason == "PARTIAL_PROFIT":
                    pos.shares_remaining = new.shares_remaining
                    pos.total_realized_pnl_partial = (pos.total_realized_pnl_partial or 0.0) + (ex.price - pos.entry_price) * ex.shares
            update = self._build_update(pos, old_state, flags=flags + (["POSITION_CLOSED"] if res.closed else []))
            if res.closed:
                self._session.delete(pos)
            self._session.flush()
            return update
        # LIVE: advisory only. Never auto-delete, never change share counts.
        for ex in res.exits:
            if ex.reason == "PARTIAL_PROFIT":
                flags.append(f"BOOK_PARTIAL_{ex.shares}_SHARES_NEAR_{ex.price:.2f}")
        if res.closed:
            pos.pending_close_reason = res.exits[-1].reason
            flags.append(f"ACTION_REQUIRED_{res.exits[-1].reason}")
        self._session.flush()
        return self._build_update(pos, old_state, flags=flags)
```
6. **Add `_log_exit`:**
```python
    def _log_exit(self, pos, ex, eval_date, days_held, final: bool) -> None:
        one_r = pos.entry_price - pos.initial_stop_loss
        gross = (ex.price - pos.entry_price) * ex.shares
        orig = pos.original_shares or pos.shares
        costs = self._costs.sell_cost(ex.price * ex.shares) + (pos.entry_costs or 0.0) * (ex.shares / orig)
        net, tax = gross - costs, 0.0
        if final:
            prior = self._session.execute(select(func.coalesce(func.sum(TradeAnalyticsLog.pnl_net), 0.0))
                                          .where(TradeAnalyticsLog.position_id == pos.id)).scalar() or 0.0
            tax = self._costs.tax_on_gain(prior + net)
        self._session.add(TradeAnalyticsLog(
            position_id=pos.id, symbol=pos.symbol, entry_date=pos.entry_date, exit_date=eval_date,
            entry_price=pos.entry_price, exit_price=ex.price, shares=ex.shares,
            initial_stop_loss=pos.initial_stop_loss, projected_rr=pos.projected_rr,
            realized_rr=(ex.price - pos.entry_price) / one_r if one_r > 0 else 0.0,
            pnl_gross=gross, exit_reason=ex.reason, sector=pos.sector, days_held=days_held,
            mode=pos.mode, costs_total=costs, pnl_net=net, tax_est=tax, is_partial=(ex.reason == "PARTIAL_PROFIT")))
```
7. **Also fix** `engine_core/analytics_loop.py::record_closed_trade` (manual close in LIVE): use `shares_remaining` (not `shares`), set `mode=pos.mode`, compute `pnl_net` with the same cost model, count `days_held` in trading sessions (it currently uses calendar days).

**Acceptance:** golden-master test `tests/integration/test_live_vs_rules.py`: feed the same 40 synthetic bars to `advance_one_bar` directly and to `process_single` (PAPER); assert identical `live_stop`, `state`, exit prices. Existing `tests/unit/test_position_lifecycle.py` must be updated for gap-aware fills and next-open decay.

### Step 2.6 — Paper trader (auto-open at next open) (P0, M)
**New `live_runner/paper_trader.py`:**
```python
from __future__ import annotations
from datetime import date
from typing import Optional

from sqlalchemy import func, select

from data.db.models import CorporateActionsLog, DailyWatchlist, MarketDataLake
from engine_core.costs import CostModel
from engine_core.equity import paper_cash, paper_equity
from engine_core.lifecycle_rules import plan_entry_fill
from engine_core.mode import current_mode
from engine_core.position_service import open_position


def previous_trading_date(session, eval_date: date) -> Optional[date]:
    return session.execute(select(func.max(MarketDataLake.trade_date))
                           .where(MarketDataLake.trade_date < eval_date)).scalar()


def expire_stale_tickets(session, eval_date: date) -> int:
    prev = previous_trading_date(session, eval_date)
    q = select(DailyWatchlist).where(DailyWatchlist.execution_status == "PENDING",
                                     DailyWatchlist.run_date < (prev or eval_date))
    rows = session.execute(q).scalars().all()
    for t in rows:
        t.execution_status, t.execution_note = "EXPIRED", "NOT_EXECUTED_NEXT_SESSION"
    return len(rows)


def open_pending_tickets(session, config: dict, eval_date: date) -> list[dict]:
    """PAPER only. Fill yesterday's approved tickets at today's open (plus slippage)."""
    assert current_mode(config) == "PAPER", "paper_trader must not run in LIVE mode"
    prev = previous_trading_date(session, eval_date)
    if prev is None:
        return []
    ex, costs = config["execution"], CostModel.from_config(config)
    tickets = session.execute(select(DailyWatchlist).where(
        DailyWatchlist.run_date == prev, DailyWatchlist.blocked.is_(False),
        DailyWatchlist.execution_status == "PENDING").order_by(DailyWatchlist.id)).scalars().all()   # rank order
    results, equity, cash = [], paper_equity(session, config), paper_cash(session, config)
    for t in tickets:
        bar = session.execute(select(MarketDataLake.open_raw).where(
            MarketDataLake.symbol == t.symbol, MarketDataLake.trade_date == eval_date)).scalar()
        if bar is None:
            t.execution_status, t.execution_note = "SKIPPED", "NO_BAR_ON_EXEC_DATE"
            continue
        ca = session.execute(select(CorporateActionsLog.id).where(
            CorporateActionsLog.symbol == t.symbol, CorporateActionsLog.ex_date == eval_date)).first()
        if ca:
            t.execution_status, t.execution_note = "SKIPPED", "CORP_ACTION_ON_EXEC_DATE"
            continue
        plan = plan_entry_fill(
            ticket_entry=t.entry_price, stop=t.live_stop_loss, target=t.initial_resistance_target,
            next_open=float(bar), equity=equity, risk_pct=float(config["risk"]["max_loss_pct_per_trade"]),
            slippage_pct=float(ex["entry_slippage_pct"]), max_gap_up_pct=float(ex["max_entry_gap_up_pct"]),
            min_rr=float(ex["min_rr_at_fill"]), cash=cash)
        if not plan.ok:
            t.execution_status, t.execution_note = "SKIPPED", plan.reason[:80]
            results.append({"symbol": t.symbol, "status": "SKIPPED", "reason": plan.reason})
            continue
        open_position(session, mode="PAPER", ticket=t, fill_date=eval_date, fill_price=plan.fill_price,
                      shares=plan.shares, equity=equity, rr_at_fill=plan.rr_at_fill,
                      fill_source="SIMULATED", costs=costs)
        cash -= plan.fill_price * plan.shares
        results.append({"symbol": t.symbol, "status": "OPENED", "price": plan.fill_price, "shares": plan.shares})
    return results
```
**Acceptance (pytest):** (a) re-running the same date does not open twice (status flips; unique `(symbol, entry_date)`); (b) a ticket with a +5% gap-up is `SKIPPED` with `GAP_UP_TOO_LARGE`; (c) a ticket on a symbol with an ex-date today is `SKIPPED`; (d) positions opened are in `mode='PAPER'`; (e) `open_pending_tickets` raises when `runtime.mode: LIVE`.

### Step 2.7 — Wire the live pipeline (P0, M)
`live_runner/pipeline.py`:
1. In `run()`, **after** the regime evaluation and **before** `PositionLifecycleManager.process_all(...)`:
```python
        from engine_core.mode import current_mode
        mode = current_mode(self.config)
        if mode == "PAPER":
            from live_runner.paper_trader import expire_stale_tickets, open_pending_tickets
            expire_stale_tickets(self.session, eval_date)
            results["paper_fills"] = open_pending_tickets(self.session, self.config, eval_date)
```
(order: open yesterday's tickets at today's open → advance all positions for today's bar → generate new tickets.)
2. `_get_open_positions_for_heat_cap`: add `.where(ActivePosition.mode == mode)` (pass `mode` in) — plus the risk floor from Step 1.5.
3. `_run_screening`: replace the equity lookup with `get_equity(self.session, self.config, mode, fallback)` from `engine_core.equity`.
4. `_persist_watchlist`: replace "delete all rows for run_date" with delete only `execution_status == 'PENDING'` rows for that run_date, and insert rows in rank order (insertion order = `id` order is how the paper trader fills).
5. `routers/portfolio.py` raw SQL on `active_positions`: add `WHERE mode = :mode` (mode from config). `routers/watchlist.py`: change `ORDER BY projected_rr DESC` to `ORDER BY id ASC` and return `execution_status`, `execution_note`.

### Step 2.8 — API and UI (P0 for PAPER view, P1 for LIVE open) (M)
**`live_runner/routers/positions.py`** — add (mirror the session pattern in `close_position`; load config with the same loader the pipeline uses — VERIFY import):
```python
class OpenPositionRequest(BaseModel):
    watchlist_id: int
    fill_price: float = Field(gt=0)
    shares: int = Field(gt=0)
    fill_date: date

@router.post("/open")
def open_position_endpoint(req: OpenPositionRequest):
    """LIVE only. Records a trade you ALREADY executed in your broker terminal. Sends nothing to any broker."""
    from config import load_config
    from engine_core.costs import CostModel
    from engine_core.mode import current_mode
    from engine_core.position_service import open_position
    from data.db.models import DailyWatchlist
    cfg = load_config()
    if current_mode(cfg) != "LIVE":
        raise HTTPException(400, "Manual open is LIVE-only. PAPER positions open automatically.")
    with get_session() as session:
        t = session.get(DailyWatchlist, req.watchlist_id)
        if t is None or t.blocked or t.execution_status != "PENDING":
            raise HTTPException(409, "Ticket not found, blocked, or already actioned")
        equity = t.risk_amount / (t.risk_pct_of_equity / 100.0) if t.risk_pct_of_equity > 0 else 0.0
        risk_ps = req.fill_price - t.live_stop_loss
        rr = (t.initial_resistance_target - req.fill_price) / risk_ps if risk_ps > 0 else 0.0
        pos = open_position(session, mode="LIVE", ticket=t, fill_date=req.fill_date, fill_price=req.fill_price,
                            shares=req.shares, equity=equity, rr_at_fill=rr, fill_source="BROKER_ENTERED",
                            costs=CostModel.from_config(cfg))
        return {"success": True, "position_id": pos.id}
```
In `close_position` (same file) add at the top: if mode is PAPER → `HTTPException(400, "PAPER positions close automatically")`.

**UI (`ui/src`) tasks:** (1) header banner showing `PAPER` or `LIVE` from a new `GET /health` field `mode`; (2) on each ticket in LIVE mode an "I bought this" form (fill price, shares, date) calling `POST /positions/open`; hide it in PAPER; (3) show `execution_status`/`execution_note` on tickets (OPENED / SKIPPED(reason) / EXPIRED); (4) show `ACTION_REQUIRED_*` and `BOOK_PARTIAL_*` flags prominently; (5) types in `ui/src/types` for the new fields. No UI element may call a broker.

### Step 2.9 — One metrics function for backtest, paper and live (P0, M)
Problem fixed: the old win rate counted partial exits as wins, "Sharpe" divided by the std of drawdown, and the decay report compared against a partly synthetic projected R:R.

**New `engine_core/trade_metrics.py`:**
```python
from __future__ import annotations
import numpy as np
import pandas as pd
from sqlalchemy import text

def trades_from_log(session, mode: str) -> pd.DataFrame:
    """One row per POSITION (partials merged)."""
    return pd.read_sql(text("""
        SELECT position_id, symbol, MIN(entry_date) AS entry_date, MAX(exit_date) AS exit_date,
               MIN(entry_price) AS entry_price, MIN(initial_stop_loss) AS stop, SUM(shares) AS shares,
               SUM(pnl_gross) AS pnl_gross, SUM(costs_total) AS costs, SUM(pnl_net) AS pnl_net,
               SUM(tax_est) AS tax_est, MAX(days_held) AS days_held
        FROM trade_analytics_log WHERE mode = :m GROUP BY position_id, symbol"""),
        session.bind, params={"m": mode}, parse_dates=["entry_date", "exit_date"])

def sharpe_from_equity(equity: pd.Series, rf_annual: float = 0.065) -> float:
    r = equity.pct_change().dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float((r.mean() - rf_annual / 252.0) / r.std() * np.sqrt(252))

def metrics_from_trades(df: pd.DataFrame, start_equity: float) -> dict:
    """Columns required: entry_price, stop, shares, pnl_net, tax_est, exit_date."""
    if df.empty:
        return {"n_trades": 0}
    t = df.sort_values("exit_date").copy()
    t["net_after_tax"] = t["pnl_net"] - t["tax_est"]
    t["r_net"] = t["pnl_net"] / ((t["entry_price"] - t["stop"]) * t["shares"])
    wins, losses = t[t["net_after_tax"] > 0], t[t["net_after_tax"] <= 0]
    eq = start_equity + t["net_after_tax"].cumsum()
    dd = ((eq.cummax() - eq) / eq.cummax()).max() * 100.0
    gl = abs(losses["net_after_tax"].sum())
    return {"n_trades": int(len(t)), "win_rate_pct": float(len(wins) / len(t) * 100.0),
            "expectancy_r": float(t["r_net"].mean()),
            "profit_factor": float(wins["net_after_tax"].sum() / gl) if gl > 0 else float("inf"),
            "avg_win_r": float(wins["r_net"].mean()) if len(wins) else 0.0,
            "avg_loss_r": float(losses["r_net"].mean()) if len(losses) else 0.0,
            "max_drawdown_pct_trade_level": float(dd), "net_pnl_after_tax": float(t["net_after_tax"].sum())}
```
**Edits:** `engine_core/analytics_loop.py::get_decay_report` and `generate_confidence_report.py` must call `metrics_from_trades` for paper/live **and** read the same keys from `backtest/outputs/audit.json["metrics"]` (written by the simulator in Step 3.5). Compare like with like; drop the comparison to `projected_rr`.

### Step 2.10 — Append-only enforcement (P2, S)
`schema.sql` has no triggers although the BRD requires them, and `fix_blocker*.py` run `DELETE`. First grep ingestion code for upserts/`REPLACE`/`DELETE`; convert them to insert-if-missing; remove or archive `fix_blocker*.py`. Then add:
```sql
CREATE TRIGGER IF NOT EXISTS trg_tal_no_update BEFORE UPDATE ON trade_analytics_log
BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_tal_no_delete BEFORE DELETE ON trade_analytics_log
BEGIN SELECT RAISE(ABORT, 'trade_analytics_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_mdl_no_delete BEFORE DELETE ON market_data_lake
BEGIN SELECT RAISE(ABORT, 'market_data_lake is append-only'); END;
```
(Do `market_data_lake`/`shares_outstanding`/`corporate_actions_log` UPDATE triggers only after ingestion no longer updates rows.) **Acceptance:** attempting `UPDATE`/`DELETE` raises.


---

## Phase 3 — Rebuild the backtest on the shared engine and re-run it honestly (P0)

Goal: the validation that authorizes live trading must run the **same code** as live and paper (Step 1.3 rules, Step 1.5 filters, Step 1.2 builder), with next-open fills, real costs and tax, fail-closed compliance data, and an out-of-sample window. Pass 1 (naive) and Pass 2 (compliant) become **two runs of one simulator**; Pass 2 simply adds exclusions, so slots are re-allocated naturally (the old Pass 2 only deleted trades after the fact).

### Step 3.1 — Config for gates and windows (P0, S)
Add to `strategy_config.yaml` (replace the old `backtest.allowed_underperform_pct` logic):
```yaml
gates:
  max_drawdown_pct: 15.0
  min_alpha_after_tax_pct: 2.0      # strategy after-tax CAGR minus Nifty after-tax CAGR; NO tolerance
  min_expectancy_r: 0.15
  min_profit_factor: 1.3
  min_trades: 40
  ltcg_tax_pct: 12.5                # Nifty buy-and-hold taxed once at the end; verify rate
  risk_free_pct: 6.5
earnings:
  known_ahead_days: 7               # backtest may only "know" an earnings date this many days ahead (what live can know)
backtest:
  regimes:                          # keep existing two windows; ADD an untouched test window if data allows
    - {name: "window_2020_2021", role: TUNE, start: "2020-01-01", end: "2021-12-31"}
    - {name: "window_2022_2026", role: TUNE, start: "2022-01-01", end: "2026-09-30"}
    - {name: "window_2015_2019", role: TEST, start: "2015-01-01", end: "2019-12-31"}   # or 2010-2013 per BRD
```
Rename the old window labels; they are labels only now — **no code may branch on them** (Step 1.4). `known_ahead_days` must be calibrated: after 4+ weeks of live collection, measure the median gap between `earnings_calendar.fetched_at` and `event_date` and set the value accordingly. (Exchanges only require short notice for board meetings, so a 14-day look-ahead block in live catches far fewer events than a backtest that "knows" every realized date.)

### Step 3.2 — Shared Nifty SMA helper (P0, S)
Move `_fetch_nifty_sma` out of `pipeline.py` into `engine_core/regime_gates.py`:
```python
from sqlalchemy import select, desc
from data.db.models import MarketDataLake

def nifty_sma(session, config: dict, eval_date, period: int):
    sym = config.get("data", {}).get("nifty_symbol", "NIFTY50_INDEX")
    rows = session.execute(select(MarketDataLake.close_raw).where(MarketDataLake.symbol == sym)
                           .where(MarketDataLake.trade_date <= eval_date)
                           .order_by(desc(MarketDataLake.trade_date)).limit(period)).scalars().all()
    return float(sum(rows) / period) if len(rows) >= period else None
```
Make `pipeline._fetch_nifty_sma` call it.

### Step 3.3 — Fail-closed exclusions `backtest/exclusions.py` (P0, S)
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

@dataclass
class Exclusions:
    asm: dict            # symbol -> [(start, end)]
    earnings: dict       # symbol -> sorted [event_date]
    block_days: int
    known_ahead_days: int
    applied: bool = True

    def asm_blocked(self, sym: str, d: date) -> bool:
        return any(s <= d <= e for s, e in self.asm.get(sym, []))

    def earnings_within(self, sym: str, d: date) -> bool:
        lim = min(self.block_days, self.known_ahead_days)       # cannot block on dates live could not know
        return any(d <= ev <= d + timedelta(days=lim) for ev in self.earnings.get(sym, []))

    @classmethod
    def load(cls, out_dir: Path, regime: str, block_days: int, known_ahead_days: int,
             allow_unverified: bool = False) -> "Exclusions":
        asm_p, earn_p = out_dir / f"pending_asm_gsm_matches_{regime}.csv", out_dir / f"historical_earnings_{regime}.csv"
        problems = []
        if not asm_p.exists(): problems.append(f"missing {asm_p.name}")
        if not earn_p.exists(): problems.append(f"missing {earn_p.name}")
        asm, earn = {}, {}
        if asm_p.exists():
            df = pd.read_csv(asm_p)
            unverified = df[df["status"] != "VERIFIED"]
            if len(unverified):
                problems.append(f"{len(unverified)} ASM/GSM rows not VERIFIED in {asm_p.name}")
            for r in df[df["status"] == "VERIFIED"].itertuples():
                s = pd.to_datetime(r.start_date).date()
                e = pd.to_datetime(r.end_date).date() if pd.notna(r.end_date) else date(2099, 12, 31)
                asm.setdefault(r.symbol, []).append((s, e))
        if earn_p.exists():
            df = pd.read_csv(earn_p)
            if df.empty: problems.append(f"{earn_p.name} is empty")
            for r in df.itertuples():
                earn.setdefault(r.symbol, []).append(pd.to_datetime(r.event_date).date())
        if problems and not allow_unverified:
            raise RuntimeError("Pass 2 refused (fail-closed): " + "; ".join(problems))
        return cls(asm, {k: sorted(v) for k, v in earn.items()}, block_days, known_ahead_days, applied=not problems)
```
**Also fix the earnings scraper** (`backtest/bifurcated_scraper/earnings_scraper.py`): it queries the NSE *corporate actions* endpoint and keeps ex-dividend dates. Replace with the exchange's board-meeting / financial-results announcement feed, output columns `symbol,event_date,announced_date,source_url`. Until that exists, Pass 2 cannot be run unverified: use `allow_unverified=True` only for experiments, and the audit then sets `compliance_applied=false` and `eligible_for_deployment=false`. ASM/GSM: implement the PDF extraction in `asm_gsm_pdf_scraper.py` (currently a stub returning `[]`) or populate the CSV by hand; every row must be `VERIFIED` with real `start_date`/`end_date`.

### Step 3.4 — The single simulator `backtest/simulator.py` (P0, L)
Replaces `pass1_naive_run.py` (`_simulate_lifecycle`, `_Pass1Screener`, `_build_candidate_dicts`) and the equity loop in `pass2_compliant_run.py`. Delete those after the golden-master test passes.
```python
"""backtest/simulator.py — one simulator for Pass 1 (exclusions=None) and Pass 2 (exclusions=Exclusions)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import distinct, select

from data.db.models import MarketDataLake
from engine_core.candidate_builder import build_candidate_dicts
from engine_core.costs import CostModel
from engine_core.entry_filters import apply_entry_filters
from engine_core.indicators import atr
from engine_core.lifecycle_rules import (BarCtx, Bar, LifecycleRules, PosState, advance_one_bar,
                                         parabolic_ref_close, plan_entry_fill)
from engine_core.regime_filter import RegimeFilter
from engine_core.regime_gates import bull_correction_active, is_bull, nifty_sma
from engine_core.risk_sizing import RiskAndSizingEngine
from engine_core.universe_screener import UniverseScreener


@dataclass
class SimResult:
    trades: pd.DataFrame
    equity: pd.Series
    skipped: list = field(default_factory=list)
    compliance_applied: bool = False


class Simulator:
    def __init__(self, config: dict, session):
        self.cfg, self.s = config, session
        self.rules = LifecycleRules.from_config(config)
        self.costs = CostModel.from_config(config)
        self.regime = RegimeFilter(config, session)
        self.screener = UniverseScreener(config, session)
        self.sizer = RiskAndSizingEngine(config)

    # ---- helpers --------------------------------------------------------------
    def _bar(self, sym: str, d: date):
        c = build_candidate_dicts(self.s, self.cfg, [sym], d)
        if not c or d not in c[0]["adjusted_ohlcv"].index:
            return None
        adj = c[0]["adjusted_ohlcv"]
        a = atr(adj["high_adj"], adj["low_adj"], adj["close_adj"], period=int(self.cfg["risk"]["atr_period"]))
        r = adj.loc[d]
        return (Bar(float(r.open_adj), float(r.high_adj), float(r.low_adj), float(r.close_adj)),
                float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else 0.0,
                parabolic_ref_close(list(adj["close_adj"]), self.rules.parabolic_lookback),
                any(x["ex_date"] == d for x in c[0]["corporate_actions"]))

    @staticmethod
    def _heat_view(open_pos: dict) -> list:
        out = []
        for sym, p in open_pos.items():
            st = p["st"]
            out.append({"symbol": sym, "sector": p["sector"],
                        "risk_amount": max(0.0, st.shares_remaining * (st.entry_price - st.live_stop)),
                        "position_value": st.shares_remaining * st.entry_price})
        return out

    # ---- main loop ------------------------------------------------------------
    def run(self, start: date, end: date, initial_equity: float, exclusions=None) -> SimResult:
        cfg, ex = self.cfg, self.cfg["execution"]
        risk_pct = float(cfg["risk"]["max_loss_pct_per_trade"])
        sma_n = int(cfg.get("macro", {}).get("bull_entry_sma_period", 0))
        days = self.s.execute(select(distinct(MarketDataLake.trade_date))
                              .where(MarketDataLake.trade_date >= start, MarketDataLake.trade_date <= end)
                              .order_by(MarketDataLake.trade_date)).scalars().all()
        cash, open_pos, pending, trades, curve, skipped, pid = float(initial_equity), {}, [], [], {}, [], 0

        for d in days:
            rs = self.regime.evaluate(d)
            ks = bool(rs.kill_switch_active)
            bull = is_bull(ks, rs.nifty_close, rs.nifty_sma200)

            # 1) fill yesterday's tickets at today's open (rank order)
            eq_now = cash + sum(p["st"].shares_remaining * p["last_close"] for p in open_pos.values())
            for t in pending:
                info = self._bar(t.symbol, d)
                if info is None or t.symbol in open_pos:
                    skipped.append((d, t.symbol, "NO_BAR_OR_ALREADY_HELD")); continue
                bar, _, _, has_ca = info
                if has_ca:
                    skipped.append((d, t.symbol, "CORP_ACTION_ON_EXEC_DATE")); continue
                plan = plan_entry_fill(ticket_entry=t.entry_price, stop=t.live_stop_loss,
                                       target=t.initial_resistance_target, next_open=bar.open, equity=eq_now,
                                       risk_pct=risk_pct, slippage_pct=float(ex["entry_slippage_pct"]),
                                       max_gap_up_pct=float(ex["max_entry_gap_up_pct"]),
                                       min_rr=float(ex["min_rr_at_fill"]), cash=cash)
                if not plan.ok:
                    skipped.append((d, t.symbol, plan.reason)); continue
                buy_cost = self.costs.buy_cost(plan.fill_price * plan.shares)
                cash -= plan.fill_price * plan.shares + buy_cost
                pid += 1
                open_pos[t.symbol] = {
                    "id": pid, "sector": t.sector, "entry_date": d, "orig": plan.shares, "entry_costs": buy_cost,
                    "gross": 0.0, "costs": buy_cost, "last_close": plan.fill_price,
                    "st": PosState(entry_price=plan.fill_price, initial_stop=t.live_stop_loss,
                                   live_stop=t.live_stop_loss, target=t.initial_resistance_target,
                                   highest_high=plan.fill_price, shares_remaining=plan.shares)}
            pending = []

            # 2) advance every open position with today's bar (includes positions filled this morning)
            for sym, p in list(open_pos.items()):
                info = self._bar(sym, d)
                if info is None:
                    continue
                bar, atr14, ref, _ = info
                res = advance_one_bar(p["st"], bar, BarCtx(atr14, ks, bull, ref), self.rules,
                                      float(ex["exit_slippage_pct"]))
                p["st"], p["last_close"] = res.pos, bar.close
                for e in res.exits:
                    sell = self.costs.sell_cost(e.price * e.shares)
                    cash += e.price * e.shares - sell
                    p["gross"] += (e.price - p["st"].entry_price) * e.shares
                    p["costs"] += sell
                if res.closed:
                    net = p["gross"] - p["costs"]
                    trades.append({"position_id": p["id"], "symbol": sym, "entry_date": p["entry_date"],
                                   "exit_date": d, "entry_price": p["st"].entry_price, "stop": p["st"].initial_stop,
                                   "shares": p["orig"], "pnl_gross": p["gross"], "costs": p["costs"],
                                   "pnl_net": net, "tax_est": self.costs.tax_on_gain(net),
                                   "days_held": p["st"].days_held})
                    del open_pos[sym]

            # 3) mark to market
            eq = cash + sum(p["st"].shares_remaining * p["last_close"] for p in open_pos.values())
            curve[d] = eq

            # 4) generate tomorrow's tickets
            nsma = nifty_sma(self.s, cfg, d, sma_n) if sma_n else None
            if ks or (sma_n and bull_correction_active(rs.nifty_close, rs.nifty_sma200, nsma)):
                continue
            passed = []
            for sym in self.screener._get_all_symbols(d):
                if sym in open_pos:
                    continue
                if not self.screener.screen_single(sym, d, apply_event_gates=False).passed:
                    continue
                if exclusions and (exclusions.asm_blocked(sym, d) or exclusions.earnings_within(sym, d)):
                    continue
                passed.append(sym)
            cands = apply_entry_filters(build_candidate_dicts(self.s, cfg, passed, d), cfg)
            setups = self.sizer.compute_all(candidates=cands, eval_date=d, account_equity=eq,
                                            current_positions=self._heat_view(open_pos), session=self.s)
            pending = [x for x in setups if not x.blocked]

        # close anything still open at the last close (marked, costs applied) so metrics are complete
        # (implementation note: reuse the exit block above with Exit('END_OF_TEST', last_close, shares_remaining))
        return SimResult(pd.DataFrame(trades), pd.Series(curve, dtype="float64"), skipped,
                         compliance_applied=bool(exclusions and exclusions.applied))
```
**Acceptance (golden master):** (a) `tests/integration/test_sim_vs_live_rules.py` feeds one synthetic symbol through `Simulator` and through `PositionLifecycleManager` (PAPER) and asserts identical exit date, exit price and stop path; (b) with `exclusions=None` and with exclusions that exclude nothing, results are identical; (c) turning a symbol into an ASM exclusion removes that trade and frees its slot for the next-ranked candidate; (d) `grep -rn "Pass1NaiveRun\|Pass2CompliantRun" --include=*.py .` returns nothing after deletion.

### Step 3.5 — Runner and audit (P0, M)
**`backtest/run_backtest.py`** — replace the Pass 1 / Pass 2 blocks with:
```python
from backtest.simulator import Simulator
from backtest.exclusions import Exclusions
...
for regime in config["backtest"]["regimes"]:
    name, s, e = regime["name"], date.fromisoformat(regime["start"]), date.fromisoformat(regime["end"])
    sim = Simulator(config, session)
    if args.pass1:
        r1 = sim.run(s, e, config["backtest"]["initial_equity"], exclusions=None)
        r1.trades.to_csv(out_dir / f"trades_pass1_{name}.csv", index=False)
        r1.equity.to_csv(out_dir / f"equity_pass1_{name}.csv")
    if args.pass2:
        block_days = int(config_value_at("binary_event_block_days"))   # key is at strategy_config.yaml line 37; read it from its real parent section
        exc = Exclusions.load(out_dir, name, block_days, int(config["earnings"]["known_ahead_days"]),
                              allow_unverified=args.allow_unverified)
        r2 = sim.run(s, e, config["backtest"]["initial_equity"], exclusions=exc)
        r2.trades.to_csv(out_dir / f"trades_pass2_{name}.csv", index=False)
        r2.equity.to_csv(out_dir / f"equity_pass2_{name}.csv")
        pd.DataFrame(r2.skipped, columns=["date", "symbol", "reason"]).to_csv(out_dir / f"skipped_pass2_{name}.csv", index=False)
```
(`config_value_at` is a placeholder: read `binary_event_block_days` from its actual parent section in `strategy_config.yaml`.) Add CLI flags `--allow-unverified`, `--freeze`, `--test`: `--freeze` writes `git hash-object strategy_config.yaml` to `outputs/FROZEN.sha` after TUNE windows are done; `--test` refuses to run TEST windows unless the current config hash equals `FROZEN.sha`. `--all` must **not** skip verification any more.

**Replace `backtest/audit_generator.py`** entirely:
```python
from __future__ import annotations
import hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from engine_core.trade_metrics import metrics_from_trades, sharpe_from_equity

def _git(*a: str) -> str:
    return subprocess.check_output(["git", *a], text=True).strip()

def summarize(res, nifty: pd.Series, cfg: dict, initial: float) -> dict:
    g = cfg["gates"]
    eq = res.equity
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    tax = float(res.trades["tax_est"].sum()) if len(res.trades) else 0.0
    final_after_tax = float(eq.iloc[-1]) - tax
    cagr = ((final_after_tax / initial) ** (1 / years) - 1) * 100
    n0, n1 = float(nifty.iloc[0]), float(nifty.iloc[-1])
    n_net_end = n1 - max(0.0, n1 - n0) * g["ltcg_tax_pct"] / 100
    n_cagr = ((n_net_end / n0) ** (1 / years) - 1) * 100
    dd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100)
    m = metrics_from_trades(res.trades, initial) if len(res.trades) else {"n_trades": 0}
    return {**m, "cagr_after_tax_pct": cagr, "nifty_cagr_after_tax_pct": n_cagr, "alpha_after_tax_pct": cagr - n_cagr,
            "max_drawdown_pct": dd, "sharpe": sharpe_from_equity(eq, g["risk_free_pct"] / 100),
            "compliance_applied": res.compliance_applied}

def generate(summaries: dict, cfg: dict, out_dir: Path) -> dict:
    g, ok_all, per = cfg["gates"], True, {}
    for name, m in summaries.items():
        checks = {"max_drawdown": m.get("max_drawdown_pct", 99) < g["max_drawdown_pct"],
                  "alpha_after_tax": m.get("alpha_after_tax_pct", -99) >= g["min_alpha_after_tax_pct"],
                  "expectancy": m.get("expectancy_r", -9) >= g["min_expectancy_r"],
                  "profit_factor": m.get("profit_factor", 0) >= g["min_profit_factor"],
                  "min_trades": m.get("n_trades", 0) >= g["min_trades"],
                  "compliance_applied": bool(m.get("compliance_applied"))}
        per[name] = checks
        ok_all &= all(checks.values())
    cfg_sha = _git("hash-object", "strategy_config.yaml")
    audit = {"audit_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "strategy_config_sha": cfg_sha, "commit_sha": _git("rev-parse", "HEAD"),
             "working_tree_clean": _git("status", "--porcelain") == "",
             "metrics": summaries, "checks": per,
             "dual_gate": {"overall_pass": ok_all}, "eligible_for_deployment": bool(ok_all)}
    p = out_dir / "audit.json"
    p.write_text(json.dumps(audit, indent=2, default=str))
    audit["audit_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    (out_dir / "audit.sha256").write_text(audit["audit_sha256"])
    return audit
```
`--audit` in the runner: load `equity_pass2_*.csv` / `trades_pass2_*.csv` (or keep the `SimResult`s in memory), build `nifty` from `market_data_lake` for the same dates, call `summarize` per window then `generate`. **Remove** the hardcoded `True` defaults, the `allowed_underperform_pct` tolerance and the old Sharpe. Commit `audit.json` and `audit.sha256` (remove from `.gitignore`) so the authorization evidence lives in the repo.

### Step 3.6 — Re-run and decide (Gate G2) (P0, M)
1. `python -m data.db.migration_phase3_paper` (if not yet applied) and rebuild the data per Step 1.2.
2. Populate and VERIFY ASM/GSM + earnings files for every window (Step 3.3).
3. TUNE windows: `python -m backtest.run_backtest --pass1 --pass2`. Tune only on TUNE windows. Then `--freeze`.
4. TEST window: `python -m backtest.run_backtest --test --pass1 --pass2`. **No config changes** between freeze and test.
5. `--audit`. If any check fails, **stop**: do not start paper trading; go back to strategy design. Do not loosen gates.
6. Expect numbers to be worse than the old audit (next-open fills, gap-aware stops, costs, tax). That is the honest baseline.

---

## Phase 4 — Harden the authorization lock (P1; must finish before Gate G3)

### Step 4.1 — `authorize_live.py` (P1, M)
Add (keep the existing clean-tree check and CLI):
```python
import hashlib, json, subprocess
def sha256_file(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def git(*a): return subprocess.check_output(["git", *a], text=True).strip()

def validate_audit(audit_path: str, cfg: dict) -> dict:
    audit = json.load(open(audit_path))
    current_cfg_sha = git("hash-object", "strategy_config.yaml")
    if audit["strategy_config_sha"] != current_cfg_sha:
        raise SystemExit(f"REFUSED: audit was generated for config {audit['strategy_config_sha'][:8]}, "
                         f"current config is {current_cfg_sha[:8]}. Re-run the backtest.")
    if not audit.get("working_tree_clean", False):
        raise SystemExit("REFUSED: audit was produced from a dirty working tree.")
    g = cfg["gates"]                                    # recompute — do not trust the stored flag
    for name, m in audit["metrics"].items():
        if not (m["max_drawdown_pct"] < g["max_drawdown_pct"] and m["alpha_after_tax_pct"] >= g["min_alpha_after_tax_pct"]
                and m["expectancy_r"] >= g["min_expectancy_r"] and m["profit_factor"] >= g["min_profit_factor"]
                and m["n_trades"] >= g["min_trades"] and m["compliance_applied"]):
            raise SystemExit(f"REFUSED: window {name} does not meet the gates.")
    if sha256_file(audit_path) != open(audit_path.replace("audit.json", "audit.sha256")).read().strip():
        raise SystemExit("REFUSED: audit.json does not match audit.sha256")
    return audit
```
Write `strategy_config_sha`, `audit_sha256`, `mode` (`PAPER` or `LIVE` as per config) and `authorized_at` into `authorized_deployment.json`. Authorizing for `LIVE` additionally requires `docs/PAPER_RESULT.json` (written by Step 5.3) showing the paper criteria passed.

### Step 4.2 — `live_runner/git_lock.py` (P1, S)
Replace the "HEAD~1 == authorized_sha" acceptance with:
```python
def _only_auth_file_changed() -> bool:
    files = git("diff", "--name-only", "HEAD~1", "HEAD").split()
    return files == ["authorized_deployment.json"]

# inside verify_git_lock(), after the clean-tree check:
head, authorized = git("rev-parse", "HEAD"), data["authorized_sha"]
ok = head == authorized or (git("rev-parse", "HEAD~1") == authorized and _only_auth_file_changed())
if not ok:
    raise SystemExit("SYSTEM_LOCKED_CODE_MODIFIED")
if git("hash-object", "strategy_config.yaml") != data["strategy_config_sha"]:
    raise SystemExit("SYSTEM_LOCKED_CONFIG_MODIFIED")
```
This closes the hole where any single commit on top of the authorized SHA passed.

### Step 4.3 — Re-check before every scheduled run (P1, S)
In `live_runner/scheduler.py`, call `verify_git_lock()` at the top of the scheduled job function (not only in the FastAPI startup hook). On failure log, send an alert, and skip the run.

### Step 4.4 — Click-to-Trade barrier test (P1, S)
`tests/unit/test_regulatory_barrier.py`:
```python
import pathlib, re
from live_runner.main import app

FORBIDDEN_ROUTE = re.compile(r"order|place|execute|trade|buy|sell|broker|kite", re.I)
FORBIDDEN_CODE = re.compile(r"place_order|modify_order|kiteconnect|selenium|playwright|pyautogui|pywinauto", re.I)
ALLOWED = {"/positions/open", "/positions/close"}          # these only RECORD fills; they call no broker

def test_no_order_routes():
    bad = [r.path for r in app.routes if hasattr(r, "path") and r.path not in ALLOWED
           and FORBIDDEN_ROUTE.search(r.path)]
    assert not bad, f"order-like routes found: {bad}"

def test_no_broker_order_code():
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = [str(p) for d in ("live_runner", "engine_core") for p in (root / d).rglob("*.py")
            if FORBIDDEN_CODE.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not hits, f"broker/order automation code found: {hits}"
```
(If market-data ingestion legitimately imports a read-only Kite client, keep it outside `live_runner/` and `engine_core/`, or whitelist that one file.)

---

## Phase 5 — Paper run (Gate G3 → G4) (P0)

### Step 5.1 — Start checklist (all must be true)
- [ ] G1 and G2 passed; `audit.json` + `audit.sha256` committed.
- [ ] `runtime.mode: PAPER`; `authorize_live.py` run on a clean tree; `authorized_deployment.json` committed.
- [ ] `docs/PAPER_TRADE_CRITERIA.md` committed **before** the first paper trade.
- [ ] Pre-flight data spot-check passes on the server. VERIFY it exists in the repo (it was Chunk 1.5 of the original dev plan); if not, implement it: adjust a known split/bonus symbol and assert the adjusted close equals a hardcoded reference value, aborting the nightly run on mismatch.
- [ ] Scheduler runs once per trading day after the bhavcopy is available; failures alert you.
Record the authorized SHA and start date. **Any commit that changes code or config stops the lock and restarts the count.**

### Step 5.2 — Daily health check `scripts/daily_health_check.py` (P0, S)
```python
"""Exit code 1 if anything looks wrong. Run after the nightly job."""
import sys
from datetime import date, timedelta
from sqlalchemy import text
from data.db.connection import get_session

def main() -> int:
    problems = []
    with get_session() as s:
        run = s.execute(text("SELECT run_date, status FROM pipeline_run_log ORDER BY run_date DESC LIMIT 1")).first()
        last_bar = s.execute(text("SELECT MAX(trade_date) FROM market_data_lake")).scalar()
        if run is None or run[1] != "SUCCESS": problems.append(f"last pipeline run not SUCCESS: {run}")
        if run and str(run[0]) != str(last_bar): problems.append(f"pipeline date {run[0]} != latest data {last_bar}")
        if last_bar and (date.today() - date.fromisoformat(str(last_bar))).days > 4: problems.append("price data is stale")
        n_pend = s.execute(text("SELECT COUNT(*) FROM daily_watchlist WHERE execution_status='PENDING' "
                                "AND run_date < (SELECT MAX(run_date) FROM daily_watchlist)")).scalar()
        if n_pend: problems.append(f"{n_pend} old tickets still PENDING (paper trader not running?)")
        stale = s.execute(text("SELECT COUNT(*) FROM active_positions WHERE mode='PAPER' AND "
                               "(last_evaluated_date IS NULL OR last_evaluated_date < (SELECT MAX(run_date) FROM pipeline_run_log))")).scalar()
        if stale: problems.append(f"{stale} paper positions not advanced on the last run")
    print("OK" if not problems else "\n".join(problems))
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main())
```
(Adjust the `status` literal to whatever `PipelineRunLog.status` uses on success.)

### Step 5.3 — Weekly report and criteria evaluation `scripts/paper_report.py` (P0, M)
Add to `strategy_config.yaml`:
```yaml
paper_criteria:
  min_days: 90
  min_closed_trades: 60
  max_expectancy_gap_r: 0.25
  max_win_rate_gap_pts: 12.0
  min_profit_factor: 1.2
  max_drawdown_pct: 12.0
  max_skipped_ticket_rate: 0.40
```
Script logic: load `trades_from_log(session, "PAPER")` filtered to `entry_date >= authorized_at`; `metrics_from_trades`; compare with `audit["metrics"]` averaged over TEST+TUNE windows **using the same definitions**; compute skipped rate = SKIPPED / (OPENED + SKIPPED) from `daily_watchlist`; print a table (pass/fail per criterion); write `docs/PAPER_RESULT.json` with `passed: true|false` and the numbers. Run weekly; do not look at the result as a reason to change code mid-run.

### Step 5.4 — Change control during the run
- No strategy-affecting commits. Measurement-only work (reports, tests, docs, UI polish that does not touch engine files) must not touch `strategy_config.yaml` or `engine_core/`; if it does, the lock fires and the run restarts.
- Keep a `paper_log.md`: date, anything unusual (data gaps, splits, halts, manual interventions). Every manual DB edit must be listed.
- In parallel (allowed): verify more historical ASM/GSM + earnings data; add tests for sizing, screening and the pipeline; clean `requirements.txt` (add `yfinance` or whatever ingestion imports), remove hardcoded Windows paths, document data provenance.

---

## Phase 6 — Go-live decision (Gate G4 → G5) (P1)

1. `python scripts/paper_report.py` shows **all** paper criteria passed (`docs/PAPER_RESULT.json passed: true`).
2. Review skipped tickets and the five worst trades by hand; confirm no data errors (splits, halts).
3. Set `runtime.mode: LIVE`, commit, run the corrected backtest again (config changed → new audit), run `authorize_live.py` (it now requires `PAPER_RESULT.json`).
4. Start at **25% of intended size** (set `risk.max_loss_pct_per_trade` to 0.25 for the first N=20 live trades) and add a guardrail in `pipeline.py` before ticket generation:
```python
        guard = self.config.get("live_guardrails", {})          # e.g. {max_drawdown_pct: 8.0}
        if mode == "LIVE" and guard:
            peak, eq = self._live_equity_peak(), self._live_equity()
            if peak and (peak - eq) / peak * 100 >= float(guard["max_drawdown_pct"]):
                results["paused"] = "LIVE_DRAWDOWN_GUARD"       # still advance positions, issue NO new tickets
                return results
```
5. Record every real fill via `POST /positions/open` with the real broker price; compare realized slippage to the paper assumption weekly and update the config (then re-authorize).
6. Scale to full size only after another 30+ live trades within the paper-derived bands. Keep the drawdown guardrail permanently.

---

## Appendix A — Dependency order and ownership
| Order | Steps | Can run in parallel with |
|---|---|---|
| 1 | 0.1–0.3 | — |
| 2 | 1.1, 1.2 (data), 1.3 | 1.4, 1.5, 1.6 after 1.3 |
| 3 | 2.1–2.4 | 3.1–3.3 |
| 4 | 2.5–2.9 | 3.2–3.3 |
| 5 | 3.4–3.5 → **G1** | 4.1–4.4 |
| 6 | 3.6 → **G2** | — |
| 7 | 4.x → **G3** | — |
| 8 | 5.x (paper) | verification of ASM/earnings history, tests, cleanup |
| 9 | 6.x | — |

## Appendix B — File index
**New:** `engine_core/{lifecycle_rules,candidate_builder,entry_filters,sector_map,regime_gates,mode,costs,equity,position_service,trade_metrics}.py`, `live_runner/paper_trader.py`, `backtest/{simulator,exclusions}.py`, `data/db/migration_phase3_paper.py`, `data/reference/sector_map.csv`, `scripts/{compare_price_sources,daily_health_check,paper_report}.py`, `docs/PAPER_TRADE_CRITERIA.md`, tests (lifecycle rules, adjustments, paper trader, simulator golden master, regulatory barrier, lock).
**Modified:** `engine_core/{adjustments,position_lifecycle,risk_sizing,universe_screener,analytics_loop,account_ledger}.py`, `live_runner/{pipeline,git_lock,scheduler}.py`, `live_runner/routers/{positions,portfolio,watchlist}.py`, `data/db/models.py`, `backtest/{run_backtest,audit_generator}.py`, `backtest/bifurcated_scraper/*`, `authorize_live.py`, `strategy_config.yaml`, `.gitignore` (stop ignoring `audit.json`), `ui/src/*`.
**Deleted:** `backtest/pass1_naive_run.py`, `backtest/pass2_compliant_run.py`, `fix_blocker1_index_data.py`, `fix_blocker2_shares_outstanding.py` (archive outside the repo; they contain `DELETE`s and a hardcoded Windows path).

## Appendix C — Known limits this plan does NOT remove
1. **Survivorship bias:** the universe is symbols that exist in the data today; delisted/merged stocks are absent from history. Obtain a point-in-time constituent list if possible; otherwise treat backtest results as optimistic.
2. **Shares outstanding** are a current snapshot applied back in time, so historical market-cap gating is approximate.
3. **Earnings knowability:** the backtest can only approximate what live would have known (`earnings.known_ahead_days`).
4. **Tax model** is a per-position approximation (no loss set-off); confirm treatment with an accountant before real money.
5. **Win rate and Sharpe** reported in older artifacts (`confidence_report.md`, `outputs_v1_stale`) are on the old definitions and must not be compared with the new numbers.
6. **No code in this plan was executed by its author.** Treat the acceptance tests as the specification; where a code block and the tests disagree, the tests win.


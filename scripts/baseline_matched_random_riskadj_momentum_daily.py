"""B1 baseline for the riskadj_momentum_daily validation: matched random entries, each with the SAME rule as the strategy on its OWN symbol.

  py scripts/baseline_matched_random_riskadj_momentum_daily.py --lake PATH --run-dir DIR --out-dir NEW_DIR [--draws 20] [--min-filled 10] [--seed 20261111] [--no-hash]

For every usable trade of the run (everything except trades flagged excluded_ca; trades closed at the window end COUNT), on the SAME signal session, 20 symbols are drawn at random (seed 20261111)
from the shared-eligible pool of that date, never the trade's own symbol, no pool filter, no ASM ranges. Every random entry gets the strategy's rule on its own symbol: initial stop = signal
close - max(3 x ATR14, 0.08 x close) (the strategy's own ``initial_stop`` and ATR function), exit policy RmdTrailingAtr3Floor8, the same next-open fill, slippage, gap rule, corporate-action
rebasing, stepping and costs as the strategy.

Why not the shared helper: ``draw_matched_random`` gives every draw the ACTUAL trade's relative stop distance, which is not the registered rule, and ``simulate_ticket`` drops a path that is
still open at the window end. ``draw_matched_random_own`` below is a strategy-side copy of the shared loop with exactly two differences, both switchable: the stop rule (``stop_rule``; the
shared helper's rule is ``shared_relative_stop`` and with it, and a policy that closes inside the lake, the output equals the shared helper's row for row: tests/unit/
test_riskadj_momentum_daily_scripts.py) and the end-of-window closure (``close_at_end``).

POOL (decided 2026-11-16, option C): for each actual entry the random pool also drops the symbols THE STRATEGY ITSELF could not have bought on that signal session, taken from the stored run's trades (never from the
draws): symbols it held (entry date <= the signal session < exit date) and symbols in its own re-entry cooldown (a STOP_HIT exit, exit session up to ``reentry_cooldown_sessions`` (21) sessions before the signal
session, the exit session included: the 22nd session after the exit is allowed again), compared by canonical (linked) name; the trade's own symbol is dropped as in the shared helper. Random draws never block each
other. ``PoolExclusions`` below does it through the ``pool_filter`` hook of the draw loop; the counts (held, cooldown, own symbol, pool sizes) are written to baseline_meta.json under ``pool_exclusions``. With
``pool_filter=None`` the loop is the shared helper's (tests/unit/test_riskadj_momentum_daily_scripts.py).

END-OF-WINDOW RULE (registered before any result): a draw still open after the last session is closed at the last close with the normal exit slippage and costs and counts as filled (exit reason
END_OF_WINDOW), exactly as the runner closes the strategy's own open positions. The numbers of such draws and of such trades are written separately in baseline_meta.json.
A pair needs at least ``min_filled`` filled draws; short pairs are counted, and more than 5% of trades losing their pair is flagged. No portfolio effects.

Reads: eligibility and each draw's path; forward returns for the secondary test T2 only up to 20 sessions after the entry (blanked when a split or bonus falls inside; raw closes), capped by
``ForwardCappedView``. Writes actual_trades.csv, baseline_draws.csv, baseline_meta.json.
"""
import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.adjustments import action_factor  # noqa: E402
from stockbot.data.asof import DEFAULT_LOOKBACK, AsOfView, active_view_name  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.engine.corporate import apply_actions, due_actions  # noqa: E402
from stockbot.engine.decide import bar_of  # noqa: E402
from stockbot.engine.fills import fill_ticket  # noqa: E402
from stockbot.engine.stale import no_bars_for, stale_sessions  # noqa: E402
from stockbot.engine.stepping import close_no_bars, step_position  # noqa: E402
from stockbot.engine.types import ClosedTrade, Ticket  # noqa: E402
from stockbot.risk.costs import CostModel  # noqa: E402
from stockbot.risk.r_metrics import compute_trade_r  # noqa: E402
from stockbot.strategies.riskadj_momentum_daily import SPEC, RmdTrailingAtr3Floor8  # noqa: E402
from stockbot.strategies.riskadj_momentum_daily.indicators import ATR_BARS, atr_last  # noqa: E402
from stockbot.strategies.riskadj_momentum_daily.strategy import initial_stop  # noqa: E402
from stockbot.universe.eligibility import eligible_symbols  # noqa: E402
from stockbot.validation.random_baseline import forward_returns_pct  # noqa: E402

DRAWS, MIN_FILLED, SEED, MAX_H = 20, 10, 20261111, 20
HORIZONS = (1, 5, 10, 20)
LOSS_FLAG = 0.05
EOW = "END_OF_WINDOW"
SUBPERIODS = (("2016-2019", date(2016, 1, 1), date(2019, 12, 31)), ("2020-2026", date(2020, 1, 1), date(2026, 12, 31)))


def window_label(d: date) -> str:
    for tag, lo, hi in SUBPERIODS:
        if lo <= d <= hi:
            return tag
    return SUBPERIODS[-1][0] if d > SUBPERIODS[-1][2] else SUBPERIODS[0][0]


# ----------------------------------------------------------------------------------------------------------------------------- stop rules
def shared_relative_stop(a, view, sym: str, ref: float):
    """The shared helper's rule: the actual trade's RELATIVE stop distance applied to the draw's close. Used only to prove the loop below equals the shared one."""
    return ref * (1.0 - (a.entry_price - a.stop) / a.entry_price)


def own_atr_stop(a, view, sym: str, ref: float):
    """The registered rule on the draw's own symbol: close - max(3 x ATR14, 0.08 x close), ATR from the last ATR_BARS adjusted bars as of the signal session (the strategy's own function).
    None (the draw is not filled, reason NO_STOP) when the ATR is unavailable or the stop would be at or below zero."""
    atr = atr_last(view.adjusted_bars(sym, lookback=ATR_BARS), int(SPEC.params["atr_period"]))
    if atr is None:
        return None
    stop, _ = initial_stop(ref, atr, SPEC.params)
    return stop if stop > 0 else None



# ----------------------------------------------------------------------------------------------------------------------------- the strategy's own unavailable symbols
class PoolExclusions:
    """``pool_filter(view, symbol) -> keep``: False for a symbol the strategy held, or had in its own cooldown, on ``view.as_of`` (the signal session). Built from the stored run's trades (all of them, excluded_ca too)."""

    def __init__(self, trades, sessions, cooldown: int):
        from stockbot.data.symbol_links import resolve
        self.resolve = resolve
        self.pos = {d: i for i, d in enumerate(sessions)}
        self.cooldown = int(cooldown)
        self.held: dict = {}                      # canonical symbol -> [(entry index, exit index)]
        self.stops: dict = {}                     # canonical symbol -> [exit index of a STOP_HIT]
        for t in trades:
            sym = resolve(t["symbol"])
            e, x = self.pos.get(date.fromisoformat(t["entry_date"])), self.pos.get(date.fromisoformat(t["exit_date"]))
            if e is None or x is None:
                continue
            self.held.setdefault(sym, []).append((e, x))
            if t.get("exit_reason_engine", t["exit_reason"]) == "STOP_HIT":
                self.stops.setdefault(sym, []).append(x)
        self.counts = {"checked": 0, "kept": 0, "held": 0, "cooldown": 0}

    def reason(self, symbol: str, day: date):
        i = self.pos.get(day)
        if i is None:
            return None
        sym = self.resolve(symbol)
        if any(e <= i < x for e, x in self.held.get(sym, ())):
            return "held"
        if any(0 <= i - x <= self.cooldown for x in self.stops.get(sym, ())):
            return "cooldown"
        return None

    def __call__(self, view, symbol: str) -> bool:
        r = self.reason(symbol, view.as_of)
        self.counts["checked"] += 1
        self.counts["kept" if r is None else r] += 1
        return r is None

# ----------------------------------------------------------------------------------------------------------------------------- the loop
def simulate_ticket_own(t: Ticket, sessions, view_at, *, shared_config, policy, equity: float, close_at_end: bool = True) -> tuple:
    """Copy of stockbot.engine.path.simulate_ticket (same fill, rebasing, stepping, costs) that, when ``close_at_end``, closes a position still open after the last session at the last close x
    (1 - exit slippage) with the sell cost, reason END_OF_WINDOW (the arithmetic of stockbot.backtest.runner). Returns (ClosedTrade or None, reason)."""
    costs = CostModel.from_shared(shared_config.costs)
    ex, pr = shared_config.execution, shared_config.portfolio_risk
    todo = [d for d in sessions if d > t.signal_date]
    if not todo:
        return None, "NO_SESSION"
    day = todo[0]
    view = view_at(day)
    plan = fill_ticket(t, bar_of(view, t.symbol), day, execution=ex, risk_pct=pr.max_loss_pct_per_trade, equity=equity, cash=equity, costs=costs, policy_id=policy.id, held=False,
                       corporate_action_today=any(a["ex_date"] == day for a in view.corporate_actions(t.symbol)), confirm=lambda proposal, price: None,
                       initial_exit_state=lambda p: dict(policy.initial_state(p, view)))
    if not plan.ok:
        return None, plan.reason
    pos = plan.position
    stale_n = stale_sessions(shared_config)
    for d in todo:
        view = view_at(d)
        bar = bar_of(view, pos.symbol)
        if bar is None:
            if stale_n and no_bars_for(view, pos.symbol, stale_n):                    # the shared no-bars closure (stockbot.engine.path): a filled draw, reason SYMBOL_NO_BARS
                res = close_no_bars(pos, d, costs, ex.exit_slippage_pct)
                pos = res.position
                net = pos.gross_pnl - pos.costs_paid
                return ClosedTrade(pos.position_id, pos.strategy_id, pos.symbol, pos.entry_date, d, pos.entry_price, pos.initial_stop, pos.shares_initial, pos.risk_inr,
                                   pos.gross_pnl, pos.costs_paid, net, "SYMBOL_NO_BARS", pos.hold), "CLOSED"
            continue
        due = due_actions(view.corporate_actions(pos.symbol), pos.entry_date, d, pos.ca_done)
        if due:
            pos = apply_actions(pos, due, bar.open, policy).position
        res = step_position(pos, bar, d, view, policy, costs, ex.exit_slippage_pct)
        pos = res.position
        if res.closed:
            net = pos.gross_pnl - pos.costs_paid
            return ClosedTrade(pos.position_id, pos.strategy_id, pos.symbol, pos.entry_date, d, pos.entry_price, pos.initial_stop, pos.shares_initial, pos.risk_inr,
                               pos.gross_pnl, pos.costs_paid, net, res.exits[-1].reason, pos.hold), "CLOSED"
    if not close_at_end:
        return None, "OPEN_AT_END"
    price = pos.last_close * (1.0 - ex.exit_slippage_pct / 100.0)
    sell = costs.sell_cost(price * pos.shares_remaining)
    gross = pos.gross_pnl + (price - pos.entry_price) * pos.shares_remaining
    paid = pos.costs_paid + sell
    return ClosedTrade(pos.position_id, pos.strategy_id, pos.symbol, pos.entry_date, todo[-1], pos.entry_price, pos.initial_stop, pos.shares_initial, pos.risk_inr,
                       gross, paid, gross - paid, EOW, pos.hold), "END_OF_WINDOW"


def draw_matched_random_own(actual: pd.DataFrame, *, sessions, view_at, shared_config, policy, equity: float, draws_per_trade: int, seed: int, stop_rule=own_atr_stop,
                            close_at_end: bool = True, forward_fn=None, pool_filter=None, asm_ranges=None) -> pd.DataFrame:
    """Same loop, same random stream and same rows as stockbot.validation.random_baseline.draw_matched_random (``actual``: unique_trade_id, symbol, entry_date, entry_price, stop, window), with
    the stop rule and the end-of-window closure as parameters. ``forward_fn(symbol, entry_date, entry_price)`` supplies the forward returns (default: the shared helper's, on the last session)."""
    rng = random.Random(seed)
    sessions = sorted(sessions)
    index = {d: i for i, d in enumerate(sessions)}
    last = view_at(sessions[-1])
    forward_fn = forward_fn or (lambda sym, d, px: forward_returns_pct(last, sym, d, px))
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
        picks = rng.sample(pool, min(draws_per_trade, len(pool)))
        for sym in sorted(picks):
            bar = bar_of(view, sym)
            if bar is None:
                continue
            ref = bar.close
            stop = stop_rule(a, view, sym, ref)
            if stop is None:
                unfilled["NO_STOP"] = unfilled.get("NO_STOP", 0) + 1
                continue
            t = Ticket(f"rand:{sym}:{signal_day.isoformat()}", "random", sym, None, signal_day, ref, stop, None, 0, 0.0, 0.0, signal_day)
            trade, why = simulate_ticket_own(t, sessions, view_at, shared_config=shared_config, policy=policy, equity=equity, close_at_end=close_at_end)
            if trade is None:
                unfilled[why] = unfilled.get(why, 0) + 1
                continue
            r = compute_trade_r(entry_price=trade.entry_price, stop=trade.initial_stop, shares_initial=trade.shares_initial, pnl_gross=trade.gross_pnl, pnl_net=trade.net_pnl,
                                risk_inr=trade.risk_inr)
            rows.append({"matched_trade_id": a.unique_trade_id, "symbol": sym, "window": a.window, "entry_date": trade.entry_date, "exit_date": trade.exit_date,
                         "entry_price": trade.entry_price, "stop": trade.initial_stop, "exit_reason": trade.exit_reason, "gross_r": r["gross_r"], "net_r": r["net_r"],
                         "days_held": index[trade.exit_date] - index[trade.entry_date], **forward_fn(sym, trade.entry_date, trade.entry_price)})
    out = pd.DataFrame(rows)
    out.attrs["unfilled"] = unfilled
    return out


# ----------------------------------------------------------------------------------------------------------------------------- forward returns (as in the pullback script)
class ForwardCappedView(AsOfView):
    """An as-of view whose open-ended forward read stops MAX_H sessions after ``start`` (how the shared ``forward_returns_pct`` reads)."""

    def __init__(self, conn, as_of, sessions):
        super().__init__(conn, as_of)
        self._sessions = list(sessions)
        self._pos = {d: i for i, d in enumerate(self._sessions)}

    def raw_bars(self, symbol, lookback=DEFAULT_LOOKBACK, start=None, end=None):
        if lookback is None and start is not None and end is None and start in self._pos:
            end = self._sessions[min(self._pos[start] + MAX_H, len(self._sessions) - 1)]
        return super().raw_bars(symbol, lookback, start, end)


def forward_returns_bounded(conn, sessions, symbol: str, entry_date: date, entry_price: float) -> dict:
    """Percent move of the raw close h sessions after the entry session, h in HORIZONS; reads nothing after entry + MAX_H sessions; NaN when the history ends first or an adjusted action falls inside."""
    nan = {f"ret_{h}": float("nan") for h in HORIZONS}
    pos = {d: i for i, d in enumerate(sessions)}
    i = pos.get(entry_date)
    if i is None:
        return nan
    end = sessions[min(i + MAX_H, len(sessions) - 1)]
    view = AsOfView(conn, end)
    try:
        if any(entry_date < a["ex_date"] <= end and action_factor(a) != 1.0 for a in view.corporate_actions(symbol)):
            return nan
    except ValueError:
        return nan
    b = view.raw_bars(symbol, lookback=None, start=entry_date, end=end)
    after = [float(c) for d, c in b["close_raw"].items() if d > entry_date]
    return {f"ret_{h}": ((after[h - 1] / entry_price - 1.0) * 100.0 if len(after) >= h else float("nan")) for h in HORIZONS}


def run_baseline(lake, run_dir, out_dir, *, draws: int = DRAWS, min_filled: int = MIN_FILLED, seed: int = SEED, shared_config=None) -> dict:
    cfg = shared_config or load_shared_config()
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to write into a non-empty directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    trades = json.loads((run_dir / "trades.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    last_day = date.fromisoformat(manifest["window"][1])
    use = [t for t in trades if not t.get("excluded_ca", False)]
    conn = open_lake(lake)
    try:
        sessions = AsOfView(conn, last_day).sessions()
        pos = {d: i for i, d in enumerate(sessions)}
        final = sessions[-1]

        def view_at(d):
            return ForwardCappedView(conn, d, sessions) if d == final else AsOfView(conn, d)

        actual = pd.DataFrame([{"unique_trade_id": t["position_id"], "symbol": t["symbol"], "entry_date": date.fromisoformat(t["entry_date"]), "entry_price": float(t["entry_price"]),
                                "stop": float(t["initial_stop"]), "window": window_label(date.fromisoformat(t["entry_date"]))} for t in use])
        excl = PoolExclusions(trades, sessions, int(SPEC.params["reentry_cooldown_sessions"]))
        if actual.empty:
            d = pd.DataFrame()
        else:
            d = draw_matched_random_own(actual, sessions=sessions, view_at=view_at, shared_config=cfg, policy=RmdTrailingAtr3Floor8(), equity=cfg.backtest.initial_equity,
                                        draws_per_trade=draws, seed=seed, stop_rule=own_atr_stop, close_at_end=True, pool_filter=excl,
                                        forward_fn=lambda sym, ed, px: forward_returns_bounded(conn, sessions, sym, ed, px))
        unfilled = dict(d.attrs.get("unfilled", {}))
        if len(d):
            d["end_of_window"] = d["exit_reason"] == EOW
        rows = []
        for t in use:
            ed, xd = date.fromisoformat(t["entry_date"]), date.fromisoformat(t["exit_date"])
            r = compute_trade_r(entry_price=t["entry_price"], stop=t["initial_stop"], shares_initial=t["shares_initial"], pnl_gross=t["gross_pnl"], pnl_net=t["net_pnl"], risk_inr=t["risk_inr"])
            rows.append({"unique_trade_id": t["position_id"], "symbol": t["symbol"], "window": window_label(ed), "entry_date": ed, "exit_date": xd, "entry_price": t["entry_price"],
                         "stop": t["initial_stop"], "gross_r": r["gross_r"], "net_r": r["net_r"], "days_held": pos[xd] - pos[ed] if ed in pos and xd in pos else float("nan"),
                         "end_of_window": bool(t.get("end_of_window", False)), **forward_returns_bounded(conn, sessions, t["symbol"], ed, t["entry_price"])})
    finally:
        conn.close()
    a = pd.DataFrame(rows)
    counts = d.groupby("matched_trade_id").size() if len(d) else pd.Series(dtype=int)
    kept = int((counts >= min_filled).sum())
    dropped = len(use) - kept
    share = dropped / len(use) if use else 0.0
    eow_trades = int(sum(1 for t in use if t.get("end_of_window", False)))
    eow_draws = int(d["end_of_window"].sum()) if len(d) else 0
    meta = {"draws_per_trade": draws, "min_filled": min_filled, "seed": seed, "policy": SPEC.exit_policy, "stop_rule": "close - max(3 x ATR14, 0.08 x close) on the draw's own symbol",
            "usable_trades": len(use), "pairs_kept": kept, "dropped_pairs": dropped, "share_dropped": share,
            "flag": (f"more than 5% of trades lost their pair ({share:.1%}): the result is flagged" if share > LOSS_FLAG else None), "draws_total": int(len(d)),
            "end_of_window_trades": eow_trades, "end_of_window_draws": eow_draws, "draws_closed_before_window_end": int(len(d)) - eow_draws, "stale_exit_draws": int((d["exit_reason"] == "SYMBOL_NO_BARS").sum()) if len(d) else 0, "unfilled": unfilled,
            "pool_exclusions": {**excl.counts, "own_symbol_per_entry": len(use), "cooldown_days": int(SPEC.params["reentry_cooldown_sessions"]), "rule": "pool minus the strategy's held symbols and its own cooldown symbols (stored trades), minus the trade's own symbol; draws never block each other"},
            "excluded_ca": sum(1 for t in trades if t.get("excluded_ca", False)), "window": manifest["window"], "spec_config_hash": SPEC.config_hash(), "asof_view": active_view_name(),
            "end_of_window_rule": "open at the window end: closed at the last close with normal costs and slippage and counted as filled / usable"}
    for name, frame in (("actual_trades.csv", a), ("baseline_draws.csv", d)):
        frame.to_csv(out_dir / name, index=False)
    (out_dir / "baseline_meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B1: matched random draws (own ATR stop rule, own exit policy) for a riskadj_momentum_daily run.")
    ap.add_argument("--lake")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--min-filled", type=int, default=MIN_FILLED)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-hash", action="store_true")
    args = ap.parse_args(argv)
    from stockbot.config.paths import lake_path
    from stockbot.data_checks.near_high_signal_count import fingerprint
    print(f"asof_view: {active_view_name()}", flush=True)
    lp = Path(args.lake) if args.lake else lake_path()
    before = fingerprint(lp, with_hash=not args.no_hash)
    meta = run_baseline(args.lake, args.run_dir, args.out_dir, draws=args.draws, min_filled=args.min_filled, seed=args.seed)
    after = fingerprint(lp, with_hash=not args.no_hash)
    meta["finsight_db"] = {"before": before, "after": after, "unchanged": before == after}
    (Path(args.out_dir) / "baseline_meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("usable_trades", "pairs_kept", "dropped_pairs", "share_dropped", "flag", "draws_total", "end_of_window_trades", "end_of_window_draws")}, indent=1))
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())

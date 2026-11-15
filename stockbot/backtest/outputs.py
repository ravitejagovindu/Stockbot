"""Run output files shared by every backtest script (same layout as the per-strategy research scripts), plus the market-switch columns.

daily.json: {date: {"equity", "cash"}} and, ONLY when a default overlay was in force that session, "market_switch": {"state": ACTIVE|CLEAR, "reason", "reentry_count"}.
With the default overlays switched off (default_overlays=[]) the file is byte-identical to the files the research scripts wrote before the market switch existed.
trades.json: every closed trade (dataclass fields). A trade closed by the no-bars rule (exit_reason SYMBOL_NO_BARS, ``stale_exit``) also carries ``"stale_exit": true``, ``"exit_price"`` and ``"last_close"``
(the stress line of the gate report needs them); no other trade has these keys, so a run without such a trade writes exactly the bytes it wrote before the rule existed.
blocked.json: every blocked proposal (date, strategy_id, symbol, reason, stage); the market switch's blocks have reason MARKET_SWITCH, stage "overlay".
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from stockbot.overlays.market_switch import ID as MARKET_SWITCH_ID


def daily_records(res) -> dict:
    out = {}
    for dec in res.decisions:
        rec = {"equity": res.equity_curve[dec.as_of], "cash": dec.cash_after}
        ms = dec.overlay_state_after.get(MARKET_SWITCH_ID) if dec.overlay_state_after else None
        if ms is not None:
            rec["market_switch"] = {"state": ms["state"], "reason": ms["reason"], "reentry_count": ms["count"]}
        out[dec.as_of.isoformat()] = rec
    return out


def blocked_records(res) -> list:
    return [{"date": dec.as_of.isoformat(), "strategy_id": b.strategy_id, "symbol": b.symbol, "reason": b.reason, "stage": b.stage} for dec in res.decisions for b in dec.blocked]


def trade_records(res, exit_slippage_pct=None) -> list:
    """The closed trades as dicts for trades.json; stale exits (SYMBOL_NO_BARS) get stale_exit/exit_price/last_close (last_close = exit price / (1 - exit slippage))."""
    stale = {e.position_id: e for dec in res.decisions for e in dec.exits if e.reason == "SYMBOL_NO_BARS"}
    if stale and exit_slippage_pct is None:
        from stockbot.config.shared import load_shared_config
        exit_slippage_pct = load_shared_config().execution.exit_slippage_pct
    out = []
    for t in res.trades:
        d = dataclasses.asdict(t)
        if t.exit_reason == "SYMBOL_NO_BARS" and t.position_id in stale:
            price = stale[t.position_id].price
            d["stale_exit"], d["exit_price"], d["last_close"] = True, price, price / (1.0 - exit_slippage_pct / 100.0)
        out.append(d)
    return out


def write_run_files(res, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(res.manifest, indent=1, default=str), encoding="utf-8")
    (out / "trades.json").write_text(json.dumps(trade_records(res), indent=1, default=str), encoding="utf-8")
    (out / "equity_curve.json").write_text(json.dumps({d.isoformat(): v for d, v in res.equity_curve.items()}, indent=1), encoding="utf-8")
    (out / "daily.json").write_text(json.dumps(daily_records(res), indent=1), encoding="utf-8")
    (out / "blocked.json").write_text(json.dumps(blocked_records(res), indent=1), encoding="utf-8")

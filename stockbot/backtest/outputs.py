"""Run output files shared by every backtest script (same layout as the per-strategy research scripts), plus the market-switch columns.

daily.json: {date: {"equity", "cash"}} and, ONLY when a default overlay was in force that session, "market_switch": {"state": ACTIVE|CLEAR, "reason", "reentry_count"}.
With the default overlays switched off (default_overlays=[]) the file is byte-identical to the files the research scripts wrote before the market switch existed.
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


def write_run_files(res, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(res.manifest, indent=1, default=str), encoding="utf-8")
    (out / "trades.json").write_text(json.dumps([dataclasses.asdict(t) for t in res.trades], indent=1, default=str), encoding="utf-8")
    (out / "equity_curve.json").write_text(json.dumps({d.isoformat(): v for d, v in res.equity_curve.items()}, indent=1), encoding="utf-8")
    (out / "daily.json").write_text(json.dumps(daily_records(res), indent=1), encoding="utf-8")
    (out / "blocked.json").write_text(json.dumps(blocked_records(res), indent=1), encoding="utf-8")

"""docs/restructure/tools/freeze_legacy_equivalence.py - Phase 10 step 1b: freeze what the OLD code answered on the random grids that the migration tests used, BEFORE it is deleted.

For each migration test that compared a new function with legacy code (heat caps, fill-time sizing, corporate-action rescaling, the entry-bar stop, path_sim, the cost model,
the config values) the inputs and the legacy outputs are written to tests/golden/legacy_equivalence.json; the tests replay them against the new code. Inputs are stored (not
re-generated from a seed) so the golden file does not depend on the random generator of a Python version.
"""
import gzip
import hashlib
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
GOLD = ROOT / "tests" / "golden"


def caps():
    from engine_core.risk_sizing import RiskAndSizingEngine
    from stockbot.config.legacy_loader import load_config
    cfg = load_config()
    eng = RiskAndSizingEngine(cfg)
    rng = random.Random(5)
    sectors = ["IT", "BANK", "AUTO", "PHARMA", None]
    cases = []
    for _ in range(4000):
        equity = rng.choice([1e5, 1e6, 3.3e6])
        open_ = [{"sector": rng.choice(sectors), "position_value": rng.uniform(0, 0.3) * equity, "risk_amount": rng.uniform(0, 0.03) * equity} for _ in range(rng.randint(0, 13))]
        sec, val, risk = rng.choice(sectors), rng.uniform(0, 0.3) * equity, rng.uniform(0, 0.03) * equity
        mp = rng.choice([None, 5, 12])
        cases.append({"equity": equity, "open": open_, "sector": sec, "value": val, "risk": risk, "max_positions": mp,
                      "reason": eng._check_heat_cap(sec, val, risk, equity, open_, max_positions=mp), "full": bool(eng._is_heat_cap_full(open_, equity, max_positions=mp))})
    r = cfg["risk"]
    return {"limits": [int(r["max_concurrent_positions"]), float(r["max_total_portfolio_risk_pct"]), float(r["max_sector_exposure_pct"])], "cases": cases}


def sizing():
    from engine_core.lifecycle_rules import plan_entry_fill
    rng = random.Random(11)
    cases = []
    for _ in range(3000):
        equity = rng.choice([1e5, 1e6, 2.5e6, 987_000.0, 1_234_567.0])
        risk_pct = rng.choice([0.25, 0.5, 1.0, 1.5, 2.0])
        nxt = rng.uniform(20, 3000)
        stop = nxt * rng.uniform(0.6, 0.97)
        plan = plan_entry_fill(ticket_entry=nxt, stop=stop, target=nxt * 3, next_open=nxt, equity=equity, risk_pct=risk_pct, slippage_pct=0.10, max_gap_up_pct=3.0, min_rr=0.0)
        cases.append({"equity": equity, "risk_pct": risk_pct, "next_open": nxt, "stop": stop, "ok": bool(plan.ok), "fill_price": plan.fill_price, "shares": int(plan.shares)})
    return cases


def corporate():
    from engine_core.lifecycle_rules import PosState
    from stockbot.engine.corporate_action_events import apply_actions_to_position as legacy_apply, due_actions as legacy_due
    rng = random.Random(11)
    kinds = ["SPLIT", "BONUS", "DIVIDEND", "MERGER", "RIGHTS"]
    cases = []
    for _ in range(400):
        sh = rng.randint(1, 5000)
        entry = rng.uniform(20, 900)
        stop = entry * rng.uniform(0.8, 0.98)
        hh = entry * rng.uniform(1.0, 1.3)
        acts = [{"ex_date": date(2020, 2, 1 + i).isoformat(), "action_type": rng.choice(kinds), "ratio_numerator": rng.randint(1, 5), "ratio_denominator": rng.randint(1, 6)}
                for i in range(rng.randint(0, 3))]
        ex_price = entry * rng.uniform(0.3, 1.0)
        acts_d = [{**a, "ex_date": date.fromisoformat(a["ex_date"])} for a in acts]
        old = PosState(entry_price=entry, initial_stop=stop, live_stop=stop, target=entry * 1.3, highest_high=hh, shares_remaining=sh)
        ref = legacy_apply(old, legacy_due(acts_d, date(2020, 1, 1), date(2020, 3, 1)), ex_price)
        cases.append({"shares": sh, "entry": entry, "stop": stop, "hh": hh, "actions": acts, "ex_price": ex_price,
                      "out": {"shares": ref.pos.shares_remaining, "entry": ref.pos.entry_price, "initial_stop": ref.pos.initial_stop, "live_stop": ref.pos.live_stop, "target": ref.pos.target,
                              "hh": ref.pos.highest_high, "fractional_shares": ref.fractional_shares, "factor": ref.total_factor, "applied": ref.applied, "review": ref.review}})
    return cases


def entry_bar():
    from engine_core.lifecycle_rules import Bar as LBar, BarCtx, LifecycleRules, PosState, advance_one_bar
    from stockbot.config.legacy_loader import load_config
    rules = LifecycleRules.from_config(load_config())
    slip = float(load_config()["execution"]["exit_slippage_pct"])
    rng = random.Random(21)
    cases = []
    for _ in range(5000):
        entry = rng.uniform(20, 900)
        stop = entry * rng.uniform(0.85, 0.99)
        o = entry * rng.uniform(0.97, 1.03)
        lo = min(o, stop * rng.uniform(0.97, 1.03)) if rng.random() < 0.6 else o * rng.uniform(0.99, 1.0)
        lo = min(lo, o)
        hi = max(o, lo) * rng.uniform(1.0, 1.04)
        cl = rng.uniform(lo, hi)
        sh = rng.randint(1, 3000)
        res = advance_one_bar(PosState(entry_price=entry, initial_stop=stop, live_stop=stop, target=entry * 1.3, highest_high=entry, shares_remaining=sh),
                              LBar(o, hi, lo, cl), BarCtx(atr14=entry * 0.03, kill_switch=False, is_bull=False, close_n_ago=entry), rules, slip)
        hit = [e for e in res.exits if e.reason == "STOP_HIT"]
        cases.append({"entry": entry, "stop": stop, "open": o, "high": hi, "low": lo, "close": cl, "shares": sh, "exit_slippage_pct": slip,
                      "stop_exit": None if not hit else {"price": hit[0].price, "shares": hit[0].shares}})
    return cases


def path_sim_cases():
    import pytest  # noqa: F401
    from backtest.path_sim import simulate_position_path
    from engine_core.candidate_builder import build_candidate_dicts
    from engine_core.risk_sizing import RiskAndSizingEngine
    from tests.unit.test_corporate_action_hold import DATES, _build
    from tests.unit.test_f6_baseline_and_locks import _session
    out = {}
    for ws in (False, True):
        s = _session()
        cfg = _build(s, action=("SPLIT", 1.0, 2.0), factor=0.5) if ws else _build(s)
        sd, ed = DATES[9], DATES[10]
        cand = build_candidate_dicts(s, cfg, ["SYNTH"], sd)[0]
        setup = RiskAndSizingEngine(cfg).compute_setup("SYNTH", sd, cand["adjusted_ohlcv"], cand["raw_ohlcv"], 1_000_000.0, [], sector=cand["sector"])
        res = simulate_position_path(s, cfg, "SYNTH", setup, ed, DATES[17], {d: (False, True) for d in DATES}, equity=1_000_000.0, cash=1_000_000.0)
        out["split" if ws else "plain"] = {"ticket": {"entry": setup.entry_price, "stop": setup.live_stop_loss, "target": setup.initial_resistance_target},
                                           "result": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in res.items()},
                                           "execution": cfg["execution"], "costs": cfg["costs"], "exit_policy": "breakeven_r=1.0"}
    return out


def costs_and_config():
    import yaml
    from stockbot.risk.costs import CostModel as Old
    from stockbot.config.legacy_loader import load_config
    cm = Old.from_config(load_config())
    raw = (ROOT / "strategy_config.yaml").read_bytes()
    return {"legacy_cost_model": {k: getattr(cm, k) for k in ("stt_buy_pct", "stt_sell_pct", "brokerage_per_order", "exch_pct", "sebi_pct", "stamp_buy_pct", "gst_pct", "dp_sell_inr", "stcg_pct")},
            "strategy_config_sha256": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(), "strategy_config": yaml.safe_load(raw.decode("utf-8"))}


def main() -> int:
    GOLD.mkdir(parents=True, exist_ok=True)
    data = {"caps": caps(), "sizing": sizing(), "corporate": corporate(), "entry_bar": entry_bar(), "path_sim": path_sim_cases(), **costs_and_config()}
    raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    with open(GOLD / "legacy_equivalence.json.gz", "wb") as fh:
        fh.write(gzip.compress(raw, 9, mtime=0))                       # mtime 0: the same content always gives the same bytes
    (GOLD / "legacy_equivalence.json").unlink(missing_ok=True)
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in sorted(GOLD.iterdir()) if f.name != "SHA256SUMS"]
    (GOLD / "SHA256SUMS").write_text(chr(10).join(sums) + chr(10), encoding="utf-8")
    print({k: (len(v) if hasattr(v, "__len__") else v) for k, v in data.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())

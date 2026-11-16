"""Byte-identity harness: riskadj_momentum and lowvol_uptrend on a fixture lake (backtest outputs + live journal/state). Usage: py proof_fixture.py OUT.json  (run from the repo root)."""
import hashlib
import importlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from stockbot.config.shared import load_shared_config  # noqa: E402
from stockbot.data.asof import AsOfView  # noqa: E402
from stockbot.data.lake import open_lake  # noqa: E402
from stockbot.data.sector_map import SectorLookup  # noqa: E402
from stockbot.engine.decide import EventData  # noqa: E402
from stockbot.live.adapter import LiveAdapter  # noqa: E402
from stockbot.live.runner import Book  # noqa: E402
from stockbot.live.state_store import StateStore  # noqa: E402
from tests.fixtures import near_high_series_lake as L  # noqa: E402

N, S, LAST = 420, 284, 284 + 45


def walk(seed, drift, sigma, n=N):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(drift + sigma * rng.standard_normal(n)))


def names():
    s = {f"CALM{k:02d}": walk(100 + k, 0.0015, 0.01) for k in range(16)}
    s.update({f"WILD{k:02d}": walk(200 + k, 0.004, 0.03) for k in range(16)})
    # a few falling names so that stops are hit inside the window
    for k in range(6):
        c = walk(300 + k, 0.002, 0.012)
        c[S + 6 + k:] = c[S + 6 + k] * 0.6
        s[f"FALL{k:02d}"] = c
    return s


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(out_json):
    tmp = Path(tempfile.mkdtemp())
    lake = tmp / "lake.db"
    ds = L.build(lake, names(), n=N)
    res = {}
    for strat in ("riskadj_momentum", "lowvol_uptrend"):
        mod = importlib.import_module(f"research_{strat}")
        out = tmp / f"run_{strat}"
        rc = mod.main(["--lake", str(lake), "--start", ds[S].isoformat(), "--end", ds[LAST].isoformat(), "--out", str(out), "--execute"])
        assert rc == 0
        res[strat] = {f: sha(out / f) for f in ("trades.json", "daily.json", "equity_curve.json", "blocked.json")}
        res[strat]["n_trades"] = len(json.loads((out / "trades.json").read_text()))
        # live adapter: one decide per session, journal and state
        pkg = importlib.import_module(f"stockbot.strategies.{strat}")
        cls = getattr(pkg, "RiskAdjMomentumStrategy" if strat == "riskadj_momentum" else "LowVolUptrendStrategy")
        pol = getattr(pkg, "TrailingAtr3Floor8" if strat == "riskadj_momentum" else "LvTrailingAtr3Floor8")
        book = Book.from_strategies([cls(pkg.SPEC)], extra_policies=[pol()])
        store = StateStore(tmp / f"state_{strat}.db")
        store.initialise(1_000_000.0)
        conn = open_lake(lake)
        ad = LiveAdapter(store, conn, book.strategies, book.policies, load_shared_config(), EventData(sectors=SectorLookup(), asm_ranges={}))
        # start the live state one session before S, then every session to LAST
        ad.process(ds[S - 1])
        for d in ds[S:LAST + 1]:
            ad.process(d)
        rows = store._con.execute("select kind, session, key, payload from journal order by seq").fetchall()
        res[strat]["journal_sha"] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        res[strat]["journal_rows"] = len(rows)
        res[strat]["state_sha"] = hashlib.sha256(store.load().to_json().encode()).hexdigest()
        store.close()
    Path(out_json).write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps(res, indent=1, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])

"""Access to the frozen golden results under tests/golden (written by docs/restructure/tools/freeze_*.py while the old code still existed)."""
import gzip
import hashlib
import json
from functools import lru_cache
from pathlib import Path

GOLD = Path(__file__).resolve().parents[1] / "golden"


def _verified(name: str) -> bytes:
    raw = (GOLD / name).read_bytes()
    sums = dict(reversed(line.split("  ", 1)) for line in (GOLD / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line.strip())
    assert hashlib.sha256(raw).hexdigest() == sums[name], f"{name} does not match SHA256SUMS: a frozen golden file was changed"
    return raw


@lru_cache(maxsize=1)
def legacy() -> dict:
    """The frozen answers of the old code (heat caps, fill-time sizing, corporate actions, entry bar, path_sim, cost model, strategy_config.yaml)."""
    return json.loads(gzip.decompress(_verified("legacy_equivalence.json.gz")).decode("utf-8"))

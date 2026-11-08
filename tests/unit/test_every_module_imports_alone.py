"""Every stockbot module (and every legacy module still in the tree) must import in a fresh interpreter, in any order (guards against circular imports
created by moving modules out of a package whose __init__ imported its siblings)."""
import pkgutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _modules():
    names = []
    for pkg in ("stockbot", "engine_core"):
        mod = __import__(pkg)
        names.append(pkg)
        names += [m.name for m in pkgutil.walk_packages(mod.__path__, pkg + ".") if not m.name.endswith(".main")]
    return sorted(set(names))


def _try(name):
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, r'{ROOT}'); import {name}"], capture_output=True, text=True, timeout=120)
    return name, r.returncode, r.stderr.strip().splitlines()[-1:] 


def test_each_module_imports_in_a_fresh_interpreter():
    with ThreadPoolExecutor(max_workers=4) as ex:
        bad = [(n, e) for n, rc, e in ex.map(_try, _modules()) if rc != 0]
    assert not bad, bad

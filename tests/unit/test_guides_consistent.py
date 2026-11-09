"""The two owner guides (docs/guides/CODEBASE_GUIDE.md, docs/guides/DATA_GUIDE.md) must stay consistent with the repository and with the database.

Offline checks (always run):
  * every package and module under stockbot/ and every file in scripts/ is named in CODEBASE_GUIDE.md;
  * every repository path named in either guide (a backticked token that looks like a path) exists, except the paths that only exist after a first run (``RUNTIME_PATHS``);
  * every table, view and trigger listed in docs/guides/data_catalogue.md (machine-measured from sqlite_master) is described in DATA_GUIDE.md;
  * the required number of Mermaid diagrams is present and each is followed by an explanation.
Env-gated (STOCKBOT_DATA_TESTS=1, read-only on the real lake): every table, view, trigger and named index in sqlite_master is named in DATA_GUIDE.md.
"""
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "docs" / "guides"
CODE = GUIDES / "CODEBASE_GUIDE.md"
DATA = GUIDES / "DATA_GUIDE.md"
CATALOGUE = GUIDES / "data_catalogue.md"
MIN_DIAGRAMS = {CODE: 8, DATA: 6}

# paths that are created by running something (or are local-only and git-ignored), so a clean clone does not have them
RUNTIME_PATHS = {"state", "state/", "state/live_state.db", "state/tickets", "state/tickets/", "logs", "logs/", "finsight.db", "finsight.db-wal", "finsight.db-shm",
                 "ui/node_modules", "ui/node_modules/", "ui/dist", "ui/dist/", "data/db", "data/db/", "data/ingestion", "data/ingestion/", "backtest/bifurcated_scraper",
                 "backtest/bifurcated_scraper/", "backtest/outputs/audit.json", ".env", "backtest/outputs/candidate_trades.csv", "backtest/outputs/pending_asm_gsm_matches.csv"}
RUNTIME_PATTERNS = (re.compile(r"^tickets_.*\.json$"), re.compile(r"^[\w./-]*YYYY[\w./-]*$"))
EXTS = (".py", ".md", ".yaml", ".yml", ".csv", ".json", ".sql", ".txt", ".npz", ".ini", ".ts", ".tsx", ".gz", ".db", ".sha256", ".docx")
TOKEN = re.compile(r"`([^`\n]+)`")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", "dist"}


def _text(p: Path) -> str:
    assert p.exists(), f"{p.relative_to(ROOT)} does not exist"
    return p.read_text(encoding="utf-8")


def _all_files() -> set:
    out = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            out.add(f)
    return out


def path_like_tokens(text: str) -> list:
    """Backticked tokens that look like repository paths: letters, digits, _ . / - only, and either a slash or a known file extension."""
    out = []
    for tok in TOKEN.findall(text):
        t = tok.strip()
        if not re.fullmatch(r"[\w./\-]+", t) or t.startswith(("http", ".", "stockbot.")) or t.endswith("..."):    # "stockbot.x.y" is a dotted module name, not a path
            continue
        if "/" in t or t.lower().endswith(EXTS):
            out.append(t)
    return out


def missing_paths(text: str, names: set) -> list:
    bad = []
    for t in sorted(set(path_like_tokens(text))):
        if t in RUNTIME_PATHS or any(p.match(t) for p in RUNTIME_PATTERNS):
            continue
        if "/" in t:
            if not (ROOT / t.rstrip("/")).exists():
                bad.append(t)
        elif t not in names:
            bad.append(t)
    return bad


def stockbot_packages() -> list:
    return sorted(".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "stockbot").rglob("__init__.py") if "__pycache__" not in p.parts)


def stockbot_modules() -> list:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "stockbot").rglob("*.py") if "__pycache__" not in p.parts and p.name != "__init__.py")


def mermaid_blocks(text: str) -> list:
    """(diagram source, the first non-blank line after the closing fence) for every ```mermaid block."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        if lines[i].strip() == "```mermaid":
            j = i + 1
            while j < len(lines) and lines[j].strip() != "```":
                j += 1
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            out.append(("\n".join(lines[i + 1:j]), lines[k] if k < len(lines) else ""))
            i = j
        i += 1
    return out


def catalogue_objects() -> dict:
    """{'table': [...], 'trigger': [...], 'view': [...]} read from section 1 of the machine-measured catalogue (rows '| type | name | table |')."""
    out = {"table": [], "view": [], "trigger": [], "index": []}
    for m in re.finditer(r"^\| (table|view|trigger|index) \| (\S+) \| (\S+) \|$", _text(CATALOGUE), re.M):
        out[m.group(1)].append(m.group(2))
    return out


# ------------------------------------------------------------------------------------------------------------------------------ offline
def test_the_guides_exist_and_are_not_stubs():
    for p in (CODE, DATA, CATALOGUE):
        assert len(_text(p).splitlines()) > 100, f"{p.name} is suspiciously short"


def test_every_stockbot_package_is_named_in_the_codebase_guide():
    t = _text(CODE)
    missing = [p for p in stockbot_packages() if f"`{p}`" not in t and f"`{p.replace('.', '/')}/`" not in t]
    assert not missing, f"packages missing from CODEBASE_GUIDE.md: {missing}"


def test_every_stockbot_module_is_named_in_the_codebase_guide():
    t = _text(CODE)
    missing = [m for m in stockbot_modules() if f"`{Path(m).name}`" not in t and f"`{m}`" not in t]
    assert not missing, f"modules missing from CODEBASE_GUIDE.md: {missing}"


def test_every_script_is_named_in_the_codebase_guide():
    t = _text(CODE)
    scripts = [p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts").rglob("*.py") if "__pycache__" not in p.parts]
    missing = [s for s in scripts if f"`{Path(s).name}`" not in t and f"`{s}`" not in t]
    assert not missing, f"scripts missing from CODEBASE_GUIDE.md: {missing}"


@pytest.mark.parametrize("guide", [CODE, DATA], ids=lambda p: p.name)
def test_every_path_named_in_a_guide_exists(guide):
    bad = missing_paths(_text(guide), _all_files())
    assert not bad, f"{guide.name} names paths that do not exist: {bad}"


def test_every_object_in_the_measured_catalogue_is_described_in_the_data_guide():
    t, objs = _text(DATA), catalogue_objects()
    assert objs["table"], "the catalogue lists no tables (format changed?)"
    missing = [n for kind in ("table", "view", "trigger") for n in objs[kind] if n not in t and not n.startswith("sqlite_")]
    missing += [n for n in objs["index"] if not n.startswith("sqlite_autoindex") and n not in t]
    assert not missing, f"objects missing from DATA_GUIDE.md: {missing}"


@pytest.mark.parametrize("guide", [CODE, DATA], ids=lambda p: p.name)
def test_the_required_diagrams_are_present_and_explained(guide):
    blocks = mermaid_blocks(_text(guide))
    assert len(blocks) >= MIN_DIAGRAMS[guide], f"{guide.name}: {len(blocks)} diagrams, at least {MIN_DIAGRAMS[guide]} required"
    for src, after in blocks:
        assert src.split("\n", 1)[0].split()[0] in ("flowchart", "sequenceDiagram", "erDiagram", "stateDiagram-v2", "graph"), src[:40]
        assert after.strip() and not after.startswith(("#", "```", "|")), f"a diagram in {guide.name} has no explanation under it: {src[:60]!r}"


def test_the_checker_itself_detects_a_missing_path_and_a_missing_object():
    """Guards the checks above: seeded problems must be reported."""
    assert missing_paths("see `stockbot/engine/does_not_exist.py` and `nothing_here.py`", _all_files()) == ["nothing_here.py", "stockbot/engine/does_not_exist.py"]
    assert missing_paths("see `stockbot/engine/decide.py`, `state/live_state.db`, `shared.yaml`", _all_files()) == []
    assert mermaid_blocks("```mermaid\nflowchart LR\n  a-->b\n```\n\nText.\n")[0][1] == "Text."


# ------------------------------------------------------------------------------------------------------------------------------ env-gated
@pytest.mark.skipif(os.environ.get("STOCKBOT_DATA_TESTS") != "1", reason="needs STOCKBOT_DATA_TESTS=1 and the real database")
def test_every_object_in_sqlite_master_is_described_in_the_data_guide():
    from stockbot.data.lake import open_lake

    con = open_lake()
    try:
        rows = con.execute("select type, name from sqlite_master where name not like 'sqlite_%'").fetchall()
    finally:
        con.close()
    t = _text(DATA)
    missing = [f"{k} {n}" for k, n in rows if n not in t]
    assert rows and not missing, f"in sqlite_master but not in DATA_GUIDE.md: {missing}"

"""Builds docs/guides/data_guide.html (one self-contained page) from docs/guides/data_guide_data.json, the measured catalogue export docs/guides/data_catalogue.json
and docs/guides/data_guide_template.html. Sibling of ``guide_html`` (the codebase guide); it reuses that module's JSON embedding and slots.

Offline, standard library only, touches no database. The HTML is a pure function of the three input files: ``build(data, template, catalogue)`` returns the same text every time
(the footer date and commit come from the JSON "meta", written by ``--stamp``). The page shows every measured number with the catalogue's measurement date.

  py scripts/build_data_guide_html.py            rebuild the HTML
  py scripts/build_data_guide_html.py --stamp    first set meta.built_at (today) and meta.built_from_commit (git HEAD) in the JSON, then rebuild
To refresh the measured numbers: py scripts/gen_data_catalogue.py --json --json-only (read-only on the lake; about five minutes), then rebuild.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from stockbot.config.paths import repo_root
from stockbot.data_checks.guide_html import DATA_SLOT, FOOT_SLOT, _esc, _git_head, embed_json


_URL = re.compile(r"https?://[^\s\"',)]*", re.I)


def strip_urls(o):
    """The measured sample rows contain real file URLs (an NSE archive address in a ``url`` column). The page must load and name nothing external, so they become a note."""
    if isinstance(o, str):
        return _URL.sub("(a web address, not shown)", o)
    if isinstance(o, list):
        return [strip_urls(x) for x in o]
    if isinstance(o, dict):
        return {k: strip_urls(v) for k, v in o.items()}
    return o


def build(data_path: Path, template_path: Path, catalogue_path: Path) -> str:
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    data["measured"] = strip_urls(json.loads(Path(catalogue_path).read_text(encoding="utf-8")))
    tpl = Path(template_path).read_text(encoding="utf-8")
    if tpl.count(DATA_SLOT) != 1 or tpl.count(FOOT_SLOT) != 1:
        raise SystemExit(f"template must contain {DATA_SLOT} and {FOOT_SLOT} exactly once")
    m = data["meta"]
    footer = (f"Built {_esc(m['built_at'])} from commit {_esc(m['built_from_commit'])}. Numbers measured {_esc(data['measured']['meta']['measured_at'])} "
              f"from the database file modified {_esc(data['measured']['meta']['db_modified'])}. Example data is made up.")
    return tpl.replace(DATA_SLOT, embed_json(data)).replace(FOOT_SLOT, footer)


def main(argv: Optional[Sequence[str]] = None) -> int:
    root = repo_root()
    g = root / "docs" / "guides"
    ap = argparse.ArgumentParser(description="Build docs/guides/data_guide.html from data_guide_data.json, data_catalogue.json and the template (offline).")
    ap.add_argument("--data", default=str(g / "data_guide_data.json"))
    ap.add_argument("--catalogue", default=str(g / "data_catalogue.json"))
    ap.add_argument("--template", default=str(g / "data_guide_template.html"))
    ap.add_argument("--out", default=str(g / "data_guide.html"))
    ap.add_argument("--stamp", action="store_true", help="set meta.built_at (today) and meta.built_from_commit (git HEAD) in the JSON first")
    a = ap.parse_args(argv)
    if a.stamp:
        p = Path(a.data)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["meta"]["built_at"], d["meta"]["built_from_commit"] = date.today().isoformat(), _git_head(root)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    text = build(Path(a.data), Path(a.template), Path(a.catalogue))
    Path(a.out).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out} ({len(text):,} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

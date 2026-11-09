"""Generates docs/restructure/OLD_STRATEGY_REFERENCE.md from CONFIG_KEYS.csv and strategy_config.yaml (values copied, never changed)."""
import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
LEG = yaml.safe_load(open(ROOT / "strategy_config.yaml", encoding="utf-8"))
rows = list(csv.DictReader(open(ROOT / "docs/restructure/CONFIG_KEYS.csv", encoding="utf-8", newline="")))


def val(k):
    s, key = k.split(".", 1)
    return LEG[s][key]


L = ["# Old strategy reference (recovery record)", "",
     "Everything that is specific to the OLD strategy (or undecided) and therefore is not in the shared config (`stockbot/config/shared.yaml`). Values are copied unchanged from `strategy_config.yaml` at tag `pre-restructure`.",
     "Until Phase 10 `strategy_config.yaml` itself stays in the tree (the old pipeline and the golden checks still read it through `stockbot/config/legacy_loader.py`); after Phase 10 recover it with `git show pre-restructure:strategy_config.yaml`.", "",
     "Recovery: tag `pre-restructure`; path `strategy_config.yaml` (all keys); code paths are listed per item.", ""]
for title, cls, why in (("Old-strategy keys (leave the shared config; become the old strategy's own parameters)", "old-strategy", ""),
                        ("Undecided (macro regime, Q4): stay in strategy_config.yaml; decided in Phase 6 Part A", "undecided", "")):
    L += [f"## {title}", "", "| key | value | note |", "|---|---|---|"]
    for r in rows:
        if r["class"] == cls:
            L.append(f"| `{r['key']}` | `{val(r['key'])}` | {r['note']} |")
    L.append("")
L += ["## Per-strategy values decided at the Stop-1 review (recorded unchanged)", "",
      f"- Q3 `risk.min_rr_ratio` = {val('risk.min_rr_ratio')}; `risk.max_rr_cap` = {val('risk.max_rr_cap')}; `execution.min_rr_at_fill` = {val('execution.min_rr_at_fill')} (per-strategy parameters; a strategy may have no target).",
      f"- Q10 `trade_management.binary_event_block_days` = {val('trade_management.binary_event_block_days')} (the mechanism - is an earnings/corporate-action event within N days, known as of the date - is shared; whether to block entries is a per-strategy parameter; a meeting date counts as known only after its intimation timestamp).",
      "- Q11 `gates.*` and Q8 `paper_criteria.*` are shared validation / acceptance config, not per-strategy: see `shared.yaml` (`validation_gates`, `paper_criteria`) and `CONFIG_DIFF.md`.", "",
      "## Removed code / files (path at tag `pre-restructure`)", "",
      "| item | removed in | what it did | note |", "|---|---|---|---|",
      "| `authorize_live.py` | Phase 4.2 | validated `audit.json` (clean tree, config hash, `audit.sha256`, all pass gates) and wrote `authorized_deployment.json` with the HEAD SHA, then committed it | git-SHA authorization lock dropped for now; the live authorization design returns in the strategy phase |",
      "| `authorized_deployment.json` | Phase 4.2 | the authorized SHA record | same |",
      "| `live_runner/git_lock.py` | Phase 4.2 | `verify_git_lock()` at startup and before each scheduled run (exit if HEAD differs from the authorized SHA, allowing one auth-file-only commit); `read_authorized_info()` for the health endpoint and the paper start date | health keeps its keys with empty values; `scripts/paper_report.py` has a local stub returning no authorization date |",
      "| `tests/unit/test_phase4_lock.py` (7 tests) | Phase 4.2 | tests of the two items above | see `REMOVED_TESTS.md` |", "",
      "More rows are added at each phase that removes old-strategy code (Phase 5 stops, Phase 6 entry filters / lifecycle exits / screener gates 6-7, Phase 10 deletions)."]
(ROOT / "docs/restructure/OLD_STRATEGY_REFERENCE.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("rows:", sum(1 for r in rows if r["class"] in ("old-strategy", "undecided")))

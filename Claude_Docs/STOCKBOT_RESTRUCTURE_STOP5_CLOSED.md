# STOP 5 closed

**Merged by explicit instruction despite an incomplete clean-clone test.** The owner explicitly told me to merge after the real-database part of the clean-clone test was killed twice for low memory. This is recorded here on purpose.

## Clean-clone test (fresh clone of pushed `restructure` tip 2ba83f5, STOCKBOT_DB = real lake, read-only)
- Unit and integration suite: 494 passed, 1 skipped, 0 failed.
- `check_all.py --data --final` steps: G1 495 passed, G3 2 passed, G5 14 passed, G6 72 passed.
- Last step, G2 `tests/data_integrity` (real database): **killed by Claude Code for low system memory, twice, at about 59 percent. No verdict.** Not a test failure; cause not diagnosed. Not re-run in the clone. (G2 earlier passed in the main working tree: 616 passed, 0 skipped.)
- `git status --ignored` was checked in the main tree, not in the clone: ignored items are caches, logs, ui build and node_modules, the lake and its -shm/-wal, data/db, data/ingestion, backtest/bifurcated_scraper, backtest/outputs/audit.json. The clone's passing runs read none of them; the G2 part is the unverified remainder.

## Done
- PRE_LIVE_LIST: item 11 added (EQ-only lake, re-entry after absences); note on item 7 (live -> validation edge to disappear when routers are reworked). Commit 680209c.
- regime_filter / regime_gates kept as provenance under scripts/provenance/regime.
- Merged `restructure` into `master` with a merge commit (no squash): 9298770. Tag `post-restructure` (annotated) -> 9298770. Both pushed.
- `main` branch not touched: origin/main = a012cf4 (2026-10-16, "authorize live deployment"); it is an ancestor of master (master 83 commits ahead, main has nothing master lacks, before this merge).

## On master after the merge
- G1: 494 passed, 1 skipped. G3: 2 passed.
- G4: finsight.db sha256 dcade465...ceb752, mtime 2026-11-08 12:38:02, size 3,432,767,488: unchanged.
- Tag `pre-restructure` still points to ca11e32 (annotated), commit 41b22ce, as before.

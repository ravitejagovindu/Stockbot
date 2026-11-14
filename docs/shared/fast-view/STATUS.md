# fast-view status

Done (all steps; see Claude_Docs/FAST-VIEW_REPORT.md)
- asof_memory.py, switch in AsOfView.__new__, fetch primitives in asof.py, 64 fixture tests, diff harness.
- Proofs 1-4 pass: 0 differences over 444 real sessions; 12-month outputs byte-identical; golden 120 and real-lake tests pass under the memory view.
- Peak RSS ~1 GB. Engine full run 3312 s (target 45 min MISSED). Baseline 1340 s (met).
- G1 943 passed (+1 guide row fixed), full G2 1073 passed, G3 2 passed, DB sha256 unchanged.

Next
- Nothing; STOPPED for owner decisions (report, Decisions needed).

Blockers
- Engine speed target: remaining time is pandas overhead in adtv and adjusted_bars (logic fixed by the brief).

## Running with the fast view
The default is still the SQL view. The memory view is chosen by one environment variable, `STOCKBOT_VIEW=memory`. Every run records which view it used (`asof_view` in the run manifest, and a line `asof_view: ...` at the start of the run).

Windows cmd:
```
set STOCKBOT_DB=F:\Projects\Ravi\StockBot\finsight.db
set STOCKBOT_VIEW=memory
py -3 scripts\research_near_52w_high.py --start 2016-01-01 --end 2026-09-30 --out OUTDIR --execute
py -3 scripts\baseline_matched_random_near_52w_high.py --run-dir OUTDIR --out-dir BASEDIR
```
Git Bash:
```
export STOCKBOT_DB='F:\Projects\Ravi\StockBot\finsight.db'
export STOCKBOT_VIEW=memory
py -3 scripts/research_near_52w_high.py --start 2016-01-01 --end 2026-09-30 --out OUTDIR --execute
py -3 scripts/baseline_matched_random_near_52w_high.py --run-dir OUTDIR --out-dir BASEDIR
```
Leave `STOCKBOT_VIEW` unset (or `sql`) for the SQL view. The live path refuses the memory view with an error.

What to expect, per process:
- Engine-only full 2016-2026 run: about 55 minutes (SQL view: about 4 hours).
- Matched-random baseline: about 22 minutes (SQL view: about 2 hours).
- First read of the lake file when it is not in the disk cache: up to 16 minutes extra, once per process.
- Memory: about 1 GB per process (peak 995 MB measured).
- Run at most two at once.

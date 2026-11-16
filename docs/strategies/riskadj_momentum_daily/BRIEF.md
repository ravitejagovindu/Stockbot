# riskadj_momentum_daily: brief

Branch `riskadj_momentum_daily` (from origin/master e2a6a82). Family `family_batch4`, K = 1. **BUILD STOPPED at step 3 (see STATUS.md): the engine cannot give a strategy its own exit history without a shared change.** Nothing was built or run; no shared file was edited; no real-lake read other than the sha256 check.

Intended rule: riskadj_momentum with every session a signal session, plus a re-entry cooldown (a symbol closed by STOP_HIT is not proposed again until 21 sessions have passed after the exit session). The owner's step list is the specification; no number is changed.

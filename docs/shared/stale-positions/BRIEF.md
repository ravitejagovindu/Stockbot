# stale-positions: symbol links and the no-bars exit (task text, condensed)

BRANCH: stale-positions   REPORT: Claude_Docs/STALE_POSITIONS_REPORT.md   INVENTORY (earlier step): Claude_Docs/STALE_SYMBOLS_INVENTORY.md

Rules of the work: plain commits, no Co-Authored-By / Claude-Session / "Generated with" lines. finsight.db read-only (sha256 dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752 before and after; the lake is never written).
No strategy folder, pre-registration, ledger row or stored result is touched (one named exception: B5). Registered results stay as recorded; nothing is re-run to update them. List every shared file touched and why.
Tests first where practical. Numbers are FIXED.

A. RENAMES: link the names (data layer)
 A1. data/reference/symbol_links.csv, built by a script from isin_symbol_map. A pair is included ONLY if: same ISIN, boundary type pure_rename, the new symbol's first bar is 1 to 5 sessions after the old symbol's last bar,
     no overlapping bars, boundary ratio (after the logged split/bonus factor) between 0.80 and 1.25. Chains resolve to the latest symbol. Everything else goes to symbol_links_not_linked.csv with the reason; none of it is linked.
     The report explains what "other" means in the map.
 A2. In the as-of views (SQL and memory, ONE shared implementation) a linked stock is ONE symbol under its latest name: bars, corporate actions (rows under either name or a feed_symbol note; a boundary-date action applied once),
     listing age, ADTV, eligibility, sector lookup. Point in time (only rows up to D). Applied on read. One switch: shared.yaml data.symbol_links_enabled: true.
 A3. Proof: (i) switch off = every existing parity test, the 120 golden as-of samples and the digest tests byte-identical to master; (ii) switch on: the same for every symbol NOT in symbol_links.csv (diff harness, >= 400 sessions);
     (iii) per linked pair: adjusted close continuous across the boundary, no duplicated or dropped session, actions applied once (PHILIPCARB/PCBL 2018-04-19 split is a named test), listing age carries over;
     (iv) SQL view = memory view with the switch on; (v) list any golden sample that changes and why.

B. NO BARS FOR 20 SESSIONS: close and COUNT (engine; one code path for backtest, paper and live)
 B1. A held position whose symbol (after linking) has had no bar for 20 consecutive sessions of the engine's calendar is closed on that 20th session at its LAST AVAILABLE CLOSE, normal exit slippage and costs, reason SYMBOL_NO_BARS,
     stale_exit: true. Data up to that session only. Slot, cash, risk released from the next session. Nothing re-opens. Number: shared.yaml engine.stale_exit_sessions: 20.
 B2. These trades are USABLE (gates, T1, T2, equity curve), not like excluded_ca.
 B3. Reporting (non-gating; shared gate/evaluate output and manifest): number of stale_exit trades, their list, total net P&L, and a STRESS line (every gate recomputed with each stale exit sold at 0.5 x its last close;
     reporting.stale_exit_stress_factor: 0.5), labelled "stress, not a gate".
 B4. The shared simulate_ticket applies the same closure; such draws are filled draws.
 B5. The strategy-side copies in scripts/*riskadj_momentum*.py may be edited ONLY to stay consistent with B1-B4; say exactly what changed; do not run them on the real lake.
 B6. State the effect on shared_config_hash; the validation_gates hash e9b6407f... must NOT change.

C. LIVE: the same decision is an explicit item in the session output ("position X: no bars for 20 sessions; closed in the book at the last close; check the holding manually (rename, merger, suspension, series change)"). Tested. No silent handling.

D. TESTS (fixture lakes): terminal symbol; gap that resumes after 30 sessions; 19 missing sessions; closure frees the slot; renamed symbol held across the rename; renamed symbol's eligibility not reset; baseline draw closure; stress arithmetic; live item;
   sql = memory; a run with no linked and no stale symbol is identical to master.

E. EFFECT (descriptive only; no engine run, no ledger, no conclusion changed): per stored run (near_52w_high 4B, pullback_uptrend run1, short_term_reversal run1, riskadj_momentum run1) which stored trades the rule would have closed and when,
   and which involve a linked symbol; symbol-sessions whose eligibility changes with linking on, per year.

FINISH: guides only where tests require (regenerate HTML with the build scripts); G1, full G2, G3, DB hash. Report; push branch stale-positions. STOP.

# stale-positions status

Done
- A1 builder + data/reference/symbol_links.csv (41 pairs, 40 stocks) and symbol_links_not_linked.csv.
- A2 stockbot/data/symbol_links.py; the link logic is in AsOfView (one implementation), the memory view replaces only the `_*_physical` fetch primitives; sector lookup follows the link.
- B1-B4 engine: stockbot/engine/stale.py, stepping.close_no_bars, decide (flag item for live), path.simulate_ticket; B3 reporting in the shared gate evaluation and the run manifest.
- B5 edits in the three riskadj_momentum scripts (see the report).
- Tests: tests/unit/test_stale_positions.py. Proofs and section E: scripts/stale_positions_proofs.py.

Next (done)
- Nothing; report written, branch pushed.

Blockers
- none

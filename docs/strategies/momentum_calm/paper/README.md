# momentum_calm: paper setup (2026-11-20)

Status `paper` is a separate spec object, `stockbot.strategies.momentum_calm.paper.PAPER_SPEC` = the registered `SPEC` with only `status` changed. The registered `SPEC` (status `research`, hash `d215b84c...cbad55`, family_batch7 ledger rows) is untouched. The registered verdict stays "not demonstrated".

Fixed settings (owner): monthly signals, first possible signal the first trading day of December 2026; account 200,000 INR, forward-only, no deposits or withdrawals, idle cash earns nothing; risk 1.0% per trade, 12 positions, shared engine limits unchanged; `STOCKBOT_NON_EQ=held`, `STOCKBOT_RISK_PCT` not set; buy EQ only (never BE/BZ/BL), held positions may be held or sold; paper review marks: drawdown below 35%, at least 30 closed trades; daily job 19:30 IST, the paper step after a successful data step, sealed data only.

Files here: `dryrun_<date>.csv` (signal list), `dryrun_<date>_blocked.csv`, `dryrun_summary.md` (read-only dry runs, `scripts/momentum_calm_paper_dryrun.py`). Full account of the set-up: `Claude_Docs/PAPER_SETUP_REPORT.md`.

"""docs/restructure/tools/gen_inventory.py — Phase 1 (analysis only): builds INVENTORY.csv and ARCHITECTURE_CURRENT.md from the code.
Classification is the RULES table below (first match wins). Lines, imported-by and tests-covering are computed from the tree."""
import ast, collections, csv, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KEEP, MOVE, REWRITE, OLD, DELETE, PROV, UND = "keep-as-is", "move", "rewrite", "old-strategy", "delete", "provenance", "undecided"
# (regex, category, target, reason). Open questions are numbered Qn and listed in UNDECIDED.md
RULES = [
 (r"^strategy_config\.yaml$", REWRITE, "config (split)", "split into shared config + old-strategy keys (see CONFIG_KEYS.csv)"),
 (r"^config\.py$", REWRITE, "config", "loader becomes typed shared config + strategy spec schema"),
 (r"^logging_config\.py$", MOVE, "config", "shared logging setup"),
 (r"^(authorize_live\.py|authorized_deployment\.json|live_runner/git_lock\.py)$", DELETE, "-", "git-SHA authorization lock; dropped for now (Phase 4.5); design returns in the strategy phase; recorded in OLD_STRATEGY_REFERENCE"),
 (r"^(fix_blocker1_index_data|fix_blocker2_shares_outstanding)\.py$", PROV, "scripts/provenance", "one-off data set-up (index/VIX load; the shares_outstanding snapshot behind KI-001)"),
 (r"^verify_db\.py$", DELETE, "-", "hard-coded-path ad-hoc row counter; superseded by data_checks"),
 (r"^(generate_confidence_report\.py|confidence_report\.md)$", OLD, "-", "report of the old paper-trading strategy (audit.json based)"),
 (r"^(BRD\.docx|Architecture_Spec\.docx|StockBot_DetailedImpl\.md)$", UND, "docs/archive", "Q1: original specs of the old design; keep as archive or drop?"),
 (r"^README\.md$", REWRITE, "docs", "rewrite after the restructure (Phase 10)"),
 (r"^enhancements/", UND, "docs/archive", "Q1: old phase plans"),
 (r"^(requirements\.txt|pytest\.ini|\.gitignore|\.env\.template)$", KEEP, "root", "project plumbing"),
 # engine_core
 (r"^engine_core/adjustments\.py$", MOVE, "data", "corporate-action price adjustment; generic; the as-of view uses it"),
 (r"^engine_core/indicators\.py$", MOVE, "data", "generic SMA/RMA/ATR/Donchian functions; no strategy logic (checked)"),
 (r"^engine_core/costs\.py$", MOVE, "risk", "cost model; shared"),
 (r"^engine_core/corporate_action_events\.py$", MOVE, "engine", "generic handling of corporate actions on open positions"),
 (r"^engine_core/(max_t_bootstrap|prereg_lock)\.py$", MOVE, "validation", "must-keep validation machinery"),
 (r"^engine_core/trade_metrics\.py$", MOVE, "validation", "trade R and portfolio metrics (R definitions shared with risk: Q2)"),
 (r"^engine_core/entry_filters\.py$", OLD, "-", "trend/breakout/pullback filters and RS ranking: all old strategy"),
 (r"^engine_core/risk_sizing\.py$", REWRITE, "risk (generic) / old-strategy (stops, target)", "generic: sizing, heat and sector caps; old: ATR/Donchian stop, 52-week target, R:R gate"),
 (r"^engine_core/universe_screener\.py$", REWRITE, "universe (generic) / old-strategy (gates 6,7)", "generic: price/ADTV/age/fund filters (market-cap parked); old: RS rank, volume breakout"),
 (r"^engine_core/lifecycle_rules\.py$", REWRITE, "engine (rescale, fill) / old-strategy (advance_one_bar rules)", "state machine, time decay, breakeven, trailing, ratchet, partials are old-strategy exit policy; rescale_for_action generic; plan_entry_fill generic but contains the min R:R gate (Q3)"),
 (r"^engine_core/position_lifecycle\.py$", REWRITE, "live / engine", "DB-bound manager mixing generic corporate-action handling with old exits"),
 (r"^engine_core/candidate_builder\.py$", REWRITE, "data (as-of view) / old-strategy", "builds candidate dicts with strategy-specific lookbacks"),
 (r"^engine_core/(regime_filter|regime_gates)\.py$", UND, "engine or strategy", "Q4: macro Nifty/VIX kill switch: shared or per strategy (Phase 6 Part A)"),
 (r"^engine_core/(account_ledger|equity|position_service)\.py$", REWRITE, "live", "paper/live state helpers bound to the ORM; move to the live state store"),
 (r"^engine_core/mode\.py$", MOVE, "config", "runtime mode resolution"),
 (r"^engine_core/preflight\.py$", MOVE, "data_checks", "adjustment spot-check; uses sector_map"),
 (r"^engine_core/sector_map\.py$", MOVE, "risk", "sector lookup used by heat caps"),
 (r"^engine_core/analytics_loop\.py$", REWRITE, "live", "closed-trade analytics / decay report tied to the old paper tables"),
 (r"^engine_core/__init__\.py$", DELETE, "-", "the namespace package replaces it"),
 # backtest
 (r"^backtest/no_network\.py$", KEEP, "backtest", "network guard (must-keep)"),
 (r"^backtest/simulator\.py$", REWRITE, "backtest", "loop will call engine.decide; old gates inside leave"),
 (r"^backtest/run_backtest\.py$", REWRITE, "backtest + scripts wrapper", "runner"),
 (r"^backtest/path_sim\.py$", UND, "backtest or validation", "Q5: single-position forward simulation reused by the random baseline"),
 (r"^backtest/exclusions\.py$", MOVE, "universe", "fail-closed ASM/GSM + earnings exclusions (generic)"),
 (r"^backtest/audit_generator\.py$", OLD, "-", "gate audit.json of the old strategy"),
 (r"^backtest/run_candidate_simulations\.py$", OLD, "-", "runner of the six pre-registered configs"),
 (r"^backtest/pre_registered_configs\.yaml$", PROV, "validation/ledger", "defines the rejected CFG-01..06; kept with the ledger"),
 (r"^backtest/bifurcated_scraper/__init__\.py$", DELETE, "-", "package of the two invalid scrapers"),
 (r"^backtest/bifurcated_scraper/", DELETE, "-", "stub PDF scraper / scraper using dividend ex-dates (invalid, F8); replaced by the collector and snapshot scripts"),
 (r"^backtest/outputs/(trial_ledger|trial_ledger_exploratory)\.csv$", PROV, "validation/ledger", "trial ledgers: data to keep (hash chain verified before/after the move)"),
 (r"^backtest/outputs/(selection_decision\.json|audit\.sha256)$", PROV, "validation/ledger", "record of the six-config selection"),
 (r"^backtest/outputs_v1_stale/", DELETE, "-", "stale"),
 (r"^backtest/outputs/pending_asm_gsm_matches_", DELETE, "-", "PENDING templates, no verified rows"),
 (r"^backtest/outputs(_recomputed_net)?/", UND, "validation/ledger or delete", "Q6: per-config trades/equity of the six rejected configs"),
 (r"^backtest/__init__\.py$", KEEP, "backtest", "package"),
 # data
 (r"^data/ingestion/pit_shares\.py$", PROV, "data (not used)", "F2b closed; NOT USED"),
 (r"^data/ingestion/", MOVE, "data/ingestion", "ingestion tooling (must-keep)"),
 (r"^data/db/(models\.py|schema\.sql)$", REWRITE, "data (lake) / live (state)", "ORM mixes lake tables with paper/live state tables"),
 (r"^data/db/connection\.py$", REWRITE, "data", "becomes read-only lake connection + separate state connection"),
 (r"^data/db/migration_", PROV, "data/db", "applied migrations; history"),
 (r"^data/quality_checker\.py$", MOVE, "data_checks", "quality checks"),
 (r"^data/reference/README_F2b_NOT_USED\.md$|^data/reference/pit_shares_", PROV, "data/reference", "F2b evidence (NOT USED)"),
 (r"^data/reference/", KEEP, "data/reference", "reference data (must-keep: isin_symbol_map, special sessions, fund list, verification set, sector map)"),
 (r"^data/f9/", MOVE, "validation", "F9 power results (must-keep)"),
 (r"^data/(__init__|db/__init__)\.py$", MOVE, "data", "package"),
 # live
 (r"^live_runner/routers/", MOVE, "live/api", "read-only API routers: moved as they are, flagged for rework (Phase 9)"),
 (r"^live_runner/(main|scheduler|idempotency)\.py$", MOVE, "live", "app entry / scheduler / idempotency"),
 (r"^live_runner/pipeline\.py$", REWRITE, "live", "EOD pipeline becomes the thin runner around engine.decide"),
 (r"^live_runner/paper_trader\.py$", REWRITE, "live", "paper fills; re-expressed on the state store"),
 (r"^live_runner/", KEEP, "live", "package"),
 # scripts
 (r"^scripts/(collect_earnings_history|snapshot_asm_gsm|ingest_raw_bhavcopy_range|f2_build_fund_symbols|f2_build_isin_symbol_map|f2_event_evidence|f2_index_gap_fill|f2_index_gap_fill_yahoo|f2_load_corporate_actions)\.py$", MOVE, "data/ingestion", "logic into the package; thin wrapper stays (must-keep)"),
 (r"^scripts/(earnings_coverage|earnings_validate|f2_copy_detector|f2_engine_scan|f2_split_rename_links|f2_verify_engine_path|f2_verify_list|preflight_spot_check)\.py$", MOVE, "data_checks", "verification tooling (must-keep: 58-row set, engine scan)"),
 (r"^scripts/(f9_.*|validate_max_t)\.py$", MOVE, "validation", "F9 power tooling / Max-T validation (must-keep)"),
 (r"^scripts/redesigned_random_baseline\.py$", REWRITE, "validation", "matched-random baseline: uses old-strategy universe gates and exits; to take them from the strategy spec"),
 (r"^scripts/select_candidate\.py$", UND, "validation or old-strategy", "Q7: six-config selection pipeline (writes the trial ledger)"),
 (r"^scripts/paper_report\.py$", UND, "live or old-strategy", "Q8: paper_criteria evaluation"),
 (r"^scripts/daily_health_check\.py$", REWRITE, "live", "health check on the old paper tables"),
 (r"^scripts/(count_candidate_signals|count_executable_entries|generate_stage_by_stage_funnel|diagnose_trades|diagnose_trades_amended|evaluate_selection_hypotheses)\.py$", OLD, "-", "analysis of the old strategy's signals/trades"),
 (r"^scripts/recompute_step3_net_r\.py$", PROV, "scripts/provenance", "F1 net-R recompute of the old outputs"),
 (r"^scripts/run_surveillance_scrapers\.py$", DELETE, "-", "calls the invalid scrapers (F8); replaced by collector + snapshot"),
 (r"^scripts/f2b_", PROV, "scripts/provenance", "F2b NOT USED"),
 (r"^scripts/(f2_eligibility_triage|f2_load_plan|f2_move_dispositions|f2_post_swap_checks|f2_pre2020_compare|f2_swap|f2_validate_staging|f2_volume_continuity|ingest_historical_2018_2019)\.py$", PROV, "scripts/provenance", "one-off F2 swap/audit step; cited by data_audit reports"),
 # tests (travel with their code)
 (r"^tests/fixtures/", KEEP, "tests/fixtures", "fixture lake (must-keep)"),
 (r"^tests/(conftest|__init__)\.py$|^tests/(unit|integration|data_integrity)/__init__\.py$", KEEP, "tests", "plumbing"),
 (r"^tests/(test_run_full_suite\.log|unit/test_baseline_reproducibility\.log)$", DELETE, "-", "stale tracked log"),
 (r"^tests/unit/test_(position_lifecycle|lifecycle_rules|regime_filter|phase1_components|phase2_paper|phase3_backtest|phase4_lock|phase5_paper_tools)\.py$", REWRITE, "travels with its code", "tests the old pipeline/lifecycle; moves or retires with that code (G1 count changes: Q9)"),
 (r"^tests/unit/test_(adjustments|ca_evidence|ca_loader|nse_ca_parser|isin_symbol_map|split_rename_links|securities_master|bhavcopy_range|f2_swap|collect_earnings|snapshot_asm_gsm|pit_shares|copy_detector|corporate_action_hold)\.py$", MOVE, "travels with its code", "data / data_checks tests"),
 (r"^tests/unit/test_(data_quality|raw_only_liquidity|universe_rules_f2|indicators)\.py$", MOVE, "travels with its code", "data / universe tests"),
 (r"^tests/unit/test_(max_t_bootstrap|f6_baseline_and_locks|r_metric)\.py$", MOVE, "validation tests", "validation tests"),
 (r"^tests/unit/test_(backtest_no_network|backtest_isolation|regulatory_barrier|baseline_reproducibility)\.py$", KEEP, "tests", "G3 / network guard / regulatory barrier: keep and re-point"),
 (r"^tests/integration/", REWRITE, "tests (parity)", "sim-vs-live parity tests; the Phase 6 parity test replaces or extends them"),
 (r"^tests/data_integrity/", KEEP, "tests/data_integrity", "env-gated data tests (G2)"),
 # docs
 (r"^docs/restructure/", KEEP, "docs/restructure", "this job"),
 (r"^docs/data_audit/", PROV, "docs/data_audit", "must-keep audit evidence"),
 (r"^docs/(MAXT_VALIDATION\.md|maxt_validation\.json|F9_|F8_|ASM_GSM_SNAPSHOT|EARNINGS_COLLECTION)", KEEP, "docs", "validation / data docs"),
 (r"^docs/(PAPER_RESULT\.json|PAPER_TRADE_CRITERIA\.md|paper_log\.md|STOCKBOT_IMPLEMENTATION_PLAN\.md)$", UND, "docs/archive", "Q1: old paper-trading / implementation docs"),
 (r"^Claude_Docs/", KEEP, "Claude_Docs", "reviewer reports"),
]


def classify(path):
    for rx, c, t, r in RULES:
        if re.search(rx, path):
            return c, t, r
    return UND, "?", "no rule matched"


def main():
    files = [f for f in subprocess.check_output(["git", "ls-files"], text=True, cwd=ROOT).split("\n") if f and not f.startswith("ui/")]
    pyf = [f for f in files if f.endswith(".py")]
    mods = {f[:-3].replace("/", ".").removesuffix(".__init__"): f for f in pyf}
    edges = collections.defaultdict(set)
    for f in pyf:
        m = f[:-3].replace("/", ".").removesuffix(".__init__")
        try:
            t = ast.parse((ROOT / f).read_text(encoding="utf-8"))
        except Exception:
            continue
        for n in ast.walk(t):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                names = [n.module] + [n.module + "." + a.name for a in n.names]
            for x in names:
                p = x
                while p and p not in mods:
                    p = p.rpartition(".")[0]
                if p and p != m:
                    edges[m].add(p)
    rev = collections.defaultdict(set)
    for a, bs in edges.items():
        for b in bs:
            rev[b].add(a)
    rows = []
    for f in files:
        c, t, r = classify(f)
        m = f[:-3].replace("/", ".").removesuffix(".__init__") if f.endswith(".py") else None
        try:
            n = 0 if f.endswith((".docx", ".pdf")) else sum(1 for _ in open(ROOT / f, "rb"))
        except Exception:
            n = 0
        imp = sorted(x for x in rev.get(m, []) if not x.startswith("tests.")) if m else []
        tst = sorted({x.replace(".", "/") + ".py" for x in rev.get(m, []) if x.startswith("tests.") and x.split(".")[-1].startswith("test_")}) if m else []
        rows.append([f, n, c, t, r, ";".join(imp), ";".join(tst)])
    with open(ROOT / "docs/restructure/INVENTORY.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "lines", "category", "target_package", "reason", "imported_by", "tests_covering"])
        w.writerows(rows)
    print(len(rows), dict(collections.Counter(r[2] for r in rows)))
    print("unmatched:", [r[0] for r in rows if r[3] == "?"])
    top = lambda m: m.split(".")[0]
    cross = collections.defaultdict(list)
    for a, bs in edges.items():
        if a.startswith("tests."):
            continue
        for b in bs:
            if top(a) != top(b):
                cross[(top(a), top(b))].append((a, b))
    L = ["# Current import graph", "",
         "Generated by `docs/restructure/tools/gen_inventory.py` from the code at the `pre-restructure` tag. Non-test modules only; same-top-level-package imports omitted.", "",
         "| from | to | module-level edges |", "|---|---|---|"]
    for (a, b), v in sorted(cross.items()):
        L.append(f"| {a} | {b} | {len(v)} |")
    L += ["", "## Edges that matter for the target rules", ""]
    def show(title, pa, pb):
        v = sorted(ab for (x, y), vs in cross.items() if x == pa and y == pb for ab in vs)
        L.append(f"- **{title}** ({len(v)}): " + (", ".join(f"`{a}`->`{b}`" for a, b in v) if v else "none"))
    show("engine_core -> data", "engine_core", "data")
    show("backtest -> data", "backtest", "data")
    show("live_runner -> engine_core", "live_runner", "engine_core")
    show("scripts -> live_runner", "scripts", "live_runner")
    uses_db = sorted(m for m, bs in edges.items() if not m.startswith("tests.") and ("data.db.connection" in bs or "data.db.models" in bs))
    L += ["", "## Non-test modules that import the database layer (`data.db.connection` / `data.db.models`)", "",
          "Under the target rules none of these may be reachable from `engine`, `strategies` or `risk`.", "", ", ".join(f"`{m}`" for m in uses_db)]
    net = []
    for f in pyf:
        if f.startswith("tests/"):
            continue
        s = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^\s*(import|from)\s+(requests|urllib|yfinance|httpx|aiohttp)\b", s, re.M):
            net.append(f)
    L += ["", "## Non-test modules importing a network library", "", ", ".join(f"`{m}`" for m in net)]
    (ROOT / "docs/restructure/ARCHITECTURE_CURRENT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

# Part B fail-before evidence

Each row: the test, the code file, the mutation that breaks it, and the result (the test must pass on the real code and FAIL on the mutated code).

| test | code mutated | defect introduced | result |
|---|---|---|---|
| tests/unit/test_engine_types.py::test_state_round_trips_through_json_without_loss | stockbot/engine/types.py | positions dropped on load | passes clean / FAILS mutated |
| tests/unit/test_engine_types.py::test_decisions_round_trip_through_json_without_loss | stockbot/engine/types.py | flags not rebuilt as Flag objects | passes clean / FAILS mutated |
| tests/unit/test_engine_types.py::test_unknown_schema_version_is_refused_not_guessed | stockbot/engine/types.py | schema version not checked | passes clean / FAILS mutated |
| tests/unit/test_engine_types.py::test_every_engine_type_is_a_frozen_dataclass_of_json_native_values | stockbot/engine/types.py | Flag no longer frozen | passes clean / FAILS mutated |
| tests/unit/test_engine_types.py::test_spec_overlays_are_part_of_the_config_hash | stockbot/strategies/spec.py | overlays left out of the hash | passes clean / FAILS mutated |
| tests/unit/test_engine_types.py::test_spec_overlay_declarations_are_validated | stockbot/strategies/spec.py | overlay declaration not validated | passes clean / FAILS mutated |
| tests/unit/test_risk_arbitration.py::test_rank_is_only_compared_inside_one_strategy | stockbot/risk/arbitration.py | global rank order (the old rule) instead of per-strategy rank | passes clean / FAILS mutated |
| tests/unit/test_risk_arbitration.py::test_interleaving_is_round_robin_in_strategy_id_order | stockbot/risk/arbitration.py | strategy order reversed | passes clean / FAILS mutated |
| tests/unit/test_risk_arbitration.py::test_order_of_arrival_does_not_matter | stockbot/risk/arbitration.py | strategies taken in arrival order | passes clean / FAILS mutated |
| tests/unit/test_risk_arbitration.py::test_symbol_already_held_cannot_be_opened_by_another_strategy | stockbot/risk/arbitration.py | held-symbol check removed | passes clean / FAILS mutated |
| tests/unit/test_risk_arbitration.py::test_first_in_admission_order_wins_a_symbol_proposed_by_two_strategies | stockbot/risk/arbitration.py | accepted symbol not recorded as held | passes clean / FAILS mutated |
| tests/unit/test_risk_arbitration.py::test_sector_and_total_risk_caps_see_positions_of_every_strategy | stockbot/risk/arbitration.py | existing positions hidden from the caps | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_the_g3_trade_is_reproduced_by_the_engine | stockbot/engine/decide.py | entry slippage dropped | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_entry_bar_stop_exits_on_the_entry_day | stockbot/engine/stepping.py | stop not checked on the entry bar | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_entry_bar_stop_has_no_floor_at_the_bars_low | stockbot/engine/stepping.py | fill floored at the bar's low | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_no_entry_bar_exit_when_the_low_stays_above_the_stop | stockbot/engine/stepping.py | stop check too loose | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_decide_handles_exactly_one_session | stockbot/engine/decide.py | catch-up allowed inside decide | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_a_non_session_date_is_refused | stockbot/engine/decide.py | non-session date accepted | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_the_exit_policy_receives_the_as_of_view | stockbot/engine/stepping.py | view not passed to the policy | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_strict_mode_stops_the_run_on_a_strategy_error | stockbot/engine/decide.py | errors swallowed in strict mode | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_strict_mode_stops_the_run_on_an_exit_policy_error | stockbot/engine/decide.py | errors swallowed in strict mode | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_overlay_errors_follow_the_same_rule | stockbot/engine/decide.py | errors swallowed in strict mode | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_live_mode_flags_the_error_and_continues_with_the_other_strategies | stockbot/engine/decide.py | live isolation removed | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_overlay_signal_reaches_only_the_declaring_strategy_and_state_persists | stockbot/engine/decide.py | every strategy gets every overlay signal | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_overlay_declaration_must_match_the_registered_version | stockbot/engine/decide.py | version mismatch ignored | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_confirm_fill_is_per_strategy_and_blocks_the_fill | stockbot/engine/decide.py | per-strategy fill check ignored | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_gap_through_stop_blocks_the_fill | stockbot/engine/decide.py | gap through stop not blocked | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_gap_up_cap_is_shared_and_blocks_the_fill | stockbot/engine/decide.py | gap-up cap inverted | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_unknown_strategy_or_policy_is_an_input_error | stockbot/engine/decide.py | unknown policy not detected | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_stops_never_move_down | stockbot/engine/stepping.py | stop allowed to move down | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_time_exit_request_executes_at_the_next_open | stockbot/engine/stepping.py | market requests ignored | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_limit_target_fills_at_max_of_open_and_limit | stockbot/engine/stepping.py | limit fill uses min instead of max | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_determinism_same_inputs_same_outputs | stockbot/engine/decide.py | randomness inside decide | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_lookahead_changing_every_later_row_does_not_change_earlier_decisions | stockbot/data/asof.py | view no longer bounded by the as-of date | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_isolation_a_strategy_gets_the_same_proposals_alone_and_together | stockbot/engine/decide.py | a strategy's input depends on the other strategies | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_a_held_symbol_cannot_be_opened_by_another_strategy_later | stockbot/engine/decide.py | open positions hidden from arbitration | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_only_risk_applies_caps | tests/fixtures/dummies.py | a dummy strategy file mentions a cap | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_proposals_outside_the_eligible_universe_are_refused | stockbot/engine/decide.py | eligibility not enforced | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_overlay_errors_follow_the_same_rule | stockbot/engine/decide.py | overlay failure not flagged | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_state_is_the_fold_of_the_decisions | stockbot/engine/apply.py | cash not taken from the decisions | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_bonus_with_a_fractional_remainder_pays_cash_in_lieu | stockbot/engine/corporate.py | cash in lieu not paid | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_unrescalable_action_puts_the_position_on_hold | stockbot/engine/corporate.py | hold flag not set | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_an_action_is_applied_once_and_dividends_are_ignored | stockbot/engine/corporate.py | already-applied action applied again | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_equal_to_the_legacy_f3_module_on_a_random_grid | stockbot/engine/corporate.py | shares rounded instead of floored | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_a_split_inside_the_holding_period_leaves_pnl_and_r_unchanged | stockbot/engine/corporate.py | initial shares not rescaled | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_a_split_inside_the_holding_period_leaves_pnl_and_r_unchanged | stockbot/engine/corporate.py | position not rescaled at the split | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_backtest_closes_open_positions_at_the_window_end | stockbot/backtest/runner.py | end-of-window exit without slippage | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_backtest_closes_open_positions_at_the_window_end | stockbot/backtest/runner.py | open positions left open at the window end | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_backtest_forbids_the_network | stockbot/backtest/runner.py | network guard removed | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_the_baseline_helper_and_the_backtest_agree_on_the_same_ticket | stockbot/engine/path.py | baseline never fills | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_the_baseline_helper_and_the_backtest_agree_on_the_same_ticket | stockbot/engine/path.py | baseline ignores exit slippage | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_the_baseline_helper_rebases_for_a_split_exactly_like_decide | stockbot/engine/path.py | baseline does not rebase for the split | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_reported_fill_overrides_the_simulated_one | stockbot/engine/reports.py | buy costs not charged on a reported fill | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_reported_exit_closes_the_position_with_the_real_price | stockbot/engine/reports.py | gross P&L of a reported exit ignored | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_ticket_not_taken_is_dropped_without_a_position | stockbot/engine/reports.py | not-taken ticket stays pending | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_missed_sessions_are_processed_one_decide_each | stockbot/live/adapter.py | missed sessions skipped | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_reported_fill_overrides_the_simulated_one | stockbot/live/adapter.py | operator reports ignored | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_a_report_given_twice_is_applied_once | stockbot/live/adapter.py | report applied twice | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_bad_reports_are_refused_not_guessed | stockbot/live/adapter.py | late report accepted | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_unreported_ticket_is_simulated_and_flagged | stockbot/live/adapter.py | live mode not passed to decide | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_backtest_and_live_give_identical_decisions_day_by_day | stockbot/live/adapter.py | live state drifts from the backtest state | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_journal_is_append_only | stockbot/live/state_store.py | journal rows can be updated | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_state_store_is_versioned_and_separate_from_the_lake | stockbot/live/state_store.py | schema version not checked | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_state_store_is_versioned_and_separate_from_the_lake | stockbot/live/state_store.py | lake file accepted as the state store | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_state_is_rebuilt_from_the_journal_alone | stockbot/live/state_store.py | rebuild ignores decisions | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_the_live_adapter_does_not_write_the_lake | stockbot/live/adapter.py | adapter tries to write the lake (read-only connection refuses) | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_reported_fill_overrides_the_simulated_one | stockbot/engine/reports.py | resolved ticket stays pending | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_processing_the_same_live_date_twice_changes_nothing | stockbot/live/adapter.py | already-processed dates are processed again (both guards removed) | passes clean / FAILS mutated |
| tests/unit/test_engine_live.py::test_a_report_journaled_before_any_further_session_is_rebuilt | stockbot/live/state_store.py | rebuild ignores operator reports | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_entry_bar_rule_equals_legacy_advance_one_bar_on_a_random_grid | stockbot/engine/stepping.py | stop-hit fill ignores the stop price | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_entry_bar_rule_equals_legacy_advance_one_bar_on_a_random_grid | stockbot/engine/stepping.py | stop-hit fill floored at the bar's low | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_a_meeting_is_visible_only_from_its_intimation_date | stockbot/data/asof.py | intimation date not enforced | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_changing_rows_intimated_after_the_as_of_date_changes_nothing | stockbot/data/asof.py | intimation date not enforced | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_duplicate_meeting_dates_collapse_to_the_earliest_intimation | stockbot/data/asof.py | latest intimation kept instead of the earliest | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_only_results_meetings_with_a_known_intimation_count | stockbot/data/asof.py | non-results meetings returned | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_coverage_says_no_data_instead_of_no_event | stockbot/data/asof.py | empty API response counted as coverage | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_a_lake_without_earnings_tables_has_no_coverage_and_no_meetings | stockbot/data/asof.py | missing earnings tables crash the view | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_results_within_is_none_without_coverage_and_respects_the_window | stockbot/universe/eligibility.py | no data read as no event | passes clean / FAILS mutated |
| tests/unit/test_asof_earnings.py::test_results_within_is_none_without_coverage_and_respects_the_window | stockbot/universe/eligibility.py | window end exclusive | passes clean / FAILS mutated |
| tests/data_integrity/test_entry_bar_real_lake.py::test_entry_bar_rule_agrees_with_every_legacy_trade_on_the_real_lake | stockbot/engine/stepping.py | stop not checked on the entry bar (real-lake legacy trades disagree) | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_the_run_manifest_records_what_reproduces_the_run | stockbot/backtest/manifest.py | config hash does not depend on the config | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_the_run_manifest_records_what_reproduces_the_run | stockbot/backtest/manifest.py | overlay declarations missing from the manifest | passes clean / FAILS mutated |
| tests/unit/test_engine_backtest.py::test_the_run_manifest_records_what_reproduces_the_run | stockbot/backtest/manifest.py | strategy config hash missing | passes clean / FAILS mutated |
| tests/unit/test_ledger_yaml_hash.py::test_the_trial_ledger_chain_verifies_at_its_validation_location_and_names_no_path | stockbot/validation/ledger/records/trial_ledger.csv | a ledger row altered after the move | passes clean / FAILS mutated |
| tests/unit/test_ledger_yaml_hash.py::test_the_exploratory_ledger_is_unchanged_and_has_no_chain | stockbot/validation/ledger/records/trial_ledger_exploratory.csv | the exploratory ledger altered | passes clean / FAILS mutated |
| tests/unit/test_ledger_yaml_hash.py::test_pre_registered_configs_yaml_matches_the_ledger_hash | stockbot/validation/ledger/records/pre_registered_configs.yaml | pre-registration yaml edited | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_a_family_is_registered_together_and_its_budget_is_its_size | stockbot/validation/ledger/__init__.py | family budget is not the family size | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_member_hashes_are_recorded_so_a_changed_member_is_visible | stockbot/validation/ledger/__init__.py | family can be re-registered silently | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_duplicate_or_empty_families_are_refused | stockbot/validation/ledger/__init__.py | duplicate member ids accepted | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_results_must_cover_exactly_the_registered_members | stockbot/validation/ledger/__init__.py | results may leave members out | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_results_must_cover_exactly_the_registered_members | stockbot/validation/ledger/__init__.py | results can be re-recorded silently | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_tampering_with_a_family_row_is_detected | stockbot/validation/ledger/__init__.py | chain not verified before reading | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_two_families_share_a_file_but_not_a_budget | stockbot/validation/ledger/__init__.py | families mixed up | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_register_writes_a_chained_registration_row_and_demands_a_reason_to_repeat | stockbot/validation/ledger/__init__.py | re-registration without a reason accepted | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_exploratory_log_has_one_header_and_no_chain | stockbot/validation/ledger/__init__.py | header written on every row | passes clean / FAILS mutated |
| tests/unit/test_validation_ledger.py::test_the_real_trial_ledger_verifies_through_the_new_api | stockbot/validation/ledger/__init__.py | wrong row count | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_same_seed_same_draws_and_other_seeds_differ | stockbot/validation/random_baseline.py | draws not seeded | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_draws_use_the_engine_exit_policy_and_the_matched_relative_stop | stockbot/validation/random_baseline.py | stop distance not matched | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_the_pool_is_the_shared_universe_minus_the_actual_symbol | stockbot/validation/random_baseline.py | pool ignores eligibility and the actual symbol | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_the_pool_is_the_shared_universe_minus_the_actual_symbol | stockbot/validation/random_baseline.py | pool_filter ignored | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_forward_returns_are_measured_from_the_fill_price | stockbot/validation/random_baseline.py | forward return off by one session | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_unfilled_draws_are_counted_not_hidden | stockbot/validation/random_baseline.py | unfilled draws not counted | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_paired_statistics_are_reproducible_for_a_seed_and_move_with_it | stockbot/validation/paired_stats.py | statistics not seeded | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_paired_difference_and_significance_follow_the_data | stockbot/validation/paired_stats.py | median used for the paired difference | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_paired_difference_and_significance_follow_the_data | stockbot/validation/paired_stats.py | significance threshold removed | passes clean / FAILS mutated |
| tests/unit/test_validation_random_baseline.py::test_trimmed_mean_and_report | stockbot/validation/paired_stats.py | nothing trimmed | passes clean / FAILS mutated |
| tests/unit/test_lake_symbols.py::test_the_mapping_in_force_on_the_ex_date_wins | stockbot/data/ingestion/lake_symbols.py | range end ignored | passes clean / FAILS mutated |
| tests/unit/test_lake_symbols.py::test_outside_every_range_the_latest_mapping_is_used | stockbot/data/ingestion/lake_symbols.py | wrong fallback mapping | passes clean / FAILS mutated |
| tests/unit/test_lake_symbols.py::test_without_an_isin_or_a_mapping_the_feed_symbol_is_kept | stockbot/data/ingestion/lake_symbols.py | feed symbol dropped | passes clean / FAILS mutated |
| tests/unit/test_check_all.py::test_default_run_has_the_four_steps_and_no_environment_switches | stockbot/data_checks/check_all.py | boundary test dropped from the entry point | passes clean / FAILS mutated |
| tests/unit/test_check_all.py::test_data_and_final_switch_on_their_environment_variables_and_add_the_real_db_step | stockbot/data_checks/check_all.py | final switch ignored | passes clean / FAILS mutated |
| tests/unit/test_check_all.py::test_any_failing_step_fails_the_whole_run_and_is_named | stockbot/data_checks/check_all.py | failures do not change the exit code | passes clean / FAILS mutated |
| tests/unit/test_f6_baseline_and_locks.py::test_engine_path_equals_legacy_path_sim_for_the_same_ticket | stockbot/engine/stepping.py | stop fill price differs from the legacy path | passes clean / FAILS mutated |
| tests/unit/test_f6_baseline_and_locks.py::test_engine_path_equals_legacy_path_sim_for_the_same_ticket | stockbot/engine/fills.py | fill price differs from the legacy path | passes clean / FAILS mutated |
| tests/unit/test_f6_baseline_and_locks.py::test_engine_path_equals_legacy_path_sim_for_the_same_ticket | stockbot/engine/corporate.py | split not rebased like the legacy path | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_live_needs_a_strategy_with_status_live_and_a_validation_ref | stockbot/live/runner.py | paper strategies allowed in LIVE | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_live_needs_a_strategy_with_status_live_and_a_validation_ref | stockbot/live/runner.py | LIVE runs with no live strategy | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_paper_runs_paper_and_live_strategies_but_never_research | stockbot/live/runner.py | research strategies run in the live package | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_a_date_the_lake_does_not_hold_yet_is_refused_and_nothing_is_written | stockbot/live/runner.py | freshness not checked | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_live_fails_closed_without_an_asm_gsm_snapshot_and_paper_continues | stockbot/live/runner.py | LIVE does not fail closed | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_a_fresh_state_database_starts_with_the_configured_paper_equity | stockbot/live/runner.py | wrong starting equity | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_tickets_are_written_as_a_file_per_session | stockbot/live/runner.py | ticket file not written atomically (temp file left) | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_running_the_same_date_twice_changes_nothing | stockbot/live/adapter.py | date processed twice | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_symbols_in_todays_asm_gsm_snapshot_are_not_eligible | stockbot/live/runner.py | ASM/GSM names not excluded | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_scheduler_job_survives_a_refusal_and_runs_when_data_is_there | stockbot/live/scheduler.py | scheduler job dies on a refusal | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_scheduler_job_survives_a_refusal_and_runs_when_data_is_there | stockbot/live/runner.py | default mode is LIVE | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_command_line_exit_codes | stockbot/live/eod_cli.py | refusal exit code changed | passes clean / FAILS mutated |
| tests/unit/test_regulatory_barrier.py::test_no_broker_order_code | stockbot/live/runner.py | order-placement code in stockbot | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_api_routers_do_not_import_engine_internals | stockbot/live/api/regime.py | a router imports the decision engine | passes clean / FAILS mutated |
| tests/unit/test_script_wrappers_help.py::test_help_answers_and_writes_nothing[earnings_coverage.py] | stockbot/data_checks/earnings_coverage.py | script without argparse: --help runs it (rewrites its outputs) | passes clean / FAILS mutated |
| tests/unit/test_script_wrappers_help.py::test_help_answers_and_writes_nothing[f9_report.py] | stockbot/validation/f9_report.py | script without argparse: --help runs it (rewrites its output) | passes clean / FAILS mutated |
| tests/unit/test_script_wrappers_help.py::test_help_answers_and_writes_nothing[check_all.py] | stockbot/data_checks/check_all.py | --help not answered by the parser (exit code/usage) | passes clean / FAILS mutated |
| tests/unit/test_risk_caps.py::test_equal_to_the_frozen_answers_of_the_legacy_heat_cap_code_on_4000_random_cases | stockbot/risk/caps.py | position count gate off by one | passes clean / FAILS mutated |
| tests/unit/test_risk_sizing_generic.py::test_agrees_with_the_frozen_fill_time_sizing_of_the_legacy_code_on_3000_random_cases | stockbot/risk/sizing.py | shares rounded instead of floored | passes clean / FAILS mutated |
| tests/unit/test_engine_corporate.py::test_equal_to_the_frozen_answers_of_the_legacy_f3_module_on_400_random_cases | stockbot/engine/corporate.py | shares rounded instead of floored | passes clean / FAILS mutated |
| tests/unit/test_engine_decide.py::test_entry_bar_rule_equals_the_frozen_answers_of_the_legacy_advance_one_bar_on_5000_random_cases | stockbot/engine/stepping.py | stop fill ignores the gap (open below the stop) | passes clean / FAILS mutated |
| tests/unit/test_costs.py::test_shared_construction_equals_the_frozen_legacy_cost_model | stockbot/risk/costs.py | exchange and SEBI rates swapped | passes clean / FAILS mutated |
| tests/unit/test_shared_config.py::test_every_shared_value_equals_the_legacy_value_and_type | stockbot/config/shared.yaml | a shared value differs from the frozen legacy value | passes clean / FAILS mutated |
| tests/unit/test_f6_baseline_and_locks.py::test_engine_path_equals_the_frozen_legacy_path_sim_for_the_same_ticket | stockbot/engine/fills.py | fill price differs from the legacy path | passes clean / FAILS mutated |
| tests/unit/test_golden_files.py::test_every_golden_file_matches_its_recorded_sha256_and_nothing_is_unlisted | tests/golden/engine_scan_summary.json | a frozen golden file edited | passes clean / FAILS mutated |
| tests/unit/test_golden_files.py::test_every_golden_file_matches_its_recorded_sha256_and_nothing_is_unlisted | tests/golden/SHA256SUMS | golden checksum list edited (file unlisted) | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_a_name_trading_on_the_lakes_first_day_is_seasoned_even_in_2013 | stockbot/data/asof.py | first-day names not seasoned | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_a_recent_listing_is_still_young_and_a_name_without_bars_has_no_age | stockbot/data/asof.py | young names treated as seasoned | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_eligibility_uses_the_f2_listing_age | stockbot/universe/eligibility.py | eligibility uses the raw session count | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_a_later_name_ages_by_its_own_sessions_until_550_calendar_days | stockbot/data/asof.py | 550-day rule dropped | passes clean / FAILS mutated |
| tests/unit/test_live_health_check.py::test_stale_price_data_is_reported | stockbot/live/health_check.py | stale data not reported | passes clean / FAILS mutated |
| tests/unit/test_live_health_check.py::test_a_snapshot_that_disagrees_with_the_journal_is_reported | stockbot/live/health_check.py | snapshot vs journal not compared | passes clean / FAILS mutated |
| tests/unit/test_live_health_check.py::test_a_state_store_behind_the_lake_is_reported | stockbot/live/health_check.py | state behind the lake not reported | passes clean / FAILS mutated |
| tests/unit/test_live_health_check.py::test_an_uninitialised_store_is_reported | stockbot/live/health_check.py | uninitialised store not reported | passes clean / FAILS mutated |
| tests/unit/test_live_health_check.py::test_command_line_exit_codes | stockbot/live/health_check.py | problems do not change the exit code | passes clean / FAILS mutated |
| tests/unit/test_script_wrappers_help.py::test_every_wrapper_and_the_provenance_readme_is_tracked_by_git | scripts/ (a new untracked wrapper file) | a wrapper that git does not track | passes clean / FAILS with an untracked wrapper present |
| tests/unit/test_asof_view.py::test_the_fund_list_file_is_read_and_funds_are_not_eligible | stockbot/universe/eligibility.py | funds are eligible | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_the_fund_list_file_is_read_and_funds_are_not_eligible | stockbot/data/asof.py | fund list not read | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_no_asm_ranges_and_an_empty_dict_give_the_same_universe | stockbot/universe/eligibility.py | ASM/GSM ranges ignored | passes clean / FAILS mutated |
| tests/unit/test_asof_view.py::test_no_asm_ranges_and_an_empty_dict_give_the_same_universe | stockbot/universe/eligibility.py | range end ignored | passes clean / FAILS mutated |
| tests/unit/test_live_runner.py::test_the_health_endpoint_reports_the_configured_mode_not_unknown | stockbot/live/api/health.py | the import swallowed by a comment (the old bug) | passes clean / FAILS mutated |
| tests/unit/test_shared_config.py::test_every_key_of_the_removed_yaml_has_a_documented_new_home | docs/restructure/CONFIG_KEYS.csv | a key left without a decided home | passes clean / FAILS mutated |
| tests/unit/test_shared_config.py::test_the_regime_endpoint_constants_equal_the_frozen_macro_section | stockbot/live/api/regime.py | display constant differs from the frozen value | passes clean / FAILS mutated |
| tests/unit/test_shared_config.py::test_the_config_dict_has_the_legacy_shape_and_the_shared_values | stockbot/config/dict_view.py | a legacy section name not mapped | passes clean / FAILS mutated |
| tests/unit/test_ledger_yaml_hash.py::test_what_remains_of_the_old_outputs_is_what_the_ledger_and_the_decisions_need | backtest/ (a tracked .py file added) | code left in backtest/ | passes clean / FAILS with a tracked .py in backtest/ |
| tests/unit/test_no_strategy_in_the_tree.py::test_no_class_outside_tests_implements_the_strategy_or_overlay_or_exit_policy_interface | stockbot/live/runner.py | a strategy-shaped class added to the live package | passes clean / FAILS mutated |
| tests/unit/test_no_strategy_in_the_tree.py::test_the_default_registry_and_the_default_live_book_are_empty | stockbot/live/runner.py | the default book is not empty | passes clean / FAILS mutated |

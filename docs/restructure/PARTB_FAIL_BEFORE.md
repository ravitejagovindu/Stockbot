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

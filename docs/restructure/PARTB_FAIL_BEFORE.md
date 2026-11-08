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

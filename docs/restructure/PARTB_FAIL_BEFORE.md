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

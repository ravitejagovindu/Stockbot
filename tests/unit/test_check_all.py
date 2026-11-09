"""stockbot.data_checks.check_all: the single entry point runs every golden-check step, passes the right environment, and fails if any step fails (runner replaced)."""
from stockbot.data_checks import check_all


def fake(codes):
    calls = []

    def runner(args, env):
        calls.append((list(args), {k: env.get(k) for k in ("STOCKBOT_DATA_TESTS", "STOCKBOT_FINAL_CHECK")}))
        return codes.get(args[0], 0)
    return runner, calls


def test_default_run_has_the_four_steps_and_no_environment_switches(monkeypatch):
    monkeypatch.delenv("STOCKBOT_DATA_TESTS", raising=False)
    monkeypatch.delenv("STOCKBOT_FINAL_CHECK", raising=False)
    runner, calls = fake({})
    lines = []
    assert check_all.run(runner=runner, out=lines.append) == 0
    assert len(calls) == 4 and all(env == {"STOCKBOT_DATA_TESTS": None, "STOCKBOT_FINAL_CHECK": None} for _, env in calls)
    assert any("G6" in l and "PASS" in l for l in lines) and lines[-1] == "ALL CHECKS PASSED"
    assert any("tests/unit/test_import_boundaries.py" in a for a, _ in calls)                            # the boundary test is part of the entry point
    assert any(any("test_engine_live.py" in x for x in a) for a, _ in calls)                              # so are the parity tests


def test_data_and_final_switch_on_their_environment_variables_and_add_the_real_db_step():
    runner, calls = fake({})
    assert check_all.run(data=True, final=True, runner=runner, out=lambda s: None) == 0
    assert len(calls) == 5 and calls[-1][0][0] == "tests/data_integrity"
    assert all(env["STOCKBOT_DATA_TESTS"] == "1" and env["STOCKBOT_FINAL_CHECK"] == "1" for _, env in calls)


def test_any_failing_step_fails_the_whole_run_and_is_named():
    runner, calls = fake({"tests/unit/test_import_boundaries.py": 1})
    lines = []
    assert check_all.run(runner=runner, out=lines.append) == 1
    assert len(calls) == 4                                                                               # later steps still run
    assert any(l.startswith("  FAIL") and "G5" in l for l in lines) and lines[-1].startswith("FAILED: G5")

"""stockbot.validation.ledger: the extracted ledger writers and the family-level helper (a family of N strategies is recorded and corrected together)."""
import csv
import json
import shutil

import pytest

from stockbot.validation import ledger
from stockbot.validation.prereg_lock import PreRegistrationError, read_ledger
from tests.fixtures.dummies import make_spec

GATES = {"min_trades": 40, "alpha": 0.05}


def specs(*ids):
    return [make_spec(i) for i in ids]


def reg(path, family="fam_a", members=("s_one", "s_two", "s_three"), **kw):
    return ledger.register_family(path=path, family_id=family, members=specs(*members), gate_params=GATES, git_sha="abc123", **kw)


def test_the_real_trial_ledger_verifies_through_the_new_api():
    st = ledger.verify()
    assert st.rows == 2 and st.last_hash == "869d1bd13d592ce635bed70c10081d6b2037a79272f64dabe21819a9152125d1"


def test_a_family_is_registered_together_and_its_budget_is_its_size(tmp_path):
    p = tmp_path / "fam.csv"
    rec = reg(p)
    assert rec["budget"] == 3 and ledger.family_budget(p, "fam_a") == 3
    assert [m["id"] for m in ledger.family_members(p, "fam_a")] == ["s_one", "s_three", "s_two"]
    assert all(len(m["config_hash"]) == 64 for m in ledger.family_members(p, "fam_a"))
    assert ledger.verify(p).rows == 1


def test_member_hashes_are_recorded_so_a_changed_member_is_visible(tmp_path):
    p = tmp_path / "fam.csv"
    reg(p)
    changed = [make_spec("s_one", params={"x": 2}), make_spec("s_two"), make_spec("s_three")]
    with pytest.raises(PreRegistrationError, match="already registered"):
        ledger.register_family(path=p, family_id="fam_a", members=changed, gate_params=GATES, git_sha="x")
    ledger.register_family(path=p, family_id="fam_a", members=changed, gate_params=GATES, git_sha="x", reason="s_one params changed")
    old = {m["id"]: m["config_hash"] for m in json.loads(read_ledger(p)[1][0]["members_json"])}
    new = {m["id"]: m["config_hash"] for m in ledger.family_members(p, "fam_a")}
    assert old["s_one"] != new["s_one"] and old["s_two"] == new["s_two"]                    # only the changed member differs
    assert ledger.verify(p).rows == 2 and read_ledger(p)[1][1]["reason"] == "s_one params changed"


def test_duplicate_or_empty_families_are_refused(tmp_path):
    with pytest.raises(PreRegistrationError, match="duplicate"):
        reg(tmp_path / "a.csv", members=("s_one", "s_one"))
    with pytest.raises(PreRegistrationError, match="at least one"):
        reg(tmp_path / "b.csv", members=())
    assert not (tmp_path / "a.csv").exists()                                                # nothing was written


def test_results_must_cover_exactly_the_registered_members(tmp_path):
    p = tmp_path / "fam.csv"
    reg(p)
    ok = {"s_one": {"p": 0.2}, "s_two": {"p": 0.6}, "s_three": {"p": 0.04}}
    with pytest.raises(PreRegistrationError, match="missing"):
        ledger.record_family_results(path=p, family_id="fam_a", results={"s_one": {"p": 0.2}}, git_sha="x")                 # the failures cannot be left out
    with pytest.raises(PreRegistrationError, match="unexpected"):
        ledger.record_family_results(path=p, family_id="fam_a", results={**ok, "s_extra": {"p": 0.5}}, git_sha="x")
    row = ledger.record_family_results(path=p, family_id="fam_a", results=ok, git_sha="x")
    assert json.loads(row["results_json"])["s_three"] == {"p": 0.04} and row["budget"] == 3
    with pytest.raises(PreRegistrationError, match="already recorded"):
        ledger.record_family_results(path=p, family_id="fam_a", results=ok, git_sha="x")                                   # no silent re-run
    ledger.record_family_results(path=p, family_id="fam_a", results=ok, git_sha="x", reason="rerun after data fix")
    assert ledger.verify(p).rows == 3


def test_unregistered_family_has_no_budget(tmp_path):
    p = tmp_path / "fam.csv"
    reg(p)
    with pytest.raises(PreRegistrationError, match="not registered"):
        ledger.family_budget(p, "fam_b")
    with pytest.raises(PreRegistrationError, match="not registered"):
        ledger.record_family_results(path=p, family_id="fam_b", results={}, git_sha="x")


def test_two_families_share_a_file_but_not_a_budget(tmp_path):
    p = tmp_path / "fam.csv"
    reg(p)
    reg(p, family="fam_b", members=("t_one", "t_two"))
    assert (ledger.family_budget(p, "fam_a"), ledger.family_budget(p, "fam_b")) == (3, 2)
    assert ledger.verify(p).rows == 2


def test_tampering_with_a_family_row_is_detected(tmp_path):
    p = tmp_path / "fam.csv"
    reg(p)
    text = p.read_text(encoding="utf-8")
    p.write_text(text.replace(",3,", ",2,", 1), encoding="utf-8")                             # lower the recorded budget
    with pytest.raises(PreRegistrationError, match="altered"):
        ledger.family_budget(p, "fam_a")


def test_the_chain_does_not_depend_on_where_the_file_lives(tmp_path):
    p = tmp_path / "one" / "fam.csv"
    reg(p)
    reg(p, family="fam_b", members=("t_one",))
    q = tmp_path / "deep" / "er" / "copy.csv"
    q.parent.mkdir(parents=True)
    shutil.copy(p, q)
    assert ledger.verify(q) == ledger.verify(p)


def test_register_writes_a_chained_registration_row_and_demands_a_reason_to_repeat(tmp_path):
    yml = tmp_path / "pre.yaml"
    yml.write_text("configs: []\n", encoding="utf-8")
    p = tmp_path / "trial.csv"
    rec = ledger.register(ledger=p, yaml_path=yml, gate_params=GATES, candidate_ids=["CFG-01", "CFG-02"], git_sha="abc", now="2026-01-01T00:00:00+00:00")
    header, recs = read_ledger(p)
    assert header[:6] == ["timestamp_utc", "commit_sha", "selected_config", "selection_reason", "CFG-01_gate_reached", "CFG-02_gate_reached"]
    assert recs[0]["row_type"] == "REGISTRATION" and recs[0]["budget"] == "2" and recs[0]["prev_hash"] == "GENESIS" and rec["yaml_sha256"] == recs[0]["yaml_sha256"]
    assert ledger.verify(p).rows == 1
    with pytest.raises(PreRegistrationError, match="re-registering"):
        ledger.register(ledger=p, yaml_path=yml, gate_params=GATES, candidate_ids=["CFG-01", "CFG-02"], git_sha="abc")
    ledger.register(ledger=p, yaml_path=yml, gate_params=GATES, candidate_ids=["CFG-01", "CFG-02"], git_sha="abc", reason="typo in yaml header")
    assert ledger.verify(p).rows == 2 and read_ledger(p)[1][1]["selection_reason"] == "typo in yaml header"


def test_exploratory_log_has_one_header_and_no_chain(tmp_path):
    p = tmp_path / "exp.csv"
    ledger.record_exploratory(path=p, note="dry-run", selected=None, gate_reached={"CFG-01": 2}, git_sha="abc", source="some-dir", now="2026-01-01T00:00:00+00:00")
    ledger.record_exploratory(path=p, note="no-ledger diagnostic", selected="CFG-02", gate_reached={"CFG-01": 1}, git_sha="abc", source="other-dir", now="2026-01-02T00:00:00+00:00")
    rows = list(csv.reader(open(p, encoding="utf-8", newline="")))
    assert rows[0] == ["timestamp_utc", "commit_sha", "outputs_dir", "mode", "selected_config", "gate_reached_json"] and len(rows) == 3
    assert rows[1][4] == "NONE" and rows[2][4] == "CFG-02" and json.loads(rows[2][5]) == {"CFG-01": 1}
    assert "row_hash" not in rows[0] and "prev_hash" not in rows[0]

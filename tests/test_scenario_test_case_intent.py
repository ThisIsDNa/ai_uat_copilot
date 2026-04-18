"""Per–test-case intent for titles and differentiated step generation."""

from __future__ import annotations

from src.scenario_builder_steps_gen import generate_default_test_steps, propose_test_steps_for_all_active_tcs
from src.scenario_builder_tc_gen import derive_negative_test_case_title_from_ac, derive_test_case_title_from_ac, propose_test_cases_from_acceptance_criteria
from src.scenario_context_expansion import expand_scenario_context, expanded_context_from_builder_session
from src.scenario_test_case_intent import infer_intent_from_builder_session, infer_test_case_intent


def test_positive_title_from_intent_not_ac_trim() -> None:
    exp = expand_scenario_context(
        scenario_context="Provider updates email and phone. Save shows confirmation.",
        business_goal="",
        workflow_name="Patient profile",
        changed_areas_bulk="",
        known_dependencies_bulk="",
    )
    t = derive_test_case_title_from_ac(
        "User can save contact changes and must see a confirmation message after a successful update.",
        expanded=exp,
    )
    assert " - " in t
    assert "verify validation behavior" not in t.lower()
    assert "complete workflow outcome" not in t.lower()


def test_negative_titles_rotate_by_condition() -> None:
    ac = "User can update demographic fields on the chart."
    titles = {derive_negative_test_case_title_from_ac(ac, variant=v) for v in range(5)}
    assert len(titles) == 5
    assert all(" - " in x for x in titles)


def test_steps_differ_when_intent_differs() -> None:
    sess = {
        "sb_scenario_context": "",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can save with confirmation and persisted data.",
        "sb_ac_0_map": ["TC-01", "TC-02"],
        "sb_n_tc": 2,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "User - Save Confirmation Message",
        "sb_tc_0_active": True,
        "sb_tc_1_id": "TC-02",
        "sb_tc_1_text": "User - Persist Updated Values",
        "sb_tc_1_active": True,
    }
    out = propose_test_steps_for_all_active_tcs(sess)
    assert len(out) == 2
    a = "\n".join(out[0]["steps"])
    b = "\n".join(out[1]["steps"])
    assert a != b
    assert "confirmation" in a.lower() or "toast" in a.lower() or "banner" in a.lower()
    assert "refresh" in b.lower() or "re-open" in b.lower() or "persist" in b.lower()


def test_generate_steps_use_intent_without_explicit_pass() -> None:
    steps = generate_default_test_steps(
        test_case_title="Provider - Invalid Email Format",
        linked_ac_texts=["Invalid email must show inline error."],
        expanded_context=None,
        intent=None,
    )
    blob = " ".join(steps).lower()
    assert "email" in blob or "invalid" in blob or "format" in blob


def test_infer_happy_path_weak_context_fallback() -> None:
    intent = infer_test_case_intent(
        criterion_text_only="User can do something useful.",
        expanded=None,
        is_negative=False,
    )
    assert intent.entity
    assert intent.intent_summary


def test_boundary_negative_accepts_valid_edge_in_ac_text() -> None:
    intent = infer_test_case_intent(
        test_case_title="Provider - Email Boundary Value",
        criterion_text_only="System accepts valid edge email length at minimum domain length.",
        expanded=None,
        is_negative=True,
        forced_condition="boundary_value",
    )
    assert "accepted edge" in (intent.persistence_expectation or "").lower()
    steps = generate_default_test_steps(
        test_case_title="Provider - Email Boundary Value",
        linked_ac_texts=["System accepts valid edge email length at minimum domain length."],
        expanded_context=None,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert "false-negative" in blob or "boundary" in blob
    assert "invalid value must not persist" not in blob


def test_expansion_boilerplate_does_not_force_invalid_format_on_unrelated_ac() -> None:
    """Generic ``invalid`` wording in expanded risk text must not override a plain sign-in AC."""
    sess = {
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can sign in.",
    }
    out = propose_test_cases_from_acceptance_criteria(sess)
    assert len(out) == 1
    assert "sign" in out[0]["title"].lower()
    assert "invalid input handling" not in out[0]["title"].lower()


def test_negative_title_explicit_email_keeps_target_field_despite_variant() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    intent = infer_test_case_intent(
        test_case_title="Provider - Invalid Email Format",
        linked_acceptance_criteria=[],
        criterion_text_only="",
        expanded=exp,
        is_negative=True,
        forced_condition="invalid_format",
        negative_field_variant=50,
    )
    assert intent.target_field == "email"


def test_infer_intent_from_builder_session_respects_explicit_negative_field_in_title() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "Validate contact save.",
        "sb_n_tc": 2,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "Provider - Invalid Email Format",
        "sb_tc_0_active": True,
        "sb_tc_1_id": "TC-02",
        "sb_tc_1_text": "Provider - Invalid Phone Format",
        "sb_tc_1_active": True,
    }
    i0 = infer_intent_from_builder_session(sess, 0, linked_ac_texts=["Validate contact save."])
    i1 = infer_intent_from_builder_session(sess, 1, linked_ac_texts=["Validate contact save."])
    assert i0.target_field == "email"
    assert i1.target_field == "phone"
    a = infer_intent_from_builder_session(sess, 1, linked_ac_texts=["Validate contact save."])
    b = infer_intent_from_builder_session(sess, 1, linked_ac_texts=["Validate contact save."])
    assert a.target_field == b.target_field

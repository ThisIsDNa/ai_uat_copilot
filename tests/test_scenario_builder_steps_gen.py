"""Heuristic test-step generation (guided builder C3)."""

from __future__ import annotations

import re

from src.scenario_builder_steps_gen import (
    active_tc_indices,
    generate_default_test_steps,
    propose_test_steps_for_all_active_tcs,
)
from src.scenario_context_expansion import expanded_context_from_builder_session
from src.scenario_test_case_intent import infer_test_case_intent


def test_generate_default_steps_count_between_3_and_6() -> None:
    for title in ("Submit enrollment", "X", "Short title for testing workflow behavior"):
        steps = generate_default_test_steps(test_case_title=title, linked_ac_texts=None)
        assert 3 <= len(steps) <= 6
        assert all(s.strip() for s in steps)


def test_generate_default_steps_negative_style() -> None:
    steps = generate_default_test_steps(
        test_case_title="Prevent submission with missing fields",
        linked_ac_texts=None,
    )
    assert len(steps) >= 4
    assert any("verify" in s.lower() for s in steps)


def test_positive_includes_validation_and_navigate_sequence() -> None:
    steps = generate_default_test_steps(test_case_title="Submit enrollment", linked_ac_texts=None)
    assert any(s.lower().startswith("navigate") for s in steps)
    assert any(re.search(r"(?i)\b(verify|confirm|validate)\b", s) for s in steps)
    assert any("persist" in s.lower() or "message" in s.lower() or "ui" in s.lower() for s in steps)


def test_vocabulary_polish_replaces_go_to() -> None:
    steps = generate_default_test_steps(test_case_title="Workflow", linked_ac_texts=None)
    joined = " ".join(steps).lower()
    assert "go to" not in joined


def test_propose_skips_tc_without_title() -> None:
    sess = {
        "sb_n_tc": 2,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "Submit enrollment",
        "sb_tc_0_active": True,
        "sb_tc_1_id": "TC-02",
        "sb_tc_1_text": "",
        "sb_tc_1_active": True,
        "sb_n_ac": 0,
    }
    out = propose_test_steps_for_all_active_tcs(sess)
    assert len(out) == 1
    assert out[0]["tc_slot"] == 0


def test_persist_intent_steps_include_refresh_and_value_check() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    intent = infer_test_case_intent(
        test_case_title="Provider - Contact Info - Persist After Refresh",
        linked_acceptance_criteria=["Updates persist after refresh."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "contact_info",
            "verification_focus": "persistence_after_refresh",
            "intent_hint": "Contact Info - Persist After Refresh",
            "forced_condition": "persisted_state_check",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Contact Info - Persist After Refresh",
        linked_ac_texts=["Updates persist after refresh."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert "refresh" in blob or "re-open" in blob
    assert "persist" in blob or "remain" in blob


def test_validation_pass_steps_include_save_and_success_outcome() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    intent = infer_test_case_intent(
        test_case_title="Provider - Email Validation Pass",
        linked_acceptance_criteria=["Email field validates before save."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "email",
            "verification_focus": "validation_pass",
            "intent_hint": "Email Validation Pass",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Email Validation Pass",
        linked_ac_texts=["Email field validates before save."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert re.search(r"save|submit|update", blob)
    assert "verify" in blob
    assert "success" in blob or "saved" in blob or "outcome" in blob


def test_valid_save_positive_includes_trigger_and_outcome_verification() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    intent = infer_test_case_intent(
        test_case_title="Provider - Update Email - Valid Save",
        linked_acceptance_criteria=["Valid email saves successfully."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "email",
            "verification_focus": "valid_save",
            "intent_hint": "Update Email - Valid Save",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Update Email - Valid Save",
        linked_ac_texts=["Valid email saves successfully."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert re.search(r"save|submit|update", blob)
    assert "verify" in blob


def test_negative_steps_include_trigger_error_and_non_persistence() -> None:
    steps = generate_default_test_steps(
        test_case_title="Provider - Invalid Phone Format",
        linked_ac_texts=["Phone must be 10 digits."],
        expanded_context=None,
        intent=None,
    )
    blob = " ".join(steps).lower()
    assert re.search(r"save|submit|continue", blob)
    assert "error" in blob or "invalid" in blob or "validation" in blob
    assert "persist" in blob or "not" in blob


def test_negative_invalid_email_no_success_outcome_padding() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    steps = generate_default_test_steps(
        test_case_title="Provider - Invalid Email Format",
        linked_ac_texts=["Malformed email shows inline error; save is blocked."],
        expanded_context=exp,
        intent=None,
    )
    blob = " ".join(s.lower() for s in steps)
    assert "invalid" in blob or "malformed" in blob or "format" in blob
    assert "email" in blob
    assert "success messaging" not in blob
    assert "saved successfully" not in blob


def test_negative_missing_required_phone_cleared_and_save_blocked() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    steps = generate_default_test_steps(
        test_case_title="Provider - Missing Required Phone",
        linked_ac_texts=["Phone is required; clearing it blocks save."],
        expanded_context=exp,
        intent=None,
    )
    blob = " ".join(s.lower() for s in steps)
    assert "phone" in blob
    assert "clear" in blob or "blank" in blob or "empty" in blob or "missing" in blob
    assert "save" in blob or "submit" in blob or "continue" in blob
    assert "success outcome" not in blob


def test_negative_completion_does_not_append_positive_save_outcome() -> None:
    """Regression: negative flows must not receive positive step-completion phrases."""
    from src.scenario_builder_steps_gen import _ensure_complete_test_steps

    intent = infer_test_case_intent(
        test_case_title="Provider - Invalid Email Format",
        linked_acceptance_criteria=["Invalid email rejected on save."],
        expanded=None,
        is_negative=True,
    )
    thin = ["Navigate to the form.", "Enter values."]
    out = _ensure_complete_test_steps(thin, intent, title="Provider - Invalid Email Format", expanded=None, linked_ac_blob="")
    blob = " ".join(s.lower() for s in out)
    assert "save outcome" not in blob
    assert "success messaging" not in blob
    assert "confirmation toast" not in blob


def test_negative_toggle_disable_all_notifications_blocked() -> None:
    from tests.test_scenario_type_detection import _notification_prefs_blob

    exp = expanded_context_from_builder_session(
        {
            "sb_scenario_context": _notification_prefs_blob(),
            "sb_business_goal": "",
            "sb_workflow_name": "Notification preferences",
            "sb_changed_areas_bulk": "",
            "sb_known_dependencies_bulk": "",
        }
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Disable All Notification Methods - Blocked",
        linked_ac_texts=["System blocks save when all delivery methods are disabled."],
        expanded_context=exp,
        intent=None,
    )
    blob = " ".join(s.lower() for s in steps)
    assert "block" in blob or "reject" in blob or "not" in blob
    assert "success messaging" not in blob
    assert "saved successfully" not in blob


def test_propose_test_steps_for_all_active_tcs_is_deterministic() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email on profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can save email.",
        "sb_ac_0_map": ["TC-01", "TC-02"],
        "sb_n_tc": 2,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "Provider - Update Email - Valid Save",
        "sb_tc_0_active": True,
        "sb_tc_1_id": "TC-02",
        "sb_tc_1_text": "Provider - Invalid Email Format",
        "sb_tc_1_active": True,
    }
    a = propose_test_steps_for_all_active_tcs(sess)
    b = propose_test_steps_for_all_active_tcs(sess)
    assert a == b


def test_active_tc_indices_respects_inactive() -> None:
    sess = {
        "sb_n_tc": 2,
        "sb_tc_0_active": True,
        "sb_tc_1_active": False,
    }
    assert active_tc_indices(sess) == [0]

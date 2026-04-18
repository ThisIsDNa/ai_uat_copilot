"""v1 cleanup: dedupe, negative inputs, toggle isolation, action/entity consistency."""

from __future__ import annotations

from unittest.mock import patch

from src.scenario_builder_steps_gen import generate_default_test_steps
from src.scenario_builder_tc_gen import derive_negative_test_case_title_from_ac, propose_test_cases_from_acceptance_criteria
from src.scenario_context_expansion import expand_scenario_context
from src.scenario_suite_optimizer import semantic_dedupe_positive_proposals_final
from src.scenario_test_case_intent import infer_test_case_intent
from tests.test_scenario_type_detection import _notification_prefs_blob


def test_negative_invalid_email_step_uses_malformed_value() -> None:
    exp = expand_scenario_context(
        scenario_context="Provider updates email and phone. Invalid email shows inline error.",
        workflow_name="Profile",
    )
    intent = infer_test_case_intent(
        test_case_title="Provider - Invalid Email Format",
        linked_acceptance_criteria=["Invalid email rejected."],
        criterion_text_only="",
        expanded=exp,
        is_negative=True,
        forced_condition="invalid_format",
        negative_field_variant=0,
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Invalid Email Format",
        linked_ac_texts=["Invalid email rejected."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert "qa.provider@" in blob or "not_an_email" in blob or "malformed" in blob
    assert "6505551234" in blob


def test_negative_missing_phone_step_clears_phone() -> None:
    exp = expand_scenario_context(
        scenario_context="Provider updates email and phone. Phone required.",
        workflow_name="Profile",
    )
    intent = infer_test_case_intent(
        test_case_title="Provider - Missing Required Phone",
        linked_acceptance_criteria=["Phone required."],
        criterion_text_only="",
        expanded=exp,
        is_negative=True,
        forced_condition="required_missing",
        negative_field_variant=1,
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Missing Required Phone",
        linked_ac_texts=["Phone required."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert "clear" in blob and "phone" in blob


def test_generate_notes_negative_title_does_not_say_generate_reply() -> None:
    blob = "Clinician uses **Generate Notes** after **meeting**; **notes draft** in panel."
    exp = expand_scenario_context(scenario_context=blob, workflow_name="Notes")
    joined = " ".join(
        derive_negative_test_case_title_from_ac("Generation respects permissions.", variant=v, expanded=exp).lower()
        for v in range(5)
    )
    assert "generate reply" not in joined
    assert "generate notes" in joined or "primary" in joined or "permission" in joined or "blocked" in joined


def test_toggle_scenario_steps_avoid_profile_contact_email_phone_templates() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    intent = infer_test_case_intent(
        test_case_title="Provider - Save Valid Notification Preferences",
        linked_acceptance_criteria=["Save notification preferences."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "notification_preferences",
            "verification_focus": "valid_save",
            "intent_hint": "Save Valid Notification Preferences",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Save Valid Notification Preferences",
        linked_ac_texts=["Save notification preferences."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert "650555" not in blob
    assert "qa.profile@" not in blob
    assert "contact update" not in blob


def test_semantic_final_merges_duplicate_action_event_surface_rows() -> None:
    blob = "Clinician uses **Generate Notes**; **notes draft** for **meeting**."
    sess = {
        "sb_scenario_context": blob,
        "sb_business_goal": "",
        "sb_workflow_name": "Notes",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 6,
    }
    for i in range(6):
        sess[f"sb_ac_{i}_id"] = f"AC-{i + 1:02d}"
        sess[f"sb_ac_{i}_text"] = "stub"
    p1 = {
        "ac_index": 1,
        "ac_id": "AC-02",
        "criterion": "Draft appears.",
        "title": "Clinician - Notes Draft Appears After Generation",
    }
    p2 = {
        "ac_index": 5,
        "ac_id": "AC-06",
        "criterion": "Draft visible.",
        "title": "Clinician - Notes Draft Visible In Panel",
    }
    out = semantic_dedupe_positive_proposals_final([p1, p2], sess)
    assert len(out) == 1


def test_propose_steps_does_not_invoke_batch_semantic_final() -> None:
    from src.scenario_builder_steps_gen import propose_test_steps_for_all_active_tcs

    sess = {
        "sb_scenario_context": "Notes **Generate Notes** **meeting**.",
        "sb_business_goal": "",
        "sb_workflow_name": "N",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_tc": 1,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "Clinician - Generate Notes Draft",
        "sb_tc_0_active": True,
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "Generate notes.",
    }
    with patch("src.scenario_suite_optimizer.semantic_dedupe_positive_proposals_final") as m_sem:
        propose_test_steps_for_all_active_tcs(sess)
        m_sem.assert_not_called()


def test_batch_propose_tc_invokes_semantic_final() -> None:
    sess = {
        "sb_scenario_context": "**Generate Notes** **meeting** **notes draft**.",
        "sb_business_goal": "",
        "sb_workflow_name": "N",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can generate notes.",
    }
    with patch("src.scenario_suite_optimizer.semantic_dedupe_positive_proposals_final") as m_sem:
        m_sem.side_effect = lambda proposals, _sess: list(proposals)
        propose_test_cases_from_acceptance_criteria(sess)
        m_sem.assert_called_once()

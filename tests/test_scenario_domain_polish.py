"""Domain polish: action/entity extraction, titles, steps, semantic dedupe, contamination, batch isolation."""

from __future__ import annotations

from unittest.mock import patch

from src.scenario_builder_steps_gen import generate_default_test_steps, propose_test_steps_for_all_active_tcs
from src.scenario_builder_tc_gen import propose_test_cases_from_acceptance_criteria
from src.scenario_context_expansion import expand_scenario_context
from src.scenario_domain_labels import (
    enrich_suggested_fix_lines,
    extract_primary_action_label,
    filter_cross_scenario_rule_noise,
    infer_domain_naming,
)
from src.scenario_suite_optimizer import semantic_dedupe_positive_proposals_final
from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent


def test_extract_primary_action_from_bold_and_patterns() -> None:
    assert extract_primary_action_label("Use **Generate Notes** for the meeting.") == "Generate Notes"
    assert extract_primary_action_label("Agent runs **Generate Reply** then reviews.") == "Generate Reply"
    assert "submit" in extract_primary_action_label('Click "Submit Enrollment" to continue.').lower()


def test_infer_domain_naming_notes_meeting_reply_conversation() -> None:
    n1 = infer_domain_naming("Generate meeting notes draft for the active meeting.")
    assert n1.artifact_singular == "notes draft"
    assert n1.record_singular == "meeting"

    n2 = infer_domain_naming("Generate reply draft in the closed conversation thread.")
    assert n2.artifact_singular == "reply draft"
    assert n2.record_singular == "conversation"


def test_expand_context_sets_action_and_entity_labels() -> None:
    blob = (
        "Clinician opens an active **meeting** and uses **Generate Notes**. "
        "A **notes draft** appears in the panel."
    )
    exp = expand_scenario_context(scenario_context=blob, workflow_name="Visit notes")
    assert exp.primary_action_label == "Generate Notes"
    assert exp.artifact_label_singular == "notes draft"
    assert exp.domain_record_label == "meeting"
    joined = " ".join(exp.action_event_lines).lower()
    assert "generate notes" in joined
    assert "described system workflow" not in joined
    assert "user-triggered control invokes" not in joined


def test_positive_titles_use_concrete_action_not_generic_workflow() -> None:
    blob = "Support agent uses **Generate Reply**; **reply draft** in the response panel."
    exp = expand_scenario_context(scenario_context=blob, workflow_name="Support")
    intent = infer_test_case_intent(
        criterion_text_only="Authorized user can trigger generation and see a draft.",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "generate_action",
            "verification_focus": "action_trigger_success",
            "intent_hint": "Generate Reply Draft",
        },
    )
    title = format_positive_title_from_intent(intent, expanded=exp).lower()
    assert "generate reply" in title
    assert "primary workflow" not in title
    assert "described system" not in title


def test_action_event_steps_use_domain_nouns_not_generic_artifact_record() -> None:
    blob = (
        "Clinician opens **meeting** and clicks **Generate Notes**. "
        "**Notes draft** appears in the notes draft panel."
    )
    exp = expand_scenario_context(scenario_context=blob, workflow_name="Notes")
    intent = infer_test_case_intent(
        test_case_title="Clinician - Generate Notes Draft",
        linked_acceptance_criteria=["Trigger Generate Notes and verify draft."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "generate_action",
            "verification_focus": "action_trigger_success",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Clinician - Generate Notes Draft",
        linked_ac_texts=["Trigger Generate Notes and verify draft."],
        expanded_context=exp,
        intent=intent,
    )
    blob_steps = " ".join(steps).lower()
    assert "generate notes" in blob_steps
    assert "notes draft" in blob_steps
    assert "meeting" in blob_steps
    # Core path should not use generic placeholders for the primary flow
    assert "artifact" not in blob_steps
    assert "current record" not in blob_steps


def test_semantic_dedupe_collapses_duplicate_surface_action_event_rows() -> None:
    """Second-pass merge collapses near-duplicate surface cases (batch proposals)."""
    blob = "Clinician uses **Generate Notes** for an active **meeting**. **Notes draft** in panel."
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
        "criterion": "Notes draft appears after generation.",
        "title": "Clinician - Notes Draft Appears After Generation",
    }
    p2 = {
        "ac_index": 5,
        "ac_id": "AC-06",
        "criterion": "Notes draft is visible in the panel.",
        "title": "Clinician - Notes Draft Visible In Panel",
    }
    out = semantic_dedupe_positive_proposals_final([p1, p2], sess)
    assert len(out) == 1
    merged = out[0].get("merged_ac_indices") or []
    assert set(merged) == {1, 5}


def test_action_event_validation_rules_drop_cross_field_noise_without_source() -> None:
    blob = "User runs **Generate Notes** for a **meeting**; **notes draft** is shown."
    exp = expand_scenario_context(scenario_context=blob, workflow_name="Notes")
    rules = "\n".join(exp.validation_rules).lower()
    assert "cross-field" not in rules
    assert "forbidden combination" not in rules
    assert "at least one method" not in rules

    noisy = filter_cross_scenario_rule_noise(
        [
            "Cross-field rules (e.g. at least one method on) are enforced: forbidden combinations cannot be saved silently."
        ],
        blob=blob,
        primary_type="action_event_flow",
    )
    assert noisy == []


def test_propose_test_steps_batch_does_not_invoke_semantic_tc_dedupe() -> None:
    """Semantic dedupe runs only on batch TC proposals, not per-row step regeneration."""
    blob = "Clinician uses **Generate Notes**; **notes draft** for the **meeting**."
    sess = {
        "sb_scenario_context": blob,
        "sb_business_goal": "",
        "sb_workflow_name": "Notes",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_tc": 1,
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": "Clinician - Generate Notes Draft",
        "sb_tc_0_active": True,
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can generate notes and see a draft.",
    }
    with patch("src.scenario_suite_optimizer.semantic_dedupe_positive_proposals_final") as m_sem:
        out = propose_test_steps_for_all_active_tcs(sess)
        m_sem.assert_not_called()
    assert out and out[0].get("steps")


def test_batch_propose_test_cases_invokes_semantic_dedupe() -> None:
    blob = "Clinician uses **Generate Notes**; **notes draft** for the **meeting**."
    sess = {
        "sb_scenario_context": blob,
        "sb_business_goal": "",
        "sb_workflow_name": "Notes",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can generate notes and see a draft.",
    }
    with patch("src.scenario_suite_optimizer.semantic_dedupe_positive_proposals_final") as m_sem:
        m_sem.side_effect = lambda proposals, _sess: list(proposals)
        propose_test_cases_from_acceptance_criteria(sess)
        m_sem.assert_called_once()


def test_enrich_suggested_fix_lines_uses_domain_action_and_artifact() -> None:
    data = {
        "scenario_context": "Use **Generate Notes** after the **meeting**; **notes draft** in panel.",
        "workflow_name": "Visit",
    }
    out = enrich_suggested_fix_lines(["Include steps to verify disabled controls."], data)
    assert out
    low = out[0].lower()
    assert "generate notes" in low
    assert "notes draft" in low or "draft" in low

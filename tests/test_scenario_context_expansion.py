"""Context expansion for AI generation (Scenario Context + related fields)."""

from __future__ import annotations

from src.scenario_builder_ac_gen import generate_acceptance_criteria_suggestions
from src.scenario_builder_steps_gen import generate_default_test_steps
from src.scenario_builder_tc_gen import derive_negative_test_case_title_from_ac, derive_test_case_title_from_ac
from src.scenario_context_expansion import expand_scenario_context, expanded_context_from_builder_session


def test_expand_scenario_context_extracts_fields_and_entity() -> None:
    exp = expand_scenario_context(
        scenario_context="Provider updates email and phone. Email valid format. Phone 10 digits. Save shows confirmation.",
        business_goal="Reduce profile errors.",
        workflow_name="Patient profile",
        changed_areas_bulk="",
        known_dependencies_bulk="Auth API",
    )
    assert "email" in exp.fields_involved
    assert "phone" in exp.fields_involved
    assert exp.primary_entity.lower() == "provider"
    assert "### Author scenario context" in exp.summary_for_prompt


def test_ac_suggestions_use_expanded_validation() -> None:
    exp = expand_scenario_context(
        scenario_context="Email must be valid format. Phone must be 10 digits.",
        business_goal="",
        workflow_name="",
        changed_areas_bulk="",
        known_dependencies_bulk="",
    )
    out = generate_acceptance_criteria_suggestions(
        business_goal="Improve data quality.",
        changed_areas_bulk="",
        expanded=exp,
    )
    assert out
    joined = " ".join(out).lower()
    assert "email" in joined or "phone" in joined or "validation" in joined


def test_positive_title_entity_action_with_expansion() -> None:
    exp = expand_scenario_context(
        scenario_context="Provider updates contact info.",
        business_goal="",
        workflow_name="",
        changed_areas_bulk="",
        known_dependencies_bulk="",
    )
    t = derive_test_case_title_from_ac("User can save updated email and phone.", expanded=exp)
    assert " - " in t
    assert "provider" in t.lower()
    assert len(t) <= 120


def test_negative_title_varies_with_fields() -> None:
    exp = expand_scenario_context(
        scenario_context="Email and phone required.",
        business_goal="",
        workflow_name="",
        changed_areas_bulk="",
        known_dependencies_bulk="",
    )
    a = derive_negative_test_case_title_from_ac("User can update profile.", variant=0, expanded=exp)
    b = derive_negative_test_case_title_from_ac("User can update profile.", variant=1, expanded=exp)
    assert a.lower() != b.lower()


def test_steps_use_expanded_summary() -> None:
    exp = expand_scenario_context(
        scenario_context="Use the patient demographics tab. Save persists email.",
        business_goal="",
        workflow_name="Chart update",
        changed_areas_bulk="",
        known_dependencies_bulk="",
    )
    steps = generate_default_test_steps(
        test_case_title="Submit profile changes",
        linked_ac_texts=["User can save profile."],
        expanded_context=exp,
    )
    blob = " ".join(steps).lower()
    assert "navigate" in blob
    assert "verify" in blob or "confirm" in blob or "validate" in blob


def test_expanded_context_from_session_defaults() -> None:
    sess = {
        "sb_scenario_context": "",
        "sb_business_goal": "",
        "sb_workflow_name": "",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    assert exp.primary_entity == "User"

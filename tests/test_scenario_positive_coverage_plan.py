"""Batch positive coverage planning (field distribution + titles)."""

from __future__ import annotations

from src.scenario_builder_steps_gen import generate_default_test_steps
from src.scenario_builder_tc_gen import propose_test_cases_from_acceptance_criteria
from src.scenario_context_expansion import expanded_context_from_builder_session
from src.scenario_positive_coverage_plan import (
    build_positive_coverage_plan_for_session,
    consolidate_positive_coverage_plan,
)
from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent


def test_coverage_plan_distributes_email_and_phone() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone. Save and confirmation.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 4,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "System validates contact fields.",
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": "System validates contact fields.",
        "sb_ac_2_id": "AC-03",
        "sb_ac_2_text": "System validates contact fields.",
        "sb_ac_3_id": "AC-04",
        "sb_ac_3_text": "System validates contact fields.",
    }
    exp = expanded_context_from_builder_session(sess)
    plan = build_positive_coverage_plan_for_session(sess, exp)
    scopes = [plan[i]["target_scope"] for i in sorted(plan)]
    assert "email" in scopes and "phone" in scopes
    hints = [plan[i]["intent_hint"] for i in sorted(plan)]
    assert len(set(hints)) == len(hints)


def test_propose_titles_distinct_no_trailing_dash() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 3,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "System saves contact updates.",
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": "System saves contact updates.",
        "sb_ac_2_id": "AC-03",
        "sb_ac_2_text": "System saves contact updates.",
    }
    out = propose_test_cases_from_acceptance_criteria(sess)
    titles = [x["title"] for x in out]
    assert len({t.lower() for t in titles}) == 3
    for t in titles:
        assert not t.rstrip().endswith(("-", "–", "—"))
        assert t.split(" - ")[-1].strip()


def test_phone_focused_steps_mention_phone_not_only_email() -> None:
    exp = expanded_context_from_builder_session(
        {
            "sb_scenario_context": "Provider updates email and phone.",
            "sb_business_goal": "",
            "sb_workflow_name": "Profile",
            "sb_changed_areas_bulk": "",
            "sb_known_dependencies_bulk": "",
        }
    )
    intent = infer_test_case_intent(
        test_case_title="Provider - Update Phone - Valid Save",
        linked_acceptance_criteria=["Phone must save with valid 10-digit format."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "phone",
            "verification_focus": "valid_save",
            "intent_hint": "Update Phone - Valid Save",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Update Phone - Valid Save",
        linked_ac_texts=["Phone must save with valid 10-digit format."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(steps).lower()
    assert "6505551234" in blob
    assert "phone" in blob


def test_contact_persist_scope_uses_both_fields_in_apply() -> None:
    exp = expanded_context_from_builder_session(
        {
            "sb_scenario_context": "Provider updates email and phone.",
            "sb_business_goal": "",
            "sb_workflow_name": "Profile",
            "sb_changed_areas_bulk": "",
            "sb_known_dependencies_bulk": "",
        }
    )
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
    assert "email" in blob and "phone" in blob
    assert "refresh" in blob or "re-open" in blob


def test_consolidate_caps_duplicate_confirmation_slots() -> None:
    base_sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 0,
    }
    exp = expanded_context_from_builder_session(base_sess)
    plan = {
        0: {
            "ac_index": 0,
            "ac_id": "AC-01",
            "target_scope": "confirmation",
            "verification_focus": "confirmation_message",
            "intent_hint": "Save Confirmation Message",
            "forced_condition": "confirmation_check",
            "criterion_excerpt": "c",
        },
        1: {
            "ac_index": 1,
            "ac_id": "AC-02",
            "target_scope": "confirmation",
            "verification_focus": "confirmation_message",
            "intent_hint": "Phone Save Confirmation",
            "forced_condition": "confirmation_check",
            "criterion_excerpt": "c",
        },
    }
    out = consolidate_positive_coverage_plan(plan, exp, base_sess)
    n_conf = sum(1 for v in out.values() if v.get("verification_focus") == "confirmation_message")
    assert n_conf <= 1


def test_consolidate_replaces_redundant_generic_persistence_when_both_fields() -> None:
    base_sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 0,
    }
    exp = expanded_context_from_builder_session(base_sess)
    plan = {
        0: {
            "ac_index": 0,
            "ac_id": "AC-01",
            "target_scope": "persistence",
            "verification_focus": "persistence_after_refresh",
            "intent_hint": "Persist Updated Values",
            "forced_condition": "persisted_state_check",
            "criterion_excerpt": "x",
        },
        1: {
            "ac_index": 1,
            "ac_id": "AC-02",
            "target_scope": "persistence",
            "verification_focus": "persistence_after_refresh",
            "intent_hint": "Persist After Refresh",
            "forced_condition": "persisted_state_check",
            "criterion_excerpt": "x",
        },
    }
    out = consolidate_positive_coverage_plan(plan, exp, base_sess)
    assert out[0]["intent_hint"] != out[1]["intent_hint"]


def test_propose_positive_titles_still_distinct_after_consolidation() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 4,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "System saves contact updates.",
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": "System saves contact updates.",
        "sb_ac_2_id": "AC-03",
        "sb_ac_2_text": "System saves contact updates.",
        "sb_ac_3_id": "AC-04",
        "sb_ac_3_text": "System saves contact updates.",
    }
    titles = [x["title"] for x in propose_test_cases_from_acceptance_criteria(sess)]
    assert len({t.lower() for t in titles}) == len(titles)


def test_format_positive_title_strips_trailing_separators() -> None:
    from src.scenario_test_case_intent import TestCaseIntent

    intent = TestCaseIntent(
        entity="User",
        title_phrase="Save Check —",
        condition_type="happy_path",
        target_scope="email",
        verification_focus="valid_save",
    )
    t = format_positive_title_from_intent(intent, expanded=None)
    assert not t.endswith("-")
    assert not t.endswith("–") and not t.endswith("—")

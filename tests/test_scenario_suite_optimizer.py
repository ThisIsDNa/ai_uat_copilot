"""Batch suite optimization: functional dedupe of proposed test cases."""

from __future__ import annotations

import pathlib

from src.scenario_builder_steps_gen import generate_default_test_steps
from src.scenario_suite_optimizer import (
    _norm_ws,
    optimize_generated_test_suite,
    optimize_negative_test_case_proposals,
    optimize_positive_test_case_proposals,
    semantic_dedupe_positive_proposals_final,
)


def _sess_profile_email_phone() -> dict:
    return {
        "sb_scenario_context": "Provider updates email and phone on the profile. Save shows confirmation.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 0,
    }


def test_positive_confirmation_cluster_keeps_one_representative_with_merge_metadata() -> None:
    sess = _sess_profile_email_phone()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "User receives a confirmation toast after saving contact changes.",
            "title": "Provider - Save Confirmation Message",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "A success banner appears when the user saves valid phone and email.",
            "title": "Provider - Phone Save Confirmation",
        },
        {
            "ac_index": 2,
            "ac_id": "AC-03",
            "criterion": "Confirmation message is shown after successful profile save.",
            "title": "Provider - Email Save Confirmation",
        },
    ]
    out = optimize_positive_test_case_proposals(proposals, sess)
    assert len(out) == 1
    assert out[0].get("merged_ac_indices") == [0, 1, 2]
    rhs = out[0]["title"].split(" - ", 1)[-1].lower()
    assert "re-check" not in rhs
    assert any(
        p["ac_index"] == out[0]["ac_index"]
        and p["criterion"] == out[0]["criterion"]
        and _norm_ws(p["title"]) == _norm_ws(out[0]["title"])
        for p in proposals
    )


def test_positive_persistence_email_vs_contact_not_collapsed() -> None:
    sess = _sess_profile_email_phone()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "Email persists after refresh.",
            "title": "Provider - Email Persist After Refresh",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "Contact info persists after refresh.",
            "title": "Provider - Contact Info - Persist After Refresh",
        },
    ]
    out = optimize_positive_test_case_proposals(proposals, sess)
    assert len(out) == 2


def test_positive_valid_save_email_and_phone_preserved() -> None:
    sess = _sess_profile_email_phone()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "Valid email saves.",
            "title": "Provider - Update Email - Valid Save",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "Valid phone saves.",
            "title": "Provider - Update Phone - Valid Save",
        },
    ]
    out = optimize_positive_test_case_proposals(proposals, sess)
    assert len(out) == 2


def test_positive_duplicate_valid_save_same_field_merges() -> None:
    sess = _sess_profile_email_phone()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "System saves valid email on profile.",
            "title": "Provider - Update Email - Valid Save",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "Profile accepts and stores a valid email address.",
            "title": "Provider - Update Email - Valid Save",
        },
    ]
    out = optimize_positive_test_case_proposals(proposals, sess)
    assert len(out) == 1
    assert out[0]["merged_ac_indices"] == [0, 1]


def test_negative_optimizer_conservative_distinct_failure_modes_remain() -> None:
    sess = _sess_profile_email_phone()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "Email required.",
            "title": "Provider - Missing Required Email",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "Phone format validated.",
            "title": "Provider - Invalid Phone Format",
        },
    ]
    out = optimize_negative_test_case_proposals(proposals, sess)
    assert len(out) == 2


def test_optimize_generated_test_suite_deterministic() -> None:
    sess = _sess_profile_email_phone()
    pos = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "Toast after save.",
            "title": "Provider - Save Confirmation Message",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "Banner after save.",
            "title": "Provider - Save Confirmation Message",
        },
    ]
    neg = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "x",
            "title": "Provider - Missing Required Email",
        },
    ]
    a = optimize_generated_test_suite(positive_proposals=pos, negative_proposals=neg, sess=sess)
    b = optimize_generated_test_suite(positive_proposals=pos, negative_proposals=neg, sess=sess)
    assert a == b


def test_step_generation_module_does_not_invoke_suite_optimizer() -> None:
    p = pathlib.Path(__file__).resolve().parents[1] / "src" / "scenario_builder_steps_gen.py"
    text = p.read_text(encoding="utf-8")
    assert "scenario_suite_optimizer" not in text


def test_generate_default_test_steps_does_not_reference_optimizer() -> None:
    steps = generate_default_test_steps(test_case_title="Submit enrollment", linked_ac_texts=None)
    assert len(steps) >= 3


def _sess_action_event_generate_reply() -> dict:
    return {
        "sb_scenario_context": (
            "User clicks Generate Reply on an active conversation. "
            "A reply draft appears in the panel. User may edit before send."
        ),
        "sb_business_goal": "",
        "sb_workflow_name": "Inbox",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 0,
    }


def test_action_event_stale_update_required_fields_proposal_dropped() -> None:
    sess = _sess_action_event_generate_reply()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "Placeholder",
            "title": "Update Required Fields",
        },
    ]
    out = semantic_dedupe_positive_proposals_final(proposals, sess)
    assert out == []


def test_semantic_merge_keeps_ac_bundle_aligned_with_best_title() -> None:
    """
    When two positives collapse, criterion/ac_index must come from the row whose title
    was selected (not from a different sorted 'winner').
    """
    sess = _sess_action_event_generate_reply()
    proposals = [
        {
            "ac_index": 0,
            "ac_id": "AC-01",
            "criterion": "Weak duplicate surface check.",
            "title": "User - Generate Reply - Surface",
        },
        {
            "ac_index": 1,
            "ac_id": "AC-02",
            "criterion": "Clicking Generate Reply inserts AI draft text into the reply panel.",
            "title": "User - Generate Reply Draft - Stronger Artifact Wording Here",
        },
    ]
    out = semantic_dedupe_positive_proposals_final(proposals, sess)
    assert len(out) == 1, out
    assert any(
        p["ac_index"] == out[0]["ac_index"]
        and p["criterion"] == out[0]["criterion"]
        and _norm_ws(p["title"]) == _norm_ws(out[0]["title"])
        for p in proposals
    )

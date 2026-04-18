"""Scenario type detection and routing for generation."""

from __future__ import annotations

from src.scenario_builder_ac_gen import generate_acceptance_criteria_suggestions
from src.scenario_builder_steps_gen import generate_default_test_steps
from src.scenario_builder_tc_gen import derive_negative_test_case_title_from_ac
from src.scenario_context_expansion import expand_scenario_context, expanded_context_from_builder_session
from src.scenario_positive_coverage_plan import build_positive_coverage_plan_for_session
from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent
from src.scenario_type_detection import detect_scenario_type


def _notification_prefs_blob() -> str:
    return (
        "Provider manages notification preferences: email notifications ON/OFF, SMS notifications ON/OFF. "
        "At least one delivery method must remain enabled. Save shows confirmation. Preferences persist after reload. "
        "Users without the correct permission cannot change preferences."
    )


def test_notification_scenario_classified_state_toggle_and_business_rule() -> None:
    d = detect_scenario_type(scenario_context=_notification_prefs_blob())
    assert d["primary_type"] == "state_toggle"
    assert "business_rule" in d["secondary_types"] or d["signals"]["cross_field_constraint"]
    assert d["signals"]["toggle_terms"]
    assert d["routing_hints"]["prefer_state_transitions"] is True
    assert d["routing_hints"]["prefer_input_format_validation"] is False


def test_toggle_scenario_expansion_avoids_email_format_ac_unless_explicit() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    joined_rules = " ".join(exp.validation_rules).lower()
    assert "invalid email format" not in joined_rules
    assert "### Scenario type (routing)" in exp.summary_for_prompt


def test_positive_titles_use_toggle_language_not_update_email_valid_save() -> None:
    sess = {
        "sb_scenario_context": _notification_prefs_blob(),
        "sb_business_goal": "",
        "sb_workflow_name": "Notification preferences",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 3,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "System allows enabling email notifications.",
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": "System blocks save when all methods disabled.",
        "sb_ac_2_id": "AC-03",
        "sb_ac_2_text": "Preferences persist after reload.",
    }
    exp = expanded_context_from_builder_session(sess)
    plan = build_positive_coverage_plan_for_session(sess, exp)
    titles = []
    for i in (0, 1, 2):
        crit = str(sess.get(f"sb_ac_{i}_text") or "")
        slot = plan.get(i)
        intent = infer_test_case_intent(
            criterion_text_only=crit,
            expanded=exp,
            is_negative=False,
            coverage_slot=slot,
        )
        titles.append(format_positive_title_from_intent(intent, expanded=exp).lower())
    blob = " ".join(titles)
    assert "update email - valid save" not in blob
    assert any(x in blob for x in ("enable email", "disable sms", "block", "persist", "preference"))


def test_negative_titles_for_toggle_scenario_include_blocked_or_permission_not_only_email_format() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    variants = [derive_negative_test_case_title_from_ac("User updates preferences.", variant=v, expanded=exp) for v in range(5)]
    joined = " ".join(v.lower() for v in variants)
    assert "invalid email format" not in joined
    assert any(
        "blocked" in v.lower() or "permission" in v.lower() or "dependency" in v.lower() for v in variants
    )


def test_steps_for_enable_email_notifications_use_on_off_language() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    intent = infer_test_case_intent(
        test_case_title="Provider - Enable Email Notifications",
        linked_acceptance_criteria=["Enable email notifications and save."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "email_toggle",
            "verification_focus": "enable_transition",
            "intent_hint": "Enable Email Notifications",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Enable Email Notifications",
        linked_ac_texts=["Enable email notifications and save."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(s.lower() for s in steps)
    assert "turn" in blob or "on" in blob
    assert "save" in blob


def test_block_all_notifications_title_treated_as_positive_rule_test() -> None:
    from src.scenario_test_case_intent import is_negative_test_case_title

    assert is_negative_test_case_title("Provider - Block All Notifications Disabled") is False


def test_hybrid_form_and_validation_still_gets_format_signals() -> None:
    d = detect_scenario_type(
        scenario_context="User enters email address with valid format. Invalid email format is rejected before save."
    )
    assert d["signals"]["text_input_validation"] is True
    assert d["routing_hints"]["prefer_input_format_validation"] is True


def test_ac_suggestions_include_rule_language_for_toggle_scenario() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    lines = generate_acceptance_criteria_suggestions(
        business_goal="Reduce support tickets.",
        changed_areas_bulk="",
        expanded=exp,
    )
    blob = " ".join(lines).lower()
    assert "toggle" in blob or "notification" in blob or "persist" in blob or "block" in blob


def test_strict_gating_coerces_missing_data_negative_on_toggle_without_explicit_input_cues() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    intent = infer_test_case_intent(
        test_case_title="User - Save With Missing Data",
        linked_acceptance_criteria=["Preferences must persist after save."],
        criterion_text_only="",
        expanded=exp,
        is_negative=True,
        negative_field_variant=0,
    )
    assert intent.condition_type != "required_missing"
    assert intent.condition_type in ("rule_blocked", "permission_issue", "dependency_failure")


def test_explicit_invalid_email_in_title_preserves_format_negative_on_toggle_hybrid() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    intent = infer_test_case_intent(
        test_case_title="User - Invalid Email Format",
        linked_acceptance_criteria=["Invalid email format is rejected before save."],
        criterion_text_only="",
        expanded=exp,
        is_negative=True,
        negative_field_variant=0,
    )
    assert intent.condition_type == "invalid_format"


def test_approval_flow_negative_titles_avoid_email_format_family() -> None:
    sc = (
        "Manager reviews submitted expense. User submits for approval. "
        "Approve or reject transitions status from Pending to Approved or Rejected."
    )
    exp = expand_scenario_context(scenario_context=sc, workflow_name="Expense approval")
    assert exp.scenario_classification.get("primary_type") == "approval_or_status_flow"
    titles = [
        derive_negative_test_case_title_from_ac(
            "Delegated approver cannot approve outside their scope.",
            variant=v,
            expanded=exp,
        )
        for v in range(10)
    ]
    blob = " ".join(t.lower() for t in titles)
    assert "invalid email" not in blob
    assert "email boundary" not in blob
    assert "missing required email" not in blob


def test_misleading_email_persist_title_steps_avoid_enter_email_under_toggle_gating() -> None:
    exp = expand_scenario_context(scenario_context=_notification_prefs_blob())
    intent = infer_test_case_intent(
        test_case_title="Provider - Email Persist After Refresh",
        linked_acceptance_criteria=["Preferences persist after reload."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot=None,
    )
    steps = generate_default_test_steps(
        test_case_title="Provider - Email Persist After Refresh",
        linked_ac_texts=["Preferences persist after reload."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(s.lower() for s in steps)
    assert "enter **email**" not in blob
    assert "change **email**" not in blob
    assert "turn" in blob or "on" in blob or "off" in blob or "channel" in blob or "toggle" in blob or "notification" in blob


def test_form_input_scenario_still_allows_format_negative_titles() -> None:
    sc = "User updates profile email and phone; invalid email format is rejected; 10-digit phone required."
    exp = expand_scenario_context(scenario_context=sc)
    assert exp.scenario_classification.get("primary_type") == "form_input"
    titles = [
        derive_negative_test_case_title_from_ac("Invalid email is rejected on save.", variant=v, expanded=exp)
        for v in range(12)
    ]
    blob = " ".join(t.lower() for t in titles)
    assert "invalid" in blob or "format" in blob or "email" in blob

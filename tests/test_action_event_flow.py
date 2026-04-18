"""action_event_flow: detection, expansion, AC, titles, negatives, steps, clustering."""

from __future__ import annotations

from src.scenario_builder_ac_gen import generate_acceptance_criteria_suggestions
from src.scenario_builder_steps_gen import generate_default_test_steps
from src.scenario_builder_tc_gen import derive_negative_test_case_title_from_ac
from src.scenario_context_expansion import expand_scenario_context
from src.scenario_positive_coverage_plan import build_positive_coverage_plan_for_session, consolidate_positive_coverage_plan
from src.scenario_suite_optimizer import _positive_functional_cluster_key
from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent
from src.scenario_type_detection import detect_scenario_type


def _startup_ai_support_blob() -> str:
    return (
        "Support agent uses **Generate Reply** in the support console. Clicking creates an AI reply **draft** in the "
        "draft response panel. The draft stays in **Draft** state and is **not** auto-sent. "
        "**Closed** conversations block generation. Only **support-agent** or **admin** can generate. "
        "If the **AI service fails**, the system shows an **error** and **inserts no draft**. "
        "Drafts **persist** in the dashboard after **refresh**."
    )


def test_startup_ai_scenario_classified_action_event_flow() -> None:
    d = detect_scenario_type(scenario_context=_startup_ai_support_blob())
    assert d["primary_type"] == "action_event_flow"
    assert d["routing_hints"].get("prefer_action_trigger_steps") is True
    assert d["routing_hints"].get("prefer_input_format_validation") is False
    assert d["signals"].get("action_event_core") is True


def test_ac_generation_covers_draft_permission_blocked_failure() -> None:
    exp = expand_scenario_context(scenario_context=_startup_ai_support_blob())
    lines = generate_acceptance_criteria_suggestions(
        business_goal="Speed up support responses.",
        changed_areas_bulk="",
        expanded=exp,
    )
    blob = " ".join(lines).lower()
    assert "draft" in blob
    assert "generate" in blob or "trigger" in blob or "primary" in blob
    assert "permission" in blob or "authorized" in blob
    assert ("closed" in blob or "block" in blob) and ("precondition" in blob or "block" in blob or "closed" in blob)
    assert "fail" in blob or "error" in blob or "no" in blob
    assert "persist" in blob or "refresh" in blob


def test_positive_titles_use_action_result_language() -> None:
    sess = {
        "sb_scenario_context": _startup_ai_support_blob(),
        "sb_business_goal": "",
        "sb_workflow_name": "Support AI replies",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 4,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "Authorized users can trigger Generate Reply and see a draft.",
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": "Draft remains Draft and is not auto-sent.",
        "sb_ac_2_id": "AC-03",
        "sb_ac_2_text": "Closed conversation blocks generation.",
        "sb_ac_3_id": "AC-04",
        "sb_ac_3_text": "Draft persists after refresh.",
    }
    exp = expand_scenario_context(
        scenario_context=str(sess.get("sb_scenario_context") or ""),
        workflow_name=str(sess.get("sb_workflow_name") or ""),
    )
    plan = consolidate_positive_coverage_plan(
        build_positive_coverage_plan_for_session(sess, exp),
        exp,
        sess,
    )
    titles = []
    for i in range(4):
        crit = str(sess.get(f"sb_ac_{i}_text") or "")
        slot = plan.get(i)
        intent = infer_test_case_intent(
            criterion_text_only=crit,
            expanded=exp,
            is_negative=False,
            coverage_slot=slot,
        )
        titles.append(format_positive_title_from_intent(intent, expanded=exp).lower())
    joined = " ".join(titles)
    assert "save updated record" not in joined
    assert any(k in joined for k in ("draft", "generate", "trigger", "artifact", "persist", "authorized", "auto"))


def test_negative_titles_avoid_format_drift_without_explicit_input_cues() -> None:
    exp = expand_scenario_context(scenario_context=_startup_ai_support_blob())
    titles = [
        derive_negative_test_case_title_from_ac("Generation must respect permissions.", variant=v, expanded=exp)
        for v in range(12)
    ]
    blob = " ".join(t.lower() for t in titles)
    assert "invalid email format" not in blob
    assert "boundary" not in blob or "boundary value" not in blob
    assert "missing required" not in blob


def test_steps_use_click_generate_draft_language() -> None:
    exp = expand_scenario_context(scenario_context=_startup_ai_support_blob())
    intent = infer_test_case_intent(
        test_case_title="Support Agent - Generate Reply Draft",
        linked_acceptance_criteria=["Click Generate Reply and verify draft appears."],
        criterion_text_only="",
        expanded=exp,
        is_negative=False,
        coverage_slot={
            "target_scope": "generate_action",
            "verification_focus": "action_trigger_success",
            "intent_hint": "Generate Reply Draft",
        },
    )
    steps = generate_default_test_steps(
        test_case_title="Support Agent - Generate Reply Draft",
        linked_ac_texts=["Click Generate Reply and verify draft appears."],
        expanded_context=exp,
        intent=intent,
    )
    blob = " ".join(s.lower() for s in steps)
    assert "generate reply" in blob or "click" in blob
    assert "enter **email**" not in blob
    assert "save updated record" not in blob


def test_suite_cluster_keys_split_draft_state_and_permission() -> None:
    from src.scenario_test_case_intent import TestCaseIntent

    exp = expand_scenario_context(scenario_context=_startup_ai_support_blob())
    i1 = TestCaseIntent(
        condition_type="happy_path",
        target_scope="draft_state",
        verification_focus="remains_draft",
    )
    i2 = TestCaseIntent(
        condition_type="permission_issue",
        target_scope="generate_action",
        verification_focus="action_trigger_success",
    )
    k1 = _positive_functional_cluster_key(i1, "Agent - Reply Draft Remains Draft State", ["a", "b"], exp)
    k2 = _positive_functional_cluster_key(i2, "Guest - Generate Reply Blocked", ["c", "d"], exp)
    assert k1 != k2
    assert "action_event_flow" in k1 and "action_event_flow" in k2


def test_hybrid_action_plus_explicit_format_keeps_format_validation_hints() -> None:
    sc = (
        _startup_ai_support_blob()
        + " Agents must enter a **tracking ticket ID** with exactly **10 alphanumeric characters**; "
        "**invalid format** is rejected before save."
    )
    d = detect_scenario_type(scenario_context=sc)
    assert d["primary_type"] == "action_event_flow"
    assert d["signals"].get("text_input_validation") is True
    assert d["routing_hints"].get("prefer_input_format_validation") is True


def _ae_exp() -> object:
    return expand_scenario_context(scenario_context=_startup_ai_support_blob())


def _assert_no_generic_save_scaffolding(steps: list[str]) -> None:
    blob = " ".join(s.lower() for s in steps)
    assert "save updated record" not in blob
    assert "verify save outcome" not in blob
    assert "trigger save, submit, or update" not in blob
    assert "click **save**" not in blob
    assert "field-level validation" not in blob
    assert "notification toggles" not in blob


def test_action_event_positive_steps_avoid_save_submit_scaffolding() -> None:
    exp = _ae_exp()
    for slot in (
        {"target_scope": "generate_action", "verification_focus": "action_trigger_success"},
        {"target_scope": "generated_draft", "verification_focus": "artifact_created"},
        {"target_scope": "draft_state", "verification_focus": "remains_draft"},
        {"target_scope": "draft_editability", "verification_focus": "editable_before_send"},
        {"target_scope": "action_persistence", "verification_focus": "persists_after_refresh"},
    ):
        intent = infer_test_case_intent(
            test_case_title="Support Agent - Generate Reply Draft",
            linked_acceptance_criteria=["Authorized users generate reply drafts."],
            expanded=exp,
            is_negative=False,
            coverage_slot=slot,
        )
        steps = generate_default_test_steps(
            test_case_title="Support Agent - Generate Reply Draft",
            linked_ac_texts=["Authorized users generate reply drafts."],
            expanded_context=exp,
            intent=intent,
        )
        _assert_no_generic_save_scaffolding(steps)
        joined = " ".join(s.lower() for s in steps)
        assert "verify" in joined
        assert "generate" in joined or "draft" in joined or "refresh" in joined or "click" in joined


def test_action_event_negative_steps_precondition_permission_failure() -> None:
    exp = _ae_exp()
    cases = [
        (
            "Closed Conversation - Generate Reply Blocked",
            ["Generation is blocked when the conversation is closed."],
        ),
        (
            "Unauthorized User - Generate Reply Blocked",
            ["Only support-agent or admin may generate reply drafts."],
        ),
        (
            "AI Service Failure - No Draft Inserted",
            ["When AI fails, show error and insert no draft."],
        ),
    ]
    for title, acs in cases:
        intent = infer_test_case_intent(
            test_case_title=title,
            linked_acceptance_criteria=acs,
            expanded=exp,
            is_negative=True,
        )
        steps = generate_default_test_steps(
            test_case_title=title,
            linked_ac_texts=acs,
            expanded_context=exp,
            intent=intent,
        )
        _assert_no_generic_save_scaffolding(steps)
        blob = " ".join(s.lower() for s in steps)
        assert "no" in blob or "block" in blob or "error" in blob or "permission" in blob or "disabled" in blob


def test_action_event_negative_title_only_routes_negative_templates() -> None:
    """Regression: negative titles must route to negative steps even when ``intent`` is not passed in."""
    exp = _ae_exp()
    cases = [
        (
            "Support Agent - Generate Reply Blocked By Preconditions",
            ["Generation is blocked when the conversation is closed."],
        ),
        (
            "Admin - Unauthorized User - Generate Reply Blocked",
            ["Only support-agent or admin may generate reply drafts."],
        ),
        (
            "Support - AI Service Failure - No Draft Inserted",
            ["When AI fails, show error and insert no draft."],
        ),
    ]
    banned_success = (
        "success messaging",
        "saved successfully",
        "still present",
        "visible artifact, state, and messaging",
        "verify save outcome",
        "confirmation-only",
    )
    for title, acs in cases:
        steps = generate_default_test_steps(
            test_case_title=title,
            linked_ac_texts=acs,
            expanded_context=exp,
            intent=None,
        )
        _assert_no_generic_save_scaffolding(steps)
        blob = " ".join(s.lower() for s in steps)
        assert "no" in blob or "not" in blob or "block" in blob or "error" in blob or "permission" in blob or "disabled" in blob
        for phrase in banned_success:
            assert phrase not in blob


def test_intent_is_negative_routes_negative_steps_even_if_title_shell_is_positive() -> None:
    """Regression: ``intent.is_negative`` must win over a neutral title so completion stays negative."""
    exp = _ae_exp()
    intent = infer_test_case_intent(
        test_case_title="Support Agent - Reply Draft In Panel",
        linked_acceptance_criteria=["Unauthorized users cannot generate reply drafts."],
        expanded=exp,
        is_negative=True,
    )
    acs = ["Unauthorized users cannot generate reply drafts."]
    steps = generate_default_test_steps(
        test_case_title="Support Agent - Reply Draft In Panel",
        linked_ac_texts=acs,
        expanded_context=exp,
        intent=intent,
    )
    _assert_no_generic_save_scaffolding(steps)
    blob = " ".join(s.lower() for s in steps)
    assert "permission" in blob or "no" in blob or "not" in blob or "denied" in blob or "disabled" in blob or "unavailable" in blob
    assert "success messaging" not in blob
    assert "verify save outcome" not in blob


def test_action_event_draft_state_steps_reference_draft_not_autosend() -> None:
    exp = _ae_exp()
    intent = infer_test_case_intent(
        test_case_title="Reply Draft - Remains Draft State",
        linked_acceptance_criteria=["Draft remains Draft and is not auto-sent."],
        expanded=exp,
        is_negative=False,
        coverage_slot={"target_scope": "draft_state", "verification_focus": "remains_draft"},
    )
    steps = generate_default_test_steps(
        test_case_title="Reply Draft - Remains Draft State",
        linked_ac_texts=["Draft remains Draft and is not auto-sent."],
        expanded_context=exp,
        intent=intent,
    )
    joined = " ".join(s.lower() for s in steps)
    assert "draft" in joined
    assert "auto" in joined or "send" in joined or "publish" in joined


def test_action_event_intent_phrase_no_trigger_primary_workflow_placeholder() -> None:
    from src.scenario_test_case_intent import _intent_phrase_positive

    low = "support agent uses generate reply in the console."
    phrase = _intent_phrase_positive("happy_path", "user", low, suppress_typed_contact_labels=False, target_scope="")
    assert "trigger primary" not in phrase.lower()
    assert "generate" in phrase.lower()

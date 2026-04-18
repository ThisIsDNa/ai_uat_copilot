"""
Per–test-case intent for Scenario Builder generation (between TC and steps).

Heuristic structured view of *what this test case is trying to prove*, so titles and
steps can diverge by intent instead of reusing one batch template. Safe to extend with
LLM enrichment later (same dataclass / fields).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from src.scenario_context_expansion import ExpandedGenerationContext


def _norm_ws(s: str) -> str:
    return " ".join(str(s).split()).strip()


_ROLE_WORDS = re.compile(
    r"(?i)\b(provider|patient|member|user|admin|administrator|customer|clinician|tester|staff)\b"
)


@dataclass
class TestCaseIntent:
    entity: str = ""
    action: str = ""
    target_field: str = ""
    title_phrase: str = ""  # right-hand phrase for ``Entity - …`` titles (from AC/title blob)
    target_scope: str = ""  # batch coverage: email, phone, contact_info, confirmation, …
    verification_focus: str = ""  # valid_save, persistence_after_refresh, confirmation_message, …
    condition_type: str = "happy_path"
    input_profile: str = ""
    expected_behavior: str = ""
    validation_focus: str = ""
    persistence_expectation: str = ""
    error_expectation: str = ""
    ui_surface_hint: str = ""
    intent_summary: str = ""
    is_negative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _blob(
    *,
    test_case_title: str,
    criterion_text_only: str,
    linked_acceptance_criteria: list[str] | None,
    expanded: "ExpandedGenerationContext | None",
) -> str:
    parts = [test_case_title, criterion_text_only, *list(linked_acceptance_criteria or [])]
    if expanded is not None and getattr(expanded, "summary_for_prompt", ""):
        parts.append(str(expanded.summary_for_prompt))
    return _norm_ws(" ".join(parts))


def _infer_entity(title: str, crit: str, expanded: "ExpandedGenerationContext | None") -> str:
    t = (title or "").strip()
    if " - " in t:
        left = t.split(" - ", 1)[0].strip()
        if left and len(left) <= 48:
            return left[0].upper() + left[1:] if len(left) > 1 else left.upper()
    parts = re.split(r"\s*-\s*", t, maxsplit=1)
    if len(parts) == 2 and parts[0].strip():
        left = parts[0].strip()
        if len(left) <= 48:
            return left[0].upper() + left[1:] if len(left) > 1 else left.upper()
    if expanded is not None:
        pe = (getattr(expanded, "primary_entity", "") or "").strip()
        if pe:
            return pe[0].upper() + pe[1:].lower() if len(pe) > 1 else pe.upper()
        ents = getattr(expanded, "entities", None) or []
        if ents:
            e0 = str(ents[0]).strip()
            return e0[0].upper() + e0[1:].lower() if len(e0) > 1 else e0.upper()
    m = _ROLE_WORDS.search(crit or "")
    if m:
        w = m.group(1)
        return w[0].upper() + w[1:].lower()
    return "User"


def _target_field_from_scope(scope: str) -> str:
    s = (scope or "").strip().lower()
    if s == "email":
        return "email"
    if s == "phone":
        return "phone"
    if s == "contact_info":
        return "contact info"
    if s == "email_toggle":
        return "email notifications"
    if s == "sms_toggle":
        return "SMS notifications"
    if s in ("notification_preferences", "rule_enforcement"):
        return "notification preferences"
    if s == "generate_action":
        return "primary workflow action"
    if s == "generated_draft":
        return "generated draft"
    if s == "draft_state":
        return "draft state"
    if s == "draft_editability":
        return "draft content"
    if s == "action_persistence":
        return "generated artifact"
    if s == "authorized_generation":
        return "generation permission"
    if s == "auto_send_prevention":
        return "send workflow"
    if s == "action_precondition":
        return "workflow preconditions"
    if s in ("permission_gate", "service_failure"):
        return "generation workflow"
    return ""


def _scenario_has_email_phone(
    low_ac: str,
    expanded: "ExpandedGenerationContext | None",
) -> tuple[bool, bool]:
    """Whether email and/or phone are clearly in play for this scenario."""
    raw = low_ac.lower()
    fields = [str(f).strip().lower() for f in (getattr(expanded, "fields_involved", None) or [])] if expanded else []
    has_email = "email" in raw or any("email" in f for f in fields)
    has_phone = "phone" in raw or any("phone" in f for f in fields)
    if expanded is not None and getattr(expanded, "summary_for_prompt", ""):
        s = str(expanded.summary_for_prompt).lower()
        has_email = has_email or "email" in s
        has_phone = has_phone or "phone" in s
    return has_email, has_phone


def _negative_target_field_from_title(title: str) -> str | None:
    """If the TC title already names a field, keep intent aligned (do not rotate away from it)."""
    t = (title or "").strip().lower()
    if not t:
        return None
    rhs = t.split(" - ", 1)[-1] if " - " in t else t
    has_email = bool(re.search(r"(?i)\bemail\b", rhs))
    has_phone = bool(re.search(r"(?i)\bphone\b", rhs))
    if has_email and not has_phone:
        return "email"
    if has_phone and not has_email:
        return "phone"
    if re.search(r"(?i)\bcontact\b", rhs):
        return "contact info"
    if re.search(r"(?i)\bprofile\b", rhs):
        return "profile"
    return None


def _negative_target_field_override(
    *,
    low_ac: str,
    expanded: "ExpandedGenerationContext | None",
    condition: str,
    negative_field_variant: int,
    picked_from_ac: str,
) -> str | None:
    """
    Rotate negative ``target_field`` labels when multiple fields exist so batches are not email-only.

    Returns None to keep the value from ``_pick_target_field`` (or scope-derived email/phone strings).
    """
    has_email, has_phone = _scenario_has_email_phone(low_ac, expanded)
    v = int(negative_field_variant) % 24

    if condition in ("permission_issue", "dependency_failure"):
        from src.scenario_type_detection import primary_scenario_type

        if expanded is not None and primary_scenario_type(expanded) == "action_event_flow":
            return "generation workflow"
        if has_email and has_phone:
            opts = ("contact info", "email", "phone", "profile save")
            return opts[v % len(opts)]
        if has_phone and not has_email:
            return "phone"
        if has_email and not has_phone:
            return "email"
        if picked_from_ac:
            return None
        return "profile"

    if condition == "rule_blocked":
        from src.scenario_type_detection import primary_scenario_type

        if expanded is not None and primary_scenario_type(expanded) == "action_event_flow":
            return "workflow preconditions"
        return "notification preferences"

    if condition in ("required_missing", "invalid_format", "boundary_value"):
        if has_email and has_phone:
            return "phone" if v % 2 else "email"
        return None

    return None


def _pick_target_field(low: str, expanded: "ExpandedGenerationContext | None") -> str:
    fields = list(getattr(expanded, "fields_involved", None) or []) if expanded else []
    for f in fields:
        fl = f.lower()
        if fl in low or any(tok in low for tok in fl.split()):
            return f
    order = (
        ("email", "email"),
        ("phone", "phone"),
        ("contact", "contact info"),
        ("profile", "profile"),
        ("password", "password or MFA"),
        ("address", "address"),
    )
    for needle, label in order:
        if needle in low:
            return label
    if "field" in low:
        return "required fields"
    return ""


def _detect_condition(
    low: str,
    *,
    is_negative: bool,
    title: str,
    forced_condition: str | None,
) -> str:
    if forced_condition:
        return forced_condition
    tl = (title or "").lower()
    # Title is authoritative when both persist and confirmation appear in linked AC text.
    if not is_negative and tl.strip():
        if re.search(
            r"(?i)\b(block|prevent)\b.*\b(all|both|every)\b.*\b(notification|channel|method|preference)\b|"
            r"\b(all|both)\b.*\b(notification|preference)\b.*\b(disabled|off)\b",
            tl,
        ):
            return "rule_blocked"
        if "persist" in tl or "refresh" in tl or "reload" in tl:
            return "persisted_state_check"
        if "confirmation" in tl or "confirm" in tl or "toast" in tl:
            return "confirmation_check"
    if is_negative or tl.startswith(("reject ", "block ", "prevent ", "validate ")):
        if "missing" in tl or "required" in tl:
            return "required_missing"
        if "invalid" in tl or "format" in tl:
            return "invalid_format"
        if "boundary" in tl:
            return "boundary_value"
        if "permission" in tl:
            return "permission_issue"
        if "dependency" in tl or "error path" in tl:
            return "dependency_failure"
        return "invalid_format"
    if re.search(r"(?i)\bconfirm|\btoast|\bmessage\b.*\b(save|after)\b|\b(save|after)\b.*\bmessage\b", low):
        return "confirmation_check"
    if re.search(r"(?i)\bpersist|\brefresh|\bre-?open|\bre-?query|\bstill\s+appear", low):
        return "persisted_state_check"
    if re.search(r"(?i)\binvalid|\berror\b.*\bfield|\bvalidation\b.*\bfail", low):
        return "invalid_format"
    return "happy_path"


def _intent_phrase_positive(
    condition: str,
    target: str,
    low: str,
    *,
    suppress_typed_contact_labels: bool = False,
    target_scope: str = "",
) -> str:
    t = (target or "").strip().lower()
    sc = (target_scope or "").strip().lower()
    if condition == "rule_blocked":
        return "Block All Notifications Disabled"
    if sc == "generate_action" or (
        sc == "" and re.search(r"(?i)\bgenerate\s+(reply|notes|summary|draft)\b", low)
    ):
        if re.search(r"(?i)\bnotes\b", low):
            return "Generate Notes Draft"
        if "reply" in low:
            return "Generate Reply Draft"
        return "Generate Draft"
    if sc == "generated_draft" or (sc == "" and "draft appears" in low):
        return "Generated Draft Appears In Panel"
    if sc == "draft_state":
        return "Reply Draft Remains Draft State"
    if sc == "draft_editability":
        return "Draft Editable Before Send"
    if sc == "action_persistence":
        return "Reply Draft Persists After Refresh"
    if sc == "authorized_generation":
        return "Authorized Role Generation Success"
    if sc == "auto_send_prevention":
        return "Draft Not Auto-Sent"
    notifish = bool(re.search(r"(?i)\bnotification|preference|channel|toggle|sms|email\s+notification", low))
    if suppress_typed_contact_labels and condition == "confirmation_check":
        return "Save Preferences Confirmation" if notifish else "Save Confirmation Message"
    if suppress_typed_contact_labels and condition == "persisted_state_check":
        return "Preferences Persist After Reload" if notifish else "Persist Updated Values"
    if condition == "confirmation_check":
        if "phone" in low and "email" not in low:
            return "Phone Save Confirmation"
        if "email" in low and "phone" not in low:
            return "Email Save Confirmation"
        return "Save Confirmation Message"
    if condition == "persisted_state_check":
        if "email" in low and "phone" not in low:
            return "Email Persist After Refresh"
        if "phone" in low and "email" not in low:
            return "Phone Persist After Refresh"
        if "email" in low and "phone" in low:
            return "Contact Info Persist After Refresh"
        return "Persist Updated Values"
    if condition == "invalid_format" and not (target or "").strip():
        return "Invalid Input Handling"
    if "enroll" in low or "registration" in low:
        return "Submit Enrollment"
    if suppress_typed_contact_labels and condition == "happy_path" and notifish:
        return "Save Valid Notification Preferences"
    if "email" in low and "phone" in low and condition == "happy_path":
        return "Update Contact Info - Valid Save"
    if t == "email" or (t == "" and "email" in low and "phone" not in low):
        return "Update Email - Valid Save"
    if t == "phone" or (t == "" and "phone" in low and "email" not in low):
        return "Update Phone - Valid Save"
    if "profile" in low or "contact" in low:
        return "Save Contact Changes - Valid Save"
    if "sign" in low or "log" in low or "auth" in low:
        return "Sign In Success"
    if "report" in low or "export" in low:
        return "Run Report Export"
    return "Complete Primary Flow"


def _primary_action_label_for_phrases(expanded: "ExpandedGenerationContext | None") -> str:
    if expanded is None:
        return ""
    pal = (getattr(expanded, "primary_action_label", "") or "").strip()
    if pal:
        return pal
    from src.scenario_domain_labels import extract_primary_action_label

    blob = _norm_ws(
        " ".join(
            [
                str(getattr(expanded, "summary_for_prompt", "") or ""),
            ]
        )
    )
    return extract_primary_action_label(blob) or ""


def _intent_phrase_negative(
    condition: str,
    target: str,
    entity: str,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    tf = (target or "field").strip() or "field"
    tf_l = tf.lower()
    tf_title = tf[0].upper() + tf[1:] if tf else "Field"
    pal = _primary_action_label_for_phrases(expanded)
    if condition == "required_missing":
        if tf_l in ("required fields", "field"):
            return "Missing Required Fields"
        if tf_l.startswith("required "):
            return f"Missing {tf_title}"
        return f"Missing Required {tf_title}"
    if condition == "invalid_format":
        return f"Invalid {tf_title} Format"
    if condition == "boundary_value":
        return f"{tf_title} Boundary Value"
    if condition == "permission_issue":
        if "notification" in tf_l or "preference" in tf_l:
            return "Permission Block On Preferences Update"
        if "contact" in tf_l:
            return "Permission Block On Contact Update"
        if "profile" in tf_l:
            return "Permission Block On Profile Save"
        if "generation" in tf_l or "workflow" in tf_l or "draft" in tf_l:
            if pal:
                return f"Unauthorized User - {pal} Blocked"
            return "Unauthorized User - Primary Generation Action Blocked"
        return f"Permission Block On {tf_title}"
    if condition == "dependency_failure":
        if "notification" in tf_l or "preference" in tf_l:
            return "Dependency Failure On Preferences Save"
        if "contact" in tf_l:
            return "Dependency Failure On Contact Update"
        if "profile" in tf_l:
            return "Dependency Failure On Profile Save"
        if "generation" in tf_l or "workflow" in tf_l:
            return "AI Service Failure - No Draft Inserted"
        return f"Dependency Failure On {tf_title}"
    if condition == "rule_blocked":
        if "notification" in tf_l or "preference" in tf_l:
            return "Disable All Notification Methods - Blocked"
        if "precondition" in tf_l or "workflow" in tf_l or "generation" in tf_l:
            if pal:
                return f"{pal} Blocked By Preconditions"
            return "Primary Action Blocked By Preconditions"
        return "Primary Action Blocked By Preconditions"
    return f"Invalid {tf_title} Format"


def infer_test_case_intent(
    *,
    test_case_title: str = "",
    linked_acceptance_criteria: list[str] | None = None,
    criterion_text_only: str = "",
    expanded: "ExpandedGenerationContext | None" = None,
    is_negative: bool = False,
    forced_condition: str | None = None,
    coverage_slot: Mapping[str, Any] | None = None,
    negative_field_variant: int = 0,
) -> TestCaseIntent:
    """
    Derive structured intent for one test case from title, AC text, expansion, and polarity.

    ``criterion_text_only`` is used when proposing titles from AC rows before a TC title exists.

    ``coverage_slot`` — optional batch plan dict with ``target_scope``, ``verification_focus``,
    ``intent_hint``, optional ``forced_condition`` (positive titles / steps only).

    ``negative_field_variant`` — rotates inferred ``target_field`` for negative cases when
    multiple fields (e.g. email + phone) are present; use AC index or TC slot for stability.
    """
    from src.scenario_type_gating import (
        action_event_flow_strict_gating,
        coerce_negative_condition_under_gating,
        explicit_text_input_validation_context,
        sanitize_positive_coverage_slot,
        state_toggle_strict_gating,
    )

    crit = (criterion_text_only or "").strip()
    title = (test_case_title or "").strip()
    slot = dict(coverage_slot) if isinstance(coverage_slot, Mapping) else {}
    if not slot and not is_negative and title:
        from src.scenario_positive_coverage_plan import coverage_slot_from_test_case_title

        inferred = coverage_slot_from_test_case_title(title)
        if inferred:
            slot = dict(inferred)
    if slot and expanded is not None:
        crit_gate = _norm_ws(" ".join([crit, title, *list(linked_acceptance_criteria or [])]))
        slot = sanitize_positive_coverage_slot(slot, expanded, crit_gate)
    scope_from_plan = str(slot.get("target_scope") or "").strip().lower()
    vf_from_plan = str(slot.get("verification_focus") or "").strip().lower()
    hint_from_plan = str(slot.get("intent_hint") or "").strip()
    blob = _blob(
        test_case_title=title,
        criterion_text_only=crit,
        linked_acceptance_criteria=linked_acceptance_criteria,
        expanded=expanded,
    )
    low = blob.lower()
    # Condition / positive-phrase cues must not read generic expansion boilerplate
    # (e.g. ``invalid data`` in risk templates) as if it were the AC under test.
    blob_ac = _norm_ws(" ".join([title, crit, *list(linked_acceptance_criteria or [])]))
    low_ac = blob_ac.lower()

    typed_workflow_suppressed = bool(
        expanded is not None
        and (
            state_toggle_strict_gating(expanded, criterion_text=blob_ac)
            or action_event_flow_strict_gating(expanded, criterion_text=blob_ac)
        )
        and not explicit_text_input_validation_context(blob_ac)
    )

    entity = _infer_entity(title, crit, expanded)
    target_field = _pick_target_field(low, expanded)
    fc_merge = forced_condition
    if not is_negative and slot.get("forced_condition"):
        fc_merge = str(slot["forced_condition"]).strip() or fc_merge
    condition = _detect_condition(low_ac, is_negative=is_negative, title=title, forced_condition=fc_merge)
    if is_negative:
        condition = coerce_negative_condition_under_gating(
            condition,
            expanded=expanded,
            criterion_text=crit,
            title=title,
            negative_field_variant=negative_field_variant,
        )
        explicit_tf = _negative_target_field_from_title(title)
        if explicit_tf:
            target_field = explicit_tf
        else:
            ov = _negative_target_field_override(
                low_ac=low_ac,
                expanded=expanded,
                condition=condition,
                negative_field_variant=negative_field_variant,
                picked_from_ac=bool(target_field),
            )
            if ov:
                target_field = ov
    if not is_negative and scope_from_plan:
        tf_scope = _target_field_from_scope(scope_from_plan)
        if tf_scope:
            target_field = tf_scope

    ui = ""
    if expanded is not None:
        ui = (getattr(expanded, "ui_surface_hint", "") or "").strip()

    # input_profile / expectations by condition
    input_profile = ""
    expected_behavior = ""
    validation_focus = ""
    persistence_expectation = ""
    error_expectation = ""
    action = ""
    title_phrase = ""

    pt_primary = ""
    if expanded is not None:
        from src.scenario_type_detection import primary_scenario_type

        pt_primary = primary_scenario_type(expanded)

    if is_negative:
        if condition == "required_missing":
            input_profile = f"required {target_field or 'field'} left blank or cleared".strip()
            expected_behavior = "save blocked or not committed"
            validation_focus = "required-field or inline missing message"
            persistence_expectation = "prior valid data remains; record not updated with blanks"
            error_expectation = f"missing {target_field or 'required'} error"
            action = "block save with missing data"
        elif condition == "invalid_format":
            input_profile = f"malformed {target_field or 'input'} with otherwise valid data".strip()
            expected_behavior = "validation failure; happy path not completed"
            validation_focus = f"inline {target_field or 'field'} format error"
            persistence_expectation = "invalid value must not persist"
            error_expectation = f"inline {target_field or 'format'} error"
            action = "reject invalid format"
        elif condition == "boundary_value":
            accept_edge = bool(
                re.search(
                    r"(?i)\baccepts?\b.*\b(edge|boundary|limit)|\bvalid\s+edge\b|\bwithin\s+(acceptable|allowed)\s+limits\b|\bminimum\b.*\baccepted\b|\bmaximum\b.*\baccepted\b",
                    low_ac,
                )
            )
            if accept_edge:
                input_profile = "boundary value that remains valid per documented rules"
                expected_behavior = "save succeeds and UI reflects the accepted edge value"
                validation_focus = "no false invalid error; field shows the committed edge value"
                persistence_expectation = "accepted edge value persists after save and refresh where applicable"
                error_expectation = "no erroneous validation blocking a valid edge case"
                action = "commit valid boundary value"
            else:
                input_profile = "boundary or edge-case value for the field under test"
                expected_behavior = "controlled rejection or clamping per product rules"
                validation_focus = "boundary validation messaging"
                persistence_expectation = "no silent acceptance of out-of-range values"
                error_expectation = "boundary violation feedback"
                action = "reject boundary value"
        elif condition == "permission_issue":
            if pt_primary == "action_event_flow":
                input_profile = "actor without required role attempts the primary generation or trigger action"
                expected_behavior = "action is blocked or disabled with clear permission messaging"
                validation_focus = "disabled control, tooltip, or permission denial banner"
                persistence_expectation = "no draft or artifact is created for the unauthorized attempt"
                error_expectation = "permission denied or not allowed messaging"
                action = "block unauthorized generation"
            else:
                input_profile = "actor lacks permission for the attempted change"
                expected_behavior = "action blocked with permission messaging"
                validation_focus = "authorization or permission denial UI"
                persistence_expectation = "no unauthorized persistence"
                error_expectation = "permission denied message"
                action = "block unauthorized update"
        elif condition == "rule_blocked":
            if pt_primary == "action_event_flow":
                input_profile = (
                    "record or conversation is in a blocked precondition (e.g. closed) so the action must not run"
                )
                expected_behavior = "UI blocks or rejects the action with a clear precondition message; no new draft"
                validation_focus = "disabled action, inline banner, or tooltip referencing the invalid state"
                persistence_expectation = "no artifact inserted when the precondition blocks the action"
                error_expectation = "blocking message references state/precondition (not a silent no-op)"
                action = "block generation when preconditions fail"
            else:
                input_profile = "all notification channels turned OFF so no delivery method remains enabled"
                expected_behavior = "save is blocked with a clear rule message; prior valid preference state unchanged"
                validation_focus = "blocking message explains at least one channel must remain enabled"
                persistence_expectation = "invalid all-off preference state does not persist when save is rejected"
                error_expectation = "rule violation or validation banner (not a silent no-op)"
                action = "block forbidden notification combination"
        elif condition == "dependency_failure":
            if pt_primary == "action_event_flow":
                input_profile = "AI or downstream service is unavailable or returns an error during generation"
                expected_behavior = "user-visible error and **no** draft or partial generated artifact is persisted"
                validation_focus = "error message, banner, or toast; empty draft panel where applicable"
                persistence_expectation = "no phantom or stale generated rows after failure"
                error_expectation = "controlled failure state with actionable messaging"
                action = "surface generation failure without artifact"
            else:
                input_profile = "data that triggers downstream or integration failure"
                expected_behavior = "graceful error without corrupting stored state"
                validation_focus = "service failure or dependency banner"
                persistence_expectation = "no partial corrupt commit"
                error_expectation = "dependency or system failure state"
                action = "surface dependency failure"

        phrase = _intent_phrase_negative(condition, target_field, entity, expanded)
        title_phrase = phrase
        intent_summary = (
            f"{entity} negative path: {phrase}. {validation_focus}. {persistence_expectation}."
        )
    else:
        if condition == "confirmation_check":
            action = "save and observe confirmation"
            input_profile = "valid data per scenario context for all required fields"
            expected_behavior = "explicit confirmation message or toast after successful save"
            validation_focus = "confirmation toast or banner text; no contradictory hard error"
            persistence_expectation = "save completes; optional follow-up read shows same values"
        elif condition == "rule_blocked":
            if pt_primary == "action_event_flow":
                action = "attempt primary workflow action while preconditions block execution"
                input_profile = "blocked object state (e.g. closed conversation) per linked acceptance criteria"
                expected_behavior = "action cannot complete; UI shows blocking state without creating a draft"
                validation_focus = "disabled control, banner, or inline message referencing the invalid precondition"
                persistence_expectation = "no new artifact is stored when the action is blocked"
            else:
                action = "attempt disallowed notification or preference combination"
                input_profile = "set toggles so every notification channel is OFF while rules require at least one ON"
                expected_behavior = "save is rejected with a clear rule message; prior valid preference state remains"
                validation_focus = "blocking message references the cross-field rule (e.g. at least one method enabled)"
                persistence_expectation = "forbidden all-off state does not persist when save fails"
        elif condition == "persisted_state_check":
            action = "save then verify durable state"
            input_profile = "valid new values for fields under test"
            expected_behavior = "updated values visible after refresh or reopen"
            validation_focus = "refreshed UI matches saved server state"
            persistence_expectation = "updated values persist across refresh/session"
        else:
            action = "save valid profile or contact updates"
            input_profile = "valid realistic values for fields under test (see scenario context)"
            expected_behavior = "success path completes with expected UI feedback"
            validation_focus = "field-level validation passes; success indicators visible"
            persistence_expectation = "valid changes persist when save succeeds"

        phrase = _intent_phrase_positive(
            condition,
            target_field,
            low_ac,
            suppress_typed_contact_labels=typed_workflow_suppressed,
            target_scope=scope_from_plan,
        )
        title_phrase = phrase
        if hint_from_plan:
            title_phrase = hint_from_plan
        intent_summary = f"{entity} proves: {title_phrase}. {expected_behavior}."

    if not ui and expanded is not None:
        ui = (getattr(expanded, "ui_surface_hint", "") or "").strip()

    if not is_negative and scope_from_plan and vf_from_plan:
        if condition == "confirmation_check":
            action = "save and observe confirmation"
            if scope_from_plan not in (
                "notification_preferences",
                "email_toggle",
                "sms_toggle",
                "rule_enforcement",
            ):
                if typed_workflow_suppressed and scope_from_plan in ("contact_info", "confirmation", "email", "phone"):
                    input_profile = (
                        "valid ON/OFF channel states per AC; confirm toggle labels match intent before save"
                    )
                else:
                    input_profile = (
                        "valid email and phone per scenario rules (e.g. qa.profile@example.com, 6505551234) "
                        if scope_from_plan in ("contact_info", "confirmation", "email", "phone")
                        else input_profile
                    )
        elif condition == "persisted_state_check":
            action = "save then verify durable state"
            if scope_from_plan == "notification_preferences":
                input_profile = (
                    "valid ON/OFF combination for notification channels; note each toggle state before save for reload comparison"
                )
            elif typed_workflow_suppressed and scope_from_plan in ("contact_info", "email", "phone"):
                input_profile = (
                    "valid ON/OFF combination for notification channels; note each toggle state before save for reload comparison"
                )
            else:
                input_profile = (
                    "updated email and phone with valid formats (e.g. qa.updated@example.com, 6505550199) "
                    if scope_from_plan == "contact_info"
                    else (
                        "valid new email (e.g. qa.updated@example.com); keep phone at a valid baseline"
                        if scope_from_plan == "email"
                        else (
                            "valid new phone (e.g. 6505550199); keep email at a valid baseline"
                            if scope_from_plan == "phone"
                            else input_profile
                        )
                    )
                )
        elif vf_from_plan == "validation_pass":
            if typed_workflow_suppressed:
                input_profile = (
                    "channel toggles in a valid ON/OFF pattern per AC; other controls at a valid baseline"
                )
            else:
                input_profile = (
                    f"valid {target_field or scope_from_plan} values that pass field rules; other fields valid baseline"
                )
        elif vf_from_plan in ("enable_transition", "disable_transition"):
            input_profile = (
                "set toggles per AC: turn channels ON or OFF while keeping a valid overall combination before save"
            )
        elif vf_from_plan == "blocked_combination":
            input_profile = "configure the forbidden ON/OFF combination described in the linked acceptance criteria"
        elif vf_from_plan in ("ui_consistency", "business_outcome"):
            input_profile = (
                "valid multi-field data consistent with scenario context; save then compare visible state"
            )
        elif vf_from_plan == "action_trigger_success" or scope_from_plan == "generate_action":
            pal0 = (getattr(expanded, "primary_action_label", "") or "").strip() if expanded is not None else ""
            rec0 = (getattr(expanded, "domain_record_label", "") or "").strip() if expanded is not None else ""
            rec_txt = f"an eligible {rec0}" if rec0 else "an eligible record or conversation"
            if pal0:
                input_profile = f"open {rec_txt}, click **{pal0}**, and wait for processing to finish"
            else:
                input_profile = (
                    "open an eligible record or conversation, then click the primary action control named in scenario context"
                )
        elif vf_from_plan == "artifact_created" or scope_from_plan == "generated_draft":
            art0 = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded is not None else ""
            if art0:
                input_profile = f"after the action completes, confirm the **{art0}** appears in the expected UI area"
            else:
                input_profile = (
                    "after the action completes, confirm the draft or generated content appears in the expected panel"
                )
        elif vf_from_plan == "remains_draft" or scope_from_plan == "draft_state":
            art0 = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded is not None else ""
            if art0:
                input_profile = (
                    f"with a {art0} visible per AC, confirm status remains Draft and no forbidden auto-transition occurs"
                )
            else:
                input_profile = (
                    "generate or open a draft per AC; confirm status remains Draft and no forbidden auto-transition occurs"
                )
        elif vf_from_plan == "editable_before_send" or scope_from_plan == "draft_editability":
            art0 = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded is not None else ""
            if art0:
                input_profile = (
                    f"with a {art0} present, edit generated text in the draft area; confirm edits persist before any send step"
                )
            else:
                input_profile = (
                    "with a draft present, edit generated text in the draft area; confirm edits persist before any send step"
                )
        elif vf_from_plan == "persists_after_refresh" or scope_from_plan == "action_persistence":
            art0 = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded is not None else ""
            if art0:
                input_profile = (
                    f"after a successful generation, refresh or re-open the workspace and compare visible {art0} to AC"
                )
            else:
                input_profile = (
                    "after a successful generation, refresh or re-open the workspace and compare visible draft to AC"
                )
        elif vf_from_plan == "workflow_outcome" or scope_from_plan == "authorized_generation":
            pal0 = (getattr(expanded, "primary_action_label", "") or "").strip() if expanded is not None else ""
            if pal0:
                input_profile = (
                    f"as an authorized role from scenario context, run **{pal0}** end-to-end and verify success signals"
                )
            else:
                input_profile = (
                    "as an authorized role from scenario context, run the action end-to-end and verify success signals"
                )
        elif vf_from_plan == "no_auto_send" or scope_from_plan == "auto_send_prevention":
            art0 = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded is not None else ""
            tail = art0 or "draft"
            input_profile = (
                f"after generation, confirm no automatic send, submit, or lifecycle transition beyond Draft without user action for the {tail}"
            )
        elif vf_from_plan == "confirmation_or_visible_result":
            art0 = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded is not None else ""
            if art0:
                input_profile = (
                    f"complete the action and verify visible confirmation, inserted **{art0}**, or result messaging per AC"
                )
            else:
                input_profile = (
                    "complete the action and verify visible confirmation, inserted draft, or result messaging per AC"
                )

    return TestCaseIntent(
        entity=entity,
        action=action,
        target_field=target_field,
        title_phrase=title_phrase,
        target_scope=scope_from_plan if not is_negative else "",
        verification_focus=vf_from_plan if not is_negative else "",
        condition_type=condition,
        input_profile=input_profile,
        expected_behavior=expected_behavior,
        validation_focus=validation_focus,
        persistence_expectation=persistence_expectation,
        error_expectation=error_expectation,
        ui_surface_hint=ui,
        intent_summary=_norm_ws(intent_summary)[:420],
        is_negative=is_negative,
    )


def format_positive_title_from_intent(
    intent: TestCaseIntent,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    """``Entity - Intent`` title (3–6 words on the right of the dash when possible)."""
    from src.scenario_domain_labels import polish_positive_title_rhs
    from src.scenario_type_gating import (
        action_event_flow_strict_gating,
        explicit_text_input_validation_context,
        state_toggle_strict_gating,
    )

    ent = (intent.entity or "User").strip()
    if ent:
        ent = ent[0].upper() + ent[1:] if len(ent) > 1 else ent.upper()
    blob_gate = _norm_ws(
        f"{intent.title_phrase} {intent.target_scope} {intent.intent_summary} {(getattr(expanded, 'summary_for_prompt', '') or '')}"
        if expanded
        else f"{intent.title_phrase} {intent.target_scope} {intent.intent_summary}"
    )
    blob_ft = _norm_ws(
        f"{intent.intent_summary} {(getattr(expanded, 'summary_for_prompt', '') or '')}" if expanded else intent.intent_summary
    )
    suppress = bool(
        expanded is not None
        and (
            state_toggle_strict_gating(expanded, criterion_text=blob_gate)
            or action_event_flow_strict_gating(expanded, criterion_text=blob_gate)
        )
        and not explicit_text_input_validation_context(blob_gate)
    )
    phrase = (intent.title_phrase or "").strip() or _intent_phrase_positive(
        intent.condition_type,
        intent.target_field,
        intent.intent_summary.lower(),
        suppress_typed_contact_labels=suppress,
        target_scope=getattr(intent, "target_scope", "") or "",
    )
    phrase = phrase.strip(" -–—")
    if phrase == "Complete Primary Flow" and expanded is not None:
        flds = list(getattr(expanded, "fields_involved", None) or [])
        if suppress and flds:
            phrase = "Save Valid Notification Preferences"
        elif len(flds) >= 2:
            a, b = flds[0], flds[1]
            phrase = f"Update {a.title()} And {b.title()}"
        elif len(flds) == 1:
            phrase = f"Update {flds[0].title()}"
    if phrase == "Complete Primary Flow" and intent.target_field:
        tf = intent.target_field[0].upper() + intent.target_field[1:] if intent.target_field else ""
        phrase = f"Update {tf}" if tf else phrase
    words = phrase.split()
    if len(words) > 6:
        phrase = " ".join(words[:6]).rstrip(",;:")
    right = " ".join(w.title() if w.islower() else w for w in phrase.split())
    right = right.replace(" Or ", " or ").replace(" Mfa", " MFA")
    right = right.strip(" -–—")
    while "  " in right:
        right = right.replace("  ", " ")
    right = polish_positive_title_rhs(right, expanded)
    out = _norm_ws(f"{ent} - {right}")
    while out.endswith("-") or out.endswith("–") or out.endswith("—"):
        out = _norm_ws(out[:-1].rstrip(" -–—"))
    return out


def format_negative_title_from_intent(
    intent: TestCaseIntent,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    ent = (intent.entity or "User").strip()
    if ent:
        ent = ent[0].upper() + ent[1:] if len(ent) > 1 else ent.upper()
    phrase = (intent.title_phrase or "").strip() or _intent_phrase_negative(
        intent.condition_type, intent.target_field, ent, expanded
    )
    words = phrase.split()
    if len(words) > 6:
        phrase = " ".join(words[:6])
    right = " ".join(w.title() if w.islower() else w for w in phrase.split())
    return _norm_ws(f"{ent} - {right}")


def infer_intent_from_builder_session(
    sess: Mapping[str, Any],
    tc_slot: int,
    *,
    linked_ac_texts: list[str] | None,
) -> TestCaseIntent:
    """Build intent for an existing TC row (used by step generation)."""
    from src.scenario_context_expansion import expanded_context_from_builder_session
    from src.scenario_positive_coverage_plan import positive_coverage_slot_for_tc_session

    exp = expanded_context_from_builder_session(sess)
    title = str(sess.get(f"sb_tc_{tc_slot}_text") or "").strip()
    neg = is_negative_test_case_title(title)
    slot = None if neg else positive_coverage_slot_for_tc_session(sess, tc_slot, exp)
    return infer_test_case_intent(
        test_case_title=title,
        linked_acceptance_criteria=linked_ac_texts,
        criterion_text_only="",
        expanded=exp,
        is_negative=neg,
        coverage_slot=slot,
        negative_field_variant=int(tc_slot),
    )


def is_negative_test_case_title(title: str) -> bool:
    """Delegates to ``scenario_builder_steps_gen._is_negative_style_title`` (single source of truth)."""
    from src.scenario_builder_steps_gen import _is_negative_style_title

    return _is_negative_style_title(title)

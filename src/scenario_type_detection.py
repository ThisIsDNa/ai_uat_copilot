"""
Heuristic scenario-type classification for routing generation (form vs toggle vs rules, etc.).

Thin layer — informs expansion, coverage planning, intent, titles, and steps without
replacing the existing pipeline.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def _norm_blob(*parts: str | None) -> str:
    return " ".join(" ".join((p or "").split()) for p in parts if p).strip()


_TOGGLE_PAT = re.compile(
    r"(?i)\b(toggle|toggles|switch|switches|checkbox|checkboxes|enable|enables|enabled|"
    r"disable|disables|disabled|turn on|turn off|on/off|on or off|selected|unselected|"
    r"preference|preferences|opt in|opt out|subscribe|unsubscribe)\b"
)
_NOTIFICATION_PAT = re.compile(r"(?i)\b(notification|notifications|notify|sms|text message)\b")
_BUSINESS_RULE_PAT = re.compile(
    r"(?i)\b(at least one|only when|cannot if|must remain|must stay|no more than|"
    r"all .{0,40}?disabled|cannot save|must be enabled|required to remain|"
    r"forbidden|invalid combination|not allowed together|business rule)\b"
)
_FORM_STRONG_PAT = re.compile(
    r"(?i)\b(email format|invalid email|phone format|10[- ]?digit|10\s+alphanumeric|"
    r"alphanumeric\s+characters?|required field|"
    r"zip code|postal code|street address|date of birth|password policy)\b"
)
# Typed field rules beyond email/phone (e.g. ticket ID length) — used for hybrid action_event + format cues.
_TYPED_FIELD_FORMAT_PAT = re.compile(
    r"(?i)(\b(invalid|bad)\s+format\b.{0,120}?\b(reject|rejected|before\s+save|on\s+save)\b"
    r"|\b(reject|rejected)\b.{0,120}?\b(invalid|bad)\s+format\b"
    r"|\b(must\s+enter|required\s+to\s+enter)\b.{0,160}?\b(exactly\s+\d{1,4}\s+alphanumeric|alphanumeric\s+characters?)\b"
    r"|\bexactly\s+\d{1,4}\s+alphanumeric\s+characters?\b)"
)
_APPROVAL_PAT = re.compile(
    r"(?i)\b(approve|approval|approve\s+or\s+reject|reject\s+or\s+approve|"
    r"reject\s+(the\s+)?(submission|request|application|expense|claim)|"
    r"rejected\s+(by\s+)?(manager|approver|workflow)|submit\s+for\s+review|submits?\s+for\s+approval|"
    r"workflow state|status changes|lifecycle|pending review)\b"
)
_TABLE_PAT = re.compile(
    r"(?i)\b(data table|grid|rows?|columns?|filter|sorting|bulk action|add row|remove row|pagination)\b"
)
_FILE_PAT = re.compile(
    r"(?i)\b(upload|download|attach|attachment|file type|file size|preview|evidence)\b"
)
_PERMISSION_PAT = re.compile(r"(?i)\b(permission|role|unauthori[sz]ed|cannot update|access denied)\b")
_SAVE_PERSIST_PAT = re.compile(r"(?i)\b(save|persist|reload|refresh|re-?login|session)\b")
# Action/event workflows: user triggers an action; system creates or transitions an artifact.
_ACTION_VERB_PAT = re.compile(
    r"(?i)\b(generate|regenerat(e|ing)|create|creates|run|runs|trigger|triggers|submit|submits|"
    r"start|starts|launch|launches|retry|retries|invoke|invokes|produce|produces|insert|inserts)\b"
)
_ACTION_UI_PAT = re.compile(
    r"(?i)\b(button|click|clicked|cta|action\s*bar|drawer|modal|panel|toolbar|menu\s*action)\b"
)
_ACTION_ARTIFACT_PAT = re.compile(
    r"(?i)\b(draft|drafts|generated\s+content|ai[-\s]?generated|reply\s+draft|draft\s+reply|"
    r"artifact|inserted\s+record|created\s+object|new\s+record|output\s+panel|response\s+panel)\b"
)
_ACTION_LIFECYCLE_PAT = re.compile(
    r"(?i)\b(draft\s+state|remains?\s+draft|not\s+sent|no\s+auto[-\s]?send|review\s+before\s+send|"
    r"pending\s+review|final\s+state|already\s+sent|conversation\s+closed|closed\s+conversation|"
    r"archived\s+record)\b"
)
_ACTION_BLOCKED_PAT = re.compile(
    r"(?i)\b(blocked|disabled|cannot\s+generate|may\s+not\s+generate|not\s+available|"
    r"forbidden|precondition)\b.*\b(closed|archived|sent|final)\b|\b(closed|archived)\b.*\b(generate|draft)\b"
)
_ACTION_FAILURE_PAT = re.compile(
    r"(?i)\b(service\s+fail|fails?|unavailable|timeout|generation\s+error|no\s+draft|"
    r"inserts?\s+no|does\s+not\s+insert|without\s+inserting|error\s+(message|state))\b"
)


def detect_scenario_type(
    *,
    scenario_context: str | None = None,
    business_goal: str | None = None,
    workflow_name: str | None = None,
    changed_areas_bulk: str | None = None,
    known_dependencies_bulk: str | None = None,
) -> dict[str, Any]:
    """
    Classify scenario shape for generation routing.

    Returns a dict with ``primary_type``, ``secondary_types``, ``signals``, ``routing_hints``, ``summary``.
    """
    blob = _norm_blob(
        scenario_context,
        business_goal,
        workflow_name,
        changed_areas_bulk,
        known_dependencies_bulk,
    )
    low = blob.lower()

    toggle_terms = bool(_TOGGLE_PAT.search(blob))
    notification_context = bool(_NOTIFICATION_PAT.search(blob))
    cross_field_constraint = bool(_BUSINESS_RULE_PAT.search(blob))
    text_input_validation = (
        bool(_FORM_STRONG_PAT.search(blob))
        or bool(_TYPED_FIELD_FORMAT_PAT.search(blob))
        or bool(
            re.search(r"(?i)\b(invalid|format|validate)\b.*\b(email|phone|address)\b", low)
            or re.search(r"(?i)\b(email|phone|address)\b.*\b(invalid|format|validate)\b", low)
        )
    )
    save_persistence = bool(_SAVE_PERSIST_PAT.search(blob))
    permission_control = bool(_PERMISSION_PAT.search(blob))
    approval_flow = bool(_APPROVAL_PAT.search(blob))
    table_management = bool(_TABLE_PAT.search(blob))
    file_flow = bool(_FILE_PAT.search(blob))

    action_verbs = bool(_ACTION_VERB_PAT.search(blob))
    action_ui = bool(_ACTION_UI_PAT.search(blob))
    action_artifact = bool(_ACTION_ARTIFACT_PAT.search(blob))
    action_lifecycle = bool(_ACTION_LIFECYCLE_PAT.search(blob))
    action_blocked = bool(_ACTION_BLOCKED_PAT.search(blob))
    action_failure = bool(_ACTION_FAILURE_PAT.search(blob))
    action_named_flow = bool(
        re.search(r"(?i)\bgenerate\s+reply\b|\bregenerate\s+(recommendation|reply|summary)\b|\brun\s+ai\b", blob)
    )
    action_event_core = bool(
        action_verbs
        and (
            action_artifact
            or action_lifecycle
            or action_ui
            or action_blocked
            or action_failure
            or action_named_flow
        )
    )

    # Scoring for primary type
    scores: dict[str, int] = {
        "form_input": 0,
        "state_toggle": 0,
        "business_rule": 0,
        "approval_or_status_flow": 0,
        "data_table_or_list_management": 0,
        "file_or_attachment_flow": 0,
        "action_event_flow": 0,
    }
    if toggle_terms or notification_context:
        scores["state_toggle"] += 3
    if notification_context and toggle_terms:
        scores["state_toggle"] += 4
    if cross_field_constraint:
        scores["business_rule"] += 4
    if re.search(r"(?i)\b(at least one|must remain|must stay)\b", low) and toggle_terms:
        scores["business_rule"] += 3
    if text_input_validation:
        scores["form_input"] += 3
    if re.search(r"(?i)\b(email|phone|address|name)\b", low) and not (toggle_terms and notification_context):
        scores["form_input"] += 1
    if approval_flow:
        scores["approval_or_status_flow"] += 4
    if table_management:
        scores["data_table_or_list_management"] += 4
    if file_flow:
        scores["file_or_attachment_flow"] += 4

    # Action / event workflows (AI draft, run job, trigger export, etc.) — requires core signals, not a lone verb.
    if action_event_core:
        if action_verbs:
            scores["action_event_flow"] += 5
        if action_artifact:
            scores["action_event_flow"] += 4
        if action_lifecycle:
            scores["action_event_flow"] += 3
        if action_ui and action_verbs:
            scores["action_event_flow"] += 2
        if permission_control and action_verbs:
            scores["action_event_flow"] += 2
        if action_blocked:
            scores["action_event_flow"] += 3
        if action_failure:
            scores["action_event_flow"] += 4
        if cross_field_constraint:
            scores["action_event_flow"] += 2
    # Pure notification preference toggles without trigger/artifact language stay state_toggle.
    if notification_context and toggle_terms and not action_event_core:
        scores["action_event_flow"] = 0
    elif notification_context and toggle_terms and scores["action_event_flow"] > 0:
        if scores["state_toggle"] >= scores["action_event_flow"]:
            scores["action_event_flow"] = max(0, scores["action_event_flow"] - 4)

    # Prefer state_toggle when notifications + toggles dominate over raw format validation
    if notification_context and toggle_terms and scores["state_toggle"] >= scores["form_input"]:
        scores["state_toggle"] += 2

    _primary_priority = {
        "action_event_flow": 85,
        "state_toggle": 78,
        "approval_or_status_flow": 72,
        "file_or_attachment_flow": 68,
        "data_table_or_list_management": 64,
        "business_rule": 45,
        "form_input": 12,
    }
    primary = max(scores, key=lambda k: (scores[k], _primary_priority.get(k, 0)))
    if scores[primary] == 0:
        primary = "form_input"

    secondaries: list[str] = []
    for k, v in scores.items():
        if k != primary and v >= 2:
            secondaries.append(k)
    if primary == "state_toggle" and scores["business_rule"] >= 2 and "business_rule" not in secondaries:
        secondaries.insert(0, "business_rule")
    if primary == "form_input" and scores["business_rule"] >= 3:
        secondaries.append("business_rule")
    if primary == "action_event_flow" and scores["business_rule"] >= 2 and "business_rule" not in secondaries:
        secondaries.insert(0, "business_rule")

    prefer_state = primary == "state_toggle" or (
        "state_toggle" in secondaries and scores["state_toggle"] >= scores["form_input"]
    )
    prefer_rules = primary == "business_rule" or "business_rule" in secondaries or cross_field_constraint
    prefer_input_format = primary == "form_input" and not (
        prefer_state and scores["state_toggle"] >= scores["form_input"] + 1
    )
    if toggle_terms and notification_context and not text_input_validation:
        prefer_input_format = False
    if primary == "action_event_flow":
        prefer_input_format = bool(text_input_validation)

    prefer_action_event = primary == "action_event_flow" or (
        "action_event_flow" in secondaries and scores["action_event_flow"] >= 3
    )
    routing_hints = {
        "prefer_state_transitions": bool(prefer_state),
        "prefer_cross_field_rules": bool(prefer_rules),
        "prefer_input_format_validation": bool(prefer_input_format),
        "prefer_action_trigger_steps": bool(prefer_action_event),
        "prefer_result_state_checks": bool(prefer_action_event),
        "prefer_artifact_creation_checks": bool(prefer_action_event),
        "prefer_status_blocking_rules": bool(prefer_action_event),
        "prefer_service_failure_checks": bool(prefer_action_event),
    }

    signals = {
        "toggle_terms": toggle_terms,
        "notification_context": notification_context,
        "cross_field_constraint": cross_field_constraint,
        "text_input_validation": text_input_validation,
        "save_persistence": save_persistence,
        "permission_control": permission_control,
        "approval_flow": approval_flow,
        "table_management": table_management,
        "file_flow": file_flow,
        "action_verbs": action_verbs,
        "action_ui_terms": action_ui,
        "action_artifact_terms": action_artifact,
        "action_lifecycle_terms": action_lifecycle,
        "action_blocked_terms": action_blocked,
        "action_failure_terms": action_failure,
        "action_event_core": action_event_core,
        "action_named_flow": action_named_flow,
    }

    summary = (
        f"Primary workflow type: **{primary.replace('_', ' ')}**. "
        f"Signals: toggles={toggle_terms}, cross-field rules={cross_field_constraint}, "
        f"format-style validation cues={text_input_validation}."
    )
    if primary == "action_event_flow":
        summary += (
            f" Action/event cues: verbs={action_verbs}, artifact={action_artifact}, lifecycle={action_lifecycle}, "
            f"blocked={action_blocked}, failure={action_failure}."
        )
        summary += (
            " Prefer trigger → artifact → state checks, permission and precondition blocks, "
            "and service-failure behavior over generic field validation or save-only tests."
        )
    if prefer_state and not prefer_input_format:
        summary += " Prefer state/toggle and rule coverage over generic email/phone format tests unless the text explicitly requires format validation."

    return {
        "primary_type": primary,
        "secondary_types": secondaries[:5],
        "signals": signals,
        "routing_hints": routing_hints,
        "summary": summary.strip(),
    }


def detect_scenario_type_from_session(sess: Mapping[str, Any]) -> dict[str, Any]:
    """Classify using the same fields as ``expanded_context_from_builder_session``."""
    return detect_scenario_type(
        scenario_context=str(sess.get("sb_scenario_context") or ""),
        business_goal=str(sess.get("sb_business_goal") or ""),
        workflow_name=str(sess.get("sb_workflow_name") or ""),
        changed_areas_bulk=str(sess.get("sb_changed_areas_bulk") or ""),
        known_dependencies_bulk=str(sess.get("sb_known_dependencies_bulk") or ""),
    )


def classification_from_expanded(expanded: Any) -> dict[str, Any]:
    """Read classification dict from ``ExpandedGenerationContext`` (or empty)."""
    if expanded is None:
        return {}
    raw = getattr(expanded, "scenario_classification", None)
    return dict(raw) if isinstance(raw, dict) else {}


def primary_scenario_type(expanded: Any) -> str:
    c = classification_from_expanded(expanded)
    return str(c.get("primary_type") or "form_input")


def routing_hints(expanded: Any) -> dict[str, bool]:
    c = classification_from_expanded(expanded)
    rh = c.get("routing_hints")
    if isinstance(rh, dict):
        return {str(k): bool(v) for k, v in rh.items()}
    return {}

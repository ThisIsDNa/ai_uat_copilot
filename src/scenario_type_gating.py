"""
Strict scenario-type gating: block mismatched generation once a workflow family is known.

Used by AC suggestions, coverage slots, negative/positive derivation, intent, steps, and suite clustering.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from src.scenario_type_detection import classification_from_expanded, primary_scenario_type


def _norm(parts: str | tuple[str, ...] | list[str]) -> str:
    if isinstance(parts, (list, tuple)):
        return " ".join(" ".join((p or "").split()) for p in parts if p).strip()
    return " ".join((parts or "").split()).strip()


# Explicit cues that typed text / format / length validation is in scope (hybrid or form-heavy).
# Intentionally avoids bare "invalid" / "boundary" so expansion risk templates do not disable gating.
_EXPLICIT_TEXT_INPUT_VALIDATION = re.compile(
    r"(?i)\b(invalid\s+(?:email|phone|format|address|value|input|characters?)\b|invalid\s+format|malformed\b|"
    r"format|regex|pattern|max\s*length|maxlength|min\s*length|characters?|"
    r"must\s+contain|email\s+address|@\s*\w|@\w|digits?\s+only|10[- ]?digit|phone\s+number|mobile\s+number|"
    r"required\s+field|cannot\s+be\s+empty|left\s+blank|free\s+text|type\s+in|enter\s+.*\b(address|number)\b|"
    r"missing\s+required|boundary\s+value|edge\s+case|character\s+limit)\b"
)


def explicit_text_input_validation_context(*texts: str) -> bool:
    """True when source text clearly calls for typed-field or format validation (allows hybrid)."""
    return bool(_EXPLICIT_TEXT_INPUT_VALIDATION.search(_norm(texts)))


def state_toggle_strict_gating(expanded: Any | None, *, criterion_text: str = "") -> bool:
    """
    When True, form-style negatives/steps/AC lines must not leak into toggle-first scenarios.

    Hybrid: disabled when ``explicit_text_input_validation_context`` fires on criterion + expansion text.
    """
    if expanded is None:
        return False
    pt = primary_scenario_type(expanded)
    sig = (classification_from_expanded(expanded).get("signals") or {})
    is_toggle_primary = pt == "state_toggle" or (
        sig.get("toggle_terms") and sig.get("notification_context") and not sig.get("text_input_validation")
    )
    if not is_toggle_primary:
        return False
    # Hybrid: only user-provided scenario / AC / title text — not expansion boilerplate in ``summary_for_prompt``.
    if explicit_text_input_validation_context(criterion_text):
        return False
    return True


def approval_flow_strict_gating(expanded: Any | None, *, criterion_text: str = "") -> bool:
    if expanded is None or primary_scenario_type(expanded) != "approval_or_status_flow":
        return False
    if explicit_text_input_validation_context(criterion_text):
        return False
    return True


def file_flow_strict_gating(expanded: Any | None, *, criterion_text: str = "") -> bool:
    if expanded is None or primary_scenario_type(expanded) != "file_or_attachment_flow":
        return False
    if explicit_text_input_validation_context(criterion_text):
        return False
    return True


def action_event_flow_strict_gating(expanded: Any | None, *, criterion_text: str = "") -> bool:
    """When True, suppress form-style negatives/steps unless typed-input validation is explicit in user text."""
    if expanded is None or primary_scenario_type(expanded) != "action_event_flow":
        return False
    if explicit_text_input_validation_context(criterion_text):
        return False
    return True


def form_style_negative_forbidden(expanded: Any | None, *, criterion_text: str = "") -> bool:
    """True when invalid_format / boundary / required_missing negatives should be suppressed."""
    return bool(
        state_toggle_strict_gating(expanded, criterion_text=criterion_text)
        or approval_flow_strict_gating(expanded, criterion_text=criterion_text)
        or file_flow_strict_gating(expanded, criterion_text=criterion_text)
        or action_event_flow_strict_gating(expanded, criterion_text=criterion_text)
    )


def negative_conditions_rotated(expanded: Any | None, criterion_text: str) -> tuple[str, ...]:
    """Ordered negative ``forced_condition`` values for title derivation."""
    if action_event_flow_strict_gating(expanded, criterion_text=criterion_text):
        return ("rule_blocked", "permission_issue", "dependency_failure", "rule_blocked", "dependency_failure")
    if state_toggle_strict_gating(expanded, criterion_text=criterion_text):
        return ("rule_blocked", "permission_issue", "dependency_failure", "rule_blocked", "permission_issue")
    if approval_flow_strict_gating(expanded, criterion_text=criterion_text):
        return ("permission_issue", "dependency_failure", "permission_issue", "dependency_failure", "rule_blocked")
    if file_flow_strict_gating(expanded, criterion_text=criterion_text):
        return ("dependency_failure", "permission_issue", "rule_blocked", "dependency_failure", "permission_issue")
    return ("required_missing", "invalid_format", "boundary_value", "permission_issue", "dependency_failure")


def coerce_negative_condition_under_gating(
    condition: str,
    *,
    expanded: Any | None,
    criterion_text: str,
    title: str,
    negative_field_variant: int,
) -> str:
    """
    Remap disallowed negative conditions after detection or forced selection.

    Preserves explicit hybrid: if title/criterion clearly names format/boundary/missing field validation, keeps.
    """
    if condition == "blocked_rule":
        condition = "rule_blocked"
    if not form_style_negative_forbidden(expanded, criterion_text=criterion_text):
        return condition
    blob = _norm((title, criterion_text))
    if condition in ("invalid_format", "boundary_value", "required_missing"):
        if explicit_text_input_validation_context(blob):
            return condition
        opts = negative_conditions_rotated(expanded, criterion_text)
        return opts[int(negative_field_variant) % len(opts)]
    return condition


_FORM_AC_LINE = re.compile(
    r"(?i)\binvalid\s+email\s+format\b|\bphone\s+numbers?\s+must\b|\bvalidates\s+.+\s+at\s+field\s+level\b|"
    r"\bboundary\s+or\s+malformed\s+values\b|\bmissing\s+required\s+email\b|\binvalid\s+phone\s+format\b|"
    r"\bemail\s+boundary\b|\bmissing\s+required\s+phone\b"
)
_REGRESSION_FORM_DRIFT = re.compile(
    r"(?i)^Regression\s+check\s+for\s+\*\*.+\*\*:\s*validation,\s*save,\s+and\s+display"
)


def filter_ac_suggestions_under_gating(lines: list[str], expanded: Any | None) -> list[str]:
    """Drop form-only AC lines when strict toggle (or similar) gating applies."""
    if expanded is None:
        return lines
    crit_blob = " ".join(lines)
    if not form_style_negative_forbidden(expanded, criterion_text=crit_blob):
        return lines
    if explicit_text_input_validation_context(crit_blob):
        return lines
    out_lines: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if _FORM_AC_LINE.search(ln):
            continue
        if action_event_flow_strict_gating(expanded, criterion_text=crit_blob) and _REGRESSION_FORM_DRIFT.search(ln):
            ln = re.sub(
                r"(?i)validation,\s*save,\s*and\s+display",
                "action triggers, artifact state, and error handling",
                ln,
                count=1,
            )
        elif state_toggle_strict_gating(expanded, criterion_text=crit_blob) and _REGRESSION_FORM_DRIFT.search(ln):
            ln = re.sub(
                r"(?i)validation,\s*save,\s*and\s+display",
                "toggle states, blocked saves, and on-screen display",
                ln,
                count=1,
            )
        out_lines.append(ln)
    return out_lines


def sanitize_positive_coverage_slot(
    slot: Mapping[str, Any],
    expanded: Any | None,
    criterion_text: str,
) -> dict[str, Any]:
    """
    Replace form-shaped positive slots (email/phone valid_save, etc.) when toggle gating is active.
    Also remap generic save shells for ``action_event_flow``.
    """
    out = dict(slot)
    if expanded is None:
        return out
    if explicit_text_input_validation_context(criterion_text):
        return out

    if action_event_flow_strict_gating(expanded, criterion_text=criterion_text):
        scope = str(out.get("target_scope") or "").strip().lower()
        vf = str(out.get("verification_focus") or "").strip().lower()
        hint = str(out.get("intent_hint") or "")

        def set_ae(ts: str, vff: str, h: str, fc: str | None) -> None:
            out["target_scope"] = ts
            out["verification_focus"] = vff
            out["intent_hint"] = h
            if fc:
                out["forced_condition"] = fc
            else:
                out.pop("forced_condition", None)

        if scope in ("save_behavior", "contact_info", "email", "phone", "persistence") and vf in (
            "valid_save",
            "validation_pass",
        ):
            set_ae("generate_action", "action_trigger_success", "Primary Action - Generate Draft", None)
            return out
        if vf == "persistence_after_refresh" and scope not in ("action_persistence", "generated_draft"):
            set_ae(
                "action_persistence",
                "persists_after_refresh",
                "Artifact Persists After Refresh",
                "persisted_state_check",
            )
            return out
        if "update email" in hint.lower() or "update phone" in hint.lower() or "persist after refresh" in hint.lower():
            if "email" in hint.lower() or "phone" in hint.lower():
                set_ae(
                    "action_persistence",
                    "persists_after_refresh",
                    "Generated Artifact Persists After Refresh",
                    "persisted_state_check",
                )
                return out
        return out

    if not state_toggle_strict_gating(expanded, criterion_text=criterion_text):
        return out

    scope = str(out.get("target_scope") or "").strip().lower()
    vf = str(out.get("verification_focus") or "").strip().lower()
    hint = str(out.get("intent_hint") or "")

    def set_row(
        ts: str,
        vff: str,
        h: str,
        fc: str | None,
    ) -> None:
        out["target_scope"] = ts
        out["verification_focus"] = vff
        out["intent_hint"] = h
        if fc:
            out["forced_condition"] = fc
        else:
            out.pop("forced_condition", None)

    # Block classic form-save / field-validation / email-phone persist shells.
    if scope in ("email", "phone") and vf in ("valid_save", "validation_pass"):
        if scope == "email":
            set_row("email_toggle", "enable_transition", "Enable Email Notifications", None)
        else:
            set_row("sms_toggle", "disable_transition", "Disable SMS Notifications", None)
        return out

    if vf == "validation_pass" and scope not in ("email_toggle", "sms_toggle", "notification_preferences"):
        set_row("notification_preferences", "valid_save", "Save Valid Notification Preferences", None)
        return out

    if vf == "persistence_after_refresh" and scope in ("email", "phone") and "notification" not in hint.lower():
        set_row(
            "notification_preferences",
            "persistence_after_reload",
            "Preferences Persist After Reload",
            "persisted_state_check",
        )
        return out

    if "update email" in hint.lower() or "update phone" in hint.lower():
        set_row("notification_preferences", "valid_save", "Save Valid Notification Preferences", None)
        return out

    return out


def form_style_email_phone_step_text_forbidden(expanded: Any | None, *, linked_text_blob: str = "") -> bool:
    """When True, step helpers must not emit ``Enter email`` / ``Change phone`` style instructions."""
    if expanded is None:
        return False
    user_blob = _norm((linked_text_blob,))
    if action_event_flow_strict_gating(expanded, criterion_text=user_blob):
        return True
    if state_toggle_strict_gating(expanded, criterion_text=user_blob):
        return True
    if approval_flow_strict_gating(expanded, criterion_text=user_blob):
        return True
    if file_flow_strict_gating(expanded, criterion_text=user_blob):
        return True
    return False


def cluster_type_prefix(expanded: Any | None) -> str:
    """Prefix for suite-optimizer clusters to avoid cross-family merges."""
    if expanded is None:
        return "any"
    return primary_scenario_type(expanded) or "any"

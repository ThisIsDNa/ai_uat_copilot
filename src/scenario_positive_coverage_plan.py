"""
Batch-level positive test coverage distribution (Scenario → Coverage Plan → TC intent).

Assigns ``target_scope``, ``verification_focus``, and ``intent_hint`` per AC row so titles
and steps diversify *before* collision repair. Safe to extend with LLM enrichment later.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from src.scenario_builder_core import normalize_ac_id_token

if TYPE_CHECKING:
    from src.scenario_context_expansion import ExpandedGenerationContext


def _norm(s: str) -> str:
    return " ".join(str(s).split()).strip()


def _fields_from_expansion_and_context(
    expanded: "ExpandedGenerationContext | None",
    scenario_context: str,
) -> tuple[bool, bool, list[str]]:
    """Return (has_email, has_phone, ordered distinct field labels)."""
    from src.scenario_type_detection import classification_from_expanded, primary_scenario_type

    raw = (scenario_context or "").lower()
    fields: list[str] = []
    if expanded is not None:
        for f in getattr(expanded, "fields_involved", None) or []:
            t = str(f).strip().lower()
            if t and t not in fields:
                fields.append(t)
    c = classification_from_expanded(expanded)
    sig = c.get("signals") or {}
    skip_raw_format_fields = (
        primary_scenario_type(expanded) == "state_toggle"
        or primary_scenario_type(expanded) == "action_event_flow"
        or (sig.get("toggle_terms") and sig.get("notification_context"))
    ) and not re.search(r"(?i)\b(invalid|format|10[- ]?digit)\b", raw)
    if "email" in raw and "email" not in fields and not skip_raw_format_fields:
        fields.append("email")
    if ("phone" in raw or "10 digit" in raw or "10-digit" in raw) and not skip_raw_format_fields:
        if "phone" not in fields:
            fields.append("phone")
    has_email = "email" in fields
    has_phone = "phone" in fields
    return has_email, has_phone, fields


def _use_toggle_style_coverage(
    expanded: "ExpandedGenerationContext | None",
    scenario_context: str,
) -> bool:
    from src.scenario_type_detection import classification_from_expanded, primary_scenario_type

    if primary_scenario_type(expanded) == "state_toggle":
        return True
    c = classification_from_expanded(expanded)
    sec = c.get("secondary_types") or []
    sig = c.get("signals") or {}
    if "business_rule" in sec and sig.get("toggle_terms"):
        return True
    if sig.get("toggle_terms") and sig.get("notification_context") and not sig.get("text_input_validation"):
        return True
    low = (scenario_context or "").lower()
    if "notification" in low and sig.get("toggle_terms"):
        return True
    return False


def _use_action_event_coverage(
    expanded: "ExpandedGenerationContext | None",
    scenario_context: str,
) -> bool:
    from src.scenario_type_detection import primary_scenario_type

    _ = scenario_context
    return primary_scenario_type(expanded) == "action_event_flow"


def _slot_template_action_event(
    n: int,
) -> list[tuple[str, str, str, str | None]]:
    """Coverage rows for user-triggered actions with system artifacts (AI drafts, jobs, exports)."""
    base: list[tuple[str, str, str, str | None]] = [
        ("generate_action", "action_trigger_success", "Primary Action - Generate Draft", None),
        ("generated_draft", "artifact_created", "Generated Draft Appears In Panel", None),
        ("draft_state", "remains_draft", "Reply Draft Remains Draft State", None),
        ("draft_editability", "editable_before_send", "Draft Editable Before Send", None),
        (
            "action_persistence",
            "persists_after_refresh",
            "Generated Draft Persists After Refresh",
            "persisted_state_check",
        ),
        (
            "ui_consistency",
            "confirmation_or_visible_result",
            "Generation Result Visible In UI",
            "confirmation_check",
        ),
        ("authorized_generation", "workflow_outcome", "Authorized Role Generation Success", None),
        ("auto_send_prevention", "no_auto_send", "Draft Not Auto-Sent", None),
    ]
    return [base[i % len(base)] for i in range(n)]


def _slot_template_state_toggle(
    n: int,
) -> list[tuple[str, str, str, str | None]]:
    """Coverage rows for preference / toggle workflows (not text-field format suites)."""
    base: list[tuple[str, str, str, str | None]] = [
        ("email_toggle", "enable_transition", "Enable Email Notifications", None),
        ("sms_toggle", "disable_transition", "Disable SMS Notifications", None),
        ("notification_preferences", "valid_save", "Save Valid Notification Preferences", None),
        ("rule_enforcement", "blocked_combination", "Block All Notifications Disabled", "rule_blocked"),
        (
            "notification_preferences",
            "persistence_after_reload",
            "Preferences Persist After Reload",
            "persisted_state_check",
        ),
        ("confirmation", "confirmation_message", "Save Preferences Confirmation", "confirmation_check"),
        ("notification_preferences", "ui_consistency", "Preferences UI Consistency", None),
        ("notification_preferences", "business_outcome", "Notification Preferences Outcome", None),
    ]
    return [base[i % len(base)] for i in range(n)]


def _slot_template(
    has_email: bool,
    has_phone: bool,
    n: int,
) -> list[tuple[str, str, str, str | None]]:
    """
    Rows: (target_scope, verification_focus, intent_hint, forced_condition or None).

    ``forced_condition`` maps into ``infer_test_case_intent`` / ``_detect_condition``.
    """
    out: list[tuple[str, str, str, str | None]] = []
    if has_email and has_phone:
        base = [
            ("email", "valid_save", "Update Email - Valid Save", None),
            ("phone", "valid_save", "Update Phone - Valid Save", None),
            (
                "contact_info",
                "persistence_after_refresh",
                "Contact Info - Persist After Refresh",
                "persisted_state_check",
            ),
            (
                "confirmation",
                "confirmation_message",
                "Save Confirmation Message",
                "confirmation_check",
            ),
            ("email", "validation_pass", "Email Validation Pass", None),
            ("phone", "validation_pass", "Phone Validation Pass", None),
            (
                "contact_info",
                "valid_save",
                "Update Contact Info - Valid Save",
                None,
            ),
            (
                "ui_consistency",
                "ui_consistency",
                "Contact Update - UI Refresh",
                None,
            ),
            (
                "business_outcome",
                "business_outcome",
                "Workflow Outcome Check",
                None,
            ),
        ]
    elif has_email:
        base = [
            ("email", "valid_save", "Update Email - Valid Save", None),
            (
                "confirmation",
                "confirmation_message",
                "Save Confirmation Message",
                "confirmation_check",
            ),
            (
                "persistence",
                "persistence_after_refresh",
                "Email Persist After Refresh",
                "persisted_state_check",
            ),
            ("email", "validation_pass", "Email Validation Pass", None),
            ("save_behavior", "valid_save", "Save Updated Record", None),
            ("ui_consistency", "ui_consistency", "Profile UI Consistency Check", None),
        ]
    elif has_phone:
        base = [
            ("phone", "valid_save", "Update Phone - Valid Save", None),
            (
                "confirmation",
                "confirmation_message",
                "Save Confirmation Message",
                "confirmation_check",
            ),
            (
                "persistence",
                "persistence_after_refresh",
                "Phone Persist After Refresh",
                "persisted_state_check",
            ),
            ("phone", "validation_pass", "Phone Validation Pass", None),
            ("save_behavior", "valid_save", "Save Updated Record", None),
        ]
    else:
        base = [
            ("contact_info", "valid_save", "Update Contact Info - Valid Save", None),
            (
                "confirmation",
                "confirmation_message",
                "Save Confirmation Message",
                "confirmation_check",
            ),
            (
                "persistence",
                "persistence_after_refresh",
                "Persist After Refresh",
                "persisted_state_check",
            ),
            ("save_behavior", "valid_save", "Save Updated Record", None),
            ("ui_consistency", "ui_consistency", "UI Consistency After Save", None),
            ("business_outcome", "business_outcome", "Workflow Outcome Check", None),
        ]
    for i in range(n):
        out.append(base[i % len(base)])
    return out


def build_positive_coverage_plan_for_session(
    sess: Mapping[str, Any],
    expanded: "ExpandedGenerationContext | None",
) -> dict[int, dict[str, Any]]:
    """
    One coverage slot per AC row index that has non-empty criterion text.

    Returns ``ac_index`` → dict with ``target_scope``, ``verification_focus``, ``intent_hint``,
    optional ``forced_condition`` (for intent / title alignment).
    """
    sc = _norm(str(sess.get("sb_scenario_context") or ""))
    n_ac = int(sess.get("sb_n_ac") or 0)
    rows: list[tuple[int, str, str]] = []
    for i in range(n_ac):
        crit = _norm(str(sess.get(f"sb_ac_{i}_text") or ""))
        if not crit:
            continue
        raw_id = str(sess.get(f"sb_ac_{i}_id") or "").strip()
        aid = normalize_ac_id_token(raw_id) if raw_id else f"AC-{i + 1:02d}"
        rows.append((i, aid, crit))

    if not rows:
        return {}

    has_email, has_phone, _ = _fields_from_expansion_and_context(expanded, sc)
    if _use_action_event_coverage(expanded, sc):
        templates = _slot_template_action_event(len(rows))
    elif _use_toggle_style_coverage(expanded, sc):
        templates = _slot_template_state_toggle(len(rows))
    else:
        templates = _slot_template(has_email, has_phone, len(rows))
    plan: dict[int, dict[str, Any]] = {}
    for (ac_i, aid, crit), (scope, vf, hint, fc) in zip(rows, templates):
        low = crit.lower()
        # AC semantics override generic field rotation (sign-in, enrollment, etc.).
        if re.search(r"(?i)\bsign\s*-?\s*in\b|\blog\s*in\b|\bauthenticate\b|\bmfa\b|\b2fa\b", low):
            scope, vf, hint, fc = (
                "save_behavior",
                "valid_save",
                "Sign In Success",
                None,
            )
        elif re.search(r"(?i)\benroll|\bregistration\b|\bsign\s*up\b", low):
            scope, vf, hint, fc = (
                "save_behavior",
                "valid_save",
                "Submit Enrollment",
                None,
            )
        slot: dict[str, Any] = {
            "ac_index": ac_i,
            "ac_id": aid,
            "target_scope": scope,
            "verification_focus": vf,
            "intent_hint": hint,
            "criterion_excerpt": crit[:180],
        }
        if fc:
            slot["forced_condition"] = fc
        # Nudge row toward AC wording when strongly signaled (without breaking distribution).
        if "persist" in low or "refresh" in low or "re-open" in low:
            if _use_action_event_coverage(expanded, sc):
                slot["verification_focus"] = "persists_after_refresh"
                slot["forced_condition"] = "persisted_state_check"
                slot["intent_hint"] = "Generated Draft Persists After Refresh"
                slot["target_scope"] = "action_persistence"
            elif _use_toggle_style_coverage(expanded, sc):
                slot["verification_focus"] = "persistence_after_reload"
                slot["forced_condition"] = "persisted_state_check"
                slot["intent_hint"] = "Preferences Persist After Reload"
                slot["target_scope"] = "notification_preferences"
            elif scope not in ("persistence", "contact_info") or vf != "persistence_after_refresh":
                slot["verification_focus"] = "persistence_after_refresh"
                slot["forced_condition"] = "persisted_state_check"
                if has_email and has_phone and scope in ("email", "phone", "contact_info"):
                    slot["intent_hint"] = (
                        "Contact Info - Persist After Refresh"
                        if scope == "contact_info"
                        else (
                            "Email Persist After Refresh"
                            if scope == "email"
                            else "Phone Persist After Refresh"
                        )
                    )
                elif has_email and not has_phone:
                    slot["intent_hint"] = "Email Persist After Refresh"
                elif has_phone and not has_email:
                    slot["intent_hint"] = "Phone Persist After Refresh"
                else:
                    slot["intent_hint"] = "Persist After Refresh"
                slot["target_scope"] = (
                    "contact_info" if has_email and has_phone else ("email" if has_email else "phone")
                )
        elif re.search(r"(?i)\bconfirm|\btoast|\bconfirmation\b", low) and "persist" not in low:
            slot["verification_focus"] = "confirmation_message"
            slot["forced_condition"] = "confirmation_check"
            if _use_action_event_coverage(expanded, sc):
                slot["intent_hint"] = "Generation Result Or Confirmation Visible"
                slot["target_scope"] = "ui_consistency"
            elif _use_toggle_style_coverage(expanded, sc):
                slot["intent_hint"] = "Save Preferences Confirmation"
                slot["target_scope"] = "confirmation"
            else:
                slot["intent_hint"] = (
                    "Phone Save Confirmation"
                    if scope == "phone" and has_phone
                    else (
                        "Email Save Confirmation"
                        if scope == "email" and has_email
                        else "Save Confirmation Message"
                    )
                )
                slot["target_scope"] = scope if scope in ("email", "phone", "confirmation") else "confirmation"
        plan[ac_i] = slot
    return plan


def _semantic_positive_bucket(slot: Mapping[str, Any]) -> str:
    """Coarse bucket for duplicate suppression (persistence / confirmation families)."""
    hint = str(slot.get("intent_hint") or "").lower()
    vf = str(slot.get("verification_focus") or "").lower()
    sc = str(slot.get("target_scope") or "").lower()
    if vf == "persistence_after_refresh" or "persist" in hint:
        if "contact" in hint or sc == "contact_info":
            return "PERS_CONTACT"
        if "phone" in hint and "email" not in hint.replace("phone", ""):
            return "PERS_PHONE"
        if "email" in hint and "phone" not in hint:
            return "PERS_EMAIL"
        if any(x in hint for x in ("persist updated", "persist after refresh", "persist after")):
            return "PERS_GENERIC"
        return "PERS_OTHER"
    if vf == "confirmation_message" or sc == "confirmation" or "save confirmation" in hint:
        return "CONF_MSG"
    return f"OTHER:{vf}:{sc}"


def _replacement_slot_for_bucket(
    bucket: str,
    *,
    has_email: bool,
    has_phone: bool,
    counts: dict[str, int],
    limits: dict[str, int],
) -> dict[str, Any] | None:
    """Pick a non-overlapping positive slot when ``bucket`` is already saturated."""
    candidates: list[tuple[str, str, str, str | None]] = []
    if bucket in ("PERS_GENERIC", "PERS_OTHER", "PERS_EMAIL", "PERS_PHONE", "PERS_CONTACT"):
        if has_email and has_phone:
            candidates.extend(
                [
                    ("phone", "validation_pass", "Phone Validation Pass", None),
                    ("email", "validation_pass", "Email Validation Pass", None),
                    ("contact_info", "valid_save", "Update Contact Info - Valid Save", None),
                    ("ui_consistency", "ui_consistency", "Contact Update - UI Refresh", None),
                ]
            )
        if has_email and counts.get("PERS_EMAIL", 0) < limits.get("PERS_EMAIL", 1):
            candidates.append(
                ("email", "persistence_after_refresh", "Email Persist After Refresh", "persisted_state_check")
            )
        if has_phone and counts.get("PERS_PHONE", 0) < limits.get("PERS_PHONE", 1):
            candidates.append(
                ("phone", "persistence_after_refresh", "Phone Persist After Refresh", "persisted_state_check")
            )
        if has_email and has_phone and counts.get("PERS_CONTACT", 0) < limits.get("PERS_CONTACT", 1):
            candidates.insert(
                0,
                (
                    "contact_info",
                    "persistence_after_refresh",
                    "Contact Info - Persist After Refresh",
                    "persisted_state_check",
                ),
            )
    elif bucket == "CONF_MSG":
        candidates = [
            ("email", "validation_pass", "Email Validation Pass", None),
            ("phone", "valid_save", "Update Phone - Valid Save", None),
            ("ui_consistency", "ui_consistency", "Contact Update - UI Refresh", None),
        ]
    for scope, vf, hint, fc in candidates:
        probe = {"target_scope": scope, "verification_focus": vf, "intent_hint": hint}
        if fc:
            probe["forced_condition"] = fc
        b2 = _semantic_positive_bucket(probe)
        if counts.get(b2, 0) < limits.get(b2, 99):
            return {
                "target_scope": scope,
                "verification_focus": vf,
                "intent_hint": hint,
                **({"forced_condition": fc} if fc else {}),
            }
    return None


def consolidate_positive_coverage_plan(
    plan: dict[int, dict[str, Any]],
    expanded: "ExpandedGenerationContext | None",
    sess: Mapping[str, Any],
) -> dict[int, dict[str, Any]]:
    """
    Reduce semantically overlapping positive slots (duplicate persistence / confirmation shells).

    Preserves AC row keys; mutates slot content toward more specific, non-redundant coverage.
    """
    if not plan:
        return plan
    from src.scenario_type_gating import sanitize_positive_coverage_slot

    sc = _norm(str(sess.get("sb_scenario_context") or ""))
    has_email, has_phone, _ = _fields_from_expansion_and_context(expanded, sc)
    limits = {
        "PERS_GENERIC": 0 if (has_email and has_phone) else 1,
        "PERS_CONTACT": 1,
        "PERS_EMAIL": 1,
        "PERS_PHONE": 1,
        "PERS_OTHER": 99,
        "CONF_MSG": 1,
    }
    out: dict[int, dict[str, Any]] = {k: dict(v) for k, v in plan.items()}
    counts: dict[str, int] = {}

    for ac_i in sorted(out.keys()):
        slot = out[ac_i]
        meta = {k: slot[k] for k in ("ac_index", "ac_id", "criterion_excerpt") if k in slot}
        bucket = _semantic_positive_bucket(slot)
        while counts.get(bucket, 0) >= limits.get(bucket, 99):
            rep = _replacement_slot_for_bucket(
                bucket,
                has_email=has_email,
                has_phone=has_phone,
                counts=counts,
                limits=limits,
            )
            if not rep:
                break
            slot.update(rep)
            if "forced_condition" not in rep:
                slot.pop("forced_condition", None)
            bucket = _semantic_positive_bucket(slot)
        slot.update(meta)
        slot = sanitize_positive_coverage_slot(
            slot,
            expanded,
            str(slot.get("criterion_excerpt") or ""),
        )
        counts[bucket] = counts.get(bucket, 0) + 1
        out[ac_i] = slot
    from src.scenario_domain_labels import apply_domain_hints_to_positive_slots

    apply_domain_hints_to_positive_slots(out, expanded, sc)
    return out


def coverage_slot_from_test_case_title(title: str) -> dict[str, Any] | None:
    """
    Infer a minimal coverage slot from an existing positive title (single-TC step generation).

    Does not depend on batch planning — keeps smart-link behavior local to the TC row.
    """
    t = (title or "").strip()
    if not t or " - " not in t:
        return None
    right = t.split(" - ", 1)[1].lower()
    fc: str | None = None
    vf = "valid_save"
    scope = "contact_info"
    hint = t.split(" - ", 1)[1].strip()

    if "generate reply" in right or ("generate" in right and "draft" in right):
        vf = "action_trigger_success"
        scope = "generate_action"
    elif "draft" in right and ("persist" in right or "refresh" in right):
        vf = "persists_after_refresh"
        scope = "action_persistence"
        fc = "persisted_state_check"
    elif "remains draft" in right or ("draft" in right and "state" in right):
        vf = "remains_draft"
        scope = "draft_state"
    elif "editable" in right and "before" in right:
        vf = "editable_before_send"
        scope = "draft_editability"
    elif "not auto" in right or "no auto" in right or "auto-sent" in right:
        vf = "no_auto_send"
        scope = "auto_send_prevention"
    elif "service failure" in right or "no draft" in right:
        vf = "failure_no_artifact"
        scope = "service_failure"
    elif "enable" in right and "email" in right and "notification" in right:
        vf = "enable_transition"
        scope = "email_toggle"
    elif "disable" in right and "sms" in right:
        vf = "disable_transition"
        scope = "sms_toggle"
    elif "block" in right and "notification" in right:
        vf = "blocked_combination"
        scope = "rule_enforcement"
        fc = "rule_blocked"
    elif "preferences persist" in right or ("preference" in right and "persist" in right):
        vf = "persistence_after_reload"
        scope = "notification_preferences"
        fc = "persisted_state_check"
    elif "save valid notification" in right or "valid notification preference" in right:
        vf = "valid_save"
        scope = "notification_preferences"
    elif "persist" in right or "refresh" in right:
        vf = "persistence_after_refresh"
        fc = "persisted_state_check"
        if "email" in right and "phone" not in right:
            scope = "email"
        elif "phone" in right and "email" not in right:
            scope = "phone"
        elif "contact" in right:
            scope = "contact_info"
        else:
            scope = "persistence"
    elif "confirmation" in right or "confirm" in right or "toast" in right:
        vf = "confirmation_message"
        fc = "confirmation_check"
        scope = "confirmation"
    elif "phone" in right:
        scope = "phone"
    elif "email" in right:
        scope = "email"
    elif "validation pass" in right:
        vf = "validation_pass"
        if "phone" in right:
            scope = "phone"
        elif "email" in right:
            scope = "email"
    elif "ui" in right or "refresh" in right:
        vf = "ui_consistency"
        scope = "ui_consistency"
    elif "outcome" in right or "workflow" in right:
        vf = "business_outcome"
        scope = "business_outcome"

    return {
        "target_scope": scope,
        "verification_focus": vf,
        "intent_hint": hint,
        **({"forced_condition": fc} if fc else {}),
    }


def positive_coverage_slot_for_tc_session(
    sess: Mapping[str, Any],
    tc_slot: int,
    expanded: Any,
) -> dict[str, Any] | None:
    """
    Resolve positive coverage slot: prefer the batch plan slot from the mapped AC row when
    it agrees with the TC title; otherwise use the title-derived slot so multiple TCs mapped
    to one AC can still diverge (confirmation vs persistence, etc.).
    """
    title = str(sess.get(f"sb_tc_{tc_slot}_text") or "").strip()
    tid = str(sess.get(f"sb_tc_{tc_slot}_id") or "").strip()
    n_ac = int(sess.get("sb_n_ac") or 0)
    ac_hit: int | None = None
    if tid:
        for i in range(n_ac):
            raw = sess.get(f"sb_ac_{i}_map") or []
            if not isinstance(raw, list):
                continue
            ids = {str(x).strip() for x in raw if x is not None and str(x).strip()}
            if tid in ids:
                ac_hit = i
                break
    title_slot = coverage_slot_from_test_case_title(title) or {}
    if ac_hit is not None:
        plan = consolidate_positive_coverage_plan(
            build_positive_coverage_plan_for_session(sess, expanded),
            expanded,
            sess,
        )
        plan_slot = plan.get(ac_hit)
        if isinstance(plan_slot, dict) and plan_slot:
            ps = dict(plan_slot)
            ts = dict(title_slot) if title_slot else {}
            p_fc = str(ps.get("forced_condition") or "")
            t_fc = str(ts.get("forced_condition") or "")
            if t_fc and t_fc != p_fc:
                return ts if ts else ps
            p_vf = str(ps.get("verification_focus") or "")
            t_vf = str(ts.get("verification_focus") or "")
            if t_vf and t_vf != p_vf and ts:
                return ts
            return ps
    return dict(title_slot) if title_slot else None

"""
Reusable context expansion for AI Scenario Builder generation (Context Intake foundation).

Builds a structured, heuristic ``ExpandedGenerationContext`` from free-text **scenario context**
plus goal, workflow, changed areas, and dependencies. Intended as **additive** input to AC / TC /
step generators — never replaces user-authored lines without explicit review in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.scenario_builder_core import parse_bullet_line_items, parse_changed_areas_bulk
from src.scenario_domain_labels import (
    extract_primary_action_label,
    filter_cross_scenario_rule_noise,
    infer_domain_naming,
)

_ENTITY_PAT = re.compile(
    r"(?i)\b(provider|patient|member|user|admin|administrator|customer|clinician|tester|staff)\b"
)
_FIELD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bemail\b|\bemail\s+address\b"), "email"),
    (re.compile(r"(?i)\bphone\b|\bmobile\b|\bcell\b|\b10\s*digits?\b|\bdigit\s+phone\b"), "phone"),
    (re.compile(r"(?i)\baddress\b|\bstreet\b|\bzip\b|\bpostal\b"), "address"),
    (re.compile(r"(?i)\bpassword\b|\bmfa\b|\b2fa\b|\botp\b"), "password or MFA"),
    (re.compile(r"(?i)\bdate\s+of\s+birth\b|\bdob\b|\bbirth\s*date\b"), "date of birth"),
    (re.compile(r"(?i)\bname\b|\bfirst\s+name\b|\blast\s+name\b"), "name"),
)


def _norm_blob(*parts: str | None) -> str:
    return " ".join(" ".join((p or "").split()) for p in parts if p).strip()


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        t = (raw or "").strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _infer_entities(blob: str) -> list[str]:
    found = _ENTITY_PAT.findall(blob or "")
    return _dedupe_preserve([x[:1].upper() + x[1:].lower() if x else x for x in found])


def _infer_fields(blob: str) -> list[str]:
    out: list[str] = []
    for pat, label in _FIELD_PATTERNS:
        if pat.search(blob or ""):
            out.append(label)
    return _dedupe_preserve(out)


def _infer_validation_rules(
    blob: str,
    fields: list[str],
    *,
    classification: dict[str, Any] | None = None,
) -> list[str]:
    from src.scenario_type_gating import explicit_text_input_validation_context

    rules: list[str] = []
    low = (blob or "").lower()
    rh = (classification or {}).get("routing_hints") or {}
    prefer_format = bool(rh.get("prefer_input_format_validation", True))
    sig = (classification or {}).get("signals") or {}
    pt = (classification or {}).get("primary_type") or ""
    toggle_no_typed = (
        (pt == "state_toggle" or (sig.get("toggle_terms") and sig.get("notification_context")))
        and not explicit_text_input_validation_context(blob or "")
    )
    action_no_typed = pt == "action_event_flow" and not explicit_text_input_validation_context(blob or "")
    if (prefer_format or sig.get("text_input_validation")) and not toggle_no_typed and not action_no_typed:
        if "email" in fields or re.search(r"(?i)\bvalid\s+email\b|\bemail\s+format\b", blob or ""):
            rules.append("Invalid email format is rejected with a clear field-level error before save.")
        if "phone" in fields or ("10" in low and "digit" in low):
            rules.append("Phone numbers must meet length/format rules (e.g. 10 digits) before the record can save.")
    if re.search(r"(?i)\brequired\s+field\b|\bmissing\s+required\b|\bmust\s+be\s+provided\b", blob or ""):
        rules.append("Required fields cannot be left empty; the UI blocks or warns before persisting.")
    if prefer_format and re.search(r"(?i)\bvalid\s+format\b|\binvalid\s+input\b", blob or ""):
        rules.append("Invalid input shows validation feedback and does not silently persist bad data.")
    if pt != "action_event_flow" or explicit_text_input_validation_context(blob or ""):
        if sig.get("toggle_terms") and sig.get("notification_context"):
            rules.append(
                "Turning off every notification channel while at least one must remain enabled is blocked with a clear message; save does not commit the invalid combination."
            )
        if sig.get("cross_field_constraint") or "business_rule" in ((classification or {}).get("secondary_types") or []):
            rules.append(
                "Cross-field rules (e.g. at least one method on) are enforced: forbidden combinations cannot be saved silently."
            )
    elif re.search(r"(?i)\b(notification|preference|toggle|channel)\b.*\b(on|off|enabled|disabled)\b", blob):
        if sig.get("toggle_terms") and sig.get("notification_context"):
            rules.append(
                "Turning off every notification channel while at least one must remain enabled is blocked with a clear message; save does not commit the invalid combination."
            )
        if (
            re.search(r"(?i)\bcross[- ]field|forbidden combination|at least one\s+(method|channel)\b", blob)
            and (
                sig.get("cross_field_constraint")
                or "business_rule" in ((classification or {}).get("secondary_types") or [])
            )
        ):
            rules.append(
                "Cross-field rules (e.g. at least one method on) are enforced: forbidden combinations cannot be saved silently."
            )
    rules = filter_cross_scenario_rule_noise(rules, blob=blob, primary_type=pt)
    return _dedupe_preserve(rules)


def _infer_expected_behavior(blob: str, *, classification: dict[str, Any] | None = None) -> list[str]:
    low = (blob or "").lower()
    out: list[str] = []
    sig = (classification or {}).get("signals") or {}
    pt = (classification or {}).get("primary_type") or ""
    if pt == "action_event_flow":
        if re.search(r"(?i)\b(generate|create|run|trigger|invoke|launch|retry)\b", low):
            out.append(
                "The primary action (button, command, or menu item) invokes the backend workflow and surfaces the resulting artifact or state in the UI."
            )
        if re.search(r"(?i)\bdraft\b|generated|insert", low):
            out.append(
                "System-created content appears as a **draft** or intermediate record until an explicit user or workflow step advances it."
            )
        if re.search(r"(?i)\bno\s+auto|not\s+auto|does\s+not\s+send|review\s+before\s+send", low):
            out.append("The system does **not** auto-send or auto-complete forbidden transitions after generation.")
        if re.search(r"(?i)\bedit|editable|modify\s+before", low):
            out.append("The user can review or edit the generated artifact before the next committed action (send, submit, etc.).")
        if re.search(r"(?i)\b(refresh|reload|re-?open|dashboard)\b", low) and re.search(
            r"(?i)\bpersist|remain|still\s+(visible|present)\b", low
        ):
            out.append("After refresh or revisit, the generated artifact or status remains consistent with the last successful action.")
        return _dedupe_preserve(out)
    if pt == "state_toggle" or (sig.get("toggle_terms") and sig.get("notification_context")):
        out.append(
            "Each toggle or switch reflects ON/OFF immediately in the UI; saving commits the chosen combination and reload shows the same states."
        )
    if re.search(r"(?i)\bsave\b|\bpersist\b|\bupdate\b|\bstore\b", low):
        out.append("Successful save persists updated values and refreshes or re-queries visible data.")
    if re.search(r"(?i)\bconfirm\b|\bconfirmation\b|\btoast\b|\bmessage\b", low):
        out.append("After a successful update, the user sees an explicit confirmation message or notice.")
    if re.search(r"(?i)\bdisplay\b|\bvisible\b|\bshown\b", low):
        out.append("Updated values are visible in the UI immediately or after refresh, consistent with server state.")
    return _dedupe_preserve(out)


def _infer_risks(blob: str, fields: list[str], *, classification: dict[str, Any] | None = None) -> list[str]:
    from src.scenario_type_gating import explicit_text_input_validation_context

    low = (blob or "").lower()
    out: list[str] = []
    rh = (classification or {}).get("routing_hints") or {}
    prefer_format = bool(rh.get("prefer_input_format_validation", True))
    sig = (classification or {}).get("signals") or {}
    pt = (classification or {}).get("primary_type") or ""
    toggle_no_typed = (
        (pt == "state_toggle" or (sig.get("toggle_terms") and sig.get("notification_context")))
        and not explicit_text_input_validation_context(blob or "")
    )
    action_no_typed = pt == "action_event_flow" and not explicit_text_input_validation_context(blob or "")
    if fields and prefer_format and not toggle_no_typed and not action_no_typed:
        out.append(f"Boundary or malformed values for: {', '.join(fields[:4])}.")
    if (
        sig.get("toggle_terms")
        and sig.get("notification_context")
        and pt != "action_event_flow"
    ):
        out.append("User disables all notification toggles and attempts save — system must block and preserve last valid state.")
    if pt == "action_event_flow":
        if re.search(r"(?i)\b(closed|archived|final|already\s+sent)\b", low) and re.search(
            r"(?i)\b(block|prevent|disable|cannot)\b", low
        ):
            out.append("Blocked preconditions (e.g. closed conversation or final state) prevent the action without inserting a stale artifact.")
        if re.search(r"(?i)\bpermission|role|only\s+\w+\s+(can|may)\b", low):
            out.append("Users without required roles cannot trigger the action; UI shows disabled control or permission denial.")
        if re.search(r"(?i)\b(fail|unavailable|timeout|error|no\s+draft|inserts?\s+no)\b", low):
            out.append("When the downstream service fails, the UI shows a clear error and does not leave a partial or phantom draft.")
        if not out:
            out.append("Action completes with visible result state, or fails with explicit feedback — no silent no-op.")
    if re.search(r"(?i)\bpermission\b|\bunauthori[sz]ed\b|\baccess\b", low):
        out.append("Unauthorized role or session cannot perform the update.")
    if re.search(r"(?i)\bdependency\b|\bdownstream\b|\bapi\b|\bservice\b", low):
        out.append("Downstream service failure surfaces a controlled error without corrupting data.")
    if not out:
        out.append("Incomplete or invalid data must not produce a false success state.")
    return _dedupe_preserve(out)


def _infer_success(blob: str, *, classification: dict[str, Any] | None = None) -> list[str]:
    low = (blob or "").lower()
    out: list[str] = []
    pt = (classification or {}).get("primary_type") or ""
    if pt == "action_event_flow":
        if re.search(r"(?i)\b(generate|run|trigger|create)\b", low):
            out.append("Authorized trigger completes and the expected draft or record appears for review.")
        return _dedupe_preserve(out)
    if re.search(r"(?i)\bsuccess\b|\bcomplete\b|\bhappy\s*path\b", low):
        out.append("Valid complete data completes the flow without errors.")
    if re.search(r"(?i)\bsave\b|\bupdate\b", low):
        out.append("All required validations pass and changes commit successfully.")
    return _dedupe_preserve(out)


def _ui_surface_hint(blob: str, workflow: str, *, classification: dict[str, Any] | None = None) -> str:
    w = (workflow or "").strip()
    low = (blob or "").lower()
    sig = (classification or {}).get("signals") or {}
    primary = (classification or {}).get("primary_type") or "form_input"
    if primary == "action_event_flow":
        if re.search(r"(?i)\bsupport|agent|inbox|ticket|conversation|console", low):
            return "the support console or conversation workspace where the primary action control is available"
        if re.search(r"(?i)\bdashboard|queue|job|export", low):
            return "the dashboard or job panel where the triggered action and its results are shown"
        return "the screen or panel where the user triggers the workflow action and reviews its result"
    if primary == "state_toggle" or (sig.get("toggle_terms") and sig.get("notification_context")):
        if "notification" in low or "preference" in low:
            return "the notification preferences or alerts screen (toggles, switches, or checkboxes)"
        return "the settings or preferences panel where toggles control enabled/disabled states"
    if w:
        return f"the {w.lower()} screen or its primary form"
    if any(k in low for k in ("profile", "account", "contact", "demographic")):
        return "the profile or contact-information form"
    if any(k in low for k in ("enrollment", "registration", "sign up", "signup")):
        return "the enrollment or registration form"
    if any(k in low for k in ("checkout", "cart", "payment")):
        return "the checkout or payment section"
    if any(k in low for k in ("chart", "patient")):
        return "the patient chart or clinical summary area"
    return ""


def _primary_entity(entities: list[str], blob: str) -> str:
    if entities:
        return entities[0]
    m = re.match(r"(?i)^\s*([A-Z][a-z]+)", (blob or "").strip())
    if m and m.group(1).lower() not in {"the", "when", "after", "before"}:
        return m.group(1)
    return "User"


def _infer_action_event_lines(blob: str, classification: dict[str, Any]) -> list[str]:
    """Structured action/event hints for summaries and downstream routing (heuristic)."""
    if (classification or {}).get("primary_type") != "action_event_flow":
        return []
    low = blob or ""
    lines: list[str] = []
    pal = extract_primary_action_label(low)
    m = re.search(
        r"(?i)\b(generate\s+reply|regenerate\s+\w+|run\s+ai\s+\w+|create\s+invoice\s+draft|start\s+export\s+job)\b",
        low,
    )
    if pal:
        lines.append(f"Primary action: **{pal}**.")
    elif m:
        lines.append(f"Primary action: **{m.group(0).strip()}**.")
    elif re.search(r"(?i)\b(generate|create|run|trigger|launch|retry|invoke)\b", low):
        lines.append("Primary action: use the main **Generate** / **Run** control described in scenario context.")
    dn = infer_domain_naming(low)
    if dn.artifact_singular:
        lines.append(f"Result focus: **{dn.artifact_singular}** (system output for review).")
    elif re.search(r"(?i)\bdraft\b|\bai[-\s]?generated\b|\bresponse\s+panel\b|\bdraft\s+panel\b|\binserted\s+draft\b", low):
        lines.append("Result focus: system-inserted **draft** or generated content for review.")
    if re.search(r"(?i)\b(not\s+sent|no\s+auto[-\s]?send|review\s+before\s+send)\b", low):
        lines.append("Lifecycle: content must **not** auto-send; explicit step advances state.")
    if re.search(r"(?i)\b(closed|archived)\b.*\b(conversation|record)\b|\bconversation\s+closed\b", low):
        lines.append("Blocked when: invalid precondition (e.g. **closed** conversation) — action disabled or rejected.")
    if re.search(r"(?i)\b(support[-\s]?agent|admin)\b.*\b(can|only|may)\b", low) or re.search(
        r"(?i)\bonly\s+\w+\s+(can|may)\s+generate\b", low
    ):
        lines.append("Permission: only **authorized roles** may trigger generation or the primary action.")
    if re.search(r"(?i)\b(service\s+fail|unavailable|timeout|no\s+draft|inserts?\s+no|error\s+message)\b", low):
        lines.append("Failure: clear error; **no** partial draft or silent success.")
    if re.search(r"(?i)\bedit\b.*\b(before|prior)\b.*\b(send|submit)\b", low):
        lines.append("Post-action: user may **edit** generated content before send/submit.")
    return _dedupe_preserve(lines)


def _build_summary(
    *,
    scenario_context: str,
    business_goal: str,
    workflow_name: str,
    changed_areas_bulk: str,
    known_dependencies_bulk: str,
    entities: list[str],
    fields: list[str],
    validation_rules: list[str],
    expected_system_behavior: list[str],
    risks_edge_cases: list[str],
    success_conditions: list[str],
    primary_entity: str,
    ui_surface_hint: str,
    scenario_classification: dict[str, Any] | None = None,
    action_event_lines: list[str] | None = None,
) -> str:
    lines: list[str] = []
    if scenario_context.strip():
        lines.append("### Author scenario context\n" + scenario_context.strip())
    if business_goal.strip():
        lines.append("### Business goal\n" + " ".join(business_goal.split()).strip())
    if workflow_name.strip():
        lines.append("### Workflow\n" + workflow_name.strip())
    ca = parse_changed_areas_bulk(changed_areas_bulk or "")
    if ca:
        ca_txt = "; ".join(
            f"{(r.get('area') or '').strip()} ({(r.get('type') or '').strip()})".strip(" ()")
            for r in ca
            if isinstance(r, dict) and (str(r.get("area") or "").strip() or str(r.get("type") or "").strip())
        )
        if ca_txt:
            lines.append("### Changed areas\n" + ca_txt)
    deps = parse_bullet_line_items(known_dependencies_bulk or "")
    if deps:
        lines.append("### Dependencies\n" + "; ".join(deps[:12]))
    sig = []
    if primary_entity:
        sig.append(f"Primary actor: {primary_entity}")
    if entities:
        sig.append("Actors: " + ", ".join(entities[:6]))
    if fields:
        sig.append("Data fields: " + ", ".join(fields))
    if ui_surface_hint:
        sig.append(f"UI focus: {ui_surface_hint}")
    if sig:
        lines.append("### Inferred signals\n" + "\n".join(f"- {s}" for s in sig))
    if validation_rules:
        lines.append("### Validation / rules\n" + "\n".join(f"- {r}" for r in validation_rules))
    if expected_system_behavior:
        lines.append("### Expected system behavior\n" + "\n".join(f"- {r}" for r in expected_system_behavior))
    if success_conditions:
        lines.append("### Success conditions\n" + "\n".join(f"- {r}" for r in success_conditions))
    if risks_edge_cases:
        lines.append("### Risks / edge cases\n" + "\n".join(f"- {r}" for r in risks_edge_cases))
    if scenario_classification:
        summ = str(scenario_classification.get("summary") or "").strip()
        if summ:
            lines.append("### Scenario type (routing)\n" + summ)
    ae = [x for x in (action_event_lines or []) if str(x).strip()]
    if ae:
        lines.append("### Action / event workflow\n" + "\n".join(f"- {x}" for x in ae))
    return "\n\n".join(lines).strip()


def _filter_fields_for_classification(
    fields: list[str],
    blob: str,
    classification: dict[str, Any],
) -> list[str]:
    """Drop spurious email/phone 'data fields' when the scenario is notification toggle–centric."""
    signals = classification.get("signals") or {}
    primary = classification.get("primary_type") or "form_input"
    low = blob.lower()
    if primary != "state_toggle" and not (signals.get("toggle_terms") and signals.get("notification_context")):
        return fields
    if not (signals.get("toggle_terms") and signals.get("notification_context")):
        return fields
    from src.scenario_type_gating import explicit_text_input_validation_context

    out: list[str] = []
    for f in fields:
        if f == "email" and not explicit_text_input_validation_context(blob):
            continue
        if f == "phone" and re.search(r"(?i)\bsms\b", low) and not explicit_text_input_validation_context(
            blob
        ) and not re.search(r"(?i)\b10[- ]?digit|phone number|mobile number|call\b", blob):
            continue
        out.append(f)
    return out if out else fields


@dataclass
class ExpandedGenerationContext:
    """Structured hints for generation prompts (additive; safe when mostly empty)."""

    entities: list[str] = field(default_factory=list)
    fields_involved: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    expected_system_behavior: list[str] = field(default_factory=list)
    risks_edge_cases: list[str] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    primary_entity: str = "User"
    ui_surface_hint: str = ""
    summary_for_prompt: str = ""
    scenario_classification: dict[str, Any] = field(default_factory=dict)
    action_event_lines: list[str] = field(default_factory=list)
    # Domain polish (action_event and other flows): concrete labels for titles/steps.
    primary_action_label: str = ""
    artifact_label_singular: str = ""
    domain_record_label: str = ""
    panel_location_phrase: str = ""

    def has_rich_signals(self) -> bool:
        return bool(
            self.fields_involved
            or self.validation_rules
            or self.expected_system_behavior
            or self.action_event_lines
            or self.primary_action_label
            or (self.summary_for_prompt and len(self.summary_for_prompt) > 80)
        )


def expand_scenario_context(
    *,
    scenario_context: str | None = None,
    business_goal: str | None = None,
    workflow_name: str | None = None,
    changed_areas_bulk: str | None = None,
    known_dependencies_bulk: str | None = None,
) -> ExpandedGenerationContext:
    """
    Derive structured generation hints from user-provided context and related builder fields.

    Heuristic only — no network calls. Callers should treat output as **hints**, not ground truth.
    """
    from src.scenario_type_detection import detect_scenario_type

    sc = (scenario_context or "").strip()
    bg = (business_goal or "").strip()
    wf = (workflow_name or "").strip()
    ca = (changed_areas_bulk or "").strip()
    kd = (known_dependencies_bulk or "").strip()
    blob = _norm_blob(sc, bg, wf, ca, kd)

    classification = detect_scenario_type(
        scenario_context=sc,
        business_goal=bg,
        workflow_name=wf,
        changed_areas_bulk=ca,
        known_dependencies_bulk=kd,
    )

    entities = _infer_entities(blob)
    fields = _infer_fields(blob)
    fields = _filter_fields_for_classification(fields, blob, classification)
    validation_rules = _infer_validation_rules(blob, fields, classification=classification)
    expected_system_behavior = _infer_expected_behavior(blob, classification=classification)
    risks = _infer_risks(blob, fields, classification=classification)
    success = _infer_success(blob, classification=classification)
    primary = _primary_entity(entities, sc or bg)
    ui_hint = _ui_surface_hint(blob, wf, classification=classification)
    action_event_lines = _infer_action_event_lines(blob, classification)
    naming = infer_domain_naming(blob)
    blob_l = blob.lower()
    palabel = extract_primary_action_label(blob)
    if not palabel and wf:
        palabel = extract_primary_action_label(_norm_blob(blob, wf))
    panel_phrase = naming.panel_zone or (
        "draft response panel"
        if "response" in blob_l or "reply" in blob_l
        else ("notes draft panel" if "notes" in blob_l and "panel" in blob_l else "")
    )
    summary = _build_summary(
        scenario_context=sc,
        business_goal=bg,
        workflow_name=wf,
        changed_areas_bulk=ca,
        known_dependencies_bulk=kd,
        entities=entities,
        fields=fields,
        validation_rules=validation_rules,
        expected_system_behavior=expected_system_behavior,
        risks_edge_cases=risks,
        success_conditions=success,
        primary_entity=primary,
        ui_surface_hint=ui_hint,
        scenario_classification=classification,
        action_event_lines=action_event_lines,
    )

    return ExpandedGenerationContext(
        entities=entities,
        fields_involved=fields,
        validation_rules=validation_rules,
        expected_system_behavior=expected_system_behavior,
        risks_edge_cases=risks,
        success_conditions=success,
        primary_entity=primary,
        ui_surface_hint=ui_hint,
        summary_for_prompt=summary,
        scenario_classification=dict(classification),
        action_event_lines=action_event_lines,
        primary_action_label=palabel,
        artifact_label_singular=naming.artifact_singular,
        domain_record_label=naming.record_singular,
        panel_location_phrase=panel_phrase,
    )


def expanded_context_from_builder_session(sess: Mapping[str, Any]) -> ExpandedGenerationContext:
    """Convenience: same inputs the guided builder keeps in ``st.session_state``."""
    return expand_scenario_context(
        scenario_context=str(sess.get("sb_scenario_context") or ""),
        business_goal=str(sess.get("sb_business_goal") or ""),
        workflow_name=str(sess.get("sb_workflow_name") or ""),
        changed_areas_bulk=str(sess.get("sb_changed_areas_bulk") or ""),
        known_dependencies_bulk=str(sess.get("sb_known_dependencies_bulk") or ""),
    )


def expand_scenario_context_from_data(data: Mapping[str, Any] | None) -> ExpandedGenerationContext:
    """Build expansion from a normalized scenario dict (e.g. after load)."""
    if not isinstance(data, dict):
        return expand_scenario_context()
    sc = str(data.get("scenario_context") or "").strip()
    if not sc:
        sc = str(data.get("story_description") or "").strip()
    bg = str(data.get("business_goal") or "").strip()
    wf = str(data.get("workflow_name") or "").strip()
    ca_lines: list[str] = []
    for row in data.get("changed_areas") or []:
        if not isinstance(row, dict):
            continue
        a = str(row.get("area") or "").strip()
        t = str(row.get("type") or "").strip()
        if a and t:
            ca_lines.append(f"{a}: {t}")
        elif a:
            ca_lines.append(a)
    ca_bulk = "\n".join(ca_lines)
    deps = data.get("known_dependencies") or []
    kd_lines = "\n".join(str(x) for x in deps if x is not None and str(x).strip()) if isinstance(deps, list) else ""
    return expand_scenario_context(
        scenario_context=sc,
        business_goal=bg,
        workflow_name=wf,
        changed_areas_bulk=ca_bulk,
        known_dependencies_bulk=kd_lines,
    )

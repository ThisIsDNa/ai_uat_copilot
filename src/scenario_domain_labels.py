"""
Domain-aware labels for generation: primary UI action and artifact/record nouns.

Heuristic only — populated on ``ExpandedGenerationContext`` during expansion and reused
by titles, steps, AC hints, and light suggested-fix enrichment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


def _norm_ws(s: str) -> str:
    return " ".join(str(s).split()).strip()


def extract_primary_action_label(blob: str) -> str:
    """
    Best short label for the main user-triggered control (button, command, menu).

    Avoids generic phrases like "primary workflow action" or "described system workflow".
    """
    b = blob or ""
    # Markdown-bold UI labels: **Generate Notes**, **Approve Request**
    for m in re.finditer(r"\*\*([^*]{2,72})\*\*", b):
        inner = m.group(1).strip()
        if re.match(
            r"(?i)^(generate|run|create|submit|publish|approve|reject|upload|download|export|retry|invoke|launch|save|send)\b",
            inner,
        ):
            return inner
    # Quoted CTA
    mq = re.search(
        r"(?i)['\"](Generate\s+\w[^'\"]{1,40}|Run\s+AI[^'\"]{1,40}|Submit\s+\w[^'\"]{1,30}|Publish\s+\w[^'\"]{1,30})['\"]",
        b,
    )
    if mq:
        return mq.group(1).strip()
    # Common product verbs + object (title case not required)
    ordered = (
        r"(?i)\b(generate\s+notes|generate\s+reply|generate\s+summary|regenerate\s+\w+|run\s+ai\s+\w+)\b",
        r"(?i)\b(create\s+invoice\s+draft|start\s+export\s+job|submit\s+for\s+review|approve\s+request|publish\s+draft)\b",
        r"(?i)\b(upload\s+file|retry\s+sync|launch\s+\w+)\b",
    )
    for pat in ordered:
        m2 = re.search(pat, b)
        if m2:
            return m2.group(0).strip().title() if m2.group(0).islower() else m2.group(0).strip()
    # Click / press patterns
    mc = re.search(r"(?i)\b(?:click|press|tap)\s+([A-Z][\w\s]{2,40}?)(?:\s+button|\s+control)?\b", b)
    if mc:
        cand = mc.group(1).strip()
        if len(cand) <= 36 and not re.search(r"(?i)^(the|a|an)\s", cand):
            return cand
    return ""


@dataclass
class DomainNaming:
    """Singular, tester-facing nouns — avoid *artifact* / *record* when we can."""

    artifact_singular: str = ""  # e.g. "notes draft", "reply draft"
    record_singular: str = ""  # e.g. "meeting", "conversation"
    panel_zone: str = ""  # e.g. "notes draft panel"


def infer_domain_naming(blob: str) -> DomainNaming:
    low = (blob or "").lower()
    artifact = ""
    if re.search(r"(?i)\b(generate\s+notes|meeting\s+notes|ai\s+notes)\b", low):
        artifact = "notes draft"
    elif "notes draft" in low or ("generate notes" in low and "draft" in low):
        artifact = "notes draft"
    elif "reply draft" in low or ("generate reply" in low and "draft" in low):
        artifact = "reply draft"
    elif "generated notes" in low:
        artifact = "generated notes"
    elif "support reply" in low or ("reply" in low and "draft" in low):
        artifact = "reply draft"
    elif re.search(r"(?i)\bmeeting\s+notes\b", low) and "draft" in low:
        artifact = "notes draft"
    elif "draft" in low and "note" in low:
        artifact = "notes draft"
    elif "draft" in low:
        artifact = "draft"

    record = ""
    if re.search(r"(?i)\bmeeting\b", low):
        record = "meeting"
    elif "conversation" in low:
        record = "conversation"
    elif re.search(r"(?i)\b(request|ticket)\b", low):
        record = "request"
    elif "enrollment" in low or "registration" in low:
        record = "enrollment"
    elif "patient" in low or "profile" in low:
        record = "profile"

    panel = ""
    if artifact == "notes draft":
        panel = "notes draft panel" if "panel" in low else "notes editor or draft area"
    elif artifact == "reply draft" or ("reply" in low and "draft" in low):
        panel = "draft response panel" if "panel" in low or "response" in low else "draft reply area"
    elif "panel" in low:
        panel = "the panel named in scenario context"
    else:
        panel = ""

    return DomainNaming(artifact_singular=artifact, record_singular=record, panel_zone=panel)


def polish_positive_title_rhs(right: str, expanded: Any | None) -> str:
    """Swap generic action/event title fragments for domain labels when available."""
    if expanded is None:
        return (right or "").strip()
    try:
        from src.scenario_type_detection import primary_scenario_type

        if primary_scenario_type(expanded) != "action_event_flow":
            return (right or "").strip()
    except Exception:  # noqa: BLE001
        return (right or "").strip()
    r = (right or "").strip()
    pal = (getattr(expanded, "primary_action_label", "") or "").strip()
    art = (getattr(expanded, "artifact_label_singular", "") or "").strip()
    al = title_case_words(art) if art else ""
    if pal and re.search(r"(?i)primary\s+action\s*-\s*generate\s+draft", r):
        repl = pal if pal.lower().endswith("draft") else f"{pal} Draft"
        r = re.sub(r"(?i)primary\s+action\s*-\s*generate\s+draft", repl, r)
    if "Generated Draft Appears" in r and al:
        r = f"{al} Appears After Generation"
    elif "Generation Result Visible" in r and al:
        r = f"{al} Visible In Panel"
    elif "Draft Not Auto-Sent" in r and al:
        r = f"{al} Remains Draft Not Auto-Sent"
    elif "Draft Editable Before Send" in r and al:
        r = f"{al} Editable Before Send"
    elif "Generated Draft Persists" in r and al:
        r = f"{al} Persists After Refresh"
    elif "Authorized Role Generation" in r and pal:
        r = f"Authorized — {pal}"
    return r


def title_case_words(phrase: str) -> str:
    p = (phrase or "").strip()
    if not p:
        return ""
    parts = []
    for w in p.split():
        if w.isupper() or len(w) <= 2:
            parts.append(w)
        else:
            parts.append(w[:1].upper() + w[1:].lower() if w else w)
    return " ".join(parts)


def apply_domain_hints_to_positive_slots(
    plan: dict[int, dict[str, Any]],
    expanded: Any | None,
    scenario_context: str,
) -> None:
    """Mutate action/event coverage ``intent_hint`` strings toward concrete action/artifact names."""
    if not plan or expanded is None:
        return
    from src.scenario_type_detection import primary_scenario_type

    if primary_scenario_type(expanded) != "action_event_flow":
        return
    pal = (getattr(expanded, "primary_action_label", "") or "").strip() or extract_primary_action_label(
        _norm_ws(scenario_context + " " + getattr(expanded, "summary_for_prompt", ""))
    )
    dn = infer_domain_naming(_norm_ws(scenario_context + " " + getattr(expanded, "summary_for_prompt", "")))
    if not getattr(expanded, "artifact_label_singular", ""):
        art = dn.artifact_singular
    else:
        art = str(getattr(expanded, "artifact_label_singular") or "").strip() or dn.artifact_singular
    al = title_case_words(art) if art else "Draft"
    rec = (getattr(expanded, "domain_record_label", "") or "").strip() or dn.record_singular
    rec_t = title_case_words(rec) if rec else ""

    for slot in plan.values():
        if not isinstance(slot, dict):
            continue
        scope = str(slot.get("target_scope") or "").strip().lower()
        vf = str(slot.get("verification_focus") or "").strip().lower()
        if scope == "generate_action" and vf == "action_trigger_success":
            if pal:
                hint = pal if pal.lower().endswith("draft") else f"{pal} Draft"
                slot["intent_hint"] = hint
        elif scope == "generated_draft" and vf == "artifact_created":
            slot["intent_hint"] = f"{al} Appears After Generation" if al else slot.get("intent_hint")
        elif scope == "ui_consistency" and vf == "confirmation_or_visible_result":
            slot["intent_hint"] = f"{al} Visible In Panel" if al else "Generation Result Visible In UI"
        elif scope == "draft_state" and vf == "remains_draft":
            slot["intent_hint"] = f"{al} Remains Draft Not Auto-Sent" if al else slot.get("intent_hint")
        elif scope == "draft_editability" and vf == "editable_before_send":
            slot["intent_hint"] = f"{al} Editable Before Send" if al else slot.get("intent_hint")
        elif scope == "action_persistence" and vf == "persists_after_refresh":
            slot["intent_hint"] = f"{al} Persists After Refresh" if al else slot.get("intent_hint")
        elif scope == "authorized_generation" and vf == "workflow_outcome":
            slot["intent_hint"] = f"Authorized User — {pal}" if pal else slot.get("intent_hint")
        elif scope == "auto_send_prevention" and vf == "no_auto_send":
            slot["intent_hint"] = f"{al} Not Auto-Published" if "publish" in (scenario_context or "").lower() else (
                f"{al} Not Auto-Sent" if al else slot.get("intent_hint")
            )
        # Light touch on generic persistence hint from AC nudges
        if "persist" in str(slot.get("intent_hint") or "").lower() and art:
            ih = str(slot.get("intent_hint") or "")
            if "Generated Draft" in ih:
                slot["intent_hint"] = ih.replace("Generated Draft", al)


def filter_cross_scenario_rule_noise(
    rules: list[str],
    *,
    blob: str,
    primary_type: str,
) -> list[str]:
    """Drop toggle/cross-field boilerplate from validation rules when not supported by the text."""
    if primary_type != "action_event_flow":
        return rules
    low = (blob or "").lower()
    toggle_story = bool(
        re.search(r"(?i)\b(notification|preference|sms|email)\b.*\b(toggle|channel|on/off)\b", low)
        or re.search(r"(?i)\b(toggle|switch)\b.*\b(notification|preference)\b", low)
    )
    cross_story = bool(
        re.search(r"(?i)\bcross[- ]field|forbidden combination|at least one\s+(method|channel)|all\s+channels\s+off\b", low)
    )
    out: list[str] = []
    for r in rules:
        rl = r.lower()
        if not toggle_story and ("notification channel" in rl or "every notification channel" in rl):
            continue
        if not cross_story and ("cross-field" in rl or "forbidden combination" in rl or "at least one method" in rl):
            continue
        out.append(r)
    return out


def enrich_suggested_fix_lines(lines: list[str], data: Mapping[str, Any] | None) -> list[str]:
    """Replace a few generic suggested-fix phrases with domain labels (action_event only)."""
    if not lines or not isinstance(data, dict):
        return list(lines)
    try:
        from src.scenario_context_expansion import expand_scenario_context_from_data
        from src.scenario_type_detection import primary_scenario_type

        exp = expand_scenario_context_from_data(data)
    except Exception:  # noqa: BLE001
        return list(lines)
    if primary_scenario_type(exp) != "action_event_flow":
        return list(lines)
    blob = _norm_ws(
        " ".join(
            [
                str(data.get("scenario_context") or data.get("story_description") or ""),
                str(data.get("workflow_name") or ""),
            ]
        )
    )
    pal = (getattr(exp, "primary_action_label", "") or "").strip() or extract_primary_action_label(blob)
    dn = infer_domain_naming(blob)
    art = (getattr(exp, "artifact_label_singular", "") or "").strip() or dn.artifact_singular or "draft"
    act = pal or "the primary action"
    out: list[str] = []
    for line in lines:
        t = (line or "").strip()
        if not t:
            continue
        low = t.lower()
        if "disabled controls" in low or "action blocking" in low:
            t = (
                f"Verify **{act}** is disabled or blocked where required, and that **no {art}** is created when preconditions fail."
            )
        elif "absence of draft" in low or "no draft" in low:
            t = f"Add checks that **{act}** shows a clear error when the service fails and **no {art}** is inserted."
        elif "precondition" in low and "draft" in low:
            t = (
                f"Include coverage that **{act}** is blocked when preconditions fail and **no {art}** appears."
            )
        out.append(t)
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in out:
        t = (raw or "").strip()
        if not t:
            continue
        k = re.sub(r"\s+", " ", t.lower())
        if k in seen:
            continue
        seen.add(k)
        deduped.append(t)
    return deduped

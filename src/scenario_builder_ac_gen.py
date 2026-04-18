"""
Heuristic acceptance-criteria suggestions for the guided Scenario Builder (C3).

Uses business goal and changed-areas bulk text only — no scenario mutation here.
Optional OpenAI enhancement can be added later; template output stays the fallback.
"""

from __future__ import annotations

import re

from src.scenario_builder_core import parse_bullet_line_items, parse_changed_areas_bulk


def _one_sentence_goal(goal: str, *, max_len: int = 160) -> str:
    g = " ".join((goal or "").split()).strip()
    if not g:
        return ""
    if len(g) > max_len:
        return g[: max_len - 1].rstrip() + "…"
    return g


def _changed_area_labels(changed_areas_bulk: str | None) -> list[str]:
    rows = parse_changed_areas_bulk(changed_areas_bulk or "")
    labels: list[str] = []
    for row in rows:
        a = str(row.get("area") or "").strip()
        t = str(row.get("type") or "").strip()
        if a and t:
            labels.append(f"{a} ({t})")
        elif a:
            labels.append(a)
    if labels:
        return labels
    return parse_bullet_line_items(changed_areas_bulk or "")


def clean_ac_suggestion_lines(lines: list[str] | None, *, cap: int = 8) -> list[str]:
    """Trim, drop empties, dedupe (case-insensitive), cap length — safe before UI bind."""
    items = [str(x).strip() for x in (lines or []) if str(x).strip()]
    return _dedupe_preserve(items)[:cap]


def _dedupe_preserve(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        t = (raw or "").strip()
        if not t:
            continue
        key = re.sub(r"\s+", " ", t).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _ac_from_validation_rule(rule: str) -> str:
    """Turn expansion validation snippets into concise **System …** AC lines."""
    t = rule.strip().rstrip(".")
    if not t:
        return ""
    low = t.lower()
    if low.startswith("invalid ") or "rejected" in low or "blocks" in low:
        return t if t[0].isupper() else t[0].upper() + t[1:]
    if low.startswith("required ") or "cannot be left" in low:
        return t if t[0].isupper() else t[0].upper() + t[1:]
    return f"System enforces: {t[0].lower() + t[1:]}" if len(t) > 1 else f"System enforces: {t}"


def generate_acceptance_criteria_suggestions(
    *,
    business_goal: str | None,
    changed_areas_bulk: str | None,
    expanded: object | None = None,
) -> list[str]:
    """
    Return 3–8 testable acceptance criteria grounded in goal, changed areas, and expansion.

    Phrasing favors **observable system behavior** (save, validation, persistence, messages)
    rather than meta lines like "User can verify…".
    """
    goal = (business_goal or "").strip()
    areas = _changed_area_labels(changed_areas_bulk or "")
    g_short = _one_sentence_goal(goal, max_len=140)
    exp = expanded

    out: list[str] = []
    pt = ""
    rh: dict = {}
    if exp is not None:
        c = getattr(exp, "scenario_classification", None) or {}
        if isinstance(c, dict):
            pt = str(c.get("primary_type") or "")
            rh = c.get("routing_hints") or {}

    val_rules = list(getattr(exp, "validation_rules", None) or []) if exp else []
    if val_rules:
        for rule in val_rules[:4]:
            line = _ac_from_validation_rule(rule)
            if line:
                out.append(line)

    fields = list(getattr(exp, "fields_involved", None) or []) if exp else []
    if fields and rh.get("prefer_input_format_validation", True) and pt not in ("state_toggle", "action_event_flow"):
        joined = ", ".join(fields[:5])
        out.append(
            f"System validates {joined} at field level and blocks save until required rules pass."
        )

    behaviors = list(getattr(exp, "expected_system_behavior", None) or []) if exp else []
    if behaviors:
        for beh in behaviors[:3]:
            b = beh.strip().rstrip(".")
            if not b:
                continue
            bl = b.lower()
            if pt == "action_event_flow" and (
                bl.startswith("successful save")
                or "refreshes or re-queries visible data" in bl
                or "successful update" in bl
            ):
                continue
            if bl.startswith("successful save") or bl.startswith("after a successful"):
                out.append(b if b[0].isupper() else b[0].upper() + b[1:])
            elif "confirmation" in bl or "notice" in bl:
                out.append(
                    b if b[0].isupper() else b[0].upper() + b[1:]
                )
            else:
                out.append(f"System behavior: {b[0].lower() + b[1:]}" if len(b) > 1 else f"System behavior: {b}")

    if g_short:
        out.append(
            f"System supports the business outcome: {g_short} — UI and persisted data stay consistent after save or refresh."
        )

    if pt != "action_event_flow":
        for label in areas[:5]:
            safe = label.replace("\n", " ").strip()
            if not safe:
                continue
            out.append(
                f"Regression check for **{safe}**: validation, save, and display behave as before for touched flows."
            )

    success = list(getattr(exp, "success_conditions", None) or []) if exp else []
    if success:
        for sc in success[:2]:
            s = sc.strip().rstrip(".")
            if not s:
                continue
            if s.lower().startswith("system "):
                out.append(s)
            else:
                out.append(f"With valid complete inputs, {s[0].lower() + s[1:]}")

    if not out:
        out.extend(
            [
                "System completes the primary workflow without unexpected errors.",
                "System surfaces clear confirmation or field-level errors for invalid actions in this flow.",
                "System allows the user to correct mistakes using documented controls (cancel, edit, or back paths).",
            ]
        )

    if pt == "state_toggle":
        seed = [
            "System allows enabling email notifications and saving the updated preference.",
            "System allows disabling SMS notifications while at least one notification method remains enabled.",
            "System blocks saving when all notification methods are disabled and shows a clear error referencing the rule.",
            "Updated notification preferences persist after save and page reload.",
        ]
        out = _dedupe_preserve(seed + out)

    if pt == "action_event_flow":
        seed = [
            "Authorized users can trigger the primary workflow action and receive the expected draft or generated artifact in the UI.",
            "Generated content is inserted as a **Draft** (or equivalent) and is **not** auto-sent or auto-submitted.",
            "Users can review and edit generated draft content before an explicit send or submit step.",
            "The primary action is blocked when preconditions fail (e.g. closed conversation) with a clear message and **no** new draft.",
            "Users without required permissions cannot run the primary action; controls are disabled or a permission error is shown.",
            "When the downstream service fails, the system shows an error and does **not** insert a partial or phantom draft.",
            "Successful generations persist and remain visible after refresh or reopen, consistent with server state.",
        ]
        out = _dedupe_preserve(seed + out)

    from src.scenario_type_gating import filter_ac_suggestions_under_gating

    out = filter_ac_suggestions_under_gating(out, exp)

    return clean_ac_suggestion_lines(out, cap=8)

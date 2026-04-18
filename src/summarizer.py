import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from src.placeholder_outputs import get_placeholder_reviewer_focus
from src.scenario_media import step_texts

load_dotenv()

_REVIEWER_FOCUS_KEYS = ("pay_attention_to", "risky", "may_be_missing")
_MAX_FOCUS_ITEMS_PER_SECTION = 2
_MAX_FOCUS_ITEM_CHARS = 160


def _coerce_str_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        t = raw.strip()
        return [t] if t else []
    if isinstance(raw, list):
        out: list[str] = []
        for x in raw:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    return []


def _parse_json_object(content: str | None) -> dict | None:
    if content is None or not str(content).strip():
        return None
    text = str(content).strip().lstrip("\ufeff")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_reviewer_focus_payload(parsed: dict) -> dict[str, list[str]] | None:
    inner = parsed.get("reviewer_focus")
    if isinstance(inner, dict):
        src = inner
    else:
        src = parsed

    out: dict[str, list[str]] = {}
    for key in _REVIEWER_FOCUS_KEYS:
        out[key] = _coerce_str_list(src.get(key))

    if not any(out.values()):
        return None
    return out


def _tighten_focus_lists(d: dict[str, list[str]]) -> dict[str, list[str]]:
    """Cap count and length so UI stays scannable; collapse whitespace."""
    out: dict[str, list[str]] = {}
    for key in _REVIEWER_FOCUS_KEYS:
        items: list[str] = []
        for raw in d.get(key, []):
            s = " ".join(str(raw).split()).strip()
            if not s:
                continue
            if len(s) > _MAX_FOCUS_ITEM_CHARS:
                s = s[: _MAX_FOCUS_ITEM_CHARS - 1].rstrip() + "…"
            items.append(s)
            if len(items) >= _MAX_FOCUS_ITEMS_PER_SECTION:
                break
        out[key] = items
    return out


def _build_scenario_context_for_prompt(data: dict) -> str:
    lines: list[str] = []

    if data.get("business_goal"):
        lines.append(f"Business goal: {data['business_goal']}")

    if data.get("workflow_name"):
        lines.append(f"Workflow: {data['workflow_name']}")

    if data.get("story_title"):
        lines.append(f"Story title: {data['story_title']}")

    narrative = str(data.get("scenario_context") or "").strip() or str(data.get("story_description") or "").strip()
    if narrative:
        lines.append(f"Scenario context: {narrative}")

    changed = data.get("changed_areas") or []
    if isinstance(changed, list) and changed:
        parts = []
        for a in changed:
            if not isinstance(a, dict):
                continue
            area = a.get("area", "")
            typ = a.get("type", "")
            if area:
                parts.append(f"{area} ({typ})" if typ else str(area))
        if parts:
            lines.append("Changed areas: " + "; ".join(parts))

    deps = data.get("known_dependencies") or []
    if isinstance(deps, list) and deps:
        lines.append("Known dependencies: " + "; ".join(str(d) for d in deps if d))

    if data.get("notes"):
        lines.append(f"Scenario notes: {data['notes']}")

    ac_list = data.get("acceptance_criteria") or []
    if isinstance(ac_list, list) and ac_list:
        lines.append("Acceptance criteria:")
        for ac in ac_list:
            if not isinstance(ac, dict):
                continue
            aid = ac.get("id", "?")
            atext = ac.get("text", "")
            tids = ac.get("test_case_ids") or []
            tid_s = ", ".join(str(x) for x in tids) if tids else "(none linked)"
            lines.append(f"  - {aid}: {atext} [tests: {tid_s}]")

    test_cases = data.get("test_cases") or []
    if isinstance(test_cases, list) and test_cases:
        lines.append("Test cases:")
        for tc in test_cases:
            if not isinstance(tc, dict):
                continue
            tid = tc.get("id", "?")
            ttext = tc.get("text", "")
            lines.append(f"  - {tid}: {ttext}")
            for i, st in enumerate(step_texts(tc), start=1):
                lines.append(f"      Step {i}: {st}")

    return "\n".join(lines) if lines else "(No structured scenario fields provided.)"


def generate_reviewer_focus(data: dict) -> dict[str, list[str]]:
    """
    Scenario-specific reviewer guidance via OpenAI when configured; otherwise
    rule-based placeholder. Same shape for app.py: pay_attention_to, risky,
    may_be_missing (lists of strings).
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return get_placeholder_reviewer_focus(data)

    context = _build_scenario_context_for_prompt(data)

    prompt = f"""You write sharp UAT review notes for the scenario below. A reviewer will skim them during execution.

--- Scenario ---
{context}
---

Return one JSON object: {{"reviewer_focus":{{"pay_attention_to":[],"risky":[],"may_be_missing":[]}}}}

Each array has exactly 1 or 2 strings (prefer 2 only if two distinct high-signal points exist). Every string must be ONE short sentence (under ~25 words), no lists inside the string, no paragraph breaks.

Grounding (mandatory):
- Most items should name something from the scenario: a changed area, dependency, test id (e.g. TC-02), screen/field implied by steps, or validation theme (format, blank, error text). Vague items with no anchor are wrong.

pay_attention_to:
- Concrete checks to run (what to watch in this workflow), tied to steps or business goal — not generic "verify quality".

risky:
- Realistic failure modes for THIS change: validation gaps, unclear/wrong UI feedback, timing of messages, shared logic regressions, auth/session edge cases, or dependencies listed — only if plausible from the data.

may_be_missing:
- Specific plausible holes vs what is written (e.g. step omits negative path that criteria imply, no explicit check for a message type, screenshot vs step mismatch risk). Not "do more testing" or "consider edge cases" without naming what.

Banned (do not write anything like these):
- "Ensure/verify the feature works", "confirm requirements", "test thoroughly", "general edge cases", "align with business objectives" without naming the objective, boilerplate about "stakeholders" or "documentation".

Do not quote acceptance criteria verbatim; infer concrete implications.

Output JSON only — no markdown.

Required shape:
{{"reviewer_focus":{{"pay_attention_to":[],"risky":[],"may_be_missing":[]}}}}
"""

    client = OpenAI(api_key=api_key)
    create_kwargs = dict(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You output only valid JSON. No markdown. "
                    "Reviewer notes must be concrete and scenario-grounded; reject generic QA filler."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.15,
    )

    try:
        try:
            response = client.chat.completions.create(
                **create_kwargs,
                response_format={"type": "json_object"},
            )
        except Exception:
            response = client.chat.completions.create(**create_kwargs)
    except Exception:
        return get_placeholder_reviewer_focus(data)

    try:
        content = response.choices[0].message.content
    except Exception:
        return get_placeholder_reviewer_focus(data)

    parsed = _parse_json_object(content)
    if not parsed:
        return get_placeholder_reviewer_focus(data)

    normalized = _normalize_reviewer_focus_payload(parsed)
    if not normalized:
        return get_placeholder_reviewer_focus(data)

    tightened = _tighten_focus_lists(normalized)
    if not any(tightened.values()):
        return get_placeholder_reviewer_focus(data)

    return tightened

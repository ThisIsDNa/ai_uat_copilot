import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from src.placeholder_outputs import get_placeholder_traceability

load_dotenv()

_COVERAGE_STATUSES = frozenset({"Covered", "Partial", "Missing"})


def _parse_model_json_list(content: str | None) -> list[dict]:
    """Parse a JSON array of objects; tolerates markdown fences and wrapper text."""
    if content is None or not str(content).strip():
        raise ValueError("Empty API response content")

    text = str(content).strip().lstrip("\ufeff")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, list):
        raise TypeError(f"Expected a JSON array, got {type(parsed).__name__}")
    return parsed


def _parse_traceability_payload(content: str | None) -> list[dict] | None:
    """
    Parse traceability API output: prefers wrapped object {"traceability": [...]},
    falls back to a raw array or a single row object.
    Returns None if nothing usable.
    """
    if content is None or not str(content).strip():
        return None

    text = str(content).strip().lstrip("\ufeff")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            return _parse_model_json_list(content)
        except Exception:
            return None

    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]

    if isinstance(parsed, dict):
        for key in ("traceability", "rows", "matrix", "items"):
            block = parsed.get(key)
            if isinstance(block, list):
                return [x for x in block if isinstance(x, dict)]
        if "acceptance_criteria_id" in parsed:
            return [parsed]

    return None


def _normalize_coverage_status(raw: object) -> str:
    s = str(raw or "").strip()
    if s in _COVERAGE_STATUSES:
        return s
    low = s.lower()
    if low in ("covered", "complete", "full", "yes"):
        return "Covered"
    if low in ("missing", "none", "gap", "no coverage"):
        return "Missing"
    if low in ("partial", "incomplete", "some", "limited", "pending"):
        return "Partial"
    return "Partial"


def _coerce_matching_test_cases(raw: object, valid_tc_ids: set[str]) -> tuple[list[str], list[str]]:
    """Return (known_ids, unknown_ids)."""
    if raw is None:
        items: list[str] = []
    elif isinstance(raw, str):
        items = [raw.strip()] if raw.strip() else []
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if x is not None and str(x).strip()]
    else:
        items = []

    known: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        if x in valid_tc_ids:
            known.append(x)
        else:
            unknown.append(x)
    return known, unknown


def _finalize_coverage_status(
    normalized_model_status: str,
    matches: list[str],
    json_linked: list[str],
) -> str:
    """Reconcile model label with actual matches and scenario links."""
    if not matches:
        return "Missing"
    if normalized_model_status == "Missing":
        return "Partial"
    if normalized_model_status == "Covered":
        return "Covered"
    if normalized_model_status == "Partial":
        jl = [x for x in json_linked if x]
        if jl and set(matches) >= set(jl):
            return "Covered"
        return "Partial"
    return "Partial"


def _merge_traceability_with_source(
    model_rows: list[dict],
    acceptance_criteria: list,
    test_cases: list,
) -> list[dict]:
    """One row per AC, all required fields, validated test ids and coverage status."""
    valid_tc_ids = {
        str(tc.get("id"))
        for tc in test_cases
        if tc.get("id") is not None and str(tc.get("id")).strip()
    }

    by_id: dict[str, dict] = {}
    by_id_lower: dict[str, str] = {}
    for row in model_rows:
        rid = row.get("acceptance_criteria_id")
        if rid is None:
            continue
        key = str(rid).strip()
        if key and key not in by_id:
            by_id[key] = row
            by_id_lower[key.lower()] = key

    out: list[dict] = []
    for ac in acceptance_criteria:
        aid = str(ac.get("id", "N/A")).strip() or "N/A"
        atext = str(ac.get("text", "") or "")
        json_linked = [
            str(x).strip()
            for x in (ac.get("test_case_ids") or [])
            if x is not None and str(x).strip()
        ]
        json_linked_valid = [x for x in json_linked if x in valid_tc_ids]

        row = by_id.get(aid)
        if row is None:
            canon = by_id_lower.get(aid.lower())
            if canon is not None:
                row = by_id.get(canon)
        model_notes = str((row or {}).get("notes") or "").strip()
        model_text = str((row or {}).get("acceptance_criteria_text") or "").strip()
        display_text = model_text or atext

        if row:
            matches, unknown = _coerce_matching_test_cases(
                row.get("matching_test_cases"), valid_tc_ids
            )
            status = _normalize_coverage_status(row.get("coverage_status"))
        else:
            matches, unknown = [], []
            status = "Partial"
            if not model_notes:
                model_notes = "No AI row for this criterion; filled from scenario JSON."

        notes_parts: list[str] = []
        if unknown:
            notes_parts.append(f"Omitted unknown test id(s): {', '.join(unknown)}.")

        restored_from_json = False
        if not matches and json_linked_valid:
            matches = list(json_linked_valid)
            restored_from_json = True

        if restored_from_json and row is not None:
            notes_parts.append(
                "Using scenario test_case_ids (model matches were empty or invalid)."
            )
        elif not matches and json_linked and not json_linked_valid:
            notes_parts.append(
                f"Scenario links are not valid test ids: {', '.join(json_linked)}."
            )

        if model_notes:
            notes_parts.insert(0, model_notes)

        status = _finalize_coverage_status(status, matches, json_linked_valid)

        out.append(
            {
                "acceptance_criteria_id": aid,
                "acceptance_criteria_text": display_text,
                "matching_test_cases": matches,
                "coverage_status": status,
                "notes": " ".join(notes_parts).strip() or "—",
            }
        )

    return out


def generate_traceability_matrix(data: dict) -> list[dict]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    acceptance_criteria = data.get("acceptance_criteria") or []
    if not isinstance(acceptance_criteria, list):
        acceptance_criteria = []
    test_cases = data.get("test_cases") or []
    if not isinstance(test_cases, list):
        test_cases = []

    if not api_key:
        return get_placeholder_traceability(data)

    if not acceptance_criteria:
        return []

    ac_lines: list[str] = []
    for ac in acceptance_criteria:
        aid = ac.get("id", "N/A")
        atext = ac.get("text", "")
        linked = ac.get("test_case_ids") or []
        suffix = (
            f" (scenario JSON test_case_ids: {', '.join(str(x) for x in linked)})"
            if linked
            else " (no test_case_ids in JSON)"
        )
        ac_lines.append(f"- {aid}: {atext}{suffix}")

    valid_tc_id_set = {
        str(tc.get("id"))
        for tc in test_cases
        if tc.get("id") is not None and str(tc.get("id")).strip()
    }
    valid_ids = sorted(valid_tc_id_set)
    tc_lines = [
        f"- {tc.get('id', 'N/A')}: {tc.get('text', '')}" for tc in test_cases
    ]
    ac_block = "\n".join(ac_lines)
    tc_block = "\n".join(tc_lines) if tc_lines else "(none)"

    prompt = f"""You map acceptance criteria to test cases for a UAT traceability matrix.

Rules:
1. Output ONLY valid JSON: one object with a single key "traceability" whose value is an array.
2. No markdown, no code fences, no commentary before or after the JSON.
3. Include exactly one array element for EVERY acceptance criterion listed below, in the same order, using the exact acceptance_criteria_id given.
4. matching_test_cases must contain only ids from the allowed test case id list (subset). You may refine JSON links if evidence clearly supports different mapping; explain in notes.
5. coverage_status must be exactly one of: Covered | Partial | Missing
   - Missing: no test case adequately addresses this criterion.
   - Partial: some coverage but gaps, weak tests, or unclear mapping.
   - Covered: linked test case(s) clearly substantiate the criterion.
6. acceptance_criteria_text should echo the criterion wording (you may shorten slightly).
7. notes: one or two short sentences; cite mapping judgment or disagreements with JSON links.

Allowed test case ids (use only these in matching_test_cases):
{json.dumps(valid_ids)}

Acceptance criteria (in order — produce one row per line, same order):
{ac_block}

Test cases (titles for reference):
{tc_block}

Required JSON shape:
{{"traceability":[{{"acceptance_criteria_id":"…","acceptance_criteria_text":"…","matching_test_cases":[],"coverage_status":"Partial","notes":"…"}}]}}
"""

    client = OpenAI(api_key=api_key)
    create_kwargs = dict(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You respond with only valid JSON objects. Never wrap JSON in markdown.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
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
        return get_placeholder_traceability(data)

    try:
        content = response.choices[0].message.content
    except Exception:
        return get_placeholder_traceability(data)

    parsed_list = _parse_traceability_payload(content)
    if not parsed_list:
        return get_placeholder_traceability(data)

    try:
        merged = _merge_traceability_with_source(
            parsed_list, acceptance_criteria, test_cases
        )
    except Exception:
        return get_placeholder_traceability(data)

    return merged

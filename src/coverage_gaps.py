"""Rule-based coverage gap detection with optional OpenAI augmentation."""

import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from src.scenario_media import expected_step_screenshot_paths, step_texts
from src.traceability import _parse_model_json_list

load_dotenv()

_GAP_TYPES = frozenset(
    {
        "Missing Coverage",
        "Partial Coverage",
        "Weak Validation",
        "Inconsistency",
    }
)

_GAP_TYPE_ORDER: dict[str, int] = {
    "Missing Coverage": 0,
    "Partial Coverage": 1,
    "Weak Validation": 2,
    "Inconsistency": 3,
}

# AC wording that implies invalid/reject/error outcomes (tight — avoids generic "error" noise)
_NEGATIVE_INTENT_AC = re.compile(
    r"\b(invalid|rejects?\b|rejected|denied|\bdeny\b|unauthoriz\w*|"
    r"\bblank\b|\bmust not\b|\bshould not\b|forbidden|"
    r"wrong\s+(password|credential|input)s?|"
    r"empty\s+(field|value|input|phone))\b",
    re.IGNORECASE,
)
_ERROR_OUTCOME_AC = re.compile(
    r"\b(error\s+message|validation\s+message|failed\s+(login|save|auth|authentication))\b",
    re.IGNORECASE,
)

# Evidence that a test actually exercises negative / failure / invalid paths
_NEGATIVE_TEST_EVIDENCE = re.compile(
    r"\b(invalid|reject|rejects|rejected|denied|\bdeny\b|unauthoriz\w*|"
    r"\berrors?\b|\bwrong\b|\bblank\b|\bempty\b|false\s+positive|"
    r"\bfail(?:ed|ure)?\b|negative|must not|should not)\b",
    re.IGNORECASE,
)

_EDGE_INTENT_AC = re.compile(
    r"\b(edge\s+case|boundary|upper\s*limit|lower\s*limit|at\s+least|at\s+most|"
    r"max(imum)?|min(imum)?|concurrent|parallel|race\s+condition|timeout|offline|"
    r"slow\s+network|special\s+character|unicode)\b",
    re.IGNORECASE,
)
_EDGE_TEST_EVIDENCE = re.compile(
    r"\b(edge|boundary|limit|max(imum)?|min(imum)?|concurrent|timeout|offline|"
    r"stress|load|unicode|special\s+char)\b",
    re.IGNORECASE,
)


def _ac_implies_negative_or_error(ac_text: str) -> bool:
    return bool(
        _NEGATIVE_INTENT_AC.search(ac_text) or _ERROR_OUTCOME_AC.search(ac_text)
    )


def _ac_implies_edge_or_boundary(ac_text: str) -> bool:
    return bool(_EDGE_INTENT_AC.search(ac_text))


def _tc_blob(tc: dict) -> str:
    return f"{tc.get('text', '')} {' '.join(step_texts(tc))}"


def _suite_has_negative_test_evidence(test_cases: list) -> bool:
    for tc in test_cases:
        if _NEGATIVE_TEST_EVIDENCE.search(_tc_blob(tc).lower()):
            return True
    return False


_VERIFICATION_VERB = re.compile(
    r"\b(verify|confirm|check|ensure)\b",
    re.IGNORECASE,
)
_CONCRETE_OUTCOME = re.compile(
    r"\b(message|messages|label|toast|banner|modal|dialog|field|button|"
    r"redirect|displays?|shown|appears|visible|hidden|disabled|enabled|"
    r"status|updated|saved|confirmation|validation|authenticated|"
    r"dashboard|home\s*page|session|logged\s+in|"
    r"reject(?:s|ed)?|denied|deny|error|blank|invalid)\b",
    re.IGNORECASE,
)


def _step_assertion_vague(step: str) -> bool:
    """True when a step asks to verify/confirm but names no concrete outcome."""
    t = step.strip()
    if len(t) < 18:
        return False
    if " — Expected:" in t:
        return False
    if not _VERIFICATION_VERB.search(t):
        return False
    if _CONCRETE_OUTCOME.search(t):
        return False
    return len(t.split()) <= 14


def _gap_row(
    acceptance_criteria_id: str,
    gap_type: str,
    description: str,
    suggested_action: str,
) -> dict[str, str]:
    return {
        "acceptance_criteria_id": acceptance_criteria_id,
        "gap_type": gap_type,
        "description": description,
        "suggested_action": suggested_action,
    }


def _tc_lookup(test_cases: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tc in test_cases:
        tid = tc.get("id")
        if tid is not None and str(tid).strip():
            out[str(tid)] = tc
    return out


def _referenced_test_ids(acceptance_criteria: list) -> set[str]:
    ids: set[str] = set()
    for ac in acceptance_criteria:
        for x in ac.get("test_case_ids") or []:
            ids.add(str(x))
    return ids


def _serialize_test_cases_for_prompt(test_cases: list) -> str:
    lines: list[str] = []
    for tc in test_cases:
        tid = tc.get("id", "?")
        lines.append(f"{tid}: {tc.get('text', '')}")
        for i, s in enumerate(step_texts(tc), 1):
            lines.append(f"  Step {i}: {s}")
    return "\n".join(lines) if lines else "(none)"


def _heuristic_coverage_gaps(data: dict) -> list[dict]:
    """Deterministic gaps: clear Missing vs Partial, targeted negative and weak checks."""
    gaps: list[dict] = []
    ac_list = data.get("acceptance_criteria") or []
    if not isinstance(ac_list, list):
        return gaps

    test_cases = data.get("test_cases") or []
    if not isinstance(test_cases, list):
        test_cases = []

    tc_by_id = _tc_lookup(test_cases)
    referenced = _referenced_test_ids(ac_list)

    # With no acceptance criteria objects, tests are not "orphans" — mapping is undefined, not inconsistent.
    if ac_list:
        for tc in test_cases:
            tid = tc.get("id")
            if tid is None or str(tid).strip() == "":
                continue
            sid = str(tid)
            if sid not in referenced:
                gaps.append(
                    _gap_row(
                        "—",
                        "Inconsistency",
                        f"{sid} is not mapped to any acceptance criterion.",
                        "Link the test case to the correct acceptance criterion or remove the orphan test.",
                    )
                )

    acs_needing_negative = sum(
        1
        for ac in ac_list
        if _ac_implies_negative_or_error((ac.get("text") or "").strip())
    )
    suite_negative = _suite_has_negative_test_evidence(test_cases)
    scenario_missing_negative_suite = (
        acs_needing_negative >= 1 and bool(test_cases) and not suite_negative
    )
    if scenario_missing_negative_suite:
        gaps.append(
            _gap_row(
                "—",
                "Missing Coverage",
                "Criteria require invalid/reject/error coverage, but no test title or step clearly exercises those paths.",
                "Add tests (or steps) that name invalid input, rejection, or the expected error message.",
            )
        )

    for ac in ac_list:
        ac_id = str(ac.get("id", "unknown"))
        ac_text = (ac.get("text") or "").strip()
        linked = [str(x) for x in (ac.get("test_case_ids") or [])]

        if not linked:
            gaps.append(
                _gap_row(
                    ac_id,
                    "Missing Coverage",
                    "No test cases are explicitly linked to this criterion.",
                    "Link at least one test case in `test_case_ids`, or mark the criterion out of scope.",
                )
            )
            continue

        unknown = [x for x in linked if x not in tc_by_id]
        valid_linked = [tc_by_id[x] for x in linked if x in tc_by_id]

        if not valid_linked:
            gaps.append(
                _gap_row(
                    ac_id,
                    "Missing Coverage",
                    f"No resolvable tests (unknown id(s): {', '.join(unknown)}).",
                    "Fix ids or add the missing test definitions.",
                )
            )
            continue

        partial_notes: list[str] = []
        if unknown:
            partial_notes.append(f"Unknown id(s): {', '.join(unknown)}")

        step_lists = [(tc, step_texts(tc)) for tc in valid_linked]
        if all(len(st) == 0 for _, st in step_lists):
            partial_notes.append("Every linked test has empty steps.")
        else:
            empty_ids = [str(tc.get("id", "?")) for tc, st in step_lists if len(st) == 0]
            if empty_ids:
                partial_notes.append(f"No steps on: {', '.join(empty_ids)}")

        combined_lower = " ".join(_tc_blob(tc).lower() for tc in valid_linked)
        if (
            _ac_implies_negative_or_error(ac_text)
            and not _NEGATIVE_TEST_EVIDENCE.search(combined_lower)
            and not scenario_missing_negative_suite
        ):
            partial_notes.append(
                "Linked tests look like happy path only; this criterion needs invalid/reject/error checks."
            )

        if (
            _ac_implies_edge_or_boundary(ac_text)
            and valid_linked
            and not _EDGE_TEST_EVIDENCE.search(combined_lower)
        ):
            partial_notes.append(
                "Edge/boundary/limit wording in criterion; linked tests do not clearly exercise that."
            )

        if partial_notes:
            gaps.append(
                _gap_row(
                    ac_id,
                    "Partial Coverage",
                    " ".join(partial_notes),
                    "Repair ids, fill steps, or add/adjust tests so this criterion is actually exercised.",
                )
            )

        weak_notes: list[str] = []
        for tc, stp in step_lists:
            tid = str(tc.get("id", "?"))
            if not stp:
                continue
            if len(stp) == 1 and len(ac_text) > 55 and len(stp[0]) < 95:
                weak_notes.append(
                    f"{tid}: only one short step for a substantive criterion"
                )
            for i, line in enumerate(stp, start=1):
                if _step_assertion_vague(line):
                    weak_notes.append(
                        f"{tid} step {i}: no validation step confirms the expected outcome (vague verify/confirm)."
                    )
                    break
            paths = expected_step_screenshot_paths(tc)
            non_empty_shots = sum(1 for x in paths if (x or "").strip())
            if non_empty_shots == 0:
                weak_notes.append(
                    f"{tid}: {len(stp)} step(s), no expected_step_screenshots"
                )
            elif non_empty_shots < len(stp):
                weak_notes.append(
                    f"{tid}: {non_empty_shots} screenshot(s) for {len(stp)} step(s)"
                )

        if weak_notes:
            seen: set[str] = set()
            deduped = []
            for n in weak_notes:
                if n not in seen:
                    seen.add(n)
                    deduped.append(n)
            gaps.append(
                _gap_row(
                    ac_id,
                    "Weak Validation",
                    "; ".join(deduped[:4]) + ("…" if len(deduped) > 4 else ""),
                    "Tighten steps (what exactly to see), split checks, and align screenshots 1:1 with steps.",
                )
            )

    return gaps


def _canonical_gap_type(gap_type: str) -> str:
    s = (gap_type or "").strip()
    low = s.casefold().replace(" ", "")
    if "inconsint" in low or low == "inconsistency":
        return "Inconsistency"
    if s in _GAP_TYPES:
        return s
    if "missing" in low and "coverage" in low:
        return "Missing Coverage"
    if "partial" in low and "coverage" in low:
        return "Partial Coverage"
    if "weak" in low:
        return "Weak Validation"
    return "Weak Validation"


def _normalize_gap_dict(raw: dict) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    ac_id = raw.get("acceptance_criteria_id")
    gap_type = raw.get("gap_type")
    desc = raw.get("description")
    action = raw.get("suggested_action")
    if not all(
        isinstance(x, str) and x.strip()
        for x in (ac_id, gap_type, desc, action)
    ):
        return None
    gap_type = _canonical_gap_type(gap_type.strip())
    return _gap_row(ac_id.strip(), gap_type, desc.strip(), action.strip())


def _consolidate_gaps_by_ac_and_type(gaps: list[dict]) -> list[dict]:
    """Merge rows that share the same AC id and gap_type (e.g. heuristic + traceability)."""
    if not gaps:
        return []
    order: list[tuple[str, str]] = []
    bucket: dict[tuple[str, str], dict] = {}
    for g in gaps:
        if not isinstance(g, dict):
            continue
        ac_id = str(g.get("acceptance_criteria_id") or "—")
        gt = str(g.get("gap_type") or "").strip()
        if gt not in _GAP_TYPES:
            continue
        key = (ac_id, gt)
        if key not in bucket:
            bucket[key] = {
                "acceptance_criteria_id": ac_id,
                "gap_type": gt,
                "description": str(g.get("description") or "").strip(),
                "suggested_action": str(g.get("suggested_action") or "").strip(),
            }
            order.append(key)
        else:
            cur = bucket[key]
            d2 = str(g.get("description") or "").strip()
            if d2 and d2 not in cur["description"]:
                cur["description"] = (cur["description"] + " | " + d2).strip()[:450]
            a2 = str(g.get("suggested_action") or "").strip()
            if len(a2) > len(cur["suggested_action"]):
                cur["suggested_action"] = a2
    return [bucket[k] for k in order]


def _traceability_alignment_gaps(
    rows: list[dict] | None,
    skip_partial_pending_ac_ids: set[str],
) -> list[dict]:
    """
    Derive gaps from the same traceability matrix shown in Review Synthesis.
    Missing always surfaces; Partial/Pending is skipped when heuristics already
    flagged that criterion (reduces duplicate noise).
    """
    if not rows:
        return []
    gaps: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ac_id = str(row.get("acceptance_criteria_id") or "").strip() or "—"
        status_raw = str(row.get("coverage_status") or "").strip()
        if not status_raw:
            continue
        scf = status_raw.casefold()
        if scf == "covered":
            continue
        notes = str(row.get("notes") or "").strip()
        notes_short = (
            ""
            if notes in ("", "—")
            else (notes[:200] + ("…" if len(notes) > 200 else ""))
        )
        matches = row.get("matching_test_cases")
        if isinstance(matches, list):
            mtx = ", ".join(str(x) for x in matches if x is not None)[:120]
        else:
            mtx = str(matches or "")[:120]

        if scf == "missing":
            parts = ["Traceability: Missing."]
            if notes_short:
                parts.append(notes_short)
            elif mtx:
                parts.append(f"Mapped: {mtx}.")
            gaps.append(
                _gap_row(
                    ac_id,
                    "Missing Coverage",
                    " ".join(parts).strip(),
                    "Add or refine tests so at least one clearly substantiates this criterion.",
                )
            )
        elif scf in ("partial", "pending"):
            if ac_id in skip_partial_pending_ac_ids:
                continue
            parts = [f"Traceability: {status_raw}."]
            if notes_short:
                parts.append(notes_short)
            gaps.append(
                _gap_row(
                    ac_id,
                    "Partial Coverage",
                    " ".join(parts).strip(),
                    "Strengthen steps, evidence, or mapping until traceability reads Covered.",
                )
            )
    return gaps


_UNMAPPED_GROUP_ID = "Unmapped"


def _normalize_group_ac_id(ac_id: str) -> str:
    s = (ac_id or "").strip()
    if s in (
        "—",
        "-",
        "–",
        "\u2014",
        "N/A",
        "n/a",
        "",
        "unknown",
    ):
        return _UNMAPPED_GROUP_ID
    return s


def _group_sort_key(group_id: str) -> tuple:
    """Sort: AC-1, AC-2, …, then other ids, then Unmapped last."""
    if group_id == _UNMAPPED_GROUP_ID:
        return (2, 0, "")
    m = re.match(r"^AC-(\d+)$", group_id, re.IGNORECASE)
    if m:
        return (0, int(m.group(1)), group_id.lower())
    m2 = re.match(r"^AC\s*(\d+)$", group_id, re.IGNORECASE)
    if m2:
        return (0, int(m2.group(1)), group_id.lower())
    tail = re.search(r"(\d+)$", group_id)
    if tail and group_id.upper().startswith("AC"):
        return (0, int(tail.group(1)), group_id.lower())
    return (1, 0, group_id.lower())


def _dedupe_preserve_order(items: list[str], max_items: int = 14) -> list[str]:
    """Drop exact and substring-near duplicates."""
    out: list[str] = []
    seen_norm: list[str] = []
    for raw in items:
        s = " ".join(str(raw).split()).strip()
        if not s or s in ("—", "–"):
            continue
        key = re.sub(r"[.!?…]+$", "", s.lower())
        key = re.sub(r"\s+", " ", key)
        dup = False
        for ex in seen_norm:
            if key == ex:
                dup = True
                break
            if len(key) >= 20 and len(ex) >= 20 and (key in ex or ex in key):
                dup = True
                break
        if dup:
            continue
        seen_norm.append(key)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _split_description_chunks(text: str) -> list[str]:
    parts = re.split(r"\s*\|\s*|\s*;\s+", text)
    return [p.strip() for p in parts if p.strip()]


def summarize_coverage_gaps_for_display(gaps: list[dict]) -> list[dict]:
    """
    Group flat gap rows by acceptance_criteria_id (Unmapped for — / suite-wide).
    Merge overlapping text, dedupe bullets, sort AC groups ascending with Unmapped last.
    Output is for Streamlit expanders (not the legacy flat dataframe).
    """
    if not gaps:
        return []

    buckets: dict[str, dict] = {}
    for g in gaps:
        if not isinstance(g, dict):
            continue
        gid = _normalize_group_ac_id(str(g.get("acceptance_criteria_id") or ""))
        gt = _canonical_gap_type(str(g.get("gap_type") or ""))
        desc = str(g.get("description") or "").strip()
        act = str(g.get("suggested_action") or "").strip()
        if gid not in buckets:
            buckets[gid] = {
                "gap_types": set(),
                "desc_chunks": [],
                "actions": [],
            }
        b = buckets[gid]
        b["gap_types"].add(gt)
        if desc:
            b["desc_chunks"].extend(_split_description_chunks(desc))
        if act:
            b["actions"].append(act)

    groups: list[dict] = []
    for gid, b in buckets.items():
        types_sorted = sorted(
            b["gap_types"],
            key=lambda t: (_GAP_TYPE_ORDER.get(t, 99), t),
        )
        problems = _dedupe_preserve_order(b["desc_chunks"], max_items=14)
        actions = _dedupe_preserve_order(b["actions"], max_items=6)
        title = (
            "Unmapped (orphan tests or suite-wide gaps)"
            if gid == _UNMAPPED_GROUP_ID
            else gid
        )
        groups.append(
            {
                "group_id": gid,
                "title": title,
                "sort_key": _group_sort_key(gid),
                "gap_types": types_sorted,
                "problems": problems,
                "actions": actions,
            }
        )
    groups.sort(key=lambda x: x["sort_key"])
    return groups


def _ac_id_is_coverage_gap_placeholder(ac_id: str) -> bool:
    s = (ac_id or "").strip()
    if not s:
        return True
    if s.casefold() in ("n/a", "na", "none", "unknown"):
        return True
    if s in ("—", "-", "–", "\u2014"):
        return True
    return False


def _is_emptyish_gap_text(s: str) -> bool:
    t = (s or "").strip()
    return not t or t in ("—", "-", "–", "\u2014")


def _is_traceability_stub_only_description(desc: str) -> bool:
    """Traceability-derived rows that carry no detail beyond the status keyword."""
    d = (desc or "").strip().lower()
    if not d:
        return True
    return bool(re.fullmatch(r"traceability:\s*(missing|partial|pending)\.?", d))


def filter_coverage_gap_rows_for_display(gaps: list[dict]) -> list[dict]:
    """
    Remove rows that would render as empty noise (placeholder AC id and no description/action).
    Rows with placeholder AC id but substantive text (e.g. orphan test warnings) are kept.
    """
    out: list[dict] = []
    for g in gaps or []:
        if not isinstance(g, dict):
            continue
        ac = str(g.get("acceptance_criteria_id") or "").strip()
        desc = str(g.get("description") or "").strip()
        act = str(g.get("suggested_action") or "").strip()
        if _ac_id_is_coverage_gap_placeholder(ac) and _is_emptyish_gap_text(
            desc
        ) and _is_emptyish_gap_text(act):
            continue
        if _ac_id_is_coverage_gap_placeholder(ac) and _is_traceability_stub_only_description(
            desc
        ) and _is_emptyish_gap_text(act):
            continue
        out.append(g)
    return out


def coverage_gap_group_title(ac_id: object) -> str:
    """Human-readable expander label; avoids a bare em dash for suite-wide/orphan gaps."""
    s = str(ac_id if ac_id is not None else "").strip()
    if _ac_id_is_coverage_gap_placeholder(s):
        return "Unmapped (orphan tests or suite-wide gaps)"
    return s


def _merge_gap_lists(base: list[dict], extra: list[dict]) -> list[dict]:
    seen = {
        (
            g["acceptance_criteria_id"],
            g["gap_type"],
            g["description"][:160],
        )
        for g in base
    }
    out = list(base)
    for g in extra:
        key = (
            g["acceptance_criteria_id"],
            g["gap_type"],
            g["description"][:160],
        )
        if key not in seen:
            seen.add(key)
            out.append(g)
    return out


def _ai_coverage_gaps(data: dict) -> list[dict]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return []

    acceptance_criteria = data.get("acceptance_criteria") or []
    test_cases = data.get("test_cases") or []
    ac_lines = []
    for ac in acceptance_criteria:
        aid = ac.get("id", "N/A")
        atext = ac.get("text", "")
        linked = ac.get("test_case_ids") or []
        suffix = (
            f" (linked: {', '.join(str(x) for x in linked)})" if linked else ""
        )
        ac_lines.append(f"{aid}: {atext}{suffix}")
    ac_block = "\n".join(ac_lines) if ac_lines else "(none)"
    tc_block = _serialize_test_cases_for_prompt(
        test_cases if isinstance(test_cases, list) else []
    )

    prompt = f"""You are a UAT analyst. Add gaps the rule engine likely missed — do not repeat obvious JSON issues (unknown ids, empty steps) already easy to see.

Rules:
- Use **Missing Coverage** only when nothing meaningful is mapped or the suite cannot test the requirement.
- Use **Partial Coverage** when tests exist but do not substantiate the criterion (e.g. happy path only for a reject/invalid criterion).
- Use **Weak Validation** only for vague verify steps or missing alignment between intent and checks.
- Keep **description** under ~200 characters; **suggested_action** one short imperative sentence.

Acceptance criteria:
{ac_block}

Test cases and steps:
{tc_block}

Return JSON array. Each object: "acceptance_criteria_id" (or "—" for suite-wide), "gap_type" (Missing Coverage | Partial Coverage | Weak Validation | Inconsistency), "description", "suggested_action".

Return [] if nothing substantive remains.
"""

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    parsed = _parse_model_json_list(content)
    out: list[dict] = []
    for item in parsed:
        row = _normalize_gap_dict(item)
        if row:
            out.append(row)
    return out


def generate_coverage_gaps(
    data: dict,
    traceability_rows: list[dict] | None = None,
) -> list[dict]:
    """
    Structured coverage gaps for Review Synthesis. Combines:
    1) Rule-based checks (mapping, negatives, edges, weak steps, screenshots)
    2) Optional **traceability_rows** — same matrix as the Traceability table (Missing / Partial / Pending)
    3) Optional OpenAI augmentation when configured

    Never raises; falls back to heuristics (± traceability) if the API fails.
    """
    try:
        base = _heuristic_coverage_gaps(data)
    except Exception:
        base = []

    heuristic_ac_ids = {
        str(g.get("acceptance_criteria_id") or "")
        for g in base
        if str(g.get("acceptance_criteria_id") or "").strip()
        and str(g.get("acceptance_criteria_id")) != "—"
    }

    try:
        tr = _traceability_alignment_gaps(traceability_rows, heuristic_ac_ids)
    except Exception:
        tr = []

    merged = _consolidate_gaps_by_ac_and_type(base + tr)
    merged = filter_coverage_gap_rows_for_display(merged)

    try:
        extra = _ai_coverage_gaps(data)
    except Exception:
        return merged

    if not extra:
        return merged
    with_ai = _merge_gap_lists(merged, extra)
    return filter_coverage_gap_rows_for_display(_consolidate_gaps_by_ac_and_type(with_ai))

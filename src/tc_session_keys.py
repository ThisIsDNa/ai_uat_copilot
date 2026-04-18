"""
Streamlit session keys for per–test-case review widgets.

Suffixes disambiguate duplicate ``test_cases[].id`` values so widget keys stay unique.
"""

from __future__ import annotations


def tc_review_state_key(scenario_key: str, suffix: str) -> str:
    return f"tc_reviewed_{scenario_key}_{suffix}"


def tc_flagged_review_key(scenario_key: str, suffix: str) -> str:
    return f"tc_flagged_review_{scenario_key}_{suffix}"


def tc_review_notes_key(scenario_key: str, suffix: str) -> str:
    return f"tc_review_notes_{scenario_key}_{suffix}"


def tc_review_upload_key(scenario_key: str, suffix: str) -> str:
    return f"tc_review_upload_{scenario_key}_{suffix}"


def tc_row_session_suffixes(test_cases: list) -> list[str]:
    """
    One session-key suffix per ``test_cases`` index.

    Visible ``id`` is unchanged in the UI. When the same id appears more than once,
    the first row keeps the plain id; later rows use ``{id}__dup1``, ``__dup2``, …
    """
    totals: dict[str, int] = {}
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip() or "unknown"
        totals[tid] = totals.get(tid, 0) + 1

    per_id_k: dict[str, int] = {}
    out: list[str] = []
    for i, tc in enumerate(test_cases):
        if not isinstance(tc, dict):
            out.append(f"_nondict_{i}")
            continue
        tid = str(tc.get("id") or "").strip() or "unknown"
        if totals.get(tid, 0) <= 1:
            out.append(tid)
            continue
        k = per_id_k.get(tid, 0)
        per_id_k[tid] = k + 1
        if k == 0:
            out.append(tid)
        else:
            out.append(f"{tid}__dup{k}")
    return out


def duplicate_tc_ids(test_cases: list) -> list[str]:
    """Sorted ids that appear more than once (dict rows only)."""
    counts: dict[str, int] = {}
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip() or "unknown"
        counts[tid] = counts.get(tid, 0) + 1
    return sorted(tid for tid, c in counts.items() if c > 1)

"""
Count-based missing-information summary for normalized scenario dicts (UI / downloads).

All metrics are derived only from the scenario object shape and fields already in memory;
no parser changes and no inference beyond explicit lists and aligned step/screenshot slots.
"""

from __future__ import annotations

from typing import Any

from src.scenario_media import (
    clean_business_goal_for_schema,
    expected_step_screenshot_paths,
    step_texts,
)


def _is_valid_ac_entry(x: Any) -> bool:
    if not isinstance(x, dict):
        return False
    return bool(str(x.get("id") or "").strip()) and bool(str(x.get("text") or "").strip())


def _is_valid_tc_entry(x: Any) -> bool:
    if not isinstance(x, dict):
        return False
    return bool(str(x.get("id") or "").strip()) and bool(str(x.get("text") or "").strip())


def _acceptance_criteria_list(scenario: dict) -> list:
    raw = scenario.get("acceptance_criteria")
    return raw if isinstance(raw, list) else []


def _test_cases_list(scenario: dict) -> list:
    raw = scenario.get("test_cases")
    return raw if isinstance(raw, list) else []


def compute_missing_info_counts(scenario: dict) -> dict[str, int]:
    """
    Return count fields for UI. Counts are factual: empty sections, invalid rows,
    unlinked ACs, unmapped TCs, TCs without steps, and step rows without screenshot paths.
    """
    ac_list = _acceptance_criteria_list(scenario)
    tc_list = _test_cases_list(scenario)

    if not isinstance(scenario.get("acceptance_criteria"), list):
        missing_ac = 1
    elif len(ac_list) == 0:
        missing_ac = 1
    else:
        missing_ac = sum(1 for x in ac_list if not _is_valid_ac_entry(x))

    if not isinstance(scenario.get("test_cases"), list):
        missing_tc = 1
    elif len(tc_list) == 0:
        missing_tc = 1
    else:
        missing_tc = sum(1 for x in tc_list if not _is_valid_tc_entry(x))

    valid_acs = [x for x in ac_list if _is_valid_ac_entry(x)]
    valid_tcs = [x for x in tc_list if _is_valid_tc_entry(x)]

    missing_test_steps = sum(
        1 for tc in valid_tcs if len(step_texts(tc)) == 0
    )

    missing_screenshot_evidence = 0
    for tc in valid_tcs:
        steps = step_texts(tc)
        paths = expected_step_screenshot_paths(tc)
        for i, line in enumerate(steps):
            if not str(line or "").strip():
                continue
            rel = (paths[i] or "").strip() if i < len(paths) else ""
            if not rel:
                missing_screenshot_evidence += 1

    unlinked_ac = 0
    covered_tc_ids: set[str] = set()
    for ac in valid_acs:
        raw_ids = ac.get("test_case_ids")
        if not isinstance(raw_ids, list) or len(raw_ids) == 0:
            unlinked_ac += 1
            continue
        for tid in raw_ids:
            if tid is not None and str(tid).strip():
                covered_tc_ids.add(str(tid).strip())

    valid_tc_ids = {str(tc.get("id") or "").strip() for tc in valid_tcs}
    test_cases_without_ac_mapping = sum(
        1 for tid in valid_tc_ids if tid and tid not in covered_tc_ids
    )

    return {
        "missing_acceptance_criteria": missing_ac,
        "missing_test_cases": missing_tc,
        "missing_test_steps": missing_test_steps,
        "missing_screenshot_evidence": missing_screenshot_evidence,
        "unlinked_acceptance_criteria": unlinked_ac,
        "test_cases_without_ac_mapping": test_cases_without_ac_mapping,
    }


_MSG_SPARSE = (
    "This file was parsed successfully, but it does not include enough structured detail "
    "for a complete UAT review packet. Add acceptance criteria and test cases with steps "
    "and evidence paths where possible."
)

_MSG_PARTIAL = (
    "Download complete. The scenario includes core test data, but some expected review "
    "inputs are still missing (see counts above). Strengthen AC↔test links and screenshot "
    "evidence to support traceability."
)

_MSG_DEFAULT = (
    "This scenario is usable, but some review data is still missing. Add acceptance criteria, "
    "screenshot evidence, and explicit AC-to-test-case links to improve traceability and "
    "reviewer confidence."
)


def missing_info_narrative(scenario: dict, counts: dict[str, int]) -> str | None:
    """
    Choose a single guidance line from normalized data only (no file-type logic).
    Returns None when checks suggest no notable gaps (avoid over-warning).
    """
    ac_list = _acceptance_criteria_list(scenario)
    tc_list = _test_cases_list(scenario)
    n_ac = sum(1 for x in ac_list if _is_valid_ac_entry(x))
    n_tc = sum(1 for x in tc_list if _is_valid_tc_entry(x))

    missing_ac = counts["missing_acceptance_criteria"]
    missing_tc = counts["missing_test_cases"]
    missing_steps = counts["missing_test_steps"]
    missing_screens = counts["missing_screenshot_evidence"]
    unlinked = counts["unlinked_acceptance_criteria"]
    unmapped = counts["test_cases_without_ac_mapping"]

    if n_ac == 0 or n_tc == 0:
        return _MSG_SPARSE

    structural_issue = (
        missing_steps > 0
        or missing_screens > 0
        or unlinked > 0
        or unmapped > 0
    )
    list_noise = missing_ac > 0 or missing_tc > 0

    if structural_issue:
        return _MSG_PARTIAL

    if list_noise:
        return _MSG_DEFAULT

    return None


def is_scenario_registry_incomplete(scenario: dict) -> bool:
    """
    True when a saved scenario is **not** structurally ready for the normal review path.

    Used for registry ``incomplete`` vs ``in_progress``: incomplete drafts lack required
    context, AC↔TC linkage, steps, and/or per-step screenshot evidence (same signals as
    :func:`compute_missing_info_counts`).
    """
    if not isinstance(scenario, dict):
        return True
    counts = compute_missing_info_counts(scenario)
    if counts["missing_acceptance_criteria"] > 0 or counts["missing_test_cases"] > 0:
        return True
    if counts["missing_test_steps"] > 0 or counts["missing_screenshot_evidence"] > 0:
        return True
    if counts["unlinked_acceptance_criteria"] > 0 or counts["test_cases_without_ac_mapping"] > 0:
        return True
    title = str(scenario.get("scenario_title") or scenario.get("story_title") or "").strip()
    if not title:
        return True
    if not clean_business_goal_for_schema(scenario.get("business_goal")):
        return True
    return False


def registry_auto_review_state_for_scenario(scenario: dict) -> str:
    """
    Lifecycle bucket for **new** saves and overwrites while the row is still a draft
    (not ``approved``, ``in_review``, or ``archived``).
    """
    return "incomplete" if is_scenario_registry_incomplete(scenario) else "in_progress"

"""C2 review helpers — dedupe, gap actions, merge with reviewer focus."""

from __future__ import annotations

from src.review_c2 import (
    collect_gap_suggested_actions,
    dedupe_preserve_order,
    merge_suggested_fixes,
    structural_feedback_lines,
)


def test_dedupe_preserve_order() -> None:
    assert dedupe_preserve_order(["a", "a", "b", ""]) == ["a", "b"]


def test_collect_and_merge_suggested_fixes() -> None:
    gaps = [
        {"acceptance_criteria_id": "AC-1", "gap_type": "x", "description": "d", "suggested_action": "Fix A"},
        {"acceptance_criteria_id": "AC-1", "gap_type": "x", "description": "d2", "suggested_action": "Fix A"},
    ]
    assert collect_gap_suggested_actions(gaps) == ["Fix A"]
    merged = merge_suggested_fixes(["Fix A", "B"], ["Fix A", "C"])
    assert merged == ["Fix A", "B", "C"]


def test_structural_feedback_merges_pay_and_observations() -> None:
    rf = {"pay_attention_to": ["Watch checkout"], "risky": [], "may_be_missing": []}
    data = {
        "scenario_id": "s",
        "acceptance_criteria": [{"id": "AC-1", "text": "", "test_case_ids": []}],
        "test_cases": [{"id": "TC-01", "text": "t", "steps": [], "expected_step_screenshots": []}],
    }
    lines = structural_feedback_lines(rf, data)
    assert any("Watch checkout" in x for x in lines)
    assert any("AC-1" in x for x in lines)

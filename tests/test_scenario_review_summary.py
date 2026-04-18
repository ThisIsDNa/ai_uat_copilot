"""Unit tests for scenario missing-info counts (normalized dict only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scenario_review_summary import (
    compute_missing_info_counts,
    missing_info_narrative,
)

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def login_flow() -> dict:
    with (_ROOT / "data" / "sample_login_flow.json").open(encoding="utf-8") as f:
        return json.load(f)


def test_login_flow_counts_reasonable(login_flow: dict) -> None:
    c = compute_missing_info_counts(login_flow)
    assert c["missing_acceptance_criteria"] == 0
    assert c["missing_test_cases"] == 0
    assert c["unlinked_acceptance_criteria"] == 0
    assert c["test_cases_without_ac_mapping"] == 0
    assert c["missing_test_steps"] == 0
    assert c["missing_screenshot_evidence"] == 0


def test_empty_lists_sparse_narrative() -> None:
    s = {
        "acceptance_criteria": [],
        "test_cases": [],
    }
    c = compute_missing_info_counts(s)
    assert c["missing_acceptance_criteria"] == 1
    assert c["missing_test_cases"] == 1
    msg = missing_info_narrative(s, c)
    assert msg is not None
    assert "structured detail" in msg.lower()


def test_unlinked_ac_triggers_partial_or_default() -> None:
    s = {
        "acceptance_criteria": [
            {"id": "AC-1", "text": "Do thing", "test_case_ids": []},
        ],
        "test_cases": [
            {"id": "TC-1", "text": "Run", "steps": ["a"], "expected_step_screenshots": [""]},
        ],
    }
    c = compute_missing_info_counts(s)
    assert c["unlinked_acceptance_criteria"] == 1
    assert c["test_cases_without_ac_mapping"] == 1
    msg = missing_info_narrative(s, c)
    assert msg is not None

"""Registry incomplete vs in-progress and business goal sanitization."""

from __future__ import annotations

import json

import src.scenario_registry as scenario_registry

from src.scenario_media import clean_business_goal_for_schema
from src.scenario_review_summary import (
    is_scenario_registry_incomplete,
    registry_auto_review_state_for_scenario,
)


def test_clean_business_goal_strips_docx_placeholder() -> None:
    assert clean_business_goal_for_schema("— (not extracted; add a Business goal section in the document.)") == ""
    assert clean_business_goal_for_schema("  Real goal  ") == "Real goal"


def test_clean_business_goal_strips_step_scaffold_prefix() -> None:
    raw = "Open or navigate to the part of the application that supports: Login"
    assert clean_business_goal_for_schema(raw) == ""


def test_registry_incomplete_when_missing_mapping() -> None:
    d = {
        "scenario_id": "x",
        "scenario_title": "T",
        "story_title": "T",
        "business_goal": "Ship feature",
        "acceptance_criteria": [{"id": "AC-1", "text": "c", "test_case_ids": []}],
        "test_cases": [{"id": "TC-01", "text": "t", "steps": ["s"], "expected_step_screenshots": ["p.png"]}],
    }
    assert is_scenario_registry_incomplete(d) is True
    assert registry_auto_review_state_for_scenario(d) == "incomplete"


def test_registry_in_progress_when_structurally_ready() -> None:
    d = {
        "scenario_id": "x",
        "scenario_title": "T",
        "story_title": "T",
        "business_goal": "Ship feature",
        "acceptance_criteria": [{"id": "AC-1", "text": "c", "test_case_ids": ["TC-01"]}],
        "test_cases": [{"id": "TC-01", "text": "t", "steps": ["s"], "expected_step_screenshots": ["p.png"]}],
    }
    assert is_scenario_registry_incomplete(d) is False
    assert registry_auto_review_state_for_scenario(d) == "in_progress"


def test_saved_scenario_structurally_allows_approved_reads_disk_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(scenario_registry, "_PROJECT_ROOT", tmp_path)
    incomplete = {
        "scenario_id": "draft1",
        "scenario_title": "Draft",
        "story_title": "Draft",
        "business_goal": "Goal",
        "acceptance_criteria": [],
        "test_cases": [],
    }
    (tmp_path / "draft1.json").write_text(json.dumps(incomplete), encoding="utf-8")
    row = {"id": "draft1", "path": "draft1.json"}
    assert scenario_registry.saved_scenario_structurally_allows_approved(row) is False

    complete = {
        "scenario_id": "ok1",
        "scenario_title": "Ok",
        "story_title": "Ok",
        "business_goal": "Ship",
        "acceptance_criteria": [{"id": "AC-1", "text": "c", "test_case_ids": ["TC-01"]}],
        "test_cases": [{"id": "TC-01", "text": "t", "steps": ["s"], "expected_step_screenshots": ["p.png"]}],
    }
    (tmp_path / "ok1.json").write_text(json.dumps(complete), encoding="utf-8")
    row_ok = {"id": "ok1", "path": "ok1.json"}
    assert scenario_registry.saved_scenario_structurally_allows_approved(row_ok) is True

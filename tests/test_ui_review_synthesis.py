"""Unit tests for Review Synthesis explicit AC↔TC mapping helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scenario_builder_core import tc_id_to_explicit_ac_ids
from src.ui_review_synthesis import ac_explicit_link_rows

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def login_flow() -> dict:
    p = _ROOT / "data" / "sample_login_flow.json"
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def test_tc_id_to_explicit_ac_ids_login_flow(login_flow: dict) -> None:
    acs = login_flow["acceptance_criteria"]
    m = tc_id_to_explicit_ac_ids(acs)
    assert m["TC-01"] == ["AC-1"]
    assert m["TC-02"] == ["AC-2", "AC-3"]


def test_ac_explicit_link_rows_unknown_tc(login_flow: dict) -> None:
    acs = list(login_flow["acceptance_criteria"])
    acs.append(
        {
            "id": "AC-X",
            "text": "Orphan link",
            "test_case_ids": ["TC-99", "TC-01"],
        }
    )
    valid = {"TC-01", "TC-02"}
    rows, unknown = ac_explicit_link_rows(acs, valid)
    assert any("TC-99" in u for u in unknown)
    assert any(r["AC"] == "AC-X" for r in rows)

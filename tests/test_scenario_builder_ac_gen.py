"""Acceptance criteria heuristic generation (C3)."""

from __future__ import annotations

from src.scenario_builder_ac_gen import (
    clean_ac_suggestion_lines,
    generate_acceptance_criteria_suggestions,
)


def test_generate_ac_suggestions_uses_goal_and_areas() -> None:
    out = generate_acceptance_criteria_suggestions(
        business_goal="Ensure checkout completes within 3 seconds.",
        changed_areas_bulk="Payment UI: frontend\nCart service",
    )
    assert len(out) >= 2
    assert not any("user can verify" in s.lower() for s in out)
    assert any(s.lower().startswith("system ") or "regression" in s.lower() for s in out)
    assert any("checkout" in s.lower() for s in out)
    assert any("payment" in s.lower() or "cart" in s.lower() for s in out)


def test_generate_ac_fallback_when_empty_inputs() -> None:
    out = generate_acceptance_criteria_suggestions(business_goal="", changed_areas_bulk="")
    assert len(out) >= 2
    assert all(s.lower().startswith("system ") for s in out)


def test_clean_ac_suggestion_lines_drops_blank_and_dedupes() -> None:
    out = clean_ac_suggestion_lines(["  a  ", "", "  ", "a", "b\n"])
    assert out == ["a", "b"]

"""Lightweight RBAC helpers (no Streamlit)."""

from __future__ import annotations

from src.app_roles import (
    APP_ROLE_OPTIONS,
    normalize_role,
    role_can_access_scenario_review,
    role_can_change_registry_review_state,
    role_can_change_testing_status,
    role_can_delete_scenarios,
    views_for_role,
)


def test_normalize_role_unknown_defaults_to_tester() -> None:
    assert normalize_role(None) == "Tester"
    assert normalize_role("") == "Tester"
    assert normalize_role("admin") == "Tester"


def test_views_for_role() -> None:
    assert "Overview" not in views_for_role("Tester")
    assert "Overview" in views_for_role("Test Lead")
    assert "AI Scenario Builder" in views_for_role("Tester")


def test_permissions_matrix() -> None:
    assert not role_can_access_scenario_review("Tester")
    assert role_can_access_scenario_review("Test Lead")
    assert role_can_access_scenario_review("Test Manager")

    assert not role_can_delete_scenarios("Tester")
    assert not role_can_delete_scenarios("Test Lead")
    assert role_can_delete_scenarios("Test Manager")

    assert not role_can_change_registry_review_state("Tester")
    assert role_can_change_registry_review_state("Test Lead")
    assert role_can_change_registry_review_state("Test Manager")

    assert not role_can_change_testing_status("Tester")
    assert role_can_change_testing_status("Test Lead")
    assert role_can_change_testing_status("Test Manager")


def test_app_role_options_tuple() -> None:
    assert APP_ROLE_OPTIONS == ("Tester", "Test Lead", "Test Manager")

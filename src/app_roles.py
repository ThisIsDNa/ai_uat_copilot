"""
Lightweight simulated roles (no authentication). Used by the sidebar role selector and action guards.
"""

from __future__ import annotations

APP_ROLE_KEY = "app_user_role"

ROLE_TESTER = "Tester"
ROLE_TEST_LEAD = "Test Lead"
ROLE_TEST_MANAGER = "Test Manager"

APP_ROLE_OPTIONS: tuple[str, ...] = (ROLE_TESTER, ROLE_TEST_LEAD, ROLE_TEST_MANAGER)

_APP_VIEW_ORDER: tuple[str, ...] = (
    "Title Screen",
    "AI Scenario Builder",
    "Overview",
    "Scenario Management",
    "File Upload",
)


def normalize_role(role: object | None) -> str:
    r = str(role or "").strip()
    return r if r in APP_ROLE_OPTIONS else ROLE_TESTER


def views_for_role(role: object | None) -> tuple[str, ...]:
    """App views available in the sidebar for this role."""
    r = normalize_role(role)
    if r == ROLE_TESTER:
        return tuple(v for v in _APP_VIEW_ORDER if v != "Overview")
    return _APP_VIEW_ORDER


def role_can_access_scenario_review(role: object | None) -> bool:
    return normalize_role(role) != ROLE_TESTER


def role_can_delete_scenarios(role: object | None) -> bool:
    return normalize_role(role) == ROLE_TEST_MANAGER


def role_can_change_registry_review_state(role: object | None) -> bool:
    return normalize_role(role) in (ROLE_TEST_LEAD, ROLE_TEST_MANAGER)


def role_can_change_testing_status(role: object | None) -> bool:
    """Testing Status in Scenario Review → Test Results (registry-backed)."""
    return normalize_role(role) in (ROLE_TEST_LEAD, ROLE_TEST_MANAGER)

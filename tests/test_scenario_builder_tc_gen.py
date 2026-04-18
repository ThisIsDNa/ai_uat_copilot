"""Test-case title heuristics from acceptance criteria (guided builder C3)."""

from __future__ import annotations

from src.scenario_context_expansion import expanded_context_from_builder_session
from src.scenario_builder_tc_gen import (
    derive_negative_test_case_title_from_ac,
    derive_test_case_title_from_ac,
    propose_negative_test_cases_from_acceptance_criteria,
    propose_test_cases_from_acceptance_criteria,
)


def test_title_strips_user_can_and_successfully() -> None:
    t = derive_test_case_title_from_ac(
        "User can submit the enrollment successfully."
    )
    assert "successfully" not in t.lower()
    assert not t.lower().startswith("user can")
    assert "submit" in t.lower()
    assert "enrollment" in t.lower()


def test_negative_titles_cover_email_and_phone_when_both_in_context() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    ac = "User can save contact changes before continuing."
    joined = " ".join(derive_negative_test_case_title_from_ac(ac, variant=v, expanded=exp) for v in range(5)).lower()
    assert "email" in joined
    assert "phone" in joined


def test_permission_negative_title_not_email_only_when_dual_fields() -> None:
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
    }
    exp = expanded_context_from_builder_session(sess)
    t = derive_negative_test_case_title_from_ac("Validate profile contact save.", variant=3, expanded=exp)
    rhs = t.split(" - ", 1)[-1].lower()
    assert "permission" in rhs
    assert "permission block on email" != rhs


def test_derive_negative_title_rotates_patterns() -> None:
    ac = "User can submit the enrollment successfully."
    t0 = derive_negative_test_case_title_from_ac(ac, variant=0)
    t1 = derive_negative_test_case_title_from_ac(ac, variant=1)
    t2 = derive_negative_test_case_title_from_ac(ac, variant=2)
    t3 = derive_negative_test_case_title_from_ac(ac, variant=3)
    t4 = derive_negative_test_case_title_from_ac(ac, variant=4)
    titles = {t0.lower(), t1.lower(), t2.lower(), t3.lower(), t4.lower()}
    assert len(titles) == 5
    assert "missing" in t0.lower()
    assert "invalid" in t1.lower()
    assert "boundary" in t2.lower()
    assert "permission" in t3.lower()
    assert "dependency" in t4.lower()


def test_positive_passive_user_receives() -> None:
    t = derive_test_case_title_from_ac(
        "User receives a confirmation message and tracking identifier after submission."
    )
    assert "user - " in t.lower()
    assert "confirmation" in t.lower()
    assert "save" in t.lower() or "message" in t.lower()


def test_positive_passive_error_message_displayed() -> None:
    t = derive_test_case_title_from_ac("Error message is displayed for invalid input.")
    assert "invalid" in t.lower()
    assert "user - " in t.lower()


def test_positive_strips_provider_can() -> None:
    t = derive_test_case_title_from_ac("Provider can open new enrollment form for the patient.")
    assert "provider can" not in t.lower()
    assert "enrollment" in t.lower()
    assert t.lower().startswith("provider - ")


def test_propose_negative_skips_when_title_already_mapped() -> None:
    crit = "User can sign in with MFA."
    dup_title = derive_negative_test_case_title_from_ac(crit, variant=0)
    sess = {
        "sb_n_ac": 1,
        "sb_n_tc": 1,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": crit,
        "sb_ac_0_map": ["TC-01"],
        "sb_tc_0_id": "TC-01",
        "sb_tc_0_text": dup_title,
        "sb_tc_0_active": True,
    }
    assert propose_negative_test_cases_from_acceptance_criteria(sess) == []


def test_propose_positive_titles_dedupe_identical_ac_rows() -> None:
    """Repeated AC wording should not yield identical positive titles for every row."""
    same = "User can save updated email and phone on the profile."
    sess = {
        "sb_scenario_context": "Provider updates email and phone on the profile.",
        "sb_business_goal": "",
        "sb_workflow_name": "Profile",
        "sb_changed_areas_bulk": "",
        "sb_known_dependencies_bulk": "",
        "sb_n_ac": 3,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": same,
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": same,
        "sb_ac_2_id": "AC-03",
        "sb_ac_2_text": same,
    }
    out = propose_test_cases_from_acceptance_criteria(sess)
    assert len(out) == 3
    titles = [x["title"].lower() for x in out]
    assert len(set(titles)) == 3


def test_propose_skips_empty_ac_text() -> None:
    sess = {
        "sb_n_ac": 2,
        "sb_ac_0_id": "AC-01",
        "sb_ac_0_text": "User can sign in.",
        "sb_ac_1_id": "AC-02",
        "sb_ac_1_text": "   ",
    }
    out = propose_test_cases_from_acceptance_criteria(sess)
    assert len(out) == 1
    assert out[0]["ac_index"] == 0
    assert "sign" in out[0]["title"].lower() and "user - " in out[0]["title"].lower()

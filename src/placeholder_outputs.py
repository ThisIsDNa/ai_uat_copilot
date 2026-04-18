########################################################
#
#  What this provides:
#   - Traceability table placeholder
#   - Reviewer checklist placeholder
#   - Reviewer Focus placeholder
#
########################################################


def get_placeholder_traceability(data: dict) -> list[dict]:
    """Traceability rows; uses scenario JSON test_case_ids when present."""
    rows = []

    for ac in data.get("acceptance_criteria", []):
        linked = [str(x) for x in (ac.get("test_case_ids") or [])]
        rows.append(
            {
                "acceptance_criteria_id": ac.get("id", "N/A"),
                "acceptance_criteria_text": ac.get("text", ""),
                "matching_test_cases": linked,
                "coverage_status": "Pending",
                "notes": (
                    "Linked in scenario JSON; confirm against test evidence."
                    if linked
                    else "Add test_case_ids on this criterion or use AI traceability when configured."
                ),
            }
        )

    return rows


def get_placeholder_checklist() -> list[str]:
    """General UAT reviewer checklist (same for all scenarios today)."""
    return [
        "Confirm each acceptance criterion can be validated.",
        "Review positive, negative, and edge-case behavior.",
        "Confirm success and failure messaging appears at the correct time.",
        "Check whether changed areas could affect related workflows.",
    ]


def get_placeholder_reviewer_focus(data: dict) -> dict[str, list[str]]:
    """Placeholder reviewer guidance until Week 2 AI-assisted analysis."""
    workflow = data.get("workflow_name", "this workflow")
    areas = [a.get("area", "") for a in data.get("changed_areas", []) if a.get("area")]
    deps = data.get("known_dependencies") or []
    ac_n = len(data.get("acceptance_criteria", []))
    tc_n = len(data.get("test_cases", []))

    try:
        from src.scenario_context_expansion import expand_scenario_context_from_data

        exp = expand_scenario_context_from_data(data)
        pt = str((exp.scenario_classification or {}).get("primary_type") or "")
    except Exception:  # noqa: BLE001 — optional enrichment only
        pt = ""

    if pt == "action_event_flow":
        pay = [
            f"In {workflow}: verify **action → artifact → state** (draft vs sent), not only that buttons respond.",
            "Confirm **blocked** cases (closed/archived) never insert a draft, and **permission** gates match role rules.",
        ]
        risky = [
            "Missing **service-failure / no-artifact** coverage when AI or downstream integration is in scope.",
            "Missing **no-auto-send** or forbidden auto-transition checks after generation.",
        ]
        missing = [
            "Edit-before-send and **draft state** verification if the scenario promises review before commit.",
            "Persistence of generated drafts after **refresh** or reopen when the story requires it.",
        ]
        if ac_n and tc_n and ac_n > tc_n:
            missing.append(
                "AC count exceeds test cases—confirm coverage for each blocked path, permission path, and failure path."
            )
        else:
            missing.append(
                "Screenshots vs steps 1:1 for evidence; scenario notes for open questions."
            )
        return {
            "pay_attention_to": pay[:2],
            "risky": risky[:2],
            "may_be_missing": missing[:2],
        }

    pay = [
        f"In {workflow}: outcomes match the business goal (success paths, rejection, and messaging).",
    ]
    if areas:
        pay.append(
            f"Changed surfaces ({', '.join(areas[:3])}"
            + ("…" if len(areas) > 3 else "")
            + ")—regressions in layout, validation, and feedback."
        )
    else:
        pay.append(
            "What each test step asserts—field state, visible text, redirects—not only that actions complete."
        )
    pay = pay[:2]

    risky = [
        "Validation or error messaging (timing, wording, or missing feedback).",
    ]
    if deps:
        risky.insert(
            0,
            f"Dependencies: {', '.join(str(d) for d in deps[:3])}"
            + ("…" if len(deps) > 3 else ""),
        )
    elif areas:
        risky.append(f"Shared components adjacent to {areas[0]}.")
    risky = risky[:2]

    missing = [
        "Negative or blank-input paths if steps skew happy-path only.",
    ]
    if ac_n and tc_n and ac_n > tc_n:
        missing.append(
            "AC count exceeds test cases—confirm coverage or add TCs for remaining criteria."
        )
    else:
        missing.append(
            "Screenshots vs steps 1:1 for evidence; scenario notes for open questions."
        )
    missing = missing[:2]

    return {
        "pay_attention_to": pay,
        "risky": risky,
        "may_be_missing": missing,
    }

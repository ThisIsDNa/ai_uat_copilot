"""
C2 — Structural feedback and suggested fixes (read-only helpers for Scenario Review).

Reuses existing gap filtering and reviewer-focus payloads; no scenario mutation, no new AI calls.
"""

from __future__ import annotations

from typing import Any

from src.coverage_gaps import filter_coverage_gap_rows_for_display
from src.scenario_builder_core import unmapped_test_case_ids
from src.scenario_media import step_texts


def dedupe_preserve_order(lines: list[str]) -> list[str]:
    """Non-empty stripped strings, first occurrence wins."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in lines:
        t = (raw or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def collect_gap_suggested_actions(gap_rows: list[Any]) -> list[str]:
    """Project ``suggested_action`` from filtered coverage gap rows (same filter as UI tables)."""
    rows = filter_coverage_gap_rows_for_display(gap_rows)
    actions: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sa = str(row.get("suggested_action") or "").strip()
        if sa:
            actions.append(sa)
    return dedupe_preserve_order(actions)


def merge_suggested_fixes(gap_actions: list[str], reviewer_may_be_missing: list[str]) -> list[str]:
    """Gap-derived actions first, then reviewer-focus ``may_be_missing`` hints (deduped)."""
    merged: list[str] = []
    for src in (gap_actions, reviewer_may_be_missing):
        for x in src:
            t = (x or "").strip()
            if t:
                merged.append(t)
    return dedupe_preserve_order(merged)


def structural_observation_lines(data: dict) -> list[str]:
    """
    Read-only, high-level notes on AC text, AC↔TC alignment, and step brevity.
    Complements (does not replace) ``generate_reviewer_focus`` pay_attention lines.
    """
    if not isinstance(data, dict):
        return []
    obs: list[str] = []
    acs = [x for x in (data.get("acceptance_criteria") or []) if isinstance(x, dict)]
    for ac in acs:
        aid = str(ac.get("id") or "").strip() or "—"
        atx = str(ac.get("text") or "").strip()
        if not atx:
            obs.append(
                f"**Acceptance criteria clarity:** **{aid}** has no criterion text yet — reviewers cannot judge coverage."
            )
        elif len(atx) < 24:
            obs.append(
                f"**Acceptance criteria clarity:** **{aid}** is very short — consider whether the outcome is unambiguous."
            )

    um = unmapped_test_case_ids(data)
    if um:
        tail = ", ".join(um[:8]) + ("…" if len(um) > 8 else "")
        obs.append(
            f"**Test case alignment:** these test ids are not listed on any AC’s `test_case_ids`: {tail}"
        )

    tcs = [x for x in (data.get("test_cases") or []) if isinstance(x, dict)]
    for tc in tcs:
        tid = str(tc.get("id") or "").strip() or "—"
        steps = [str(s or "").strip() for s in step_texts(tc)]
        if not steps:
            obs.append(f"**Step flow:** **{tid}** has no step lines yet — execution path is undefined for reviewers.")
            continue
        short = sum(1 for s in steps if 0 < len(s) < 10)
        if short >= 2:
            obs.append(
                f"**Step quality:** **{tid}** includes multiple very short steps — flow may be hard to follow or evidence."
            )
            break
    return dedupe_preserve_order(obs)


def structural_feedback_lines(
    reviewer_focus: dict[str, list[str]],
    data: dict,
) -> list[str]:
    """Pay-attention bullets (reviewer focus) plus read-only structural observations, deduped."""
    pay = reviewer_focus.get("pay_attention_to") or []
    if not isinstance(pay, list):
        pay = []
    pay_s = [str(x).strip() for x in pay if str(x or "").strip()]
    obs = structural_observation_lines(data)
    return dedupe_preserve_order([*pay_s, *obs])

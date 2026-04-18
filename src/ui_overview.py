"""
Overview: Scope acceptance-criteria snapshot and Test Cases (AC–TC traceability).

`render_acceptance_criteria_snapshot` restores the explicit AC↔TC matrix table for Scope & Context.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.scenario_media import (
    resolve_media_path,
    step_texts,
    workflow_process_screenshot_pairs,
)
from src.scenario_builder_core import format_tc_ac_link_lines, tc_id_to_explicit_ac_ids

_TRACEABILITY_COL_ORDER = [
    "acceptance_criteria_id",
    "matching_test_cases",
    "acceptance_criteria_text",
    "coverage_status",
    "notes",
]


def _sort_traceability_df_by_ac_id(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "acceptance_criteria_id" not in df.columns:
        return df.reset_index(drop=True)
    return df.sort_values(
        by="acceptance_criteria_id", ascending=True, kind="stable"
    ).reset_index(drop=True)


def _format_matching_test_cases_cell(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, (list, tuple)):
        return ", ".join(str(x) for x in val if x is not None and str(x).strip())
    return str(val)


def _prepare_traceability_display_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "matching_test_cases" in d.columns:
        d["matching_test_cases"] = d["matching_test_cases"].map(_format_matching_test_cases_cell)
    ordered = [c for c in _TRACEABILITY_COL_ORDER if c in d.columns]
    extra = [c for c in d.columns if c not in ordered]
    return d[ordered + extra]


_TRACEABILITY_SNAPSHOT_COLS = [
    "acceptance_criteria_id",
    "acceptance_criteria_text",
    "matching_test_cases",
    "coverage_status",
]

_TRACEABILITY_SNAPSHOT_COLUMN_CONFIG = {
    "acceptance_criteria_id": st.column_config.TextColumn("AC ID", width="small"),
    "acceptance_criteria_text": st.column_config.TextColumn("Criterion", width="medium"),
    "matching_test_cases": st.column_config.TextColumn("Mapped tests", width="medium"),
    "coverage_status": st.column_config.TextColumn("Coverage", width="small"),
}


def render_workflow_level_screenshots(data: dict) -> None:
    """Workflow-level evidence images for Scope & Context (aligned to scenario JSON paths)."""
    st.markdown("### Workflow-Level Screenshots")
    pairs = workflow_process_screenshot_pairs(data)
    if not pairs and isinstance(data.get("workflow_screenshots"), list):
        # Legacy / alternate key — merge into a view-only shape for rendering.
        legacy = dict(data)
        legacy["workflow_process_screenshots"] = list(data.get("workflow_screenshots") or [])
        pairs = workflow_process_screenshot_pairs(legacy)
    if not pairs:
        st.info("No workflow-level screenshots were included for this scenario.")
        return
    n = len(pairs)
    cols = st.columns(min(n, 3))
    for i, (rel, lbl) in enumerate(pairs):
        rel_s = (rel or "").strip().replace("\\", "/")
        fname = Path(rel_s).name if rel_s else "—"
        lb = (lbl or "").strip()
        cap = f"{lb} — {fname}" if lb else fname
        with cols[i % len(cols)]:
            resolved = resolve_media_path(rel_s) if rel_s else None
            if resolved is not None and resolved.is_file():
                st.image(str(resolved), caption=cap, use_container_width=True)
            else:
                st.warning(f"Missing or unresolved image: {cap}")


def render_acceptance_criteria_snapshot(matrix: list[dict]) -> None:
    """Acceptance criteria / explicit AC↔TC snapshot for Scope & Context (sorted by AC ID)."""
    st.markdown("### Acceptance Criteria")
    df = pd.DataFrame(matrix)
    if df.empty:
        st.info("No acceptance criteria to map for this scenario.")
        return

    df = _prepare_traceability_display_df(_sort_traceability_df_by_ac_id(df))
    cols = [c for c in _TRACEABILITY_SNAPSHOT_COLS if c in df.columns]
    df = df[cols]
    cfg = {
        k: v
        for k, v in _TRACEABILITY_SNAPSHOT_COLUMN_CONFIG.items()
        if k in df.columns
    }
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=cfg or None,
    )


def render_test_cases_tab(data: dict, test_cases: list, tc_lookup: dict) -> None:
    """
    Test case expanders (TC id : description) with steps; AC-only rows when no TCs linked;
    orphan test cases at the end.
    """
    acs = [x for x in (data.get("acceptance_criteria") or []) if isinstance(x, dict)]
    st.markdown("### Test Cases")
    linked_from_ac: set[str] = set()
    for ac in acs:
        raw_ids = ac.get("test_case_ids") or []
        if not isinstance(raw_ids, list):
            continue
        for tid in raw_ids:
            if tid is not None and str(tid).strip():
                linked_from_ac.add(str(tid).strip())

    tc_to_acs = tc_id_to_explicit_ac_ids(acs)
    rendered_linked_tc: set[str] = set()

    for ac in acs:
        ac_id = str(ac.get("id") or "unknown")
        ac_text = (ac.get("text") or "").strip()
        mapped = ac.get("test_case_ids") or []
        if not isinstance(mapped, list):
            mapped = []
        if not mapped:
            with st.expander(f"{ac_id} — {ac_text or '—'}", expanded=False):
                st.warning(
                    "No test cases are explicitly linked to this criterion in the scenario data."
                )
            continue
        for tc_id in mapped:
            tid_key = str(tc_id).strip() if tc_id is not None else ""
            if tid_key in rendered_linked_tc:
                continue
            if tid_key:
                rendered_linked_tc.add(tid_key)
            tc = tc_lookup.get(tc_id)
            if tc is None and tc_id is not None:
                tc = tc_lookup.get(tid_key)
            label_tc = tid_key or "—"
            if tc:
                tc_desc = (tc.get("text") or "").strip() or "—"
                tid_disp = str(tc.get("id") or "").strip() or label_tc
                pair_title = f"{tid_disp} : {tc_desc}"
            else:
                pair_title = f"{label_tc} : —"
            with st.expander(pair_title, expanded=False):
                linked_lines = format_tc_ac_link_lines(acs, tid_key)
                if linked_lines:
                    st.markdown("**Listed under acceptance criteria:**")
                    for ln in linked_lines:
                        st.markdown(f"- {ln}")
                if tc:
                    tn = (tc.get("notes") or "").strip() if isinstance(tc, dict) else ""
                    if tn:
                        st.markdown("**Tester notes**")
                        st.info(tn)
                    steps = step_texts(tc)
                    st.markdown("**Test steps**")
                    if steps:
                        for sn, line in enumerate(steps, 1):
                            st.write(f"{sn}. {line}")
                    else:
                        st.caption("No steps in scenario data.")
                else:
                    st.error(f"Unknown test case id: `{label_tc}`")

    orphan_tcs = []
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip()
        if tid and tid not in linked_from_ac:
            orphan_tcs.append(tc)
    for tc in orphan_tcs:
        tid = str(tc.get("id") or "unknown").strip() or "unknown"
        ttext = (tc.get("text") or "").strip() or "—"
        steps = step_texts(tc)
        with st.expander(f"{tid} : {ttext}", expanded=False):
            st.caption("Not listed under any acceptance criterion.")
            tn = (tc.get("notes") or "").strip() if isinstance(tc, dict) else ""
            if tn:
                st.markdown("**Tester notes**")
                st.info(tn)
            st.markdown("**Test steps**")
            if steps:
                for sn, line in enumerate(steps, 1):
                    st.write(f"{sn}. {line}")
            else:
                st.caption("No steps in scenario data.")

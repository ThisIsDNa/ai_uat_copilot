"""
Review Synthesis tab: reviewer focus, coverage gaps, test results, handoff gating.

Session keys (`tc_reviewed_*`, `handoff_sent_*`, `test_results_status_*`, `tc_flagged_review_*`,
`tc_review_notes_*`, file uploader widget keys, dialog checkboxes) are written here via
`st.session_state`. Per–test-case keys use suffixes from ``src.tc_session_keys`` when
``test_cases[].id`` values repeat.
"""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from src.coverage_gaps import (
    coverage_gap_group_title,
    filter_coverage_gap_rows_for_display,
    generate_coverage_gaps,
)
from src.scenario_export_docx import (
    build_uat_review_export_docx,
    safe_export_filename,
)
from src.scenario_media import (
    _parse_step_screenshot_entry,
    expected_step_screenshot_labels,
    expected_step_screenshot_paths,
    raw_step_screenshot_paths_in_json_order,
    resolve_media_path,
    step_texts,
    resolved_test_case_title,
    workflow_process_screenshot_pairs,
)
from src.app_roles import APP_ROLE_KEY, normalize_role, role_can_change_testing_status
from src.scenario_builder_core import (
    format_tc_ac_link_lines,
    tc_id_to_explicit_ac_ids,
    unmapped_test_case_ids,
)
from src.scenario_registry import (
    display_label_for_review_state,
    internal_review_state_from_display,
    load_registry_saved,
    normalize_review_state,
    saved_scenario_structurally_allows_approved,
    update_saved_scenario_review_state_direct,
)
from src.scenario_review_summary import (
    compute_missing_info_counts,
    is_scenario_registry_incomplete,
    missing_info_narrative,
)
from src.review_c2 import (
    collect_gap_suggested_actions,
    merge_suggested_fixes,
    structural_feedback_lines,
)
from src.summarizer import generate_reviewer_focus
from src.tc_session_keys import (
    duplicate_tc_ids,
    tc_flagged_review_key,
    tc_review_notes_key,
    tc_review_state_key,
    tc_review_upload_key,
    tc_row_session_suffixes,
)


def _persist_test_results_status_changed() -> None:
    """Persist Testing Status selectbox to registry (saved scenarios only)."""
    if not role_can_change_testing_status(normalize_role(st.session_state.get(APP_ROLE_KEY))):
        return
    rid = (st.session_state.get("_tr_status_persist_rid") or "").strip()
    sk = st.session_state.get("_tr_status_persist_sk")
    if not rid or not sk:
        return
    lab = st.session_state.get(sk)
    if not lab:
        return
    internal = internal_review_state_from_display(lab)
    if internal == "approved":
        row = next((r for r in load_registry_saved() if r.get("id") == rid), None)
        if not isinstance(row, dict) or not saved_scenario_structurally_allows_approved(row):
            st.session_state[sk] = display_label_for_review_state("incomplete")
            return
    ok = update_saved_scenario_review_state_direct(rid, internal)
    if not ok and internal == "approved":
        st.session_state[sk] = display_label_for_review_state("incomplete")


def _valid_tc_id_set(test_cases: list) -> set[str]:
    out: set[str] = set()
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip()
        if tid:
            out.add(tid)
    return out


def ac_explicit_link_rows(
    acceptance_criteria: list,
    valid_tc_ids: set[str],
) -> tuple[list[dict], list[str]]:
    """
    Build rows for the explicit AC → TC table; return (rows, unknown_tc_reference_messages).
    """
    rows: list[dict] = []
    unknown: list[str] = []
    for ac in acceptance_criteria or []:
        if not isinstance(ac, dict):
            continue
        ac_id = str(ac.get("id") or "").strip() or "—"
        text = (ac.get("text") or "").strip()
        mapped = ac.get("test_case_ids") or []
        if not isinstance(mapped, list):
            mapped = []
        ids = [str(x).strip() for x in mapped if x is not None and str(x).strip()]
        for tid in ids:
            if tid not in valid_tc_ids:
                unknown.append(f"{tid!r} (listed under {ac_id})")
        rows.append(
            {
                "AC": ac_id,
                "Criterion": text,
                "Mapped test cases": ", ".join(ids) if ids else "—",
            }
        )
    return rows, unknown


def _render_screenshot_paths_grid(
    relative_paths: list[str],
    *,
    empty_message: str,
    labels: list[str] | None = None,
) -> None:
    """Small grid of images / missing-file warnings (mirrors Overview Scope pattern)."""
    if not relative_paths:
        st.caption(empty_message)
        return
    cols = st.columns(min(len(relative_paths), 3))
    for i, rel in enumerate(relative_paths):
        resolved = resolve_media_path(rel)
        lbl = ""
        if labels is not None and i < len(labels):
            lbl = (labels[i] or "").strip()
        cap = f"{lbl} — {rel}" if lbl else rel
        with cols[i % len(cols)]:
            if resolved is not None:
                st.image(str(resolved), caption=cap, use_container_width=True)
            else:
                st.warning(f"Missing file: {cap}")


def _render_scenario_map_section(data: dict, test_cases: list) -> None:
    """Counts, explicit AC→TC links, workflow images (collapsed) — honest for sparse data."""
    st.markdown("### Scenario Map")
    st.caption(
        "**Explicit links** come from `test_case_ids` on each acceptance criterion. "
        "**Traceability** and **Coverage gaps** may show inferred or partial coverage beyond these IDs."
    )

    ac_list = data.get("acceptance_criteria") or []
    if not isinstance(ac_list, list):
        ac_list = []
    n_ac = sum(1 for x in ac_list if isinstance(x, dict))
    n_tc = sum(1 for x in test_cases if isinstance(x, dict))
    n_steps = sum(len(step_texts(tc)) for tc in test_cases if isinstance(tc, dict))
    wf_pairs = workflow_process_screenshot_pairs(data)
    n_wf = len(wf_pairs)
    n_step_paths = 0
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        for p in expected_step_screenshot_paths(tc):
            if (p or "").strip():
                n_step_paths += 1

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Acceptance criteria", str(n_ac))
    m2.metric("Test cases", str(n_tc))
    m3.metric("Total steps", str(n_steps))
    m4.metric("Workflow images", str(n_wf))
    m5.metric("Step-level evidence paths", str(n_step_paths))

    if n_ac == 0 and n_tc == 0:
        st.info("No acceptance criteria or test cases in this scenario — workflow images may still apply.")

    valid_ids = _valid_tc_id_set(test_cases)
    rows, unknown_refs = ac_explicit_link_rows(ac_list, valid_ids)
    st.markdown("#### Explicit AC → test case IDs")
    if not rows:
        st.caption("No acceptance criteria objects to display.")
    else:
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "AC": st.column_config.TextColumn("AC", width="small"),
                "Criterion": st.column_config.TextColumn("Criterion", width="large"),
                "Mapped test cases": st.column_config.TextColumn("Mapped TCs", width="medium"),
            },
        )
    if unknown_refs:
        uniq = sorted(set(unknown_refs))
        st.warning(
            "Unknown test case id(s) in `test_case_ids` (no matching `test_cases[].id`): "
            + "; ".join(uniq)
        )

    with st.expander("Workflow-level screenshots (scenario context)", expanded=False):
        st.caption(
            "Images attached to the whole workflow, not a single step. "
            "The same set appears under **Scope & Context**."
        )
        paths = [p for p, _ in wf_pairs]
        wlabels = [lb for _, lb in wf_pairs]
        _render_screenshot_paths_grid(
            paths,
            empty_message="No workflow-level screenshot paths in this scenario.",
            labels=wlabels,
        )


@st.dialog("Reviewer checklist", width="large")
def _reviewer_checklist_dialog(scenario_key: str, items: list[str]) -> None:
    """Modal checklist; reopen from Test Results while reviewing evidence."""
    st.caption("Baseline checks—close this panel to continue in Test Results.")
    for i, item in enumerate(items):
        st.checkbox(item, key=f"dlg_chk_{scenario_key}_{i}")


def _count_unconfirmed_test_results(
    test_cases: list, scenario_key: str, *, data: dict
) -> int:
    """Count mapped test cases whose **Reviewed & Approved** checkbox is still unchecked."""
    tc_to_acs = tc_id_to_explicit_ac_ids(data.get("acceptance_criteria"))
    suffixes = tc_row_session_suffixes(test_cases)
    n = 0
    for i, tc in enumerate(test_cases):
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id", "") or "").strip()
        if not tid:
            continue
        if not tc_to_acs.get(tid):
            continue
        if not _tc_step_evidence_complete(tc):
            continue
        suf = suffixes[i]
        if not st.session_state.get(tc_review_state_key(scenario_key, suf), False):
            n += 1
    return n


def _all_test_results_confirmed(test_cases: list, scenario_key: str, *, data: dict) -> bool:
    if not test_cases:
        return True
    return _count_unconfirmed_test_results(test_cases, scenario_key, data=data) == 0


def _no_unmapped_test_cases(data: dict) -> bool:
    return len(unmapped_test_case_ids(data)) == 0


def _tc_has_nonempty_step_text(tc: dict) -> bool:
    return any(str(s or "").strip() for s in step_texts(tc))


def _tc_has_nonempty_step_screenshot(tc: dict) -> bool:
    raw = tc.get("expected_step_screenshots") or []
    if isinstance(raw, list):
        for item in raw:
            p, _, _ = _parse_step_screenshot_entry(item)
            if str(p or "").strip():
                return True
    return any(str(p or "").strip() for p in expected_step_screenshot_paths(tc))


def _tc_step_evidence_complete(tc: dict) -> bool:
    """Requires at least one non-empty step line and at least one non-empty step screenshot path."""
    return _tc_has_nonempty_step_text(tc) and _tc_has_nonempty_step_screenshot(tc)


def _incomplete_evidence_test_case_ids(test_cases: list) -> list[str]:
    out: list[str] = []
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id") or "").strip() or "unknown"
        if not _tc_step_evidence_complete(tc):
            out.append(tid)
    return out


def _all_test_cases_have_required_step_evidence(test_cases: list) -> bool:
    if not test_cases:
        return True
    return len(_incomplete_evidence_test_case_ids(test_cases)) == 0


def _any_flagged_for_review(test_cases: list, scenario_key: str) -> bool:
    suffixes = tc_row_session_suffixes(test_cases)
    for i, tc in enumerate(test_cases):
        if not isinstance(tc, dict):
            continue
        tid = str(tc.get("id", "") or "").strip()
        if not tid:
            continue
        suf = suffixes[i]
        if st.session_state.get(tc_flagged_review_key(scenario_key, suf), False):
            return True
    return False


def _ac_explicit_mapping_counts(data: dict) -> tuple[int, int]:
    """
    From scenario data only: count AC objects and how many list at least one non-empty
    `test_case_ids` entry (explicit mapping; does not resolve TC ids against `test_cases`).
    """
    acs = [x for x in (data.get("acceptance_criteria") or []) if isinstance(x, dict)]
    n = len(acs)
    if n == 0:
        return 0, 0
    n_mapped = 0
    for ac in acs:
        raw = ac.get("test_case_ids") or []
        if not isinstance(raw, list):
            raw = []
        if any(str(x).strip() for x in raw if x is not None):
            n_mapped += 1
    return n, n_mapped


def _ac_mapping_allows_approved(data: dict) -> bool:
    """Approved requires at least one AC and every AC to have ≥1 mapped TC id in data."""
    n, m = _ac_explicit_mapping_counts(data)
    return n > 0 and m == n


def _allowed_test_results_statuses(
    test_cases: list,
    scenario_key: str,
    *,
    registry_internal: str | None,
    data: dict,
) -> list[str]:
    """Dropdown options; **Approved** only when structurally complete + mapping + evidence + confirmations."""
    ri = normalize_review_state(registry_internal or "in_progress")
    structurally_ready = not is_scenario_registry_incomplete(data)
    can_approve = (
        structurally_ready
        and _ac_mapping_allows_approved(data)
        and _no_unmapped_test_cases(data)
        and _all_test_cases_have_required_step_evidence(test_cases)
        and _all_test_results_confirmed(test_cases, scenario_key, data=data)
    )
    # Registry **Incomplete** is a draft bucket — never offer **Approved** until the row leaves that state
    # (e.g. after re-save from the builder moves JSON + registry to **In Progress**).
    registry_blocks_approved = ri == "incomplete"
    if ri == "archived":
        opts = ["Archived", "Incomplete", "In Progress"]
        if test_cases:
            if _any_flagged_for_review(test_cases, scenario_key):
                opts.append("In Review")
            if can_approve and not registry_blocks_approved:
                opts.append("Approved")
        return opts
    opts = ["Incomplete", "In Progress"]
    if not test_cases:
        return opts
    if _any_flagged_for_review(test_cases, scenario_key):
        opts.append("In Review")
    if can_approve and not registry_blocks_approved:
        opts.append("Approved")
    return opts


def _clamp_test_results_status(current: str, allowed: list[str]) -> str:
    if current in allowed:
        return current
    for pick in ("Approved", "In Review", "In Progress", "Incomplete", "Archived"):
        if pick in allowed:
            return pick
    return allowed[0] if allowed else "In Progress"


_COVERAGE_GAPS_COLUMN_CONFIG = {
    "acceptance_criteria_id": st.column_config.TextColumn("AC", width="small"),
    "gap_type": st.column_config.TextColumn("Type", width="small"),
    "description": st.column_config.TextColumn("Description", width="large"),
    "suggested_action": st.column_config.TextColumn("Suggested action", width="large"),
}


def _coverage_gap_description_fragments(desc: str) -> list[str]:
    """Split combined gap descriptions on ``|`` into separate display fragments."""
    t = desc.strip()
    if not t:
        return []
    if "|" not in t:
        return [t]
    parts = [p.strip() for p in t.split("|")]
    return [p for p in parts if p]


def _render_coverage_gaps_table(
    gap_rows: list[dict],
    *,
    include_suggested_action_column: bool = True,
) -> None:
    """Flat table: easy to scan gaps alongside acceptance criteria ids/text."""
    gap_rows = filter_coverage_gap_rows_for_display(gap_rows)
    df = pd.DataFrame(gap_rows)
    if not include_suggested_action_column and "suggested_action" in df.columns:
        df = df.drop(columns=["suggested_action"])
    cfg = {k: v for k, v in _COVERAGE_GAPS_COLUMN_CONFIG.items() if k in df.columns}
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=cfg or None,
    )


def _render_coverage_gaps_by_ac(
    gap_rows: list[dict],
    *,
    show_suggested_action: bool = True,
) -> None:
    """Per AC: AC / Type / Description; optional suggested actions (see **Suggested Fixes** when omitted)."""
    gap_rows = filter_coverage_gap_rows_for_display(gap_rows)
    df = pd.DataFrame(gap_rows)
    ac_col = "acceptance_criteria_id"
    if df.empty:
        return
    if ac_col not in df.columns:
        _render_coverage_gaps_table(
            gap_rows,
            include_suggested_action_column=show_suggested_action,
        )
        return
    work = df.copy()
    work[ac_col] = work[ac_col].apply(
        lambda x: "—" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)
    )
    work = work.sort_values(by=ac_col, ascending=True, kind="stable")
    for ac_id, group in work.groupby(ac_col, sort=False):
        label = coverage_gap_group_title(ac_id)
        with st.expander(f"Coverage gaps — {label}", expanded=False):
            rows_list = group.reset_index(drop=True)
            for idx, row in rows_list.iterrows():
                if idx > 0:
                    st.divider()
                ac_val = str(row.get("acceptance_criteria_id", "") or "").strip() or "—"
                ac_display = coverage_gap_group_title(ac_val)
                gt = str(row.get("gap_type", "") or "").strip() or "—"
                desc_raw = row.get("description")
                desc = (
                    ""
                    if desc_raw is None or (isinstance(desc_raw, float) and pd.isna(desc_raw))
                    else str(desc_raw).strip()
                )
                st.markdown(f"**AC:** {ac_display}")
                st.markdown(f"**Type:** {gt}")
                st.divider()
                st.markdown("**Description**")
                frags = _coverage_gap_description_fragments(desc)
                if not frags:
                    st.markdown("—")
                elif len(frags) == 1:
                    st.markdown(frags[0])
                else:
                    for frag in frags:
                        st.markdown(f"- {frag}")
                if show_suggested_action and "suggested_action" in rows_list.columns:
                    sa_raw = row.get("suggested_action")
                    sa = (
                        ""
                        if sa_raw is None or (isinstance(sa_raw, float) and pd.isna(sa_raw))
                        else str(sa_raw).strip()
                    )
                    if sa:
                        st.divider()
                        st.markdown("**Suggested action**")
                        st.markdown(sa)


def _render_test_results(
    test_cases: list,
    scenario_key: str,
    checklist_items: list[str],
    *,
    data: dict,
    traceability_matrix: list[dict],
    gap_rows: list[dict],
    reviewer_focus: dict[str, list[str]],
    unconfirmed: int,
    tc_to_explicit_acs: dict[str, list[str]],
    registry_id: str | None = None,
    catalog_meta: dict | None = None,
    can_change_testing_status: bool = True,
) -> str:
    """Renders bordered Test Results + review actions. Returns current **Testing Status** label."""
    if registry_id and catalog_meta is not None:
        status_key = f"test_results_status_reg_{registry_id}"
        cat_ts = str(catalog_meta.get("review_state_updated_at") or "")
        sync_key = f"_trs_sync_ver_{registry_id}"
        reg_internal = normalize_review_state(catalog_meta.get("review_state"))
        reg_disp = display_label_for_review_state(reg_internal)
        # Registry already Approved: default per-test Reviewed checkboxes on so gating matches disk state.
        if reg_internal == "approved":
            sfx = tc_row_session_suffixes(test_cases)
            for idx, tc in enumerate(test_cases):
                if not isinstance(tc, dict):
                    continue
                if idx < len(sfx):
                    st.session_state.setdefault(tc_review_state_key(scenario_key, sfx[idx]), True)
        allowed = _allowed_test_results_statuses(
            test_cases, scenario_key, registry_internal=reg_internal, data=data
        )
        if reg_internal == "approved" and "Approved" not in allowed:
            allowed = list(dict.fromkeys([*allowed, "Approved"]))
        if st.session_state.get(sync_key) != cat_ts:
            st.session_state[status_key] = (
                reg_disp if reg_disp in allowed else _clamp_test_results_status(reg_disp, allowed)
            )
            st.session_state[sync_key] = cat_ts
        elif st.session_state.get(status_key) not in allowed:
            st.session_state[status_key] = _clamp_test_results_status(
                str(st.session_state.get(status_key, "In Progress")), allowed
            )
        st.session_state["_tr_status_persist_rid"] = registry_id
        st.session_state["_tr_status_persist_sk"] = status_key
    else:
        status_key = f"test_results_status_{scenario_key}"
        st.session_state.setdefault(status_key, "In Progress")
        allowed = _allowed_test_results_statuses(
            test_cases, scenario_key, registry_internal=None, data=data
        )
        cur = st.session_state.get(status_key, "In Progress")
        if cur not in allowed:
            st.session_state[status_key] = _clamp_test_results_status(cur, allowed)
        st.session_state["_tr_status_persist_rid"] = ""
        st.session_state["_tr_status_persist_sk"] = status_key

    with st.container(border=True):
        st.markdown("## Test Results")
        if registry_id and catalog_meta is not None:
            if normalize_review_state(catalog_meta.get("review_state")) == "incomplete":
                st.warning(
                    "**Registry status: Incomplete** — this scenario is stored as a **draft** and cannot be "
                    "**Approved** (or marked **Reviewed & Approved** per test) until structural requirements are met. "
                    "Continue in **AI Scenario Builder** and **save**; when the JSON is complete the registry moves to "
                    "**In Progress** and approval controls unlock."
                )
        n_ac_map, n_ac_mapped = _ac_explicit_mapping_counts(data)
        if not _ac_mapping_allows_approved(data):
            if n_ac_map == 0:
                st.warning(
                    "Approval unavailable: all Acceptance Criteria must have at least one mapped test case. "
                    "This scenario has **no** acceptance criteria objects — add criteria and map each to at least "
                    "one test id in `test_case_ids` before **Approved** can be selected."
                )
            else:
                st.warning(
                    "Approval unavailable: all Acceptance Criteria must have at least one mapped test case "
                    f"(via `test_case_ids`). **{n_ac_mapped} of {n_ac_map}** Acceptance Criteria have at least one "
                    "mapped test case."
                )
        elif test_cases and not _no_unmapped_test_cases(data):
            um = unmapped_test_case_ids(data)
            st.warning(
                "Unmapped test case(s): these test ids are not listed on any acceptance criterion’s "
                f"`test_case_ids` — **Approved** is blocked until each maps to at least one AC: "
                + ", ".join(um)
            )
        elif test_cases and not _all_test_cases_have_required_step_evidence(test_cases):
            bad = _incomplete_evidence_test_case_ids(test_cases)
            st.warning(
                "Incomplete test evidence: every test case must have **at least one non-empty step** and "
                "**at least one step-level screenshot path** in `expected_step_screenshots`. "
                f"**Approved** is blocked until fixed — affected test id(s): "
                + ", ".join(bad)
            )

        note_col, status_col = st.columns([2.2, 1])
        with note_col:
            if (
                not is_scenario_registry_incomplete(data)
                and _ac_mapping_allows_approved(data)
                and _no_unmapped_test_cases(data)
                and _all_test_cases_have_required_step_evidence(test_cases)
            ):
                st.caption(
                    "Structural checks, AC→TC mapping, and step evidence satisfy baseline rules. Use **Reviewed & Approved** "
                    "on each mapped test below when evidence is satisfactory (and registry is not **Incomplete**)."
                )
        with status_col:
            _ts_help = (
                "**Incomplete** (registry) — draft bucket; **Approved** is hidden until you re-save from the builder "
                "and the registry moves to **In Progress**. **In Progress** — structurally complete JSON; not yet approved. "
                "**In Review** — at least one **Flagged for Review** below. "
                "**Approved** — full structural checks, every AC lists ≥1 test id, every test id on ≥1 AC, step text + "
                "step screenshots, and every **Reviewed & Approved** checked for mapped tests with evidence. "
                "Changes write to the registry. **Archived** when the scenario is archived."
            )
            if not can_change_testing_status:
                _ts_help += " Your role cannot change this control."
            _ts_kw: dict = {
                "label": "Testing Status",
                "options": allowed,
                "key": status_key,
                "disabled": not can_change_testing_status,
                "help": _ts_help,
            }
            if can_change_testing_status:
                _ts_kw["on_change"] = _persist_test_results_status_changed
            st.selectbox(**_ts_kw)
            try:
                doc_bytes = build_uat_review_export_docx(
                    data=data,
                    test_cases=test_cases,
                    scenario_key=scenario_key,
                    traceability_matrix=traceability_matrix,
                    session=st.session_state,
                    tc_to_explicit_acs=tc_to_explicit_acs,
                    gap_rows=gap_rows,
                    reviewer_focus=reviewer_focus,
                    registry_id=registry_id,
                )
                dl_key = re.sub(r"[^\w]+", "_", f"export_{scenario_key}")[:96]
                st.download_button(
                    "Export DOCX",
                    data=doc_bytes,
                    file_name=safe_export_filename(data, scenario_key),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"uat_export_{dl_key}",
                    use_container_width=True,
                )
            except Exception as ex:
                st.caption(f"Export unavailable: {ex}")

        if st.button("Open Reviewer Checklist", key=f"open_checklist_{scenario_key}"):
            _reviewer_checklist_dialog(scenario_key, checklist_items)

        if not test_cases:
            st.info("No test cases in this scenario.")
            st.caption("**Testing Status** stays **In Progress** when there are no tests.")
            return str(st.session_state.get(status_key, "In Progress"))

        dup_ids = duplicate_tc_ids(test_cases)
        if dup_ids:
            st.warning(
                "Duplicate `test_cases[].id` value(s) in this scenario — review controls use unique keys per row; "
                "consider fixing ids in source data: "
                + ", ".join(dup_ids)
            )

        row_suffixes = tc_row_session_suffixes(test_cases)
        for i, tc in enumerate(test_cases):
            if not isinstance(tc, dict):
                continue
            tc_id = tc.get("id", "unknown")
            tc_text = resolved_test_case_title(tc)
            steps = step_texts(tc)
            paths = expected_step_screenshot_paths(tc)
            fig_labels = expected_step_screenshot_labels(tc)
            tid_str = str(tc_id)
            row_suf = row_suffixes[i]
            with st.expander(f"{tc_id} — {tc_text or '—'}", expanded=False):
                tc_author_notes = str(tc.get("notes") or "").strip() if isinstance(tc, dict) else ""
                if tc_author_notes:
                    st.markdown("##### Tester notes")
                    st.info(tc_author_notes)
                linked_acs = tc_to_explicit_acs.get(tid_str, [])
                ac_lines = format_tc_ac_link_lines(data.get("acceptance_criteria"), tid_str)
                if ac_lines:
                    st.markdown("**Acceptance criteria references** *(from `test_case_ids`)*")
                    for ln in ac_lines:
                        st.markdown(f"- {ln}")
                else:
                    st.caption(
                        "No acceptance criterion lists this test under `test_case_ids` — "
                        "see **Scope & Context** (AC snapshot) or edit scenario data to link ACs to this test id."
                    )
                st.markdown(f"**Test Case ID:** `{tid_str}`")
                st.markdown(f"**Test Case Title:** {tc_text or '—'}")

                ev_ok = _tc_step_evidence_complete(tc)
                if not ev_ok:
                    ev_parts: list[str] = []
                    if not _tc_has_nonempty_step_text(tc):
                        ev_parts.append("no non-empty step text")
                    if not _tc_has_nonempty_step_screenshot(tc):
                        ev_parts.append("no step screenshot paths")
                    st.warning(
                        "Incomplete evidence for this test — " + "; ".join(ev_parts) + ". "
                        "**Approved** is unavailable until every test has steps and step-level screenshots."
                    )

                n_st = len(steps)
                raw_paths = raw_step_screenshot_paths_in_json_order(tc)
                if n_st == 0 and raw_paths:
                    st.warning(
                        "Expected step screenshots are present but **no steps** are defined — "
                        "per-step alignment does not apply; verify evidence paths manually."
                    )
                    st.markdown("##### Expected Evidence Paths (no steps to align)")
                    for p in raw_paths:
                        st.code(p, language=None)

                non_empty = sum(1 for p in paths if (p or "").strip())
                if non_empty > 0 and n_st > 0 and non_empty < n_st:
                    st.warning(
                        f"{non_empty} screenshot path(s) for {n_st} step(s)—some steps have no evidence path."
                    )

                st.markdown("##### Steps and Expected Evidence")
                for i, step_line in enumerate(steps):
                    st.markdown(f"**Step {i + 1}.** {step_line}")
                    if i < len(paths):
                        rel = (paths[i] or "").strip()
                        lbl = (fig_labels[i] or "").strip() if i < len(fig_labels) else ""
                        cap = f"{lbl} — {rel}" if lbl else rel
                        if not rel:
                            st.caption("No image for this step.")
                        else:
                            resolved = resolve_media_path(rel)
                            if resolved is not None:
                                st.image(str(resolved), caption=cap, use_container_width=True)
                            else:
                                st.warning(f"Missing file: {cap}")
                    else:
                        st.caption("No image for this step.")

                is_mapped = bool(linked_acs)
                scenario_ready = not is_scenario_registry_incomplete(data)
                can_check_reviewed = is_mapped and ev_ok and scenario_ready
                ra_kw: dict = {
                    "label": "Reviewed & Approved",
                    "key": tc_review_state_key(scenario_key, row_suf),
                    "disabled": not can_check_reviewed,
                }
                if not scenario_ready:
                    ra_kw["help"] = (
                        "Complete scenario context (title, business goal), AC↔TC links, steps, and per-step "
                        "screenshots for every test — same rules as leaving **Incomplete** — before marking reviewed."
                    )
                elif not is_mapped:
                    ra_kw["help"] = (
                        "Map this test id under at least one acceptance criterion’s `test_case_ids` before approval."
                    )
                elif not ev_ok:
                    ra_kw["help"] = (
                        "Add non-empty step text and at least one step-level screenshot path before marking reviewed."
                    )
                st.checkbox(**ra_kw)
                st.checkbox(
                    "Flagged for Review",
                    key=tc_flagged_review_key(scenario_key, row_suf),
                )
                st.text_area(
                    "Reviewer notes",
                    key=tc_review_notes_key(scenario_key, row_suf),
                    placeholder="Optional notes for this test case…",
                    height=80,
                )
                st.file_uploader(
                    "Supporting image (optional)",
                    type=["png", "jpg", "jpeg", "webp", "gif"],
                    key=tc_review_upload_key(scenario_key, row_suf),
                )

        if not _ac_mapping_allows_approved(data):
            st.caption(
                "**Approved** also requires every Acceptance Criterion to have at least one entry in `test_case_ids` "
                "(see **Scope & Context**)."
            )
        elif not _no_unmapped_test_cases(data):
            um = unmapped_test_case_ids(data)
            st.caption(
                "**Approved** is blocked while these test case id(s) are not listed on any AC’s `test_case_ids`: "
                + ", ".join(um)
            )
        elif not _all_test_cases_have_required_step_evidence(test_cases):
            bad = _incomplete_evidence_test_case_ids(test_cases)
            st.caption(
                "**Approved** is blocked until these tests have step text and step screenshot paths: "
                + ", ".join(bad)
            )
        elif unconfirmed > 0:
            st.caption(
                f"**Approved** appears in the status menu after every **Reviewed & Approved** "
                f"is checked ({unconfirmed} remaining)."
            )
        if test_cases and not _any_flagged_for_review(test_cases, scenario_key):
            st.caption(
                "**In Review** appears in the status menu after at least one **Flagged for Review** is checked."
            )

        return str(st.session_state.get(status_key, "In Progress"))


def _render_review_synthesis_tab(
    data: dict,
    test_cases: list,
    scenario_key: str,
    traceability_matrix: list[dict],
    checklist_items: list[str],
    *,
    registry_id: str | None = None,
    catalog_meta: dict | None = None,
    can_change_testing_status: bool = True,
) -> None:
    """Overview → Review synthesis tab body (reviewer focus, gaps, test results, handoff)."""
    rf = generate_reviewer_focus(data)
    unconfirmed = _count_unconfirmed_test_results(test_cases, scenario_key, data=data)

    ac_list = data.get("acceptance_criteria") or []
    if not isinstance(ac_list, list):
        ac_list = []
    tc_to_explicit_acs = tc_id_to_explicit_ac_ids(ac_list)

    if is_scenario_registry_incomplete(data):
        st.markdown("### Draft readiness (structural validation)")
        counts = compute_missing_info_counts(data)
        st.caption(
            "Counts reflect missing or invalid data required before **Approved** / **Reviewed & Approved** "
            "(same rules as registry **Incomplete** vs **In Progress**)."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Check": k.replace("_", " ").title(), "Count": int(v)}
                    for k, v in sorted(counts.items())
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        nar = missing_info_narrative(data, counts)
        if nar:
            st.info(nar)
        st.divider()

    try:
        gap_rows = generate_coverage_gaps(data, traceability_rows=traceability_matrix)
    except Exception:
        gap_rows = []

    st.markdown("### Coverage Gaps")
    st.caption(
        "Missing or weak coverage signals from the same **generate_coverage_gaps** pipeline as before "
        "(descriptions only here — **Suggested Fixes** collects recommended actions)."
    )
    if gap_rows:
        _render_coverage_gaps_by_ac(gap_rows, show_suggested_action=False)
    elif is_scenario_registry_incomplete(data):
        st.info(
            "No heuristic/AI gap rows yet — use **Draft readiness** above and complete AC↔TC links, steps, "
            "screenshots, and context fields; gap detection strengthens as the scenario fills in."
        )
    else:
        st.info("No automated gaps flagged—still judge coverage yourself.")

    st.markdown("### Risk Flags")
    st.caption(
        "Failure-mode and validation-style risks (former **Reviewer Focus → Risks**); grounded in scenario fields or "
        "placeholder rules — not a pass/fail gate."
    )
    risky = rf.get("risky") or []
    if isinstance(risky, list) and any(str(x or "").strip() for x in risky):
        for line in risky:
            t = str(line or "").strip()
            if t:
                st.write(f"- {t}")
    else:
        st.info("No risk flags from the current rule/AI reviewer-focus pass.")

    st.markdown("### Structural Feedback")
    st.caption(
        "Descriptive read on acceptance criteria clarity, test alignment, and step flow — combines "
        "**Reviewer Focus → Pay attention** with lightweight read-only checks (does not change scenario data)."
    )
    sf_lines = structural_feedback_lines(rf, data)
    if sf_lines:
        for line in sf_lines:
            st.write(f"- {line}")
    else:
        st.info("No structural feedback lines yet — enrich AC text, mappings, and steps for richer observations.")

    st.markdown("### Suggested Fixes")
    st.caption(
        "Actionable improvements: **suggested_action** text from coverage gaps plus **Reviewer Focus → Possible gaps** "
        "(deduped). Maps to issues called out above."
    )
    fix_lines = merge_suggested_fixes(
        collect_gap_suggested_actions(gap_rows),
        rf.get("may_be_missing") or [],
    )
    try:
        from src.scenario_domain_labels import enrich_suggested_fix_lines

        fix_lines = enrich_suggested_fix_lines(fix_lines, data)
    except Exception:  # noqa: BLE001
        pass
    if fix_lines:
        for line in fix_lines:
            st.write(f"- {line}")
    else:
        st.info("No consolidated fix suggestions — add gap detail or enable reviewer-focus generation for more hints.")

    results_status = _render_test_results(
        test_cases,
        scenario_key,
        checklist_items,
        data=data,
        traceability_matrix=traceability_matrix,
        gap_rows=gap_rows,
        reviewer_focus=rf,
        unconfirmed=unconfirmed,
        tc_to_explicit_acs=tc_to_explicit_acs,
        registry_id=registry_id,
        catalog_meta=catalog_meta,
        can_change_testing_status=can_change_testing_status,
    )

    handoff_key = f"handoff_sent_{scenario_key}"
    if results_status == "Approved":
        st.session_state[handoff_key] = True
    else:
        st.session_state.pop(handoff_key, None)
    if st.session_state.get(handoff_key):
        st.success(
            "Marked as approved. Hand off per your team’s process (e.g. email, ticket, or sign-off)."
        )

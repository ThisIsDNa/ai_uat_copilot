"""
Guided step-by-step UI for the AI Scenario Builder (Path C1).

Reuses the same ``st.session_state`` keys as the classic builder. Imported lazily from
``render_scenario_builder_page`` to avoid circular imports with ``ui_scenario_builder``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from src.scenario_builder_core import (
    assign_ac_ids_for_bulk_rows,
    format_tc_ac_link_lines,
    parse_acceptance_criteria_bulk_lines,
    parse_steps_bulk,
    read_flat_builder_session,
    resolve_builder_scenario_id,
    sync_builder_persisted_media_from_data,
    tc_title_text_and_steps_from_session,
    unmapped_test_case_ids,
)
from src.scenario_builder_media import (
    bulk_upload_file_indices_for_step,
    tc_bulk_step_upload_widget_key,
    tc_step_upload_widget_key,
)
from src.scenario_media import resolved_test_case_title
from src.scenario_registry import load_registry_saved, persist_imported_json_scenario
from src.coverage_gaps import generate_coverage_gaps
from src.traceability import generate_traceability_matrix
from src.summarizer import generate_reviewer_focus
from src.review_c2 import collect_gap_suggested_actions, merge_suggested_fixes
from src.placeholder_outputs import get_placeholder_reviewer_focus
from src.ui_review_synthesis import _render_coverage_gaps_by_ac
from src.scenario_export_docx import build_execution_draft_export_docx, safe_execution_draft_filename

_GUIDED_STEP_KEY = "_guided_builder_step"
_N_GUIDED_STEPS = 6


def _ac_targets_for_tc_proposal(row: Mapping[str, Any]) -> list[int]:
    """AC row indices this proposal row maps to (includes ``merged_ac_indices`` when present)."""
    ac_i = int(row.get("ac_index", -1))
    raw = row.get("merged_ac_indices")
    out: set[int] = set()
    if ac_i >= 0:
        out.add(ac_i)
    if isinstance(raw, list):
        for x in raw:
            try:
                xi = int(x)
                if xi >= 0:
                    out.add(xi)
            except (TypeError, ValueError):
                continue
    return sorted(out)

_STEP_TITLES = [
    "Business goal",
    "Changed areas",
    "Acceptance criteria",
    "Test case generation",
    "Test steps & screenshots",
    "Final review",
]

# Final review: expand long AC/TC lists by default for scannability.
_FINAL_REVIEW_COLLAPSE_THRESHOLD = 6


def _guided_step() -> int:
    s = int(st.session_state.get(_GUIDED_STEP_KEY) or 0)
    return max(0, min(s, _N_GUIDED_STEPS - 1))


def _guided_reset_all() -> None:
    import src.ui_scenario_builder as usb

    usb._reset_builder_form()
    usb._sb_init_defaults()
    st.session_state[_GUIDED_STEP_KEY] = 0
    st.session_state[usb.BUILDER_LAYOUT_MODE_KEY] = usb.BUILDER_LAYOUT_GUIDED


def _clear_ac_generation_dialog_state() -> None:
    st.session_state.pop("_g_ac_gen_suggestions", None)
    for i in range(48):
        st.session_state.pop(f"_g_ac_dlg_{i}", None)
    st.session_state.pop("_g_ac_dlg_apply_mode", None)
    st.session_state.pop("_g_ac_dlg_replace_confirm", None)


def _apply_generated_acceptance_criteria(*, append: bool) -> None:
    """Write reviewed AC lines into ``sb_ac_*`` / ``sb_n_ac``; preserves AC maps when appending."""
    import src.ui_scenario_builder as usb

    sugg = st.session_state.get("_g_ac_gen_suggestions")
    if not isinstance(sugg, list) or not sugg:
        return
    edited: list[str] = []
    for i in range(len(sugg)):
        edited.append(str(st.session_state.get(f"_g_ac_dlg_{i}", "")).strip())
    texts = [t for t in edited if t]
    if not texts:
        return
    n_existing = int(st.session_state.get("sb_n_ac") or 0)
    combined: list[tuple[str | None, str]] = []
    old_maps: list[list] = []
    if append and n_existing > 0:
        for i in range(n_existing):
            aid = str(st.session_state.get(f"sb_ac_{i}_id") or "").strip() or None
            tx = str(st.session_state.get(f"sb_ac_{i}_text") or "").strip()
            if not tx:
                continue
            combined.append((aid, tx))
            m = st.session_state.get(f"sb_ac_{i}_map")
            old_maps.append(list(m) if isinstance(m, list) else [])
    for t in texts:
        combined.append((None, t))
    pairs = assign_ac_ids_for_bulk_rows(combined)
    pairs = [(a, t) for a, t in pairs if (t or "").strip()]
    if not pairs:
        return
    new_n = len(pairs)
    prev_n = int(st.session_state.get("sb_n_ac") or 0)
    ceiling = max(prev_n, new_n)
    for i in range(new_n, ceiling + 32):
        st.session_state.pop(f"sb_ac_{i}_id", None)
        st.session_state.pop(f"sb_ac_{i}_text", None)
        st.session_state.pop(f"sb_ac_{i}_map", None)
    st.session_state["sb_n_ac"] = new_n
    for i, (aid, tx) in enumerate(pairs):
        st.session_state[f"sb_ac_{i}_id"] = aid
        st.session_state[f"sb_ac_{i}_text"] = tx
        if append and i < len(old_maps):
            st.session_state[f"sb_ac_{i}_map"] = old_maps[i]
        else:
            st.session_state[f"sb_ac_{i}_map"] = []
    usb._sb_recompute_all_linked_ac_hints()
    _clear_ac_generation_dialog_state()


@st.dialog("Review generated acceptance criteria")
def _guided_ac_generation_review_dialog() -> None:
    """Review / edit heuristic AC lines before merging into the builder session."""
    from src.scenario_builder_ac_gen import clean_ac_suggestion_lines

    sugg_raw = st.session_state.get("_g_ac_gen_suggestions")
    sugg = clean_ac_suggestion_lines(sugg_raw if isinstance(sugg_raw, list) else [])
    st.session_state["_g_ac_gen_suggestions"] = sugg
    for j in range(len(sugg), 48):
        st.session_state.pop(f"_g_ac_dlg_{j}", None)
    if not sugg:
        st.warning("Nothing to review — try **Generate Acceptance Criteria** again.")
        if st.button("Close", key="sb_g_ac_dlg_close_empty"):
            _clear_ac_generation_dialog_state()
            st.rerun()
        return
    st.markdown(
        "Suggestions use **Scenario context**, **Business goal**, and **Changed areas** (from steps 1–2) via context expansion. "
        "Edit any line or clear a line to drop it, then **Append** or **Replace** — replacing clears existing AC rows only after you confirm."
    )
    for i, t in enumerate(sugg):
        key = f"_g_ac_dlg_{i}"
        if key not in st.session_state:
            st.session_state[key] = t
        st.text_area(f"Criterion {i + 1}", key=key, height=68, label_visibility="visible")
    n_existing = int(st.session_state.get("sb_n_ac") or 0)
    st.divider()
    st.radio(
        "Apply mode",
        ["Append to existing acceptance criteria", "Replace all acceptance criteria"],
        key="_g_ac_dlg_apply_mode",
        horizontal=False,
    )
    mode = str(st.session_state.get("_g_ac_dlg_apply_mode") or "").strip()
    replace = mode.startswith("Replace")
    if replace and n_existing > 0:
        st.checkbox(
            f"I understand this removes the current **{n_existing}** acceptance criterion row(s) and replaces them.",
            key="_g_ac_dlg_replace_confirm",
        )
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Accept all and apply", type="primary", key="sb_g_ac_dlg_accept"):
            if replace and n_existing > 0 and not bool(st.session_state.get("_g_ac_dlg_replace_confirm")):
                st.error("Confirm **Replace all** above before applying.")
            else:
                _apply_generated_acceptance_criteria(append=not replace)
                st.rerun()
    with b2:
        if st.button("Reject", type="secondary", key="sb_g_ac_dlg_reject"):
            _clear_ac_generation_dialog_state()
            st.rerun()
    with b3:
        if st.button("Close", type="secondary", key="sb_g_ac_dlg_close"):
            _clear_ac_generation_dialog_state()
            st.rerun()


def _clear_tc_generation_dialog_state() -> None:
    st.session_state.pop("_g_tc_gen_proposal", None)
    for i in range(48):
        st.session_state.pop(f"_g_tc_dlg_title_{i}", None)
    st.session_state.pop("_g_tc_dlg_apply_mode", None)
    st.session_state.pop("_g_tc_dlg_replace_confirm", None)


def _planned_tc_generation_count(prop: list[dict[str, Any]], *, replace: bool) -> int:
    """How many test cases would be created for the given proposal and mode."""
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    planned = 0
    for row in prop:
        targets = _ac_targets_for_tc_proposal(row)
        if not targets:
            continue
        if not any(
            str(st.session_state.get(f"sb_ac_{a}_text") or "").strip()
            for a in targets
            if 0 <= a < n_ac
        ):
            continue
        if not replace:
            all_mapped = True
            for a in targets:
                if a < 0 or a >= n_ac:
                    continue
                raw = st.session_state.get(f"sb_ac_{a}_map")
                cur = (
                    [str(x).strip() for x in raw if x is not None and str(x).strip()]
                    if isinstance(raw, list)
                    else []
                )
                if not cur:
                    all_mapped = False
                    break
            if all_mapped:
                continue
        planned += 1
    return planned


def _apply_generated_test_cases_from_dialog(*, replace: bool) -> None:
    """Create TC rows + ``sb_ac_*_map`` entries from reviewed proposal (merge or replace)."""
    import src.ui_scenario_builder as usb
    from src.scenario_builder_tc_gen import derive_test_case_title_from_ac

    prop = st.session_state.get("_g_tc_gen_proposal")
    if not isinstance(prop, list) or not prop:
        return
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    titles: list[str] = []
    for k in range(len(prop)):
        t = str(st.session_state.get(f"_g_tc_dlg_title_{k}", "")).strip()
        row = prop[k]
        crit = str(row.get("criterion") or "").strip()
        if not t:
            t = (
                str(row.get("title") or "").strip()
                or derive_test_case_title_from_ac(crit)
                or "Verify criterion"
            )
        titles.append(t.strip())
    if _planned_tc_generation_count(prop, replace=replace) <= 0:
        return
    if replace:
        usb._sb_wipe_all_test_cases()
    for k, row in enumerate(prop):
        targets = _ac_targets_for_tc_proposal(row)
        if not targets:
            continue
        if not any(
            str(st.session_state.get(f"sb_ac_{a}_text") or "").strip()
            for a in targets
            if 0 <= a < n_ac
        ):
            continue
        if not replace:
            all_mapped = True
            for a in targets:
                if a < 0 or a >= n_ac:
                    continue
                raw = st.session_state.get(f"sb_ac_{a}_map") or []
                cur = [
                    str(x).strip()
                    for x in (raw if isinstance(raw, list) else [])
                    if x is not None and str(x).strip()
                ]
                if not cur:
                    all_mapped = False
                    break
            if all_mapped:
                continue
        ac_i = int(row.get("ac_index", -1))
        if ac_i < 0 or ac_i >= n_ac:
            continue
        crit = str(st.session_state.get(f"sb_ac_{ac_i}_text") or row.get("criterion") or "").strip()
        if not crit:
            continue
        title = titles[k] if k < len(titles) else ""
        if not title.strip():
            title = derive_test_case_title_from_ac(crit) or "Verify criterion"
        j = int(st.session_state.get("sb_n_tc") or 0)
        st.session_state["sb_n_tc"] = j + 1
        tid = f"TC-{j + 1:02d}"
        st.session_state[f"sb_tc_{j}_id"] = tid
        st.session_state[f"sb_tc_{j}_text"] = title.strip()
        st.session_state[f"sb_tc_{j}_n_steps"] = 1
        st.session_state[f"sb_tc_{j}_steps_bulk"] = "1. "
        st.session_state[f"sb_tc_{j}_linked_ac"] = ac_i
        st.session_state[f"sb_tc_{j}_active"] = True
        st.session_state.pop(f"sb_tc_{j}_step_0_persisted_path", None)
        st.session_state.pop(f"sb_tc_{j}_step_0_persisted_paths", None)
        st.session_state.setdefault(f"sb_tc_{j}_notes", "")
        st.session_state.pop(f"sb_tc_{j}_title_steps_paste", None)
        st.session_state.pop(f"sb_tc_{j}_paste_digest", None)
        st.session_state.setdefault(f"sb_tc_{j}_step_0_text", "")
        for a in targets:
            if a < 0 or a >= n_ac:
                continue
            if not str(st.session_state.get(f"sb_ac_{a}_text") or "").strip():
                continue
            mkey = f"sb_ac_{a}_map"
            raw_map = st.session_state.get(mkey)
            cur: list[str] = (
                [str(x).strip() for x in raw_map if x is not None and str(x).strip()]
                if isinstance(raw_map, list)
                else []
            )
            nxt = list(cur)
            if tid not in nxt:
                nxt.append(tid)
            st.session_state[mkey] = nxt
    usb._sb_renumber_sequential_tc_ids()
    usb._sb_recompute_all_linked_ac_hints()
    _clear_tc_generation_dialog_state()


@st.dialog("Review generated test cases")
def _guided_tc_generation_review_dialog() -> None:
    import src.ui_scenario_builder as usb

    prop = st.session_state.get("_g_tc_gen_proposal")
    if not isinstance(prop, list) or not prop:
        st.warning("Nothing to review — use **Generate Test Cases** again after adding acceptance criteria text.")
        if st.button("Close", key="sb_g_tc_dlg_close_empty"):
            _clear_tc_generation_dialog_state()
            st.rerun()
        return
    st.markdown(
        "Each row is **one test case** mapped to its acceptance criterion. Edit titles, then **Merge** or **Replace**. "
        "**Merge** adds a TC only for ACs that have **no** mapped test case yet. **Replace** removes all existing test cases first — confirm when prompted."
    )
    for k, row in enumerate(prop):
        aid = str(row.get("ac_id") or "")
        crit = str(row.get("criterion") or "")
        merged = row.get("merged_ac_indices")
        extra = ""
        if isinstance(merged, list) and len(merged) > 1:
            extra = f" *(covers AC rows {', '.join(str(int(x) + 1) for x in merged)})*"
        key = f"_g_tc_dlg_title_{k}"
        if key not in st.session_state:
            st.session_state[key] = str(row.get("title") or "")
        st.caption(
            f"**{aid}** — {crit[:280]}{'…' if len(crit) > 280 else ''}{extra}"
        )
        st.text_input("Test case title", key=key, help="Concise, action-oriented title saved as the test case name.")
    n_existing = usb._sb_count_active_test_cases()
    st.divider()
    st.radio(
        "Apply mode",
        [
            "Merge: add one test case only for ACs with no mapped test case yet",
            "Replace: remove all existing test cases and create one per row above",
        ],
        key="_g_tc_dlg_apply_mode",
        horizontal=False,
    )
    mode = str(st.session_state.get("_g_tc_dlg_apply_mode") or "").strip()
    replace = mode.lower().startswith("replace")
    if replace and n_existing > 0:
        st.checkbox(
            f"I understand this removes the current **{n_existing}** test case row(s) and replaces them.",
            key="_g_tc_dlg_replace_confirm",
        )
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Accept all and apply", type="primary", key="sb_g_tc_dlg_accept"):
            if replace and n_existing > 0 and not bool(st.session_state.get("_g_tc_dlg_replace_confirm")):
                st.error("Confirm **Replace** above before applying.")
            elif _planned_tc_generation_count(prop, replace=replace) <= 0:
                st.error(
                    "Nothing to add — in **Merge** mode every acceptance criterion already has a mapped test case, "
                    "or there is no criterion text. Use **Replace** to rebuild from scratch."
                )
            else:
                _apply_generated_test_cases_from_dialog(replace=replace)
                st.rerun()
    with b2:
        if st.button("Reject", type="secondary", key="sb_g_tc_dlg_reject"):
            _clear_tc_generation_dialog_state()
            st.rerun()
    with b3:
        if st.button("Close", type="secondary", key="sb_g_tc_dlg_close"):
            _clear_tc_generation_dialog_state()
            st.rerun()


def _clear_neg_tc_generation_dialog_state() -> None:
    st.session_state.pop("_g_neg_tc_gen_proposal", None)
    for i in range(48):
        st.session_state.pop(f"_g_neg_tc_dlg_title_{i}", None)


def _apply_negative_test_cases_from_dialog() -> None:
    """Append negative TC rows and extend ``sb_ac_*_map``; never removes existing test cases."""
    import src.ui_scenario_builder as usb
    from src.scenario_builder_tc_gen import (
        derive_negative_test_case_title_from_ac,
        mapped_tc_title_lowers_for_ac,
    )

    prop = st.session_state.get("_g_neg_tc_gen_proposal")
    if not isinstance(prop, list) or not prop:
        return
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    per_ac_titles_lower: dict[int, set[str]] = {}
    created = 0
    for k, row in enumerate(prop):
        targets = _ac_targets_for_tc_proposal(row)
        if not targets:
            continue
        ac_i = int(row.get("ac_index", -1))
        if ac_i < 0 or ac_i >= n_ac:
            continue
        crit = str(st.session_state.get(f"sb_ac_{ac_i}_text") or row.get("criterion") or "").strip()
        if not crit:
            continue
        dlg_key = f"_g_neg_tc_dlg_title_{k}"
        t = str(st.session_state.get(dlg_key, "")).strip()
        if not t:
            t = (
                str(row.get("title") or "").strip()
                or derive_negative_test_case_title_from_ac(crit, variant=ac_i)
            )
        title = t.strip()
        if not title:
            continue
        tl = title.lower()
        if any(
            tl in mapped_tc_title_lowers_for_ac(st.session_state, a)
            for a in targets
            if 0 <= a < n_ac
        ):
            continue
        if any(tl in per_ac_titles_lower.setdefault(a, set()) for a in targets if 0 <= a < n_ac):
            continue
        for a in targets:
            if 0 <= a < n_ac:
                per_ac_titles_lower.setdefault(a, set()).add(tl)
        j = int(st.session_state.get("sb_n_tc") or 0)
        st.session_state["sb_n_tc"] = j + 1
        tid = f"TC-{j + 1:02d}"
        st.session_state[f"sb_tc_{j}_id"] = tid
        st.session_state[f"sb_tc_{j}_text"] = title
        st.session_state[f"sb_tc_{j}_n_steps"] = 1
        st.session_state[f"sb_tc_{j}_steps_bulk"] = "1. "
        st.session_state[f"sb_tc_{j}_linked_ac"] = ac_i
        st.session_state[f"sb_tc_{j}_active"] = True
        st.session_state.pop(f"sb_tc_{j}_step_0_persisted_path", None)
        st.session_state.pop(f"sb_tc_{j}_step_0_persisted_paths", None)
        st.session_state.setdefault(f"sb_tc_{j}_notes", "")
        st.session_state.pop(f"sb_tc_{j}_title_steps_paste", None)
        st.session_state.pop(f"sb_tc_{j}_paste_digest", None)
        st.session_state.setdefault(f"sb_tc_{j}_step_0_text", "")
        for a in targets:
            if a < 0 or a >= n_ac:
                continue
            if not str(st.session_state.get(f"sb_ac_{a}_text") or "").strip():
                continue
            mkey = f"sb_ac_{a}_map"
            raw_map = st.session_state.get(mkey)
            cur: list[str] = (
                [str(x).strip() for x in raw_map if x is not None and str(x).strip()]
                if isinstance(raw_map, list)
                else []
            )
            nxt = list(cur)
            if tid not in nxt:
                nxt.append(tid)
            st.session_state[mkey] = nxt
        created += 1
    usb._sb_renumber_sequential_tc_ids()
    usb._sb_recompute_all_linked_ac_hints()
    _clear_neg_tc_generation_dialog_state()


@st.dialog("Review generated negative test cases")
def _guided_negative_tc_generation_review_dialog() -> None:
    prop = st.session_state.get("_g_neg_tc_gen_proposal")
    if not isinstance(prop, list) or not prop:
        st.warning("Nothing to review — use **Generate Negative Test Cases** again after adding acceptance criteria text.")
        if st.button("Close", key="sb_g_neg_tc_dlg_close_empty"):
            _clear_neg_tc_generation_dialog_state()
            st.rerun()
        return
    st.markdown(
        "Optional **negative** coverage: validation, failure, or rejection scenarios. "
        "Each row appends **one** new test case to the builder and maps it to the listed AC — **existing test cases are not removed**."
    )
    for k, row in enumerate(prop):
        aid = str(row.get("ac_id") or "")
        crit = str(row.get("criterion") or "")
        merged = row.get("merged_ac_indices")
        extra = ""
        if isinstance(merged, list) and len(merged) > 1:
            extra = f" *(covers AC rows {', '.join(str(int(x) + 1) for x in merged)})*"
        key = f"_g_neg_tc_dlg_title_{k}"
        if key not in st.session_state:
            st.session_state[key] = str(row.get("title") or "")
        st.caption(f"**{aid}** — {crit[:280]}{'…' if len(crit) > 280 else ''}{extra}")
        st.text_input("Negative test case title", key=key, help="Failure / validation / rejection scenario.")
    st.divider()
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Accept all and apply", type="primary", key="sb_g_neg_tc_dlg_accept"):
            _apply_negative_test_cases_from_dialog()
            st.rerun()
    with b2:
        if st.button("Reject", type="secondary", key="sb_g_neg_tc_dlg_reject"):
            _clear_neg_tc_generation_dialog_state()
            st.rerun()
    with b3:
        if st.button("Close", type="secondary", key="sb_g_neg_tc_dlg_close"):
            _clear_neg_tc_generation_dialog_state()
            st.rerun()


def _clear_steps_gen_dialog_state() -> None:
    st.session_state.pop("_g_steps_gen_proposal", None)
    for i in range(32):
        st.session_state.pop(f"_g_steps_dlg_body_{i}", None)
    st.session_state.pop("_g_steps_dlg_apply_mode", None)
    st.session_state.pop("_g_steps_dlg_replace_confirm", None)


def _steps_gen_proposal_has_existing_steps(prop: list[dict[str, Any]]) -> bool:
    import src.ui_scenario_builder as usb

    for row in prop:
        j = int(row.get("tc_slot", -1))
        if j >= 0 and usb._sb_tc_has_substantive_steps(j):
            return True
    return False


def _apply_steps_generation_from_dialog(*, replace: bool) -> None:
    """Write reviewed steps into ``sb_tc_*``; merge appends without duplicate lines; replace overwrites steps only."""
    import src.ui_scenario_builder as usb

    prop = st.session_state.get("_g_steps_gen_proposal")
    if not isinstance(prop, list) or not prop:
        return
    for idx, row in enumerate(prop):
        j = int(row.get("tc_slot", -1))
        if j < 0:
            continue
        blob = str(st.session_state.get(f"_g_steps_dlg_body_{idx}", "")).strip()
        parsed = parse_steps_bulk(blob) if blob else []
        new_steps = [str(s).strip() for s in parsed if str(s).strip()]
        if not new_steps:
            new_steps = [str(s).strip() for s in (row.get("steps") or []) if str(s).strip()]
        if not new_steps:
            continue
        if replace:
            usb._sb_set_tc_steps_programmatically(j, new_steps)
        else:
            _tt, old = tc_title_text_and_steps_from_session(st.session_state, j)
            old_clean = [str(s).strip() for s in old if str(s).strip()]
            existing_lower = {x.lower() for x in old_clean}
            merged = list(old_clean)
            for s in new_steps:
                sl = s.lower()
                if sl not in existing_lower:
                    merged.append(s)
                    existing_lower.add(sl)
            merged = merged[:16] if merged else list(new_steps)
            usb._sb_set_tc_steps_programmatically(j, merged)
    usb._sb_update_guided_snapshot_from_session(guided_step=4)
    _clear_steps_gen_dialog_state()


@st.dialog("Review generated test steps")
def _guided_steps_generation_review_dialog() -> None:
    prop = st.session_state.get("_g_steps_gen_proposal")
    if not isinstance(prop, list) or not prop:
        st.warning("Nothing to review — use **Generate Test Steps** again when test cases have titles.")
        if st.button("Close", key="sb_g_steps_dlg_close_empty"):
            _clear_steps_gen_dialog_state()
            st.rerun()
        return
    st.markdown(
        "Steps are generated from each **test case title** with optional context from **linked acceptance criteria**. "
        "Edit any line, then **Merge** (append to existing steps) or **Replace** (overwrite steps only — titles, IDs, and AC mappings stay)."
    )
    for idx, row in enumerate(prop):
        tid = str(row.get("tc_id") or "")
        ttl = str(row.get("title") or "")
        key = f"_g_steps_dlg_body_{idx}"
        default_lines = "\n".join(
            f"{i + 1}. {s}" for i, s in enumerate(row.get("steps") or []) if str(s).strip()
        )
        if key not in st.session_state:
            st.session_state[key] = default_lines
        st.markdown(f"**{tid}** — {ttl[:200]}{'…' if len(ttl) > 200 else ''}")
        st.text_area(
            "Numbered steps (one per line)",
            key=key,
            height=min(220, 40 + 28 * max(3, len(row.get("steps") or []))),
            help="Edit freely; blank lines are dropped on apply.",
            label_visibility="visible",
        )
    has_existing = _steps_gen_proposal_has_existing_steps(prop)
    st.divider()
    st.radio(
        "Apply mode",
        [
            "Merge: append generated steps after any existing steps (skip exact duplicates)",
            "Replace: overwrite existing steps with the lines above (test case title unchanged)",
        ],
        key="_g_steps_dlg_apply_mode",
        horizontal=False,
    )
    mode = str(st.session_state.get("_g_steps_dlg_apply_mode") or "").strip()
    replace = mode.lower().startswith("replace")
    if replace and has_existing:
        st.checkbox(
            "I understand this **replaces** existing step text for the listed test cases (screenshots for removed step indices are cleared).",
            key="_g_steps_dlg_replace_confirm",
        )
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Accept all and apply", type="primary", key="sb_g_steps_dlg_accept"):
            if replace and has_existing and not bool(st.session_state.get("_g_steps_dlg_replace_confirm")):
                st.error("Confirm **Replace** above before applying.")
            else:
                _apply_steps_generation_from_dialog(replace=replace)
                st.rerun()
    with b2:
        if st.button("Reject", type="secondary", key="sb_g_steps_dlg_reject"):
            _clear_steps_gen_dialog_state()
            st.rerun()
    with b3:
        if st.button("Close", type="secondary", key="sb_g_steps_dlg_close"):
            _clear_steps_gen_dialog_state()
            st.rerun()


@st.dialog("Review polished test steps")
def _guided_polish_review_dialog() -> None:
    """Shows proposed polish; applies only after explicit confirmation."""
    import src.ui_scenario_builder as usb

    updates = st.session_state.get("_g_polish_dialog_updates")
    lines = st.session_state.get("_g_polish_dialog_lines") or []
    if not isinstance(updates, dict) or not updates:
        st.warning("No pending changes.")
        return
    st.markdown(
        "**Proposed changes** — review below. Nothing is written to disk until you **Save** the scenario later."
    )
    for ln in lines:
        st.markdown(ln)
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Accept and apply", type="primary", key="sb_g_polish_dlg_apply"):
            usb._sb_apply_polish_step_updates(updates)
            st.session_state.pop("_g_polish_dialog_updates", None)
            st.session_state.pop("_g_polish_dialog_lines", None)
            st.session_state.pop("_g_polish_dialog_rows", None)
            st.rerun()
    with c2:
        if st.button("Cancel", type="secondary", key="sb_g_polish_dlg_cancel"):
            st.session_state.pop("_g_polish_dialog_updates", None)
            st.session_state.pop("_g_polish_dialog_lines", None)
            st.session_state.pop("_g_polish_dialog_rows", None)
            st.rerun()


def render_guided_scenario_builder(*, pending_select_key: str) -> None:
    import src.ui_scenario_builder as usb

    usb._sb_sync_ac_n_from_row_keys()
    usb._sb_restore_missing_from_guided_snapshot()
    usb._sb_backfill_empty_from_guided_snapshot()
    shots_saved = st.session_state.pop(usb._SB_FLASH_GUIDED_STEP_SHOTS_SAVED, None)
    st.session_state.setdefault(_GUIDED_STEP_KEY, 0)
    step = _guided_step()
    if shots_saved:
        st.success(str(shots_saved))

    st.markdown("### Guided scenario creation")
    st.caption(
        "Work through each step below. Your entries are the same draft as **Classic** mode — "
        "switch modes anytime without losing data."
    )
    st.progress((step + 1) / _N_GUIDED_STEPS)
    st.markdown(f"**Step {step + 1} of {_N_GUIDED_STEPS}: {_STEP_TITLES[step]}**")

    # --- Step bodies ---
    if step == 0:
        st.markdown(
            "Start with **Scenario context** — the single place for narrative detail (actors, fields, validation, "
            "edge cases, and what the AI should respect). Then title, workflow, business goal, and ID — all feed "
            "Scenario Review and exports."
        )
        st.text_area(
            "Scenario context",
            key="sb_scenario_context",
            height=160,
            placeholder=(
                "Example: Provider updates email and phone number. Email must be valid format. "
                "Phone must be 10 digits. Required fields should block save if blank. Save should persist changes "
                "and display confirmation message."
            ),
            help=(
                "**Main freeform narrative** for this scenario. Describe what changed, how the workflow behaves, "
                "and any rules the generators should follow. Feeds **context expansion** for AC, test cases, negatives, "
                "and steps — additive only; never auto-overwrites your rows."
            ),
        )
        st.text_input(
            "Scenario title",
            key="sb_story_title",
            placeholder="e.g. Patient profile update",
        )
        st.text_input(
            "Workflow name",
            key="sb_workflow_name",
            placeholder="e.g. Registration flow",
        )
        st.text_area(
            "Business goal",
            key="sb_business_goal",
            height=88,
            placeholder="One concise outcome the business cares about (e.g. reduce checkout errors).",
        )
        st.checkbox("Auto-generate Scenario ID from title", key="sb_auto_id")
        if not st.session_state.get("sb_auto_id"):
            st.text_input(
                "Scenario ID (required when auto is off)",
                key="sb_scenario_id",
                placeholder="e.g. patient_profile_update",
            )

    elif step == 1:
        st.markdown(
            "List **what changed** in this release and any **dependencies** other teams should know about. "
            "Both are optional; you can skip lines."
        )
        st.text_area(
            "Changed areas (one per line)",
            key="sb_changed_areas_bulk",
            height=140,
            placeholder="e.g.\nPatient chart\nBilling: backend\n- Checkout UI",
        )
        st.text_area(
            "Known dependencies (one per line)",
            key="sb_known_dependencies_bulk",
            height=100,
            placeholder="e.g.\nAuth service\n- Payment API",
        )
        st.divider()
        st.markdown(
            "##### Workflow-level screenshots (optional)\n"
            "Attach **early** context (flow overview, environment, or release scope) here — not per-test-step evidence. "
            "Step screenshots stay on **Test steps & screenshots**."
        )
        st.file_uploader(
            "Workflow screenshot files (.png, .jpg, .jpeg)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="sb_wf_upload",
        )
        wf_persisted = st.session_state.get("sb_wf_persisted_paths")
        n_prev_wf = (
            len([x for x in wf_persisted if str(x).strip()])
            if isinstance(wf_persisted, list)
            else 0
        )
        wf_up = st.session_state.get("sb_wf_upload")
        n_wf_up = len(wf_up) if isinstance(wf_up, list) else (1 if wf_up is not None and hasattr(wf_up, "read") else 0)
        if isinstance(wf_persisted, list) and wf_persisted:
            for wi, p in enumerate(list(wf_persisted)):
                ps = str(p).strip()
                if not ps:
                    continue
                slot = wi + 1
                st.markdown(f"**Workflow image {slot}** — `{Path(ps).name}`")
                st.caption(ps)
                c2, c3 = st.columns([4, 1])
                with c2:
                    st.text_input(
                        "Caption",
                        key=f"sb_wf_lbl_{wi}",
                        placeholder="What this image shows",
                    )
                with c3:
                    st.button(
                        "Remove",
                        key=f"sb_g_rm_wf_{wi}",
                        on_click=usb._sb_clear_wf_persisted_at,
                        args=(wi,),
                        type="secondary",
                    )
        if n_wf_up:
            for ui in range(n_wf_up):
                idx = n_prev_wf + ui
                st.markdown(f"**Workflow image {idx + 1}** *(new)*")
                st.text_input("Caption", key=f"sb_wf_lbl_{idx}", placeholder="…")
        st.button(
            "Clear workflow file picker",
            key="sb_g_clear_wf_upload",
            on_click=usb._sb_clear_wf_upload_widget,
            type="secondary",
        )

    elif step == 2:
        st.markdown(
            "**Paste** acceptance criteria (one per line). You can include ids like `AC-01` or leave them off — "
            "ids are normalized when you click **Apply pasted lines**. Then tune rows in the expanders below."
        )
        if st.button(
            "Generate Acceptance Criteria",
            type="secondary",
            key="sb_g_btn_gen_ac",
            help=(
                "Builds **testable system-behavior** criteria from **Scenario context**, **Business goal**, **Workflow**, "
                "and **Changed areas** (context expansion). Opens a review panel — you can edit each line, append to "
                "existing ACs, or replace all (with confirmation)."
            ),
        ):
            from src.scenario_builder_ac_gen import generate_acceptance_criteria_suggestions

            _clear_ac_generation_dialog_state()
            from src.scenario_context_expansion import expanded_context_from_builder_session

            exp = expanded_context_from_builder_session(st.session_state)
            bg = str(st.session_state.get("sb_business_goal") or "")
            ca = str(st.session_state.get("sb_changed_areas_bulk") or "")
            st.session_state["_g_ac_gen_suggestions"] = generate_acceptance_criteria_suggestions(
                business_goal=bg,
                changed_areas_bulk=ca,
                expanded=exp,
            )
            _guided_ac_generation_review_dialog()
        st.text_area(
            "Bulk paste acceptance criteria (one per line)",
            key="sb_ac_bulk_text",
            height=140,
            placeholder="AC-01 User can sign in\nAC-02 Reports load within 2s",
        )
        if st.button("Apply pasted lines as acceptance criteria", key="sb_g_btn_apply_ac_bulk"):
            parsed = parse_acceptance_criteria_bulk_lines(st.session_state.get("sb_ac_bulk_text"))
            if not parsed:
                st.warning("No non-empty lines to apply.")
            else:
                pairs = assign_ac_ids_for_bulk_rows(parsed)
                old_n = int(st.session_state.get("sb_n_ac") or 0)
                new_n = len(pairs)
                for i in range(new_n, max(old_n, new_n) + 32):
                    st.session_state.pop(f"sb_ac_{i}_id", None)
                    st.session_state.pop(f"sb_ac_{i}_text", None)
                    st.session_state.pop(f"sb_ac_{i}_map", None)
                st.session_state["sb_n_ac"] = new_n
                for i, (aid, tx) in enumerate(pairs):
                    st.session_state[f"sb_ac_{i}_id"] = aid
                    st.session_state[f"sb_ac_{i}_text"] = tx
                    st.session_state[f"sb_ac_{i}_map"] = []
                usb._sb_recompute_all_linked_ac_hints()
                st.success(f"Applied **{new_n}** acceptance criteria (mappings reset).")
                st.rerun()
        st.number_input(
            "Number of acceptance criteria (manual)",
            min_value=0,
            max_value=60,
            step=1,
            key="sb_n_ac",
        )
        n_ac = int(st.session_state.get("sb_n_ac") or 0)
        if n_ac == 0:
            st.info(
                "You can **save a draft** without acceptance criteria. Add at least one AC (and map tests) "
                "before the scenario leaves **Incomplete** in Scenario Management."
            )
        for i in range(n_ac):
            aid_key = f"sb_ac_{i}_id"
            if aid_key not in st.session_state:
                st.session_state[aid_key] = f"AC-{i + 1:02d}"
            with st.expander(f"Acceptance criterion {i + 1}", expanded=(i == 0 and n_ac <= 5)):
                h1, h2 = st.columns([4, 1])
                with h1:
                    st.text_input("AC id", key=aid_key)
                with h2:
                    st.button(
                        "Remove",
                        key=f"sb_g_btn_rm_ac_{i}",
                        on_click=usb._sb_remove_ac,
                        args=(i,),
                        type="secondary",
                    )
                st.text_area("Criterion text", key=f"sb_ac_{i}_text", height=68, placeholder="Verifiable outcome…")

    elif step == 3:
        st.markdown(
            "Create **test case IDs** and link them to acceptance criteria. **Generate Test Cases** proposes "
            "one titled test case per acceptance criterion, maps each TC to its AC, and opens a **review** dialog "
            "(merge or replace, edit titles, then apply). **Generate Negative Test Cases** (optional) appends "
            "validation/failure-style titles without removing existing TCs. You can still add empty rows manually below."
        )
        usb._sb_sync_ac_n_from_row_keys()
        n_ac = int(st.session_state.get("sb_n_ac") or 0)
        n_tc = int(st.session_state.get("sb_n_tc") or 0)
        tc_id_options: list[str] = usb._sb_tc_multiselect_options()

        if n_ac > 0:
            st.selectbox(
                "Select acceptance criterion (for manual add only)",
                options=list(range(n_ac)),
                format_func=usb._sb_ac_pick_label,
                key="sb_pick_ac_for_spawn",
            )
            gen1, gen2 = st.columns(2)
            with gen1:
                if st.button(
                    "Generate Test Cases",
                    type="primary",
                    use_container_width=True,
                    key="sb_g_btn_gen_tc_review",
                    help=(
                        "Builds one suggested test case per AC with a title derived from the criterion text, "
                        "pre-mapped on the AC. Review, edit, then merge (gaps only) or replace all."
                    ),
                ):
                    from src.scenario_builder_tc_gen import propose_test_cases_from_acceptance_criteria

                    proposal = propose_test_cases_from_acceptance_criteria(st.session_state)
                    if not proposal:
                        st.warning(
                            "No acceptance criteria with text — go back to **Acceptance criteria** and add criterion text."
                        )
                    else:
                        _clear_tc_generation_dialog_state()
                        st.session_state["_g_tc_gen_proposal"] = proposal
                        _guided_tc_generation_review_dialog()
            with gen2:
                if st.button(
                    "Generate Negative Test Cases",
                    type="secondary",
                    use_container_width=True,
                    key="sb_g_btn_gen_neg_tc_review",
                    help=(
                        "Optional: one failure/validation-style title per AC, **appended** to existing test cases "
                        "(never removes current TCs). Skips titles that duplicate an existing mapped TC on the same AC."
                    ),
                ):
                    from src.scenario_builder_tc_gen import propose_negative_test_cases_from_acceptance_criteria

                    neg_prop = propose_negative_test_cases_from_acceptance_criteria(st.session_state)
                    if not neg_prop:
                        st.warning(
                            "No new negative titles to add — check acceptance criteria text, or mapped TC titles "
                            "may already match the generated negative phrasing for each AC."
                        )
                    else:
                        _clear_neg_tc_generation_dialog_state()
                        st.session_state["_g_neg_tc_gen_proposal"] = neg_prop
                        _guided_negative_tc_generation_review_dialog()
            st.button(
                "Add empty test case linked to selected criterion",
                on_click=usb._sb_spawn_linked_tc,
                type="secondary",
                use_container_width=True,
                key="sb_g_btn_spawn_tc",
            )
        else:
            st.caption("Add acceptance criteria in the previous step first.")

        st.divider()
        st.markdown(
            f"##### Acceptance criteria → test cases (**{n_ac}** criteria; counts stay in sync with your rows)"
        )
        if n_ac <= 0:
            st.warning(
                "No acceptance criteria in session — go back to **Acceptance criteria** and apply or add AC rows."
            )
        else:
            for i in range(n_ac):
                aid = str(st.session_state.get(f"sb_ac_{i}_id") or f"AC-{i + 1:02d}")
                atx = str(st.session_state.get(f"sb_ac_{i}_text") or "").strip().replace("\n", " ")[:160]
                cur_raw = st.session_state.get(f"sb_ac_{i}_map")
                cur_list = (
                    [str(x).strip() for x in cur_raw if x is not None and str(x).strip()]
                    if isinstance(cur_raw, list)
                    else []
                )
                exp = n_ac <= 8 or i < 4
                with st.expander(f"**{aid}** — {atx or '*(no text)*'}", expanded=exp):
                    if tc_id_options:
                        st.multiselect(
                            f"{aid} → mapped test case IDs",
                            options=tc_id_options,
                            key=f"sb_ac_{i}_map",
                            help="Each AC should list the test ids that cover it. **Generate Test Cases** pre-fills one TC per AC (after review).",
                        )
                    else:
                        st.caption(
                            "**Currently mapped:** "
                            + (", ".join(cur_list) if cur_list else "—")
                        )
                        st.info("No test case ids yet — use **Generate Test Cases** above to create one per AC.")

        st.markdown("##### Mapping snapshot")
        snap_rows: list[str] = []
        for i in range(n_ac):
            aid = str(st.session_state.get(f"sb_ac_{i}_id") or f"AC-{i + 1:02d}")
            raw = st.session_state.get(f"sb_ac_{i}_map")
            ids = (
                ", ".join(str(x).strip() for x in raw if isinstance(raw, list) and x is not None and str(x).strip())
                if isinstance(raw, list)
                else "—"
            )
            snap_rows.append(f"- **{aid}** → {ids or '—'}")
        if snap_rows:
            st.markdown("\n".join(snap_rows))
        else:
            st.caption("No rows to show.")

        unmapped = usb._sb_session_unmapped_tc_ids()
        if tc_id_options and unmapped:
            st.info(
                "**Unmapped test case IDs** — link each to at least one AC for a structurally complete scenario "
                "(required before **Approved** in Scenario Review). You can still **save a draft** now: "
                + ", ".join(unmapped)
            )
        elif tc_id_options and n_ac > 0 and not unmapped:
            st.success("Every test case id appears on at least one AC mapping.")

    elif step == 4:
        st.markdown(
            "Author **steps** for each test case, then attach **optional per-step** screenshots as evidence. "
            "**Workflow-level** images are optional on **Changed areas** (step 2). **Generate Test Steps** drafts "
            "numbered steps from each **test case title** (and linked AC text); review, then merge or replace existing "
            "steps. Use **Save step screenshots** below to write evidence to disk before the final step; the catalog "
            "**Save** on the last step also persists any remaining uploads. You can skip screenshots entirely."
        )
        sid_hint = resolve_builder_scenario_id(st.session_state)
        st.caption(f"Evidence files persist under `data/json_upload_media/{sid_hint}/` on **Save**.")
        st.markdown("##### Test cases: steps & evidence")
        st.caption(
            "**Primary path:** use **Paste title & steps together** in each test case (Title: … then numbered steps). "
            "Per-step fields update from the paste box."
        )
        n_tc = int(st.session_state.get("sb_n_tc") or 0)
        if any(usb._sb_tc_row_active(j) for j in range(n_tc)):
            if st.button(
                "Generate Test Steps",
                type="secondary",
                use_container_width=True,
                key="sb_g_btn_gen_steps_review",
                help=(
                    "Builds 3–6 suggested steps per titled test case from the title and linked acceptance criteria. "
                    "Opens a review dialog — merge appends, replace overwrites step text (with confirmation)."
                ),
            ):
                from src.scenario_builder_steps_gen import propose_test_steps_for_all_active_tcs

                prop = propose_test_steps_for_all_active_tcs(st.session_state)
                if not prop:
                    st.warning(
                        "No steps to generate — add **test case titles** on the **Test case generation** step first."
                    )
                else:
                    _clear_steps_gen_dialog_state()
                    st.session_state["_g_steps_gen_proposal"] = prop
                    _guided_steps_generation_review_dialog()
        vis_idx = 0
        for j in range(n_tc):
            if not usb._sb_tc_row_active(j):
                continue
            vis_idx += 1
            kid = f"sb_tc_{j}_id"
            if kid not in st.session_state:
                st.session_state[kid] = f"TC-{vis_idx:02d}"
            with st.expander(f"Test case {vis_idx}", expanded=(vis_idx == 1)):
                ac_lines = usb._sb_linked_ac_lines_for_tc(j)
                if ac_lines:
                    st.caption("Linked ACs: " + "; ".join(ac_lines))
                tid = str(st.session_state.get(kid) or "").strip() or f"TC-{vis_idx:02d}"
                st.caption(f"Test case ID: **{tid}**")
                st.text_area(
                    "Paste title & steps together",
                    key=f"sb_tc_{j}_title_steps_paste",
                    height=100,
                    placeholder="Title: …\n1. …\n2. …",
                    help="Primary authoring path: paste here first; step fields below sync when this text changes.",
                )
                usb._sb_sync_paste_to_step_fields(j)
                st.button(
                    "Delete test case",
                    key=f"sb_g_del_tc_{j}",
                    on_click=usb._sb_delete_tc,
                    args=(j,),
                    type="secondary",
                )
                st.file_uploader(
                    "Bulk step screenshots",
                    type=["png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                    key=tc_bulk_step_upload_widget_key(st.session_state, j),
                    help=(
                        "On **Save**, files map to steps in order: file 1 → Step 1, file 2 → Step 2, … "
                        "(one per step by default). If there are more files than steps, extras continue in the same "
                        "round-robin pattern. Per-step uploaders below can replace or add evidence."
                    ),
                )
                st.text_input(
                    "Title",
                    key=f"sb_tc_{j}_text",
                    placeholder="Short test case name (filled from paste **Title:** line; editable)",
                )
                nk = f"sb_tc_{j}_n_steps"
                if nk not in st.session_state:
                    st.session_state[nk] = 1
                if f"sb_tc_{j}_steps_bulk" not in st.session_state:
                    st.session_state[f"sb_tc_{j}_steps_bulk"] = "1. "
                n_from_state = max(int(st.session_state.get(nk) or 1), 1)
                _tt, steps_eff = tc_title_text_and_steps_from_session(st.session_state, j)
                n_st = max(n_from_state, len(steps_eff) if steps_eff else 0, 1)
                bulk_key = tc_bulk_step_upload_widget_key(st.session_state, j)
                braw = st.session_state.get(bulk_key)
                bulk_files: list = []
                if isinstance(braw, list):
                    bulk_files = [x for x in braw if x is not None and hasattr(x, "read")]
                elif braw is not None and hasattr(braw, "read"):
                    bulk_files = [braw]
                for k in range(n_st):
                    st.markdown(f"**Step {k + 1}**")
                    st.text_input(
                        f"Step {k + 1} — test step text",
                        key=f"sb_tc_{j}_step_{k}_text",
                        placeholder=f"Describe step {k + 1}…",
                    )
                    if bulk_files:
                        for mi in bulk_upload_file_indices_for_step(k, n_st, len(bulk_files)):
                            fn = getattr(bulk_files[mi], "name", None) or f"upload_{mi + 1}"
                            st.info(
                                f"**Bulk screenshot for Step {k + 1}** — file **{mi + 1} of {len(bulk_files)}** "
                                f"in the bulk picker: `{fn}`. This step receives that file when you **Save** the scenario."
                            )
                    plist = st.session_state.get(f"sb_tc_{j}_step_{k}_persisted_paths")
                    singles: list[str] = []
                    if isinstance(plist, list):
                        singles = [str(x).strip() for x in plist if str(x).strip()]
                    else:
                        pp0 = str(st.session_state.get(f"sb_tc_{j}_step_{k}_persisted_path") or "").strip()
                        if pp0:
                            singles = [pp0]
                    if singles:
                        st.caption(f"Saved files for step {k + 1}:")
                    for si, pp in enumerate(singles):
                        c1b, c2b = st.columns([4, 1])
                        with c1b:
                            st.caption(f"· **{Path(pp).name}**")
                        with c2b:
                            st.button(
                                "Remove",
                                key=f"sb_g_rm_step_shot_{j}_{k}_{si}",
                                on_click=usb._sb_remove_step_shot_at,
                                args=(j, k, si),
                                type="secondary",
                            )
                    st.file_uploader(
                        f"Add screenshot(s) for step {k + 1} (.png, .jpg, .jpeg)",
                        type=["png", "jpg", "jpeg"],
                        accept_multiple_files=True,
                        key=tc_step_upload_widget_key(st.session_state, j, k),
                    )
                    st.button(
                        f"Clear all saved screenshots & upload for step {k + 1}",
                        key=f"sb_g_rm_step_{j}_{k}",
                        on_click=usb._sb_clear_step_persisted_and_upload,
                        args=(j, k),
                        type="secondary",
                    )
                st.text_area("Tester notes (optional)", key=f"sb_tc_{j}_notes", height=56)
        if vis_idx == 0:
            st.info("No test cases — go back to **Test case generation** to add some.")
        else:
            st.divider()
            if st.button(
                "Save step screenshots",
                type="primary",
                use_container_width=True,
                key="sb_g_save_step_shots",
                help="Writes bulk and per-step uploads to your scenario media folder and refreshes saved paths in this draft.",
            ):
                usb._sb_commit_guided_test_step_screenshots()
                st.rerun()
            st.caption(
                "Writes bulk and per-step uploads the same way as catalog **Save** (workflow-level files are handled "
                "when you leave **Changed areas** or on full **Save**). After saving, paths show under each step; you can "
                "still replace or remove files before the final save. Leaving this step (**Next** / **Back**) also flushes "
                "uploads so nothing is lost before **Save to catalog**."
            )

    else:  # step 5 — final review
        st.markdown(
            "Confirm titles, coverage, and notes below. New screenshot paths are finalized when you **Save**."
        )
        n_tc_pre = int(st.session_state.get("sb_n_tc") or 0)
        for j in range(n_tc_pre):
            if usb._sb_tc_row_active(j):
                usb._sb_sync_paste_to_step_fields(j)
        usb._sb_backfill_empty_from_guided_snapshot()
        try:
            preview = read_flat_builder_session(st.session_state)
        except Exception as ex:
            st.error(f"Could not build preview: {ex}")
            preview = None
        if not isinstance(preview, dict):
            st.markdown("---")
            st.markdown("##### Suggested fixes")
            st.info("No suggested fixes at this time.")
        if isinstance(preview, dict):
            scn_title = (
                str(preview.get("scenario_title") or "").strip()
                or str(preview.get("story_title") or "").strip()
                or "—"
            )
            st.markdown(f"**Scenario title:** {scn_title}")
            sctx = str(preview.get("scenario_context") or "").strip()
            if sctx:
                st.markdown(f"**Scenario context:** {sctx[:420]}{'…' if len(sctx) > 420 else ''}")
            st.markdown(f"**Workflow:** {(preview.get('workflow_name') or '—')}")
            st.markdown(f"**Business goal:** {(preview.get('business_goal') or '—')}")
            sid = (preview.get("scenario_id") or "").strip() or "—"
            st.markdown(f"**Scenario ID (on save):** `{sid}`")
            acs = preview.get("acceptance_criteria") or []
            tcs = preview.get("test_cases") or []
            st.markdown("---")
            n_ac_list = len(acs) if isinstance(acs, list) else 0
            n_tc_list = len(tcs) if isinstance(tcs, list) else 0
            with st.expander(
                f"Acceptance criteria ({n_ac_list})",
                expanded=isinstance(acs, list) and n_ac_list <= _FINAL_REVIEW_COLLAPSE_THRESHOLD,
            ):
                if isinstance(acs, list) and acs:
                    for ac in acs:
                        if not isinstance(ac, dict):
                            continue
                        aid = str(ac.get("id") or "—")
                        atx = str(ac.get("text") or "").strip().replace("\n", " ")[:280]
                        raw_ids = ac.get("test_case_ids") or []
                        ids = ", ".join(str(x) for x in raw_ids if x is not None and str(x).strip()) or "—"
                        st.markdown(f"- **{aid}** — {atx or '—'}  \n  *Mapped tests:* {ids}")
                else:
                    st.caption("No acceptance criteria yet.")
            with st.expander(
                f"Test cases ({n_tc_list})",
                expanded=isinstance(tcs, list) and n_tc_list <= _FINAL_REVIEW_COLLAPSE_THRESHOLD,
            ):
                if isinstance(tcs, list) and tcs:
                    for tc in tcs:
                        if not isinstance(tc, dict):
                            continue
                        tid = str(tc.get("id") or "—")
                        ttx = resolved_test_case_title(tc) or "—"
                        steps = tc.get("steps") or []
                        n_steps = len(steps) if isinstance(steps, list) else 0
                        ac_lines = format_tc_ac_link_lines(acs if isinstance(acs, list) else [], tid)
                        ac_disp = "; ".join(ac_lines) if ac_lines else "*(not linked on any AC)*"
                        st.markdown(f"- **{tid}** — {ttx}  \n  *Steps:* {n_steps}  \n  *AC links:* {ac_disp}")
                else:
                    st.caption("No test cases yet.")
            um = unmapped_test_case_ids(preview)
            if um:
                st.info(
                    "**Unmapped test case ids** — required before **Approved** in Scenario Review; optional before save: "
                    + ", ".join(um)
                )
            else:
                if isinstance(tcs, list) and tcs:
                    st.success("Every test case appears on at least one acceptance criterion.")

            try:
                trace_mat = generate_traceability_matrix(preview)
            except Exception:
                trace_mat = []
            try:
                gap_rows = generate_coverage_gaps(preview, traceability_rows=trace_mat)
            except Exception:
                gap_rows = []
            try:
                rf = generate_reviewer_focus(preview)
            except Exception:
                rf = get_placeholder_reviewer_focus(preview)
            if not isinstance(rf, dict):
                rf = get_placeholder_reviewer_focus(preview)

            st.markdown("---")
            st.markdown("##### Coverage gaps")
            st.caption("Heuristic coverage signals (same pipeline as Scenario Review).")
            if gap_rows:
                _render_coverage_gaps_by_ac(gap_rows, show_suggested_action=False)
            else:
                st.info("No automated coverage gaps flagged for this draft.")

            st.markdown("##### Risk flags")
            st.caption("Failure-mode hints from reviewer-focus rules (not a pass/fail gate).")
            risky = rf.get("risky") or []
            if isinstance(risky, list) and any(str(x or "").strip() for x in risky):
                for line in risky:
                    t = str(line or "").strip()
                    if t:
                        st.write(f"- {t}")
            else:
                st.info("No risk flags from the current reviewer-focus pass.")

            st.markdown("##### Suggested fixes")
            st.caption("Actions from coverage gaps plus possible gaps; risks add validation hints when fixes are thin.")
            fix_lines = merge_suggested_fixes(
                collect_gap_suggested_actions(gap_rows),
                rf.get("may_be_missing") or [],
            )
            try:
                from src.scenario_domain_labels import enrich_suggested_fix_lines

                if isinstance(preview, dict):
                    fix_lines = enrich_suggested_fix_lines(fix_lines, preview)
            except Exception:  # noqa: BLE001
                pass
            has_signal = bool(gap_rows) or bool(
                [x for x in (rf.get("risky") or []) if isinstance(x, str) and x.strip()]
            )
            if not fix_lines and has_signal:
                risk_hints = [
                    f"Plan validation for: {str(x).strip()}"
                    for x in (rf.get("risky") or [])
                    if isinstance(x, str) and str(x).strip()
                ]
                fix_lines = merge_suggested_fixes(fix_lines, risk_hints)
            if fix_lines:
                for line in fix_lines:
                    st.write(f"- {line}")
            else:
                st.info("No suggested fixes at this time.")

        st.text_area("Scenario notes (optional)", key="sb_notes", height=64)

        st.markdown("##### Export for execution")
        try:
            export_flat = read_flat_builder_session(st.session_state, include_export_hints=True)
        except Exception as ex:
            export_flat = None
            st.caption(f"Could not prepare export data: {ex}")
        if isinstance(export_flat, dict):
            try:
                ex_doc = build_execution_draft_export_docx(data=export_flat)
                ex_name = safe_execution_draft_filename(export_flat)
            except Exception as ex:
                ex_doc = b""
                ex_name = "scenario_execution_draft.docx"
                st.caption(f"Execution draft export unavailable: {ex}")
            else:
                st.caption(
                    "Export the current scenario as a draft test script for execution. "
                    "Review approval is not required."
                )
                st.download_button(
                    "Export Execution Draft (DOCX)",
                    data=ex_doc,
                    file_name=ex_name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key="sb_g_export_execution_draft_docx",
                    type="secondary",
                )

        st.markdown("##### Jump to another step")
        st.caption(
            "Moving between steps only changes which form you see — your data stays in the draft. "
            "Use **Back** / **Next** in the footer, or jump here."
        )
        st.session_state.setdefault("sb_g_jump_step_select", step)
        jcol1, jcol2 = st.columns([3, 1])
        with jcol1:
            jump_ix = st.selectbox(
                "Step",
                options=list(range(_N_GUIDED_STEPS)),
                format_func=lambda i: f"{i + 1}. {_STEP_TITLES[i]}",
                key="sb_g_jump_step_select",
                label_visibility="collapsed",
            )
        with jcol2:
            if st.button("Go", key="sb_g_jump_go"):
                st.session_state[_GUIDED_STEP_KEY] = int(jump_ix)
                st.rerun()

        r1, r2, r3 = st.columns(3)
        with r1:
            st.button("Reset builder", on_click=_guided_reset_all, type="secondary", key="sb_g_reset")
        with r2:
            if st.button("Polish all test steps…", key="sb_g_polish_final"):
                p_status, p_updates, p_lines, _p_rows = usb._sb_preview_polish_test_steps()
                if p_status == "no_api_key":
                    st.warning(
                        "**Polish needs an OpenAI API key.** Set the `OPENAI_API_KEY` environment variable "
                        "for the Streamlit process, then try again."
                    )
                elif p_status == "no_step_content":
                    st.warning(
                        "**No test step wording to polish.** Add numbered steps (in **Paste title & steps together**, "
                        "per-step fields, or multiline steps) for at least one test case, then try again."
                    )
                elif p_status == "no_changes":
                    st.info(
                        "**No wording changes to preview.** Either the model returned identical text, or there was "
                        "nothing to refine."
                    )
                elif p_status == "api_error":
                    st.warning(
                        "**Polish could not run** — the OpenAI call failed or returned an unexpected response. "
                        "Check your API key, network, and quota, then try again."
                    )
                elif p_status == "ok" and p_updates and (p_lines or _p_rows):
                    st.session_state["_g_polish_dialog_updates"] = p_updates
                    st.session_state["_g_polish_dialog_lines"] = p_lines
                    _guided_polish_review_dialog()
                else:
                    st.warning("Polish could not prepare a preview. Try again after editing step text.")
        with r3:
            do_save = st.button("Save to catalog", type="primary", key="sb_g_save")

        if do_save:
            try:
                usb._sb_renumber_sequential_tc_ids()
                data, shot_replaced = usb._build_scenario_with_uploads()
                if shot_replaced:
                    st.session_state[usb._SB_FLASH_SHOT_REPLACED] = "Existing screenshot replaced."
                sid = str(data.get("scenario_id") or "").strip()
                existing = {r["id"] for r in load_registry_saved()}
                if sid in existing:
                    st.warning(
                        f"A saved scenario with id **{sid}** already exists — saving will **overwrite** that JSON file."
                    )
                fname = f"{sid}.json"
                persist_imported_json_scenario(data, fname)
                sync_builder_persisted_media_from_data(st.session_state, data)
                st.session_state.pop("sb_wf_upload", None)
                st.session_state[pending_select_key] = sid
                st.session_state[usb._SB_FLASH_SAVE_SUCCESS] = sid
                st.rerun()
            except ValueError as e:
                st.session_state[usb._SB_FLASH_SAVE_ERROR] = str(e)
                st.rerun()
            except Exception as e:
                st.session_state[usb._SB_FLASH_SAVE_ERROR] = f"Save failed: {e}"
                st.rerun()

    # --- Navigation ---
    st.divider()
    n1, n2 = st.columns([1, 1])
    with n1:
        if st.button("← Back", disabled=step <= 0, key=f"sb_g_back_{step}"):
            # Guided steps unmount file uploaders; flush evidence before leaving.
            if step == 1:
                usb._sb_persist_guided_workflow_uploads_only()
            if step == 4:
                usb._sb_persist_guided_step4_media(flash_message=False)
            st.session_state[_GUIDED_STEP_KEY] = step - 1
            st.rerun()
    with n2:
        if st.button("Next →", disabled=step >= _N_GUIDED_STEPS - 1, key=f"sb_g_next_{step}"):
            if step == 1:
                usb._sb_persist_guided_workflow_uploads_only()
            if step == 4:
                usb._sb_persist_guided_step4_media(flash_message=False)
            st.session_state[_GUIDED_STEP_KEY] = step + 1
            st.rerun()

    usb._sb_update_guided_snapshot_from_session(guided_step=step)

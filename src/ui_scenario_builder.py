"""
AI Scenario Builder: guided forms → schema-shaped JSON → save via registry.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from src.intake_parser import load_scenario
from src.scenario_builder_ai import polish_parallel_texts
from src.scenario_builder_core import (
    _bucket_step_paths_from_raw,
    apply_guided_snapshot_backfill,
    assign_ac_ids_for_bulk_rows,
    hydrate_builder_session_from_scenario,
    parse_acceptance_criteria_bulk_lines,
    parse_steps_bulk,
    parse_test_case_title_and_steps_bulk,
    read_flat_builder_session,
    resolve_builder_scenario_id,
    sync_builder_persisted_media_from_data,
    tc_title_text_and_steps_from_session,
    unmapped_test_case_ids,
    write_step_paths_to_session,
)
from src.scenario_media import expected_step_screenshot_paths, step_texts
from src.scenario_builder_media import (
    bulk_upload_file_indices_for_step,
    bump_upload_widget_epoch,
    clear_tc_step_file_uploader_session_keys,
    persist_bulk_tc_step_screenshot_uploads,
    persist_step_screenshot_uploads,
    persist_workflow_screenshot_uploads,
    tc_bulk_step_upload_widget_key,
    tc_step_upload_widget_key,
)
from src.scenario_registry import load_registry_saved, persist_imported_json_scenario

# Guided vs Classic shell (``render_scenario_builder_page``). New / reset → Guided; registry Edit → Classic.
BUILDER_LAYOUT_MODE_KEY = "_builder_layout_mode"
BUILDER_LAYOUT_GUIDED = "Guided step-by-step"
BUILDER_LAYOUT_CLASSIC = "Classic (all sections)"

_SB_LOAD_REGISTRY_ID_KEY = "_sb_load_registry_id"
_SB_BUILDER_LOAD_ERROR_KEY = "_sb_builder_load_error"
_SB_FLASH_SAVE_SUCCESS = "_sb_flash_save_success_sid"
_SB_FLASH_SAVE_ERROR = "_sb_flash_save_error_msg"
_SB_FLASH_SHOT_REPLACED = "_sb_flash_screenshot_replaced_msg"
_SB_FLASH_GUIDED_STEP_SHOTS_SAVED = "_sb_flash_guided_step_shots_saved_msg"
_SB_GUIDED_SNAPSHOT_KEY = "_sb_guided_last_sb_snapshot"
# 0-based guided index for the step that renders AC ↔ TC multiselects ("Test case generation").
_SB_GUIDED_STEP_AC_TC_MAP = 3
# One-shot: guided “Test steps & screenshots” step expands this builder slot index (``sb_tc_{j}_*``).
SB_GUIDED_FOCUS_TC_SLOT = "_sb_guided_focus_tc_slot"
_SB_AC_MAP_SESSION_KEY = re.compile(r"^sb_ac_\d+_map$")


def _one_line_snip(s: str, lim: int = 140) -> str:
    t = " ".join((s or "").split())
    return (t[: lim - 1] + "…") if len(t) > lim else t


def _sb_ac_map_session_nonempty(val: Any) -> bool:
    """True when ``sb_ac_*_map`` session value lists at least one non-empty test case id."""
    if not isinstance(val, list):
        return False
    return any(str(x).strip() for x in val if x is not None)


def _sb_skip_key_for_guided_snapshot(k: str) -> bool:
    if not isinstance(k, str) or not k.startswith("sb_"):
        return True
    # Guided-mode widget keys (``sb_g_*``) are not scenario data; restoring them would write
    # Streamlit button/select state and raises StreamlitValueAssignmentNotAllowedError.
    if k.startswith("sb_g_"):
        return True
    if k == "sb_wf_upload":
        return True
    if "_file_e" in k:
        return True
    return False


def _sb_restore_missing_from_guided_snapshot() -> None:
    """
    Restore ``sb_*`` keys Streamlit may drop when widgets unmount (guided step navigation).

    Multiselect ``sb_ac_{i}_map`` often remains in session as ``[]`` after unmount; merge that
    with the snapshot when the snapshot still holds the user's selections.
    """
    snap = st.session_state.get(_SB_GUIDED_SNAPSHOT_KEY)
    if not isinstance(snap, dict):
        return
    for k, v in snap.items():
        if _sb_skip_key_for_guided_snapshot(k):
            continue
        if isinstance(k, str) and _SB_AC_MAP_SESSION_KEY.match(k):
            if _sb_ac_map_session_nonempty(v) and not _sb_ac_map_session_nonempty(st.session_state.get(k)):
                try:
                    st.session_state[k] = copy.deepcopy(v)
                except Exception:
                    st.session_state[k] = v
            continue
        if k not in st.session_state:
            try:
                st.session_state[k] = copy.deepcopy(v)
            except Exception:
                st.session_state[k] = v


def _sb_update_guided_snapshot_from_session(*, guided_step: int | None = None) -> None:
    """
    Merge builder fields into a snapshot (excluding file-upload widget blobs).

    Starts from the previous snapshot so keys Streamlit temporarily removes from
    ``st.session_state`` are not lost before :func:`_sb_restore_missing_from_guided_snapshot`
    runs on the next script execution.
    """
    prev = st.session_state.get(_SB_GUIDED_SNAPSHOT_KEY)
    cur: dict[str, Any] = copy.deepcopy(prev) if isinstance(prev, dict) else {}
    for k in list(st.session_state.keys()):
        if _sb_skip_key_for_guided_snapshot(k):
            continue
        if not isinstance(k, str) or not k.startswith("sb_"):
            continue
        if (
            guided_step is not None
            and guided_step != _SB_GUIDED_STEP_AC_TC_MAP
            and _SB_AC_MAP_SESSION_KEY.match(k)
            and not _sb_ac_map_session_nonempty(st.session_state[k])
            and _sb_ac_map_session_nonempty(cur.get(k))
        ):
            continue
        try:
            cur[k] = copy.deepcopy(st.session_state[k])
        except Exception:
            cur[k] = st.session_state[k]
    for k in list(cur.keys()):
        if isinstance(k, str) and k.startswith("sb_g_"):
            cur.pop(k, None)
    st.session_state[_SB_GUIDED_SNAPSHOT_KEY] = cur


def _sb_backfill_empty_from_guided_snapshot() -> None:
    """Republish core ``sb_*`` fields from the guided snapshot when session holds only blanks."""
    apply_guided_snapshot_backfill(st.session_state, st.session_state.get(_SB_GUIDED_SNAPSHOT_KEY))


def _sb_sync_paste_to_step_fields(j: int) -> None:
    """When paste text changes, parse and populate per-step keys + title (does not run if digest unchanged)."""
    paste = str(st.session_state.get(f"sb_tc_{j}_title_steps_paste") or "")
    dkey = f"sb_tc_{j}_paste_digest"
    if not paste.strip():
        st.session_state.pop(dkey, None)
        return
    digest = hashlib.sha256(paste.encode("utf-8")).hexdigest()
    if st.session_state.get(dkey) == digest:
        return
    p_title, steps = parse_test_case_title_and_steps_bulk(paste)
    if not steps:
        steps = [""]
    st.session_state[f"sb_tc_{j}_text"] = p_title
    ns = max(len(steps), 1)
    st.session_state[f"sb_tc_{j}_n_steps"] = ns
    for k in range(64):
        st.session_state.pop(f"sb_tc_{j}_step_{k}_text", None)
    for k, s in enumerate(steps):
        st.session_state[f"sb_tc_{j}_step_{k}_text"] = str(s) if s is not None else ""
    st.session_state[dkey] = digest


def _sb_tc_has_substantive_steps(j: int) -> bool:
    """True when this TC slot has at least one non-empty step from structured fields, paste, or bulk."""
    _tt, steps = tc_title_text_and_steps_from_session(st.session_state, j)
    return any(str(s).strip() for s in steps)


def _sb_set_tc_steps_programmatically(j: int, steps: list[str]) -> None:
    """
    Write per-step text, ``steps_bulk``, and ``title_steps_paste`` for slot ``j``.

    Preserves ``sb_tc_{j}_id`` and ``sb_tc_{j}_text`` (title). Clears persisted screenshot keys only for
    step indices at or above the new step count so retained steps keep evidence.
    """
    title = str(st.session_state.get(f"sb_tc_{j}_text") or "").strip()
    _pt, _ = tc_title_text_and_steps_from_session(st.session_state, j)
    if not title and _pt:
        title = str(_pt).strip()
    clean = [re.sub(r"\s+", " ", str(s)).strip() for s in steps if str(s).strip()]
    if not clean:
        clean = ["Document the observed outcome."]
    clean = clean[:20]
    ns = len(clean)
    bulk = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(clean))
    st.session_state[f"sb_tc_{j}_n_steps"] = ns
    st.session_state[f"sb_tc_{j}_steps_bulk"] = bulk
    for k in range(64):
        st.session_state.pop(f"sb_tc_{j}_step_{k}_text", None)
    for k, line in enumerate(clean):
        st.session_state[f"sb_tc_{j}_step_{k}_text"] = line
    for k in range(ns, 64):
        st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)
        st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)
    paste_lines = [f"Title: {title}"] if title else []
    paste_lines.extend(f"{i + 1}. {line}" for i, line in enumerate(clean))
    paste = "\n".join(paste_lines)
    st.session_state[f"sb_tc_{j}_title_steps_paste"] = paste
    st.session_state[f"sb_tc_{j}_paste_digest"] = hashlib.sha256(paste.encode("utf-8")).hexdigest()


def _sb_linked_ac_lines_for_tc(j: int) -> list[str]:
    """All ACs whose multiselect lists this test case id (builder session)."""
    _sb_sync_ac_n_from_row_keys()
    tid = str(st.session_state.get(f"sb_tc_{j}_id") or "").strip()
    if not tid:
        return []
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    lines: list[str] = []
    for i in range(n_ac):
        raw = st.session_state.get(f"sb_ac_{i}_map") or []
        if not isinstance(raw, list):
            continue
        ids = {str(x).strip() for x in raw if x is not None and str(x).strip()}
        if tid not in ids:
            continue
        aid = str(st.session_state.get(f"sb_ac_{i}_id") or f"AC-{i + 1}")
        atx = str(st.session_state.get(f"sb_ac_{i}_text") or "").strip().replace("\n", " ")[:220]
        lines.append(f"**{aid}**" + (f" — {atx}" if atx else ""))
    return lines


def _sb_recompute_all_linked_ac_hints() -> None:
    """Refresh optional ``linked_ac`` hint (lowest AC index) after AC list changes; display uses maps."""
    _sb_sync_ac_n_from_row_keys()
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    for j in range(n_tc):
        if not _sb_tc_row_active(j):
            continue
        tid = str(st.session_state.get(f"sb_tc_{j}_id") or "").strip()
        if not tid:
            st.session_state.pop(f"sb_tc_{j}_linked_ac", None)
            continue
        n_ac = int(st.session_state.get("sb_n_ac") or 0)
        found: int | None = None
        for i in range(n_ac):
            raw = st.session_state.get(f"sb_ac_{i}_map") or []
            if not isinstance(raw, list):
                continue
            if any(str(x).strip() == tid for x in raw if x is not None):
                found = i
                break
        if found is not None:
            st.session_state[f"sb_tc_{j}_linked_ac"] = found
        else:
            st.session_state.pop(f"sb_tc_{j}_linked_ac", None)


def _sb_clear_wf_persisted_at(idx: int) -> None:
    lst = st.session_state.get("sb_wf_persisted_paths")
    if not isinstance(lst, list) or idx < 0 or idx >= len(lst):
        return
    old_n = len(lst)
    new_lst = [x for i, x in enumerate(lst) if i != idx]
    st.session_state["sb_wf_persisted_paths"] = new_lst
    for i in range(len(new_lst)):
        src = i if i < idx else i + 1
        lb = st.session_state.get(f"sb_wf_lbl_{src}")
        if str(lb or "").strip():
            st.session_state[f"sb_wf_lbl_{i}"] = str(lb).strip()
        else:
            st.session_state.pop(f"sb_wf_lbl_{i}", None)
    for i in range(len(new_lst), old_n + 8):
        st.session_state.pop(f"sb_wf_lbl_{i}", None)


def _sb_clear_wf_upload_widget() -> None:
    st.session_state.pop("sb_wf_upload", None)


def _sb_clear_step_persisted_and_upload(j: int, k: int) -> None:
    st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)
    st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)
    clear_tc_step_file_uploader_session_keys(st.session_state, j, k)


def _sb_remove_step_shot_at(j: int, k: int, shot_i: int) -> None:
    """Remove one persisted path from a step's multi-screenshot list."""
    key = f"sb_tc_{j}_step_{k}_persisted_paths"
    lst = st.session_state.get(key)
    if isinstance(lst, list) and 0 <= shot_i < len(lst):
        st.session_state[key] = [x for i, x in enumerate(lst) if i != shot_i]
        if not st.session_state[key]:
            st.session_state.pop(key, None)
        return
    st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)


def queue_builder_load_from_registry(registry_id: str) -> None:
    """Switch to builder on next run with this saved scenario loaded for editing."""
    st.session_state[_SB_LOAD_REGISTRY_ID_KEY] = str(registry_id or "").strip()


def _maybe_consume_pending_builder_load() -> None:
    rid = st.session_state.pop(_SB_LOAD_REGISTRY_ID_KEY, None)
    if not rid:
        return
    row = next((r for r in load_registry_saved() if r.get("id") == rid), None)
    if not row:
        st.session_state[_SB_BUILDER_LOAD_ERROR_KEY] = f"Unknown scenario id `{rid}`."
        return
    path = str(row.get("path") or "").strip()
    if not path:
        st.session_state[_SB_BUILDER_LOAD_ERROR_KEY] = f"No file path for `{rid}`."
        return
    try:
        data = load_scenario(path)
    except Exception as ex:
        st.session_state[_SB_BUILDER_LOAD_ERROR_KEY] = f"Could not load scenario for edit: {ex}"
        return
    _reset_builder_form()
    hydrate_builder_session_from_scenario(
        st.session_state, data, editing_registry_id=rid
    )
    # Scenario Management → Open in builder: prefer Classic for full-form maintenance editing.
    st.session_state[BUILDER_LAYOUT_MODE_KEY] = BUILDER_LAYOUT_CLASSIC


def _sb_apply_polish_step_updates(updates: Mapping[str, Any]) -> None:
    """
    Apply deferred test-step polish keys only.

    Refreshes ``sb_tc_*`` fields derived from ``*_title_steps_paste`` via sync so titles and
    step widgets stay aligned; does not touch AC maps, ids, notes, or screenshot paths.
    """
    if not isinstance(updates, dict):
        return
    paste_slots: set[int] = set()
    for k, v in updates.items():
        st.session_state[k] = v
        if isinstance(k, str) and k.startswith("sb_tc_") and k.endswith("_title_steps_paste"):
            parts = k.split("_")
            if len(parts) >= 4 and parts[0] == "sb" and parts[1] == "tc":
                try:
                    paste_slots.add(int(parts[2]))
                except ValueError:
                    pass
    for jj in sorted(paste_slots):
        st.session_state.pop(f"sb_tc_{jj}_paste_digest", None)
        _sb_sync_paste_to_step_fields(jj)


def _drain_builder_polish_queues() -> None:
    """Apply deferred text updates before widgets bind (avoids mutating widget keys mid-run)."""
    bulk_polish = st.session_state.pop("_sb_g_ac_bulk_polish_pending", None)
    if isinstance(bulk_polish, str):
        st.session_state["sb_ac_bulk_text"] = bulk_polish
    ac = st.session_state.pop("_sb_polish_ac_text_updates", None)
    if isinstance(ac, dict):
        for k, v in ac.items():
            st.session_state[k] = v
    stu = st.session_state.pop("_sb_polish_step_text_updates", None)
    if isinstance(stu, dict):
        _sb_apply_polish_step_updates(stu)


def _reset_builder_form() -> None:
    for k in list(st.session_state.keys()):
        if (
            k.startswith("sb_")
            or k.startswith("_sb_polish")
            or k.startswith("_g_polish")
            or k == "_sb_g_ac_bulk_polish_pending"
        ):
            del st.session_state[k]
    st.session_state.pop(_SB_GUIDED_SNAPSHOT_KEY, None)
    st.session_state.pop(_SB_FLASH_GUIDED_STEP_SHOTS_SAVED, None)
    st.session_state.pop(SB_GUIDED_FOCUS_TC_SLOT, None)


def _sb_consolidate_legacy_story_description_into_context() -> None:
    """Legacy ``sb_story_description`` (removed from UI) folds into ``sb_scenario_context`` when context was empty."""
    legacy = st.session_state.pop("sb_story_description", None)
    leg = str(legacy).strip() if legacy is not None else ""
    sc = str(st.session_state.get("sb_scenario_context") or "").strip()
    if leg and not sc:
        st.session_state["sb_scenario_context"] = leg


def _sb_init_defaults() -> None:
    st.session_state.setdefault("sb_auto_id", True)
    st.session_state.setdefault("sb_story_title", "")
    st.session_state.setdefault("sb_scenario_id", "")
    st.session_state.setdefault("sb_scenario_context", "")
    st.session_state.setdefault("sb_workflow_name", "")
    st.session_state.setdefault("sb_business_goal", "")
    st.session_state.setdefault("sb_notes", "")
    st.session_state.setdefault("sb_n_ac", 1)
    st.session_state.setdefault("sb_n_tc", 0)
    st.session_state.setdefault("sb_n_ca", 0)
    st.session_state.setdefault("sb_n_dep", 0)
    st.session_state.setdefault("sb_pick_ac_for_spawn", 0)
    st.session_state.setdefault("sb_changed_areas_bulk", "")
    st.session_state.setdefault("sb_known_dependencies_bulk", "")
    st.session_state.setdefault("sb_upload_widget_epoch", 0)
    st.session_state.setdefault("sb_ac_bulk_text", "")
    st.session_state.setdefault("_guided_builder_step", 0)


def _sb_ac_pick_label(i: int) -> str:
    aid = str(st.session_state.get(f"sb_ac_{i}_id") or f"AC-{i + 1}")
    tx = (st.session_state.get(f"sb_ac_{i}_text") or "").strip().replace("\n", " ")[:60]
    return f"{aid} — {tx}" if tx else aid


def _sb_clear_tc_slot(j: int) -> None:
    prefix = f"sb_tc_{j}_"
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(prefix):
            del st.session_state[k]


def _sb_snapshot_tc_row(j: int) -> dict:
    ttitle, stexts = tc_title_text_and_steps_from_session(st.session_state, j)
    if not stexts:
        stexts = [""]
    n_st = len(stexts)
    bulk = "\n".join(
        f"{k + 1}. {t}" for k, t in enumerate(stexts) if str(t).strip()
    )
    if not bulk.strip() and stexts:
        bulk = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(stexts))
    tid = str(st.session_state.get(f"sb_tc_{j}_id") or "").strip() or f"TC-{j + 1:02d}"
    path_lists: list[list[str]] = []
    for k in range(n_st):
        plist = st.session_state.get(f"sb_tc_{j}_step_{k}_persisted_paths")
        if isinstance(plist, list):
            path_lists.append([str(x).strip() for x in plist if str(x).strip()])
        else:
            p = str(st.session_state.get(f"sb_tc_{j}_step_{k}_persisted_path") or "").strip()
            path_lists.append([p] if p else [])
    return {
        "tid": tid,
        "text": ttitle,
        "n_steps": n_st,
        "linked_ac": st.session_state.get(f"sb_tc_{j}_linked_ac"),
        "steps_bulk": bulk,
        "step_texts": stexts,
        "step_path_lists": path_lists,
        "notes": str(st.session_state.get(f"sb_tc_{j}_notes") or ""),
    }


def _sb_restore_tc_row(i: int, row: dict, *, new_tid: str) -> None:
    st.session_state[f"sb_tc_{i}_id"] = new_tid
    st.session_state[f"sb_tc_{i}_text"] = row.get("text", "")
    st.session_state[f"sb_tc_{i}_notes"] = str(row.get("notes") or "")
    st.session_state.pop(f"sb_tc_{i}_title_steps_paste", None)
    st.session_state[f"sb_tc_{i}_active"] = True
    la = row.get("linked_ac")
    if la is not None and isinstance(la, int):
        st.session_state[f"sb_tc_{i}_linked_ac"] = la
    else:
        st.session_state.pop(f"sb_tc_{i}_linked_ac", None)
    stexts = [str(x) for x in (row.get("step_texts") or [])]
    if not stexts:
        bulk = str(row.get("steps_bulk") or "")
        if bulk.strip():
            stexts = parse_steps_bulk(bulk)
    if not stexts:
        stexts = [""]
    n_st = max(len(stexts), int(row.get("n_steps") or 0) or 0, 1)
    st.session_state[f"sb_tc_{i}_n_steps"] = n_st
    st.session_state[f"sb_tc_{i}_steps_bulk"] = "\n".join(
        f"{k + 1}. {t}" for k, t in enumerate(stexts) if str(t).strip()
    )
    if not st.session_state[f"sb_tc_{i}_steps_bulk"].strip():
        st.session_state[f"sb_tc_{i}_steps_bulk"] = "\n".join(
            f"{k + 1}. {t}" for k, t in enumerate(stexts)
        )
    for k in range(64):
        st.session_state.pop(f"sb_tc_{i}_step_{k}_text", None)
    for k, t in enumerate(stexts):
        st.session_state[f"sb_tc_{i}_step_{k}_text"] = t
    st.session_state.pop(f"sb_tc_{i}_paste_digest", None)
    path_lists = row.get("step_path_lists")
    if not isinstance(path_lists, list):
        path_lists = []
        legacy = row.get("step_pers") or []
        for k in range(n_st):
            pv = legacy[k] if k < len(legacy) else ""
            path_lists.append([str(pv).strip()] if str(pv).strip() else [])
    for k in range(65):
        st.session_state.pop(f"sb_tc_{i}_step_{k}_persisted_path", None)
        st.session_state.pop(f"sb_tc_{i}_step_{k}_persisted_paths", None)
    for k in range(len(path_lists)):
        lst = [x for x in path_lists[k] if str(x).strip()]
        if len(lst) == 1:
            st.session_state[f"sb_tc_{i}_step_{k}_persisted_path"] = lst[0]
        elif lst:
            st.session_state[f"sb_tc_{i}_step_{k}_persisted_paths"] = lst


def _sb_remap_ac_tid_list(
    cur: list[str], old_tids: list[str], new_tids: list[str], valid: set[str]
) -> list[str]:
    nxt: list[str] = []
    for x in cur:
        nx = x
        for i, o in enumerate(old_tids):
            if x == o:
                nx = new_tids[i]
                break
        if nx in valid and nx not in nxt:
            nxt.append(nx)
    return nxt


def _sb_renumber_sequential_tc_ids() -> None:
    """Assign TC-01..TC-n in active order and remap AC multiselects (does not clear step/upload keys)."""
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    active_js = [j for j in range(n_tc) if _sb_tc_row_active(j)]
    old_tids = [
        str(st.session_state.get(f"sb_tc_{j}_id") or "").strip() or f"TC-{j + 1:02d}"
        for j in active_js
    ]
    new_tids = [f"TC-{i + 1:02d}" for i in range(len(active_js))]
    if old_tids == new_tids:
        return
    for j, nid in zip(active_js, new_tids):
        st.session_state[f"sb_tc_{j}_id"] = nid
    valid = set(new_tids)
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    for ai in range(n_ac):
        mkey = f"sb_ac_{ai}_map"
        cur = [str(x).strip() for x in (st.session_state.get(mkey) or []) if x is not None and str(x).strip()]
        st.session_state[mkey] = _sb_remap_ac_tid_list(cur, old_tids, new_tids, valid)


def _sb_compact_reindex_test_cases() -> None:
    """Remove gaps in TC slots; force ids TC-01..TC-n; remap AC multiselects."""
    bump_upload_widget_epoch(st.session_state)
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    active_js = [j for j in range(n_tc) if _sb_tc_row_active(j)]
    rows = [_sb_snapshot_tc_row(j) for j in active_js]
    old_tids = [r["tid"] for r in rows]
    new_tids = [f"TC-{i + 1:02d}" for i in range(len(rows))]
    for j in range(n_tc):
        _sb_clear_tc_slot(j)
    st.session_state["sb_n_tc"] = len(rows)
    for i, row in enumerate(rows):
        _sb_restore_tc_row(i, row, new_tid=new_tids[i])
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    valid = set(new_tids)
    for ai in range(n_ac):
        mkey = f"sb_ac_{ai}_map"
        cur = [str(x).strip() for x in (st.session_state.get(mkey) or []) if x is not None and str(x).strip()]
        st.session_state[mkey] = _sb_remap_ac_tid_list(cur, old_tids, new_tids, valid)
    _sb_recompute_all_linked_ac_hints()


def _sb_generate_tcs_for_all_acs() -> None:
    """Create one new empty test case per acceptance criterion and append its id to that AC's ``test_case_ids``."""
    _sb_sync_ac_n_from_row_keys()
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    if n_ac <= 0:
        return
    for i in range(n_ac):
        mkey = f"sb_ac_{i}_map"
        raw = st.session_state.get(mkey) or []
        cur = (
            [str(x).strip() for x in raw if isinstance(raw, list) and x is not None and str(x).strip()]
            if isinstance(raw, list)
            else []
        )
        j = int(st.session_state.get("sb_n_tc") or 0)
        st.session_state["sb_n_tc"] = j + 1
        tid = f"TC-{j + 1:02d}"
        st.session_state[f"sb_tc_{j}_id"] = tid
        st.session_state[f"sb_tc_{j}_text"] = ""
        st.session_state[f"sb_tc_{j}_n_steps"] = 1
        st.session_state[f"sb_tc_{j}_steps_bulk"] = "1. "
        st.session_state[f"sb_tc_{j}_linked_ac"] = i
        st.session_state[f"sb_tc_{j}_active"] = True
        st.session_state.pop(f"sb_tc_{j}_step_0_persisted_path", None)
        st.session_state.pop(f"sb_tc_{j}_step_0_persisted_paths", None)
        st.session_state.setdefault(f"sb_tc_{j}_notes", "")
        st.session_state.pop(f"sb_tc_{j}_title_steps_paste", None)
        st.session_state.pop(f"sb_tc_{j}_paste_digest", None)
        st.session_state.setdefault(f"sb_tc_{j}_step_0_text", "")
        nxt = list(cur)
        if tid not in nxt:
            nxt.append(tid)
        st.session_state[mkey] = nxt
    _sb_recompute_all_linked_ac_hints()


def _sb_count_active_test_cases() -> int:
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    return sum(1 for j in range(n_tc) if _sb_tc_row_active(j))


def _sb_wipe_all_test_cases() -> None:
    """Deactivate every test case slot and compact so no TCs remain; AC ``*_map`` lists clear via compact remap."""
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    for j in range(n_tc):
        st.session_state[f"sb_tc_{j}_active"] = False
    _sb_compact_reindex_test_cases()


def _sb_spawn_linked_tc() -> None:
    ac_i = int(st.session_state.get("sb_pick_ac_for_spawn", 0))
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    if n_ac <= 0 or ac_i < 0 or ac_i >= n_ac:
        return
    j = int(st.session_state.get("sb_n_tc") or 0)
    st.session_state["sb_n_tc"] = j + 1
    tid = f"TC-{j + 1:02d}"
    st.session_state[f"sb_tc_{j}_id"] = tid
    st.session_state[f"sb_tc_{j}_text"] = ""
    st.session_state[f"sb_tc_{j}_n_steps"] = 1
    st.session_state[f"sb_tc_{j}_linked_ac"] = ac_i
    st.session_state[f"sb_tc_{j}_active"] = True
    st.session_state.setdefault(f"sb_tc_{j}_steps_bulk", "1. ")
    mkey = f"sb_ac_{ac_i}_map"
    cur = [str(x).strip() for x in (st.session_state.get(mkey) or []) if x is not None and str(x).strip()]
    if tid not in cur:
        cur.append(tid)
    st.session_state[mkey] = cur
    st.session_state.setdefault(f"sb_tc_{j}_notes", "")
    st.session_state.pop(f"sb_tc_{j}_title_steps_paste", None)
    st.session_state.pop(f"sb_tc_{j}_paste_digest", None)
    st.session_state.setdefault(f"sb_tc_{j}_step_0_text", "")


def _sb_delete_tc(j: int) -> None:
    """Remove a test case, strip it from AC maps, then compact slots and reassign TC-01..TC-n."""
    tid = str(st.session_state.get(f"sb_tc_{j}_id") or "").strip() or f"TC-{j + 1:02d}"
    st.session_state[f"sb_tc_{j}_active"] = False
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    for i in range(n_ac):
        mkey = f"sb_ac_{i}_map"
        cur = [str(x).strip() for x in (st.session_state.get(mkey) or []) if x is not None and str(x).strip()]
        st.session_state[mkey] = [x for x in cur if x != tid]
    _sb_compact_reindex_test_cases()


def _sb_remove_ac(remove_idx: int) -> None:
    """
    Drop one acceptance criterion and its AC↔TC mappings (multiselect lists only).
    Test cases are kept; TCs only mapped on this AC become unmapped until remapped.
    """
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    if remove_idx < 0 or remove_idx >= n_ac:
        return
    remaining: list[tuple[str, str, list]] = []
    for i in range(n_ac):
        if i == remove_idx:
            continue
        aid = str(st.session_state.get(f"sb_ac_{i}_id") or "")
        atx = str(st.session_state.get(f"sb_ac_{i}_text") or "")
        mkey = f"sb_ac_{i}_map"
        raw = st.session_state.get(mkey) or []
        cur: list[str] = []
        if isinstance(raw, list):
            cur = [str(x).strip() for x in raw if x is not None and str(x).strip()]
        remaining.append((aid, atx, cur))
    for i in range(n_ac):
        st.session_state.pop(f"sb_ac_{i}_id", None)
        st.session_state.pop(f"sb_ac_{i}_text", None)
        st.session_state.pop(f"sb_ac_{i}_map", None)
    new_n = len(remaining)
    st.session_state["sb_n_ac"] = new_n
    for ni, (aid, atx, cmap) in enumerate(remaining):
        st.session_state[f"sb_ac_{ni}_id"] = aid.strip() or f"AC-{ni + 1}"
        st.session_state[f"sb_ac_{ni}_text"] = atx
        st.session_state[f"sb_ac_{ni}_map"] = list(cmap)

    _sb_recompute_all_linked_ac_hints()

    pick = int(st.session_state.get("sb_pick_ac_for_spawn", 0))
    if new_n <= 0:
        st.session_state["sb_pick_ac_for_spawn"] = 0
    else:
        if pick == remove_idx:
            st.session_state["sb_pick_ac_for_spawn"] = max(0, min(remove_idx, new_n - 1))
        elif pick > remove_idx:
            st.session_state["sb_pick_ac_for_spawn"] = max(0, min(pick - 1, new_n - 1))
        else:
            st.session_state["sb_pick_ac_for_spawn"] = max(0, min(pick, new_n - 1))

    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("sb_g_btn_rm_ac_"):
            st.session_state.pop(k, None)


def _sb_tc_row_active(j: int) -> bool:
    return st.session_state.get(f"sb_tc_{j}_active", True) is not False


def _sb_effective_ac_count(sess: Mapping[str, Any]) -> int:
    """
    Max of ``sb_n_ac`` and inferred count from ``sb_ac_{i}_{id|text|map}`` keys so AC rows are not
    dropped when ``sb_n_ac`` was reset (e.g. widget not mounted on another step).
    """
    n = int(sess.get("sb_n_ac") or 0)
    pat = re.compile(r"^sb_ac_(\d+)_(?:id|text|map)$")
    hi = -1
    for k in sess:
        if not isinstance(k, str):
            continue
        m = pat.match(k)
        if m:
            hi = max(hi, int(m.group(1)))
    inferred = hi + 1 if hi >= 0 else 0
    return max(n, inferred)


def _sb_sync_ac_n_from_row_keys() -> None:
    """Raise ``sb_n_ac`` to cover all AC row keys present in session (never shrink)."""
    eff = _sb_effective_ac_count(st.session_state)
    cur = int(st.session_state.get("sb_n_ac") or 0)
    if eff > cur:
        st.session_state["sb_n_ac"] = eff


def _sb_tc_multiselect_options() -> list[str]:
    """
    Test case ids for AC↔TC multiselects: active TCs in slot order, then any ids already stored on
    ``sb_ac_*_map`` so Streamlit does not drop selections when options were rebuilt narrowly.
    """
    _sb_sync_ac_n_from_row_keys()
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    ordered: list[str] = []
    seen: set[str] = set()
    for j in range(n_tc):
        if not _sb_tc_row_active(j):
            continue
        raw = st.session_state.get(f"sb_tc_{j}_id")
        tid = (str(raw).strip() if raw is not None else "") or f"TC-{j + 1:02d}"
        if tid not in seen:
            seen.add(tid)
            ordered.append(tid)
    for i in range(n_ac):
        raw = st.session_state.get(f"sb_ac_{i}_map")
        if not isinstance(raw, list):
            continue
        for x in raw:
            t = str(x).strip() if x is not None else ""
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)
    return ordered


def _sb_session_unmapped_tc_ids() -> list[str]:
    """Active builder TC ids not referenced on any ``sb_ac_*_map`` (normalized strip match)."""
    try:
        _sb_backfill_empty_from_guided_snapshot()
        data = read_flat_builder_session(st.session_state)
        return unmapped_test_case_ids(data)
    except Exception:
        _sb_sync_ac_n_from_row_keys()
        n_tc = int(st.session_state.get("sb_n_tc") or 0)
        n_ac = int(st.session_state.get("sb_n_ac") or 0)
        mapped: set[str] = set()
        for i in range(n_ac):
            raw = st.session_state.get(f"sb_ac_{i}_map")
            if isinstance(raw, list):
                for x in raw:
                    if x is not None and str(x).strip():
                        mapped.add(str(x).strip())
        out: list[str] = []
        for j in range(n_tc):
            if not _sb_tc_row_active(j):
                continue
            raw = st.session_state.get(f"sb_tc_{j}_id")
            tid = (str(raw).strip() if raw is not None else "") or f"TC-{j + 1:02d}"
            if tid not in mapped:
                out.append(tid)
        return out


def _sb_persist_guided_workflow_uploads_only() -> None:
    """
    Persist **workflow-level** screenshot picks when leaving guided **Step 2 — Changed areas**.

    Step-level uploaders live on the test-steps step; this helper only flushes ``sb_wf_upload`` so
    navigation does not drop workflow files before **Save to catalog**.
    """
    _sb_backfill_empty_from_guided_snapshot()
    sid = resolve_builder_scenario_id(st.session_state)
    persist_workflow_screenshot_uploads(st.session_state, sid)
    st.session_state.pop("sb_wf_upload", None)


def _sb_persist_guided_step4_media(*, flash_message: bool = False) -> None:
    """
    Write workflow + bulk + per-step screenshot uploads to disk and refresh persisted path keys.

    Guided **Test steps & screenshots** unmounts file uploaders when navigating away; callers must
    run this **before** leaving that step (or from **Save step screenshots**) so evidence is not
    lost before catalog Save. Workflow picks may also be flushed here if present (e.g. after
    navigating back from the test-steps step).
    """
    _sb_backfill_empty_from_guided_snapshot()
    sid = resolve_builder_scenario_id(st.session_state)
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    n_steps_for_tc: list[int] = []
    for j in range(n_tc):
        if st.session_state.get(f"sb_tc_{j}_active", True) is False:
            n_steps_for_tc.append(0)
            continue
        _tt, steps_eff = tc_title_text_and_steps_from_session(st.session_state, j)
        n_steps_for_tc.append(len(steps_eff) if steps_eff else 1)
    persist_bulk_tc_step_screenshot_uploads(
        st.session_state, sid, n_tc=n_tc, n_steps_for_tc=n_steps_for_tc
    )
    wf_extra, _wf_rep = persist_workflow_screenshot_uploads(st.session_state, sid)
    # Clear widget state after persisting so we do not rewrite the same uploads on the next flush.
    st.session_state.pop("sb_wf_upload", None)
    step_ov, _sr = persist_step_screenshot_uploads(
        st.session_state, sid, n_tc=n_tc, n_steps_for_tc=n_steps_for_tc
    )
    data = read_flat_builder_session(
        st.session_state,
        extra_workflow_paths=wf_extra or None,
        step_shot_overrides=step_ov or None,
    )
    tcs_list = [x for x in (data.get("test_cases") or []) if isinstance(x, dict)]
    by_tid = {str(tc.get("id") or "").strip(): tc for tc in tcs_list if str(tc.get("id") or "").strip()}
    for j in range(n_tc):
        if st.session_state.get(f"sb_tc_{j}_active", True) is False:
            continue
        tid = (str(st.session_state.get(f"sb_tc_{j}_id") or "").strip() or f"TC-{j + 1:02d}")
        tc = by_tid.get(tid)
        if not isinstance(tc, dict):
            continue
        steps = list(step_texts(tc))
        pr = expected_step_screenshot_paths(tc)
        n_steps = max(len(steps), len(pr))
        ns = max(n_steps, 1)
        raw_ess = tc.get("expected_step_screenshots") or []
        if not isinstance(raw_ess, list):
            raw_ess = []
        buckets = _bucket_step_paths_from_raw(raw_ess, ns if ns > 0 else 1)
        write_step_paths_to_session(st.session_state, j, buckets)
        for k in range(len(buckets), 65):
            st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)
            st.session_state.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)
    bump_upload_widget_epoch(st.session_state)
    if flash_message:
        st.session_state[_SB_FLASH_GUIDED_STEP_SHOTS_SAVED] = "Step screenshots saved successfully."


def _sb_commit_guided_test_step_screenshots() -> None:
    """
    Persist bulk + per-step + workflow screenshot uploads to disk and refresh ``sb_tc_*_persisted_*`` keys
    from the built scenario (same paths as full Save), without writing the JSON catalog.
    """
    _sb_persist_guided_step4_media(flash_message=True)


def _sb_build_polish_test_step_updates() -> tuple[str, dict[str, str | int], list[str], list[dict[str, Any]]]:
    """
    Build polish updates aligned with ``tc_title_text_and_steps_from_session``.

    Returns ``(status, updates, lines, preview_rows)`` where ``preview_rows`` are dicts with
    ``location``, ``kind``, ``tc_slot``, ``step_index`` (0-based or None), ``old``, ``new``, ``state_key``.
    """
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return "no_api_key", {}, [], []

    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    updates: dict[str, str | int] = {}
    lines: list[str] = []
    rows: list[dict[str, Any]] = []
    ok_any = False
    api_fail = False
    tried_polish = False

    for j in range(n_tc):
        if not _sb_tc_row_active(j):
            continue
        tid = str(st.session_state.get(f"sb_tc_{j}_id") or "").strip() or f"TC-{j + 1:02d}"
        title_e, steps_eff = tc_title_text_and_steps_from_session(st.session_state, j)
        if not any(s.strip() for s in steps_eff):
            continue

        tried_polish = True
        texts = list(steps_eff)
        out = polish_parallel_texts(texts, role="test steps for one test case")
        if out is None or len(out) != len(texts):
            api_fail = True
            continue

        step_same = all(
            (texts[k] if k < len(texts) else "").strip() == out[k].strip() for k in range(len(out))
        )
        paste = str(st.session_state.get(f"sb_tc_{j}_title_steps_paste") or "").strip()
        new_paste: str | None = None
        if paste:
            body = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(out))
            tt = (title_e or "").strip()
            new_paste = f"Title: {tt}\n\n{body}" if tt else body
        paste_changed = bool(paste) and new_paste is not None and new_paste.strip() != paste.strip()

        if step_same and not paste_changed:
            continue

        ok_any = True
        updates[f"sb_tc_{j}_text"] = title_e
        updates[f"sb_tc_{j}_n_steps"] = len(out)
        for k, t in enumerate(out):
            updates[f"sb_tc_{j}_step_{k}_text"] = t
        bulk_lines = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(out))
        updates[f"sb_tc_{j}_steps_bulk"] = bulk_lines
        if paste_changed and new_paste is not None:
            updates[f"sb_tc_{j}_title_steps_paste"] = new_paste

        if not step_same:
            for k, t in enumerate(out):
                old = texts[k] if k < len(texts) else ""
                if old.strip() == t.strip():
                    continue
                o_short = (old[:72] + "…") if len(old) > 72 else old
                n_short = (t[:72] + "…") if len(t) > 72 else t
                lines.append(f"- **{tid}** — Step {k + 1}: `{o_short or '(empty)'}` → `{n_short or '(empty)'}`")
                rows.append(
                    {
                        "location": f"{tid} - Step {k + 1}",
                        "kind": "step",
                        "tc_slot": j,
                        "step_index": k,
                        "old": old,
                        "new": t,
                        "state_key": f"sb_tc_{j}_step_{k}_text",
                    }
                )
        if paste_changed and new_paste is not None:
            lines.append(
                f"- **{tid}** — *Paste title & steps together*: "
                f"`{_one_line_snip(paste)}` → `{_one_line_snip(new_paste)}`"
            )
            rows.append(
                {
                    "location": f"{tid} - Paste (title & steps together)",
                    "kind": "paste",
                    "tc_slot": j,
                    "step_index": None,
                    "old": paste,
                    "new": new_paste,
                    "state_key": f"sb_tc_{j}_title_steps_paste",
                }
            )

    if ok_any:
        return "ok", updates, lines, rows
    if not tried_polish:
        return "no_step_content", {}, [], []
    if api_fail:
        return "api_error", {}, [], []
    return "no_changes", {}, [], []


def _sb_queue_polish_test_steps() -> bool:
    """Queue deferred polish updates for all active test cases; returns True if any were queued."""
    status, updates, _lines, _rows = _sb_build_polish_test_step_updates()
    if status != "ok" or not updates:
        return False
    st.session_state["_sb_polish_step_text_updates"] = updates
    return True


def _sb_preview_polish_test_steps() -> tuple[
    str, dict[str, str | int] | None, list[str] | None, list[dict[str, Any]] | None
]:
    """
    Compute polish updates without applying them.

    Returns ``(status, updates_or_none, lines_or_none, preview_rows_or_none)``; ``status`` is ``ok``
    or an error token from :func:`_sb_build_polish_test_step_updates`.
    """
    status, updates, lines, rows = _sb_build_polish_test_step_updates()
    if status != "ok":
        return status, None, None, None
    if not updates:
        return "no_changes", None, None, None
    return "ok", updates, lines, rows


def _build_scenario_with_uploads() -> tuple[dict, bool]:
    """Persist workflow + step uploads under data/json_upload_media/<scenario_id>/ then assemble JSON."""
    _sb_backfill_empty_from_guided_snapshot()
    sid = resolve_builder_scenario_id(st.session_state)
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    n_steps_for_tc: list[int] = []
    for j in range(n_tc):
        if st.session_state.get(f"sb_tc_{j}_active", True) is False:
            n_steps_for_tc.append(0)
            continue
        _tt, steps_eff = tc_title_text_and_steps_from_session(st.session_state, j)
        n_steps_for_tc.append(len(steps_eff) if steps_eff else 1)
    bulk_replaced = persist_bulk_tc_step_screenshot_uploads(
        st.session_state, sid, n_tc=n_tc, n_steps_for_tc=n_steps_for_tc
    )
    wf_extra, wf_replaced = persist_workflow_screenshot_uploads(st.session_state, sid)
    step_ov, step_replaced = persist_step_screenshot_uploads(
        st.session_state, sid, n_tc=n_tc, n_steps_for_tc=n_steps_for_tc
    )
    replaced_screenshot = bulk_replaced or wf_replaced or step_replaced
    data = read_flat_builder_session(
        st.session_state,
        extra_workflow_paths=wf_extra or None,
        step_shot_overrides=step_ov or None,
    )
    return data, replaced_screenshot


def render_scenario_builder_page(
    *,
    pending_select_key: str,
) -> None:
    """Full-page builder; save uses persist_imported_json_scenario (same as JSON import)."""
    _drain_builder_polish_queues()
    load_err = st.session_state.pop(_SB_BUILDER_LOAD_ERROR_KEY, None)
    if load_err:
        st.error(str(load_err))
    ok_sid = st.session_state.pop(_SB_FLASH_SAVE_SUCCESS, None)
    if ok_sid:
        st.success(f"Scenario saved successfully. (`{ok_sid}`)")
    save_err = st.session_state.pop(_SB_FLASH_SAVE_ERROR, None)
    if save_err:
        st.error(str(save_err))
    shot_msg = st.session_state.pop(_SB_FLASH_SHOT_REPLACED, None)
    if shot_msg:
        st.info(str(shot_msg))
    _maybe_consume_pending_builder_load()
    _sb_restore_missing_from_guided_snapshot()
    _sb_init_defaults()
    _sb_consolidate_legacy_story_description_into_context()
    _sb_backfill_empty_from_guided_snapshot()

    st.markdown("## AI Scenario Builder")
    st.caption(
        "Create a **schema-compliant** scenario and save to the catalog. "
        "Saved scenarios appear under **Scenario Management** (as **Incomplete** or **In Progress** until ready) "
        "and can be reviewed in **Scenario Review** when your role allows. "
        "**Approval** still requires full AC↔TC mapping, steps, and evidence — drafts may be saved anytime."
    )
    edit_rid = str(st.session_state.get("sb_editing_registry_id") or "").strip()
    if edit_rid:
        st.info(
            f"Editing saved scenario **`{edit_rid}`**. **Save** overwrites that JSON file in the catalog "
            "(review rules and traceability still apply)."
        )

    st.session_state.setdefault(BUILDER_LAYOUT_MODE_KEY, BUILDER_LAYOUT_GUIDED)
    st.caption(
        "**New scenarios** default to **Guided step-by-step**. "
        "**Classic** is the suggested layout when you open a saved scenario from **Scenario Management** (all sections on one page). "
        "You can switch anytime with **Builder layout** below."
    )
    layout = st.radio(
        "Builder layout",
        [BUILDER_LAYOUT_GUIDED, BUILDER_LAYOUT_CLASSIC],
        horizontal=True,
        key=BUILDER_LAYOUT_MODE_KEY,
        help=(
            "**Guided** walks through creation in order (recommended for new scenarios). "
            "**Classic** shows every section on one page (handy for edits and power users)."
        ),
    )
    if layout == BUILDER_LAYOUT_GUIDED:
        from src.ui_scenario_builder_guided import render_guided_scenario_builder

        render_guided_scenario_builder(pending_select_key=pending_select_key)
        return

    st.markdown("### 1) Scenario overview")
    st.text_area(
        "Scenario context",
        key="sb_scenario_context",
        height=140,
        placeholder=(
            "Example: Provider updates email and phone number. Email must be valid format. "
            "Phone must be 10 digits. Required fields should block save if blank. Save should persist changes "
            "and display a confirmation message."
        ),
        help=(
            "**Primary narrative for this scenario** — actors, workflow details, field rules, validation hints, "
            "edge cases, and anything the AI should respect when you use **Generate**. Feeds context expansion only; "
            "it does not auto-overwrite your AC or test rows."
        ),
    )
    st.text_input(
        "Scenario title",
        key="sb_story_title",
        placeholder="e.g. Patient profile update",
        help="Human-readable name shown in the sidebar and title areas (story / scenario name).",
    )
    st.text_input(
        "Workflow name",
        key="sb_workflow_name",
        placeholder="e.g. Registration flow",
        help="Label for the **business workflow** under test (distinct from the scenario title).",
    )
    st.text_area(
        "Business goal",
        key="sb_business_goal",
        height=80,
        placeholder="One concise outcome the business cares about (e.g. reduce checkout errors).",
    )

    st.checkbox("Auto-generate Scenario ID from title", key="sb_auto_id")
    if not st.session_state.get("sb_auto_id"):
        st.text_input(
            "Scenario ID (required when auto is off)",
            key="sb_scenario_id",
            placeholder="e.g. patient_profile_update",
        )

    st.markdown("### 2) Changed areas (optional)")
    st.text_area(
        "Changed areas (one per line)",
        key="sb_changed_areas_bulk",
        height=120,
        placeholder="e.g.\nPatient chart\nBilling: backend\n- Checkout UI",
        help="Optional ``Area: type`` split on first colon; lines starting with ``-`` / ``*`` / numbers are cleaned up.",
    )

    st.markdown("### 3) Known dependencies (optional)")
    st.text_area(
        "Known dependencies (one per line)",
        key="sb_known_dependencies_bulk",
        height=100,
        placeholder="e.g.\nAuth service\n- Payment API",
        help="One dependency per non-empty line; bullet prefixes are stripped automatically.",
    )

    st.markdown("### 4) Workflow-level screenshots (optional)")
    sid_hint = resolve_builder_scenario_id(st.session_state)
    st.caption(
        f"**Upload first**, then describe each image. Files save under **`data/json_upload_media/{sid_hint}/`** "
        "when you save; paths are stored in your scenario file."
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
        st.caption("Saved workflow images (from scenario file). **Remove** clears the path and its description.")
        for wi, p in enumerate(list(wf_persisted)):
            ps = str(p).strip()
            if not ps:
                continue
            slot = wi + 1
            st.markdown(f"**Workflow Screenshot {slot}** — `{Path(ps).name}`")
            st.caption(ps)
            c2, c3 = st.columns([4, 1])
            with c2:
                st.text_input(
                    "What does this screenshot represent?",
                    key=f"sb_wf_lbl_{wi}",
                    placeholder="e.g. Login screen before MFA",
                )
            with c3:
                st.button(
                    "Remove",
                    key=f"sb_rm_wf_{wi}",
                    on_click=_sb_clear_wf_persisted_at,
                    args=(wi,),
                    type="secondary",
                )
    if n_wf_up:
        st.caption("**New uploads** — one row per file in upload order (paired with the file above).")
        for ui in range(n_wf_up):
            idx = n_prev_wf + ui
            slot = idx + 1
            st.markdown(f"**Workflow Screenshot {slot}** *(new)*")
            st.text_input(
                "What does this screenshot represent?",
                key=f"sb_wf_lbl_{idx}",
                placeholder="e.g. Error banner on checkout",
            )
    st.button(
        "Clear workflow uploads (this session)",
        key="sb_clear_wf_upload",
        on_click=_sb_clear_wf_upload_widget,
        type="secondary",
        help="Clears the file picker only; saved paths above stay until you remove them or save.",
    )

    st.markdown("### 5) Acceptance criteria (wording)")
    st.caption(
        "Paste many criteria at once (one per line). Lines may start with an id such as **AC-01**. "
        "Click **Apply pasted lines** to replace the current list; then use per-row fields or **Remove** to fine-tune."
    )
    st.text_area(
        "Bulk paste acceptance criteria (one per line)",
        key="sb_ac_bulk_text",
        height=120,
        placeholder="AC-01 User can sign in\nAC-02 Reports load within 2s\nOr a line without an id — ids are assigned automatically.",
    )
    if st.button("Apply pasted lines as acceptance criteria", key="sb_btn_apply_ac_bulk", type="secondary"):
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
            st.success(f"Applied **{new_n}** acceptance criteria (mappings reset — re-map test cases in section 6).")
            st.rerun()
    st.number_input("Number of acceptance criteria", min_value=0, max_value=60, step=1, key="sb_n_ac")
    n_ac = int(st.session_state.get("sb_n_ac") or 0)
    if n_ac == 0:
        st.warning("At least one Acceptance Criteria is required.")
    for i in range(n_ac):
        aid_key = f"sb_ac_{i}_id"
        if aid_key not in st.session_state:
            st.session_state[aid_key] = f"AC-{i + 1}"
        with st.expander(f"Acceptance criterion {i + 1}", expanded=(i == 0 and n_ac <= 5)):
            h1, h2 = st.columns([4, 1])
            with h1:
                st.text_input("AC id", key=aid_key)
            with h2:
                st.button(
                    "Remove",
                    key=f"sb_btn_rm_ac_{i}",
                    on_click=_sb_remove_ac,
                    args=(i,),
                    type="secondary",
                    help="Remove this criterion and its mapped test IDs on this AC only. Test cases are not deleted.",
                )
            st.text_area("Criterion text", key=f"sb_ac_{i}_text", height=68, placeholder="Verifiable outcome…")

    st.markdown("### 6) AC ↔ TC mapping")
    st.caption(
        "Use multiselects to attach test case IDs to each AC. **Save** requires at least one acceptance criterion, "
        "every test case to appear on at least one AC’s `test_case_ids`, and every AC must list at least one test id."
    )
    n_tc = int(st.session_state.get("sb_n_tc") or 0)
    tc_id_options: list[str] = _sb_tc_multiselect_options()

    if n_ac > 0:
        st.selectbox(
            "Select acceptance criterion",
            options=list(range(n_ac)),
            format_func=_sb_ac_pick_label,
            key="sb_pick_ac_for_spawn",
        )
        st.caption(
            "Use **Generate test cases for all acceptance criteria** to add **one new** empty test per AC "
            "(each id is appended to that AC’s mapping). Use **Add empty test case** for a single manual row."
        )
        st.button(
            "Generate test cases for all acceptance criteria",
            on_click=_sb_generate_tcs_for_all_acs,
            type="primary",
            use_container_width=True,
            help="Adds one new empty test case for every acceptance criterion and links each to its AC.",
        )
        st.button(
            "Add empty test case linked to selected criterion",
            on_click=_sb_spawn_linked_tc,
            type="secondary",
            use_container_width=True,
        )
    else:
        st.caption("Add at least one acceptance criterion before creating linked test cases.")

    if not tc_id_options:
        st.caption("No test cases yet — use the button above to add a scaffold.")
    else:
        for i in range(n_ac):
            ac_lbl = st.session_state.get(f"sb_ac_{i}_id") or f"AC-{i + 1}"
            st.multiselect(
                f"**{ac_lbl}** → mapped test case IDs (`test_case_ids`)",
                options=tc_id_options,
                key=f"sb_ac_{i}_map",
                help="Refine which tests explicitly cover this criterion.",
            )

    unmapped_sess = _sb_session_unmapped_tc_ids()
    st.markdown("##### Unmapped test cases")
    if not tc_id_options:
        st.caption("Add a test case to see mapping status.")
    elif not unmapped_sess:
        st.caption("All test cases are referenced on at least one acceptance criterion.")
    else:
        st.info(
            "These test case IDs are not on any AC’s `test_case_ids` — map them for a structurally complete scenario "
            "(required before **Approved**). You can still **save a draft**: "
            + ", ".join(unmapped_sess)
        )

    st.markdown("### 7) Test cases")
    vis_idx = 0
    for j in range(n_tc):
        if not _sb_tc_row_active(j):
            continue
        vis_idx += 1
        kid = f"sb_tc_{j}_id"
        if kid not in st.session_state:
            st.session_state[kid] = f"TC-{vis_idx:02d}"
        _sb_sync_paste_to_step_fields(j)

        with st.expander(f"Test case {vis_idx}", expanded=(vis_idx == 1 and len(tc_id_options) <= 4)):
            ac_lines = _sb_linked_ac_lines_for_tc(j)
            if ac_lines:
                st.markdown("**Linked acceptance criteria** *(from section 6 `test_case_ids` multiselects)*")
                for ln in ac_lines:
                    st.markdown(f"- {ln}")
            else:
                st.markdown(
                    "**Linked acceptance criteria:** *(map this test id on at least one AC in section 6)*"
                )
            tc_disp_id = str(st.session_state.get(kid) or "").strip() or f"TC-{vis_idx:02d}"
            st.caption(f"Test case ID: **{tc_disp_id}** (sequential; renumbered after deletes).")
            c_tx, c_del = st.columns([3, 1])
            with c_tx:
                st.text_area(
                    "Paste title & steps together",
                    key=f"sb_tc_{j}_title_steps_paste",
                    height=120,
                    placeholder=(
                        "Title: Short name for this test\n"
                        "1. First step\n"
                        "2. Second step\n\n"
                        "After you paste, editable **Step 1 / Step 2 / …** fields appear below; you can refine them there."
                    ),
                    help="Primary authoring path: **Title:** line for the saved test case name; numbered or plain lines "
                    "for steps. Changing this box re-parses into the step fields when the text changes.",
                )
                st.file_uploader(
                    "Bulk step screenshots (.png, .jpg, .jpeg)",
                    type=["png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                    key=tc_bulk_step_upload_widget_key(st.session_state, j),
                    help=(
                        "Upload several images at once. On **Save**, file 1 → Step 1, file 2 → Step 2, … "
                        "(one per step by default). If there are more files than steps, extras continue in the same "
                        "round-robin pattern. Per-step uploaders below still apply."
                    ),
                )
                st.caption(
                    "Bulk files are persisted when you **Save**. Use per-step controls under each step to fine-tune "
                    "or add more evidence."
                )
            with c_del:
                st.button(
                    "Delete",
                    key=f"sb_btn_del_tc_{j}",
                    on_click=_sb_delete_tc,
                    args=(j,),
                    type="secondary",
                    help="Remove this test case from the builder and strip it from AC mappings.",
                )
            nk = f"sb_tc_{j}_n_steps"
            if nk not in st.session_state:
                st.session_state[nk] = 1
            if f"sb_tc_{j}_steps_bulk" not in st.session_state:
                st.session_state[f"sb_tc_{j}_steps_bulk"] = "1. "
            n_step_widgets = max(int(st.session_state.get(nk) or 1), 1)
            _ttc, steps_eff_c = tc_title_text_and_steps_from_session(st.session_state, j)
            n_st_bulk = max(n_step_widgets, len(steps_eff_c) if steps_eff_c else 0, 1)
            bulk_key_c = tc_bulk_step_upload_widget_key(st.session_state, j)
            braw_c = st.session_state.get(bulk_key_c)
            bulk_files_c: list = []
            if isinstance(braw_c, list):
                bulk_files_c = [x for x in braw_c if x is not None and hasattr(x, "read")]
            elif braw_c is not None and hasattr(braw_c, "read"):
                bulk_files_c = [braw_c]
            for k in range(n_step_widgets):
                st.text_input(
                    f"Step {k + 1}",
                    key=f"sb_tc_{j}_step_{k}_text",
                    placeholder=f"Describe step {k + 1}…",
                )
                if bulk_files_c:
                    for mi in bulk_upload_file_indices_for_step(k, n_st_bulk, len(bulk_files_c)):
                        fn = getattr(bulk_files_c[mi], "name", None) or f"upload_{mi + 1}"
                        st.info(
                            f"**Bulk screenshot for Step {k + 1}** — file **{mi + 1} of {len(bulk_files_c)}** "
                            f"in the bulk picker: `{fn}`. This step receives that file when you **Save**."
                        )
                plist = st.session_state.get(f"sb_tc_{j}_step_{k}_persisted_paths")
                singles: list[str] = []
                if isinstance(plist, list):
                    singles = [str(x).strip() for x in plist if str(x).strip()]
                else:
                    pp0 = str(st.session_state.get(f"sb_tc_{j}_step_{k}_persisted_path") or "").strip()
                    if pp0:
                        singles = [pp0]
                for si, pp in enumerate(singles):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.caption(f"Saved: **{Path(pp).name}** — `{pp}`")
                    with c2:
                        st.button(
                            "Remove",
                            key=f"sb_rm_step_shot_{j}_{k}_{si}",
                            on_click=_sb_remove_step_shot_at,
                            args=(j, k, si),
                            type="secondary",
                        )
                st.file_uploader(
                    "Add screenshot(s) for this step (.png, .jpg, .jpeg)",
                    type=["png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                    key=tc_step_upload_widget_key(st.session_state, j, k),
                )
                st.button(
                    "Clear all saved screenshots & upload for this step",
                    key=f"sb_rm_step_{j}_{k}",
                    on_click=_sb_clear_step_persisted_and_upload,
                    args=(j, k),
                    type="secondary",
                )
            st.text_area(
                "Tester notes (optional)",
                key=f"sb_tc_{j}_notes",
                height=72,
                placeholder="Assumptions, edge cases, environment (data, URLs, roles)…",
                help="Saved on this test case in the scenario JSON and shown in Scenario Review / export.",
            )

    st.markdown("### 8) Scenario notes (optional)")
    st.caption("Whole-scenario commentary (import trail, handoff, or global context). **Per–test-case** notes are in each test case expander above.")
    st.text_area("Scenario notes", key="sb_notes", height=60, placeholder="Source, assumptions, or handoff…")

    st.divider()

    b_reset, b_polish, b_save = st.columns(3)
    with b_reset:
        do_reset = st.button("Reset", type="secondary", key="sb_btn_reset")
    with b_polish:
        do_polish_steps = st.button("Polish", type="secondary", key="sb_btn_polish_steps")
    with b_save:
        do_save = st.button("Save", type="primary", key="sb_btn_save")

    if do_reset:
        _reset_builder_form()
        _sb_init_defaults()
        _sb_consolidate_legacy_story_description_into_context()
        st.session_state["_guided_builder_step"] = 0
        st.session_state[BUILDER_LAYOUT_MODE_KEY] = BUILDER_LAYOUT_GUIDED
        st.rerun()

    if do_polish_steps:
        if _sb_queue_polish_test_steps():
            st.rerun()
        else:
            st.warning("No steps polished (check API key, step counts, or API response).")

    if do_save:
        try:
            _sb_renumber_sequential_tc_ids()
            data, shot_replaced = _build_scenario_with_uploads()
            if shot_replaced:
                st.session_state[_SB_FLASH_SHOT_REPLACED] = "Existing screenshot replaced."
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
            st.session_state[_SB_FLASH_SAVE_SUCCESS] = sid
            st.rerun()
        except ValueError as e:
            st.session_state[_SB_FLASH_SAVE_ERROR] = str(e)
            st.rerun()
        except Exception as e:
            st.session_state[_SB_FLASH_SAVE_ERROR] = f"Save failed: {e}"
            st.rerun()


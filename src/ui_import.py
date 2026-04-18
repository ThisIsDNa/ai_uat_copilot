"""
Import-related Streamlit UI helpers (File Upload) and JSON normalization for internal use.

`_parse_scenario_json_upload` and validators support tests and programmatic loads; the File Upload
view is DOCX-only. Session keys and orchestration live in app.py.
"""

from __future__ import annotations

import json

import streamlit as st

from src.json_import_media import partition_scenario_screenshot_paths
from src.scenario_media import warn_json_upload_sibling_relative_paths
from src.scenario_review_summary import compute_missing_info_counts, missing_info_narrative


def _normalize_workflow_screenshot_list(raw: object) -> list:
    """Keep path strings or {path, label, …} dicts; do not stringify objects."""
    if not isinstance(raw, list):
        return []
    out: list = []
    for x in raw:
        if x is None:
            continue
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            out.append(dict(x))
        else:
            out.append(str(x))
    return out


def _normalize_pasted_scenario(obj: dict) -> dict:
    """Ensure schema-shaped keys and list types so tabs stay stable."""
    out = dict(obj)
    str_fields = (
        "scenario_id",
        "scenario_title",
        "story_title",
        "story_description",
        "business_goal",
        "workflow_name",
        "scenario_context",
        "notes",
    )
    for key in str_fields:
        if key not in out or out[key] is None:
            out[key] = ""
        elif not isinstance(out[key], str):
            out[key] = str(out[key])
    st = str(out.get("story_title") or "").strip()
    sc = str(out.get("scenario_title") or "").strip()
    if st and not sc:
        out["scenario_title"] = st
    elif sc and not st:
        out["story_title"] = sc
    wf_raw = out.get("workflow_process_screenshots")
    out["workflow_process_screenshots"] = _normalize_workflow_screenshot_list(wf_raw)
    kd = out.get("known_dependencies")
    if not isinstance(kd, list):
        out["known_dependencies"] = []
    else:
        out["known_dependencies"] = [str(x) for x in kd if x is not None]
    ac = out.get("acceptance_criteria")
    if not isinstance(ac, list):
        out["acceptance_criteria"] = []
    else:
        out["acceptance_criteria"] = [x for x in ac if isinstance(x, dict)]
    tc = out.get("test_cases")
    if not isinstance(tc, list):
        out["test_cases"] = []
    else:
        out["test_cases"] = [x for x in tc if isinstance(x, dict)]
    ca = out.get("changed_areas")
    if not isinstance(ca, list):
        out["changed_areas"] = []
    else:
        out["changed_areas"] = [x for x in ca if isinstance(x, dict)]
    return out


def _validate_scenario_upload_shape(obj: dict) -> None:
    """Light structural check before normalization (see docs/schema.md)."""
    sid = obj.get("scenario_id")
    if sid is None or not str(sid).strip():
        raise ValueError("Missing or empty `scenario_id` (required).")
    for key, label in (
        ("acceptance_criteria", "acceptance_criteria"),
        ("test_cases", "test_cases"),
        ("changed_areas", "changed_areas"),
    ):
        v = obj.get(key, [])
        if v is not None and not isinstance(v, list):
            raise ValueError(f"`{label}` must be an array when present.")
    tc = obj.get("test_cases") or []
    if isinstance(tc, list):
        for i, row in enumerate(tc):
            if not isinstance(row, dict):
                raise ValueError(f"`test_cases[{i}]` must be an object.")
    ac = obj.get("acceptance_criteria") or []
    if isinstance(ac, list):
        for i, row in enumerate(ac):
            if not isinstance(row, dict):
                raise ValueError(f"`acceptance_criteria[{i}]` must be an object.")


def _parse_scenario_json_upload(uploaded_file) -> dict:
    """Read uploaded .json (UTF-8), validate shape, return normalized scenario dict."""
    raw = uploaded_file.read()
    if not raw:
        raise ValueError("File is empty.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("File must be UTF-8 encoded text.") from e
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON ({e.msg} at position {e.pos}).") from e
    if not isinstance(parsed, dict):
        raise ValueError("JSON root must be an object { … }, not an array or plain value.")
    _validate_scenario_upload_shape(parsed)
    normalized = _normalize_pasted_scenario(parsed)
    from src.scenario_builder_core import normalize_loaded_scenario_dict

    normalize_loaded_scenario_dict(normalized)
    warn_json_upload_sibling_relative_paths(normalized)
    return normalized


def _empty_scenario_for_docx() -> dict:
    return {
        "scenario_id": "",
        "story_title": "",
        "story_description": "",
        "business_goal": "",
        "workflow_name": "",
        "workflow_process_screenshots": [],
        "acceptance_criteria": [],
        "test_cases": [],
        "changed_areas": [],
        "known_dependencies": [],
        "notes": "Open **Scenario Management** or **File Upload** to add a scenario from a DOCX file.",
    }


def _render_json_import_image_validation(payload: dict) -> None:
    """After JSON load: report workflow + per-step screenshot paths vs files on disk."""
    meta = payload.get("ingestion_meta")
    if isinstance(meta, dict):
        for w in meta.get("warnings") or []:
            if isinstance(w, str) and w.strip():
                st.warning(w.strip())
    existing, missing = partition_scenario_screenshot_paths(payload)
    if not existing and not missing:
        st.info(
            "No screenshot or workflow image paths are referenced in this scenario JSON."
        )
        return
    if not missing:
        st.success(
            f"Image references resolved: all **{len(existing)}** path(s) exist under the project root."
        )
        return
    st.warning(
        f"**Missing files:** {len(missing)} path(s) not found on disk (**{len(existing)}** OK). "
        "The scenario is still loaded—attach matching images below or correct paths in the JSON."
    )
    for p in missing[:25]:
        st.code(p, language=None)
    if len(missing) > 25:
        st.caption(f"… and {len(missing) - 25} more.")


def _render_import_present_quick_stats(preview: dict | None) -> None:
    """File Upload: present counts (AC / TC / changed areas) for the last import preview."""
    st.markdown("##### Quick Stats")
    if preview is None:
        st.caption("No scenario loaded yet — import a DOCX file on **File Upload**.")
        st.markdown(
            "<div style='margin-bottom:0.25rem;'>"
            "<strong>Acceptance Criteria:</strong> —<br/>"
            "<strong>Test Cases:</strong> —<br/>"
            "<strong>Changed Areas:</strong> —"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    n_ac = len(preview.get("acceptance_criteria") or [])
    n_tc = len(preview.get("test_cases") or [])
    n_ch = len(preview.get("changed_areas") or [])
    st.caption("Counts from the last successful import on **File Upload**.")
    st.markdown(
        "<div style='margin-bottom:0.25rem;'>"
        f"<strong>Acceptance Criteria:</strong> {n_ac}<br/>"
        f"<strong>Test Cases:</strong> {n_tc}<br/>"
        f"<strong>Changed Areas:</strong> {n_ch}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_missing_info_summary_panel(preview: dict | None) -> None:
    """Completeness gap counts + narrative from normalized preview dict (import session)."""
    st.markdown("##### Missing-info summary")
    if preview is None:
        st.caption("Import a file to see gap counts and guidance.")
        st.markdown(
            "<div style='margin-bottom:0.25rem;'>"
            "<strong>Missing acceptance criteria:</strong> —<br/>"
            "<strong>Missing test cases:</strong> —<br/>"
            "<strong>Missing test steps:</strong> —<br/>"
            "<strong>Missing screenshot evidence:</strong> —<br/>"
            "<strong>Unlinked acceptance criteria:</strong> —<br/>"
            "<strong>Test cases without explicit AC mapping:</strong> —"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    counts = compute_missing_info_counts(preview)
    st.markdown(
        "<div style='margin-bottom:0.25rem;'>"
        f"<strong>Missing acceptance criteria:</strong> {counts['missing_acceptance_criteria']}<br/>"
        f"<strong>Missing test cases:</strong> {counts['missing_test_cases']}<br/>"
        f"<strong>Missing test steps:</strong> {counts['missing_test_steps']}<br/>"
        f"<strong>Missing screenshot evidence:</strong> {counts['missing_screenshot_evidence']}<br/>"
        f"<strong>Unlinked acceptance criteria:</strong> {counts['unlinked_acceptance_criteria']}<br/>"
        f"<strong>Test cases without explicit AC mapping:</strong> "
        f"{counts['test_cases_without_ac_mapping']}"
        "</div>",
        unsafe_allow_html=True,
    )
    note = missing_info_narrative(preview, counts)
    if note:
        st.info(note)


def _render_mgmt_import_quick_stats(preview: dict | None) -> None:
    """Combined present + gap panel (e.g. tests); prefer split helpers for File Upload layout."""
    _render_import_present_quick_stats(preview)
    st.divider()
    _render_missing_info_summary_panel(preview)


def _render_import_debug_panel(preview: object) -> None:
    """
    Optional debug: last in-session import dict after DOCX parse (internal JSON shape).

    Uses the same normalized object stored in session—no extra transforms. Includes `ingestion_meta`
    when the parser attached it.
    """
    st.markdown("##### Internal scenario data (debug)")
    st.caption(
        "Latest **Parse document** result on **File Upload**. Same structure the app uses internally."
    )
    if not isinstance(preview, dict):
        st.info("Parse a DOCX above to inspect the internal representation here.")
        return

    meta = preview.get("ingestion_meta")
    if isinstance(meta, dict):
        warns = meta.get("warnings") or []
        n_warn = (
            len([w for w in warns if isinstance(w, str) and w.strip()])
            if isinstance(warns, list)
            else 0
        )
        if n_warn:
            st.caption(
                f"`ingestion_meta` includes **{n_warn}** import warning(s)—see **Parse Check** (left column)."
            )

    json_str = json.dumps(preview, indent=2, ensure_ascii=False)
    sid = str(preview.get("scenario_id") or "scenario").strip().replace(" ", "_") or "scenario"
    for bad in '\\/:*?"<>|':
        sid = sid.replace(bad, "_")
    fname = f"{sid}_parsed.json"

    st.download_button(
        "Download internal JSON (debug)",
        data=json_str.encode("utf-8"),
        file_name=fname,
        mime="application/json",
        key="import_debug_download_json",
    )

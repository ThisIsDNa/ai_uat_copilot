"""
Streamlit trust / completeness UI for imported scenarios (Overview + Scenario Management).

Uses `ingestion_meta` and scenario dict fields only; no parser changes here.
"""

from __future__ import annotations

import streamlit as st

from src.json_import_media import iter_scenario_screenshot_reference_paths
from src.scenario_registry import PASTED_SCENARIO_ID


def _ingestion_warning_strings(data: dict) -> list[str]:
    meta = data.get("ingestion_meta")
    if not isinstance(meta, dict):
        return []
    raw = meta.get("warnings")
    if not isinstance(raw, list):
        return []
    return [str(w).strip() for w in raw if w is not None and str(w).strip()]


def _infer_source_from_scenario_id(data: dict) -> str:
    sid = str(data.get("scenario_id") or "")
    return "docx" if sid.startswith("docx_") else "json"


def _effective_import_source(data: dict, stored: str | None) -> str:
    if stored in ("json", "docx"):
        return stored
    return _infer_source_from_scenario_id(data)


def _overview_trust_source(catalog: dict, selected_id: str | None) -> str:
    if selected_id is None:
        return "json"
    if selected_id == PASTED_SCENARIO_ID:
        return "json"
    meta = catalog.get(selected_id) or {}
    return meta.get("source") or "json"


def _source_honesty_label(source: str, data: dict) -> str:
    n_ac = len(data.get("acceptance_criteria") or [])
    n_tc = len(data.get("test_cases") or [])
    if source == "json":
        return "Parsed from structured JSON"
    if source == "docx":
        if n_ac == 0 or n_tc == 0:
            return "Parsed from sparse DOCX"
        return "Parsed from DOCX with fallback extraction"
    return "Source not determined"


def _import_type_label(source: str, data: dict) -> str:
    """
    Import shape for trust summary (not a confidence score).
    JSON → structured; DOCX with missing AC or TC → sparse; else DOCX → fallback.
    """
    n_ac = len(data.get("acceptance_criteria") or [])
    n_tc = len(data.get("test_cases") or [])
    if source == "json":
        return "Structured"
    if source == "docx":
        if n_ac == 0 or n_tc == 0:
            return "Sparse"
        return "Fallback"
    return "—"


def _images_detected_count_display(data: dict) -> str:
    """Single count for summary row: embedded body count when present, else path references."""
    meta = data.get("ingestion_meta")
    m = meta if isinstance(meta, dict) else {}
    det = m.get("images_detected")
    if det is not None:
        try:
            return str(int(det))
        except (TypeError, ValueError):
            pass
    return str(len(iter_scenario_screenshot_reference_paths(data)))


def _render_parse_trust_summary_row(
    data: dict,
    source: str,
    *,
    warn_list: list[str] | None = None,
) -> None:
    n_ac = len(data.get("acceptance_criteria") or [])
    n_tc = len(data.get("test_cases") or [])
    img_n = _images_detected_count_display(data)
    warns = warn_list if warn_list is not None else _ingestion_warning_strings(data)
    n_warn = len(warns)
    src_tag = "JSON" if source == "json" else "DOCX"
    imp_type = _import_type_label(source, data)
    st.markdown(
        "<div style='margin-bottom:0.35rem;font-size:0.92rem;line-height:1.45;'>"
        f"<strong>Source type:</strong> {src_tag}<br/>"
        f"<strong>Import type:</strong> {imp_type}<br/>"
        f"<strong>Acceptance criteria:</strong> {n_ac}<br/>"
        f"<strong>Test cases:</strong> {n_tc}<br/>"
        f"<strong>Images detected:</strong> {img_n}<br/>"
        f"<strong>Warning count:</strong> {n_warn}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_trust_warnings_panel(warns: list[str]) -> None:
    if not warns:
        return
    st.markdown("##### Import Warnings")
    with st.container():
        for i, w in enumerate(warns, start=1):
            st.warning(f"{i}. {w}")


def _render_scenario_trust_section(
    data: dict | None,
    source: str,
    *,
    subtitle: str | None = None,
) -> None:
    if not isinstance(data, dict):
        st.caption("No scenario loaded for trust summary.")
        return
    st.markdown("##### Parse Check")
    if subtitle:
        st.caption(subtitle)
    st.caption(_source_honesty_label(source, data))
    warns = _ingestion_warning_strings(data)
    _render_parse_trust_summary_row(data, source, warn_list=warns)
    _render_trust_warnings_panel(warns)


def _render_review_trust_strip(data: dict, source: str) -> None:
    if not isinstance(data, dict):
        return
    n_ac = len(data.get("acceptance_criteria") or [])
    n_tc = len(data.get("test_cases") or [])
    label = _source_honesty_label(source, data)
    imp = _import_type_label(source, data)
    warns = _ingestion_warning_strings(data)
    wn = len(warns)
    img_n = _images_detected_count_display(data)
    st.caption(
        f"{label} **Import type:** {imp} · **AC:** {n_ac} · **TC:** {n_tc} · "
        f"**Images detected:** {img_n} · **Warnings:** {wn}"
    )

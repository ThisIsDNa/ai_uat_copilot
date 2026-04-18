"""
File Upload view: quick stats, missing-info summary, DOCX import.

Scenarios are stored internally as JSON on disk after DOCX parse; users upload and export DOCX only.
"""

from __future__ import annotations

import time

import streamlit as st

from src.docx_parser import parse_scenario_from_docx
from src.scenario_registry import persist_parsed_docx_scenario
from src.ui_import import (
    _render_import_present_quick_stats,
    _render_missing_info_summary_panel,
)


def render_file_upload_page(
    *,
    mgmt_flash_success_key: str,
    import_preview_key: str,
    import_preview_source_key: str,
    pending_scenario_select_key: str,
) -> None:
    flash = st.session_state.pop(mgmt_flash_success_key, None)
    if flash:
        sec = float(flash.get("seconds") or 0)
        suffix = f" ({sec:.2f}s)"
        fk = flash.get("kind")
        if fk == "docx":
            n_img = flash.get("images_detected")
            extra = ""
            if isinstance(n_img, (int, float)) and not isinstance(n_img, bool):
                extra = f" Embedded images in document body: **{int(n_img)}**."
            st.success(f"DOCX scenario parsed successfully.{suffix}{extra}")
        elif fk in ("json", "json_saved"):
            # Legacy session flash from older builds; no longer user-initiated.
            st.success(f"Import completed.{suffix}")

    st.markdown("# File Upload")

    stats_col, miss_col = st.columns(2)
    preview = st.session_state.get(import_preview_key)
    with stats_col:
        _render_import_present_quick_stats(preview if isinstance(preview, dict) else None)
    with miss_col:
        _render_missing_info_summary_panel(preview if isinstance(preview, dict) else None)

    st.divider()
    st.subheader("Import from DOCX")
    st.caption(
        "Upload a **.docx** UAT scenario document. **Parse document** converts it to the app’s internal "
        "format, saves it, and selects it in **Scenario Review**. "
        "Re-select the file after switching views if needed."
    )
    uploaded_docx = st.file_uploader(
        "DOCX file",
        type=["docx"],
        accept_multiple_files=False,
        key="import_docx_file",
        help="Word document (.docx) only. After parsing, review and export from **Scenario Review**.",
    )
    if st.button("Parse document", key="parse_docx_btn"):
        if uploaded_docx is None:
            st.error("Choose a .docx file first.")
        else:
            try:
                try:
                    uploaded_docx.seek(0)
                except Exception:
                    pass
                with st.spinner("Uploading and parsing DOCX…"):
                    t0 = time.perf_counter()
                    parsed = parse_scenario_from_docx(uploaded_docx)
                    new_id = persist_parsed_docx_scenario(parsed, uploaded_docx.name)
                    elapsed = time.perf_counter() - t0
                st.session_state[import_preview_key] = parsed
                st.session_state[import_preview_source_key] = "docx"
                st.session_state["docx_upload_name"] = uploaded_docx.name
                st.session_state[pending_scenario_select_key] = new_id
                ing = parsed.get("ingestion_meta") if isinstance(parsed, dict) else None
                n_img = ing.get("images_detected") if isinstance(ing, dict) else None
                st.session_state[mgmt_flash_success_key] = {
                    "kind": "docx",
                    "seconds": elapsed,
                    "images_detected": n_img,
                }
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Unexpected error while parsing: {e}")

    if (
        uploaded_docx is not None
        and st.session_state.get("docx_upload_name")
        and uploaded_docx.name != st.session_state.get("docx_upload_name")
    ):
        st.caption("New file selected—click **Parse document** to import.")


# Backward-compatible name for orchestration imports.
render_file_upload_debug_page = render_file_upload_page

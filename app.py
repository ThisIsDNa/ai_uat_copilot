import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from src.intake_parser import load_scenario
from src.placeholder_outputs import get_placeholder_checklist
from src.scenario_builder_core import normalize_loaded_scenario_dict, unmapped_test_case_ids
from src.scenario_registry import (
    PASTED_SCENARIO_ID,
    build_scenario_catalog,
    count_saved_by_review_state,
    display_label_for_review_state,
    format_scenario_dropdown_label,
    sorted_scenario_ids,
)
from src.traceability import generate_traceability_matrix
from src.ui_import import _empty_scenario_for_docx
from src.ui_file_upload_debug import render_file_upload_page
from src.ui_overview import (
    render_acceptance_criteria_snapshot,
    render_workflow_level_screenshots,
)
from src.ui_review_synthesis import _render_review_synthesis_tab
from src.ui_scenario_builder import render_scenario_builder_page
from src.ui_scenario_management import render_scenario_management_page
from src.ui_title_screen import render_title_screen
from src.app_roles import (
    APP_ROLE_KEY,
    APP_ROLE_OPTIONS,
    normalize_role,
    role_can_access_scenario_review,
    role_can_change_testing_status,
    views_for_role,
)

st.set_page_config(page_title="AI UAT Copilot", layout="wide")

_JSON_USE_PASTED = "json_use_pasted"
_JSON_PASTED_DATA = "json_pasted_scenario_data"


st.markdown(
    """
<style>
/* Sidebar: uniform body size and section spacing */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
section[data-testid="stSidebar"] .block-container {
    font-size: 0.95rem;
    line-height: 1.55;
}
section[data-testid="stSidebar"] h1 {
    font-size: 1.35rem !important;
}
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h5 {
    font-size: 1rem !important;
    margin-top: 0.85rem !important;
    margin-bottom: 0.4rem !important;
}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown li {
    font-size: 0.95rem;
}
/* Dataframe: wrap long cells (traceability notes; gap description/action). */
div[data-testid="stDataFrame"] td {
    white-space: pre-wrap !important;
    vertical-align: top !important;
    word-break: break-word;
}
</style>
""",
    unsafe_allow_html=True,
)

checklist_items_global = get_placeholder_checklist()

_SCENARIO_SELECT_KEY = "scenario_select_id"
_PENDING_SCENARIO_SELECT_KEY = "_pending_scenario_select_id"
_APP_VIEW_KEY = "app_view"
# Applied on the next run before the app_view selectbox is created (safe navigation from main body).
_PENDING_APP_VIEW_KEY = "_pending_app_view"
_APP_VIEW_OPTIONS = (
    "Title Screen",
    "AI Scenario Builder",
    "Overview",
    "Scenario Management",
    "File Upload",
)
# All internal view ids (used to validate pending navigation from other modules).
_FULL_APP_VIEWS = frozenset(_APP_VIEW_OPTIONS)


def _format_app_view_label(internal: str) -> str:
    """User-facing labels; session state keeps internal values (e.g. Overview)."""
    if internal == "Overview":
        return "Scenario Review"
    return internal
# Last successful DOCX import on File Upload (preview).
_IMPORT_PREVIEW_KEY = "_import_preview_scenario"
# "docx" for last import preview (legacy sessions may still hold "json").
_IMPORT_PREVIEW_SOURCE_KEY = "_import_preview_source"
# One-shot success after parse on File Upload.
_MGMT_FLASH_SUCCESS = "_mgmt_flash_success"
_SHOW_ARCHIVED_SCENARIOS_KEY = "show_archived_scenarios"


def _scenario_select_changed() -> None:
    if st.session_state.get(_SCENARIO_SELECT_KEY) != PASTED_SCENARIO_ID:
        st.session_state[_JSON_USE_PASTED] = False


def _render_quick_stats(n_ac: int, n_tc: int, n_ch: int) -> None:
    st.markdown("##### Quick Stats")
    st.markdown(
        "<div style='margin-bottom:0.25rem;'>"
        f"<strong>Acceptance Criteria:</strong> {n_ac}<br/>"
        f"<strong>Test Cases:</strong> {n_tc}<br/>"
        f"<strong>Changed Areas:</strong> {n_ch}"
        "</div>",
        unsafe_allow_html=True,
    )


def _resolve_scenario_data(
    *,
    catalog: dict,
    selected_id: str | None,
) -> tuple[dict, str]:
    if selected_id is None:
        return _empty_scenario_for_docx(), "no_scenarios"
    if selected_id == PASTED_SCENARIO_ID:
        raw = st.session_state.get(_JSON_PASTED_DATA)
        if not isinstance(raw, dict):
            data = _empty_scenario_for_docx()
        else:
            data = raw
            normalize_loaded_scenario_dict(data)
        scenario_key = (
            str(data.get("scenario_id") or "").strip().replace(" ", "_")
            or "imported_session"
        )
        return data, scenario_key
    meta = catalog[selected_id]
    try:
        data = load_scenario(meta["path"])
    except FileNotFoundError as e:
        st.sidebar.error(str(e))
        data = _empty_scenario_for_docx()
        data["notes"] = "Scenario file missing; re-import or fix the path in the registry."
        return data, "missing_file"
    except Exception as e:
        st.sidebar.error(f"Could not load scenario file: {e}")
        data = _empty_scenario_for_docx()
        data["notes"] = "Load error; try another scenario or import a DOCX from **File Upload**."
        return data, "load_error"
    scenario_key = (
        str(data.get("scenario_id") or "").strip().replace(" ", "_") or selected_id
    )
    return data, scenario_key


with st.sidebar:
    st.title("AI UAT Copilot")

    st.session_state.setdefault(_JSON_USE_PASTED, False)
    st.session_state.setdefault(_JSON_PASTED_DATA, None)
    st.session_state.setdefault(_APP_VIEW_KEY, _APP_VIEW_OPTIONS[0])
    if st.session_state.get(_APP_VIEW_KEY) == "File Upload / Debug":
        st.session_state[_APP_VIEW_KEY] = "File Upload"
    st.session_state.setdefault(APP_ROLE_KEY, APP_ROLE_OPTIONS[0])
    st.selectbox(
        "Your role (simulated)",
        options=list(APP_ROLE_OPTIONS),
        key=APP_ROLE_KEY,
        help="No login—pick a role to match how you are working. Controls which views and registry actions are available.",
    )
    _role = normalize_role(st.session_state.get(APP_ROLE_KEY))
    _allowed_views = list(views_for_role(_role))

    pending_view = st.session_state.pop(_PENDING_APP_VIEW_KEY, None)
    if pending_view in _FULL_APP_VIEWS:
        st.session_state[_APP_VIEW_KEY] = (
            pending_view if pending_view in _allowed_views else _allowed_views[0]
        )
    if st.session_state.get(_APP_VIEW_KEY) not in _allowed_views:
        st.session_state[_APP_VIEW_KEY] = _allowed_views[0]

    pending_sel = st.session_state.pop(_PENDING_SCENARIO_SELECT_KEY, None)
    if pending_sel is not None:
        st.session_state[_SCENARIO_SELECT_KEY] = pending_sel

    app_view = st.selectbox(
        "App view",
        options=_allowed_views,
        format_func=_format_app_view_label,
        key=_APP_VIEW_KEY,
    )

    catalog = build_scenario_catalog()
    sorted_catalog_ids = sorted_scenario_ids(catalog)
    pasted_ready = bool(
        st.session_state.get(_JSON_USE_PASTED)
        and st.session_state.get(_JSON_PASTED_DATA) is not None
    )
    has_archived = any(
        catalog[sid].get("review_state", "in_progress") == "archived"
        for sid in sorted_catalog_ids
    )
    show_archived = bool(st.session_state.get(_SHOW_ARCHIVED_SCENARIOS_KEY, False))
    filtered_catalog_ids = [
        sid
        for sid in sorted_catalog_ids
        if show_archived or catalog[sid].get("review_state", "in_progress") != "archived"
    ]
    effective_scenario_ids = filtered_catalog_ids + (
        [PASTED_SCENARIO_ID] if pasted_ready else []
    )

    data: dict
    scenario_key: str
    selected_id: str | None

    if not effective_scenario_ids:
        selected_id = None
        data, scenario_key = _resolve_scenario_data(catalog=catalog, selected_id=None)
        if app_view == "Overview":
            if sorted_catalog_ids and not filtered_catalog_ids and has_archived:
                st.checkbox(
                    "Show archived scenarios",
                    key=_SHOW_ARCHIVED_SCENARIOS_KEY,
                )
            if sorted_catalog_ids and not filtered_catalog_ids:
                st.warning(
                    "All saved scenarios are **archived**. Check **Show archived scenarios** "
                    "in the sidebar to select one, or change state under **Scenario Management**."
                )
            else:
                st.warning(
                    "No scenarios in the catalog yet. Create one in **AI Scenario Builder**, "
                    "or use **File Upload** to import a DOCX scenario."
                )
        elif app_view == "Title Screen":
            if role_can_access_scenario_review(_role):
                st.caption(
                    "Import or load scenarios from **File Upload**, then open **Scenario Review** to review."
                )
            else:
                st.caption(
                    "Create or fix scenarios in **AI Scenario Builder**, import via **File Upload**, "
                    "and locate them under **Scenario Management**."
                )
    else:
        if _SCENARIO_SELECT_KEY not in st.session_state:
            st.session_state[_SCENARIO_SELECT_KEY] = effective_scenario_ids[0]
        elif st.session_state[_SCENARIO_SELECT_KEY] not in effective_scenario_ids:
            st.session_state[_SCENARIO_SELECT_KEY] = effective_scenario_ids[0]

        if app_view == "Overview":

            def _dropdown_label(sid: str) -> str:
                if sid == PASTED_SCENARIO_ID:
                    pd = st.session_state.get(_JSON_PASTED_DATA) or {}
                    title = (pd.get("story_title") or "Unsaved scenario (session)").strip()
                    if len(title) > 72:
                        title = title[:69] + "…"
                    return format_scenario_dropdown_label("session", title)
                meta = catalog[sid]
                return format_scenario_dropdown_label(meta["source"], meta["label"])

            st.selectbox(
                "Choose a scenario",
                options=effective_scenario_ids,
                format_func=_dropdown_label,
                key=_SCENARIO_SELECT_KEY,
                on_change=_scenario_select_changed,
            )
            if has_archived:
                st.checkbox(
                    "Show archived scenarios",
                    key=_SHOW_ARCHIVED_SCENARIOS_KEY,
                )
        elif app_view == "AI Scenario Builder":
            if role_can_access_scenario_review(_role):
                st.caption(
                    "Switch to **Scenario Review** to review, **File Upload** to import, or **Scenario Management** to manage saved scenarios."
                )
            else:
                st.caption(
                    "Use **File Upload** to import a DOCX or **Scenario Management** to open a saved scenario in the builder."
                )
        elif app_view == "Title Screen":
            if role_can_access_scenario_review(_role):
                st.caption(
                    "Switch to **Scenario Review** to review a scenario, or **File Upload** to import."
                )
            else:
                st.caption(
                    "Switch to **AI Scenario Builder** or **File Upload** to work on scenarios; "
                    "**Scenario Management** lists saved items."
                )

        selected_id = st.session_state.get(_SCENARIO_SELECT_KEY)
        data, scenario_key = _resolve_scenario_data(
            catalog=catalog, selected_id=selected_id
        )

    test_cases = data.get("test_cases", [])

    n_ac = len(data.get("acceptance_criteria", []))
    n_tc = len(test_cases)
    n_ch = len(data.get("changed_areas", []))

    if app_view == "Overview":
        qcol, rcol = st.columns(2)
        with qcol:
            _render_quick_stats(n_ac, n_tc, n_ch)
        with rcol:
            st.markdown("##### Testing Status")
            if selected_id is None:
                st.write("—")
            elif selected_id == PASTED_SCENARIO_ID:
                sk = f"test_results_status_{scenario_key}"
                st.write(str(st.session_state.get(sk, "In Progress")))
            else:
                st.write(
                    display_label_for_review_state(
                        catalog.get(selected_id, {}).get("review_state")
                    )
                )

if app_view == "Title Screen":
    render_title_screen(counts_by_state=count_saved_by_review_state())

elif app_view == "AI Scenario Builder":
    render_scenario_builder_page(pending_select_key=_PENDING_SCENARIO_SELECT_KEY)

elif app_view == "Overview":
    if not role_can_access_scenario_review(st.session_state.get(APP_ROLE_KEY)):
        st.error("Scenario Review is not available for the **Tester** role. Switch role or use **AI Scenario Builder**.")
        st.stop()
    # Re-resolve from disk/registry here so Scope & Context and Test Results always match
    # the latest saved JSON for the sidebar selection (independent of sidebar block ordering).
    catalog = build_scenario_catalog()
    selected_id = st.session_state.get(_SCENARIO_SELECT_KEY)
    data, scenario_key = _resolve_scenario_data(catalog=catalog, selected_id=selected_id)
    test_cases = data.get("test_cases", [])

    tab1, tab2 = st.tabs(["Scope & Context", "Test Results"])

    traceability_matrix = generate_traceability_matrix(data)

    with tab1:
        st.markdown("### Scenario title")
        disp_title = str(data.get("scenario_title") or data.get("story_title") or "").strip()
        st.write(disp_title if disp_title else "— (not set)")

        st.markdown("### Business Goal")
        bg = data.get("business_goal")
        st.write(bg if bg not in (None, "") else "— (not set)")

        render_acceptance_criteria_snapshot(traceability_matrix)

        st.markdown("### Changed Areas")
        changed = data.get("changed_areas", [])
        if changed:
            st.dataframe(pd.DataFrame(changed), use_container_width=True, hide_index=True)
        else:
            st.info("No changed areas were included for this scenario.")

        st.markdown("### Known Dependencies")
        deps = data.get("known_dependencies", [])
        if deps:
            st.dataframe(
                pd.DataFrame({"Dependency": deps}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No dependencies were listed for this scenario.")

        render_workflow_level_screenshots(data)

        um_ids = unmapped_test_case_ids(data)
        if um_ids:
            st.markdown("#### Unmapped test cases")
            st.warning(
                "These test case ids are not listed on any acceptance criterion’s `test_case_ids`. "
                "Link each test to at least one AC before **Approved** is allowed in **Test Results**: "
                + ", ".join(um_ids)
            )

    with tab2:
        _rid = (
            selected_id
            if selected_id and selected_id != PASTED_SCENARIO_ID
            else None
        )
        _meta = catalog.get(selected_id) if _rid else None
        _render_review_synthesis_tab(
            data,
            test_cases,
            scenario_key,
            traceability_matrix,
            checklist_items_global,
            registry_id=_rid,
            catalog_meta=_meta,
            can_change_testing_status=role_can_change_testing_status(
                st.session_state.get(APP_ROLE_KEY)
            ),
        )

elif app_view == "Scenario Management":
    render_scenario_management_page(
        scenario_select_key=_SCENARIO_SELECT_KEY,
        pending_select_key=_PENDING_SCENARIO_SELECT_KEY,
        import_preview_key=_IMPORT_PREVIEW_KEY,
        import_preview_source_key=_IMPORT_PREVIEW_SOURCE_KEY,
        json_use_pasted=_JSON_USE_PASTED,
        json_pasted_data=_JSON_PASTED_DATA,
        show_archived_key=_SHOW_ARCHIVED_SCENARIOS_KEY,
        role=st.session_state.get(APP_ROLE_KEY),
    )

elif app_view == "File Upload":
    render_file_upload_page(
        mgmt_flash_success_key=_MGMT_FLASH_SUCCESS,
        import_preview_key=_IMPORT_PREVIEW_KEY,
        import_preview_source_key=_IMPORT_PREVIEW_SOURCE_KEY,
        pending_scenario_select_key=_PENDING_SCENARIO_SELECT_KEY,
    )

else:
    st.error("Unknown app view.")

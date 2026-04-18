"""
Scenario Management: saved registry rows grouped by review_state (four editable tables + Apply).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.intake_parser import load_scenario
from src.app_roles import (
    normalize_role,
    role_can_change_registry_review_state,
    role_can_delete_scenarios,
)
from src.ui_scenario_builder import queue_builder_load_from_registry
from src.scenario_registry import (
    PASTED_SCENARIO_ID,
    REVIEW_STATE_DISPLAY_LABELS,
    build_scenario_catalog,
    delete_saved_scenario,
    display_label_for_review_state,
    internal_review_state_from_display,
    load_registry_saved,
    normalize_review_state,
    sorted_scenario_ids,
    update_saved_scenario_review_state_direct,
)

# Must match app.py `_PENDING_APP_VIEW_KEY` target — applied before sidebar `app_view` widget binds.
_PENDING_APP_VIEW_KEY = "_pending_app_view"
_EDIT_OPEN_LABEL = "Open in builder"
_EDIT_IDLE_LABEL = "—"

# Render order: (section heading, internal review_state key)
_TABLE_SECTIONS: list[tuple[str, str]] = [
    ("Approved", "approved"),
    ("In Review", "in_review"),
    ("In Progress", "in_progress"),
    ("Incomplete", "incomplete"),
    ("Archived", "archived"),
]


def _mgmt_column_config(
    labels: list[str],
    *,
    editable_review_state: bool,
    include_delete_column: bool,
) -> dict:
    cfg: dict = {
        "scenario_id": st.column_config.TextColumn("scenario_id", disabled=True),
        "source": st.column_config.TextColumn("source", disabled=True),
        "title": st.column_config.TextColumn("title", disabled=True),
        "edit": st.column_config.SelectboxColumn(
            "edit",
            options=[_EDIT_IDLE_LABEL, _EDIT_OPEN_LABEL],
            required=True,
        ),
    }
    if editable_review_state:
        cfg["review_state"] = st.column_config.SelectboxColumn(
            "review_state",
            options=labels,
            required=True,
        )
    else:
        cfg["review_state"] = st.column_config.TextColumn("review_state", disabled=True)
    if include_delete_column:
        cfg["delete"] = st.column_config.SelectboxColumn(
            "delete",
            options=["no", "yes"],
            required=True,
        )
    return cfg


def _build_mgmt_table_rows() -> pd.DataFrame:
    rows: list[dict] = []
    for row in sorted(
        load_registry_saved(), key=lambda r: (r["label"].lower(), r["id"])
    ):
        rid = row["id"]
        path = row.get("path", "")
        try:
            loaded = load_scenario(path)
            scen_id = str(loaded.get("scenario_id") or "").strip() or rid
        except Exception:
            scen_id = rid
        rs_int = normalize_review_state(row.get("review_state"))
        rs_label = display_label_for_review_state(rs_int)
        rows.append(
            {
                "_registry_id": rid,
                "_internal_rs": rs_int,
                "scenario_id": scen_id,
                "source": "Saved",
                "title": row.get("label", ""),
                "review_state": rs_label,
                "delete": "no",
                "edit": _EDIT_IDLE_LABEL,
            }
        )
    return pd.DataFrame(rows)


def _split_by_internal_state(full: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for _, internal in _TABLE_SECTIONS:
        sub = full[full["_internal_rs"] == internal].copy().reset_index(drop=True)
        out[internal] = sub
    return out


def _advance_selection_after_delete(
    deleted_id: str,
    *,
    scenario_select_key: str,
    pending_select_key: str,
    import_preview_key: str,
    import_preview_source_key: str,
    json_use_pasted: str,
    json_pasted_data: str,
    show_archived_key: str,
) -> None:
    if st.session_state.get(scenario_select_key) != deleted_id:
        return
    cat = build_scenario_catalog()
    sorted_ids = sorted_scenario_ids(cat)
    show_ar = bool(st.session_state.get(show_archived_key, False))
    filtered_next = [
        s
        for s in sorted_ids
        if show_ar or cat[s].get("review_state", "in_progress") != "archived"
    ]
    pasted_ok = bool(
        st.session_state.get(json_use_pasted) and st.session_state.get(json_pasted_data)
    )
    next_ids = filtered_next + ([PASTED_SCENARIO_ID] if pasted_ok else [])
    if next_ids:
        st.session_state[pending_select_key] = next_ids[0]


def _try_consume_mgmt_edit_navigation(
    base_sub: pd.DataFrame,
    edited: pd.DataFrame,
    *,
    editor_session_suffix: str,
    editor_role_tag: str,
) -> None:
    """
    If a row's **edit** column was set to **Open in builder**, queue load and defer app view change
    until the next run (before the sidebar selectbox is instantiated).

    ``editor_session_suffix`` must match the ``internal`` review-state segment used in
    ``st.data_editor(..., key=f"scenario_mgmt_editor_{internal}_{editor_role_tag}")`` so the correct widget state is cleared.
    """
    if base_sub.empty or "edit" not in edited.columns:
        return
    rid_series = base_sub["_registry_id"].tolist()
    for i, rid in enumerate(rid_series):
        prev = str(base_sub.iloc[i].get("edit", _EDIT_IDLE_LABEL)).strip()
        cur = str(edited.iloc[i].get("edit", _EDIT_IDLE_LABEL)).strip()
        if cur != _EDIT_OPEN_LABEL or prev == _EDIT_OPEN_LABEL:
            continue
        queue_builder_load_from_registry(str(rid))
        st.session_state[_PENDING_APP_VIEW_KEY] = "AI Scenario Builder"
        st.session_state.pop(
            f"scenario_mgmt_editor_{editor_session_suffix}_{editor_role_tag}", None
        )
        st.rerun()


def _clear_import_preview_if_match(
    deleted_id: str, import_preview_key: str, import_preview_source_key: str
) -> None:
    prev = st.session_state.get(import_preview_key)
    if isinstance(prev, dict) and str(prev.get("scenario_id") or "").strip() == deleted_id:
        st.session_state[import_preview_key] = None
        st.session_state.pop(import_preview_source_key, None)


def render_scenario_management_page(
    *,
    scenario_select_key: str,
    pending_select_key: str,
    import_preview_key: str,
    import_preview_source_key: str,
    json_use_pasted: str,
    json_pasted_data: str,
    show_archived_key: str,
    role: str | None = None,
) -> None:
    r = normalize_role(role)
    can_delete = role_can_delete_scenarios(r)
    can_edit_rs = role_can_change_registry_review_state(r)
    can_apply_registry = can_delete or can_edit_rs

    st.markdown("# Scenario Management")
    if not can_apply_registry:
        st.caption(
            "Locate scenarios and use **Open in builder** to edit in **AI Scenario Builder** "
            "(loads in **Classic** view — all sections on one page). "
            "**Review state** is read-only for your role; **Apply** is disabled—use **Test Lead** or **Test Manager** "
            "for approval-style registry updates."
        )
    elif not can_delete:
        st.caption(
            "Edit **review state**, then **Apply**. "
            "Use **Open in builder** to load a scenario into **AI Scenario Builder** in **Classic** layout "
            "(all sections on one page; navigation applies immediately). "
            "**Delete** is reserved for **Test Manager**. Scenarios are grouped by current review state. "
            "Saved scenarios may come from **AI Scenario Builder**, **File Upload** (DOCX), or earlier imports — "
            "use **Scenario Review → Show archived scenarios** to include archived in the scenario dropdown."
        )
    else:
        st.caption(
            "Edit **review state** or mark **delete** = yes, then **Apply**. "
            "Use the **edit** column (**Open in builder**) to load a scenario into **AI Scenario Builder** in **Classic** "
            "layout (navigation applies immediately). Scenarios are grouped by current review state; after **Apply**, rows refresh into the "
            "matching section. Saved scenarios may come from **AI Scenario Builder**, **File Upload** (DOCX), or "
            "earlier imports — use **Scenario Review → Show archived scenarios** to include archived in the scenario dropdown."
        )

    full_df = _build_mgmt_table_rows()
    if full_df.empty:
        st.info(
            "No saved scenarios yet. Create one in **AI Scenario Builder**, or use **File Upload** to import a DOCX."
        )
        return

    labels = list(REVIEW_STATE_DISPLAY_LABELS.values())
    col_cfg = _mgmt_column_config(
        labels,
        editable_review_state=can_edit_rs,
        include_delete_column=can_delete,
    )
    by_state = _split_by_internal_state(full_df)

    drop_extra = ["_registry_id", "_internal_rs"]
    if not can_delete:
        drop_extra.append("delete")

    _editor_role_tag = r.replace(" ", "_")
    group_edited: dict[str, pd.DataFrame | None] = {}
    for heading, internal in _TABLE_SECTIONS:
        st.subheader(heading)
        base_sub = by_state[internal]
        if base_sub.empty:
            st.caption(f"No scenarios in **{heading}**.")
            group_edited[internal] = None
            continue
        display_df = base_sub.drop(columns=drop_extra, errors="ignore")
        edited = st.data_editor(
            display_df,
            column_config=col_cfg,
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key=f"scenario_mgmt_editor_{internal}_{_editor_role_tag}",
        )
        group_edited[internal] = edited
        if edited is not None:
            _try_consume_mgmt_edit_navigation(
                base_sub,
                edited,
                editor_session_suffix=internal,
                editor_role_tag=_editor_role_tag,
            )

    apply_help = None
    if not can_apply_registry:
        apply_help = "Your role cannot change registry review state or delete scenarios."
    if st.button(
        "Apply",
        key="scenario_mgmt_apply_btn",
        type="primary",
        disabled=not can_apply_registry,
        help=apply_help,
    ):
        any_err = False
        deleted_ids: list[str] = []
        for heading, internal in _TABLE_SECTIONS:
            base_sub = by_state[internal]
            edited = group_edited.get(internal)
            if base_sub.empty or edited is None:
                continue
            if len(edited) != len(base_sub):
                st.error(f"Table shape mismatch in **{heading}**; refresh the page.")
                return
            rid_series = base_sub["_registry_id"].tolist()
            for i, rid in enumerate(rid_series):
                row = edited.iloc[i]
                if can_delete and str(row.get("delete", "no")).strip().lower() == "yes":
                    if delete_saved_scenario(rid):
                        deleted_ids.append(rid)
                        _clear_import_preview_if_match(
                            rid, import_preview_key, import_preview_source_key
                        )
                    else:
                        st.warning(f"Could not delete `{rid}` (missing row or bundled).")
                        any_err = True
                elif can_edit_rs:
                    want = internal_review_state_from_display(row.get("review_state"))
                    if not update_saved_scenario_review_state_direct(rid, want):
                        if want == "approved":
                            st.warning(
                                f"Could not set **`{rid}`** to **Approved**: on-disk scenario is still structurally "
                                "**Incomplete**. Edit in **AI Scenario Builder** (or fix JSON), **save**, then try again."
                            )
                        else:
                            st.warning(f"Could not update review state for `{rid}`.")
                        any_err = True
        cur_sel = st.session_state.get(scenario_select_key)
        if cur_sel in deleted_ids:
            _advance_selection_after_delete(
                str(cur_sel),
                scenario_select_key=scenario_select_key,
                pending_select_key=pending_select_key,
                import_preview_key=import_preview_key,
                import_preview_source_key=import_preview_source_key,
                json_use_pasted=json_use_pasted,
                json_pasted_data=json_pasted_data,
                show_archived_key=show_archived_key,
            )
        if not any_err:
            st.success("Changes applied.")
        st.rerun()

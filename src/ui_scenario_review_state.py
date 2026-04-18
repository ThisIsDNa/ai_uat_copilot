"""
Scenario-level review state controls (registry-backed; Streamlit only).
"""

from __future__ import annotations

import streamlit as st

from src.scenario_registry import (
    allowed_review_targets,
    normalize_review_state,
    set_saved_scenario_review_state,
)


def _format_state_label(s: str) -> str:
    return str(s).replace("_", " ").title()


def render_saved_scenario_review_state_panel(saved_rows: list[dict]) -> None:
    """Per saved registry row: show current state, allowed targets, Apply."""
    if not saved_rows:
        return
    st.subheader("Review state")
    st.caption(
        "Saved scenarios only. **Archived** are hidden from **Overview** unless "
        "**Show archived scenarios** is checked in the sidebar. Content is never deleted when archived."
    )
    for row in sorted(saved_rows, key=lambda r: (r["label"].lower(), r["id"])):
        rid = row["id"]
        cur = normalize_review_state(row.get("review_state"))
        targets = allowed_review_targets(cur)
        choices: list[str] = []
        seen: set[str] = set()
        for x in [cur] + targets:
            if x not in seen:
                seen.add(x)
                choices.append(x)
        c0, c1, c2 = st.columns((2, 2, 1))
        with c0:
            st.markdown(f"**`{rid}`** — {row.get('label', '')}")
        with c1:
            ix = choices.index(cur) if cur in choices else 0
            pick = st.selectbox(
                "State",
                options=choices,
                index=ix,
                format_func=_format_state_label,
                key=f"review_state_select_{rid}",
                label_visibility="collapsed",
            )
        with c2:
            if st.button("Apply", key=f"review_state_apply_{rid}"):
                if pick != cur and set_saved_scenario_review_state(rid, pick):
                    st.rerun()
                elif pick != cur:
                    st.error("Could not update state (invalid transition or missing row).")

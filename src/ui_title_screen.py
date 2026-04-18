"""
Landing / title view: neutral entry point before choosing a scenario.
"""

from __future__ import annotations

import streamlit as st


def render_title_screen(*, counts_by_state: dict[str, int] | None = None) -> None:
    st.markdown("# AI UAT Copilot")
    st.markdown("##### Quick Stats")
    st.caption(
        "Counts are **saved scenarios in the registry** by **review state** (not past-month analytics)."
    )
    c = counts_by_state or {}
    ap = c.get("approved", 0)
    ar = c.get("archived", 0)
    inc = c.get("incomplete", 0)
    ip = c.get("in_progress", 0)
    ir = c.get("in_review", 0)
    st.markdown(
        "<div style='margin-bottom:0.35rem;line-height:1.55;'>"
        f"<strong>Approved:</strong> {ap}<br/>"
        f"<strong>Archived:</strong> {ar}<br/>"
        f"<strong>In Review:</strong> {ir}<br/>"
        f"<strong>In Progress:</strong> {ip}<br/>"
        f"<strong>Incomplete:</strong> {inc}"
        "</div>",
        unsafe_allow_html=True,
    )

"""
Optional evidence images for JSON import: save under data/json_upload_media/<scenario_slug>/
and rewrite scenario paths when basenames match (case-insensitive).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.scenario_media import resolve_media_path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSON_UPLOAD_MEDIA_ROOT = _PROJECT_ROOT / "data" / "json_upload_media"


def iter_scenario_screenshot_reference_paths(scenario: dict) -> list[str]:
    """
    Unique non-empty paths from workflow_process_screenshots and
    test_cases[].expected_step_screenshots (strings or path objects), stable order.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in scenario.get("workflow_process_screenshots") or []:
        if isinstance(item, str):
            p = item.strip()
        elif isinstance(item, dict):
            p = str(item.get("path") or "").strip()
        else:
            continue
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    for tc in scenario.get("test_cases") or []:
        if not isinstance(tc, dict):
            continue
        for item in tc.get("expected_step_screenshots") or []:
            if isinstance(item, str):
                p = item.strip()
            elif isinstance(item, dict):
                p = str(item.get("path") or "").strip()
            else:
                continue
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def partition_scenario_screenshot_paths(
    scenario: dict,
) -> tuple[list[str], list[str]]:
    """(existing_on_disk, missing) using the same resolution rules as the UI."""
    existing: list[str] = []
    missing: list[str] = []
    for p in iter_scenario_screenshot_reference_paths(scenario):
        if resolve_media_path(p):
            existing.append(p)
        else:
            missing.append(p)
    return existing, missing


def sanitize_scenario_folder_name(scenario_id: str) -> str:
    """Filesystem-safe folder name derived from scenario_id."""
    s = (scenario_id or "scenario").strip() or "scenario"
    s = re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE)
    s = s.strip("._") or "scenario"
    return s[:120]


def save_uploaded_evidence_images(scenario_id: str, uploaded_files: list) -> dict[str, str]:
    """
    Write Streamlit UploadedFile-like objects to JSON_UPLOAD_MEDIA_ROOT/<slug>/.

    Returns mapping: lowercase basename -> project-relative posix path.
    Same basename uploaded twice: last write wins.
    """
    slug = sanitize_scenario_folder_name(scenario_id)
    dest_dir = JSON_UPLOAD_MEDIA_ROOT / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for uf in uploaded_files:
        raw_name = getattr(uf, "name", None) or "image.png"
        name = Path(str(raw_name)).name
        if not name or name in (".", ".."):
            continue
        try:
            uf.seek(0)
        except Exception:
            pass
        dest = dest_dir / name
        dest.write_bytes(uf.read())
        rel = str(dest.relative_to(_PROJECT_ROOT)).replace("\\", "/")
        mapping[name.lower()] = rel
    return mapping


def rewrite_scenario_screenshot_paths(
    scenario: dict, basename_to_rel: dict[str, str]
) -> int:
    """
    In-place: replace path strings when Path(original).name.lower() is in basename_to_rel.

    Touches workflow_process_screenshots and each test_cases[].expected_step_screenshots
    (string or {"path": ...} entries per docs/schema.md).
    """
    if not basename_to_rel:
        return 0

    def maybe_rewrite(path_str: str) -> tuple[str, bool]:
        s = (path_str or "").strip()
        if not s:
            return path_str, False
        base = Path(s.replace("\\", "/")).name.lower()
        if base in basename_to_rel:
            return basename_to_rel[base], True
        return path_str, False

    n = 0
    wf = scenario.get("workflow_process_screenshots")
    if isinstance(wf, list):
        for i, item in enumerate(wf):
            if isinstance(item, str):
                newp, ch = maybe_rewrite(item)
                if ch:
                    wf[i] = newp
                    n += 1
            elif isinstance(item, dict):
                p = str(item.get("path") or "")
                newp, ch = maybe_rewrite(p)
                if ch:
                    item["path"] = newp
                    n += 1

    tcs = scenario.get("test_cases")
    if isinstance(tcs, list):
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            ess = tc.get("expected_step_screenshots")
            if not isinstance(ess, list):
                continue
            for i, item in enumerate(ess):
                if isinstance(item, str):
                    newp, ch = maybe_rewrite(item)
                    if ch:
                        ess[i] = newp
                        n += 1
                elif isinstance(item, dict):
                    p = str(item.get("path") or "")
                    newp, ch = maybe_rewrite(p)
                    if ch:
                        item["path"] = newp
                        n += 1
    return n

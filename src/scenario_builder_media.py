"""
Save Scenario Builder uploads under data/json_upload_media/<scenario_slug>/ (same root as JSON import).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, MutableMapping

from src.json_import_media import JSON_UPLOAD_MEDIA_ROOT, sanitize_scenario_folder_name

# Bumped when TC rows are compacted so Streamlit file_uploaders get fresh keys (never assign to uploader state).
_SB_UPLOAD_EPOCH_KEY = "sb_upload_widget_epoch"


def tc_step_upload_widget_key(sess: Mapping[str, Any], j: int, k: int) -> str:
    """Session key for a step screenshot file uploader (must not be written programmatically)."""
    e = int(sess.get(_SB_UPLOAD_EPOCH_KEY) or 0)
    return f"sb_tc_{j}_step_{k}_file_e{e}"


def tc_bulk_step_upload_widget_key(sess: Mapping[str, Any], j: int) -> str:
    """Session key for multi-file bulk step screenshot uploader for test case row ``j``."""
    e = int(sess.get(_SB_UPLOAD_EPOCH_KEY) or 0)
    return f"sb_tc_{j}_bulk_step_file_e{e}"


def bulk_upload_file_indices_for_step(step_index: int, n_steps: int, n_files: int) -> list[int]:
    """
    Indices ``i`` in ``0..n_files-1`` whose bulk upload maps to ``step_index`` (0-based),
    using the same rule as :func:`persist_bulk_tc_step_screenshot_uploads` (``i % n_steps``).
    """
    n_st = max(int(n_steps), 1)
    return [mi for mi in range(max(n_files, 0)) if mi % n_st == step_index]


def bump_upload_widget_epoch(sess: MutableMapping[str, Any]) -> None:
    """Increment so compacted TC rows bind to fresh file_uploader widget keys on rerun."""
    e = int(sess.get(_SB_UPLOAD_EPOCH_KEY) or 0)
    sess[_SB_UPLOAD_EPOCH_KEY] = e + 1


def clear_tc_step_file_uploader_session_keys(sess: MutableMapping[str, Any], j: int, k: int) -> None:
    """Remove any session keys used by Streamlit file_uploaders for this step (never assign to these)."""
    p = f"sb_tc_{j}_step_{k}_file"
    sess.pop(p, None)
    for key in list(sess.keys()):
        if isinstance(key, str) and key.startswith(p + "_e"):
            sess.pop(key, None)


def _write_upload(dest: Path, uf: Any) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        uf.seek(0)
    except Exception:
        pass
    dest.write_bytes(uf.read())


def persist_workflow_screenshot_uploads(
    sess: Mapping[str, Any],
    scenario_id: str,
) -> tuple[list[str], bool]:
    """
    Persist ``sb_wf_upload`` files; return (project-relative posix paths in upload order, replaced_existing_file).
    """
    raw = sess.get("sb_wf_upload")
    if raw is None:
        return [], False
    files = raw if isinstance(raw, list) else [raw]
    slug = sanitize_scenario_folder_name(scenario_id)
    dest_dir = JSON_UPLOAD_MEDIA_ROOT / slug
    project_root = JSON_UPLOAD_MEDIA_ROOT.parent.parent
    out: list[str] = []
    replaced = False
    for i, uf in enumerate(files):
        if uf is None or not hasattr(uf, "read"):
            continue
        raw_name = getattr(uf, "name", None) or "workflow.png"
        name = Path(str(raw_name)).name
        if not name or name in (".", ".."):
            continue
        suf = Path(name).suffix.lower()
        if suf not in (".png", ".jpg", ".jpeg"):
            suf = ".png"
        fname = f"workflow_screenshot_{i + 1:02d}{suf}"
        dest = dest_dir / fname
        if dest.exists():
            replaced = True
        _write_upload(dest, uf)
        out.append(str(dest.relative_to(project_root)).replace("\\", "/"))
    if out and isinstance(sess, MutableMapping):
        prior = sess.get("sb_wf_persisted_paths")
        merged: list[str] = []
        if isinstance(prior, list):
            merged = [str(x).strip() for x in prior if str(x).strip()]
        for p in out:
            ps = (p or "").strip()
            if ps and ps not in merged:
                merged.append(ps)
        sess["sb_wf_persisted_paths"] = merged
    return out, replaced


def persist_step_screenshot_uploads(
    sess: Mapping[str, Any],
    scenario_id: str,
    *,
    n_tc: int,
    n_steps_for_tc: list[int],
) -> tuple[dict[tuple[int, int], list[str]], bool]:
    """
    Persist step screenshot upload widgets (single or multiple files per slot).

    Returns ((tc_index, step_index) -> list of project-relative posix paths, replaced_existing_file_anywhere).
    """
    slug = sanitize_scenario_folder_name(scenario_id)
    dest_dir = JSON_UPLOAD_MEDIA_ROOT / slug
    project_root = JSON_UPLOAD_MEDIA_ROOT.parent.parent
    out: dict[tuple[int, int], list[str]] = {}
    replaced = False
    for j in range(n_tc):
        n_st = n_steps_for_tc[j] if j < len(n_steps_for_tc) else 0
        for k in range(n_st):
            key = tc_step_upload_widget_key(sess, j, k)
            uf = sess.get(key)
            files: list[Any] = []
            if isinstance(uf, list):
                files = [x for x in uf if x is not None and hasattr(x, "read")]
            elif uf is not None and hasattr(uf, "read"):
                files = [uf]
            if not files:
                continue
            paths_out: list[str] = []
            prior_list = sess.get(f"sb_tc_{j}_step_{k}_persisted_paths")
            prior_single = str(sess.get(f"sb_tc_{j}_step_{k}_persisted_path") or "").strip()
            if isinstance(prior_list, list) and prior_list:
                replaced = True
            elif prior_single:
                replaced = True
            for mi, fobj in enumerate(files):
                raw_name = getattr(fobj, "name", None) or "step.png"
                suf = Path(str(raw_name)).suffix.lower()
                if suf not in (".png", ".jpg", ".jpeg"):
                    suf = ".png"
                fname = f"tc_{j + 1:02d}_step_{k + 1:02d}_{mi + 1:02d}{suf}"
                dest = dest_dir / fname
                if dest.exists():
                    replaced = True
                _write_upload(dest, fobj)
                rel = str(dest.relative_to(project_root)).replace("\\", "/")
                paths_out.append(rel)
            if paths_out:
                out[(j, k)] = paths_out
    return out, replaced


def persist_bulk_tc_step_screenshot_uploads(
    sess: MutableMapping[str, Any],
    scenario_id: str,
    *,
    n_tc: int,
    n_steps_for_tc: list[int],
) -> bool:
    """
    Persist ``tc_bulk_step_upload_widget_key`` uploads: assign files in upload order across
    steps with ``i % n_steps`` (first file → step 1, second → step 2, …; one file per step
    until step count is exceeded, then round-robin). Appends paths to session
    ``persisted_paths`` / ``persisted_path`` for each step. Clears each processed uploader key.
    """
    slug = sanitize_scenario_folder_name(scenario_id)
    dest_dir = JSON_UPLOAD_MEDIA_ROOT / slug
    project_root = JSON_UPLOAD_MEDIA_ROOT.parent.parent
    replaced = False
    for j in range(n_tc):
        if sess.get(f"sb_tc_{j}_active", True) is False:
            continue
        nst = n_steps_for_tc[j] if j < len(n_steps_for_tc) else 1
        if nst < 1:
            continue
        n_st = max(nst, 1)
        key = tc_bulk_step_upload_widget_key(sess, j)
        raw = sess.get(key)
        files: list[Any] = []
        if isinstance(raw, list):
            files = [x for x in raw if x is not None and hasattr(x, "read")]
        elif raw is not None and hasattr(raw, "read"):
            files = [raw]
        if not files:
            continue
        for mi, fobj in enumerate(files):
            k = mi % n_st
            raw_name = getattr(fobj, "name", None) or "step.png"
            suf = Path(str(raw_name)).suffix.lower()
            if suf not in (".png", ".jpg", ".jpeg"):
                suf = ".png"
            fname = f"tc_{j + 1:02d}_step_{k + 1:02d}_bulk_{mi + 1:02d}{suf}"
            dest = dest_dir / fname
            if dest.exists():
                replaced = True
            _write_upload(dest, fobj)
            rel = str(dest.relative_to(project_root)).replace("\\", "/")

            plist = sess.get(f"sb_tc_{j}_step_{k}_persisted_paths")
            prior_single = str(sess.get(f"sb_tc_{j}_step_{k}_persisted_path") or "").strip()
            merged: list[str] = []
            if isinstance(plist, list):
                merged = [str(x).strip() for x in plist if str(x).strip()]
            elif prior_single:
                merged = [prior_single]
            if merged:
                replaced = True
            merged.append(rel)
            if len(merged) == 1:
                sess[f"sb_tc_{j}_step_{k}_persisted_path"] = merged[0]
                sess.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)
            else:
                sess[f"sb_tc_{j}_step_{k}_persisted_paths"] = merged
                sess.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)

        sess.pop(key, None)
    return replaced

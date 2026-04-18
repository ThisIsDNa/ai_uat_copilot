"""
Scenario catalog: optional bundled JSON + user-saved scenarios (from DOCX or JSON import).

Metadata (source type, display label, file path, optional review_state) lives in code +
`data/scenario_registry.json`. Persisted scenario JSON files remain schema-focused;
review lifecycle fields are stored on the registry row.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.scenario_media import strip_ingestion_meta_for_persist
from src.scenario_review_summary import registry_auto_review_state_for_scenario

SourceType = Literal["json", "docx"]

REVIEW_STATES: tuple[str, ...] = (
    "incomplete",
    "in_progress",
    "in_review",
    "approved",
    "archived",
)


def normalize_review_state(raw: object) -> str:
    s = str(raw or "").strip()
    return s if s in REVIEW_STATES else "in_progress"


# UI labels for scenario management table / sidebar (Title Case).
REVIEW_STATE_DISPLAY_LABELS: dict[str, str] = {
    "incomplete": "Incomplete",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "approved": "Approved",
    "archived": "Archived",
}

_DISPLAY_TO_INTERNAL: dict[str, str] = {
    v: k for k, v in REVIEW_STATE_DISPLAY_LABELS.items()
}


def display_label_for_review_state(internal: str) -> str:
    return REVIEW_STATE_DISPLAY_LABELS.get(normalize_review_state(internal), internal)


def internal_review_state_from_display(label: object) -> str:
    s = str(label or "").strip()
    if s in _DISPLAY_TO_INTERNAL:
        return _DISPLAY_TO_INTERNAL[s]
    return normalize_review_state(s)


def allowed_review_targets(current: str) -> list[str]:
    """Supported transitions (intentional but not a strict workflow engine)."""
    cur = normalize_review_state(current)
    if cur == "archived":
        return ["incomplete", "in_progress", "in_review"]
    if cur == "incomplete":
        return ["in_progress", "in_review", "archived"]
    if cur == "in_progress":
        return ["incomplete", "in_review", "approved", "archived"]
    if cur == "in_review":
        return ["incomplete", "in_progress", "approved", "archived"]
    if cur == "approved":
        return ["archived"]
    return ["in_progress"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def count_saved_by_review_state() -> dict[str, int]:
    """Counts over registry `saved` rows only (not pasted session)."""
    out: dict[str, int] = {k: 0 for k in REVIEW_STATES}
    for row in load_registry_saved():
        out[normalize_review_state(row.get("review_state"))] += 1
    return out


def _load_saved_scenario_dict_for_guard(row: dict) -> dict | None:
    """Load scenario JSON for a registry row (used before allowing **approved**)."""
    path = str(row.get("path") or "").strip()
    if not path:
        return None
    full = _PROJECT_ROOT / path.replace("\\", "/")
    try:
        from src.intake_parser import load_scenario

        return load_scenario(str(full))
    except Exception:
        return None


def saved_scenario_structurally_allows_approved(row: dict) -> bool:
    """True when on-disk JSON passes structural completeness checks for approval."""
    from src.scenario_review_summary import is_scenario_registry_incomplete

    data = _load_saved_scenario_dict_for_guard(row)
    if not isinstance(data, dict):
        return False
    return not is_scenario_registry_incomplete(data)


def set_saved_scenario_review_state(scenario_id: str, new_state: str) -> bool:
    """
    Update review_state for a saved registry row. Returns False if id missing or
    transition not in allowed_review_targets.
    """
    if new_state not in REVIEW_STATES:
        return False
    saved = load_registry_saved()
    idx = next((i for i, r in enumerate(saved) if r["id"] == scenario_id), None)
    if idx is None:
        return False
    row = dict(saved[idx])
    cur = normalize_review_state(row.get("review_state"))
    if new_state == cur:
        return True
    if new_state not in allowed_review_targets(cur):
        return False
    if new_state == "approved" and not saved_scenario_structurally_allows_approved(row):
        return False
    row["review_state"] = new_state
    row["review_state_updated_at"] = _utc_now_iso()
    saved[idx] = row
    _save_registry_saved(saved)
    return True


def update_saved_scenario_review_state_direct(scenario_id: str, new_state: str) -> bool:
    """
    Set review_state without transition rules (Scenario Management batch table).
    """
    if new_state not in REVIEW_STATES:
        return False
    saved = load_registry_saved()
    idx = next((i for i, r in enumerate(saved) if r["id"] == scenario_id), None)
    if idx is None:
        return False
    row = dict(saved[idx])
    if normalize_review_state(row.get("review_state")) == new_state:
        return True
    if new_state == "approved" and not saved_scenario_structurally_allows_approved(row):
        return False
    row["review_state"] = new_state
    row["review_state_updated_at"] = _utc_now_iso()
    saved[idx] = row
    _save_registry_saved(saved)
    return True


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = _PROJECT_ROOT / "data" / "scenario_registry.json"
SAVED_SCENARIOS_DIR = _PROJECT_ROOT / "data" / "saved_scenarios"

# Session / UI id for in-memory pasted JSON (not persisted).
PASTED_SCENARIO_ID = "__pasted_json__"

# Optional bundled starters (id -> { source, label, path relative to project root }).
BUNDLED: dict[str, dict[str, str]] = {}


def format_scenario_dropdown_label(source: str, label: str) -> str:
    if source == "session":
        return f"[Draft] {label}"
    return str(label or "").strip() or "—"


def _path_relative_to_root(path: Path) -> str:
    return str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/")


def load_registry_saved() -> list[dict[str, str]]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            obj = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    raw = obj.get("saved")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        src = str(row.get("source") or "json").strip().lower()
        if src not in ("json", "docx"):
            src = "json"
        label = str(row.get("label") or sid).strip() or sid
        path = str(row.get("path") or "").strip()
        if sid and path:
            rs = normalize_review_state(row.get("review_state"))
            rts = str(row.get("review_state_updated_at") or "").strip()
            out.append(
                {
                    "id": sid,
                    "source": src,
                    "label": label,
                    "path": path,
                    "review_state": rs,
                    "review_state_updated_at": rts,
                }
            )
    return out


def _save_registry_saved(entries: list[dict[str, str]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump({"saved": entries}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def build_scenario_catalog() -> dict[str, dict[str, str]]:
    """id -> {source, label, path, review_state, review_state_updated_at} for bundled + saved."""
    catalog: dict[str, dict[str, str]] = {}
    for sid, meta in BUNDLED.items():
        catalog[sid] = {
            "source": meta["source"],
            "label": meta["label"],
            "path": meta["path"],
            "review_state": "in_progress",
            "review_state_updated_at": "",
        }
    for row in load_registry_saved():
        catalog[row["id"]] = {
            "source": row["source"],
            "label": row["label"],
            "path": row["path"],
            "review_state": row.get("review_state", "in_progress"),
            "review_state_updated_at": row.get("review_state_updated_at", ""),
        }
    return catalog


def sorted_scenario_ids(catalog: dict[str, dict[str, str]]) -> list[str]:
    return sorted(catalog.keys(), key=lambda sid: (catalog[sid]["label"].lower(), sid))


def _persist_scenario_to_disk(
    data: dict, original_filename: str, *, source: Literal["docx", "json"]
) -> str:
    """Write scenario JSON and upsert registry. Does not mutate `data`. Returns scenario_id."""
    sid = str(data.get("scenario_id") or "").strip()
    if not sid:
        raise ValueError("Scenario has no scenario_id")

    SAVED_SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SAVED_SCENARIOS_DIR / f"{sid}.json"
    path_rel = _path_relative_to_root(out_path)

    to_write = strip_ingestion_meta_for_persist(data) if isinstance(data, dict) else data

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(to_write, f, indent=2, ensure_ascii=False)
        f.write("\n")

    label = data.get("story_title") or Path(original_filename).stem or sid
    label = str(label).strip() if label is not None else sid
    if not label:
        label = sid

    saved = load_registry_saved()
    existing = next((r for r in saved if r["id"] == sid), None)
    others = [r for r in saved if r["id"] != sid]
    if existing:
        rs_prev = normalize_review_state(existing.get("review_state"))
        rts = str(existing.get("review_state_updated_at") or "").strip() or _utc_now_iso()
        if rs_prev in ("approved", "in_review", "archived"):
            rs = rs_prev
        else:
            rs = registry_auto_review_state_for_scenario(data if isinstance(data, dict) else {})
            if rs != rs_prev:
                rts = _utc_now_iso()
    else:
        rs = registry_auto_review_state_for_scenario(data if isinstance(data, dict) else {})
        rts = _utc_now_iso()
    others.append(
        {
            "id": sid,
            "source": source,
            "label": label,
            "path": path_rel,
            "review_state": rs,
            "review_state_updated_at": rts,
        }
    )
    others.sort(key=lambda r: (r["label"].lower(), r["id"]))
    _save_registry_saved(others)
    return sid


def persist_parsed_docx_scenario(data: dict, original_filename: str) -> str:
    """Write `data` from DOCX parse; registry `source` is docx."""
    return _persist_scenario_to_disk(data, original_filename, source="docx")


def persist_imported_json_scenario(data: dict, original_filename: str = "") -> str:
    """Write `data` from JSON file import; registry `source` is json."""
    return _persist_scenario_to_disk(data, original_filename or "scenario.json", source="json")


def is_bundled_scenario_id(scenario_id: str) -> bool:
    return scenario_id in BUNDLED


def delete_saved_scenario(scenario_id: str) -> bool:
    """
    Remove a user-saved scenario from the registry and delete its JSON file.
    Bundled scenarios cannot be deleted. Returns True if something was removed.
    """
    if scenario_id in BUNDLED:
        return False
    saved = load_registry_saved()
    row = next((r for r in saved if r["id"] == scenario_id), None)
    if not row:
        return False
    fpath = (_PROJECT_ROOT / row["path"]).resolve()
    save_root = SAVED_SCENARIOS_DIR.resolve()
    try:
        fpath.relative_to(save_root)
        if fpath.is_file():
            fpath.unlink()
    except ValueError:
        pass
    except OSError:
        return False
    _save_registry_saved([r for r in saved if r["id"] != scenario_id])
    return True

"""Resolve image paths from scenario JSON (paths relative to project root)."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_project_root() -> Path:
    return _PROJECT_ROOT


def resolve_media_path(relative_path: str) -> Path | None:
    """
    Return a resolved file path if `relative_path` is relative, stays under the project
    root, and points to an existing file.
    """
    raw = Path(relative_path)
    if raw.is_absolute():
        return None
    full = (_PROJECT_ROOT / raw).resolve()
    try:
        full.relative_to(_PROJECT_ROOT)
    except ValueError:
        return None
    if full.is_file():
        return full
    return None


# Optional intake diagnostics (stripped before persisting scenario JSON to disk).
INGESTION_META_KEY = "ingestion_meta"


def strip_ingestion_meta_for_persist(data: dict) -> dict:
    """Copy of scenario dict without ephemeral `ingestion_meta` (for saved JSON files)."""
    return {k: v for k, v in data.items() if k != INGESTION_META_KEY}


# Parser / scaffold fallbacks that must never be treated as real ``business_goal`` content.
_SPURIOUS_BUSINESS_GOAL_MARKERS: tuple[str, ...] = (
    "— (not extracted; add a Business goal section in the document.)",
    "(not extracted; add a Business goal section",
    "not extracted; add a business goal",
)
_STEP_SCAFFOLD_BUSINESS_GOAL_PREFIX = "Open or navigate to the part of the application that supports:"


def clean_business_goal_for_schema(raw: object) -> str:
    """
    User-authored business goal only — strip DOCX placeholder lines and accidental
    paste of step-scaffold boilerplate (never persist helper/prompt copy as ``business_goal``).
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    low = s.lower()
    for frag in _SPURIOUS_BUSINESS_GOAL_MARKERS:
        if frag.lower() in low:
            return ""
    if s.startswith(_STEP_SCAFFOLD_BUSINESS_GOAL_PREFIX):
        return ""
    return s


def _ingestion_meta(scenario: dict) -> dict:
    meta = scenario.get(INGESTION_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
        scenario[INGESTION_META_KEY] = meta
    meta.setdefault("warnings", [])
    return meta


def _iter_screenshot_path_strings(scenario: dict) -> list[str]:
    """Same path discovery as json_import_media (avoid import cycle at module load)."""
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


def normalize_scenario_image_paths(scenario: dict, json_dir: Path | None) -> None:
    """
    Rewrite image path strings to project-relative POSIX paths.

    For each referenced path: if it already resolves from the project root, leave it.
    Otherwise resolve ``(json_dir / path)`` when ``json_dir`` is set and under the project
    root, then store ``relative_to(project_root)``. Missing files do not raise; warnings
    go into ``scenario['ingestion_meta']['warnings']``.
    """
    if not isinstance(scenario, dict) or json_dir is None:
        return

    meta = _ingestion_meta(scenario)
    root = _PROJECT_ROOT.resolve()
    try:
        jd = json_dir.resolve()
        jd.relative_to(root)
    except ValueError:
        meta["warnings"].append(
            "JSON directory is outside the project root; skipped resolving paths next to the JSON file."
        )
        return

    n_refs = 0

    def process_path_str(stripped: str) -> str | None:
        nonlocal n_refs
        if not stripped:
            return None
        n_refs += 1
        if resolve_media_path(stripped):
            return None
        cand = (jd / stripped).resolve()
        try:
            cand.relative_to(root)
        except ValueError:
            meta["warnings"].append(
                f"Image path could not be resolved (outside project root): {stripped!r}"
            )
            return None
        new_rel = cand.relative_to(root).as_posix()
        if not cand.is_file():
            meta["warnings"].append(
                f"Referenced image not found: {new_rel} (from {stripped!r} next to JSON file)"
            )
        return new_rel

    wf = scenario.get("workflow_process_screenshots")
    if isinstance(wf, list):
        for i, item in enumerate(wf):
            if isinstance(item, str):
                s = item.strip().replace("\\", "/")
                if not s:
                    continue
                new_rel = process_path_str(s)
                if new_rel is not None:
                    wf[i] = new_rel
            elif isinstance(item, dict):
                p = str(item.get("path") or "").strip().replace("\\", "/")
                if not p:
                    continue
                new_rel = process_path_str(p)
                if new_rel is not None:
                    item["path"] = new_rel

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
                    s = item.strip().replace("\\", "/")
                    if not s:
                        continue
                    new_rel = process_path_str(s)
                    if new_rel is not None:
                        ess[i] = new_rel
                elif isinstance(item, dict):
                    p = str(item.get("path") or "").strip().replace("\\", "/")
                    if not p:
                        continue
                    new_rel = process_path_str(p)
                    if new_rel is not None:
                        item["path"] = new_rel

    meta["images_referenced"] = n_refs
    meta["images_resolved_ok"] = sum(
        1 for p in _iter_screenshot_path_strings(scenario) if resolve_media_path(p)
    )


def warn_json_upload_sibling_relative_paths(scenario: dict) -> None:
    """
    Browser JSON upload has no folder context; ``./`` / ``../`` paths cannot target
    sibling files. Adds a single warning to ``ingestion_meta`` when such paths appear.
    """
    if not isinstance(scenario, dict):
        return
    for p in _iter_screenshot_path_strings(scenario):
        s = p.strip()
        if s.startswith("./") or s.startswith("../"):
            meta = _ingestion_meta(scenario)
            meta["warnings"].append(
                "Paths starting with ./ or ../ are not resolved for file uploads—use "
                "project-root-relative paths, load JSON from disk next to images, or use **Attach images**."
            )
            return


def _parse_workflow_screenshot_item(item: object) -> tuple[str, str]:
    """Return (path, label) for one workflow screenshot entry."""
    if isinstance(item, str):
        s = item.strip()
        return (s, "")
    if isinstance(item, dict):
        p = item.get("path")
        path_str = str(p).strip() if p is not None else ""
        lb = item.get("label")
        label_str = str(lb).strip() if lb is not None and str(lb).strip() else ""
        return (path_str, label_str)
    return ("", "")


def workflow_process_screenshot_pairs(scenario: dict) -> list[tuple[str, str]]:
    """
    Non-empty workflow screenshot (path, label) pairs in JSON order.
    Supports string paths or {"path": "...", "label": "..."} objects.
    """
    raw = scenario.get("workflow_process_screenshots") or []
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str]] = []
    for item in raw:
        p, lb = _parse_workflow_screenshot_item(item)
        if p:
            out.append((p, lb))
    return out


def workflow_process_screenshots(scenario: dict) -> list[str]:
    """Scenario-level paths only (backward compatible)."""
    return [p for p, _ in workflow_process_screenshot_pairs(scenario)]


def workflow_process_screenshot_labels(scenario: dict) -> list[str]:
    """Labels parallel to `workflow_process_screenshots()` path list."""
    return [lb for _, lb in workflow_process_screenshot_pairs(scenario)]


def step_texts(test_case: dict) -> list[str]:
    """Normalize `test_cases[].steps` (strings or `{ \"text\": ... }`) to plain text."""
    steps = test_case.get("steps") or []
    out: list[str] = []
    for s in steps:
        if isinstance(s, str):
            out.append(s)
        elif isinstance(s, dict) and "text" in s:
            out.append(str(s["text"]))
        else:
            out.append(str(s))
    return out


def resolved_test_case_title(test_case: dict) -> str:
    """Human-readable test case title (builder / JSON / DOCX may use different keys)."""
    if not isinstance(test_case, dict):
        return ""
    for key in ("title", "text", "name", "summary", "test_case_name"):
        raw = test_case.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s
    return ""


def _parse_step_screenshot_entry(item: object) -> tuple[str, str, int | None]:
    """
    One expected_step_screenshots entry → (path, label, mapped_to_step_index or None).

    - str → path only, sequential placement
    - dict → path (required for non-empty), optional label, optional mapped_to_step_index (int, 0-based)
    """
    if isinstance(item, str):
        return (item.strip(), "", None)
    if isinstance(item, dict):
        p = item.get("path")
        path_str = str(p).strip() if p is not None else ""
        lb = item.get("label")
        label_str = str(lb).strip() if lb is not None and str(lb).strip() else ""
        mi = item.get("mapped_to_step_index")
        mapped: int | None = None
        if isinstance(mi, int) and not isinstance(mi, bool):
            mapped = mi if mi >= 0 else None
        elif isinstance(mi, float) and mi == int(mi):
            iv = int(mi)
            mapped = iv if iv >= 0 else None
        return (path_str, label_str, mapped)
    return ("", "", None)


def raw_step_screenshot_paths_in_json_order(test_case: dict) -> list[str]:
    """
    Paths from expected_step_screenshots in file order (strings or dict.path only).
    Used by DOCX reconcile when reading heuristic placements from mixed shapes.
    """
    raw = test_case.get("expected_step_screenshots") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        p, _, _ = _parse_step_screenshot_entry(item)
        if p:
            out.append(p)
    return out


def resolved_step_screenshots(test_case: dict) -> tuple[list[str], list[str]]:
    """
    Paths and labels aligned to len(steps): index i matches step i.

    - Entries with mapped_to_step_index are placed first at that index (last wins).
    - Remaining entries fill the first empty slots 0..n-1 in JSON order.
    - Legacy parallel expected_step_screenshot_labels fills missing labels per index.
    """
    steps = step_texts(test_case)
    n = len(steps)
    raw = test_case.get("expected_step_screenshots") or []
    if not isinstance(raw, list):
        raw = []
    legacy_labels = test_case.get("expected_step_screenshot_labels") or []
    if not isinstance(legacy_labels, list):
        legacy_labels = []

    paths = [""] * n
    labels = [""] * n
    if n == 0:
        return paths, labels

    mapped_slots: dict[int, tuple[str, str]] = {}
    sequential: list[tuple[str, str]] = []

    for item in raw:
        path_str, label_str, mapped = _parse_step_screenshot_entry(item)
        if not path_str:
            continue
        if mapped is not None and mapped < n:
            mapped_slots[mapped] = (path_str, label_str)
        else:
            sequential.append((path_str, label_str))

    for i, (p, lb) in mapped_slots.items():
        paths[i] = p
        labels[i] = lb

    q = 0
    for p, lb in sequential:
        while q < n and paths[q]:
            q += 1
        if q < n:
            paths[q] = p
            labels[q] = lb
            q += 1

    for i in range(n):
        if paths[i] and not labels[i] and i < len(legacy_labels):
            leg = legacy_labels[i]
            if leg is not None and str(leg).strip():
                labels[i] = str(leg).strip()

    return paths, labels


def expected_step_screenshot_paths(test_case: dict) -> list[str]:
    """Parallel to `steps` — one path per step (empty string if none)."""
    p, _ = resolved_step_screenshots(test_case)
    return p


def expected_step_screenshot_labels(test_case: dict) -> list[str]:
    """Parallel to paths from `expected_step_screenshot_paths` for the same test case."""
    _, lb = resolved_step_screenshots(test_case)
    return lb

"""
Assemble and validate scenario dicts for the AI Scenario Builder (schema per docs/schema.md).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Mapping, MutableMapping

from src.scenario_media import (
    _parse_step_screenshot_entry,
    clean_business_goal_for_schema,
    expected_step_screenshot_paths,
    resolved_test_case_title,
    step_texts,
    workflow_process_screenshot_pairs,
)
from src.scenario_builder_media import clear_tc_step_file_uploader_session_keys
from src.ui_import import _normalize_pasted_scenario, _validate_scenario_upload_shape

# Session keys copied from the guided snapshot when the live value is empty (widgets unmounted).
_GUIDED_SNAPSHOT_STR_BACKFILL_KEYS: tuple[str, ...] = (
    "sb_scenario_context",
    "sb_story_title",
    "sb_workflow_name",
    "sb_business_goal",
    "sb_changed_areas_bulk",
    "sb_known_dependencies_bulk",
    "sb_notes",
)


def apply_guided_snapshot_backfill(sess: MutableMapping[str, Any], snap: Mapping[str, Any] | None) -> None:
    """
    When guided steps unmount, Streamlit may leave ``sb_*`` keys as empty strings so
    ``setdefault``/restore never repopulate from the last good values. Merge non-empty
    snapshot values for core scenario fields (and workflow screenshot paths) in that case.
    """
    if not isinstance(snap, Mapping):
        return
    for k in _GUIDED_SNAPSHOT_STR_BACKFILL_KEYS:
        v = snap.get(k)
        if not isinstance(v, str) or not v.strip():
            continue
        cur = sess.get(k)
        if cur is None or (isinstance(cur, str) and not str(cur).strip()):
            sess[k] = copy.deepcopy(v)
    v_sid = snap.get("sb_scenario_id")
    if isinstance(v_sid, str) and v_sid.strip():
        cur_sid = sess.get("sb_scenario_id")
        if cur_sid is None or (isinstance(cur_sid, str) and not str(cur_sid).strip()):
            sess["sb_scenario_id"] = copy.deepcopy(v_sid)
    snap_wf = snap.get("sb_wf_persisted_paths")
    sess_wf = sess.get("sb_wf_persisted_paths")

    def _paths_nonempty(lst: object) -> bool:
        return isinstance(lst, list) and any(str(x).strip() for x in lst)

    if _paths_nonempty(snap_wf) and not _paths_nonempty(sess_wf):
        sess["sb_wf_persisted_paths"] = copy.deepcopy(snap_wf)
    # Workflow captions: Streamlit drops ``sb_wf_lbl_*`` when workflow widgets unmount (guided
    # step 2 or test-steps step); snapshot keeps last values.
    for sk in list(snap.keys()):
        if not isinstance(sk, str) or not sk.startswith("sb_wf_lbl_"):
            continue
        v = snap.get(sk)
        if not isinstance(v, str) or not str(v).strip():
            continue
        cur = sess.get(sk)
        if cur is None or (isinstance(cur, str) and not str(cur).strip()):
            sess[sk] = copy.deepcopy(v)
    _tc_text_key = re.compile(r"^sb_tc_\d+_text$")
    for k, v in snap.items():
        if not isinstance(k, str) or not _tc_text_key.match(k):
            continue
        if not isinstance(v, str) or not v.strip():
            continue
        cur = sess.get(k)
        if cur is None or (isinstance(cur, str) and not str(cur).strip()):
            sess[k] = copy.deepcopy(v)


def sync_scenario_title_aliases(data: dict) -> None:
    """Keep ``story_title`` and ``scenario_title`` in sync on loaded or merged dicts."""
    if not isinstance(data, dict):
        return
    st = str(data.get("story_title") or "").strip()
    sc = str(data.get("scenario_title") or "").strip()
    if st and not sc:
        data["scenario_title"] = st
    elif sc and not st:
        data["story_title"] = sc


def merge_legacy_story_into_scenario_context(data: MutableMapping[str, Any]) -> None:
    """
    Single narrative field: prefer ``scenario_context``; if empty, lift legacy ``story_description``.

    Mutates ``data`` in place (idempotent when ``scenario_context`` is already set).
    """
    if not isinstance(data, dict):
        return
    sc = _nonempty_str(data.get("scenario_context"))
    sd = _nonempty_str(data.get("story_description"))
    if sc:
        return
    if sd:
        data["scenario_context"] = sd


def normalize_loaded_scenario_dict(data: dict) -> None:
    """
    Align on-disk / imported JSON with the canonical app shape (titles, workflow evidence).

    Mutates ``data`` in place (same object ``load_scenario`` returns).
    """
    if not isinstance(data, dict):
        return
    sync_scenario_title_aliases(data)
    data["business_goal"] = clean_business_goal_for_schema(data.get("business_goal"))
    raw_ctx = data.get("scenario_context")
    if raw_ctx is not None and not isinstance(raw_ctx, str):
        data["scenario_context"] = str(raw_ctx).strip()
    elif isinstance(raw_ctx, str):
        data["scenario_context"] = " ".join(raw_ctx.split()).strip()
    wf = data.get("workflow_process_screenshots")
    if (not isinstance(wf, list) or len(wf) == 0) and isinstance(data.get("workflow_screenshots"), list):
        data["workflow_process_screenshots"] = copy.deepcopy(data["workflow_screenshots"])
    for tc in data.get("test_cases") or []:
        if not isinstance(tc, dict):
            continue
        if str(tc.get("title") or "").strip() or str(tc.get("text") or "").strip():
            continue
        for alt_k in ("name", "summary", "test_case_name"):
            raw = tc.get(alt_k)
            if isinstance(raw, str) and raw.strip():
                s = raw.strip()
                tc["text"] = s
                tc["title"] = s
                break

    merge_legacy_story_into_scenario_context(data)


def tc_id_to_explicit_ac_ids(acceptance_criteria: list | None) -> dict[str, list[str]]:
    """
    For each test case id, AC ids that explicitly list it under ``test_case_ids``
    (order follows ``acceptance_criteria`` array order).
    """
    mapping: dict[str, list[str]] = {}
    for ac in acceptance_criteria or []:
        if not isinstance(ac, dict):
            continue
        ac_id = str(ac.get("id") or "").strip() or "unknown"
        raw_ids = ac.get("test_case_ids") or []
        if not isinstance(raw_ids, list):
            continue
        for tid in raw_ids:
            if tid is None:
                continue
            t = str(tid).strip()
            if not t:
                continue
            mapping.setdefault(t, []).append(ac_id)
    return mapping


def format_tc_ac_link_lines(acceptance_criteria: list | None, tc_id: str) -> list[str]:
    """One display line per AC that lists ``tc_id``: ``**AC-01** — excerpt``."""
    tid = (tc_id or "").strip()
    if not tid:
        return []
    lines: list[str] = []
    for ac in acceptance_criteria or []:
        if not isinstance(ac, dict):
            continue
        raw_ids = ac.get("test_case_ids") or []
        if not isinstance(raw_ids, list):
            continue
        ids = {str(x).strip() for x in raw_ids if x is not None and str(x).strip()}
        if tid not in ids:
            continue
        aid = str(ac.get("id") or "").strip() or "unknown"
        atx = str(ac.get("text") or "").strip().replace("\n", " ")[:220]
        lines.append(f"**{aid}**" + (f" — {atx}" if atx else ""))
    return lines


def format_tc_ac_link_lines_for_export(
    acceptance_criteria: list | None,
    tc_id: str,
    *,
    prefer_ac_slot_index: int | None = None,
) -> list[str]:
    """
    Like ``format_tc_ac_link_lines``, but when ``prefer_ac_slot_index`` points to an AC row
    that maps ``tc_id``, show only that row (builder ``sb_tc_*_linked_ac`` / spawn hint).
    Falls back to all mapped ACs if the hint is missing, out of range, or does not list this TC.
    """
    all_lines = format_tc_ac_link_lines(acceptance_criteria, tc_id)
    tid = (tc_id or "").strip()
    if not tid or prefer_ac_slot_index is None:
        return all_lines
    acs = [x for x in (acceptance_criteria or []) if isinstance(x, dict)]
    if not (0 <= prefer_ac_slot_index < len(acs)):
        return all_lines
    ac = acs[prefer_ac_slot_index]
    raw_ids = ac.get("test_case_ids") or []
    if not isinstance(raw_ids, list):
        return all_lines
    ids = {str(x).strip() for x in raw_ids if x is not None and str(x).strip()}
    if tid not in ids:
        return all_lines
    pref = format_tc_ac_link_lines([ac], tc_id)
    return pref if pref else all_lines


def _strip_internal_tc_keys(tc: dict[str, Any]) -> dict[str, Any]:
    """Remove export-only hints so saved JSON stays schema-clean."""
    return {k: v for k, v in tc.items() if not (isinstance(k, str) and k.startswith("_export_"))}


def suggest_scenario_id_from_title(title: str) -> str:
    """URL-safe slug for scenario_id; fallback if title is empty."""
    raw = (title or "").strip().lower()
    base = re.sub(r"[^\w]+", "_", raw).strip("_")[:56]
    return base or "built_scenario"


def resolve_builder_scenario_id(sess: Mapping[str, Any]) -> str:
    """Same ``scenario_id`` resolution as ``read_flat_builder_session`` (for media folder names)."""
    story_title = _nonempty_str(sess.get("sb_story_title"))
    auto_id = bool(sess.get("sb_auto_id", True))
    manual = _nonempty_str(sess.get("sb_scenario_id"))
    if auto_id:
        if story_title:
            return suggest_scenario_id_from_title(story_title)
        return manual or "built_scenario"
    if manual:
        return manual
    if story_title:
        return suggest_scenario_id_from_title(story_title)
    return "built_scenario"


def _nonempty_str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


_BULLET_PREFIX = re.compile(r"^[\-\*\u2022\u25cf\u25cb]\s*")
_NUMBERED_LINE = re.compile(r"^\s*\d+\s*[\.\)]\s*")


def parse_bullet_line_items(text: str | None) -> list[str]:
    """Non-empty lines with common bullet / numbering prefixes stripped."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        s = _NUMBERED_LINE.sub("", s)
        s = _BULLET_PREFIX.sub("", s).strip()
        if s:
            out.append(s)
    return out


def parse_changed_areas_bulk(text: str | None) -> list[dict[str, str]]:
    """One changed-area row per non-empty line; optional ``Area: type`` split."""
    rows: list[dict[str, str]] = []
    for s in parse_bullet_line_items(text):
        if ":" in s:
            a, t = s.split(":", 1)
            rows.append({"area": a.strip(), "type": t.strip()})
        else:
            rows.append({"area": s, "type": ""})
    return rows


def normalize_ac_id_token(raw: str) -> str | None:
    """Normalize ``AC-1`` / ``AC_01`` / ``AC01`` → ``AC-01``; invalid → None."""
    t = (raw or "").strip().upper().replace("_", "-")
    m = re.match(r"^AC-(\d{1,4})$", t)
    if m:
        return f"AC-{int(m.group(1)):02d}"
    m2 = re.match(r"^AC(\d{1,4})$", t)
    if m2:
        return f"AC-{int(m2.group(1)):02d}"
    return None


def parse_acceptance_criteria_bulk_lines(text: str | None) -> list[tuple[str | None, str]]:
    """
    One logical AC per non-empty line. Optional leading ``AC-01`` / ``AC_2`` … preserved when valid.
    Returns (optional normalized id or None, body text).
    """
    out: list[tuple[str | None, str]] = []
    for raw in (text or "").splitlines():
        s0 = raw.strip()
        if not s0:
            continue
        s = _NUMBERED_LINE.sub("", s0)
        s = _BULLET_PREFIX.sub("", s).strip()
        if not s:
            continue
        # Hyphen must be first in `[...]` so it is not parsed as a ``:``–en-dash range (that would swallow letters).
        m = re.match(r"^AC[-_]?(\d{1,4})\b\s*[-–—.:]?\s*(.*)$", s, re.I)
        if m:
            aid = normalize_ac_id_token("AC-" + m.group(1))
            body = (m.group(2) or "").strip()
            out.append((aid, body))
        else:
            out.append((None, s))
    return out


def assign_ac_ids_for_bulk_rows(parsed: list[tuple[str | None, str]]) -> list[tuple[str, str]]:
    """
    Fill missing / duplicate AC ids with lowest unused ``AC-01`` … ``AC-99`` style ids.

    Skips rows whose criterion text is empty after strip. Normalizes known id tokens
    (e.g. ``AC-1``, ``AC_2``, ``AC03``) to ``AC-01`` form; unknown id strings are treated
    as missing and reassigned.
    """
    used: set[str] = set()
    out: list[tuple[str, str]] = []
    for av, txt in parsed:
        t = (txt or "").strip()
        if not t:
            continue
        raw = (av or "").strip()
        aid_norm = normalize_ac_id_token(raw) if raw else None
        if aid_norm and aid_norm not in used:
            aid = aid_norm
        else:
            n = 1
            while True:
                cand = f"AC-{n:02d}"
                if cand not in used:
                    aid = cand
                    break
                n += 1
        used.add(aid)
        out.append((aid, t))
    return out


_TITLE_FIELD_LINE = re.compile(r"^\s*title\s*:\s*(.*)$", re.I)


def parse_test_case_title_and_steps_bulk(text: str | None) -> tuple[str, list[str]]:
    """
    Parse a pasted test case block: optional first ``Title: …`` line, then numbered / bulleted steps.
    """
    if text is None or not str(text).strip():
        return "", []
    raw_lines = str(text).splitlines()
    title = ""
    body_lines: list[str] = []
    title_idx = -1
    for i, line in enumerate(raw_lines):
        m = _TITLE_FIELD_LINE.match(line)
        if m:
            title = (m.group(1) or "").strip()
            title_idx = i
            break
    if title_idx >= 0:
        body_lines = raw_lines[title_idx + 1 :]
    else:
        body_lines = raw_lines
    body = "\n".join(body_lines).strip()
    steps = parse_steps_bulk(body) if body else []
    return title, steps


def tc_title_text_and_steps_from_session(sess: Mapping[str, Any], j: int) -> tuple[str, list[str]]:
    """
    Resolve title + steps: prefer per-step ``sb_tc_{j}_step_{k}_text`` when structured;
    else pasted block; else legacy ``steps_bulk``.
    """
    title = _nonempty_str(sess.get(f"sb_tc_{j}_text"))
    n_steps = max(int(sess.get(f"sb_tc_{j}_n_steps") or 0), 1)
    steps = [_nonempty_str(sess.get(f"sb_tc_{j}_step_{k}_text")) for k in range(n_steps)]
    # Require real per-step text — do not treat ``n_steps > 1`` alone as structured, or guided
    # Final review (step widgets unmounted) yields empty step keys and would drop paste-derived titles.
    structured_nonempty = any(s.strip() for s in steps)
    if structured_nonempty:
        return title, steps if steps else [""]
    paste = sess.get(f"sb_tc_{j}_title_steps_paste")
    if isinstance(paste, str) and paste.strip():
        p_title, p_steps = parse_test_case_title_and_steps_bulk(paste)
        if not p_steps:
            p_steps = [""]
        # Widget title wins when set so exports stay aligned with the visible test case name.
        pt = (p_title or "").strip()
        wt = (title or "").strip()
        merged = wt or pt or title
        return merged, p_steps
    bulk = sess.get(f"sb_tc_{j}_steps_bulk")
    if isinstance(bulk, str) and bulk.strip():
        return title, parse_steps_bulk(bulk)
    return title, steps if steps else [""]


def parse_steps_bulk(text: str | None) -> list[str]:
    """
    Split multiline steps; strip leading ``1.`` / ``1)`` / bullets per line.
    Returns at least one string (possibly empty) so the builder always has a step slot when the widget exists.
    """
    lines: list[str] = []
    for s in parse_bullet_line_items(text):
        lines.append(s)
    return lines if lines else [""]


def _bucket_step_paths_from_raw(raw_ess: list[Any], n_steps: int) -> list[list[str]]:
    """Group screenshot paths by 0-based step index (mapped entries + sequential fill)."""
    n = max(int(n_steps or 0), 1)
    buckets: list[list[str]] = [[] for _ in range(n)]
    sequential: list[str] = []
    for item in raw_ess:
        p, _, mapped = _parse_step_screenshot_entry(item)
        ps = str(p).strip()
        if not ps:
            continue
        if mapped is not None and isinstance(mapped, int) and mapped >= 0:
            while len(buckets) <= mapped:
                buckets.append([])
            buckets[mapped].append(ps)
        else:
            sequential.append(ps)
    q = 0
    for ps in sequential:
        while q < len(buckets) and buckets[q]:
            q += 1
        if q < len(buckets):
            buckets[q].append(ps)
        else:
            buckets.append([ps])
    return buckets


def write_step_paths_to_session(
    sess: MutableMapping[str, Any], j: int, buckets: list[list[str]]
) -> None:
    """Persist grouped paths into session keys (list or legacy single path)."""
    for k, plist in enumerate(buckets):
        sess.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)
        sess.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)
        if len(plist) == 1:
            sess[f"sb_tc_{j}_step_{k}_persisted_path"] = plist[0]
        elif plist:
            sess[f"sb_tc_{j}_step_{k}_persisted_paths"] = list(plist)
    for k in range(len(buckets), 65):
        sess.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)
        sess.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)


def build_scenario_dict(
    *,
    scenario_id: str,
    story_title: str,
    story_description: str,
    business_goal: str,
    workflow_name: str,
    workflow_process_screenshots: list,
    acceptance_criteria: list[dict[str, Any]],
    test_cases: list[dict[str, Any]],
    changed_areas: list[dict[str, Any]],
    known_dependencies: list[str],
    notes: str,
    scenario_context: str = "",
) -> dict:
    """
    Build a normalized scenario dict. Raises ValueError if shape is invalid for save/import rules.
    Does not invent content — caller supplies all lists/fields.
    """
    sid = _nonempty_str(scenario_id)
    if not sid:
        raise ValueError("Scenario ID is required before save or validation.")

    stitle = _nonempty_str(story_title)
    cleaned_tcs: list[Any] = []
    for tc in test_cases or []:
        if isinstance(tc, dict):
            cleaned_tcs.append(_strip_internal_tc_keys(dict(tc)))
        else:
            cleaned_tcs.append(tc)
    raw: dict[str, Any] = {
        "scenario_id": sid,
        "scenario_title": stitle,
        "story_title": stitle,
        "story_description": _nonempty_str(story_description),
        "business_goal": clean_business_goal_for_schema(business_goal),
        "workflow_name": _nonempty_str(workflow_name),
        "workflow_process_screenshots": list(workflow_process_screenshots or []),
        "acceptance_criteria": list(acceptance_criteria or []),
        "test_cases": cleaned_tcs,
        "changed_areas": list(changed_areas or []),
        "known_dependencies": [str(x).strip() for x in (known_dependencies or []) if str(x).strip()],
        "notes": _nonempty_str(notes),
    }
    sctx = _nonempty_str(scenario_context)
    if sctx:
        raw["scenario_context"] = sctx
    _validate_scenario_upload_shape(raw)
    return _normalize_pasted_scenario(raw)


def scenario_dict_to_pretty_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def unmapped_test_case_ids(data: dict) -> list[str]:
    """
    Test case ids present in ``test_cases`` but not listed on any acceptance criterion's
    ``test_case_ids`` (explicit mapping only). Order follows ``test_cases`` array order.
    """
    acs = [x for x in (data.get("acceptance_criteria") or []) if isinstance(x, dict)]
    tcs = [x for x in (data.get("test_cases") or []) if isinstance(x, dict)]
    covered: set[str] = set()
    for ac in acs:
        raw = ac.get("test_case_ids") or []
        if not isinstance(raw, list):
            continue
        for tid in raw:
            if tid is None:
                continue
            t = str(tid).strip()
            if t:
                covered.add(t)
    out: list[str] = []
    seen: set[str] = set()
    for tc in tcs:
        tid = str(tc.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        if tid not in covered:
            out.append(tid)
    return out


def sync_builder_persisted_media_from_data(sess: MutableMapping[str, Any], data: dict) -> None:
    """Refresh workflow / step persisted path keys from a built or loaded scenario dict."""
    if not isinstance(data, dict):
        return
    pairs = workflow_process_screenshot_pairs(data)
    wf_paths = [p.strip() for p, _lb in pairs if (p or "").strip()]
    sess["sb_wf_persisted_paths"] = wf_paths
    for i, (_, lb) in enumerate(pairs):
        if _nonempty_str(lb):
            sess[f"sb_wf_lbl_{i}"] = _nonempty_str(lb)
        else:
            sess.pop(f"sb_wf_lbl_{i}", None)
    for i in range(len(pairs), 48):
        sess.pop(f"sb_wf_lbl_{i}", None)

    changed = [x for x in (data.get("changed_areas") or []) if isinstance(x, dict)]
    ca_lines: list[str] = []
    for row in changed:
        a = _nonempty_str(row.get("area"))
        t = _nonempty_str(row.get("type"))
        if a and t:
            ca_lines.append(f"{a}: {t}")
        elif a:
            ca_lines.append(a)
    sess["sb_changed_areas_bulk"] = "\n".join(ca_lines)

    deps = [str(x).strip() for x in (data.get("known_dependencies") or []) if str(x).strip()]
    sess["sb_known_dependencies_bulk"] = "\n".join(deps)

    tcs = [x for x in (data.get("test_cases") or []) if isinstance(x, dict)]
    for j, tc in enumerate(tcs):
        steps = list(step_texts(tc))
        pr = expected_step_screenshot_paths(tc)
        n_steps = max(len(steps), len(pr))
        ns = max(n_steps, 1)
        sess[f"sb_tc_{j}_n_steps"] = ns
        sess[f"sb_tc_{j}_steps_bulk"] = "\n".join(
            f"{k + 1}. {t}" for k, t in enumerate(steps) if str(t).strip()
        )
        for k in range(64):
            sess.pop(f"sb_tc_{j}_step_{k}_text", None)
        for k in range(ns):
            val = steps[k] if k < len(steps) else ""
            sess[f"sb_tc_{j}_step_{k}_text"] = str(val) if val is not None else ""
        sess.pop(f"sb_tc_{j}_paste_digest", None)
        raw_ess = tc.get("expected_step_screenshots") or []
        if not isinstance(raw_ess, list):
            raw_ess = []
        buckets = _bucket_step_paths_from_raw(raw_ess, ns if ns > 0 else 1)
        write_step_paths_to_session(sess, j, buckets)
        for k in range(len(buckets), 65):
            sess.pop(f"sb_tc_{j}_step_{k}_persisted_path", None)
            sess.pop(f"sb_tc_{j}_step_{k}_persisted_paths", None)
        sess[f"sb_tc_{j}_notes"] = _nonempty_str(tc.get("notes"))
        sess.pop(f"sb_tc_{j}_title_steps_paste", None)


def hydrate_builder_session_from_scenario(
    sess: MutableMapping[str, Any],
    data: dict,
    *,
    editing_registry_id: str | None = None,
) -> None:
    """
    Populate Scenario Builder session keys from a scenario dict (e.g. load for edit).
    Caller must clear builder keys first (e.g. ``_reset_builder_form``).
    """
    if not isinstance(data, dict):
        return
    merge_legacy_story_into_scenario_context(data)
    sid = _nonempty_str(data.get("scenario_id"))
    sess["sb_story_title"] = _nonempty_str(data.get("scenario_title")) or _nonempty_str(
        data.get("story_title")
    )
    sess["sb_auto_id"] = False
    sess["sb_scenario_id"] = sid
    sess["sb_workflow_name"] = _nonempty_str(data.get("workflow_name"))
    sess["sb_business_goal"] = clean_business_goal_for_schema(data.get("business_goal"))
    sess["sb_scenario_context"] = _nonempty_str(data.get("scenario_context"))
    sess["sb_notes"] = _nonempty_str(data.get("notes"))

    pairs = workflow_process_screenshot_pairs(data)
    wf_paths = [p.strip() for p, _lb in pairs if (p or "").strip()]
    sess["sb_wf_persisted_paths"] = wf_paths
    for i, (_, lb) in enumerate(pairs):
        if _nonempty_str(lb):
            sess[f"sb_wf_lbl_{i}"] = _nonempty_str(lb)
        else:
            sess.pop(f"sb_wf_lbl_{i}", None)
    for i in range(len(pairs), 48):
        sess.pop(f"sb_wf_lbl_{i}", None)

    changed = [x for x in (data.get("changed_areas") or []) if isinstance(x, dict)]
    sess["sb_n_ca"] = len(changed)
    ca_lines: list[str] = []
    for row in changed:
        a = _nonempty_str(row.get("area"))
        t = _nonempty_str(row.get("type"))
        if a and t:
            ca_lines.append(f"{a}: {t}")
        elif a:
            ca_lines.append(a)
    sess["sb_changed_areas_bulk"] = "\n".join(ca_lines)

    deps = [str(x).strip() for x in (data.get("known_dependencies") or []) if str(x).strip()]
    sess["sb_n_dep"] = len(deps)
    sess["sb_known_dependencies_bulk"] = "\n".join(deps)

    acs = [x for x in (data.get("acceptance_criteria") or []) if isinstance(x, dict)]
    sess["sb_n_ac"] = len(acs)
    tcs = [x for x in (data.get("test_cases") or []) if isinstance(x, dict)]

    old_by_index: list[str] = []
    for idx, tc in enumerate(tcs):
        oid = _nonempty_str(tc.get("id")) or f"TC-{idx + 1:02d}"
        old_by_index.append(oid)
    new_by_index = [f"TC-{i + 1:02d}" for i in range(len(tcs))]

    def _remap_tid(tid: str) -> str | None:
        t = (tid or "").strip()
        if not t:
            return None
        try:
            pos = old_by_index.index(t)
        except ValueError:
            return None
        return new_by_index[pos]

    for i, ac in enumerate(acs):
        sess[f"sb_ac_{i}_id"] = _nonempty_str(ac.get("id")) or f"AC-{i + 1}"
        sess[f"sb_ac_{i}_text"] = _nonempty_str(ac.get("text"))
        raw_ids = ac.get("test_case_ids") or []
        mapped: list[str] = []
        if isinstance(raw_ids, list):
            for tid in raw_ids:
                r = _remap_tid(str(tid or ""))
                if r and r not in mapped:
                    mapped.append(r)
        sess[f"sb_ac_{i}_map"] = mapped

    sess["sb_n_tc"] = len(tcs)
    for j, tc in enumerate(tcs):
        oid = old_by_index[j]
        sess[f"sb_tc_{j}_id"] = new_by_index[j]
        sess[f"sb_tc_{j}_text"] = _nonempty_str(tc.get("title")) or _nonempty_str(tc.get("text"))
        sess[f"sb_tc_{j}_active"] = True
        steps = list(step_texts(tc))
        paths = expected_step_screenshot_paths(tc)
        n_steps = max(len(steps), len(paths))
        ns = max(n_steps, 1)
        sess[f"sb_tc_{j}_n_steps"] = ns
        sess[f"sb_tc_{j}_steps_bulk"] = "\n".join(
            f"{k + 1}. {t}" for k, t in enumerate(steps) if str(t).strip()
        )
        for k in range(64):
            sess.pop(f"sb_tc_{j}_step_{k}_text", None)
        for k in range(ns):
            val = steps[k] if k < len(steps) else ""
            sess[f"sb_tc_{j}_step_{k}_text"] = str(val) if val is not None else ""
        sess.pop(f"sb_tc_{j}_paste_digest", None)
        raw_ess = tc.get("expected_step_screenshots") or []
        if not isinstance(raw_ess, list):
            raw_ess = []
        buckets = _bucket_step_paths_from_raw(raw_ess, ns if ns > 0 else 1)
        write_step_paths_to_session(sess, j, buckets)
        for k in range(len(buckets), 65):
            clear_tc_step_file_uploader_session_keys(sess, j, k)
        lac: int | None = None
        for ai, ac in enumerate(acs):
            raw_ids = ac.get("test_case_ids") or []
            if not isinstance(raw_ids, list):
                continue
            if any(_nonempty_str(x) == oid for x in raw_ids):
                lac = ai
                break
        if lac is not None:
            sess[f"sb_tc_{j}_linked_ac"] = lac
        else:
            sess.pop(f"sb_tc_{j}_linked_ac", None)
        sess[f"sb_tc_{j}_notes"] = _nonempty_str(tc.get("notes"))
        sess.pop(f"sb_tc_{j}_title_steps_paste", None)

    sess.setdefault("sb_pick_ac_for_spawn", 0)
    if editing_registry_id:
        sess["sb_editing_registry_id"] = str(editing_registry_id).strip()
    else:
        sess.pop("sb_editing_registry_id", None)


def _steps_from_sess(sess: Mapping[str, Any], j: int) -> list[str]:
    _, steps = tc_title_text_and_steps_from_session(sess, j)
    return steps


def _collect_upload_paths_for_step(
    sess: Mapping[str, Any],
    j: int,
    k: int,
    *,
    step_shot_overrides: dict[tuple[int, int], Any] | None,
) -> list[str]:
    """Persisted paths for (tc j, step k), replaced entirely when an upload override exists for that slot."""
    if step_shot_overrides and (j, k) in step_shot_overrides:
        ovr = step_shot_overrides[(j, k)]
        out: list[str] = []
        if isinstance(ovr, list):
            for x in ovr:
                px = _nonempty_str(x)
                if px:
                    out.append(px)
        else:
            px = _nonempty_str(ovr)
            if px:
                out.append(px)
        return out
    paths: list[str] = []
    plist = sess.get(f"sb_tc_{j}_step_{k}_persisted_paths")
    if isinstance(plist, list):
        for x in plist:
            px = _nonempty_str(x)
            if px:
                paths.append(px)
    else:
        sp = _nonempty_str(sess.get(f"sb_tc_{j}_step_{k}_persisted_path"))
        if sp:
            paths.append(sp)
    return paths


def read_flat_builder_session(
    sess: Mapping[str, Any],
    *,
    extra_workflow_paths: list[str] | None = None,
    step_shot_overrides: dict[tuple[int, int], str | list[str]] | None = None,
    include_export_hints: bool = False,
) -> dict:
    """
    Read Streamlit session_state keys written by ui_scenario_builder and return a scenario dict.
    Key naming contract is owned by ui_scenario_builder.py.

    ``extra_workflow_paths`` — saved workflow screenshot upload paths (deduped).
    ``step_shot_overrides`` — (tc_index, step_index) -> path or list of paths from new uploads (replaces persisted).

    ``include_export_hints`` — when True, add ``_export_primary_ac_slot`` on each test case dict for
    execution-draft DOCX only (stripped by ``build_scenario_dict`` on save).
    """
    story_title = _nonempty_str(sess.get("sb_story_title"))
    scenario_context = _nonempty_str(sess.get("sb_scenario_context")) or _nonempty_str(
        sess.get("sb_story_description")
    )
    scenario_id = resolve_builder_scenario_id(sess)
    n_ac = int(sess.get("sb_n_ac") or 0)
    n_tc = int(sess.get("sb_n_tc") or 0)
    n_ca = int(sess.get("sb_n_ca") or 0)
    n_dep = int(sess.get("sb_n_dep") or 0)

    declared_tc_ids: set[str] = set()
    for j in range(n_tc):
        tid0 = _nonempty_str(sess.get(f"sb_tc_{j}_id")) or f"TC-{j + 1:02d}"
        declared_tc_ids.add(tid0)

    test_cases: list[dict[str, Any]] = []
    for j in range(n_tc):
        if sess.get(f"sb_tc_{j}_active", True) is False:
            continue
        tid = _nonempty_str(sess.get(f"sb_tc_{j}_id")) or f"TC-{j + 1:02d}"
        ttext, steps = tc_title_text_and_steps_from_session(sess, j)
        if not steps:
            steps = [""]
        n_steps = len(steps)
        by_k = [
            _collect_upload_paths_for_step(sess, j, k, step_shot_overrides=step_shot_overrides)
            for k in range(n_steps)
        ]
        use_parallel = all(len(x) <= 1 for x in by_k)
        if use_parallel:
            ess: list[Any] = [x[0] if x else "" for x in by_k]
        else:
            ess = []
            for k, lst in enumerate(by_k):
                for p in lst:
                    ess.append({"path": p, "mapped_to_step_index": k})
        tc_row: dict[str, Any] = {
            "id": tid,
            "text": ttext,
            "title": ttext,
            "steps": steps,
            "expected_step_screenshots": ess,
        }
        tcn = _nonempty_str(sess.get(f"sb_tc_{j}_notes"))
        if tcn:
            tc_row["notes"] = tcn
        if include_export_hints:
            lac_raw = sess.get(f"sb_tc_{j}_linked_ac")
            lac_i: int | None = None
            if (
                isinstance(lac_raw, int)
                and not isinstance(lac_raw, bool)
                and lac_raw >= 0
                and lac_raw < n_ac
            ):
                raw_map = sess.get(f"sb_ac_{lac_raw}_map") or []
                ids = (
                    {str(x).strip() for x in raw_map if x is not None and str(x).strip()}
                    if isinstance(raw_map, list)
                    else set()
                )
                if tid in ids:
                    lac_i = lac_raw
            if lac_i is not None:
                tc_row["_export_primary_ac_slot"] = lac_i
        test_cases.append(tc_row)

    acs: list[dict[str, Any]] = []
    for i in range(n_ac):
        aid = _nonempty_str(sess.get(f"sb_ac_{i}_id")) or f"AC-{i + 1}"
        atxt = _nonempty_str(sess.get(f"sb_ac_{i}_text"))
        raw_map = sess.get(f"sb_ac_{i}_map")
        if isinstance(raw_map, list):
            mapped = [str(x).strip() for x in raw_map if str(x).strip()]
        else:
            mapped = []
        # Keep mappings for any declared slot id (active or inactive). Filtering only to
        # ``active`` ids dropped user mappings after navigation or when ids matched slots
        # that were temporarily inactive.
        mapped = [x for x in mapped if x in declared_tc_ids]
        acs.append({"id": aid, "text": atxt, "test_case_ids": mapped})

    bulk_ca = sess.get("sb_changed_areas_bulk")
    changed_from_bulk: list[dict[str, str]] = []
    if isinstance(bulk_ca, str):
        changed_from_bulk = parse_changed_areas_bulk(bulk_ca)
    changed_from_slots: list[dict[str, str]] = []
    for i in range(n_ca):
        area = _nonempty_str(sess.get(f"sb_ca_{i}_area"))
        typ = _nonempty_str(sess.get(f"sb_ca_{i}_type"))
        if area or typ:
            changed_from_slots.append({"area": area, "type": typ})
    changed = changed_from_bulk if changed_from_bulk else changed_from_slots

    bulk_dep = sess.get("sb_known_dependencies_bulk")
    deps_from_bulk: list[str] = []
    if isinstance(bulk_dep, str):
        deps_from_bulk = parse_bullet_line_items(bulk_dep)
    deps_from_slots: list[str] = []
    for i in range(n_dep):
        d = _nonempty_str(sess.get(f"sb_dep_{i}"))
        if d:
            deps_from_slots.append(d)
    deps = deps_from_bulk if deps_from_bulk else deps_from_slots

    wf_items: list[Any] = []
    paths_ordered: list[str] = []
    raw_pf = sess.get("sb_wf_persisted_paths")
    if isinstance(raw_pf, list):
        for p in raw_pf:
            p = (str(p) or "").strip()
            if p and p not in paths_ordered:
                paths_ordered.append(p)
    if extra_workflow_paths:
        for p in extra_workflow_paths:
            p = (p or "").strip()
            if p and p not in paths_ordered:
                paths_ordered.append(p)
    for i, p in enumerate(paths_ordered):
        lb = _nonempty_str(sess.get(f"sb_wf_lbl_{i}"))
        if lb:
            wf_items.append({"path": p, "label": lb})
        else:
            wf_items.append(p)

    flat = build_scenario_dict(
        scenario_id=scenario_id,
        story_title=story_title,
        story_description="",
        business_goal=clean_business_goal_for_schema(sess.get("sb_business_goal")),
        workflow_name=_nonempty_str(sess.get("sb_workflow_name")),
        workflow_process_screenshots=wf_items,
        acceptance_criteria=acs,
        test_cases=test_cases,
        changed_areas=changed,
        known_dependencies=deps,
        notes=_nonempty_str(sess.get("sb_notes")),
        scenario_context=scenario_context,
    )
    if include_export_hints:
        out_tcs = flat.get("test_cases") or []
        for i, src in enumerate(test_cases):
            if i >= len(out_tcs) or not isinstance(out_tcs[i], dict):
                continue
            slot = src.get("_export_primary_ac_slot")
            if slot is not None:
                out_tcs[i]["_export_primary_ac_slot"] = slot
    return flat

"""
Heuristic numbered test-step generation from test case titles (guided builder C3).

Produces 3–6 concise, tester-style steps (navigate → act → submit → validate) with
reduced vague wording and combined validation where appropriate.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from src.scenario_context_expansion import ExpandedGenerationContext
    from src.scenario_test_case_intent import TestCaseIntent

_MAX_STEP_LEN = 220
_MIN_STEPS = 3
_MAX_STEPS = 6

_NEGATIVE_TITLE_PREFIXES = (
    "prevent ",
    "reject ",
    "validate ",
    "block ",
    "require ",
)

# ``Entity - …`` tail: negative / failure signals (keep in sync with ``is_negative_test_case_title``).
_NEGATIVE_TITLE_RHS_RE = re.compile(
    r"(?i)\s-\s.*(?:"
    r"\b(?:invalid|missing|malformed|reject|rejected|block|blocked|blocking|boundary|permission|unauthorized|forbidden|prohibited|"
    r"denied|dependency|dependencies|failure|failures|unavailable|disallowed|not\s+allowed)\b|"
    r"\bno\s+drafts?\b|\bno\s+artifacts?\b|\bmust\s+not\b|\bnot\s+(?:persisted|saved|committed)\b"
    r")"
)

# Positive rule-enforcement titles that contain ``block`` / ``prevent`` but are not negative tests.
_NEGATIVE_TITLE_NOTIFICATION_BLOCK_ALL_EXCLUSION_RE = re.compile(
    r"(?i)\b(notification|preference)\b.*\b(all|both|every)\b.*\b(disabled|off)\b|"
    r"\b(block|prevent)\b.*\b(all|both)\b.*\bnotifications?\b|"
    r"\bblock\b.*\ball\b.*\bnotifications?\b"
)

# Whole-phrase / word-boundary upgrades (applied after steps are built).
_VOCAB_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"(?i)\bgo to\b", "Navigate to"),
    (r"(?i)\bhead to\b", "Navigate to"),
    (r"(?i)\bopen up\b", "Open"),
    (r"(?i)\benter info(rmation)?\b", "Enter required information"),
    (r"(?i)\bfill in info\b", "Enter required information"),
    (r"(?i)\bput in data\b", "Enter required information"),
    (r"(?i)\bobserve validation\b", "Verify validation"),
    (r"(?i)\bobserve the\b", "Verify the"),
    (r"(?i)\bobserve that\b", "Verify that"),
    (r"(?i)\bcheck that\b", "Verify that"),
    (r"(?i)\bcheck the\b", "Verify the"),
    (r"(?i)\bcheck if\b", "Verify whether"),
    (r"(?i)\bmake sure\b", "Confirm"),
    (r"(?i)\bensure\b", "Verify"),
)


def _is_negative_style_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if any(t.startswith(p) for p in _NEGATIVE_TITLE_PREFIXES):
        return True
    # Intent-style negatives: ``Entity - Invalid …``, ``… Blocked …``, ``… No Draft …``, etc.
    if not _NEGATIVE_TITLE_RHS_RE.search(t):
        return False
    if _NEGATIVE_TITLE_NOTIFICATION_BLOCK_ALL_EXCLUSION_RE.search(t):
        return False
    return True


def _route_negative_steps(title: str, intent: "TestCaseIntent | None") -> bool:
    """Use negative step templates when the title *or* inferred intent marks a negative case."""
    if intent is not None and bool(getattr(intent, "is_negative", False)):
        return True
    return _is_negative_style_title(title)


def _is_weak_title(title: str) -> bool:
    t = (title or "").strip()
    return len(t) < 6 or re.match(r"^(x+|tbd|todo|test|n/?a)\.?$", t, re.I) is not None


def _norm_ws(s: str) -> str:
    return " ".join(str(s).split()).strip()


def _truncate_step(s: str, *, max_len: int = _MAX_STEP_LEN) -> str:
    s = _norm_ws(s)
    if len(s) <= max_len:
        return s
    cut = s[: max_len - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _polish_vocabulary(s: str) -> str:
    t = _norm_ws(s)
    for pat, repl in _VOCAB_REPLACEMENTS:
        t = re.sub(pat, repl, t)
    return _norm_ws(t)


def _ensure_validation_near_end(
    steps: list[str],
    expanded: "ExpandedGenerationContext | None" = None,
    *,
    is_negative: bool = False,
) -> list[str]:
    """Guarantee at least one late step uses Verify / Confirm / Validate."""
    if not steps:
        return steps
    tail = " ".join(steps[-2:]).lower()
    if re.search(r"(?i)\b(verify|confirm|validate)\b", tail):
        return steps
    if is_negative and _primary_is_action_event_flow(expanded):
        extra = (
            "Verify the outcome: blocked or denied behavior, absence of an unauthorized draft or artifact, "
            "errors or messaging, and post-refresh state match the linked acceptance criteria."
        )
    elif _primary_is_action_event_flow(expanded):
        extra = (
            "Verify the outcome: artifact presence or absence, UI state, and messaging match the linked acceptance criteria."
        )
    elif is_negative:
        extra = (
            "Verify the outcome: expected errors or blocked save, no incorrect persistence, and UI state match "
            "the linked acceptance criteria."
        )
    else:
        extra = (
            "Verify the outcome: expected message or notice, UI state, and persisted or refreshed data match "
            "the linked acceptance criteria."
        )
    out = list(steps)
    if len(out) >= _MAX_STEPS:
        out[-1] = _truncate_step(_polish_vocabulary(f"{out[-1].rstrip('.')}. {extra}"))
    else:
        out.append(extra)
    return out


def _steps_blob_lower(steps: list[str]) -> str:
    return " ".join(steps).lower()


def _has_commit_trigger(blob: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(trigger\s+)?(save|submit|update|commit)\b|\bclick\s+(save|submit|update)\b",
            blob,
        )
    )


def _explicit_form_save_central_to_action_event(blob: str) -> bool:
    """True when user text explicitly centers a traditional save/submit/update form path (hybrid scenarios)."""
    b = (blob or "").lower()
    return bool(
        re.search(
            r"(?i)\b(save|submit|update)\s+(the\s+)?(form|record|profile|changes|entry)\b|"
            r"\bform\s+(save|submit)\b|\bpersist\s+(edited|typed)\s+fields\b|"
            r"\brequired\s+fields?\b.*\b(save|submit)\b|\bfield-level\s+validation\b.*\b(save|submit)\b",
            b,
        )
    )


def _primary_is_action_event_flow(expanded: "ExpandedGenerationContext | None") -> bool:
    if expanded is None:
        return False
    from src.scenario_type_detection import primary_scenario_type

    return primary_scenario_type(expanded) == "action_event_flow"


def _ae_context_blob(
    title: str,
    linked_ac_blob: str,
    expanded: "ExpandedGenerationContext | None",
) -> str:
    parts = [title or "", linked_ac_blob or ""]
    if expanded is not None:
        parts.append(getattr(expanded, "summary_for_prompt", "") or "")
        parts.extend(str(x) for x in (getattr(expanded, "action_event_lines", None) or []) if str(x).strip())
    return _norm_ws(" ".join(parts))


def _ae_primary_action_short(title: str, linked_ac_blob: str, expanded: "ExpandedGenerationContext | None") -> str:
    """Short phrase for buttons / triggers (not generic Save)."""
    pal = (getattr(expanded, "primary_action_label", "") or "").strip() if expanded is not None else ""
    if pal:
        return pal
    for line in getattr(expanded, "action_event_lines", None) or []:
        s = str(line)
        m = re.search(r"(?i)primary\s+action:\s*\*\*([^*]+)\*\*", s)
        if m:
            return m.group(1).strip()
        m2 = re.search(r"(?i)primary\s+action:\s*(.+)", s)
        if m2:
            return re.sub(r"\*+", "", m2.group(1)).split("(")[0].strip()
    blob = _norm_ws(" ".join([title, linked_ac_blob, getattr(expanded, "summary_for_prompt", "") or ""])).lower()
    m3 = re.search(
        r"(?i)\b(generate\s+reply|generate\s+notes|regenerate\s+\w+|run\s+ai\b[^.]{0,40}|create\s+invoice\s+draft)\b",
        blob,
    )
    if m3:
        return m3.group(0).strip()
    return "the primary action control described in scenario context (e.g. Generate Reply or Generate Notes)"


def _ae_artifact_panel_phrase(expanded: "ExpandedGenerationContext | None") -> str:
    if expanded is not None:
        pz = (getattr(expanded, "panel_location_phrase", "") or "").strip()
        if pz:
            return pz
        art = (getattr(expanded, "artifact_label_singular", "") or "").strip()
        if art:
            return f"the {art} area described in scenario context"
    blob = (getattr(expanded, "summary_for_prompt", "") or "").lower() if expanded else ""
    if "panel" in blob or "response" in blob or "draft" in blob:
        return "the draft or response panel called out in scenario context"
    return "the intended draft, response, or results panel for this workflow"


def _ae_record_phrase(expanded: "ExpandedGenerationContext | None") -> str:
    r = (getattr(expanded, "domain_record_label", "") or "").strip() if expanded is not None else ""
    if r:
        return f"the current {r}"
    return "an eligible active record, conversation, or meeting described in scenario context"


def _action_event_family_positive(intent: "TestCaseIntent") -> str:
    scope = (getattr(intent, "target_scope", "") or "").strip().lower()
    vf = (getattr(intent, "verification_focus", "") or "").strip().lower()
    cond = (intent.condition_type or "").strip().lower()
    if cond == "rule_blocked":
        return "precondition_block"
    if scope in ("generate_action", "authorized_generation") or vf in (
        "action_trigger_success",
        "workflow_outcome",
    ):
        return "trigger_success"
    if scope in ("generated_draft",) or vf in ("artifact_created", "artifact_inserted", "confirmation_or_visible_result"):
        return "artifact_visible"
    if (
        scope in ("draft_state", "auto_send_prevention")
        or vf in ("remains_draft", "no_auto_send", "remains_in_draft_state")
    ):
        return "draft_status"
    if scope == "draft_editability" or vf in ("editable_before_send",):
        return "editable_before_commit"
    if scope == "action_persistence" or vf in ("persists_after_refresh", "persistence_after_refresh"):
        return "persistence_refresh"
    if scope in ("action_precondition",) or vf in ("blocked_when_closed", "blocked_combination"):
        return "precondition_block"
    if scope == "ui_consistency":
        return "artifact_visible"
    return "trigger_success"


def _action_event_family_negative(intent: "TestCaseIntent") -> str:
    c = (intent.condition_type or "").strip().lower()
    if c == "permission_issue":
        return "permission_block"
    if c == "dependency_failure":
        return "service_failure_no_artifact"
    if c == "rule_blocked":
        return "precondition_block"
    if c in ("required_missing", "invalid_format", "boundary_value"):
        return "validation_negative_ae"
    return "precondition_block"


def _build_action_event_positive_steps(
    n: int,
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None",
    *,
    linked_ac_blob: str,
    loc: str,
) -> list[str]:
    fam = _action_event_family_positive(intent)
    act = _ae_primary_action_short(title, linked_ac_blob, expanded)
    panel = _ae_artifact_panel_phrase(expanded)
    role = "the role implied by this test title and linked acceptance criteria"
    rec = _ae_record_phrase(expanded)
    art = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded else ""
    art_disp = art or "draft"

    templates: dict[str, list[str]] = {
        "trigger_success": [
            f"Open {rec} as {role}.",
            f"Locate and click **{act}**; wait for processing to finish if a spinner or progress indicator appears.",
            f"Verify a {art_disp} appears in {panel}.",
            "Verify visible success or result messaging matches the linked acceptance criteria when applicable.",
            f"Verify the {art_disp} is tied to {rec} (not inserted for a different context).",
        ],
        "artifact_visible": [
            f"Open {rec} as {role}.",
            f"Trigger **{act}**.",
            f"Verify the {art_disp} appears in {panel}.",
            f"Verify the content is associated with {rec}, not a different row or session.",
            "Verify no stale or duplicate generated block is shown for this slot.",
        ],
        "draft_status": [
            f"Open {rec} and trigger **{act}**.",
            f"Verify the {art_disp} shows **Draft** (or the equivalent unpublished state) in the UI.",
            "Verify no automatic send, publish, or submit transition occurred without an explicit user commit step.",
            "Verify the next lifecycle action still requires an explicit user action (per product design).",
            "Confirm the UI state matches the linked acceptance criteria for draft vs sent/published.",
        ],
        "editable_before_commit": [
            f"Open {rec} and trigger **{act}** until a {art_disp} is visible.",
            f"Place the cursor in {panel} (or the editor region for the generated content).",
            "Modify part of the generated text using normal editing gestures.",
            f"Verify edits remain visible and the {art_disp} is still not auto-sent or auto-published.",
            "Verify editing does not trigger an unintended commit or lifecycle transition.",
        ],
        "persistence_refresh": [
            f"Open {rec} and trigger **{act}** successfully.",
            f"Confirm the {art_disp} is visible in {panel}.",
            "Refresh the browser, reopen the record, or navigate away and back per scenario context.",
            "Verify the same generated content and state are still present after reload.",
            "Verify displayed state stays consistent with the linked acceptance criteria after refresh.",
        ],
        "precondition_block": [
            f"Open {rec} in the **blocked** precondition state described in the title or linked acceptance criteria.",
            f"Attempt **{act}** (or open the control if it should remain disabled).",
            "Verify the action is disabled, blocked, or shows a clear blocking message as designed.",
            f"Verify **no** new {art_disp} is created.",
            "Verify the UI reflects the blocked precondition without silent failure.",
        ],
    }
    steps = templates.get(fam) or templates["trigger_success"]
    steps = [_truncate_step(_polish_vocabulary(s)) for s in steps]
    take = max(_MIN_STEPS, min(n, len(steps)))
    return steps[:take]


def _build_action_event_negative_steps(
    n: int,
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None",
    *,
    linked_ac_blob: str,
    loc: str,
) -> list[str]:
    fam = _action_event_family_negative(intent)
    act = _ae_primary_action_short(title, linked_ac_blob, expanded)
    panel = _ae_artifact_panel_phrase(expanded)
    role = "a user context implied by this negative test title and linked acceptance criteria"
    rec_ok = _ae_record_phrase(expanded)
    art = (getattr(expanded, "artifact_label_singular", "") or "").strip() if expanded else ""
    art_disp = art or "draft"

    templates: dict[str, list[str]] = {
        "permission_block": [
            f"Open {rec_ok} as {role} without the permission required by scenario context.",
            f"Attempt **{act}** (or locate the control).",
            "Verify the action is unavailable, disabled, or shows a permission denial state.",
            "Verify an error or permission message appears when the product defines one.",
            f"Verify **no** {art_disp} is created or persisted for this attempt.",
        ],
        "service_failure_no_artifact": [
            f"Open {rec_ok} with permissions suitable to reach **{act}**.",
            "Simulate or use an environment where the downstream AI or generation service is unavailable or returns failure, per linked acceptance criteria.",
            f"Trigger **{act}**.",
            "Verify a clear error message, banner, or toast is shown.",
            f"Verify **no** {art_disp} appears in {panel} and no partial or phantom generated block remains.",
        ],
        "precondition_block": [
            f"Open {rec_ok} in the **blocked** precondition state from the title or linked acceptance criteria.",
            f"Attempt **{act}**.",
            "Verify the action is disabled or blocked with a clear message tied to the invalid state.",
            f"Verify **no** new {art_disp} is created.",
            "Verify prior content (if any) is unchanged in a way that matches the acceptance criteria.",
        ],
        "validation_negative_ae": [
            f"Navigate to {loc} where this validation-focused negative can be exercised without unrelated data entry unless the AC requires it.",
            "Apply only the inputs or state changes described in the test title and linked acceptance criteria.",
            f"If the path still reaches **{act}**, trigger it; otherwise verify the UI blocks earlier as designed.",
            "Verify expected failure behavior: inline errors, disabled controls, or banners per acceptance criteria.",
            f"Verify invalid or blocked outcomes do not create an unintended {art_disp}.",
        ],
    }
    steps = templates.get(fam) or templates["precondition_block"]
    steps = [_truncate_step(_polish_vocabulary(s)) for s in steps]
    take = max(_MIN_STEPS, min(n, len(steps)))
    return steps[:take]


def _ensure_action_event_positive_completion(
    steps: list[str],
    intent: "TestCaseIntent",
    *,
    title: str,
    expanded: "ExpandedGenerationContext | None",
) -> list[str]:
    """Append only action/event outcomes — never generic Save/Submit unless hybrid cues exist."""
    out = [s for s in steps if s.strip()]
    blob = _steps_blob_lower(out)
    scope = (getattr(intent, "target_scope", "") or "").strip().lower()
    vf = (getattr(intent, "verification_focus", "") or "").strip().lower()
    cond = intent.condition_type or ""

    if cond == "persisted_state_check" or vf == "persistence_after_refresh" or scope == "action_persistence":
        if not re.search(r"(?i)\b(refresh|reload|re-?open|revisit)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Refresh or revisit the same record and verify the generated draft or result is still present."
                    )
                )
            )
            blob = _steps_blob_lower(out)
        if not re.search(r"(?i)\b(still\s+present|remains|persist|after\s+refresh)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify draft or generated content and its state still match the linked acceptance criteria after reload."
                    )
                )
            )
        return _trim_steps_to_max(out, _MAX_STEPS)

    if cond == "confirmation_check" or vf == "confirmation_message":
        if not re.search(r"(?i)\b(toast|banner|success|message|visible)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify any success or confirmation messaging tied to the primary action matches the linked acceptance criteria."
                    )
                )
            )
        return _trim_steps_to_max(out, _MAX_STEPS)

    if not re.search(r"(?i)\b(verify|confirm)\b", _steps_blob_lower(out[-2:]) if len(out) >= 2 else blob):
        out.append(
            _truncate_step(
                _polish_vocabulary(
                    "Verify end-to-end outcomes match the linked acceptance criteria: visible artifact, state, and messaging."
                )
            )
        )
    return _trim_steps_to_max(out, _MAX_STEPS)


def _ensure_action_event_negative_completion(
    steps: list[str],
    intent: "TestCaseIntent",
) -> list[str]:
    out = [s for s in steps if s.strip()]
    blob = _steps_blob_lower(out)
    if not re.search(r"(?i)\b(error|blocked|denied|unavailable|no\s+draft|not\s+created|disabled)\b", blob):
        out.append(
            _truncate_step(
                _polish_vocabulary(
                    "Verify expected failure behavior: error, block, or permission messaging as described in the linked acceptance criteria."
                )
            )
        )
    if not re.search(r"(?i)\b(no\s+draft|no\s+artifact|not\s+persist|does\s+not\s+appear|unchanged)\b", blob):
        pe = (intent.persistence_expectation or "").strip()
        tail = pe if pe else "no unauthorized draft or artifact is persisted"
        out.append(_truncate_step(_polish_vocabulary(f"Verify {tail}.")))
    return _trim_steps_to_max(out, _MAX_STEPS)


def _trim_steps_to_max(steps: list[str], max_n: int) -> list[str]:
    """Prefer dropping redundant middle UI-confirm rows over losing save / verify / refresh."""
    out = [s for s in steps if s.strip()]
    while len(out) > max_n:
        drop_idx: int | None = None
        for i in range(1, max(1, len(out) - 2)):
            sl = out[i].lower()
            if "confirm the correct screen" in sl or "breadcrumbs" in sl or "confirm the starting state" in sl:
                drop_idx = i
                break
        if drop_idx is not None:
            out.pop(drop_idx)
            continue
        if len(out) > 4:
            out.pop(1)
        elif len(out) > 1:
            out.pop(-2)
        else:
            break
    return out[:max_n]


def _ensure_positive_step_completion(
    steps: list[str],
    intent: "TestCaseIntent",
    *,
    title: str = "",
    expanded: "ExpandedGenerationContext | None" = None,
    linked_ac_blob: str = "",
) -> list[str]:
    """Append minimal lines so positive cases do not stop before save, refresh, or outcome checks."""
    if _primary_is_action_event_flow(expanded):
        ctx = _ae_context_blob(title, linked_ac_blob, expanded)
        if not _explicit_form_save_central_to_action_event(ctx):
            return _ensure_action_event_positive_completion(
                steps, intent, title=title, expanded=expanded
            )

    out = [s for s in steps if s.strip()]
    blob = _steps_blob_lower(out)
    cond = intent.condition_type or ""
    vf = (getattr(intent, "verification_focus", "") or "").strip().lower()

    if not _has_commit_trigger(blob):
        out.append(
            _truncate_step(
                _polish_vocabulary(
                    "Click **Save**, **Submit**, or **Update** (the control that commits this path—not draft-only unless the AC says so)."
                )
            )
        )
        blob = _steps_blob_lower(out)

    if cond == "persisted_state_check" or vf == "persistence_after_refresh":
        if not re.search(r"(?i)\b(refresh|reload|re-?open)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Refresh the browser or re-open the same record so the UI reloads persisted values."
                    )
                )
            )
            blob = _steps_blob_lower(out)
        if not re.search(r"(?i)\b(persist|remain|still\s+(visible|present)|after\s+(reload|refresh))\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify updated values for the fields under test still appear after reload and match what was saved."
                    )
                )
            )
    elif cond == "confirmation_check" or vf == "confirmation_message":
        if not re.search(r"(?i)\b(toast|banner|confirmation|success\s+message)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify a **confirmation** toast, banner, or inline success message appears for this save."
                    )
                )
            )
            blob = _steps_blob_lower(out)
        if not re.search(r"(?i)\b(no\s+contradict|no\s+hard\s+error|contradictory)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Confirm no contradictory hard error is shown while the success confirmation is visible."
                    )
                )
            )
    elif cond == "rule_blocked" or vf == "blocked_combination":
        if not re.search(r"(?i)\b(block|reject|not\s+allowed|error|cannot\s+save|disabled\s+save)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify **Save** is blocked or rejected and messaging explains the cross-field rule (e.g. at least one channel must stay on)."
                    )
                )
            )
            blob = _steps_blob_lower(out)
        if not re.search(r"(?i)\b(unchanged|prior|baseline|previous|still\s+enabled)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify the previous valid preference or toggle baseline is unchanged after the failed save attempt."
                    )
                )
            )
    elif cond == "validation_pass" or vf == "validation_pass":
        if not re.search(r"(?i)\b(inline|validation|no\s+blocking\s+error|no\s+error)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Confirm inline validation shows **no** blocking error for the values entered."
                    )
                )
            )
            blob = _steps_blob_lower(out)
        if not re.search(r"(?i)\b(save\s+completes|success|saved|outcome|updated\s+ui)\b", blob):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "After save, verify success: confirmation or updated UI matches the linked acceptance criteria."
                    )
                )
            )
    else:
        if not re.search(
            r"(?i)\b(verify|confirm)\b.*\b(success|saved|outcome|persist|updated|confirmation)\b|\b(success|saved)\b.*\b(verify|confirm)\b",
            blob,
        ):
            out.append(
                _truncate_step(
                    _polish_vocabulary(
                        "Verify the save outcome end-to-end: success messaging or confirmation, visible UI updates, "
                        "and persisted or refreshed data where applicable per the linked acceptance criteria."
                    )
                )
            )
    return out


def _ensure_negative_step_completion(
    steps: list[str],
    intent: "TestCaseIntent",
    *,
    title: str = "",
    expanded: "ExpandedGenerationContext | None" = None,
    linked_ac_blob: str = "",
) -> list[str]:
    if _primary_is_action_event_flow(expanded):
        ctx = _ae_context_blob(title, linked_ac_blob, expanded)
        if not _explicit_form_save_central_to_action_event(ctx):
            return _ensure_action_event_negative_completion(steps, intent)

    out = [s for s in steps if s.strip()]
    blob = _steps_blob_lower(out)
    if not _has_commit_trigger(blob):
        out.append(
            _truncate_step(
                _polish_vocabulary(
                    "Click **Save**, **Submit**, or **Continue** so the application validates the input."
                )
            )
        )
        blob = _steps_blob_lower(out)
    if not re.search(r"(?i)\b(error|invalid|blocked|validation|denied|permission|missing)\b", blob):
        out.append(
            _truncate_step(
                _polish_vocabulary(
                    "Verify expected failure behavior: inline errors, disabled save, permission messaging, or error banner."
                )
            )
        )
        blob = _steps_blob_lower(out)
    if not re.search(r"(?i)\b(not\s+persist|does\s+not\s+complete|remains\s+intact|prior\s+valid|blocked|must\s+not)\b", blob):
        pe = (intent.persistence_expectation or "").strip()
        tail = pe if pe else "the success path is blocked and invalid or incomplete data is not persisted incorrectly"
        out.append(_truncate_step(_polish_vocabulary(f"Verify {tail}.")))
    return out


def _ensure_complete_test_steps(
    steps: list[str],
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None" = None,
    linked_ac_blob: str = "",
) -> list[str]:
    if _route_negative_steps(title, intent):
        return _ensure_negative_step_completion(
            steps, intent, title=title, expanded=expanded, linked_ac_blob=linked_ac_blob
        )
    return _ensure_positive_step_completion(
        steps, intent, title=title, expanded=expanded, linked_ac_blob=linked_ac_blob
    )


def _dedupe_similar_steps(steps: list[str]) -> list[str]:
    out: list[str] = []
    seen_lower: set[str] = set()
    for s in steps:
        t = _norm_ws(s)
        if not t:
            continue
        key = re.sub(r"\s+", " ", t.lower())
        if key in seen_lower:
            continue
        seen_lower.add(key)
        out.append(t)
    return out


def active_tc_indices(sess: Mapping[str, Any]) -> list[int]:
    """0-based TC slot indices that are active in the builder session."""
    n = int(sess.get("sb_n_tc") or 0)
    return [j for j in range(n) if sess.get(f"sb_tc_{j}_active", True) is not False]


def linked_ac_texts_for_tc(sess: Mapping[str, Any], j: int) -> list[str]:
    """Criterion text for each AC that maps this test case id."""
    tid = str(sess.get(f"sb_tc_{j}_id") or "").strip()
    if not tid:
        return []
    n_ac = int(sess.get("sb_n_ac") or 0)
    out: list[str] = []
    for i in range(n_ac):
        raw = sess.get(f"sb_ac_{i}_map") or []
        if not isinstance(raw, list):
            continue
        ids = {str(x).strip() for x in raw if x is not None and str(x).strip()}
        if tid not in ids:
            continue
        tx = str(sess.get(f"sb_ac_{i}_text") or "").strip()
        if tx:
            out.append(tx)
    return out


def _step_count_for_title(title: str) -> int:
    t = (title or "").strip()
    base = 3 + (min(len(t), 120) % 4)
    return max(_MIN_STEPS, min(_MAX_STEPS, base))


def _location_phrase(
    title: str,
    title_lower: str,
    ctx_lower: str,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    """Short UI / area hint for Navigate / Confirm steps."""
    if expanded is not None and getattr(expanded, "ui_surface_hint", ""):
        return expanded.ui_surface_hint
    if _is_weak_title(title) and expanded and getattr(expanded, "summary_for_prompt", "").strip():
        blob = (expanded.summary_for_prompt or "").lower()
        if any(k in blob for k in ("profile", "contact", "email", "phone", "form", "notification", "preference", "toggle")):
            return "the profile or contact form described in scenario context"
    if _is_weak_title(title):
        return "the specific form or page described in scenario context (not a generic landing page)"
    if any(k in title_lower for k in ("enrollment", "registration", "application", "onboard")):
        return "the enrollment or registration form (or summary page, if applicable)"
    if "sign" in title_lower or "log" in title_lower or "auth" in title_lower:
        return "the sign-in page or authentication entry point"
    if "report" in title_lower or "export" in title_lower or "dashboard" in title_lower:
        return "the report, dashboard, or export section"
    if "payment" in title_lower or "payment" in ctx_lower or "billing" in ctx_lower:
        return "the payment or billing section of the application"
    if "profile" in title_lower or "account" in title_lower or "settings" in title_lower:
        return "the profile, account, or settings area"
    if "form" in ctx_lower or "page" in ctx_lower or "section" in ctx_lower:
        return "the relevant page, section, or form described in the scenario"
    return "the application screen or page that supports this test"


def _enter_examples(
    ctx_lower: str,
    title_lower: str,
    expanded: "ExpandedGenerationContext | None" = None,
    *,
    linked_ac_blob: str = "",
) -> str:
    """Parenthetical examples when input is vague or generic."""
    from src.scenario_type_gating import form_style_email_phone_step_text_forbidden

    blob = _norm_ws(" ".join([linked_ac_blob, ctx_lower, title_lower]))
    if expanded is not None and form_style_email_phone_step_text_forbidden(expanded, linked_text_blob=blob):
        return "(e.g., notification channels as ON/OFF toggles — use values implied by the linked acceptance criteria)"
    if expanded is not None and expanded.fields_involved:
        joined = ", ".join(expanded.fields_involved[:6])
        return f"(e.g., {joined} — use realistic valid and invalid values)"
    if "payment" in ctx_lower or "payment" in title_lower or "card" in ctx_lower:
        return "(e.g., payment method, amount, billing address, or card fields as shown)"
    if "email" in ctx_lower or "email" in title_lower:
        return "(e.g., email, username, or related identity fields)"
    if any(k in ctx_lower for k in ("address", "demographic", "contact", "phone", "name")):
        return "(e.g., name, contact, address, or other required demographic fields)"
    if "password" in ctx_lower or "mfa" in ctx_lower or "otp" in ctx_lower:
        return "(e.g., password, MFA code, or security questions as prompted)"
    if len(ctx_lower) > 40:
        return "(using values consistent with the linked acceptance criteria)"
    return "(e.g., name, email, phone, or address as required by the form)"


def _positive_apply_instruction(
    intent: "TestCaseIntent",
    *,
    title: str = "",
    linked_ac_blob: str = "",
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    """Executable edit step: concrete example values when scope is known."""
    from src.scenario_type_detection import primary_scenario_type
    from src.scenario_type_gating import (
        explicit_text_input_validation_context,
        form_style_email_phone_step_text_forbidden,
        state_toggle_strict_gating,
    )

    scope = (getattr(intent, "target_scope", "") or "").strip().lower()
    tf = (intent.target_field or "").strip().lower()
    vf = (getattr(intent, "verification_focus", "") or "").strip().lower()
    cond = intent.condition_type or ""
    blob = _norm_ws(" ".join([title, linked_ac_blob]))
    forbid_typed = form_style_email_phone_step_text_forbidden(expanded, linked_text_blob=blob)
    toggle_strict = bool(
        expanded is not None
        and state_toggle_strict_gating(expanded, criterion_text=blob)
        and not explicit_text_input_validation_context(blob)
    )

    if cond == "rule_blocked" or vf == "blocked_combination":
        if expanded is not None and primary_scenario_type(expanded) == "action_event_flow":
            act0 = _ae_primary_action_short(title, linked_ac_blob, expanded)
            return (
                f"Open a record in a **blocked** precondition state (e.g. **Closed** conversation); attempt **{act0}**; "
                "leave the UI ready to observe disabled control, tooltip, or blocking message."
            )
        return (
            "Turn **OFF** Email notifications and **OFF** SMS so **no** channel remains enabled (or apply the forbidden "
            "combination from the linked acceptance criteria); leave the screen ready to attempt **Save**."
        )

    if expanded is not None and primary_scenario_type(expanded) == "action_event_flow":
        act = _ae_primary_action_short(title, linked_ac_blob, expanded)
        art_l = (getattr(expanded, "artifact_label_singular", "") or "").strip() or "draft"
        if scope == "generate_action" or vf == "action_trigger_success":
            return (
                f"Open an **eligible active** conversation or record as the scenario role; click **{act}** "
                "and wait until processing finishes."
            )
        if scope == "generated_draft" or vf == "artifact_created":
            return (
                f"Trigger **{act}**, then confirm a **{art_l}** appears in the draft or response panel described in scenario context."
            )
        if scope == "draft_state" or vf == "remains_draft":
            return (
                f"After generation, confirm the **{art_l}** shows **Draft** (or equivalent) status and **no** automatic send occurred."
            )
        if scope == "draft_editability" or vf == "editable_before_send":
            return (
                "With a draft visible, place the cursor in the draft panel, **edit** part of the generated text, and confirm it remains editable (not sent)."
            )
        if scope == "action_persistence" or vf == "persists_after_refresh":
            return (
                "After a successful generation, **refresh or re-open** the workspace; verify the draft content and state still match the linked acceptance criteria."
            )
        if scope == "authorized_generation" or vf == "workflow_outcome":
            return (
                "As an **authorized** role from scenario context, run the primary action end-to-end and confirm success indicators per AC."
            )
        if scope == "auto_send_prevention" or vf == "no_auto_send":
            return (
                "After generation completes, confirm **no** send/submit or forbidden lifecycle transition happened without an explicit user step."
            )
        if vf == "confirmation_or_visible_result" or scope == "ui_consistency":
            return (
                "Complete the primary action; confirm visible confirmation, inserted draft, or result messaging matches AC."
            )

    if scope == "email_toggle" or vf == "enable_transition":
        return (
            "Turn **ON** Email notifications (toggle or switch). Keep SMS in a valid baseline (e.g. **ON**) so at least one method stays enabled."
        )
    if scope == "sms_toggle" or vf == "disable_transition":
        return (
            "Turn **OFF** SMS notifications while **Email** notifications remain **ON** (or another valid combination per AC)."
        )
    if scope == "notification_preferences" and cond not in (
        "persisted_state_check",
        "confirmation_check",
        "rule_blocked",
    ):
        return (
            "Set notification toggles to a valid ON/OFF pattern per the linked acceptance criteria; confirm each control shows the intended state before **Save**."
        )

    if cond == "confirmation_check":
        if (
            scope == "notification_preferences"
            or "notification" in tf
            or (
                toggle_strict
                and re.search(r"(?i)\bnotification|preference|channel|toggle|sms|email\s+notification", blob)
            )
        ):
            return (
                "Set toggles to a valid combination; confirm **Email** and **SMS** ON/OFF labels match intent, then proceed to **Save**."
            )
        if forbid_typed:
            return (
                "Apply valid allowed choices for this workflow per the linked acceptance criteria, then proceed to **Save**."
            )
        return (
            "Enter **email** `qa.profile@example.com` and **phone** `6505551234` (both valid per scenario rules); "
            "leave other required fields at realistic baseline values."
        )
    if cond == "persisted_state_check":
        if scope == "notification_preferences" or "notification preference" in tf:
            return (
                "Save a valid notification preference combination; note which channels are **ON** vs **OFF** for comparison after refresh or re-login."
            )
        if toggle_strict and scope in ("email", "phone", "contact_info", "persistence"):
            return (
                "Save a valid notification preference combination; note which channels are **ON** vs **OFF** for comparison after refresh or re-login."
            )
        if forbid_typed:
            return (
                "Save using valid allowed data for this workflow; note the visible state you expect to match after refresh or re-login."
            )
        if scope == "contact_info" or tf == "contact info":
            return (
                "Enter **email** `qa.updated@example.com` and **phone** `6505550199`; save, then use these values "
                "as the expected pair after refresh."
            )
        if scope == "email" or tf == "email":
            return (
                "Change **email** to `qa.updated@example.com` while keeping **phone** at a valid baseline (e.g. `6505551234`); save."
            )
        if scope == "phone" or tf == "phone":
            return (
                "Change **phone** to `6505550199` while keeping **email** at a valid baseline (e.g. `qa.profile@example.com`); save."
            )
        return (
            "Update the fields under test with valid values from scenario context; save and note values for reload comparison."
        )

    if forbid_typed and (scope in ("phone", "email") or tf in ("phone", "email")):
        if scope == "phone" or tf == "phone":
            return (
                "Turn **OFF** SMS notifications while **Email** remains **ON** (or another valid combination per AC); confirm labels before save."
            )
        return (
            "Turn **ON** Email notifications while keeping a valid baseline for other channels per AC; confirm labels before save."
        )

    if scope == "phone" or tf == "phone":
        return (
            "Enter **phone** `6505551234` (10 digits, valid format); keep **email** and other fields at valid baseline values; "
            "ensure inline validation shows no phone error before save."
        )
    if scope == "email" or tf == "email":
        return (
            "Enter **email** `qa.provider@example.com` (valid format); keep **phone** and other fields at valid baseline values; "
            "ensure inline validation shows no email error before save."
        )
    if scope == "contact_info" or tf == "contact info":
        return (
            "Enter **email** `qa.profile@example.com` and **phone** `6505551234`; confirm both fields pass inline validation, then proceed."
        )

    if vf == "ui_consistency":
        return (
            "Save valid changes, then compare visible labels, field values, and status indicators against the linked acceptance criteria "
            "(no stale errors, no mismatched read-only vs editable values)."
        )
    if vf == "business_outcome":
        return (
            "Complete the save path with realistic valid data; verify the UI and stored values together reflect the business outcome "
            "described in scenario context and ACs."
        )
    if vf == "validation_pass":
        if forbid_typed:
            return (
                "Set channels to a valid ON/OFF pattern per AC; confirm no blocking inline error appears for the toggle row, then proceed to **Save**."
            )
        if scope == "phone" or tf == "phone":
            return (
                "Enter **phone** `6505551234`; keep **email** at `qa.profile@example.com`; confirm inline validation shows **no** phone error, then proceed to save."
            )
        if scope == "email" or tf == "email":
            return (
                "Enter **email** `qa.provider@example.com`; keep **phone** at `6505551234`; confirm inline validation shows **no** email error, then proceed to save."
            )
        return (
            "Enter valid values for the fields under test per scenario rules; confirm inline validation shows **no** blocking errors, then proceed to save."
        )
    return (
        f"Apply valid values for **{tf or 'the fields under test'}** consistent with scenario context and linked ACs: {intent.input_profile or 'use realistic valid data'}."
    )


def _intent_surface_location(
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None",
) -> str:
    if (intent.ui_surface_hint or "").strip():
        return intent.ui_surface_hint.strip()
    tl = (title or "").strip().lower()
    return _location_phrase(title or intent.entity or "workflow", tl, "", expanded)


def _positive_steps_from_intent(
    n: int,
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None",
    *,
    linked_ac_blob: str = "",
) -> list[str]:
    from src.scenario_type_detection import primary_scenario_type
    from src.scenario_type_gating import form_style_email_phone_step_text_forbidden

    loc = _intent_surface_location(intent, title, expanded)
    blob_ae = _ae_context_blob(title, linked_ac_blob, expanded)
    if (
        expanded is not None
        and primary_scenario_type(expanded) == "action_event_flow"
        and not _explicit_form_save_central_to_action_event(blob_ae)
    ):
        return _build_action_event_positive_steps(
            n, intent, title, expanded, linked_ac_blob=linked_ac_blob, loc=loc
        )
    eb = intent.expected_behavior or "the success path completes with correct UI feedback"
    vf = intent.validation_focus or "expected validation and success signals"
    pe = intent.persistence_expectation or "persisted or refreshed data matches the save"

    s_nav = _truncate_step(
        f"Navigate to {loc} using the workflow path implied by this test case intent — avoid generic landing pages."
    )
    s_confirm = _truncate_step(
        "Confirm the correct screen or section is active (title, breadcrumbs, or primary controls align with this test)."
    )
    tf = (intent.target_field or "").strip()
    blob_fs = _norm_ws(" ".join([title, linked_ac_blob]))
    forbid_fs = form_style_email_phone_step_text_forbidden(expanded, linked_text_blob=blob_fs)
    field_scope = tf if tf else "the fields called out in the title and linked acceptance criteria"
    if forbid_fs and intent.condition_type in ("confirmation_check", "persisted_state_check"):
        field_scope = "notification channel toggles and linked preference rules"
    s_apply = _truncate_step(
        _positive_apply_instruction(intent, title=title, linked_ac_blob=linked_ac_blob, expanded=expanded)
    )
    s_trigger = _truncate_step(
        "Trigger Save, Submit, or Update with the control that commits this path (not a draft-only action unless AC says so)."
    )

    if intent.condition_type == "rule_blocked":
        s_verify = _truncate_step(
            f"Verify **save is blocked**: {eb} — disabled save, blocking banner, or inline rule message as designed."
        )
        s_verify2 = _truncate_step(
            f"Verify {vf}; prior valid preference or toggle baseline remains unchanged."
        )
        s_extra = _truncate_step(f"Verify {pe}")
        pool = [s_nav, s_confirm, s_apply, s_trigger, s_verify, s_verify2]
    elif intent.condition_type == "confirmation_check":
        s_verify = _truncate_step(
            f"Verify **confirmation-only** outcome: {eb} — toast, banner, or inline success text tied to this save."
        )
        s_verify2 = _truncate_step(
            f"Verify {vf}; ensure no contradictory hard error appears while the success confirmation is shown."
        )
        s_extra = _truncate_step(
            f"Optional: re-open the record and confirm {field_scope} still reflect the saved values."
        )
    elif intent.condition_type == "persisted_state_check":
        s_verify = _truncate_step(
            f"After save, **refresh or re-open** the same record; verify {eb} for {field_scope}."
        )
        s_verify2 = _truncate_step(
            f"Verify {pe}; compare visible {field_scope} to the linked acceptance criteria after reload."
        )
        s_extra = _truncate_step(
            "If applicable, spot-check server/UI consistency (same identifiers and field values after reload)."
        )
    else:
        s_verify = _truncate_step(f"Verify **save outcome** for this case: {eb}")
        s_verify2 = _truncate_step(f"Verify {vf} specifically for {field_scope}.")
        s_extra = _truncate_step(f"Verify persistence: {pe}")

    pool = [s_nav, s_confirm, s_apply, s_trigger, s_verify, s_verify2]
    if n >= 6:
        pool.append(s_extra)
    # Short runs should still include the outcome-specific verification (not only navigate/apply).
    if n <= 4 and intent.condition_type == "confirmation_check":
        pool = [s_nav, s_apply, s_trigger, s_verify]
    elif n <= 4 and intent.condition_type == "rule_blocked":
        pool = [s_nav, s_apply, s_trigger, s_verify]
    elif n <= 4 and intent.condition_type == "persisted_state_check":
        pool = [s_nav, s_apply, s_trigger, s_verify]
    elif n == 3 and intent.condition_type in ("confirmation_check", "persisted_state_check", "rule_blocked"):
        pool = [s_nav, s_trigger, s_verify]
    out = [_truncate_step(_polish_vocabulary(s)) for s in pool if s.strip()]
    take = max(_MIN_STEPS, min(n, len(out)))
    if intent.condition_type in ("confirmation_check", "persisted_state_check", "rule_blocked"):
        take = max(take, min(4, len(out)))
    else:
        # Happy path / validation_pass / UI / business — never return only navigate + apply without save + outcome.
        take = max(take, min(5, len(out)))
    return out[:take]


def _negative_field_input_instruction(
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None",
    *,
    linked_ac_blob: str,
    forbid_contact_language: bool,
    explicit_input: bool,
) -> str | None:
    """
    Executable data-entry line for form negatives: values must match the failure class
    (blank vs malformed vs boundary), not the happy-path valid examples.
    """
    cond = (intent.condition_type or "").strip()
    if cond not in ("required_missing", "invalid_format", "boundary_value"):
        return None
    if forbid_contact_language and not explicit_input:
        return None

    rhs = title.split(" - ", 1)[-1].lower() if " - " in (title or "") else (title or "").lower()
    tf = (intent.target_field or "").strip().lower()
    if "missing" in rhs and "email" in rhs and "phone" not in rhs:
        tf = "email"
    elif "missing" in rhs and "phone" in rhs and "email" not in rhs:
        tf = "phone"
    elif "invalid" in rhs and "email" in rhs and "phone" not in rhs:
        tf = "email"
    elif "invalid" in rhs and "phone" in rhs and "email" not in rhs:
        tf = "phone"
    elif "boundary" in rhs and "email" in rhs and "phone" not in rhs:
        tf = "email"
    elif "boundary" in rhs and "phone" in rhs and "email" not in rhs:
        tf = "phone"

    valid_email = "qa.profile@example.com"
    valid_phone = "6505551234"

    if cond == "required_missing":
        if tf == "email":
            return (
                f"**Clear the Email field** (leave it blank or delete all characters). "
                f"Keep **Phone** at a valid baseline such as **{valid_phone}** and other required fields valid."
            )
        if tf == "phone":
            return (
                f"**Clear the Phone field** (leave it blank). "
                f"Keep **Email** at a valid address such as **{valid_email}** and other required fields valid."
            )
        if "contact" in tf:
            return (
                "**Clear Email** entirely (blank) while keeping Phone at a valid baseline, "
                "or clear Phone while keeping Email valid — match the field named in the test title."
            )
        return None

    if cond == "invalid_format":
        if tf == "email":
            return (
                f"In **Email**, enter a clearly malformed value such as **qa.provider@** or **not_an_email** "
                f"(missing domain / invalid pattern). Keep **Phone** at **{valid_phone}**."
            )
        if tf == "phone":
            return (
                f"In **Phone**, enter **65055** or **abcd1234567890** (wrong length or invalid characters). "
                f"Keep **Email** at **{valid_email}**."
            )
        return None

    if cond == "boundary_value":
        accept = "accepted edge value" in (intent.input_profile or "").lower() or "remains valid" in (
            intent.input_profile or ""
        ).lower()
        if accept:
            return (
                "Enter a **valid edge** value per documented limits (for example shortest allowed email local-part) "
                f"while keeping other fields at valid baselines ({valid_email} / {valid_phone} where applicable)."
            )
        if tf == "email":
            return (
                "Enter an **overlong** or otherwise **out-of-range** email string per product limits "
                f"(e.g. excessive local-part length); keep **Phone** at **{valid_phone}**."
            )
        if tf == "phone":
            return (
                f"Enter a **too-short** or **too-long** phone string (e.g. **00000** or **1** repeated past max); "
                f"keep **Email** at **{valid_email}**."
            )
        return None


def _sanitize_output_steps_for_family(
    steps: list[str],
    expanded: "ExpandedGenerationContext | None",
    *,
    title: str,
    linked_ac_blob: str,
) -> list[str]:
    """Remove cross-family placeholder wording from final emitted steps."""
    from src.scenario_type_detection import primary_scenario_type
    from src.scenario_type_gating import explicit_text_input_validation_context, state_toggle_strict_gating

    if not steps:
        return []
    if expanded is None:
        return list(steps)
    blob = _norm_ws(" ".join([title, linked_ac_blob]))
    pt = primary_scenario_type(expanded)
    toggle_gate = state_toggle_strict_gating(expanded, criterion_text=blob) and not explicit_text_input_validation_context(
        blob
    )
    out: list[str] = []
    for line in steps:
        low = line.lower()
        if toggle_gate:
            if re.search(
                r"(?i)\b(valid|invalid)\s+(email|phone)\b|"
                r"\b650555\d*\b|qa\.\w+@\w|profile\s+or\s+contact|contact\s+update|"
                r"\benter\s+required\s+information\b.*\b(email|phone|address|demographic)\b|"
                r"\bupdate\s+email\b|\bupdate\s+phone\b|\bemail\s+and\s+phone\b",
                low,
            ):
                line = (
                    "Adjust **Email** and **SMS** notification toggles per the linked acceptance criteria; "
                    "leave unrelated profile or contact text fields unchanged unless the AC explicitly requires them."
                )
        elif pt == "action_event_flow" and not explicit_text_input_validation_context(blob):
            pal = (getattr(expanded, "primary_action_label", "") or "").strip()
            if pal and re.search(r"(?i)\bgenerate\s+reply\b", low) and "reply" not in pal.lower():
                line = re.sub(r"(?i)\bgenerate\s+reply\b", pal, line)
            art = (getattr(expanded, "artifact_label_singular", "") or "").strip()
            if art and "generated artifact" in low:
                line = re.sub(r"(?i)\bgenerated\s+artifact\b", art, line)
            if "save updated record" in low:
                rec = (getattr(expanded, "domain_record_label", "") or "").strip() or "current context"
                line = re.sub(
                    r"(?i)save\s+updated\s+record",
                    f"complete the workflow for the current {rec}",
                    line,
                )
        out.append(line)
    return _dedupe_similar_steps(out)


def _negative_steps_from_intent(
    n: int,
    intent: "TestCaseIntent",
    title: str,
    expanded: "ExpandedGenerationContext | None",
    *,
    linked_ac_blob: str = "",
) -> list[str]:
    from src.scenario_type_detection import primary_scenario_type
    from src.scenario_type_gating import explicit_text_input_validation_context, form_style_email_phone_step_text_forbidden

    loc = _intent_surface_location(intent, title, expanded)
    blob_ae = _ae_context_blob(title, linked_ac_blob, expanded)
    if (
        expanded is not None
        and primary_scenario_type(expanded) == "action_event_flow"
        and not _explicit_form_save_central_to_action_event(blob_ae)
    ):
        return _build_action_event_negative_steps(
            n, intent, title, expanded, linked_ac_blob=linked_ac_blob, loc=loc
        )
    ip = intent.input_profile or "data that violates the rule under test while keeping other fields valid where possible"
    ee = intent.error_expectation or intent.validation_focus or "expected validation or blocking behavior"
    pe = intent.persistence_expectation or "invalid or incomplete data must not persist incorrectly"
    focus = (intent.target_field or "").strip() or "the field under test"
    blob_n = _norm_ws(" ".join([title, linked_ac_blob, getattr(expanded, "summary_for_prompt", "") or ""]))
    forbid_n = form_style_email_phone_step_text_forbidden(expanded, linked_text_blob=blob_n)
    explicit_input = explicit_text_input_validation_context(blob_n)
    concrete_apply = _negative_field_input_instruction(
        intent,
        title,
        expanded,
        linked_ac_blob=linked_ac_blob,
        forbid_contact_language=forbid_n,
        explicit_input=explicit_input,
    )

    s_nav = _truncate_step(f"Navigate to {loc} where this negative outcome can be exercised.")
    s_confirm = _truncate_step("Confirm the starting state is clean for this test (no stale success banners masking errors).")
    if (
        forbid_n
        and not explicit_input
        and intent.condition_type in ("permission_issue", "dependency_failure", "rule_blocked")
    ):
        from src.scenario_type_detection import primary_scenario_type

        if expanded is not None and primary_scenario_type(expanded) == "action_event_flow":
            act_ae = _ae_primary_action_short(title, linked_ac_blob, expanded)
            s_apply = _truncate_step(
                "Set up the record or conversation state from the title and linked AC (e.g. **Closed** vs **Active**, or service unavailable); "
                f"attempt **{act_ae}** without unrelated free-text edits unless the AC requires them."
            )
        else:
            s_apply = _truncate_step(
                "Adjust toggles, channels, or role context per this test title and linked AC so the blocked rule or permission case applies; "
                "avoid unrelated free-text field edits unless the AC requires them."
            )
    elif concrete_apply:
        s_apply = _truncate_step(concrete_apply)
    else:
        s_apply = _truncate_step(
            f"Apply inputs for **{focus}** as required by this test title and linked acceptance criteria: {ip}."
        )
    s_trigger = _truncate_step("Trigger Save, Submit, or Continue so the application validates the input.")
    s_verify = _truncate_step(f"Verify {ee} (inline field errors, disabled save, or error banner as designed).")
    pe_l = (pe or "").lower()
    if "accepted edge value persists" in pe_l or "accepted edge" in pe_l:
        s_persist = _truncate_step(
            f"Verify durable state for the **boundary case**: {pe} (no false-negative validation blocking a valid edge)."
        )
    else:
        s_persist = _truncate_step(f"Verify {pe}.")
    pool = [s_nav, s_confirm, s_apply, s_trigger, s_verify, s_persist]
    out = [_truncate_step(_polish_vocabulary(s)) for s in pool if s.strip()]
    take = max(_MIN_STEPS, min(n, len(out)))
    return out[:take]


def _positive_steps(
    title: str,
    n: int,
    ctx: str,
    expanded: "ExpandedGenerationContext | None" = None,
) -> list[str]:
    t_raw = (title or "").strip() or "workflow"
    tl = t_raw.lower()
    ctx_raw = _norm_ws(ctx)
    ctx_l = ctx_raw.lower()
    loc = _location_phrase(t_raw, tl, ctx_l, expanded)
    examples = _enter_examples(ctx_l, tl, expanded, linked_ac_blob=ctx_raw)

    s_nav = _truncate_step(f"Navigate to {loc} using the shortest path from the test entry role.")
    s_confirm_ui = _truncate_step(
        "Confirm the correct page or section is displayed (title, breadcrumbs, or key controls visible)."
    )
    s_enter = _truncate_step(
        f"Enter required information {examples}, following field-level validation if present."
    )
    s_act = _truncate_step(
        "Complete the primary workflow action (for example Save, Submit, Continue, or Confirm) using the UI control intended for this path."
    )
    s_validate = _truncate_step(
        "Verify success end-to-end: any confirmation message or toast, visible UI updates (status, navigation, or next step), "
        "and that persisted or refreshed data reflects the change (re-query or reopen the record if appropriate)."
    )
    s_doc = _truncate_step(
        "Capture any notes, environment identifiers, or attachments needed for traceability (build, role, URL, or dataset)."
    )

    s_enter_act = _truncate_step(
        f"Enter required information {examples}, then complete the primary action "
        "(Save, Submit, Continue, or Confirm) using the intended control."
    )
    if "report" in tl or "export" in tl:
        s_enter = _truncate_step(
            f"Set filters or parameters as needed, then enter or confirm export criteria {examples}."
        )
        s_enter_act = _truncate_step(
            f"{s_enter.rstrip('.')}; then run or export using the primary action control."
        )
    if "sign" in tl or "log" in tl:
        s_enter = _truncate_step(f"Enter credentials or authentication details {examples}.")
        s_enter_act = _truncate_step(
            f"{s_enter.rstrip('.')}, then complete sign-in using the primary action control."
        )

    # Navigate → (confirm UI) → act/enter → submit → validate (+ optional doc). Compact when n is small.
    if n <= 3:
        return [s_nav, s_enter_act, s_validate]
    if n == 4:
        return [s_nav, s_confirm_ui, s_enter_act, s_validate]
    pool = [s_nav, s_confirm_ui, s_enter, s_act, s_validate]
    if n >= 6:
        pool.append(s_doc)
    return [s for s in pool[:n] if s.strip()][: _MAX_STEPS]


def _negative_steps(
    title: str,
    n: int,
    expanded: "ExpandedGenerationContext | None" = None,
) -> list[str]:
    short = _norm_ws(title)
    if len(short) > 88:
        short = short[:85].rstrip() + "…"
    loc = _location_phrase(short, short.lower(), "", expanded)

    pool = [
        _truncate_step(f"Navigate to {loc} where invalid or incomplete inputs can be supplied."),
        _truncate_step(
            f"Enter or select data that intentionally violates the scenario: {short}."
        ),
        _truncate_step(
            "Trigger the submit, save, or continuation control so the application can validate the input."
        ),
        _truncate_step(
            "Verify validation behavior: field-level messages, blocking of the happy path, or error banners as applicable."
        ),
        _truncate_step(
            "Confirm the system does not complete the success path incorrectly; capture messages or screenshots for evidence if required."
        ),
        _truncate_step(
            "Validate persisted or refreshed state: erroneous records must not appear; prior good data remains intact where expected."
        ),
    ]
    take = max(_MIN_STEPS, min(max(n, 4), len(pool)))
    return [s for s in pool[:take] if s.strip()]


def generate_default_test_steps(
    *,
    test_case_title: str,
    linked_ac_texts: list[str] | None = None,
    expanded_context: "ExpandedGenerationContext | None" = None,
    intent: "TestCaseIntent | None" = None,
) -> list[str]:
    """
    Build 3–6 numbered-ready step lines (no leading numbers here — caller formats).

    When **intent** is provided (or can be inferred), steps follow **Test Case Intent**
    instead of a single generic positive template. ``expanded_context`` remains additive scenario context.
    """
    from src.scenario_test_case_intent import infer_test_case_intent
    from src.scenario_type_detection import primary_scenario_type

    title = (test_case_title or "").strip() or "the workflow"
    ctx = _norm_ws(" ".join(linked_ac_texts or []))
    linked_blob = ctx
    if expanded_context and expanded_context.summary_for_prompt.strip():
        ctx = _norm_ws(ctx + "\n" + expanded_context.summary_for_prompt)
    n = _step_count_for_title(title)

    intent_obj = intent
    if intent_obj is None:
        intent_obj = infer_test_case_intent(
            test_case_title=title,
            linked_acceptance_criteria=linked_ac_texts,
            criterion_text_only="",
            expanded=expanded_context,
            is_negative=_is_negative_style_title(title),
        )

    route_neg = _route_negative_steps(title, intent_obj)

    use_intent = bool(
        intent_obj
        and (
            intent_obj.intent_summary.strip()
            or intent_obj.target_field.strip()
            or getattr(intent_obj, "target_scope", "").strip()
            or getattr(intent_obj, "verification_focus", "").strip()
        )
    )
    ae_no_hybrid = bool(
        expanded_context is not None
        and primary_scenario_type(expanded_context) == "action_event_flow"
        and not _explicit_form_save_central_to_action_event(_ae_context_blob(title, linked_blob, expanded_context))
    )
    if use_intent:
        if route_neg:
            steps = _negative_steps_from_intent(
                n, intent_obj, title, expanded_context, linked_ac_blob=linked_blob
            )
        else:
            steps = _positive_steps_from_intent(
                n, intent_obj, title, expanded_context, linked_ac_blob=linked_blob
            )
    elif ae_no_hybrid and intent_obj is not None:
        loc_i = _intent_surface_location(intent_obj, title, expanded_context)
        if route_neg:
            steps = _build_action_event_negative_steps(
                n, intent_obj, title, expanded_context, linked_ac_blob=linked_blob, loc=loc_i
            )
        else:
            steps = _build_action_event_positive_steps(
                n, intent_obj, title, expanded_context, linked_ac_blob=linked_blob, loc=loc_i
            )
    elif route_neg:
        steps = _negative_steps(title, n, expanded_context)
    else:
        steps = _positive_steps(title, n, ctx, expanded_context)

    steps = [_truncate_step(_polish_vocabulary(re.sub(r"\s+", " ", s).strip())) for s in steps if s and str(s).strip()]
    steps = _dedupe_similar_steps(steps)
    if intent_obj is not None and (use_intent or ae_no_hybrid):
        steps = _ensure_complete_test_steps(
            steps, intent_obj, title, expanded=expanded_context, linked_ac_blob=linked_blob
        )
    steps = _dedupe_similar_steps(steps)
    steps = _ensure_validation_near_end(steps, expanded_context, is_negative=route_neg)

    if len(steps) < _MIN_STEPS:
        from src.scenario_type_gating import form_style_email_phone_step_text_forbidden

        hint = ""
        if expanded_context and expanded_context.ui_surface_hint:
            hint = f" Navigate to {expanded_context.ui_surface_hint}."
        if route_neg and expanded_context and primary_scenario_type(expanded_context) == "action_event_flow":
            outcome_line = (
                "Verify outcomes: the action stays blocked or surfaces errors as designed, no new draft or artifact is created, "
                "and UI or messaging matches the linked acceptance criteria."
            )
        elif expanded_context and primary_scenario_type(expanded_context) == "action_event_flow":
            art_pad = (getattr(expanded_context, "artifact_label_singular", "") or "").strip() or "generated draft"
            outcome_line = (
                f"Verify outcomes: {art_pad}, blocked or permission messaging, errors, and refresh behavior "
                "match expectations."
            )
        elif route_neg:
            outcome_line = (
                "Verify outcomes: validation errors or blocked save, no incorrect persistence, and prior valid state "
                "per the linked acceptance criteria."
            )
        elif expanded_context and form_style_email_phone_step_text_forbidden(
            expanded_context, linked_text_blob=_norm_ws(title + " " + linked_blob)
        ):
            outcome_line = (
                "Verify outcomes: UI confirmation, rule or permission messaging as applicable, and persisted or refreshed state match expectations."
            )
        else:
            outcome_line = (
                "Verify outcomes: UI confirmation, field-level validation, and persisted or refreshed data match expectations."
            )
        if route_neg:
            pad = [
                f"Open the application context for this scenario.{hint}".strip(),
                "Exercise the negative conditions from the test case title using scenario context and linked acceptance criteria (attempt the blocked path).",
                outcome_line,
            ]
        else:
            pad = [
                f"Open the application context for this scenario.{hint}".strip(),
                "Perform the actions implied by the test case title using data consistent with scenario context and linked acceptance criteria.",
                outcome_line,
            ]
        existing = {re.sub(r"\s+", " ", x.lower()) for x in steps}
        for p in pad:
            if len(steps) >= _MIN_STEPS:
                break
            pl = re.sub(r"\s+", " ", p.lower())
            if pl not in existing:
                steps.append(_truncate_step(_polish_vocabulary(p)))
                existing.add(pl)

    steps = [_truncate_step(_polish_vocabulary(s)) for s in steps if s.strip()]
    steps = _dedupe_similar_steps(steps)
    steps = _trim_steps_to_max(steps, _MAX_STEPS)
    steps = _sanitize_output_steps_for_family(
        steps,
        expanded_context,
        title=title,
        linked_ac_blob=linked_blob,
    )
    return steps


def propose_test_steps_for_all_active_tcs(sess: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    One proposal object per active test case with non-empty title.

    Each dict: ``tc_slot``, ``tc_id``, ``title``, ``steps`` (list of str).
    """
    from src.scenario_context_expansion import expanded_context_from_builder_session
    from src.scenario_test_case_intent import infer_intent_from_builder_session

    exp = expanded_context_from_builder_session(sess)
    out: list[dict[str, Any]] = []
    for j in active_tc_indices(sess):
        title = str(sess.get(f"sb_tc_{j}_text") or "").strip()
        if not title:
            continue
        tid = str(sess.get(f"sb_tc_{j}_id") or "").strip() or f"TC-{j + 1:02d}"
        ctxs = linked_ac_texts_for_tc(sess, j)
        tc_intent = infer_intent_from_builder_session(sess, j, linked_ac_texts=ctxs)
        steps = generate_default_test_steps(
            test_case_title=title,
            linked_ac_texts=ctxs,
            expanded_context=exp,
            intent=tc_intent,
        )
        steps = [s for s in steps if s.strip()]
        if not steps:
            continue
        out.append(
            {
                "tc_slot": j,
                "tc_id": tid,
                "title": title,
                "steps": steps,
            }
        )
    return out

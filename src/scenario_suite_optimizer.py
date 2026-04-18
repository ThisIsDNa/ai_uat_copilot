"""
Batch-only suite optimization: remove functionally redundant generated test case proposals.

Runs after titles (and uses generated steps + intent) to cluster duplicates; keeps the
strongest representative per cluster and records merged AC indices for traceability.

Does **not** run on single-TC step regeneration — only via ``propose_*`` batch paths.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Mapping


def _norm_ws(s: str) -> str:
    return " ".join(str(s).split()).strip()


def _steps_canonical_signature(steps: list[str]) -> str:
    """
    Normalized step sequence for duplicate detection (masks long numbers, strips re-check noise).
    """
    parts: list[str] = []
    for s in steps or []:
        t = re.sub(r"^\d+\.\s*", "", (s or "").lower())
        t = re.sub(r"\bre[\s-]*check\b", "", t)
        t = re.sub(r"\bpersist\s+updated\s+values\b", "persist state", t)
        t = re.sub(r"\bupdated\s+values\s+persist\b", "persist state", t)
        t = re.sub(r"\d{5,}", "#", t)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            parts.append(t)
    return "||".join(parts) if parts else "empty"


def _step_similarity_signature(steps: list[str]) -> str:
    """Coarse ordered-agnostic fingerprint of action / trigger / verify shape."""
    flags: set[str] = set()
    for s in steps:
        t = re.sub(r"^\d+\.\s*", "", (s or "").lower())
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        if re.search(r"\b(navigate|open)\b", t):
            flags.add("N")
        if re.search(r"\b(save|submit|update|commit|continue)\b", t):
            flags.add("T")
        if re.search(r"\b(refresh|reload|re-?open)\b", t):
            flags.add("R")
        if re.search(r"\b(confirm|toast|banner|confirmation|success\s+message)\b", t):
            flags.add("C")
        if re.search(r"\b(verify|validate)\b", t):
            flags.add("V")
        if re.search(r"\b(inline|validation|error|invalid|blocked|permission)\b", t):
            flags.add("E")
    return "".join(sorted(flags)) or "X"


def _title_specificity_score(title: str) -> int:
    rhs = title.split(" - ", 1)[-1] if " - " in title else title
    r = rhs.lower()
    score = min(len(rhs.split()), 14)
    if "contact" in r:
        score += 10
    if "email" in r and "phone" in r:
        score += 6
    if "confirmation" in r or "save confirmation" in r:
        score += 4
    for bad in ("persist updated values", " re-check", "re-check", "complete primary flow"):
        if bad in r:
            score -= 18
    if "persist" in r and "refresh" in r:
        score += 5
    if "validation pass" in r:
        score += 3
    if "generate notes" in r or "generate reply" in r or "generate summary" in r:
        score += 14
    if "notes draft" in r or "reply draft" in r:
        score += 12
    if "artifact" in r or "workflow outcome" in r or "primary workflow" in r:
        score -= 12
    return score


def _step_depth_score(steps: list[str]) -> int:
    blob = " ".join(steps).lower()
    s = len(steps) * 5 + min(len(blob) // 10, 40)
    for kw in ("refresh", "re-open", "persist", "toast", "banner", "confirmation", "verify", "save", "submit"):
        if kw in blob:
            s += 4
    return s


def _persist_scope_bucket(intent: Any, title: str) -> str:
    sc = (getattr(intent, "target_scope", "") or "").strip().lower()
    if sc == "email":
        return "email"
    if sc == "phone":
        return "phone"
    if sc in ("contact_info", "persistence"):
        return "contact"
    rhs = title.split(" - ", 1)[-1].lower() if " - " in title else title.lower()
    if "contact" in rhs:
        return "contact"
    if "email" in rhs and "phone" not in rhs:
        return "email"
    if "phone" in rhs and "email" not in rhs:
        return "phone"
    return "generic"


def _positive_functional_cluster_key(
    intent: Any,
    title: str,
    steps: list[str],
    exp: Any | None = None,
) -> str:
    from src.scenario_type_gating import cluster_type_prefix

    pref = cluster_type_prefix(exp)
    cond = (intent.condition_type or "").strip()
    vf = (getattr(intent, "verification_focus", "") or "").strip().lower()
    sig = _step_similarity_signature(steps)

    if pref == "action_event_flow":
        sc = (getattr(intent, "target_scope", "") or "").strip().lower()
        rhs = title.split(" - ", 1)[-1].lower() if " - " in title else title.lower()
        if cond == "rule_blocked" or vf == "blocked_combination" or "blocked" in rhs:
            return f"{pref}|BLOCK|{sc}|{sig}"
        if cond == "permission_issue":
            return f"{pref}|BLOCK|perm|{sc}|{sig}"
        if cond == "dependency_failure":
            return f"{pref}|FAIL|service|{sc}|{sig}"
        if vf == "action_trigger_success" or sc == "generate_action":
            return f"{pref}|ACTION|{sc}|{sig}"
        if vf in ("artifact_created", "remains_draft", "editable_before_send", "no_auto_send") or sc in (
            "generated_draft",
            "draft_state",
            "draft_editability",
            "auto_send_prevention",
        ):
            return f"{pref}|STATE|{sc}|{vf}|{sig}"
        if vf == "persists_after_refresh" or sc == "action_persistence":
            return f"{pref}|PERSIST|{sc}|{sig}"
        if cond == "confirmation_check" or vf == "confirmation_or_visible_result":
            return f"{pref}|RESULT|{sc}|{sig}"
        return f"{pref}|AE|{cond}|{vf}|{sc}|{sig}"

    if cond == "confirmation_check" or vf == "confirmation_message":
        return f"{pref}|CONF|{sig}"

    if cond == "rule_blocked" or vf == "blocked_combination":
        return f"{pref}|RULEBLK|{sig}"

    if cond == "persisted_state_check" or vf == "persistence_after_refresh":
        bucket = _persist_scope_bucket(intent, title)
        return f"{pref}|PERS|{bucket}|{sig}"

    if vf == "validation_pass":
        scope = (getattr(intent, "target_scope", "") or "").strip().lower() or _persist_scope_bucket(intent, title)
        return f"{pref}|VPASS|{scope}|{sig}"

    if vf in ("ui_consistency", "business_outcome"):
        return f"{pref}|{vf.upper()}|{sig}"

    sc_toggle = (getattr(intent, "target_scope", "") or "").strip().lower()
    if vf in ("enable_transition", "disable_transition"):
        return f"{pref}|TOGGLE|{sc_toggle}|{vf}|{sig}"
    if sc_toggle in ("notification_preferences", "email_toggle", "sms_toggle") and vf == "valid_save":
        return f"{pref}|NOTIFSAVE|{sc_toggle}|{sig}"

    # valid save / default happy path — split by field scope so email vs phone are never collapsed together
    scope = (getattr(intent, "target_scope", "") or "").strip().lower()
    rhs = title.split(" - ", 1)[-1].lower() if " - " in title else title.lower()
    if scope == "email" or ("email" in rhs and "phone" not in rhs):
        return f"{pref}|SAVE|email|{sig}"
    if scope == "phone" or ("phone" in rhs and "email" not in rhs):
        return f"{pref}|SAVE|phone|{sig}"
    if scope == "contact_info" or "contact" in rhs:
        return f"{pref}|SAVE|contact|{sig}"
    return f"{pref}|SAVE|other|{vf}|{scope}|{sig}"


def _best_title_in_cluster(titles: list[str]) -> str:
    return max(titles, key=lambda t: (_title_specificity_score(t), len(t)))


def _primary_row_for_best_title(group: list[dict[str, Any]], best_title: str) -> dict[str, Any]:
    """
    Return the proposal row whose title matches ``best_title`` (normalized).

    Keeps ``ac_index`` / ``ac_id`` / ``criterion`` aligned with the chosen display title when
    merging duplicates — never pair another row's AC text with a best title from a sibling.
    """
    bt = _norm_ws(best_title)
    btl = bt.lower()
    for x in group:
        xt = _norm_ws(str(x.get("title") or ""))
        if xt == bt or xt.lower() == btl:
            return dict(x)
    return dict(group[0])


_STALE_AE_GENERIC_TITLE = re.compile(
    r"(?i)^\s*(update|verify|complete)\s+(all\s+)?required\s+fields\b",
)


def _drop_stale_action_event_generic_title(exp: Any, proposal: Mapping[str, Any]) -> bool:
    """True if this positive proposal should be removed (action/event only, generic field-save leakage)."""
    from src.scenario_type_detection import primary_scenario_type

    if exp is None or primary_scenario_type(exp) != "action_event_flow":
        return False
    t = _norm_ws(str(proposal.get("title") or ""))
    return bool(_STALE_AE_GENERIC_TITLE.match(t))


def _enrich_positive_row(
    row: Mapping[str, Any],
    exp: Any,
    sess: Mapping[str, Any] | None = None,
) -> tuple[Any, list[str]]:
    from src.scenario_builder_steps_gen import generate_default_test_steps
    from src.scenario_positive_coverage_plan import (
        build_positive_coverage_plan_for_session,
        consolidate_positive_coverage_plan,
        coverage_slot_from_test_case_title,
    )
    from src.scenario_test_case_intent import infer_test_case_intent

    title = str(row.get("title") or "").strip()
    crit = str(row.get("criterion") or "").strip()
    slot: dict[str, Any] | None = None
    ac_i = int(row.get("ac_index", -1))
    if sess is not None and ac_i >= 0:
        plan = consolidate_positive_coverage_plan(
            build_positive_coverage_plan_for_session(sess, exp),
            exp,
            sess,
        )
        raw = plan.get(ac_i)
        if isinstance(raw, dict) and raw:
            slot = dict(raw)
    if not slot:
        inferred = coverage_slot_from_test_case_title(title)
        slot = dict(inferred) if inferred else {}
    intent = infer_test_case_intent(
        test_case_title=title,
        linked_acceptance_criteria=[crit] if crit else None,
        criterion_text_only=crit,
        expanded=exp,
        is_negative=False,
        coverage_slot=slot,
    )
    steps = generate_default_test_steps(
        test_case_title=title,
        linked_ac_texts=[crit] if crit else None,
        expanded_context=exp,
        intent=intent,
    )
    return intent, steps


def _enrich_negative_row(
    row: Mapping[str, Any],
    exp: Any,
) -> tuple[Any, list[str]]:
    from src.scenario_builder_steps_gen import generate_default_test_steps
    from src.scenario_test_case_intent import infer_test_case_intent

    title = str(row.get("title") or "").strip()
    crit = str(row.get("criterion") or "").strip()
    intent = infer_test_case_intent(
        test_case_title=title,
        linked_acceptance_criteria=[crit] if crit else None,
        criterion_text_only=crit,
        expanded=exp,
        is_negative=True,
        negative_field_variant=int(row.get("ac_index", 0)),
    )
    steps = generate_default_test_steps(
        test_case_title=title,
        linked_ac_texts=[crit] if crit else None,
        expanded_context=exp,
        intent=intent,
    )
    return intent, steps


def optimize_positive_test_case_proposals(
    proposals: list[dict[str, Any]],
    sess: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Collapse functionally redundant positive proposals; survivors may list ``merged_ac_indices``.

    Batch generation only (called from ``propose_test_cases_from_acceptance_criteria``).
    """
    from src.scenario_context_expansion import expanded_context_from_builder_session

    exp = expanded_context_from_builder_session(sess)
    if len(proposals) <= 1:
        return [
            _strip_internal_positive(dict(r))
            for r in proposals
            if not _drop_stale_action_event_generic_title(exp, r)
        ]

    enriched: list[dict[str, Any]] = []
    for row in proposals:
        r = dict(row)
        intent, steps = _enrich_positive_row(r, exp, sess)
        r["_intent"] = intent
        r["_steps"] = steps
        r["_key"] = _positive_functional_cluster_key(intent, r.get("title", "") or "", steps, exp)
        enriched.append(r)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        by_key[str(r["_key"])].append(r)

    survivors: list[dict[str, Any]] = []
    for key in sorted(by_key.keys()):
        group = by_key[key]
        if len(group) == 1:
            g0 = group[0]
            survivors.append(_strip_internal_positive(g0))
            continue
        group.sort(
            key=lambda x: (
                -(_title_specificity_score(str(x.get("title") or "")) + _step_depth_score(x.get("_steps") or [])),
                -_title_specificity_score(str(x.get("title") or "")),
                int(x.get("ac_index", 0)),
            )
        )
        merged_acs = sorted(
            {int(x.get("ac_index", -1)) for x in group if int(x.get("ac_index", -1)) >= 0}
        )
        best_title = _best_title_in_cluster([str(x.get("title") or "") for x in group])
        primary = _primary_row_for_best_title(group, best_title)
        out_row = {
            "ac_index": int(primary.get("ac_index", -1)),
            "ac_id": str(primary.get("ac_id") or ""),
            "criterion": str(primary.get("criterion") or ""),
            "title": _norm_ws(best_title),
            "merged_ac_indices": merged_acs,
        }
        survivors.append(out_row)

    survivors.sort(key=lambda x: int(x.get("ac_index", 0)))
    return survivors


def _strip_internal_positive(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not str(k).startswith("_")}


def optimize_negative_test_case_proposals(
    proposals: list[dict[str, Any]],
    sess: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Conservative dedupe: collapse only when condition, target field, steps, and title all align.

    Batch generation only.
    """
    if len(proposals) <= 1:
        return list(proposals)

    from src.scenario_context_expansion import expanded_context_from_builder_session

    exp = expanded_context_from_builder_session(sess)
    enriched: list[dict[str, Any]] = []
    for row in proposals:
        r = dict(row)
        intent, steps = _enrich_negative_row(r, exp)
        tl = str(r.get("title") or "").strip().lower()
        tf = (intent.target_field or "").strip().lower()
        sig = _step_similarity_signature(steps)
        r["_key"] = f"{intent.condition_type}|{tf}|{sig}|{tl}"
        enriched.append(r)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in enriched:
        by_key[str(r["_key"])].append(r)

    out: list[dict[str, Any]] = []
    for key in sorted(by_key.keys()):
        group = by_key[key]
        if len(group) == 1:
            out.append({k: v for k, v in group[0].items() if not str(k).startswith("_")})
            continue
        group.sort(
            key=lambda x: (
                -(_title_specificity_score(str(x.get("title") or "")) + _step_depth_score(x.get("_steps") or [])),
                int(x.get("ac_index", 0)),
            )
        )
        winner = group[0]
        merged = sorted(
            {int(x.get("ac_index", -1)) for x in group if int(x.get("ac_index", -1)) >= 0}
        )
        out.append(
            {
                "ac_index": int(winner.get("ac_index", -1)),
                "ac_id": str(winner.get("ac_id") or ""),
                "criterion": str(winner.get("criterion") or ""),
                "title": str(winner.get("title") or "").strip(),
                "merged_ac_indices": merged,
            }
        )
    out.sort(key=lambda x: int(x.get("ac_index", 0)))
    return out


def _action_event_title_soft_bucket(title: str) -> str:
    rhs = title.split(" - ", 1)[-1].lower() if " - " in title else title.lower()
    if "persist" in rhs or "refresh" in rhs or "reload" in rhs:
        return "persist"
    if ("draft" in rhs and ("remain" in rhs or "state" in rhs)) or "not auto" in rhs:
        return "draft_state"
    if "editable" in rhs or "edit before" in rhs:
        return "edit"
    if "permission" in rhs or "unauthorized" in rhs:
        return "perm"
    if "fail" in rhs or "service" in rhs or "no draft" in rhs:
        return "fail"
    if "closed" in rhs or ("block" in rhs and "generate" in rhs):
        return "precond"
    if "appear" in rhs or "visible" in rhs or "panel" in rhs or "result" in rhs:
        return "surface"
    if "generate" in rhs or "trigger" in rhs:
        return "trigger"
    return "other"


def _final_positive_merge_bucket(exp: Any, intent: Any, title: str, steps: list[str]) -> str:
    """
    Batch-merge bucket: action_event uses title/scope soft buckets; other families use
    scope + verification_focus + condition + canonical steps so near-duplicate persists/surfaces collapse.
    """
    from src.scenario_type_detection import primary_scenario_type

    pt = primary_scenario_type(exp) if exp is not None else ""
    if pt == "action_event_flow":
        soft = _action_event_title_soft_bucket(title)
        return "ae|" + _ae_positive_merge_bucket(
            str(getattr(intent, "target_scope", "") or ""),
            str(getattr(intent, "verification_focus", "") or ""),
            soft,
        )
    sc = str(getattr(intent, "target_scope", "") or "").strip().lower()
    vf = str(getattr(intent, "verification_focus", "") or "").strip().lower()
    cond = str(getattr(intent, "condition_type", "") or "").strip().lower()
    canon = _steps_canonical_signature(steps)
    # Keep distinct negative-ish positive shells split by condition
    if cond in ("permission_issue", "dependency_failure"):
        return f"{pt}|{cond}|{sc}|{vf}|{canon}"
    return f"{pt}|{sc}|{vf}|{cond}|{canon}"


def _ae_positive_merge_bucket(scope: str, vf: str, soft: str) -> str:
    """Coarse bucket for a second-pass merge of near-duplicate positive action/event titles."""
    s = (scope or "").strip().lower()
    v = (vf or "").strip().lower()
    if soft == "persist":
        return "persist"
    if soft == "draft_state":
        return "draft_state"
    if soft == "edit":
        return "edit"
    if soft == "trigger":
        return "trigger"
    if s in ("generated_draft", "ui_consistency") or v in ("artifact_created", "confirmation_or_visible_result"):
        return "surface_visible"
    if soft == "surface":
        return "surface_visible"
    return f"other|{s}|{v}"


def semantic_dedupe_positive_proposals_final(
    proposals: list[dict[str, Any]],
    sess: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Final batch-only semantic merge: near-duplicate positives (same family, scope, focus,
    materially identical steps) collapse to the strongest title. Action/event uses surface/persist/draft buckets;
    form/toggle uses scope + vf + condition + canonical step signature.

    Not used for single-TC smart-link regeneration.
    """
    from src.scenario_context_expansion import expanded_context_from_builder_session

    exp = expanded_context_from_builder_session(sess)
    if len(proposals) <= 1:
        return [dict(r) for r in proposals if not _drop_stale_action_event_generic_title(exp, r)]
    keyed: list[tuple[str, dict[str, Any]]] = []
    for row in proposals:
        r = dict(row)
        intent, steps = _enrich_positive_row(r, exp, sess)
        bucket = _final_positive_merge_bucket(exp, intent, str(row.get("title") or ""), steps)
        keyed.append((bucket, dict(row)))

    by_b: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bucket, row in keyed:
        by_b[bucket].append(row)

    out: list[dict[str, Any]] = []
    for bucket in sorted(by_b.keys()):
        group = by_b[bucket]
        if len(group) == 1:
            out.append(group[0])
            continue
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for x in group:
            xr = dict(x)
            _intent_i, steps_i = _enrich_positive_row(xr, exp, sess)
            tit = str(x.get("title") or "")
            score = _title_specificity_score(tit) + _step_depth_score(steps_i) + len(tit) // 4
            scored.append((-score, int(x.get("ac_index", 0)), x))
        scored.sort(key=lambda t: (t[0], t[1]))
        idxs: set[int] = set()
        for x in group:
            ai = int(x.get("ac_index", -1))
            if ai >= 0:
                idxs.add(ai)
            raw_m = x.get("merged_ac_indices") or []
            if isinstance(raw_m, list):
                for m in raw_m:
                    try:
                        mi = int(m)
                    except (TypeError, ValueError):
                        continue
                    if mi >= 0:
                        idxs.add(mi)
        titles = [str(x.get("title") or "") for x in group]
        best_title = _norm_ws(_best_title_in_cluster(titles))
        primary = _primary_row_for_best_title(group, best_title)
        out.append(
            {
                "ac_index": int(primary.get("ac_index", -1)),
                "ac_id": str(primary.get("ac_id") or ""),
                "criterion": str(primary.get("criterion") or ""),
                "title": best_title,
                "merged_ac_indices": sorted(idxs),
            }
        )
    out.sort(key=lambda x: int(x.get("ac_index", 0)))
    out = [dict(r) for r in out if not _drop_stale_action_event_generic_title(exp, r)]
    return out


def semantic_dedupe_action_event_proposals(
    proposals: list[dict[str, Any]],
    sess: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Backward-compatible name — delegates to :func:`semantic_dedupe_positive_proposals_final`."""
    return semantic_dedupe_positive_proposals_final(proposals, sess)


def optimize_generated_test_suite(
    *,
    positive_proposals: list[dict[str, Any]],
    negative_proposals: list[dict[str, Any]],
    sess: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Optimize positives and negatives independently (batch suite hook)."""
    return (
        optimize_positive_test_case_proposals(positive_proposals, sess),
        optimize_negative_test_case_proposals(negative_proposals, sess),
    )

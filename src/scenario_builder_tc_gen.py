"""
Heuristic test-case title generation from acceptance criteria (guided builder C3).

No external APIs — transforms AC wording into concise, action-oriented titles suitable
for Scenario Review, test results, and DOCX export.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from src.scenario_builder_core import normalize_ac_id_token

if TYPE_CHECKING:
    from src.scenario_context_expansion import ExpandedGenerationContext

_MAX_POS_TITLE = 90
_MAX_NEG_TITLE = 88

_FILLER_PHRASES = (
    r"\bsuccessfully\b",
    r"\bappropriately\b",
    r"\bcorrectly\b",
    r"\bproperly\b",
    r"\beffectively\b",
    r"\bas\s+expected\b",
    r"\bwithout\s+issues\b",
    r"\bwithout\s+errors\b",
    r"\bwithout\s+issue\b",
)

# Leading actor / capability phrases to strip before building a title.
_ACTOR_LEAD_PATTERNS: tuple[str, ...] = (
    r"(?i)^the\s+system\s+allows\s+(?:the\s+)?user\s+to\s+",
    r"(?i)^system\s+allows\s+(?:the\s+)?user\s+to\s+",
    r"(?i)^the\s+system\s+shall\s+allow\s+(?:the\s+)?user\s+to\s+",
    r"(?i)^the\s+user\s+is\s+allowed\s+to\s+",
    r"(?i)^the\s+user\s+is\s+able\s+to\s+",
    r"(?i)^the\s+user\s+can\s+",
    r"(?i)^user\s+can\s+",
    r"(?i)^user\s+may\s+",
    r"(?i)^users?\s+can\s+",
    r"(?i)^the\s+provider\s+can\s+",
    r"(?i)^provider\s+can\s+",
    r"(?i)^the\s+tester\s+can\s+",
    r"(?i)^tester\s+can\s+",
    r"(?i)^the\s+admin(?:istrator)?\s+can\s+",
    r"(?i)^admin(?:istrator)?\s+can\s+",
)


def _norm_ws(s: str) -> str:
    return " ".join(str(s).split()).strip()


def _cap_sentence(s: str) -> str:
    s = _norm_ws(s).strip(" .;:!?")
    if not s:
        return ""
    return s[0].upper() + s[1:]


def _clip_words(t: str, max_words: int) -> str:
    words = t.split()
    if len(words) <= max_words:
        return t
    clipped = " ".join(words[:max_words]).rstrip(",;:")
    return clipped + "…"


_VAGUE_POS = re.compile(r"(?i)interact with functionality|affected by|without regressions or silent")


def _apply_actor_leads(t: str) -> str:
    s = t
    for pat in _ACTOR_LEAD_PATTERNS:
        s = re.sub(pat, "", s)
    return _norm_ws(s)


def _apply_fillers(t: str) -> str:
    s = t
    for pat in _FILLER_PHRASES:
        s = re.sub(pat, " ", s, flags=re.I)
    return _norm_ws(s)


def _trim_redundant_the(s: str) -> str:
    """Light cleanup: `` the `` in the middle → single space (keeps leading sense)."""
    s = re.sub(r"(?i)\s+the\s+", " ", " " + s + " ")
    return _norm_ws(s)


def _passive_ac_to_validation_title(t: str) -> str | None:
    """
    Map common passive / outcome AC phrasing to a concise validation-style title.
    Returns None when no rule matches.
    """
    raw = _norm_ws(t)
    if not raw:
        return None

    m = re.match(r"(?i)^(the\s+)?user\s+receives?\s+(.+)$", raw)
    if m:
        rest = _norm_ws(m.group(2).rstrip("."))
        rest = re.sub(r"(?i)^(a|an)\s+confirmation\s+message\b", "submission message", rest)
        rest = re.sub(r"(?i)^confirmation\s+message\b", "submission message", rest)
        if rest:
            body = rest.lower()
            return _cap_sentence(f"Confirm {body}")

    if re.match(
        r"(?i)^(an?\s+)?error\s+message\s+is\s+(displayed|shown)\b",
        raw,
    ):
        return "Validate error message for invalid input"

    m = re.match(r"(?i)^(.{4,72}?)\s+is\s+(displayed|shown|visible)\b", raw)
    if m:
        core = _norm_ws(m.group(1)).strip(" .;:!?")
        if len(core) >= 4:
            if re.match(r"(?i)error", core):
                return "Validate error message for invalid input"
            cl = core.lower()
            return _cap_sentence(f"Confirm {cl} is visible")

    m = re.match(r"(?i)^(.{4,72}?)\s+shall\s+be\s+(displayed|shown|visible|available)\b", raw)
    if m:
        core = _norm_ws(m.group(1)).strip(" .;:!?")
        if len(core) >= 4:
            return _cap_sentence(f"Confirm {core.lower()} is available")

    m = re.match(r"(?i)^(.{4,72}?)\s+are\s+displayed\b", raw)
    if m:
        core = _norm_ws(m.group(1)).strip(" .;:!?")
        if len(core) >= 4:
            return _cap_sentence(f"Confirm {core.lower()} are shown")

    return None


def _core_for_positive_title(text: str) -> str:
    """Strip actors and fillers; light ``the`` cleanup; first clause focus."""
    t = _norm_ws(text)
    if not t:
        return ""
    passive = _passive_ac_to_validation_title(t)
    if passive:
        return passive
    t = _apply_actor_leads(t)
    t = _apply_fillers(t)
    t = _trim_redundant_the(t)
    t = _norm_ws(t).strip(" .;:!?")
    if not t:
        return ""
    # Prefer first segment before semicolon or em-dash for scannable titles.
    t = re.split(r"[;–—]", t, 1)[0].strip()
    t = _clip_words(t, 12)
    return t


def _legacy_positive_title_fallback(
    text: str | None,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    """Passive / clause heuristics when intent-based titling is too thin."""
    _ = expanded
    raw_t = str(text or "")
    core = _core_for_positive_title(raw_t)
    passive = _passive_ac_to_validation_title(_norm_ws(raw_t))
    if passive:
        out = passive
    elif core:
        out = _cap_sentence(core.lower())
    else:
        return ""
    out = _norm_ws(out)
    if _VAGUE_POS.search(out):
        out = _VAGUE_POS.sub("", out)
        out = _norm_ws(out)
    words = out.split()
    if len(words) > 8:
        out = " ".join(words[:8]).rstrip(",;:")
    if len(out) > _MAX_POS_TITLE:
        out = out[: _MAX_POS_TITLE - 1].rstrip() + "…"
    return out


def derive_test_case_title_from_ac(
    text: str | None,
    *,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    """
    Derive a positive ``Entity - Intent`` title from AC text using **Test Case Intent** inference
    (not by trimming long AC prose).
    """
    from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent

    intent = infer_test_case_intent(
        criterion_text_only=str(text or ""),
        expanded=expanded,
        is_negative=False,
    )
    out = format_positive_title_from_intent(intent, expanded=expanded)
    vague_sub = (
        "verify validation",
        "complete workflow outcome",
        "complete primary flow",
        "verify on happy",
        "verify validation behavior",
    )
    if not out.strip() or any(v in out.lower() for v in vague_sub):
        fb = _legacy_positive_title_fallback(text, expanded)
        if fb.strip():
            return fb
        if not out.strip():
            return ""
    if len(out) > _MAX_POS_TITLE:
        out = out[: _MAX_POS_TITLE - 1].rstrip() + "…"
    return out


def _bump_positive_title_phrase_for_batch(
    intent: "object", crit: str, aid: str, bump: int
) -> None:
    """Adjust ``intent.title_phrase`` so batch-proposed positive titles diverge when ACs look similar."""
    low = crit.lower()
    cond = getattr(intent, "condition_type", "") or ""
    base = (getattr(intent, "title_phrase", "") or "").strip()
    if bump <= 0:
        return
    if cond == "happy_path" and "email" in low and "phone" in low:
        intent.title_phrase = "Update Phone - Valid Save" if bump % 2 else "Update Email - Valid Save"
        return
    if cond == "persisted_state_check":
        if "email" in low and "phone" in low:
            opts = (
                "Email Persist After Refresh",
                "Phone Persist After Refresh",
                "Contact Info Persist After Refresh",
            )
            intent.title_phrase = opts[(bump - 1) % len(opts)]
            return
        if "email" in low:
            intent.title_phrase = "Email Persist After Refresh"
            return
        if "phone" in low:
            intent.title_phrase = "Phone Persist After Refresh"
            return
    if cond == "confirmation_check":
        if "email" in low and "phone" in low:
            intent.title_phrase = "Phone Save Confirmation" if bump % 2 else "Email Save Confirmation"
            return
    intent.title_phrase = f"{base} - {aid}" if base else f"Coverage - {aid}"


def _positive_tc_title_for_ac_deduped(
    crit: str,
    expanded: "ExpandedGenerationContext | None",
    used_lower: set[str],
    aid: str,
) -> str:
    """Derive positive title; if a sibling row already used the same title, enrich with intent bumps."""
    from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent

    title = derive_test_case_title_from_ac(crit, expanded=expanded)
    if title and title.lower() not in used_lower:
        return title
    for bump in range(1, 14):
        intent = infer_test_case_intent(criterion_text_only=crit, expanded=expanded, is_negative=False)
        _bump_positive_title_phrase_for_batch(intent, crit, aid, bump)
        cand = format_positive_title_from_intent(intent, expanded=expanded)
        if cand and cand.lower() not in used_lower:
            return cand
    fallback = title or f"Verify {aid}"
    return fallback if fallback.lower() not in used_lower else f"{fallback} - {aid}"


def propose_test_cases_from_acceptance_criteria(sess: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Proposed positive test cases for AC rows with non-empty criterion text.

    After titles are built, a **suite optimization** pass removes functionally redundant
    proposals (same intent + step shape). Survivors may include ``merged_ac_indices`` so
    one TC can map to multiple ACs when applied from the guided builder.

    Returns dicts: ``ac_index``, ``ac_id``, ``criterion``, ``title``; optional ``merged_ac_indices``.
    """
    from src.scenario_context_expansion import expanded_context_from_builder_session
    from src.scenario_positive_coverage_plan import (
        build_positive_coverage_plan_for_session,
        consolidate_positive_coverage_plan,
    )
    from src.scenario_test_case_intent import format_positive_title_from_intent, infer_test_case_intent

    exp = expanded_context_from_builder_session(sess)
    plan = build_positive_coverage_plan_for_session(sess, exp)
    plan = consolidate_positive_coverage_plan(plan, exp, sess)
    n_ac = int(sess.get("sb_n_ac") or 0)
    out: list[dict[str, Any]] = []
    used_positive_titles: set[str] = set()
    for i in range(n_ac):
        crit = str(sess.get(f"sb_ac_{i}_text") or "").strip()
        if not crit:
            continue
        raw_id = str(sess.get(f"sb_ac_{i}_id") or "").strip()
        aid = normalize_ac_id_token(raw_id) if raw_id else None
        if not aid:
            aid = f"AC-{i + 1:02d}"
        slot = plan.get(i)
        intent = infer_test_case_intent(
            criterion_text_only=crit,
            expanded=exp,
            is_negative=False,
            coverage_slot=slot,
        )
        title = format_positive_title_from_intent(intent, expanded=exp)
        vague_sub = (
            "verify validation",
            "complete workflow outcome",
            "complete primary flow",
            "verify on happy",
            "verify validation behavior",
        )
        if not title.strip() or any(v in title.lower() for v in vague_sub):
            title = derive_test_case_title_from_ac(crit, expanded=exp)
        if title.lower() in used_positive_titles and slot:
            bump = dict(slot)
            hint0 = str(bump.get("intent_hint") or "").strip()
            if hint0:
                bump["intent_hint"] = f"{hint0} Re-check"
                intent2 = infer_test_case_intent(
                    criterion_text_only=crit,
                    expanded=exp,
                    is_negative=False,
                    coverage_slot=bump,
                )
                title = format_positive_title_from_intent(intent2, expanded=exp)
        if title.lower() in used_positive_titles:
            title = _positive_tc_title_for_ac_deduped(crit, exp, used_positive_titles, aid)
        if not title:
            title = f"Verify {aid}"
        title = title.rstrip(" -–—").strip()
        used_positive_titles.add(title.lower())
        out.append(
            {
                "ac_index": i,
                "ac_id": aid,
                "criterion": crit,
                "title": title,
            }
        )
    from src.scenario_suite_optimizer import (
        optimize_positive_test_case_proposals,
        semantic_dedupe_positive_proposals_final,
    )

    return semantic_dedupe_positive_proposals_final(optimize_positive_test_case_proposals(out, sess), sess)


def mapped_tc_title_lowers_for_ac(sess: Mapping[str, Any], ac_i: int) -> set[str]:
    """Lowercased titles of active TCs currently mapped on ``sb_ac_{ac_i}_map`` (for dedupe checks)."""
    return _titles_of_mapped_test_cases(sess, ac_i)


def _titles_of_mapped_test_cases(sess: Mapping[str, Any], ac_i: int) -> set[str]:
    """Lowercased titles of active test cases currently listed on ``sb_ac_{ac_i}_map``."""
    raw = sess.get(f"sb_ac_{ac_i}_map")
    mapped_lower = {
        str(x).strip().lower()
        for x in (raw if isinstance(raw, list) else [])
        if x is not None and str(x).strip()
    }
    if not mapped_lower:
        return set()
    n_tc = int(sess.get("sb_n_tc") or 0)
    out: set[str] = set()
    for j in range(n_tc):
        if sess.get(f"sb_tc_{j}_active", True) is False:
            continue
        tid_j = str(sess.get(f"sb_tc_{j}_id") or "").strip()
        if not tid_j or tid_j.lower() not in mapped_lower:
            continue
        tt = str(sess.get(f"sb_tc_{j}_text") or "").strip().lower()
        if tt:
            out.add(tt)
    return out


_BUSINESS_OUTCOME_LEAD = re.compile(
    r"(?i)^\s*(reduce|increase|improve|decrease|optimize|drive|maximize|minimize)\b"
)
# Ordered: substring test → short noun phrase for "Reject incomplete …" / captions (max ~3 words).
_NEGATIVE_TOPIC_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("enrollment", "enrollment submission"),
    ("registration", "registration submission"),
    ("checkout", "checkout submission"),
    ("reconciliation", "reconciliation submission"),
    ("appointment", "appointment booking"),
    ("scheduling", "scheduling request"),
    ("billing", "billing update"),
    ("claim", "claim submission"),
    ("prior authorization", "prior authorization request"),
    ("password reset", "password reset"),
    ("multi-factor", "multi-factor sign-in"),
    ("mfa", "multi-factor sign-in"),
    ("two-factor", "multi-factor sign-in"),
    ("sign in", "sign-in"),
    ("sign-in", "sign-in"),
    ("log in", "sign-in"),
    ("login", "sign-in"),
    ("chart", "chart update"),
    ("patient chart", "chart update"),
    ("report", "report generation"),
    ("export", "data export"),
    ("import", "data import"),
    ("profile", "profile update"),
    ("payment", "payment submission"),
    ("refund", "refund request"),
)


def _negative_topic_phrase(ac_text: str) -> str:
    """
    Short, failure-testable flow label (not a pasted AC fragment).

    Favors domain keywords over long trimmed prose so titles stay scannable in Review and DOCX.
    """
    raw = _norm_ws(ac_text)
    if not raw:
        return "submission"

    low = raw.lower()
    for needle, label in _NEGATIVE_TOPIC_KEYWORDS:
        if needle in low:
            return label

    t = _apply_actor_leads(raw)
    t = _apply_fillers(t)
    t = _trim_redundant_the(t)
    t = _norm_ws(t).strip(" .;:!?")
    t = re.split(r"[;–—]", t, 1)[0].strip()
    t = _norm_ws(t)
    if not t:
        return "submission"

    if _BUSINESS_OUTCOME_LEAD.search(t) and not re.search(
        r"(?i)\b(user|system|form|field|screen|page|button|submit|sign|login|enroll|register)\b",
        t,
    ):
        return "primary user flow"

    if re.search(r"(?i)\b(submit|submission|enroll|register)\b", t):
        return "submission"

    if re.match(r"(?i)^(an?\s+)?error\s+message\s+is\s+(displayed|shown)\b", t):
        return "invalid input handling"

    m = re.match(r"(?i)^(the\s+)?user\s+receives?\s+(.+)$", t)
    if m:
        rest = _norm_ws(m.group(2).rstrip("."))
        rest = re.sub(r"(?i)^(a|an)\s+confirmation\s+message\b", "confirmation", rest)
        rest = re.sub(r"(?i)^confirmation\s+message\b", "confirmation", rest)
        rest = _clip_words(rest.lower(), 3)
        if len(rest) >= 3 and len(rest) <= 36 and " and " not in rest:
            return rest

    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]*", t)]
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "for",
        "in",
        "on",
        "at",
        "with",
        "by",
        "from",
        "into",
        "that",
        "this",
        "can",
        "may",
        "must",
        "shall",
        "will",
        "is",
        "are",
        "be",
        "as",
        "user",
        "users",
        "system",
    }
    picked: list[str] = []
    for w in words:
        wl = w.lower()
        if wl in stop or len(wl) < 3:
            continue
        picked.append(wl)
        if len(picked) >= 2:
            break
    if picked:
        phrase = " ".join(picked)
        if len(phrase) <= 36:
            return phrase

    return "submission"


def derive_negative_test_case_title_from_ac(
    text: str | None,
    *,
    variant: int = 0,
    expanded: "ExpandedGenerationContext | None" = None,
) -> str:
    """
    Build a concise **Entity - Intent** negative title via **Test Case Intent** (failure class rotates with ``variant``).
    """
    from src.scenario_test_case_intent import format_negative_title_from_intent, infer_test_case_intent

    raw = _norm_ws(str(text or ""))
    if not raw:
        return ""
    from src.scenario_type_gating import negative_conditions_rotated

    conditions = negative_conditions_rotated(expanded, raw)
    cond = conditions[int(variant) % len(conditions)]
    intent = infer_test_case_intent(
        criterion_text_only=raw,
        expanded=expanded,
        is_negative=True,
        forced_condition=cond,
        negative_field_variant=int(variant),
    )
    out = format_negative_title_from_intent(intent, expanded=expanded)
    out = _norm_ws(out)
    if len(out) > _MAX_NEG_TITLE:
        out = out[: _MAX_NEG_TITLE - 1].rstrip(" ,;—") + "…"
    if not out:
        return "Validate error when invalid input is entered"
    return out[0].upper() + out[1:] if len(out) > 1 else out.upper()


def propose_negative_test_cases_from_acceptance_criteria(sess: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Optional **negative** test cases per AC with non-empty criterion text.

    A conservative **suite optimization** pass may merge only exact functional duplicates
    (same condition, target field, title, and step fingerprint). Optional ``merged_ac_indices``.

    Skips rows when the proposed title already matches an existing mapped TC title
    on that AC (case-insensitive), to reduce accidental duplicates on repeat clicks.
    """
    from src.scenario_context_expansion import expanded_context_from_builder_session

    exp = expanded_context_from_builder_session(sess)
    n_ac = int(sess.get("sb_n_ac") or 0)
    out: list[dict[str, Any]] = []
    used_negative_titles: set[str] = set()
    for i in range(n_ac):
        crit = str(sess.get(f"sb_ac_{i}_text") or "").strip()
        if not crit:
            continue
        raw_id = str(sess.get(f"sb_ac_{i}_id") or "").strip()
        aid = normalize_ac_id_token(raw_id) if raw_id else None
        if not aid:
            aid = f"AC-{i + 1:02d}"
        title = ""
        for bump in range(0, 28):
            cand = derive_negative_test_case_title_from_ac(crit, variant=i + bump, expanded=exp).strip()
            if not cand:
                continue
            cl = cand.lower()
            if cl in used_negative_titles:
                continue
            title = cand
            break
        if not title.strip():
            continue
        existing = mapped_tc_title_lowers_for_ac(sess, i)
        if title.strip().lower() in existing:
            continue
        used_negative_titles.add(title.strip().lower())
        out.append(
            {
                "ac_index": i,
                "ac_id": aid,
                "criterion": crit,
                "title": title,
            }
        )
    from src.scenario_suite_optimizer import optimize_negative_test_case_proposals

    return optimize_negative_test_case_proposals(out, sess)

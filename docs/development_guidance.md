# AI_UAT_Copilot — Development guidance



Authoritative context for implementation and review.



### Documentation map



| Document | Role |

|----------|------|

| **`docs/cursor_handoff.md`** | Current product + **end-to-end generation pipeline**, workflow families, **stable vs validating**, phase |

| **`docs/development_guidance.md`** | *This file* — priorities, change workflow, **where to hook generation**, **gating guardrails** |

| **`docs/schema.md`** | Internal scenario object (**canonical JSON**) |

| **`docs/testing_notes.md`** | **Stabilization playbook** + manual test history |

| **`docs/intake_notes.md`** | DOCX/JSON → dict; parser debug (**Step 0 not built**) |

| **`docs/retrospective.md`** | Historical phases |

| **`test_assets/README.md`** | Optional local fixtures (not used by the app) |



---



## Project name



**AI_UAT_Copilot**



## Project purpose



Reviewer-friendly UAT validation: **reduce cognitive load**, not replace the reviewer. **DOCX** + **AI Scenario Builder** for users; **normalized JSON** per **`docs/schema.md`** as the **internal persisted contract**.



**Roles:** **`docs/cursor_handoff.md`** matrix (**Tester** / **Test Lead** / **Test Manager**).



---



## Current priority



**Dual track:**

1. **v1 validation** — Prove the **generation stack** end-to-end: **detection → expansion → gating → coverage planning → intent → titles → steps → batch dedupe** on **weak → medium → realistic** scenarios plus the **three-family** strip in **`docs/testing_notes.md`**; fix regressions with **`pytest`** first.

2. **DOCX reliability** — Still the main **user-facing** variability risk (AC/TC/steps/changed areas/business goal extraction).



Do **not** treat “DOCX is weak” as permission to ignore **workflow-type gating** regressions; both matter.



**Before substantive generation changes:** read **`docs/cursor_handoff.md`** § pipeline and **`src/scenario_type_gating.py`** expectations.



---



## Required workflow for any changes



1. **Identify scope** — Parser-only? Generation-only? UI-only? Mixed changes need **separate** validation (JSON fixture vs builder session).

2. **First failure point** — Fix the earliest broken layer (wrong `primary_type` vs weak expansion vs over-aggressive gating, etc.).

3. **Data before chrome** — Incorrect or missing structured data outranks layout tweaks.

4. **Run tests** — `pip install -r requirements-dev.txt` then **`pytest`** from repo root; add/adjust tests when behavior is intentional.



---



## Generation routing — where logic lives (safe hooks)

Generation should **obey `primary_type`** from **`detect_scenario_type`** and respect **`scenario_type_gating`**. Do not re-implement the same filters in three places; extend the **appropriate** layer.

### System layers (in pipeline order)

| Order | Layer | Module(s) | Responsibility |
|-------|-------|-----------|----------------|
| 1 | **Detection** | `src/scenario_type_detection.py` | **`primary_type`**, **`secondary_types`**, **`signals`**, **`routing_hints`**. Change when **classification** rules change. |
| 2 | **Expansion** | `src/scenario_context_expansion.py`, `src/scenario_domain_labels.py` | Structured hints from **`scenario_context`** + classification; domain action/entity labels for **`action_event_flow`**. Interpretation of the story — **not** where to strip negatives (use gating). |
| 3 | **Strict gating** | `src/scenario_type_gating.py` | Blocks or rewrites AC lines, coverage slots, step phrases, and negative shapes that **violate** the primary family. **Single place** for cross-type leakage rules. |
| 4 | **Coverage planning** | `src/scenario_positive_coverage_plan.py` | Positive **slots** per AC; templates per **`primary_type`**; consolidation; **`positive_coverage_slot_for_tc_session`** for per-TC slot vs title alignment. |
| 5 | **Intent** | `src/scenario_test_case_intent.py` | **`TestCaseIntent`** (`target_scope`, **`verification_focus`**, `condition_type`, **`input_profile`**, etc.). Drives titles and step families. |
| 6 | **Titles** | `src/scenario_builder_tc_gen.py`, `scenario_test_case_intent.py` | Positive/negative titles; batch proposal assembly. |
| 7 | **Steps** | `src/scenario_builder_steps_gen.py` | Intent-driven steps; negative **data** lines for form failures; final **sanitize** pass for toggle / action_event isolation. |
| 8 | **AC suggestions** | `src/scenario_builder_ac_gen.py` | AC bullets; family seeds; filtered by gating. |
| 9 | **Batch dedupe** | `src/scenario_suite_optimizer.py` | **`optimize_positive_test_case_proposals`** / negative optimizer (cluster by intent + step fingerprint); **`semantic_dedupe_positive_proposals_final`** for near-duplicate **positive** batch rows. **Batch only** — not used for smart-link single-TC step regen. |
| — | **Orchestration / UI** | `src/scenario_builder_core.py`, `src/scenario_builder_ai.py`, `app.py`, `src/ui_*.py` | Session keys, dialogs, apply/merge — keep **`app.py`** thin. |



**Guardrails — do not break:**

- **Strict type gating** — Prefer improving **`signals`** in detection over disabling gating. Family-specific rules belong in **`scenario_type_gating.py`**, not copy-pasted in UI or AC gen only.
- **Scenario isolation** — Final step text must not reintroduce profile/contact/email-phone templates on **toggle** or **`action_event_flow`** without explicit user text (see **`_sanitize_output_steps_for_family`** in **`scenario_builder_steps_gen.py`**).
- **Intent-driven steps** — Do not bypass **`TestCaseIntent`** for C3 steps when intent is populated; form negatives must keep **input** aligned with **`condition_type`** (missing vs invalid vs boundary).
- **`action_event_flow`**: no generic **missing / invalid email / boundary** shells unless **`explicit_text_input_validation_context`** (hybrid) applies.
- **`state_toggle`**: no email/phone **format** negatives unless format signals exist.
- **Batch dedupe** — Do not call **`semantic_dedupe_positive_proposals_final`** from single-TC / smart-link paths; extend merge keys in **`scenario_suite_optimizer.py`** only with tests proving distinct families (permission, precondition, service failure, draft, persist, etc.) stay split.
- After changes: **`pytest`**, especially **`tests/test_action_event_flow.py`**, **`tests/test_scenario_v1_cleanup.py`**, **`tests/test_scenario_type_detection.py`**.



**Leakage vocabulary (avoid):**



- **Form → toggle:** field validation / required-field spam on notification-only stories.

- **Form/toggle → action/event:** generic “save updated record” / “enter email” when the story is **Generate / draft / blocked / permission / failure**.

- **Action/event → form:** stripping real typed-input requirements when the user **explicitly** asked for format rules (hybrid scenarios — see detection for `text_input_validation`).



---



## DOCX and intake (parallel priority)



When changing **`src/docx_parser.py`**:



- Validate against **internal JSON** baseline (fixture or saved scenario).

- Output must remain aligned with **`docs/schema.md`**.

- See **`docs/intake_notes.md`** for section heuristics and **`scripts/inspect_docx_structure.py`**.



---



## When reviewing the app



1. Parser / import gaps vs **`docs/schema.md`**

2. Data vs UI trust (misleading completeness)

3. **Generation** quality for the detected **`primary_type`**

4. Workflow friction



---



## Design principles



- Do not over-engineer; preserve **`docs/schema.md`** and reviewer workflow.

- **Streamlit:** do **not** assign to **`st.session_state`** keys backing **`st.file_uploader`**; use backing scenario dict + uploader **epoch** keys after TC deletes.

- **Images:** no invented semantics from pixels; paths per **`src/scenario_media.py`**.

- **Generation:** review dialogs, no silent replace-all; outputs stay editable after apply.



### AI generation guidelines (C3)



- **`scenario_context`** — primary author narrative for expansion; **heuristic** and **additive**.

- **Titles** — concise, **family-aligned** (action/result/state for **`action_event_flow`**).

- **Steps** — include verification where implied; **gated** language per **`scenario_type_gating.py`**.

- **Negative TCs** — optional; dedupe when redundant with mapped positives.



---



## Do not



- Break the internal JSON contract.

- **Bypass** `scenario_type_gating` from UI “special cases” without moving logic into the gating module.

- Assume DOCX structure is clean.



---



## Success criteria (v1 readiness)

- **`pytest`** green; **`docs/testing_notes.md`** playbook + **three-family** strip behave per **`primary_type`**.
- **DOCX:** clearer extraction and honest gaps on varied templates (parallel track).
- **Reviewer experience:** traceability, gaps, and exports stay consistent with the loaded dict.

### Reasoning about workflow families when adding features

Pick the **lowest layer** that can own the change: if the story is misread, fix **detection** or **expansion**; if the story is read correctly but outputs belong to the wrong family, fix **gating** or **step sanitization**; if diversity of positives is wrong, fix **coverage planning** or **suite optimizer** merge keys — avoid fixing duplicates only in the UI. When in doubt, add a **`pytest`** case that locks the intended **`primary_type`** and a short assertion on titles or steps.



---



## What the product is becoming



A system that helps reviewers answer: **“Is this scenario complete, valid, and safe to approve?”** — with **typed workflow routing** so generated tests read like the **actual** product behavior (form vs toggle vs **action/event**), not generic placeholders.



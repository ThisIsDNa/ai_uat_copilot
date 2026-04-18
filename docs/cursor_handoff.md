# AI_UAT_Copilot — Cursor Handoff Brief

## Source of truth (documentation)

| Priority | Document | Role |
|----------|----------|------|
| **1** | **`docs/cursor_handoff.md`** | This file — **current** product flow, **generation architecture**, lifecycle, limitations, phase |
| **2** | **`docs/development_guidance.md`** | How to change the codebase safely: priorities, hooks, **generation routing**, gating guardrails |
| **3** | **`docs/schema.md`** | Canonical **internal scenario object** (persisted JSON, parser output) |
| **4** | **`docs/testing_notes.md`** | **Validation playbook** (tiers + **§1.5 three-family** strip + regressions) + historical manual-test notes |
| **5** | **`docs/intake_notes.md`** | DOCX / JSON → dict; parser debugging (**Step 0 intake not built yet**) |
| **6** | **`docs/retrospective.md`** | Project arc — **historical**; not the live architecture spec |

**Overlap:** Quick schema reminders below mirror **`docs/schema.md`**; **schema.md** wins on field definitions. **DOCX change rules** live in **`docs/development_guidance.md`**.

**Product split (current):**

| Role (simulated; sidebar) | Primary tools | Responsibility |
|---------------------------|---------------|----------------|
| **Tester** | **AI Scenario Builder**, **File Upload** (DOCX import), **Scenario Management** | **Author** structured scenarios (builder **Save** persists the internal contract); **import** partner **DOCX**; no **Scenario Review** tab |
| **Test Lead** | Above + **Scenario Review** | **Validate / review / approve** packets; **Export DOCX**; change testing status where enabled |
| **Test Manager** | Full app views | Same as Test Lead + **delete** saved scenarios where the UI allows |

- **AI Scenario Builder** = authoring (guided + classic), including **C3** optional **AI generation** (AC, TC, negative TC, steps) with review/confirm before apply.
- **Scenario Review** (sidebar label; internal session key **`Overview`**) = validation / review / export of the loaded scenario.
- **JSON** per **`docs/schema.md`** = internal persisted contract. **DOCX** = primary user interchange for import and export—not hand-edited JSON in the default UX.

## Project purpose

AI_UAT_Copilot turns UAT scenario data into a structured, reviewer-friendly validation packet. It does **not** replace the reviewer; it reduces cognitive load. Pillars: **scenario lifecycle**, **reviewer workflow**, **input normalization** (DOCX / builder → normalized JSON).

---

## Phase and timeline (where we are)

| Stage | Status | Notes |
|-------|--------|--------|
| **Core build** (Scenario Builder, review, smart linking, DOCX export, persistence) | **Complete** | Treat as **stable** unless regression found |
| **Generation stack** (detection, expansion, gating, coverage, intent, titles, steps, batch semantic dedupe, **`action_event_flow`**, domain-aware polish) | **Complete for v1** | Behavior documented here; **`pytest`** is the regression gate. Heuristic quality on arbitrary prose can still vary. |
| **DOCX parsing quality** | **Ongoing risk** | Heuristic extraction of AC / TC / steps / changed areas / business goal remains **variable** on real templates |
| **Step 0 — dedicated context intake UI** | **Not implemented** | Optional future upstream capture **before** heavy generation; see **`docs/intake_notes.md`**. Does **not** block v1 of the current builder-driven flow. |
| **LLM-backed enrichment** (Reviewer Focus, traceability, optional gaps merge) | **Optional** | When **`OPENAI_API_KEY`** is unset, placeholders apply; not part of the deterministic C3 path. |

**Recommended next steps (in order):**

1. **v1 validation** — run **`docs/testing_notes.md`** (weak → medium → realistic + **three-family** strip); confirm no regressions in **`pytest`**.
2. **Real-world DOCX** — spot-check imports; treat weak sections as parser follow-ups, not generation defects.
3. **Productization** — Step 0 (if desired), UX polish, packaging — **after** (1)–(2) confidence.

---

## End-to-end generation pipeline (C3)

Authoritative **code** lives under **`src/`**. The deterministic path is **heuristic** (rules + templates), not a hosted ML service. Optional OpenAI use is limited to review/traceability features when configured — see **Phase** table above.

**Canonical narrative:** **`scenario_context`** is the single intake field the builder treats as the **authoritative free-text story** for detection, expansion, and C3 generation. Other fields (`business_goal`, `workflow_name`, changed areas, dependencies) refine hints. Legacy **`story_description`** (and related story fields) on older JSON/DOCX payloads are **merged into** **`scenario_context`** when context is empty (**`merge_legacy_story_into_scenario_context`** in **`src/scenario_builder_core.py`**); new authoring should prefer **`scenario_context`** only.

**Pipeline order (stable):**

1. **`scenario_context`** (+ merged legacy story, goals, workflow, areas, dependencies) — session / scenario dict.
2. **Scenario type detection** — **`src/scenario_type_detection.py`**: **`primary_type`**, **`secondary_types`** (e.g. **`business_rule`** overlays), **`signals`**, **`routing_hints`**. Feeds expansion and every downstream gate.
3. **Context expansion** — **`src/scenario_context_expansion.py`**: entities, validation/behavior hints, risks, **`action_event_lines`** when applicable, **`scenario_classification`** copy, domain labels (**`primary_action_label`**, artifact/record nouns) via **`src/scenario_domain_labels.py`**. **Additive** only.
4. **Strict type gating** — **`src/scenario_type_gating.py`**: prevents **cross-family leakage** (form-style email/phone negatives and generic “save record” shells on **toggle** or **`action_event_flow`** unless user text explicitly supports typed-input validation). Also sanitizes AC suggestions and positive coverage slots where needed.
5. **Positive coverage planning** — **`src/scenario_positive_coverage_plan.py`**: per-AC **slots** (`target_scope`, **`verification_focus`**, `intent_hint`, optional `forced_condition`), including **`action_event_flow`** templates and consolidation to reduce duplicate shells.
6. **Intent derivation** — **`src/scenario_test_case_intent.py`**: **`TestCaseIntent`** from title/criterion + expansion + **coverage slot**. Batch TC proposals use the consolidated plan slot by **`ac_index`**. Per-TC step regen resolves the slot via **`positive_coverage_slot_for_tc_session`** in **`src/scenario_positive_coverage_plan.py`** (plan vs title disagreement → title wins so multiple TCs on one AC can differ).
7. **Titles** — **`src/scenario_builder_tc_gen.py`** + **`format_positive_title_from_intent`** / **`format_negative_title_from_intent`** in **`scenario_test_case_intent.py`**: family-aligned wording (incl. domain polish for **`action_event_flow`**).
8. **Steps** — **`src/scenario_builder_steps_gen.py`**: intent-driven templates; negative **input** lines match failure class (missing vs invalid vs boundary) for **form_input**; final **output sanitization** removes stray profile/email language on **toggle** and wrong action nouns on **`action_event_flow`** when gated.
9. **Acceptance criteria (suggestions)** — **`src/scenario_builder_ac_gen.py`**: uses expansion + classification; gating filters lines in **`scenario_type_gating.filter_ac_suggestions_under_gating`**.
10. **Batch suite optimization** — **`src/scenario_suite_optimizer.py`**: **`optimize_positive_test_case_proposals`** / negatives (cluster by intent + step shape; plan-aligned enrichment); then **`semantic_dedupe_positive_proposals_final`** collapses near-duplicate **positive** batch proposals (same family + scope/focus + canonical step signature, or action/event surface buckets). **Not** run on per-row smart-link step regen.
11. **Review / placeholders** — **`src/scenario_review_summary.py`**, **`src/placeholder_outputs.py`**, **`src/ui_review_synthesis.py`** (optional AI bias when expansion shows **`action_event_flow`**).

**Export:** **`src/scenario_export_docx.py`** — DOCX from the loaded scenario dict.

---

## Supported workflow families (generation routing)

Classification is **best-effort**. **`primary_type`** chooses the dominant family; **`secondary_types`** can include overlays (e.g. **`business_rule`** with **`state_toggle`** or **`form_input`**).

| `primary_type` (and overlays) | Meaning (short) | Typical generation emphasis |
|-------------------------------|-----------------|------------------------------|
| **`form_input`** | Typed fields, formats, required inputs | Validation, required-field / boundary / save paths when signals support it |
| **`state_toggle`** | Preferences, notifications, ON/OFF | Toggle state, blocked combinations, preferences save/persist — **not** generic profile/email/phone entry unless explicit hybrid text |
| **`business_rule`** | Cross-field / logical constraints | Usually a **secondary**; enforced in AC/steps when combined with form or toggle |
| **`approval_or_status_flow`** | Approvals, lifecycle states | Status transitions where detected |
| **`action_event_flow`** | User **action** → system **artifact** / state (AI draft, job, export, retry) | Trigger (**Generate …**), draft/visibility, precondition block, permission, service failure (**no** draft), persistence, **no** forbidden auto-send |
| **Other primaries** (`data_table_or_list_management`, `file_or_attachment_flow`) | Lists / files | Routed when signals dominate |

**Strict gating** (`scenario_type_gating.py`) enforces **scenario isolation**: wrong-family vocabulary and negatives are dropped or rewritten so outputs read like the **detected** workflow, not a generic form suite.

---

## What is stable vs optional / deferred

**Stable for v1 (fix regressions if tests fail):**

- Internal **JSON** contract (**`docs/schema.md`**), registry save/load, builder save, AC↔TC mapping rules, unmapped-TC gates
- **Deterministic C3 pipeline**: detection → expansion → gating → coverage → intent → titles → steps → **batch** suite optimization + **`semantic_dedupe_positive_proposals_final`**
- Modules: **`scenario_type_detection`**, **`scenario_context_expansion`**, **`scenario_type_gating`**, **`scenario_positive_coverage_plan`**, **`scenario_test_case_intent`**, **`scenario_builder_ac_gen`**, **`scenario_builder_tc_gen`**, **`scenario_builder_steps_gen`**, **`scenario_suite_optimizer`**, **`scenario_domain_labels`**, **`scenario_builder_core`** (merge + session helpers)
- **`tests/`** — including **`tests/test_action_event_flow.py`**, **`tests/test_scenario_v1_cleanup.py`**, **`tests/test_scenario_domain_polish.py`**, gating and suite tests

**Still variable in the wild (not a code “todo,” but expect noise):**

- **Heuristic** `primary_type` on messy or multi-topic prose
- **DOCX** extraction quality (AC/TC/steps/areas/goal)
- Subjective **wording** quality for uncommon domains

**Optional / not part of deterministic v1:**

- **Step 0** dedicated intake UI (see **`docs/intake_notes.md`**)
- **LLM** paths when API key absent (placeholders)
- Marketing / full **release** narrative beyond **`CHANGELOG.md`** facts

---

## Current capabilities (product)

- **App views** — **`Title Screen`**, **`File Upload`** (DOCX), **`AI Scenario Builder`**, **`Scenario Management`**, **`Scenario Review`** (`Overview`). **Tester** does not see **Scenario Review**.
- **Scenario catalog** — **`BUNDLED`** empty; catalog = **saved** registry (`data/saved_scenarios/` + `data/scenario_registry.json`) + optional **`[Draft]`** session scenario. Dropdown = **titles**; **`scenario_id`** under **Scenario details**.
- **DOCX ingestion** — **File Upload** → parse → normalized JSON + registry; **`ingestion_meta`** when present.
- **Scenario Review** — **Scope & Context**, **Test Cases**, **Test Results** (Reviewer Focus → Coverage gaps → structural feedback / suggested fixes → bordered test results, export, checkboxes).
- **C3 generation** — AC / positive TC / optional negative TC / steps with confirm-before-apply; **smart linking** from review signals to builder where wired.

---

## Scenario lifecycle (short)

1. **Land** — Title Screen; pick role.
2. **Import / create** — File Upload (DOCX) or AI Scenario Builder → **Save**.
3. **Preview / trust** — Quick stats and warnings where implemented.
4. **Persist** — JSON under `data/saved_scenarios/` + registry.
5. **Select** — Scenario Review dropdown.
6. **Delete** (optional) — Scenario Management, **Test Manager** only for saved rows.

---

## Internal scenario schema (simplified)

Authoritative: **`docs/schema.md`**.

- **`scenario_id`**, **`acceptance_criteria`** (`test_case_ids`), **`test_cases`** (`steps`, `expected_step_screenshots`, …)
- **`scenario_context`** — **Canonical narrative for C3** (detection, expansion, generation). Prefer this field for new scenarios.
- **`story_title`**, **`story_description`** — legacy/display; **`story_description`** is merged into **`scenario_context`** when context is empty on load/save paths.
- **`business_goal`**, **`workflow_name`**, **`changed_areas`**, **`known_dependencies`**, **`notes`**
- **`workflow_process_screenshots`**

---

## Key product principles

- Do **not** replace the reviewer.
- Prioritize **Test Results** evidence, **traceability** (AC↔TC), **coverage clarity**.
- **One strong signal** over redundant panels.
- **Generation** must stay **non-destructive by default** (confirm on replace).

---

## Known limitations

- **DOCX** — AC / TC / steps / changed areas / business goal **unreliable** when headings and layout diverge from heuristics; treat imports as **draft** until verified in Scenario Review.
- **`.docx` parsing** — heading / list / table inference; see **`docs/intake_notes.md`**.
- **Screenshot mapping** — figure references help; order fallback can mis-assign.
- **Reviewer Focus** — OpenAI when configured; else placeholders.
- **Coverage gaps** — rule-based (+ optional AI); still tuning noise vs signal.
- **Delete** does not remove **`data/docx_imports/<slug>/`** media trees.

---

## Rules for making changes

- Follow **`docs/development_guidance.md`**.
- Do **not** break **`docs/schema.md`** persistence, builder save, or tests.
- When touching **generation**, respect **`primary_type`** and **`scenario_type_gating`** — run **`pytest`**.
- Prefer small, targeted parser changes; surface **uncertainty** instead of implying full extraction.

---

## What NOT to do

- Do not hand-edit raw JSON as the default user path.
- Do not redesign the entire UI in one pass.
- Do not **weaken type gating** to “make more tests” — fix **detection** or **slot templates** instead.
- Do not add **Step 0** product scope without an explicit decision (design still TBD).

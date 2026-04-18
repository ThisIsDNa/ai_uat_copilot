# Testing notes — AI_UAT_Copilot

Companion to **`docs/cursor_handoff.md`** (product + **generation architecture**), **`docs/development_guidance.md`** (change workflow + **gating guardrails**), **`docs/schema.md`**, **`docs/intake_notes.md`**, **`docs/retrospective.md`**, **`test_assets/README.md`**.

**Phase:** **Stabilization → v1 readiness** — the deterministic generation stack is **feature-complete**; this playbook validates behavior before calling v1 shipped. DOCX intake remains a separate variability risk; see **`docs/cursor_handoff.md`** for stable vs optional scope.

---

## 1. Stabilization validation playbook

### 1.1 Scenario purpose tiers (what to run)

| Tier | Purpose | What it should expose |
|------|---------|------------------------|
| **Weak** | Thin or vague **`scenario_context`**, minimal goal/areas | Expansion + detection still pick a coherent **`primary_type`**; generation **does not invent** strict field rules; **no false completeness**. |
| **Medium** | Clear goal + context; a few ACs; typical SME prose | AC/TC/steps quality; **traceability** after generation; **smart linking** still points to sensible builder actions. |
| **Realistic** | Full session: context + goals + changed areas + multi-AC as a real team would write | End-to-end **Save → Review → Export DOCX**; coverage gaps and reviewer focus **grounded** in text; **no orphan TCs**. |
| **Cross-domain** | Same **machinery**, different domains (support AI draft, expense submit, notification toggle, profile form) | **`primary_type`** matches story shape: **`action_event_flow`** vs **`form_input`** vs **`state_toggle`**; **gating** prevents wrong-family negatives/steps. |

### 1.2 Workflow families (generation — what “good” looks like)

Heuristic classification is in **`src/scenario_type_detection.py`**. When exercising manually, confirm outputs **feel like** the family:

| Family | Signals in user text | Generation should **prefer** |
|--------|----------------------|------------------------------|
| **`form_input`** | Typed fields, formats, required inputs | Validation, required field / boundary **only when** user (or hybrid text) explicitly calls for them |
| **`state_toggle`** | Toggles, notifications, subscribe | State before/after, UI toggle, notification content — **not** unrelated CRUD field spam |
| **`business_rule`** | Cross-field rules | Often with form or toggle; constraints reflected in AC/steps |
| **`action_event_flow`** | Generate, draft, click, blocked when closed, permission, service failure | Trigger → artifact → **Draft/final state**, edit before send, **no auto-send**, persistence, failure = **no artifact** |

### 1.3 Known regression checks (generation + structure)

After code changes to detection, expansion, gating, coverage, intent, steps, or suite optimizer:

| Check | Failure mode to watch for |
|-------|---------------------------|
| **No form leakage into toggle** | Email/phone/required-field negatives on pure notification/toggle stories |
| **No toggle leakage into action/event** | Generic on/off steps dominating **Generate / draft / retry** flows |
| **No form-style leakage into action/event** | Generic “save updated record”, “enter email”, boundary tests **without** explicit typed-input cues |
| **No orphan TCs** | TC ids not on any AC **`test_case_ids`** after builder operations |
| **No incomplete steps** | Empty step rows where titles imply verification |
| **No duplicate / collapsed suites** | Semantically distinct positives (e.g. **draft state** vs **permission block**) merged into one cluster incorrectly — see **`src/scenario_suite_optimizer.py`** |

### 1.4 Automated regression

From repo root: `pip install -r requirements-dev.txt` then **`pytest`**. Tests live under **`tests/`** (include **`tests/test_action_event_flow.py`**, **`tests/test_scenario_v1_cleanup.py`**, **`tests/test_scenario_domain_polish.py`**). Optional **`test_assets/docx/*.docx`** fixtures may be **skipped** if missing.

### 1.5 Final three-family validation (before v1)

Run **three** short builder sessions (or equivalent JSON) so each run has a clear dominant shape. After **C3** proposals (AC / TC / steps) where applicable, confirm:

| Family | Purpose of the fixture | Pass criteria (manual) |
|--------|------------------------|-------------------------|
| **`action_event_flow`** | AI / trigger → draft (e.g. **Generate Notes** or **Generate Reply**, meeting/conversation, draft panel, persist, permission, failure) | Steps use **click/trigger → draft → verify** language; **no** generic “save updated record” / profile email-phone unless the narrative explicitly asks; **no** wrong action name (notes vs reply); batch positives **dedupe** obvious duplicate persist/surface rows. |
| **`state_toggle`** + **`business_rule`** | Notification preferences, ON/OFF, blocked all-off | Steps use **toggle / channel / Save preferences**; **no** “enter email and phone” or profile-update templates unless hybrid text explicitly requires format validation. |
| **`form_input`** | Profile / contact with email + phone validation | Negatives include **concrete** inputs: malformed email, bad phone, **cleared** field for missing-required; positives include valid-save / persist / confirmation where appropriate. |

**Regression checklist (after any generation change):**

| Check | What “bad” looks like |
|-------|------------------------|
| **No cross-type leakage** | Toggle story with email/phone format negatives; action/event story dominated by save/contact steps. |
| **Correct negative inputs** | “Invalid email” step still shows valid email; “missing phone” step does not say “clear phone”. |
| **Batch dedupe** | Two near-identical **positive** batch proposals (same persist or same “visible in panel”) both kept when steps differ materially; obvious duplicates collapsed after **Apply** batch TC flow. **Smart-link** single-TC step regen still produces steps (dedupe is **not** applied there). |
| **Step patterns** | **`action_event_flow`**: trigger, draft, blocked, permission, error, refresh patterns per intent. **Toggle**: rule-blocked save, persist reload, toggles. **Form**: navigate → enter → save → validation messages. |

---

## 2. Overview (historical + supporting detail)

This document also records **lessons learned** from real JSON and DOCX runs — parser quirks, trust UI, and C3 iteration — below the playbook.

**Scenario Management trust strip:** parse summary uses **import type** Structured (JSON) vs Fallback vs Sparse (DOCX with missing AC or TC); **images detected** prefers `ingestion_meta.images_detected`, else counts screenshot path references in the scenario dict.

**Import / completeness:** **Import Warnings** (`ingestion_meta.warnings`) are the **primary** parse/issue signal under **Parse Check** (numbered list). **Quick Stats** on Scenario Management combines **present** counts and **completeness/gap** counts in one panel (divider between groups).

**Title Screen:** **Quick Stats** there are **placeholders** only — not persistent analytics.

Use the sections below when:
- triaging **DOCX** templates
- debugging **import vs generation** separately
- onboarding to **past** manual findings

---

## 3. Test scenarios used

Scenarios exercised during development and manual testing (labels as used in the **Scenario Review** dropdown: **title** (and **`[Draft]`** for unsaved session scenarios); **`scenario_id`** shown under **Scenario details**):

| Label / fixture | Source | Notes |
|-----------------|--------|--------|
| **banking_login** | JSON | External / saved fixture (naming as tested) |
| **checkout_flow** | JSON | External / saved fixture |
| **patient_info_update** | JSON | External / saved fixture |
| **doc_banking** | DOCX | Word template; AC / TC / changed areas weakly extracted |
| **doc_ecommerce** | DOCX | Word template; AC / TC / changed areas / business goal gaps |
| **doc_healthcare** | DOCX | Word template; same class of gaps as ecommerce |

**Bundled starters:** **`BUNDLED`** in `src/scenario_registry.py` is currently **empty** (former `data/sample_*.json` starters are not listed in the app catalog). **`data/sample_login_flow.json`** and similar files may still exist for **tests** / CLI. External-style fixtures (banking, checkout, patient) and DOCX templates are **not** all committed; use **`test_assets/`** or local imports when repeating cases.

---

## 4. What worked well

- **Internal JSON (fixtures / disk)** — **`load_scenario`** + saved files align with **`docs/schema.md`**; stable **Scenario Review** packet (tabs, coverage, steps, evidence).
- **Structured ground truth** — Explicit **`acceptance_criteria`**, **`test_case_ids`**, **`test_cases`**, and path-based **`expected_step_screenshots`** behave predictably end-to-end in tests and when reviewing saved scenarios.
- **Screenshot mapping (JSON)** — String paths and structured `{ path, label?, mapped_to_step_index? }` per schema; **`src/scenario_media.py`** resolution matches **Test Results** expectations.
- **Screenshot mapping (DOCX)** — **Figure / Fig / bracketed** captions plus **“see Figure …”** (and similar) in steps when authors follow supported patterns (`docs/intake_notes.md`).
- **Test Results tab structure** — **Reviewer Focus** → **Coverage gaps** (per-AC expanders; pipe-separated descriptions may render as bullets) → **Test Results** (consistent with `cursor_handoff.md`).
- **Coverage gaps (baseline)** — Rule-based signals (missing links, weak steps, screenshot/step skew); optional AI merge when configured (`src/coverage_gaps.py`).

---

## 5. Key issues identified

### A. DOCX parsing

- **Acceptance criteria** — Not consistently detected; depends on heading styles, wording, and section breaks.
- **Test cases** — Same: weak when `TC-…` / **Test case** patterns and step numbering diverge from heuristics.
- **Changed areas** — Often empty when sections are titled differently or not styled as headings.
- **Business goal** — Sometimes missing when labels/layout differ.
- **Root cause** — Heavy reliance on **inconsistent real-world document structure**; unmatched headings land in **`notes`** (`docs/intake_notes.md` — *Known parsing limitations*).

### B. Screenshot mapping

- **Strong** when figure references and captions align with supported label patterns and step prose.
- **Fallback** (document-order fill into **`expected_step_screenshots`**) can **mis-assign** when structure is ambiguous; overflow correctly tends toward **`workflow_process_screenshots`** but reviewers must still verify.

### C. Coverage gaps output

- Earlier **grouped / long-form** presentation was **too verbose** for mapping gaps back to ACs.
- **Reverted to a dataframe table** in **Review synthesis** for clarity; keep future experiments table-first or AC-keyed.

### D. Scenario management

- **Scenario Management** view — **registry tables** (review state, open in builder, **Test Manager** delete); separates **catalog maintenance** from **Scenario Review**.

- **Delete** for saved scenarios retires bad imports and registry clutter.
- **Labeling** — Dropdown shows **human title** (no **`[JSON]`** / **`[DOCX]`** prefix); **`scenario_id`** visible in **Scenario details** for traceability across files and session keys.

### E. UI/UX

- **Scenario Review vs Scenario Management** must stay **separate**: selection/review vs registry / state; avoids mixing “current packet” with catalog maintenance. **Scenario Management**, **AI Scenario Builder**, and **File Upload** omit the scenario picker (**selection on Scenario Review**).
- **Quick stats** — **Scenario Review** sidebar = **selected** scenario counts. **File Upload** / **Scenario Management** may show parse- or registry-oriented stats depending on view.
- **Success messages + loaders** — Needed so users know parse/load/save finished and that work is in progress (elapsed time optional but helpful).

---

## 6. Lessons learned

- **JSON scenarios** are the **reference** for schema and UI behavior; use them to bisect “data bug” vs “parser bug.”
- **DOCX** introduces **real-world variability**; passing one template does not generalize.
- **Explicit structure** (clear headings, **`AC-*` / `TC-*`**, figure labels, step numbering) **directly improves** extraction and screenshot placement.
- **Parsing reliability** (especially DOCX) is the **main bottleneck** before investing in flashier analytics on top of imported data.

---

## 7. Image path and DOCX image checks (manual regression)

Use **`test_assets/json/*_sparse/`** (scenario JSON + sibling images) and optional **`test_assets/docx/`** DOCX files.

| Case | How to run | Expected |
|------|------------|----------|
| JSON + valid local image | Open scenario from catalog if registered, or `load_scenario()` on e.g. `test_assets/json/ecommerce_sparse/scenario_ecommerce.json` with `./fig1.jpeg` present | Paths normalize to project-relative strings; images resolve in UI where applicable. |
| JSON + missing image | Same folder, temporarily rename/remove referenced file or use a bogus `./missing.png` | Ingestion succeeds; `ingestion_meta.warnings` includes **Referenced image not found** (or path outside project); **Scenario Management** image check lists missing paths. |
| DOCX with embedded images | **Parse document** on a template that includes inline images | Success message includes embedded image count; `ingestion_meta.images_detected` > 0. |
| DOCX without images | Sparse / text-only `.docx` | Parse succeeds; `ingestion_meta.warnings` may include **No embedded images found**; no invented captions. |
| JSON upload + `./` path | **Parse / Load JSON** in the app with a file that only uses `./foo.png` | Scenario loads; warning that `./`/`../` are not resolved for uploads (use root-relative path or disk **load_scenario** next to assets). |

---

## 8. Recommendations for future testing

**Corpus**

- **Clean structured** docs (headings + labeled sections).
- **Semi-structured** (mixed tables and prose).
- **Messy** real-world exports (manual formatting, inconsistent naming).

**Data checks**

- JSON: explicit **`test_case_ids`** on **`acceptance_criteria`**; per-step **`expected_step_screenshots`** (strings and/or objects per **`docs/schema.md`**).
- DOCX: **figure-labeled** screenshots and step text that references the same labels.

**Validation targets**

- **Coverage gaps** table — rows make sense per AC, no false-noise spam.
- **Reviewer Focus** — bullets grounded in scenario text (OpenAI on vs placeholder off).
- **Traceability** — **Scope & Context** acceptance snapshot + matrix-driven gaps/export consistent with JSON / parsed **`test_case_ids`** (and inference when AI traceability is on).

---

## 9. Next focus areas (post–v1-ready + parallel work)

- **Regression hygiene** — Keep **§1** + **§1.5** runs green after changes (`pytest` + spot manual three-family).
- **DOCX robustness** — AC / TC / **changed_areas** / **business_goal** without breaking **`docs/schema.md`** or screenshot reconciliation.
- **C3 generation** — Confirm role visibility, Final Review, suggested fixes on large drafts; verify **`primary_type`**-aligned wording after detection changes.
- **Coverage gaps / Reviewer Focus** — AC-oriented clarity; optional AI merge; scenario-grounded bullets.
- **Scenario lifecycle** — Polish **import → preview → save → select → delete** (e.g. optional cleanup of `data/docx_imports/` on delete—product decision).

---

## 10. Edge cases (product + Streamlit)

- **Deleting test cases (AI Scenario Builder)** — Never assign to **`st.session_state`** keys backing **`st.file_uploader`**; compact TC rows using a backing snapshot + **new uploader widget keys** (epoch) so Streamlit does not raise **`StreamlitValueAssignmentNotAllowedError`**. Persisted screenshot paths must live on **non–file-uploader** keys (`sb_tc_*_persisted_path*`).
- **Unmapped test cases** — Builder **save** and strict review rules require every **TC** id to appear on **≥1** AC’s **`test_case_ids`**; unmapped TCs should surface as **blocking** warnings/errors before save/approve.
- **Approval gating** — **Approved** (and related checklists) depends on per-test “reviewed” state, registry role permissions (**Test Lead** / **Test Manager**), and scenario completeness (including AC↔TC coverage where enforced); missing steps or unresolved screenshot paths may block trust even when checkboxes are clickable.
- **Screenshot replacement** — Uploading new step screenshots (builder or review flows) may **replace** prior persisted paths for the same slot; expect **overwrite** behavior under `data/json_upload_media/` (and similar) when filenames collide—see save/export code paths.
- **Export freshness** — **DOCX export** from **Scenario Review** should reflect the **currently loaded** scenario dict (including edits made in-session); re-run export after changes if the UI does not auto-refresh the file.

---

## 11. C3 testing — AI-assisted generation

Use **two scenario shapes** when manually exercising generation + review:

| Shape | Intent |
|-------|--------|
| **Gold (structured)** | Clear business goal, changed areas, AC lines, TC ids — validates **mapping integrity** and that generation **does not corrupt** good drafts. |
| **Weak (unstructured / vague)** | Thin or messy goal/areas/AC paste — validates that **generation improves usability** without claiming false completeness. |

**Focus areas**

- **AC generation quality** — criteria are verifiable, not generic filler; ids and bulk paste still behave after apply.
- **TC generation and mapping** — each generated TC lands on the intended AC; **unmapped** warnings still make sense after merges.
- **Negative TC usefulness** — optional flow; titles stay short and failure-focused; dedupe skips when a mapped TC already matches.
- **Step generation quality** — steps align to titles/ACs; merge vs replace; polish paths if enabled.
- **Smart linking** — review **structural feedback** / **suggested fixes** / gaps line up with **builder** actions where wired (issue → remediation).

**Success criteria (C3)**

- **Weak input improves** after a generation pass (or clearly signals what is still missing).
- **No silent data loss** — leaving steps, canceling dialogs, and navigation preserve or intentionally flush only media keys as designed.
- **Review output remains accurate** — gaps and suggested fixes track the loaded dict; no empty “suggested fixes” shell without a message.
- **Generated content remains editable** — after apply, all fields behave like manually authored rows.

---

## Iteration: JSON import missing image validation

### 1. Changes implemented

- **JSON import** now scans **`workflow_process_screenshots`** and **`test_cases[].expected_step_screenshots`** (string or `{ path }` entries) as soon as a file is **Parse / Load JSON**’d, using the same **`resolve_media_path`** rules as **Test Results**.
- **Missing** references are listed in a **warning** on **Scenario Management**; **all found** yields a **success** message; **no paths** yields a short **info** note.
- Load **never** blocked—broken references are visible at intake, not only in **Test Results**.
- **Optional in-app evidence upload** on Scenario Management was **removed**; fix paths in JSON, use **disk** `load_scenario` with sibling files, or root-relative paths (see **`docs/intake_notes.md`**). **`json_import_media`** helpers may remain in code for non-UI use.

### 2. Issues before changes

- Missing screenshots were often noticed **only in Test Results**.
- JSON import could succeed **silently** with dead paths.
- Lower **trust** in the intake step for evidence-heavy scenarios.

### 3. Improvements observed

- **Earlier** detection of missing evidence paths.
- **Clearer** feedback during import (counts + path list).
- More **predictable** JSON intake when assets are incomplete or machine-local paths differ.

### 4. Remaining limitations

- Checks are **path + file existence** only (no pixel/content validation).
- **Basename matching** for uploads still requires authors to name files consistently with JSON basenames.
- **Empty** slots or wrong **relative** paths outside the project root still need manual JSON fixes.
- **Parallel `expected_step_screenshot_labels`** without paths in objects are not separately validated.

### 5. Lessons learned

- Validation should cover **data and assets** together for UAT packets.
- **Early** warnings on import improve confidence in the workflow.
- JSON scenarios need lightweight **evidence integrity** checks before review.

---

## Iteration: Scenario Management + JSON Validation

### 1. Changes implemented

- Dedicated **Scenario Management** view with **scenarios table**, import under it, and **quick delete** for saved scenarios.
- **JSON** and **DOCX** import as parallel tabbed flows; JSON uses **file upload** only; **Quick stats (last import)** scoped to that context with `—` before import.
- JSON **image path validation** at load (no Scenario Management **Attach images** UI; path fixes via JSON or disk load).
- **Success messages** and **loaders** (upload/parse) with optional **elapsed time** display.

### 2. Issues before changes

- Missing screenshots discovered too late (mostly in Test Results).
- Fragmented scenario lifecycle (import vs catalog vs delete).
- Unclear separation between **import** tooling and **review** (Overview).

### 3. Improvements observed

- Earlier error detection for missing assets at intake.
- Clearer end-to-end workflow (import → preview → save → select → delete).
- Better separation: **Scenario Management** vs **Overview** / **AI Builder**.

### 4. Remaining limitations

- **DOCX** parsing still unreliable for AC / TC / steps / changed areas / business goal.
- Screenshot path matching is not fully automated (basename heuristics, structure-dependent DOCX figures).
- Strongest results still need **structured JSON** or well-formed Word layout.

### 5. Lessons learned

- Validate **assets** at intake, not only schema structure.
- **JSON** is the control baseline; **DOCX** is the variability challenge.

---

## Iteration: DOCX Parsing Validation + Import State Checks

### 1. General notes (confirmed)

- Bundled **`[JSON]` Login Flow** / **Profile Phone Update** are **removed** from the catalog; regression around scenario switching should use **saved** or **in-session** scenarios instead.

### 2. Import from JSON (gap vs expected)

- After **Parse / Load JSON**, the UI **switches to Import from DOCX** — **unexpected**; should **stay on Import from JSON**.
- After **Save scenario**, the UI **again switches to Import from DOCX** — **unexpected**; should **stay on Import from JSON**.

### 3. Missing files / images

- **Confirmed:** missing **.png** path tracking behaves correctly.
- **Next:** exercise a test case that actually **renders** the missing path in **Test Results** (not only intake warning).
- **Attach images to scenario** UI was **removed**; no manual test of that flow in-app.

**Open (product / UX):**

- Can screenshots ship with the **initial** JSON upload in one step?
- Would that imply creating **`data/json_upload_media/<slug>/`** (or equivalent) **before** attach, or is multi-file upload enough?

### 4. DOCX: doc_healthcare (observed)

- **Still empty / weak:** Changed Areas, Known Dependencies, Workflow Context, Traceability, Test Cases, Steps (by TC), **Test Results** evidence alignment — and **Quick stats** does not reflect AC / TC / Changed Areas counts for this file.
- **Reviewer Focus** does populate (**Pay Attention To**, **Risks**, **Possible Gaps**).
- **Preference:** keep Reviewer Focus to **1–2 high-signal points** per section when possible (aligns with summarizer caps; still validate on real runs).

### 5. Open questions

- Does **doc_healthcare** actually contain those sections in **body** text (vs text boxes, scans, or non-standard layout)?
- What is the parser **currently** matching for those sections? (See **`docs/intake_notes.md`**, **`src/docx_parser.py`**, and DEBUG / `scripts/inspect_docx_structure.py`.)
- Can we **inspect** the `.docx` (styles, block order, tables) to map author headings to parser hooks?

### 6. Future idea — do **not** implement yet

**Archive-style tab (concept only):**

- List all **Test Results** with status categories: **Approved** / **Refused** / **Work in Progress**.
- **Sidebar** scenario status: green = Approved, red = Refused, yellow = WIP.

**Approved:** In Review; Walkthrough in Progress; Completed.

**Refused:** Rework Needed; Requirements Issue; Other.

**WIP:** Requirements Gathering in Progress; Investigation in Progress; Test Execution in Progress.

---

*Last aligned: 2026-04-05 — **§1.5 Final three-family validation**; playbook phase **stabilization → v1 readiness**; **§9** post–v1-ready wording. Older: §1 playbook-only; 2026-04-08 C3 testing notes; 2026-04-07 roles / DOCX-first; 2026-04-06 trust / Title Screen.*

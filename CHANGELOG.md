# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Dates group when items were recorded in this log (not necessarily distinct releases).

### Stabilization / v1-ready generation (2026-04)

Factual checkpoint of **implemented** behavior (not a versioned release).

- **Unified intake for C3** — **`scenario_context`** is the canonical narrative field on the scenario dict; legacy **`story_description`** merges into it when context is empty (`merge_legacy_story_into_scenario_context` in **`src/scenario_builder_core.py`**).
- **Scenario type detection** — **`src/scenario_type_detection.py`**: **`primary_type`**, secondaries, signals, routing hints drive downstream modules.
- **Strict type gating** — **`src/scenario_type_gating.py`**: cross-family leakage prevention across AC suggestions, coverage slots, negatives, and step phrasing.
- **`action_event_flow` support** — Detection, expansion, coverage templates, intent, AC/TC/steps, suite clustering, and tests (**`tests/test_action_event_flow.py`**).
- **Action/event step templates** — **`src/scenario_builder_steps_gen.py`**: trigger / draft / persist / blocked / permission / failure paths gated vs generic form save.
- **Final cleanup pass** — **`src/scenario_suite_optimizer.py`**: plan-aligned positive enrichment, **`semantic_dedupe_positive_proposals_final`** (batch only); **`src/scenario_builder_steps_gen.py`**: negative **input** lines aligned to failure class, output sanitization for toggle/action_event isolation; **`src/scenario_domain_labels.py`**: primary action / entity consistency; **`src/scenario_test_case_intent.py`**: aligned negative titles.

### Documentation — stabilization / generation architecture (2026-04)

Checkpoint documenting **already-shipped** behavior for handoffs (not a release tag).

#### Added (documented; implementation precedes this log entry)

- **`action_event_flow`** primary workflow type and routing (**`src/scenario_type_detection.py`**, **`src/scenario_context_expansion.py`**, **`src/scenario_positive_coverage_plan.py`**, **`src/scenario_test_case_intent.py`**, **`src/scenario_builder_ac_gen.py`**, **`src/scenario_builder_steps_gen.py`**, **`src/scenario_suite_optimizer.py`**, **`src/placeholder_outputs.py`**) with tests under **`tests/test_action_event_flow.py`**.
- **Strict scenario type gating** — **`src/scenario_type_gating.py`** reduces form/toggle/action cross-leakage in generated ACs, steps, coverage, and negatives.

#### Changed

- **Builder narrative for generation** — **`scenario_context`** is the primary field; legacy **`story_description`** (and related story fields) merge into **`scenario_context`** when context is empty (**`merge_legacy_story_into_scenario_context`** in **`src/scenario_builder_core.py`**).

#### Documentation

- **`docs/cursor_handoff.md`**, **`docs/development_guidance.md`**, **`docs/testing_notes.md`** — pipeline (**titles → steps → batch dedupe**), workflow families, **`scenario_context`** as canonical narrative, **§1.5** three-family validation strip, safe extension points.
- **`docs/schema.md`** — **`scenario_context`** + legacy **`story_description`** merge (v1: story_description marked legacy in table).
- **`docs/intake_notes.md`**, **`docs/retrospective.md`** — short pointers; intake **`scenario_context`** wording aligned.

### 2026-04-08 — C2/C3 (AI-assisted scenario authoring)

High-level checkpoint: guided builder and Scenario Review now support **generation and refinement**, not only validation.

#### Added

- **Guided AI Scenario Builder — generation** — acceptance criteria from **business goal + changed areas**; positive **test cases** from acceptance criteria; **optional negative** test cases; **test steps** from titles (review/confirm before apply).
- **Scenario Review — C2 readouts** — **structural feedback**, **suggested fixes** (coverage gaps + reviewer-focus hints), and **smart linking** between review issues and builder-style remediation where implemented.
- **Guided Final Review** — collapsible **acceptance criteria** and **test cases** (with counts); coverage gaps, risk flags, and suggested fixes surfaced so the step is not silently empty.

#### Changed

- **Workflow-level screenshots** — optional workflow evidence moved to **Step 2 (Changed areas)** in the guided flow; test-steps step focuses on per-step evidence.
- **Negative test case titles** — shorter, failure-focused patterns (avoid long AC/business-goal pastes); positive/step title quality refinements where applicable.

#### Documentation

- Doc checkpoint: **`docs/cursor_handoff.md`** (C3 phase), **`docs/development_guidance.md`** (AI generation guidelines), **`docs/testing_notes.md`** (§10 C3 testing), **`docs/retrospective.md`** (Phase 10), **`docs/intake_notes.md`** (Context intake Step 0 stub).

### 2026-04-07

#### Added

- **Simulated roles** (`src/app_roles.py`, `app.py` sidebar): **Tester**, **Test Lead**, **Test Manager** — controls which app views appear; **Scenario Review** is hidden from **Tester**; **Scenario Management** registry **delete** is limited to **Test Manager**; review / testing status edits gated per role.

#### Changed

- **DOCX-first intake (user-facing)** — **`File Upload`** (`src/ui_file_upload_debug.py`) accepts **`.docx` only** for new imports; normalized scenarios still persist as **JSON files** under `data/saved_scenarios/` **for internal storage and tooling** (not positioned as the primary author input in the product UI).
- **Internal JSON contract** — same normalized scenario dict end-to-end (parse, registry, builder save, review); users are not asked to hand-edit raw JSON in the main workflow.
- **Scenario catalog labels** — dropdown uses **human-readable titles** only (`format_scenario_dropdown_label` in `src/scenario_registry.py`); removed **`[JSON]`** / **`[DOCX]`** source prefix; unsaved session scenarios labeled **`[Draft]`**.
- **Figure-style screenshot labels** — DOCX reconciliation and schema-aligned `{ path, label?, … }` entries continue to prefer **Figure / Fig / bracketed** caption patterns (see `docs/intake_notes.md`).
- **AI Scenario Builder** — **bulk paste** for **Acceptance Criteria** (multiline → rows; optional `AC-xx` preservation / auto-ids); multiline **test steps**; **test case delete** refactored for Streamlit (**file_uploader** keys include upload **epoch**; no programmatic writes to uploader-backed `st.session_state` keys).
- **Scenario Review** (sidebar app view internally **`Overview`**) — **Scope & context** / **Test Cases** / **Test Results** layout and scope ordering updates (`src/ui_overview.py`, `src/ui_review_synthesis.py`).

#### Documentation

- Refreshed **`docs/cursor_handoff.md`**, **`docs/development_guidance.md`**, **`docs/schema.md`**, **`docs/testing_notes.md`**, **`docs/retrospective.md`**, **`docs/intake_notes.md`** for DOCX-first roles, internal JSON, builder vs review split, and Streamlit session-state cautions.

### 2026-04-06

#### Added

- **Title Screen** (`src/ui_title_screen.py`, `app.py`): new **App view** option and **default landing** experience; heading **AI UAT Copilot** plus **Quick Stats** placeholder block (past-month metrics labeled as non-persistent / illustrative only).
- **Scope & Context — Acceptance Criteria** (`src/ui_overview.py`, `app.py`): explicit AC↔TC snapshot table (from traceability matrix) restored alongside changed areas and dependencies.

#### Changed

- **Scenario catalog** (`src/scenario_registry.py`): **`BUNDLED`** emptied — former hardcoded **`[JSON]` Login Flow** and **`[JSON]` Profile Phone Update`** no longer appear as default starters; catalog is **saved registry** rows (+ in-session pasted JSON when loaded).
- **Scenario Management — JSON import** (`app.py`): removed **Optional Evidence Images** / **Attach images to scenario** UI; **Image Path Check** and **Parse / Load JSON** / **Save scenario** unchanged. Users should correct paths or place files per path check guidance.
- **Scenario Management — trust / completeness** (`src/ui_trust.py`, `src/ui_import.py`): **Import Warnings** list items are **numbered** for scanability; **Missing Sections** panel under **Parse Check** removed (overlap with warnings); **Review Completeness** metrics merged into **Quick Stats** with a **divider** between present counts (AC / TC / changed areas) and gap counts; narrative **`missing_info_narrative`** shown once under that panel (removed duplicate block from **Import Output (Debug)**).
- **Overview — Test Cases** (`src/ui_overview.py`): traceability **dataframe** removed; expanders use **`TC id : description`** titles; lighter body (steps + warnings only where needed).
- **Overview — Test Results — Coverage gaps** (`src/ui_review_synthesis.py`): per-gap layout **AC** / **Type** / **Description** with dividers; descriptions containing **` | `** split into **bullet** lines for readability.
- **Overview — sidebar**: removed **How to use this validation packet** expander.
- **Test Results** (`src/ui_review_synthesis.py`, earlier in phase): header actions **Archive** / **Approved**; per-test **Flagged for Review**, notes, optional image upload; **Coverage Gaps** in **expanders** per AC; **Export** DOCX (`src/scenario_export_docx.py`).
- **Scenario Management** (`app.py`): import source tab persistence via **`_mgmt_import_tab_pending`** (avoids mutating widget-bound session state after **st.radio**).

#### Fixed

- **JSON / DOCX parse reruns** no longer error on **`st.session_state._mgmt_import_tab`** after **Parse document** / **Parse / Load JSON** (pending tab applied before **st.radio** on the next run).

### 2026-04-05

#### Added

- **Review synthesis — scenario map** (`src/ui_review_synthesis.py`): **Overview → Review synthesis** adds metrics (AC/TC/step counts, workflow vs step-level evidence paths), an **explicit AC → test case IDs** table from `test_case_ids`, a collapsible **workflow-level screenshots** block (same assets as **Scope & context**), and per–test-case captions linking back to explicit ACs plus clearer **Steps and expected evidence** (including a warning when screenshots exist without steps). Handoff / checkboxes unchanged.
- **Regression tests** (`tests/test_regression_import.py`, `tests/fixtures/json_local_image/`, `pytest.ini`, `requirements-dev.txt`): pytest coverage for JSON baseline, local/missing image paths, DOCX banking (AC/goal/images), healthcare sparse `Test:` + trust warning, and generated text-only DOCX (`images_detected == 0`).

#### Documentation

- **Doc set alignment** — Roles clarified across **`docs/cursor_handoff.md`**, **`docs/development_guidance.md`** (adds a **documentation map** table), **`docs/intake_notes.md`**, **`docs/schema.md`**, **`docs/testing_notes.md`**, and **`docs/retrospective.md`** (cross-links; handoff notes schema summary vs **schema.md** as authoritative).
- **Image / intake docs** — **`docs/schema.md`** (`ingestion_meta`), **`docs/intake_notes.md`** (disk vs upload path rules), **`docs/testing_notes.md`** (manual regression table), **`docs/cursor_handoff.md`**, **`docs/development_guidance.md`**, **`docs/retrospective.md`**: JSON paths next to file, DOCX image counts, no fabricated semantics.
- **`test_assets/README.md`** + **`scripts/inspect_docx_structure.py`** — optional local **`test_assets/docx/`** fixtures; bare `*.docx` filename resolves under that folder; improved CLI output. **Does not** change Streamlit upload behavior.

### 2026-04-04

#### Added

- **Parse trust UI** (`app.py`): **Scenario Management** shows a **Parse trust & completeness** block after the debug panel (source type, **import type** Structured/Fallback/Sparse, AC/TC counts, **images detected** count, warning count, **Import Warnings** panel when `ingestion_meta.warnings` is non-empty, **Missing sections** captions). **Overview** adds a collapsible **Parse trust & completeness** in the sidebar and a one-line **review trust strip** at the top of **Scope & context**. Session key `_import_preview_source` records last JSON vs DOCX import for the preview row. *(**Missing sections** captions under Parse Check later removed — see **2026-04-06**.)*
- **Import output (debug)** (`app.py`): under **Scenario Management → Import**, after a successful import—**View normalized output** (`st.json`), **Copy parsed JSON** (clipboard), **Download parsed JSON**—uses the in-session preview dict unchanged (includes `ingestion_meta` when present).
- **JSON image path resolution** (`src/intake_parser.py`, `src/scenario_media.py`): disk load resolves screenshot paths against the **JSON file’s directory** when not already valid from the project root (e.g. `./fig1.jpeg` next to the file). Missing files add **`ingestion_meta.warnings`** only; ingestion does not fail.
- **DOCX embedded-image signaling** (`src/docx_parser.py`): optional **`ingestion_meta`** with **`images_detected`** and **`warnings`** (e.g. no embedded images). No captions or pixel inference.
- **Persisted JSON** (`src/scenario_registry.py`): **`ingestion_meta`** stripped on save (`data/saved_scenarios/*.json` stays clean).
- **Scenario management** (`app.py`, `src/scenario_registry.py`): Overview sidebar lists **saved** scenarios from `data/scenario_registry.json` with **Confirm** + **Delete**; `delete_saved_scenario()` removes the registry row and deletes the JSON file under `data/saved_scenarios/` when the path resolves under that directory (bundled scenarios are not deletable).
- **Import view** (`app.py`): dedicated **App view → Import** with **Import from DOCX** / **Import from JSON**; JSON via **file upload** (not sidebar textarea); **Quick stats (import)** for the last successful import only (placeholder `—` before any load); **spinner** + **`st.success`** after DOCX parse, JSON load, and JSON save, with **elapsed seconds** in the message.
- **Test Results actions** (`app.py`): **Flag for Review** and **Send for Internal Review** in the top-right of the bordered Test Results panel (with **Open Reviewer Checklist** below).
- **Structured step screenshots** (`src/scenario_media.py`, `docs/schema.md`): `expected_step_screenshots` may mix **path strings** and **objects** `{ path, label?, mapped_to_step_index? }` (0-based index); unmapped objects fill first empty step slots after mapped entries; parallel `expected_step_screenshot_labels` still supported for legacy string-only arrays.
- **DOCX screenshot mapping** (`src/docx_parser.py`): **Figure / Fig / bracketed** caption labels registered from image paragraphs; step text (**see Figure …**, etc.) maps evidence to steps when patterns match; **reconciliation** with order-based fallback; one image per step slot where possible; overflow and unplaced images to `workflow_process_screenshots`.
- **DOCX UAT import** (`src/docx_parser.py`, `app.py`, `src/scenario_registry.py`): **Import** view file uploader + **Parse document**; extracts structured text and inline images into `data/docx_imports/<slug>/media/`; persists scenario JSON + registry entry; same normalized scenario dict as JSON; `python-docx` dependency; `.gitignore` for `data/docx_imports/`.
- **Scenario catalog** (`src/scenario_registry.py`): bundled scenarios in code + saved rows in `scenario_registry.json`; Overview dropdown labels **`[JSON]`** / **`[DOCX]`** + title via `format_scenario_dropdown_label`.

#### Removed

- Sidebar **Paste or Edit JSON Scenario** / **Apply JSON**; JSON ingestion is **Import → file upload** (session still uses internal `json_pasted_*` keys for in-memory loaded JSON until saved).

#### Documentation

- **`docs/cursor_handoff.md`**, **`docs/schema.md`**, **`docs/intake_notes.md`**: scenario lifecycle (import → preview → save → select → delete), Import vs Overview quick stats, DOCX parsing limits (AC / TC / changed areas / business goal reliability), per-step screenshot object shape vs workflow-level `{ path, label }`, registry paths, and handoff checklist updates.

#### Fixed

- **Saved scenario delete** (`src/scenario_registry.py`): only deletes files that resolve under `data/saved_scenarios/` (`Path.relative_to`); registry row is still removed if the path is outside that tree (avoids unlinking arbitrary paths).

### 2026-04-03

#### Changed

- **DOCX output cleanup** (`src/docx_parser.py`): `expected_step_screenshots` serialized as `{path, mapped_to_step_index, label?}` entries only (no parallel empty strings); strip contextual “see Figure N” prose from steps only when that figure ref explicitly mapped the image for that step; drop standalone figure caption lines from import notes when those figures already appear in placed evidence paths.
- **DOCX sparse / fallback extraction** (`src/docx_parser.py`): `business_goal` continuations no longer absorb `AC-#` / REQ-style bullets (promoted to acceptance); `Test: …` opens a test case; `Steps:` labels and obvious imperative lines attach as steps in the tests section; optional harvest of the same patterns from `notes_parts`; single-TC docs link remaining AC rows to that TC; `ingestion_meta.warnings` include honest sparse-structure hints.
- **JSON file upload** (`app.py`): **`workflow_process_screenshots`** keeps **strings or `{ path, … }` objects** (not stringified). **`warn_json_upload_sibling_relative_paths`** for `./`/`../` when upload has no folder context.
- **Review synthesis** (`app.py`): order **Reviewer Focus** → **Coverage gaps** (dataframe **table**, AC-oriented) → **Test Results**; **Traceability** table **removed** from below Test Results (full matrix remains under **What to validate**).
- **DOCX section parsing** (`src/docx_parser.py`): broader heading/keyword matching (outline prefix strip, synonyms for AC / tests / business goal / changed areas / dependencies); state for **changed_areas** and **known_dependencies**; acceptance continuation can switch section on new headers; fallback when `section is None` for **`AC-1`-style** lines; extra **test case** header patterns (`UAT-n`, `TC:`, etc.).
- **Overview sidebar** (`app.py`): empty **Workflow** shows **—** (aligned with other missing-value dashes).
- **UI / UX (`app.py`, `README.md`)**: **Quick stats** in Overview sidebar for the **selected** scenario; unified sidebar typography (CSS); **`st.set_page_config` at top**; **Reviewer checklist** as **`st.dialog`** from **Open Reviewer Checklist** in **Test Results**; **## Test Results** in bordered block; traceability column order, wrapping CSS, coverage gap columns, approval checkbox wording, handoff flow as before.
- **Traceability** (`src/traceability.py`): stricter prompt + system message (JSON only); `response_format: json_object` with fallback if unsupported; `_parse_traceability_payload` for wrapped objects, fences, BOM, and array fallback; `_merge_traceability_with_source` guarantees one row per AC with all required fields, valid test ids, case-insensitive AC id match, coverage status normalization (Covered / Partial / Missing), and scenario JSON backfill when the model omits or invalidates matches.
- **Traceability overview (UI)** (`app.py`): table sorted **Missing → Partial → Covered** ( **Pending** with Partial); caption with per-status counts; row tint + left border for attention rows via Pandas `Styler`, with unstyled fallback if styling fails.
- **Reviewer Focus** (`src/summarizer.py`, `src/placeholder_outputs.py`): OpenAI when `OPENAI_API_KEY` is set (`json_object` + markdown/BOM-tolerant parse); rich scenario context (goal, workflow, story, changed areas, dependencies, notes, AC links, steps via `step_texts`); prompt emphasizes concrete, scenario-grounded bullets and bans generic QA filler; `_tighten_focus_lists` limits items and line length for scannability; lower temperature; fallback `get_placeholder_reviewer_focus` copy tightened for execution-focused checks (unchanged return shape for `app.py`).
- **README** / **app** copy: documents OpenAI for Reviewer Focus + traceability; sidebar and Review synthesis captions updated (checklist remains rule-based).
- **Coverage Gaps** (`src/coverage_gaps.py`, `app.py`): rule-based detection with optional OpenAI merge; gaps shown in **Review synthesis** as a **table** tied to AC mapping. Heuristics: **Missing** vs **Partial** (unresolvable ids → missing; broken id(s) plus some valid links → partial); suite-level **Missing** when criteria need invalid/reject/error coverage but no test shows it (per-AC happy-path note suppressed then); tighter negative phrasing; vague verify/confirm only without concrete outcomes; **Weak** aggregated per AC (screenshots, shallow steps, vague assertions); shorter copy; AI prompt asks for non-obvious gaps only.
- Reviewer-oriented UI: tab labels **Scope & context** / **What to validate** / **Steps & procedures** / **Review synthesis**; collapsible **How to read this validation packet** (maps the five reviewer questions to UI); per-tab captions; Requirements copy points to traceability instead of “Week 2.”

## [0.2.1] - 2026-04-05

### Changed

- **Review Packet (`app.py`)** — Removed **Workflow summary**; tab order is now **Reviewer Focus** → **Traceability overview** → **Expected results (screenshots)**.
- **`generate_workflow_summary` (`src/summarizer.py`)** — Returned only `reviewer_focus` from placeholders; no workflow `summary` string. *(Superseded by `generate_reviewer_focus` in Unreleased.)*
- **`src/models.py`** — Comment block for summarizer output no longer included a `summary` field.

## [0.2.0] - 2026-04-05

### Added

- `src/scenario_media.py` — resolve image paths under the project root; `workflow_process_screenshots`, `step_texts`, `expected_step_screenshot_paths`.
- `scripts/generate_placeholder_screenshots.py` — generates demo PNGs for workflow context and per-step expected screenshots.
- Scenario JSON support: `workflow_process_screenshots` (scenario-level); per test case `expected_step_screenshots` (1:1 with `steps`); `test_case_ids` on acceptance criteria.
- **Review Packet — Reviewer Focus** — three lists from `get_placeholder_reviewer_focus` in `src/placeholder_outputs.py`: what to pay attention to, what looks risky, what may be missing (scenario-aware placeholders).
- **Traceability** — OpenAI-backed `generate_traceability_matrix` in `src/traceability.py` with safe JSON parsing and placeholder fallback when the API key is missing or the response is invalid.

### Changed

- **App layout (`app.py`)** — Sidebar: app title, caption, scenario selector, scenario details, **business goal** (replaces former “current story” block). Main: fixed/pinned toolbar (CSS) for **Quick Stats**, **Reviewer Checklist**, and **Generate UAT Packet**; toolbar typography reduced by 2pt; checklist in one column with the generate button centered between “Test cases” and “Changed areas” columns.
- **Overview tab** — Tables for changed areas and known dependencies; **Current workflow process screenshots** from `workflow_process_screenshots` (not tied to test cases). Removed the former overview field table (story title, description, etc.).
- **Requirements tab** — Acceptance criteria show mapped test case IDs/titles only (no steps in this tab).
- **Test Evidence tab** — Test case summary table, steps by test case; caption updates; removed the raw “expected step screenshot paths” listing section.
- **Review Packet tab** — Order: Workflow summary → **Reviewer Focus** → Traceability overview → **Expected results (screenshots)** (per step via `expected_step_screenshots`). Removed **Before / after** table.
- **`generate_workflow_summary` (`src/summarizer.py`)** — Returns `summary` and structured `reviewer_focus` from placeholders; removed unused `before` / `after` from the returned dict (placeholders remain in `placeholder_outputs.py` for future use).
- **`src/models.py`** — Comment block updated for the new summary output shape.

### Removed

- Per-test-case upload widgets for screenshots; evidence is path-driven from JSON and files under `data/screenshots/`.
- Review Packet **Before / after** UI section (and corresponding use of summarizer `before`/`after` in the app).

## [0.1.0] - 2026-04-05

### Added

- `requirements.txt` with `streamlit` and `pandas` lower bounds for reproducible installs.
- `Dockerfile` and `.dockerignore` for container runs on `0.0.0.0:8501` with `app.py`, `src/`, and `data/`.
- `CHANGELOG.md` (this file).

### Changed

- Placeholder traceability rows include `matching_test_cases: []` so output matches the shape described in `src/models.py` for Week 2.

### Fixed

- `generate_traceability_matrix` no longer crashes on empty or non-JSON model responses: optional Markdown JSON fences, bracket extraction for arrays, and `get_placeholder_traceability` fallback when the API key is missing or the call/parse fails.

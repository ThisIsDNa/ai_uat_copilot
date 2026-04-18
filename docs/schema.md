# Scenario schema

This document describes the **scenario object** the app treats as canonical **internal** input. It is the shape returned by `load_scenario()` for on-disk JSON files and by `parse_scenario_from_docx()` for Word imports. Downstream features (Scenario Review tabs, traceability, coverage gaps, reviewer focus, test results) read this structure.

**User-facing vs internal:** End users work in **DOCX** (import / export) and the **AI Scenario Builder**; they are **not** expected to hand-edit this JSON. **`docs/schema.md`** is still the **authoritative contract** for persisted `data/saved_scenarios/*.json`, parser output, builder save, and automated tests.

**DOCX** should normalize into this shape as closely as possible; see **`docs/development_guidance.md`** for parsing priority and trust expectations. **Live product summary:** **`docs/cursor_handoff.md`**. **Ingestion and parser debugging:** **`docs/intake_notes.md`**. **Manual test history:** **`docs/testing_notes.md`**.

Paths to images are **strings, relative to the project root** after `load_scenario()` (POSIX-style with `/` is fine on all platforms). **Authoring on disk:** paths like `./screenshot.png` next to the JSON file are rewritten to project-relative form during load (`normalize_scenario_image_paths`). Resolution and safety checks live in `src/scenario_media.py` (`resolve_media_path`).

**Missing or unresolved paths** are valid in the data model: the app may load scenarios whose `path` strings do not yet exist on disk. Intake / tooling may warn when referenced files are missing; **Test Results** still surfaces per-step missing files. Fixing paths is manual (re-save from builder, fix assets, or edit **internal** JSON when appropriate). The schema does not require every path to resolve at authoring time.

---

## Root object

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| `scenario_id` | string | **required for product flows** | Stable identifier: registry row id / slug, media folders, and **Scenario Review** session keys (e.g. per–test-case checkboxes). Parsers and the builder should always emit a non-empty id. |
| `story_title` | string | optional | Short title shown in the sidebar and summaries. |
| `story_description` | string | optional | **Legacy** longer narrative; prefer authoring **`scenario_context`** for new work. On load/save, merged into **`scenario_context`** when context is empty (see **`scenario_context`** row below). May remain populated on older files for display compatibility. |
| `business_goal` | string | optional | Outcome-focused context for reviewers. |
| `scenario_context` | string | optional | **Primary free-text narrative** for the AI Scenario Builder’s **context expansion** and C3 generation (actors, constraints, success signals). Does not change review/traceability rules. Omitted when empty on save. On load/save paths, legacy **`story_description`** (and related story fields) may be **merged into** `scenario_context` when context is empty — see **`merge_legacy_story_into_scenario_context`** in **`src/scenario_builder_core.py`** — so older files and imports still feed generation without a separate builder “story” field. |
| `workflow_name` | string | optional | Label for the workflow under review. |
| `workflow_process_screenshots` | (string \| object)[] | optional | Workflow-level evidence. Each item may be a **path string** or `{ "path": "…", "label": "…" }` (`label` optional). There is **no** `mapped_to_step_index` at scenario level—mapping is per test case only. **DOCX:** also receives overflow / unassigned step images. |
| `acceptance_criteria` | object[] | **required for review/save gates** | Non-empty list for a complete UAT packet; see **`acceptance_criteria[]`** below. |
| `test_cases` | object[] | **required for review/save gates** | Each scenario meant for review should include at least one test case object; see **`test_cases[]`** below. |
| `changed_areas` | object[] | optional | Structured change list; see below. |
| `known_dependencies` | string[] | optional | Systems, teams, or components involved. |
| `notes` | string | optional | Free-form reviewer notes or import provenance. |
| `ingestion_meta` | object | optional | **Ephemeral** intake diagnostics only. May appear on dicts returned from `load_scenario()` (disk JSON) or `parse_scenario_from_docx()`. **Omitted** from files written under `data/saved_scenarios/` (`strip_ingestion_meta_for_persist`). Do not treat as part of the long-lived schema. |

### `ingestion_meta` (when present)

| Field | Type | Description |
|--------|------|-------------|
| `warnings` | string[] | Non-fatal issues (e.g. referenced image missing, `./` path on **browser JSON upload**, JSON directory outside project, DOCX with no embedded images). |
| `images_referenced` | number | **JSON (disk load):** non-empty screenshot paths considered for resolution. |
| `images_resolved_ok` | number | **JSON (disk load):** those paths that resolve to an existing file under the project root after normalization. |
| `images_detected` | number | **DOCX:** count of embedded images seen in the document body during parse (metadata only; no captions or semantic inference). |

Unknown top-level keys are ignored unless new code reads them.

---

## AC ↔ TC mapping (integrity)

- Each **`acceptance_criteria[]`** row carries **`test_case_ids`** — explicit **AC → TC** links used for traceability, coverage gaps, and builder/review validation.
- Every **`test_cases[].id`** that should be in scope for approval must appear in **at least one** AC’s **`test_case_ids`** (no **unmapped** TCs when saving from the builder or approving under current rules).
- Symmetrically, each AC is expected to list **≥1** test id for a “complete” packet in strict review/builder paths.

---

## `acceptance_criteria[]`

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| `id` | string | recommended | e.g. `AC-1`, `AC-01`. Used in traceability and UI. |
| `text` | string | recommended | Criterion wording. |
| `test_case_ids` | string[] | **required for strict validation** | IDs of `test_cases` that cover this criterion. May be empty only where the product explicitly allows draft states; builder save and approval flows expect non-empty, valid ids. |

One acceptance criterion may map to **multiple** test case IDs (see `sample_login_flow.json`: AC-2 and AC-3 both reference `TC-02`).

---

## `test_cases[]`

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| `id` | string | recommended | e.g. `TC-01`. Must be unique within the scenario for reliable linking. |
| `text` | string | recommended | Test case title / summary. |
| `steps` | (string \| object)[] | optional | Ordered steps. Each item is either a **string** or an object with a `text` property (`step_texts()` in `scenario_media.py` normalizes both). |
| `expected_step_screenshots` | (string \| object)[] | optional | Per-step evidence. **Backward compatible:** each item may be a **path string** (slot *i* = step *i*). **Structured object** (JSON authors and normalized DOCX output): `{ "path": "…", "label": "…", "mapped_to_step_index": <optional int> }` — `path` required; `label` optional (caption / figure id); `mapped_to_step_index` optional **0-based** step index (places that image on that step). Entries **without** `mapped_to_step_index` fill **first empty** step slots in array order after mapped slots are applied. Normalization: `src/scenario_media.py` (`resolved_step_screenshots`). |
| `expected_step_screenshot_labels` | string[] | optional | Legacy parallel labels when `expected_step_screenshots` is all strings; merged when a slot has a path but no object `label`. **DOCX** may set this after import; object `label` takes precedence when both exist. |

**Per-step screenshot object shape** (canonical; same semantics for **hand-authored JSON** and **DOCX-parsed** scenarios after reconciliation):

```json
{
  "path": "data/screenshots/flow/step3.png",
  "label": "Figure 1.1",
  "mapped_to_step_index": 2
}
```

- **`path`** (string, required in object form) — relative to project root.
- **`label`** (string, optional) — caption or figure reference text for the UI.
- **`mapped_to_step_index`** (integer, optional) — 0-based step index; omit to participate in **order-based** slot filling.

**Mixed array example** (strings + objects; backward compatible):

```json
"expected_step_screenshots": [
  "data/screenshots/flow/step1.png",
  {
    "path": "data/screenshots/flow/step3.png",
    "label": "Figure 1.1",
    "mapped_to_step_index": 2
  }
]
```

`mapped_to_step_index` is 0-based. Entries **without** that field fill **first empty** step slots in array order after mapped slots are applied (`resolved_step_screenshots` in `src/scenario_media.py`).

---

## `changed_areas[]`

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| `area` | string | recommended | Human-readable area name. |
| `type` | string | optional | Category hint (e.g. `frontend`, `backend`, `business_logic`, `user_feedback`). |

---

## JSON examples

Bundled samples:

- `data/sample_profile_phone_update.json`
- `data/sample_login_flow.json`

---

## JSON on disk — optional evidence helpers (`json_import_media`)

Some modules support **basename-matched** evidence rewrites for **JSON authored or loaded by tooling**; that does **not** change the field shapes above (paths remain strings or `{ "path", "label?", "mapped_to_step_index?" }`). **DOCX** output uses the same fields after reconciliation (often parallel string paths + labels). See `docs/intake_notes.md` and `src/json_import_media.py`. **Default in-app intake** is **DOCX** via **File Upload**, not user JSON upload.

---

## DOCX import parity

`src/docx_parser.py` builds the same top-level keys and types described above so **JSON** and **DOCX** scenarios share one contract. Typical differences from hand-authored JSON:

- `scenario_id` is prefixed (e.g. `docx_<slug>`).
- `changed_areas` and `known_dependencies` are populated **when** section headings/labels match heuristics; otherwise they may be **empty** (see `docs/intake_notes.md` — known parsing limitations).
- `workflow_process_screenshots` holds **workflow / context** images and **overflow** screenshots that are **not** assigned to a step index (unassigned or unclear mapping—see `docs/intake_notes.md`).
- `expected_step_screenshots` after import is reconciled to **parallel path + label arrays** (and optional `expected_step_screenshot_labels`) compatible with the same resolution rules as JSON; hand-authored JSON may use **strings** and/or **objects** with `path` / `label` / `mapped_to_step_index` as in this document.
- `notes` includes import metadata and parser caveats.

---

## Validation

There is **no** JSON Schema file or runtime validator in-repo today; this document is the contract for authors and parsers. If you add fields, update this file and any parser that should populate them.

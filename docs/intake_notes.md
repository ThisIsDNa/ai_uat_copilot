# Intake layer — notes for handoffs

Use this together with **`docs/cursor_handoff.md`** (current product), **`docs/development_guidance.md`** (priority and change workflow), **`docs/schema.md`** (data contract), **`docs/testing_notes.md`** (manual test findings), and **`docs/retrospective.md`** (project arc).

*Planned (not product yet):* **Context intake — Step 0** — a future guided step or flow to capture richer upstream context before AC/TC generation; this file stays focused on current **DOCX / builder → dict** behavior until that ships. **Stabilization-phase architecture** (generation pipeline, workflow types, gating) is summarized in **`docs/cursor_handoff.md`** — read that file before large intake or builder changes.

---

## What “intake” means here

Anything that produces the **scenario dict** consumed by `app.py` and `src/*` modules.

**User-facing (default product path):**

1. **`.docx`** — **`File Upload`**: **Parse document** → normalized dict, persisted as **internal JSON** (`data/saved_scenarios/`) + registry, media under `data/docx_imports/<slug>/`.
2. **AI Scenario Builder** — guided fields + **paste-friendly** multiline inputs (e.g. acceptance criteria, steps) → **Save** → same internal JSON + registry. **`scenario_context`** (free text) is the **canonical narrative field** for C3 when non-empty; it is saved on the scenario dict and powers **context expansion** and generation (legacy **`story_description`** still merges into context when context is empty — see **`docs/schema.md`**).

**Internal / developer:** JSON on disk via **`src/intake_parser.load_scenario`**, **pytest** fixtures, and optional tooling paths. Same **`docs/schema.md`** contract; not the primary in-app author surface.

The rest of the app should not care which path was used once `data` is populated.

---

## Scenario Management (flow)

Single app view for **saved registry rows** and **review state** (not the primary DOCX import surface, not the reviewer packet):

- **Scenarios tables** — grouped by review state; **`scenario_id`**, title, **Open in builder**, optional **delete** (**Test Manager** only), editable review state where role allows.
- **Remove saved scenarios** — per-row **delete** → **`delete_saved_scenario`** in `src/scenario_registry.py` (path must resolve under `data/saved_scenarios/` for file unlink).

**Scenario Review** (internal app key **`Overview`**) remains **review-only**: scenario **dropdown**, **Quick stats**, **Scenario details**, review tabs (no registry delete there).

---

## Import flow (user DOCX vs internal JSON)

| Step | User-facing **DOCX** | Internal **JSON** (persistence / tooling) |
|------|----------------------|---------------------------------------------|
| Where | **`File Upload`** | `data/saved_scenarios/*.json`, tests, `load_scenario` |
| Input | `st.file_uploader` (`.docx`) | Files on disk (or fixtures) |
| Primary action | **Parse document** — parses, saves scenario JSON + registry row, extracts images | Read/write via registry + **`intake_parser`**; same normalized dict |
| Persist | Automatic on successful parse | **AI Scenario Builder Save**, DOCX parse, or tooling writes registry + file |
| Feedback | Spinner + success (elapsed time optional); quick stats panels when implemented | N/A for silent disk reads |

**Scenario Review sidebar stats** describe the **selected** scenario. **File Upload** may show **last parsed** preview stats for that view.

**Lifecycle** — see **Scenario lifecycle** in `docs/cursor_handoff.md` (import → preview → save → select → delete).

---

## JSON path (internal / developer)

| Piece | Location |
|--------|-----------|
| Loader | `src/intake_parser.py` — `load_scenario(path)` calls `normalize_scenario_image_paths` so paths in `workflow_process_screenshots` / `expected_step_screenshots` that are **not** already valid from the **project root** are resolved against the **JSON file’s directory** (e.g. `./login_error.png` next to the scenario file). Missing files add `ingestion_meta.warnings` and still load. If the JSON directory is outside the project root, sibling resolution is skipped (warning). |
| Catalog | `src/scenario_registry.py` — `BUNDLED` + `data/scenario_registry.json` → `build_scenario_catalog()` |
| Session-only preview | Legacy / internal keys (e.g. `json_pasted_scenario_data`) may still exist for edge flows; **default intake** is **DOCX** on **File Upload**. |
| Optional evidence helpers | `src/json_import_media.py` — basename-matched rewrites for tooling / non-default flows; see module docstrings. |
| Saved files | `data/saved_scenarios/*.json` |
| Samples | `data/sample_*.json` (tests / examples) |

**Handoff rule:** New **bundled** scenarios = valid JSON per `docs/schema.md` + one entry in `BUNDLED` in `scenario_registry.py`. **Saved** rows are registry entries pointing at files under `data/saved_scenarios/`. Any alternative JSON upload path must still validate against the scenario object shape (`_validate_scenario_upload_shape` in `src/ui_import.py`) if enabled in code.

---

## DOCX path

| Piece | Location |
|--------|-----------|
| Parser | `src/docx_parser.py` — `parse_scenario_from_docx(uploaded_file)`; returns optional **`ingestion_meta`** with **`images_detected`** (embedded images in body) and **`warnings`** (e.g. no images found). No AI-generated captions or invented descriptions. |
| UI | `src/ui_file_upload_debug.py` — **File Upload**, **Parse document** |
| Persist | `src/scenario_registry.py` — `persist_parsed_docx_scenario` |
| Session / UX | `docx_upload_name`, `_import_preview_scenario`, etc. |
| Extracted media | `data/docx_imports/<slug>/media/` (gitignored) |

**Handoff rule:** Parser output must stay aligned with `docs/schema.md`. Prefer small, targeted heuristic changes in `docx_parser.py` over app-wide refactors.

**Debug (developer):** `python scripts/inspect_docx_structure.py path/to/file.docx` — block order, Word paragraph styles, and quick hints (`section~…`, `tc_open:…`) using the same header matchers as the parser (no UI). Optional local fixtures: see **`test_assets/README.md`**; example `python scripts/inspect_docx_structure.py "test_assets/docx/doc_healthcare.docx"` or bare `doc_healthcare.docx` (resolves under `test_assets/docx/`). Does not affect end-user uploads.

**UX detail:** If the user selects a new file before parsing, a caption reminds them to click **Parse document** again so the UI does not silently show stale content.

### How `.docx` parsing works

- **Text extraction:** Body **paragraphs** and **table cells** are read in document order. Multi-line paragraphs are split into lines; leading **bullets** (`•`, `-`, `*`, common Unicode bullets) are stripped for body text. **Word heading** styles (e.g. Heading 1, Title) are treated as headings so numbered heading text is not mistaken for test steps. Headings that **do not** match a known section keyword are appended to **`notes`** (unstructured catch-all).
- **Section detection:** A finite-state parser uses **labeled lines** (e.g. `Story title:`, `Business goal:`, `Acceptance criteria:`) plus **keyword / synonym matching** on headings (after stripping outline prefixes like `1.`) to switch context—story, business goal, acceptance, **changed areas**, **dependencies**, tests, workflow/context. **Acceptance criteria** accumulate until a **new section** or **test case** header appears. **Test cases** open on `TC-…`, `Test case …`, and related patterns. **Steps** come from numbered lines (`1.`, `Step 1:`), **Word list numbering** (`numPr`) in the test area, or **tables** in the tests section (two+ columns → `Action — Expected: …`). **Expected result:**-style lines merge into the **previous step** text.
- **Fallback:** If sections are not confidently identified, content may land in **`notes`** or **`workflow_process_screenshots`** instead of AC/TC/changed-area fields—see **Known parsing limitations** below.
- **Screenshots — extract & store:** Embedded images are resolved from **DrawingML blips** and **VML imagedata** under each paragraph (relationship ids deduped), written as `img_NNNN.ext` under `data/docx_imports/<slug>/media/`, referenced by **paths relative to the project root** (same as JSON).
- **Screenshots — explicit mapping (figure references):** Caption-style text on the same paragraph as an image (or a **short caption-only** paragraph immediately before an image-only paragraph) registers a **label → path** (e.g. **Figure 1.1**, **Fig 2**, **`[Screenshot 3]`**). Step text that references those labels (**see Figure …**, **refer to Fig …**, etc., or plain **Figure N** if no contextual phrase matched) is used **after the full parse** to place images on the matching **step index**. **One** resolved reference per step wins for placement.
- **Screenshots — fallback:** During the walk, images still use the **legacy heuristic**: in the **tests** context, fill **`expected_step_screenshots`** in document order while `len(shots) < len(steps)` (one path per step). **Reconciliation** then **overrides** slots where figure references resolve; remaining heuristic paths fill **empty** slots in order; unused paths and registry orphans go to **`workflow_process_screenshots`**.

**Supported figure label formats (DOCX / captions):** `Figure N`, `Fig N`, `Fig. N`, dotted forms **`Figure 1.1`**, bracketed **`[Screenshot N]`**, **`[Screen N]`**, **`[Fig N]`**, **`[Figure N]`** (regex-based; not arbitrary prose).

### Assumptions (DOCX)

- **Paste-friendly structure** in Word (clear headings, **`AC-*`** / **`TC-*`** lines, numbered steps, **Figure** captions) aligns with both **DOCX import** and **AI Scenario Builder** bulk patterns—see **`docs/development_guidance.md`**.
- Authors use recognizable **labels** and/or **headings** for major sections; **test cases** start with patterns like `TC-01` or `Test case …`.
- **Steps** are conveyed with **numbering** (`1.`, `Step 1:`), **Word numbered lists** in the test area, and/or **test-section tables** as above.
- **Figure mapping** works best when **captions sit with or directly before** the image and **step text uses the same numbering** as the caption (normalized, e.g. leading zeros dropped in segments).
- **`.docx` only** (ZIP / Office Open XML); legacy `.doc` is not supported.

### Limitations (DOCX accuracy)

- Layouts that **don’t** match the heuristics (unusual tables, heavy text boxes, scanned pages, linked-but-not-embedded images) will **lose or mis-route** structure and evidence.
- **Screenshot-to-step** is **not** semantic or visual; **explicit figure references** reduce ambiguity but **do not guarantee** correct mapping if labels duplicate, captions are far from images, or wording falls outside supported patterns.
- **Fallback** remains **order + section + conservative caps**; **`workflow_process_screenshots`** is the catch-all for **overflow** and **unplaced** registry images—reviewers should scan it.

---

## Known parsing limitations

**Scope:** **DOCX** extraction only (JSON follows `docs/schema.md` + app validation; image path checks are separate).

Practical impact for reviewers and authors:

- **Acceptance criteria** — Often **missing or wrong** if the document uses non-standard headings, merges ACs into prose, uses tables without recognizable `AC-1` patterns, or omits clear section breaks.
- **Test cases** — Often **missing or collapsed** if cases are not introduced with recognizable `TC-…` / **Test case** patterns, or if steps are not numbered / listed in a way the parser expects.
- **Test steps** — Can **merge incorrectly** or **omit** when bullets, numbering, or tables do not match heuristics.
- **Changed areas / dependencies** — **Frequently empty** when sections are titled differently (e.g. informal “Scope” prose) or not styled as headings.
- **Business goal** — **Inconsistently detected** when labeled differently or placed outside detected sections.
- **Screenshots** — **Figure** labels and step references work when structure matches supported patterns; otherwise **order-based** placement may mis-assign; overflow goes to **`workflow_process_screenshots`**.
- **Unrecognized headings** go to **`notes`**; do not assume DOCX import is complete without checking **Scenario Review** and tabs against the source Word file.

---

## Media paths

- Always **relative to project root** (see `src/scenario_media.py` — `resolved_step_screenshots`, `workflow_process_screenshot_pairs` normalize **string** and **object** `{ path, label?, mapped_to_step_index? }` entries for the UI).
- DOCX imports write files under `data/docx_imports/...`; JSON samples use `data/screenshots/...`; optional JSON upload evidence under `data/json_upload_media/...`.

---

## What not to break

- **Internal JSON contract** (`docs/schema.md`) must keep working for saved scenarios, builder save, and tests when editing intake.
- **Schema consistency** — tabs, traceability, coverage gaps, and test results assume the fields in `docs/schema.md`.
- **Reviewer workflow** — do not remove gating that depends on `scenario_id` / per–test-case keys without an explicit product decision (see `cursor_handoff.md`).

---

## Known intake limitations (current)

- **DOCX:** heuristic parsing, unreliable AC/TC/changed-area/business-goal extraction on varied templates; conservative screenshot mapping; **`.docx` only** (not `.doc`).
- **JSON (disk/tests):** no separate JSON Schema file in-repo—see `docs/schema.md`.
- **Delete** (saved scenarios) does not remove **`data/docx_imports/`** folders.

---

## Suggested handoff checklist

1. Read `docs/cursor_handoff.md` for stage and priorities.
2. Read `docs/schema.md` if changing fields or parsers.
3. If touching DOCX: run a representative `.docx` through `parse_scenario_from_docx` and spot-check `test_cases`, `acceptance_criteria`, `changed_areas`, `business_goal`, figure references, and image paths.
4. Confirm bundled + saved JSON still load via **`load_scenario`** / **Scenario Review** picker, and **File Upload** DOCX parse still persists registry rows.

---

## Related files (quick reference)

| Concern | File |
|---------|------|
| Catalog, persist, delete saved scenarios | `src/scenario_registry.py` |
| JSON import evidence uploads + path rewrite | `src/json_import_media.py` |
| Scenario dict field usage (media) | `src/scenario_media.py` |
| Traceability input | `src/traceability.py` |
| Coverage gaps input | `src/coverage_gaps.py` |
| Reviewer focus context | `src/summarizer.py`, `src/placeholder_outputs.py` |

# AI_UAT_Copilot — Project Retrospective

## Overview

AI_UAT_Copilot began as an exploration of how AI could support validation workflows, specifically within UAT (User Acceptance Testing). The goal evolved into building a system that reduces reviewer cognitive load by structuring scenario data into a clear, actionable validation experience.

This retrospective captures how the project evolved, key decisions made, lessons learned, and the current state of the system.

**Related documentation (live spec vs history):** For **current** capabilities, limits, and lifecycle, use **`docs/cursor_handoff.md`**. For **how to change the codebase** (DOCX priority, workflow), use **`docs/development_guidance.md`**. For **ongoing manual test observations**, use **`docs/testing_notes.md`**. This retrospective is the **narrative arc**, not the authoritative field schema (**`docs/schema.md`**) or ingestion details (**`docs/intake_notes.md`**).

---

## Phase 1 — Problem Framing

Initial thinking focused on:

- AI-assisted validation
- reducing human review burden
- bridging gaps between automation and manual QA

Key decision:

- Narrow scope to **UAT workflows** instead of broader SDLC or generic AI tooling

Why it mattered:

- grounded the project in a real, familiar workflow
- reduced ambiguity
- made the system more actionable

---

## Phase 2 — Structural Foundation

Focus:

- building the app container
- defining schema
- organizing tabs and workflow

Key components:

- Scenario schema (JSON-based)
- Overview / Review tabs
- Placeholder outputs

Lesson:

- Structure must come before intelligence

---

## Phase 3 — Reviewer Workflow Design

Shift toward:

- usability
- clarity
- human-centered design

Introduced:

- Quick Stats
- Reviewer Focus
- Coverage Gaps
- Review Synthesis
- clearer tab structure

Lesson:

- the product is not the data, it is the **review experience**

---

## Phase 4 — Intelligence Layer

Added:

- traceability
- coverage gap detection
- reviewer guidance

Key realization:

- AI should enhance decision-making, not replace it

Lesson:

- intelligence must sit inside a structured workflow

---

## Phase 5 — Input Normalization

Introduced:

- JSON (structured baseline)
- DOCX (real-world input)

Added:

- schema normalization
- screenshot mapping
- scenario ingestion flow

Key realization:

- system quality is limited by input quality

Lesson:

- ingestion is as important as output

---

## Phase 6 — Scenario Lifecycle

Expanded from:

- “load and display”

To:

- import → preview → save → select → delete

Introduced:

- Scenario Management view
- scenario table
- delete functionality
- source labeling (JSON / DOCX)

Lesson:

- systems need lifecycle, not just functionality

---

## Phase 7 — Validation and Testing Layer

Created:

- testing_notes.md
- structured iteration tracking

Introduced:

- JSON validation (missing image detection)
- success messaging and loaders

Lesson:

- testing must feed back into system design

---

## Phase 8 — Workflow usability and trust consolidation (recent)

**Theme:** Product and reviewer UX, not parser expansion.

- **Duplicate UI signals** (e.g. **Missing Sections** vs **Import Warnings**, completeness repeated in debug) were **consolidated** — fewer panels, clearer primary signals (**numbered Import Warnings**, merged **Quick Stats**).
- **Hardcoded bundled JSON starters** were **removed** from the catalog; the app now defaults to a **Title Screen** instead of assuming sample scenarios — avoids artificial “happy path” onboarding.
- **Reviewer tabs** were **simplified** (Scope / Test Cases / Test Results; lighter Test Cases list; coverage gap layout readability).
- **Trust** improved by **honest, scannable guidance** rather than long parallel explanations.
- **Structural extraction** of UI into **`src/ui_*`** reduced pressure on **`app.py`** for import, trust, overview, and review synthesis.

**Lesson:** Reducing noise and assumption-laden defaults often helps reviewers more than adding explanatory chrome.

---

## Phase 9 — DOCX-first roles and paste-friendly authoring (recent)

**Theme:** Product direction, not parser-only work.

- **DOCX as primary user interchange** — **`File Upload`** is **DOCX-only** for import; persisted files remain **internal JSON** aligned with **`docs/schema.md`**.
- **Separation of roles** — Simulated **Tester** / **Test Lead** / **Test Manager** gate **Scenario Review**, registry **delete**, and testing-status edits (`src/app_roles.py`).
- **AI Scenario Builder** — Shift toward **multiline / bulk** inputs (acceptance criteria, steps) instead of only incremental row controls; **AC-driven** empty test-case generation where product requires it.
- **UI clarity** — Scenario dropdown **titles** without **`[JSON]`** source prefix; **Scenario Review** as the user-facing name for the review packet view.

**Observations**

- **Streamlit state** — Widget-backed keys (**especially `file_uploader`**) are fragile: prefer updating the **data model** and **rebinding** widgets with new keys after structural deletes (see **`docs/development_guidance.md`**).
- **System integrity before AI** — Traceability, gaps, and polish only help when **AC/TC/steps/screenshots** land in the normalized model reliably (DOCX remains the bottleneck).

---

## Phase 10 — C2/C3: from validation tool to AI-assisted authoring (checkpoint)

**Theme:** The product’s center of gravity shifted from **only identifying issues** in a loaded packet to **generating, refining, and guiding** scenario construction while keeping the same **internal JSON** contract and reviewer packet.

- **Guided builder** — AC, positive TC, optional negative TC, and test-step generation with **review dialogs** and explicit merge/replace choices.
- **Scenario Review** — **Structural feedback** and **suggested fixes** sit alongside gaps and test results; **smart linking** connects review signals to builder-side actions where implemented.
- **Trust** — Generation stays **non-destructive by default**; users can still edit every line after apply.

**Likely next evolution:** **Context intake (Step 0)** — richer upstream context before generation (see **`docs/cursor_handoff.md`**).

---

## Current State

**Stabilization (in progress, 2026):** Core build and the **generation / routing stack** (scenario type detection, expansion, strict gating, **`action_event_flow`**, coverage, intent, suite optimization) are **implemented**; the team is validating them on realistic scenarios. **Live** phase description and file-level map: **`docs/cursor_handoff.md`**. This retrospective is **not** updated per stabilization sprint; a fuller arc can be written after realistic validation settles.

### Strong Areas

- JSON ingestion (reliable baseline)
- Scenario lifecycle (clear and functional)
- Reviewer workflow (well structured)
- Documentation system (high quality)
- UI clarity and separation of concerns

### Weak Areas

- DOCX parsing reliability (primary bottleneck)
- inconsistent extraction of:
  - acceptance criteria
  - test cases
  - changed areas
  - business goal
- screenshot mapping depends heavily on structure

---

## Key Lessons Learned

1. A stable **internal JSON** contract is essential for persistence, tests, and UI—while **DOCX** (and builder paste fields) remain what authors touch day-to-day
2. DOCX introduces real-world variability and complexity
3. Reviewer trust depends on early validation (intake, not just output)
4. Systems should reduce cognitive load, not add to it
5. Structure before intelligence is the correct order
6. Lifecycle design is as important as feature design

---

## Current Bottleneck

DOCX parsing reliability is the largest constraint on system usefulness.

Until DOCX parsing improves:

- the system is strongest in controlled scenarios (fixtures / well-formed saved scenarios)
- weakest in real-world **DOCX** usage

---

## Next Focus Areas

1. Improve DOCX parsing reliability:
   - acceptance criteria detection
   - test case detection
   - step extraction

2. Align DOCX outputs with JSON baseline

3. Improve trust in outputs:
   - avoid misleading completeness
   - surface uncertainty clearly

4. Continue iterative testing:
   - clean vs semi-structured vs messy documents
   - folder-packaged JSON (paths next to the file) vs browser upload (no sibling context for `./` unless user uses root-relative paths or disk load)

---

## Final Reflection

The project evolved from:

- an idea about AI-assisted validation

into:

- a structured system that supports human reviewers in making better decisions

The strongest aspect of this project is its focus on:

- reducing human effort
- structuring ambiguity
- improving clarity in validation workflows

The next phase is not about adding features, but about:

- improving reliability
- increasing trust
- handling real-world input more effectively

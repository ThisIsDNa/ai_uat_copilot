# test_assets (local debugging)

Optional **local** fixtures for regression checks and parser debugging. **Not** used by the Streamlit app; uploads still come from anywhere on disk.

Suggested layout (create files yourself):

- `docx/` — e.g. `doc_healthcare.docx`, `doc_ecommerce.docx`, `doc_banking.docx`
- `json/` — e.g. `scenario_healthcare.json`, … (baseline comparisons)

**Inspect a DOCX** (from repo root):

```text
python scripts/inspect_docx_structure.py "test_assets/docx/doc_healthcare.docx"
python scripts/inspect_docx_structure.py doc_healthcare.docx
```

The second form resolves to `test_assets/docx/doc_healthcare.docx` when you pass a bare filename.

#!/usr/bin/env python3
"""
Developer helper: dump .docx block order, paragraph styles, and line-level hints
for aligning templates with src/docx_parser.py heuristics.

This script reads a **real file from disk** (Streamlit upload is unrelated). Paths can be
absolute or relative to the current working directory (usually repo root).

Usage (from repo root):

  python scripts/inspect_docx_structure.py "C:/path/to/any/document.docx"
  python scripts/inspect_docx_structure.py "test_assets/docx/doc_healthcare.docx"
  python scripts/inspect_docx_structure.py doc_healthcare.docx
  python scripts/inspect_docx_structure.py doc_healthcare.docx --json

The last form resolves to ``test_assets/docx/<filename>`` **only** when you pass a bare
filename (no ``/`` or ``\\``) and that file is not found in the current directory.
End-user app uploads are unchanged; this is CLI-only.

Does not modify the document. Not used by the Streamlit app.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo root on path for parser imports
_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DOCX_DIR = _ROOT / "test_assets" / "docx"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.docx_parser import (
    _infer_section_from_free_heading,
    _is_heading_paragraph,
    _match_section_header,
    _parse_test_case_header,
    iter_block_items,
)


def resolve_docx_path(raw: Path, *, cwd: Path | None = None) -> Path:
    """
    Resolve to an existing .docx file.

    1) ``raw`` as given (relative to cwd or absolute).
    2) If missing and ``raw`` is a bare ``*.docx`` name, try ``test_assets/docx/<name>``
       under the repo root (debug fixtures only).
    """
    cwd = cwd or Path.cwd()
    candidates: list[Path] = []
    p = (cwd / raw).resolve() if not raw.is_absolute() else raw.expanduser().resolve()
    candidates.append(p)
    s = str(raw)
    bare_name = "/" not in s and "\\" not in s and raw.suffix.lower() == ".docx"
    if bare_name:
        fb = (_FIXTURE_DOCX_DIR / raw.name).resolve()
        if fb not in candidates:
            candidates.append(fb)
    for c in candidates:
        if c.is_file():
            return c
    tried = ", ".join(str(x) for x in candidates)
    print(
        "No readable .docx found.\n"
        f"  Argument: {raw!s}\n"
        f"  Tried: {tried}\n"
        "\n"
        "Pass a real path to a Word file on disk (not a label or URL).\n"
        "For local fixtures: place files under test_assets/docx/ or pass the full path.\n"
        "Bare filename fallback: test_assets/docx/<name> (repo root) when no path separators.",
        file=sys.stderr,
    )
    sys.exit(1)


def _paragraph_record(p: Paragraph, index: int) -> dict:
    style = ""
    try:
        style = (p.style.name or "").strip()
    except (AttributeError, TypeError):
        pass
    text = (p.text or "").strip()
    lines = [ln.strip() for ln in (p.text or "").splitlines() if ln.strip()]
    hints: list[str] = []
    is_h = _is_heading_paragraph(p)
    if is_h and text:
        sec = _match_section_header(text)
        if sec is None:
            sec = _infer_section_from_free_heading(text)
        if sec:
            hints.append(f"section~{sec}")
        else:
            hints.append("heading (no section match)")
    for ln in lines[:3]:
        h2 = _match_section_header(ln)
        if h2:
            hints.append(f"line→{h2}")
        tc_id, _t = _parse_test_case_header(ln)
        if tc_id:
            hints.append(f"tc_open:{tc_id}")
    return {
        "i": index,
        "kind": "paragraph",
        "style": style,
        "is_heading_style": is_h,
        "text_preview": text[:240] + ("…" if len(text) > 240 else ""),
        "line_count": len(lines),
        "hints": list(dict.fromkeys(hints)),
    }


def _table_record(table: Table, index: int) -> dict:
    rows_out: list[list[str]] = []
    for row in table.rows[:12]:
        cells = []
        for cell in row.cells:
            parts = [p.text.strip() for p in cell.paragraphs if p.text.strip()]
            cells.append(" ".join(parts).strip())
        if any(cells):
            rows_out.append(cells)
    return {
        "i": index,
        "kind": "table",
        "row_count": len(table.rows),
        "first_rows": rows_out,
    }


def inspect_docx(path: Path) -> dict:
    doc = Document(str(path))
    blocks: list[dict] = []
    for bi, block in enumerate(iter_block_items(doc)):
        if isinstance(block, Paragraph):
            blocks.append(_paragraph_record(block, bi))
        elif isinstance(block, Table):
            blocks.append(_table_record(block, bi))
    return {"file": str(path.resolve()), "blocks": blocks}


def _print_text_report(data: dict) -> None:
    sep = "─" * 72
    print(sep)
    print(f"DOCX structure inspect  |  file: {data['file']}")
    print(f"Blocks (body order): {len(data['blocks'])}")
    print(sep + "\n")
    for b in data["blocks"]:
        idx = b["i"]
        if b["kind"] == "paragraph":
            hs = ", ".join(b["hints"]) if b["hints"] else "(no parser hints)"
            htag = "HEADING" if b["is_heading_style"] else "paragraph"
            print(f"## Block {idx} — {htag}")
            print(f"   style: {b['style']!r}  |  lines in block: {b['line_count']}")
            print(f"   hints: {hs}")
            print(f"   text:  {b['text_preview']}\n")
        else:
            print(f"## Block {idx} — TABLE ({b['row_count']} rows)")
            for ri, r in enumerate(b.get("first_rows") or []):
                print(f"   row {ri}: {r}")
            print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Inspect .docx body structure for parser debugging. "
            "Requires a real file path; bare *.docx may resolve under test_assets/docx/."
        )
    )
    ap.add_argument(
        "docx",
        type=Path,
        help="Path to a .docx file on disk, or a bare filename for test_assets/docx/",
    )
    ap.add_argument("--json", action="store_true", help="Print JSON only (machine-readable)")
    args = ap.parse_args()

    path = resolve_docx_path(args.docx)
    data = inspect_docx(path)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    _print_text_report(data)


if __name__ == "__main__":
    main()

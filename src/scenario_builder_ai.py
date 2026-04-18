"""
Optional OpenAI helpers for the Scenario Builder — wording only, same cardinality as input.
"""

from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

load_dotenv()


def polish_parallel_texts(
    items: list[str],
    *,
    role: str,
) -> list[str] | None:
    """
    Refine wording for a list of user-authored strings. Returns list of same length, or None on skip/failure.

    role: short description e.g. "acceptance criteria" or "test step lines".
    Does not add or remove entries.
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    cleaned = [str(x).strip() for x in items]
    if not cleaned:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    client = OpenAI(api_key=api_key)
    payload = json.dumps(
        [{"index": i, "text": t} for i, t in enumerate(cleaned)], ensure_ascii=False
    )
    prompt = f"""You polish UAT {role} wording. The user wrote each item below — keep meaning; fix grammar and clarity only.

Rules:
- Return ONLY a JSON array of strings, same length and order as the input ({len(cleaned)} strings).
- Do not add new items, remove items, or invent requirements or coverage.
- If an input string is empty, return "" for that slot.

Input (JSON array of objects with index and text):
{payload}
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception:
        return None

    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content, re.IGNORECASE)
    if m:
        content = m.group(1).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or len(parsed) != len(cleaned):
        return None
    out: list[str] = []
    for x in parsed:
        if x is None:
            out.append("")
        elif isinstance(x, str):
            out.append(x.strip())
        else:
            out.append(str(x).strip())
    return out


def suggest_test_steps_from_title(title: str) -> list[str]:
    """
    Lightweight step scaffolding from a test case title (no API required).
    Callers may optionally run ``polish_parallel_texts`` on the result when an API key is set.
    """
    t = (title or "").strip() or "the feature under test"
    if len(t) > 120:
        t = t[:117] + "…"
    return [
        f"Open or navigate to the part of the application that supports: {t}",
        "Perform the primary user actions that exercise this test case.",
        "Verify the outcome matches expectations (UI, data, or system messages).",
        "Note or capture any evidence needed for review (screenshots are added in a later step).",
    ]

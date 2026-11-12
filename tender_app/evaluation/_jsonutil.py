"""Small shared helpers for parsing JSON returned by the LLM.

The Gemini model often wraps JSON in ``` or ```json code fences. These helpers
strip the fences and parse leniently so the LLM-driven stages (coverage,
capacity, pricing) can share one robust parser.
"""
from __future__ import annotations

import json
from typing import Any


def strip_code_fences(text: str) -> str:
    """Remove a surrounding ``` or ```json code fence if present."""
    s = (text or "").strip()
    if s.startswith("```"):
        newline = s.find("\n")
        if newline != -1:
            s = s[newline + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def parse_json(text: str) -> Any:
    """Strip code fences and parse the JSON payload. Raises on invalid JSON."""
    return json.loads(strip_code_fences(text))

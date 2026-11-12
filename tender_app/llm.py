"""Thin wrapper around the Google GenAI (Gemini) SDK."""
from __future__ import annotations

from google import genai
from google.genai import types

from . import config

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.require_api_key())
    return _client


def generate(prompt: str, system: str | None = None, temperature: float = 0.4) -> str:
    """Single-shot text generation."""
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=system,
    )
    resp = client().models.generate_content(
        model=config.LLM_MODEL,
        contents=prompt,
        config=cfg,
    )
    return (resp.text or "").strip()


def generate_multimodal(
    prompt: str,
    images: list[bytes],
    system: str | None = None,
    temperature: float = 0.2,
) -> str:
    """Single-shot multimodal generation: text prompt + one or more PNG page images.

    ``images`` are raw PNG bytes (e.g. rendered by pypdfium2). Each is passed as
    an inline image part alongside the text prompt. Used for OCR and content
    classification/extraction against the same multimodal ``config.LLM_MODEL``
    ("gemini-2.5-flash"). Mirrors ``generate(...)`` for system instruction,
    temperature, and return handling.
    """
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=system,
    )
    contents: list = [prompt]
    for img in images:
        contents.append(types.Part.from_bytes(data=img, mime_type="image/png"))
    resp = client().models.generate_content(
        model=config.LLM_MODEL,
        contents=contents,
        config=cfg,
    )
    return (resp.text or "").strip()

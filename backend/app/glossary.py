"""Glossary extraction (DeepSeek), validation, and persistence helpers."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from . import translator

GLOSSARY_PROMPT_PATH = Path(__file__).with_name("glossary_prompt.txt")
CATEGORIES = {"character", "place", "term", "title", "other"}
MAX_EXTRACT_TOKENS = 8192


class GlossaryError(ValueError):
    pass


def validate_glossary(glossary) -> tuple[bool, list]:
    """Shape contract: a list of {original, persian, category, note?}."""
    errors = []
    if not isinstance(glossary, list):
        return False, ["glossary must be a JSON array"]
    for i, item in enumerate(glossary):
        if not isinstance(item, dict):
            errors.append(f"entry {i}: not an object")
            continue
        orig = item.get("original")
        persian = item.get("persian")
        if not orig or not str(orig).strip():
            errors.append(f"entry {i}: missing/empty original")
        if not persian or not str(persian).strip():
            errors.append(f"entry {i}: missing/empty persian")
        if item.get("category", "other") not in CATEGORIES:
            errors.append(f"entry {i}: invalid category {item.get('category')!r}")
    return (not errors), errors


def _parse_payload(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise GlossaryError("response contained no JSON array")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise GlossaryError(f"malformed JSON in response: {e}") from e
    if not isinstance(data, list):
        raise GlossaryError("response is not a JSON array")
    return data


async def _extract_async(client, model: str, prompt: str, text: str, retries: int = 1) -> list:
    last = []
    for _ in range(retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=MAX_EXTRACT_TOKENS,
                extra_body=translator.extra_body(),
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
            )
            raw = resp.choices[0].message.content or ""
        except Exception as e:  # API/transport error — retry once, then loud
            last = [f"API error: {e}"]
            continue
        try:
            data = _parse_payload(raw)
        except GlossaryError as e:
            last = [str(e)]
            continue
        ok, errors = validate_glossary(data)
        if ok:
            return data
        last = errors
    raise GlossaryError(
        "glossary extraction failed: " + "; ".join(str(e) for e in last[:5])
    )


def extract_glossary(text: str, prompt: str, api_key: str | None = None,
                     client=None, model: str | None = None) -> list:
    """Extract proposed glossary terms from a chapter's text.

    `client` is injectable for tests (any object with async
    .chat.completions.create). Raises GlossaryError on failure.
    model: resolved from BYOK settings at call time.
    """
    model = model or translator.current_model()
    if client is None:
        if not api_key and not translator.settings_mod.mock_enabled():
            raise GlossaryError("DEEPSEEK_API_KEY is required")
        client = translator._make_client(api_key)
    return asyncio.run(_extract_async(client, model, prompt, text))

"""DeepSeek-backed chapter translation: batching, JSON validation, retry-once,
loud failure with the specific node ids that failed.

DeepSeek's API is OpenAI-compatible: AsyncOpenAI pointed at
https://api.deepseek.com, model "deepseek-v4-flash" (override via
DEEPSEEK_MODEL). Cost rule: flash only — pro is expensive and must be
approved by the user first.

flash is a reasoning model; WITHOUT disabling thinking it spends the whole
output budget on reasoning_content and never answers (content empty,
finish_reason=length). `extra_body={"thinking": {"type": "disabled"}}`
turns it into a fast chat model — verified: 0 reasoning tokens, valid JSON,
~22s/call. response_format json_object is avoided (empty content on this
model family); the prompt already mandates bare JSON and the regex
extraction + validation + retry-once cover the rest.

Public API: translate_chapter(...) — a sync wrapper over async batched calls
(asyncio.gather per chapter).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .textnodes import ChapterData, TextNode
from . import settings as settings_mod

DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEFAULT_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEFAULT_PROMPT_PATH = Path(__file__).with_name("translation_prompt.txt")
MAX_NODES_PER_BATCH = 50
MAX_TOKENS_PER_BATCH = 2000
CHARS_PER_TOKEN = 4
# Cap concurrent batch requests per chapter. Firing every batch of a large
# chapter at once (25+ parallel calls) trips provider rate limits (429s) and
# whole chapters fail after the single retry. 4 parallel is a safe ceiling.
MAX_CONCURRENT_BATCHES = 4
API_RETRY_BACKOFF = 2.0  # seconds before retrying a transport/rate-limit error
# flash is a reasoning model that consumes ALL available output budget on
# reasoning_content when thinking is left on (16k -> never answers). With
# thinking disabled via extra_body, output tokens are pure answer, so give it
# headroom for a full 50-node batch of Persian text (~4-6k tokens).
MAX_OUTPUT_TOKENS = 16384
THINKING_DISABLED = {"thinking": {"type": "disabled"}}  # DeepSeek-specific


class TranslationError(RuntimeError):
    """Raised when a batch fails validation after all retries.

    failing_ids: the input node ids of the failed batch (or [] when the
    failure happened before id-level validation, e.g. malformed JSON).
    """

    def __init__(self, message: str, failing_ids: list):
        super().__init__(message)
        self.failing_ids = failing_ids


@dataclass
class TranslationResult:
    chapter: ChapterData
    report: dict


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def build_batches(nodes, max_nodes=MAX_NODES_PER_BATCH, max_tokens=MAX_TOKENS_PER_BATCH):
    """~max_nodes nodes or ~max_tokens tokens per batch, whichever comes first."""
    batches, cur, tokens = [], [], 0
    for n in nodes:
        t = estimate_tokens(n.text)
        if cur and (len(cur) >= max_nodes or tokens + t > max_tokens):
            batches.append(cur)
            cur, tokens = [], 0
        cur.append(n)
        tokens += t
    if cur:
        batches.append(cur)
    return batches


def current_model() -> str:
    """Model from BYOK settings, falling back to env/module default."""
    cfg = settings_mod.load_settings()
    return cfg.get("model") or DEFAULT_MODEL


def extra_body() -> dict | None:
    """DeepSeek-only thinking-disabled flag. OpenAI/custom providers reject
    unknown request params, so the flag is omitted unless the provider
    preset enables it (deepseek)."""
    cfg = settings_mod.load_settings()
    return THINKING_DISABLED if cfg.get("disable_thinking") else None


def _make_client(api_key: str | None = None, base_url: str | None = None):
    if settings_mod.mock_enabled():
        from .mockai import mock_client

        return mock_client()
    from openai import AsyncOpenAI

    cfg = settings_mod.load_settings()
    key = api_key or cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    url = base_url or cfg.get("base_url") or DEFAULT_BASE_URL
    return AsyncOpenAI(api_key=key, base_url=url)


def _parse_payload(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise TranslationError("response contained no JSON array", [])
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise TranslationError(f"malformed JSON in response: {e}", []) from e
    if not isinstance(data, list):
        raise TranslationError("response is not a JSON array", [])
    return data


def validate_response(ids: list, data) -> tuple[bool, list]:
    """Structural contract: same length, same order, same ids, non-empty
    translations, no nulls."""
    errors = []
    if not isinstance(data, list):
        return False, ["response is not a list"]
    if len(data) != len(ids):
        errors.append(f"count mismatch: expected {len(ids)} nodes, got {len(data)}")
    out_ids = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"item {i} is not an object")
            continue
        iid = item.get("id")
        out_ids.append(iid)
        if iid not in ids:
            errors.append(f"unknown id {iid!r}")
        if "translation" not in item:
            errors.append(f"id {iid}: missing translation field")
        elif item["translation"] is None:
            errors.append(f"id {iid}: null translation")
        elif not str(item["translation"]).strip():
            errors.append(f"id {iid}: empty translation")
    if out_ids != ids:
        errors.append("id order differs from input")
    return (not errors), errors


def _batch_payload(batch, glossary: dict | None = None) -> str:
    items = [{"id": n.id, "text": n.text} for n in batch]
    if glossary:
        # The translation prompt supports a glossary object in the request:
        # terms are treated as fixed, mandatory translations.
        return json.dumps({"items": items, "glossary": glossary}, ensure_ascii=False)
    return json.dumps(items, ensure_ascii=False)


async def _translate_batch(client, model: str, prompt: str, batch, glossary: dict | None = None,
                           retries: int = 1):
    """One batch -> ({node_id: translation}, attempts, usage, kept_original_ids).

    Resilience contract (live failure mode): deepseek-v4-flash occasionally
    returns "" for specific nodes — even plain sentences — deterministically.
    Empty/whitespace translations are dropped from the batch and the node
    KEEPS ITS ORIGINAL TEXT (the epub stays complete; QA can flag it later).
    Null translations, count mismatches, unknown ids etc. are hard errors and
    fail loudly with the batch ids, as before.
    """
    pending = list(batch)
    results: dict = {}
    kept_original: list = []
    usage_dict = None
    attempts = 0
    max_attempts = (retries + 1) * 2  # API retries + empty-drop passes
    last_error = "unknown error"
    while pending and attempts < max_attempts:
        attempts += 1
        ids = [n.id for n in pending]
        raw = None
        try:
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                extra_body=extra_body(),
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": _batch_payload(pending, glossary)},
                ],
            )
            usage = getattr(resp, "usage", None)
            if usage is not None:
                usage_dict = {
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                }
            raw = resp.choices[0].message.content or ""
        except Exception as e:  # API/transport error — backoff, retry, then loud
            last_error = f"API error: {e}"
            if attempts < max_attempts:
                await asyncio.sleep(API_RETRY_BACKOFF)
            continue
        try:
            data = _parse_payload(raw)
        except TranslationError as e:
            last_error = str(e)
            continue
        ok, errors = validate_response(ids, data)
        if ok:
            by_id = {item["id"]: item["translation"] for item in data}
            results.update({n.id: by_id[n.id] for n in pending})
            return results, attempts, usage_dict, kept_original
        empty_ids = {
            item["id"]
            for item in data
            if isinstance(item, dict) and item.get("id") in ids
            and str(item.get("translation") or "").strip() == ""
        }
        returned = [item for item in data if isinstance(item, dict)]
        returned_ids = [item.get("id") for item in returned]
        missing = [i for i in ids if i not in returned_ids]
        extras = [i for i in returned_ids if i not in ids]
        # clean subset = model dropped item(s) but kept everything else
        # intact: same ids, original order, no nulls. Missing nodes keep
        # their original text; the rest is retried. Anything else (reorder,
        # unknown ids, nulls) is corruption and fails loudly below.
        clean_subset = (
            not extras
            and bool(missing)
            and returned_ids == [i for i in ids if i in returned_ids]
            and all(item.get("translation") is not None for item in returned)
        )
        if empty_ids or clean_subset:
            drop = set(empty_ids) | set(missing)
            kept_original.extend(n.id for n in pending if n.id in drop)
            pending = [n for n in pending if n.id not in drop]
            last_error = (
                f"model returned empty/missing for {len(drop)} node(s) — "
                "keeping their original text"
            )
            continue
        # genuine corruption (nulls, reorder, unknown ids, count mismatch
        # beyond a clean subset): retry the same nodes, then fail loudly
        hard_errors = [e for e in errors if "empty translation" not in e]
        last_error = "; ".join(hard_errors[:5]) if hard_errors else "validation failed"
        continue
    if pending:
        raise TranslationError(
            f"batch of {len(pending)} nodes failed after {attempts} attempts: {last_error}",
            [n.id for n in pending],
        )
    return results, attempts, usage_dict, kept_original


async def _translate_async(client, model: str, prompt: str, chapter: ChapterData,
                           glossary: dict | None = None) -> TranslationResult:
    batches = build_batches(chapter.text_nodes)
    sem = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)

    async def _run(batch):
        async with sem:
            return await _translate_batch(client, model, prompt, batch, glossary)

    results = await asyncio.gather(*[_run(b) for b in batches], return_exceptions=True)
    translated_by_id: dict = {}
    total_attempts = 0
    kept_original_ids: list = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    for batch, res in zip(batches, results):
        if isinstance(res, BaseException):
            if isinstance(res, TranslationError):
                raise res
            raise TranslationError(f"API error: {res}", [n.id for n in batch]) from res
        mapping, attempts, batch_usage, kept = res
        translated_by_id.update(mapping)
        total_attempts += attempts
        usage["calls"] += attempts
        kept_original_ids.extend(kept)
        if batch_usage:
            usage["prompt_tokens"] += batch_usage.get("prompt_tokens", 0)
            usage["completion_tokens"] += batch_usage.get("completion_tokens", 0)

    # nodes the model returned empty for keep their original text
    for n in chapter.text_nodes:
        if n.id in kept_original_ids and n.id not in translated_by_id:
            translated_by_id[n.id] = n.text

    new_nodes = [
        TextNode(id=n.id, path=n.path, text=translated_by_id[n.id]) for n in chapter.text_nodes
    ]
    changed = sum(1 for n in chapter.text_nodes if n.text != translated_by_id[n.id])
    report = {
        "batches": len(batches),
        "nodes": len(chapter.text_nodes),
        "changed": changed,
        "retries": total_attempts - len(batches),  # extra attempts beyond the first
        "kept_original": len(kept_original_ids),
        "usage": usage,
    }
    return TranslationResult(
        chapter=ChapterData(chapter_id=chapter.chapter_id, href=chapter.href, text_nodes=new_nodes),
        report=report,
    )


def translate_chapter(chapter: ChapterData, prompt: str, api_key: str | None = None,
                      client=None, model: str | None = None,
                      glossary: dict | None = None) -> TranslationResult:
    """Translate one chapter. `client` is injectable for tests (any object
    with an async .chat.completions.create). Raises TranslationError on failure.
    glossary: {term: persian} — included in every batch request as fixed,
    mandatory translations. model: resolved from BYOK settings at call time."""
    model = model or current_model()
    if client is None:
        if not api_key:
            cfg = settings_mod.load_settings()
            if not (api_key or cfg.get("api_key") or settings_mod.mock_enabled()):
                raise TranslationError("no API key configured — set one in Settings", [])
        client = _make_client(api_key)
    return asyncio.run(_translate_async(client, model, prompt, chapter, glossary))

"""Deterministic in-process stand-in for the AI provider (mock/sandbox mode).

Zero API calls, zero cost — exercises the full UI/pipeline flow (glossary,
translation, QA, finalize) so the app can be tested freely. Every output is
visibly marked with MOCK_PREFIX so mock results are never mistaken for real
translations. Activated via settings mock_mode=True; translator._make_client()
returns this client whenever the flag is on.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

MOCK_PREFIX = "【آزمایشی】"
# fake usage so the cost/token UI stays alive during mock runs
_FAKE_USAGE = SimpleNamespace(prompt_tokens=25, completion_tokens=25, total_tokens=50)


def mock_client():
    """Drops into any `AsyncOpenAI`-shaped call site: .chat.completions.create."""
    return SimpleNamespace(chat=SimpleNamespace(completions=MockCompletions()))


def _respond(payload: list):
    content = json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=_FAKE_USAGE,
    )


class MockCompletions:
    """Dispatch on the request payload shape (same shapes the real pipeline
    sends): translation items, QA items, glossary items, or plain chapter text
    for glossary extraction."""

    async def create(self, **kwargs):
        user = kwargs["messages"][-1]["content"]
        try:
            data = json.loads(user)
        except (json.JSONDecodeError, TypeError):
            data = None

        if isinstance(data, list) and data and isinstance(data[0], dict):
            # translation batch OR titles: [{id, text}]
            return _respond(
                [
                    {"id": it["id"], "translation": MOCK_PREFIX + " " + it["text"]}
                    for it in data
                ]
            )

        if isinstance(data, dict) and "items" in data:
            items = data["items"]
            if not items:
                return _respond([])
            first = items[0]
            if "original" in first and "translation" in first:
                # QA review: scripted fluency issues on the first 2 sampled nodes
                return _respond(
                    [
                        {
                            "id": it["id"],
                            "issue_type": "fluency",
                            "description": "mock QA issue (sandbox mode — not a real problem)",
                            "suggested_fix": MOCK_PREFIX + " " + it["translation"],
                            "original": it["original"],
                            "translation": it["translation"],
                        }
                        for it in items[:2]
                    ]
                )
            if "original" in first and "persian" in first:
                # glossary terms from structured items
                return _respond(
                    [
                        {
                            "original": it["original"],
                            "persian": MOCK_PREFIX + " " + it["original"],
                            "category": "term",
                            "note": "mock mode",
                        }
                        for it in items[:6]
                    ]
                )
            # translation with glossary: {items: [{id, text}], glossary: {...}}
            return _respond(
                [
                    {"id": it["id"], "translation": MOCK_PREFIX + " " + it["text"]}
                    for it in items
                ]
            )

        # plain chapter text -> glossary extraction
        seen, terms = set(), []
        for w in re.findall(r"[A-Za-z]{6,}", user):
            if w in seen:
                continue
            seen.add(w)
            terms.append(
                {
                    "original": w,
                    "persian": MOCK_PREFIX + " " + w,
                    "category": "term",
                    "note": "mock mode",
                }
            )
            if len(terms) >= 4:
                break
        return _respond(terms)

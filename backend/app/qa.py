"""QA/consistency review: sampled per-chapter checks + corrections store.

Runs the QA prompt on a deterministic ~10-15% sample of translated nodes per
chapter (with the approved glossary), persists qa_report.json, and validates
user corrections against real node ids.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from . import translator

QA_PROMPT_PATH = Path(__file__).with_name("qa_prompt.txt")
ISSUE_TYPES = {"glossary_violation", "meaning_drift", "fluency", "tone"}
SAMPLE_FRACTION = 0.12
MAX_QA_TOKENS = 8192


class QAError(ValueError):
    pass


def sample_nodes(nodes: list, fraction: float = SAMPLE_FRACTION) -> list:
    """Deterministic ~10-15% sample via evenly spaced indices."""
    n = len(nodes)
    if n == 0:
        return []
    k = max(1, round(n * fraction))
    if k == 1:
        return [nodes[0]]
    idxs = [round(i * (n - 1) / (k - 1)) for i in range(k)]
    return [nodes[i] for i in dict.fromkeys(idxs)]


def _parse_payload(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise QAError("response contained no JSON array")
    data = json.loads(m.group(0))
    if not isinstance(data, list):
        raise QAError("response is not a JSON array")
    return data


def _valid_issue(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    iid = item.get("id")
    if not iid or item.get("issue_type") not in ISSUE_TYPES:
        return None
    return {
        "id": iid,
        "issue_type": item["issue_type"],
        "description": str(item.get("description") or ""),
        "suggested_fix": str(item.get("suggested_fix") or ""),
    }


async def _qa_batch(client, model: str, prompt: str, items: list, glossary: dict | None):
    payload = {
        "items": [
            {"id": it["id"], "original": it["original"], "translation": it["translation"]}
            for it in items
        ]
    }
    if glossary:
        payload["glossary"] = glossary
    resp = await client.chat.completions.create(
        model=model,
        max_tokens=MAX_QA_TOKENS,
        extra_body=translator.extra_body(),
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    raw = resp.choices[0].message.content or ""
    data = _parse_payload(raw)
    sampled_ids = {it["id"] for it in items}
    issues = [x for x in (_valid_issue(i) for i in data) if x]
    ignored = [x for x in issues if x["id"] not in sampled_ids]
    by_id = {it["id"]: it for it in items}

    def _with_snippets(issue):
        src = by_id.get(issue["id"])
        if src:
            issue["original"] = src["original"]
            issue["translation"] = src["translation"]
        return issue

    return [_with_snippets(x) for x in issues if x["id"] in sampled_ids], [
        _with_snippets(x) for x in ignored
    ]


def run_qa(job_id: str, api_key: str, client=None, model: str | None = None) -> dict:
    """Run QA on every translated chapter's sample. Per-chapter failures are
    recorded, not fatal — the rest of the report still stands."""
    from . import jobs

    model = model or translator.current_model()
    paths = jobs.job_paths(job_id)
    glossary = jobs.load_approved_glossary(job_id)
    prompt = QA_PROMPT_PATH.read_text(encoding="utf-8")
    if client is None:
        client = translator._make_client(api_key)

    report = {"chapters": {}, "total_issues": 0, "ignored_issues": [], "errors": []}
    for tpath in sorted(paths["chapters"].glob("*.translated.json")):
        data = json.loads(tpath.read_text(encoding="utf-8"))
        sample = sample_nodes(data["text_nodes"])
        if not sample:
            continue
        items = [
            {"id": n["id"], "original": n["original"], "translation": n["translation"]}
            for n in sample
        ]
        try:
            issues, ignored = asyncio.run(_qa_batch(client, model, prompt, items, glossary))
        except Exception as e:
            report["errors"].append({"chapter": data["chapter_id"], "error": str(e)})
            continue
        report["chapters"][data["chapter_id"]] = {"sampled": len(items), "issues": issues}
        report["total_issues"] += len(issues)
        report["ignored_issues"].extend(ignored)

    paths["qa_report"].write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report

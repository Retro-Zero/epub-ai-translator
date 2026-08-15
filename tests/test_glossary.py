"""Phase 3: glossary extraction/approval + full-book queue + progress.

All model calls are mocked (FakeDeepSeek). The queue's mid-run failure
survival and per-chapter retry are exercised with a fake that fails exactly
one chapter's nodes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import jobs  # noqa: E402
from app.glossary import extract_glossary, validate_glossary  # noqa: E402
from app.main import app  # noqa: E402
from app.translator import translate_chapter  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
TRANSLATION_PROMPT = (ROOT / "backend" / "app" / "translation_prompt.txt").read_text(encoding="utf-8")
GLOSSARY_PROMPT = (ROOT / "backend" / "app" / "glossary_prompt.txt").read_text(encoding="utf-8")

PROPOSED_TERMS = [
    {"original": "Major", "persian": "میجر", "category": "character", "note": "transliterated proper noun"},
    {"original": "Manor Farm", "persian": "مزرعه‌ی مانور", "category": "place", "note": "translated place name"},
]


class FakeCompletions:
    def __init__(self, mode="translate", fail_on=None):
        self.mode = mode
        self.fail_on = set(fail_on or [])
        self.calls = 0
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.mode == "glossary":
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(PROPOSED_TERMS)))]
            )
        content = kwargs["messages"][-1]["content"]
        data = json.loads(content)
        items = data["items"] if isinstance(data, dict) else data
        ids = [it["id"] for it in items]
        if any(i in self.fail_on for i in ids):
            payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in items]
            del payload[0]["id"]  # validation failure -> retry -> loud failure
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in items]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )


class FakeDeepSeek:
    def __init__(self, mode="translate", fail_on=None):
        self.chat = SimpleNamespace(completions=FakeCompletions(mode=mode, fail_on=fail_on))


def _make_job() -> str:
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes((FIXTURES / "synthetic.epub").read_bytes())
    jobs.run_pipeline(job_id)
    return job_id


def _approve_glossary(job_id, client, terms=None):
    terms = terms if terms is not None else PROPOSED_TERMS
    r = client.patch(f"/glossary/{job_id}", json={"glossary": terms})
    assert r.status_code == 200, r.text
    return r.json()


# --- glossary extraction ------------------------------------------------------


def test_extract_glossary_returns_terms():
    fake = FakeDeepSeek(mode="glossary")
    terms = extract_glossary("Chapter text with Major and Manor Farm.", GLOSSARY_PROMPT, client=fake)
    assert [t["original"] for t in terms] == ["Major", "Manor Farm"]
    assert all(t["category"] in {"character", "place", "term", "title", "other"} for t in terms)


def test_validate_glossary_rejects_bad_entries():
    ok, errors = validate_glossary(PROPOSED_TERMS)
    assert ok and not errors
    ok, errors = validate_glossary([{"original": "", "persian": "فا", "category": "nope"}])
    assert not ok
    assert any("original" in e for e in errors)
    assert any("category" in e for e in errors)
    ok, errors = validate_glossary("not a list")
    assert not ok


# --- glossary in translation payload ------------------------------------------


def test_translate_payload_includes_glossary():
    from app.textnodes import TextNode, ChapterData

    data = ChapterData(
        chapter_id="ch01",
        href="x.html",
        text_nodes=[TextNode(id="ch01_n0000", path=[0], text="Major locked the hen-houses.")],
    )
    fake = FakeDeepSeek(mode="translate")
    translate_chapter(data, TRANSLATION_PROMPT, client=fake, glossary={"Major": "میجر"})
    content = json.loads(fake.chat.completions.last_kwargs["messages"][-1]["content"])
    assert isinstance(content, dict)
    assert content["items"][0]["id"] == "ch01_n0000"
    assert content["glossary"]["Major"] == "میجر"


# --- endpoints ----------------------------------------------------------------


def test_extract_endpoint_saves_proposed_glossary(monkeypatch):
    job_id = _make_job()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="glossary"))
    r = TestClient(app).post(f"/glossary/{job_id}/extract")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "proposed"
    assert len(body["glossary"]) == 2
    saved = json.loads(jobs.job_paths(job_id)["glossary_proposed"].read_text(encoding="utf-8"))
    assert saved[0]["original"] == "Major"


def test_patch_glossary_endpoint_saves_approved(monkeypatch):
    job_id = _make_job()
    client = TestClient(app)
    _approve_glossary(job_id, client)
    saved = json.loads(jobs.job_paths(job_id)["glossary_approved"].read_text(encoding="utf-8"))
    assert saved[0]["original"] == "Major"


def test_patch_glossary_endpoint_rejects_invalid(monkeypatch):
    job_id = _make_job()
    r = TestClient(app).patch(f"/glossary/{job_id}", json={"glossary": [{"original": ""}]})
    assert r.status_code == 400


def test_translate_all_requires_approved_glossary(monkeypatch):
    job_id = _make_job()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="translate"))
    r = TestClient(app).post(f"/translate/{job_id}/all")
    assert r.status_code == 400
    assert "glossary" in r.json()["detail"].lower()


def test_translate_all_runs_all_chapters_and_survives_failure(monkeypatch):
    """GATE: one chapter's API failure must not corrupt the job — others
    finish, the failed one is marked failed, and is retryable."""
    job_id = _make_job()
    client = TestClient(app)
    _approve_glossary(job_id, client)

    ch03_ids = [n["id"] for n in json.loads(
        (jobs.job_paths(job_id)["chapters"] / "ch03.json").read_text(encoding="utf-8")
    )["text_nodes"]]
    fake = FakeDeepSeek(mode="translate", fail_on=ch03_ids)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: fake)

    r = client.post(f"/translate/{job_id}/all")
    assert r.status_code == 202, r.text

    status = client.get(f"/jobs/{job_id}/status").json()
    by_id = {c["id"]: c["status"] for c in status["chapters"]}
    assert by_id["ch01"] == "done"
    assert by_id["ch02"] == "done"
    assert by_id["ch03"] == "failed"
    assert status["running"] is False
    assert jobs.job_paths(job_id)["translated"].exists()
    # progress persisted to disk
    progress = json.loads(jobs.job_paths(job_id)["progress"].read_text(encoding="utf-8"))
    assert progress["chapters"]["ch03"] == "failed"


def test_retry_failed_chapter(monkeypatch):
    job_id = _make_job()
    client = TestClient(app)
    _approve_glossary(job_id, client)
    ch03_ids = [n["id"] for n in json.loads(
        (jobs.job_paths(job_id)["chapters"] / "ch03.json").read_text(encoding="utf-8")
    )["text_nodes"]]
    failing = FakeDeepSeek(mode="translate", fail_on=ch03_ids)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: failing)
    client.post(f"/translate/{job_id}/all")

    # now a healthy client retries only the failed chapter
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="translate"))
    r = client.post(f"/translate/{job_id}/chapter/ch03")
    assert r.status_code == 200, r.text
    status = client.get(f"/jobs/{job_id}/status").json()
    by_id = {c["id"]: c["status"] for c in status["chapters"]}
    assert by_id["ch03"] == "done"


def test_job_status_endpoint_reports_chapters_and_glossary(monkeypatch):
    job_id = _make_job()
    client = TestClient(app)
    _approve_glossary(job_id, client)
    body = client.get(f"/jobs/{job_id}/status").json()
    assert len(body["chapters"]) == 3
    assert body["glossary"]["approved"][0]["original"] == "Major"
    assert "translated_epub" in body

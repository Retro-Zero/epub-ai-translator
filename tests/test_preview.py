"""Phase 6: upload preview, chapter titles, translate-remaining semantics,
QA snippet enrichment (frontend spec: 5-screen flow)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import jobs  # noqa: E402
from app.main import app  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
EPUB = (FIXTURES / "synthetic.epub").read_bytes()


def _make_job() -> str:
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes(EPUB)
    jobs.run_pipeline(job_id)
    return job_id


def _approve_glossary(client, job_id):
    r = client.patch(
        f"/glossary/{job_id}",
        json={
            "glossary": [
                {"original": "Major", "persian": "میجر", "category": "character", "note": ""}
            ]
        },
    )
    assert r.status_code == 200, r.text


class _FailingCompletions:
    async def create(self, **kwargs):
        content = kwargs["messages"][-1]["content"]
        data = json.loads(content)
        items = data["items"] if isinstance(data, dict) else data
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in items]
        del payload[0]["id"]  # validation failure -> retry -> loud failure
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


class _FailingDeepSeek:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FailingCompletions())


class _TranslateCompletions:
    async def create(self, **kwargs):
        content = kwargs["messages"][-1]["content"]
        data = json.loads(content)
        items = data["items"] if isinstance(data, dict) else data
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in items]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


class _TranslateDeepSeek:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_TranslateCompletions())


# --- /preview -----------------------------------------------------------------


def test_preview_returns_metadata_without_creating_job():
    before = set(jobs.DATA_DIR.iterdir()) if jobs.DATA_DIR.exists() else set()
    r = TestClient(app).post(
        "/preview", files={"file": ("book.epub", EPUB, "application/epub+zip")}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "book.epub"
    assert body["size"] == len(EPUB)
    assert body["title"] == "Synthetic Fixture"
    assert body["chapter_count"] == 3
    assert len(body["chapters"]) == 3
    assert all(c["text_nodes"] > 0 for c in body["chapters"])
    after = set(jobs.DATA_DIR.iterdir()) if jobs.DATA_DIR.exists() else set()
    assert after == before  # no job was created


def test_preview_rejects_non_epub():
    r = TestClient(app).post("/preview", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_preview_rejects_corrupt_zip():
    r = TestClient(app).post("/preview", files={"file": ("bad.epub", b"PK\x03\x04not-a-zip", "application/epub+zip")})
    assert r.status_code == 422


# --- chapter titles ------------------------------------------------------------


def test_pipeline_records_chapter_titles():
    job_id = _make_job()
    report = json.loads(jobs.job_paths(job_id)["report"].read_text(encoding="utf-8"))
    titles = {c["id"]: c.get("title", "") for c in report["chapters"]}
    assert titles["ch01"]  # body heading or <title>
    assert all(isinstance(t, str) for t in titles.values())


# --- translate-remaining semantics ---------------------------------------------


def test_translate_all_skips_already_done_chapters(monkeypatch):
    job_id = _make_job()
    client = TestClient(app)
    _approve_glossary(client, job_id)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    # ch01 done via the single-chapter endpoint
    monkeypatch.setattr("app.translator._make_client", lambda api_key: _TranslateDeepSeek())
    r = client.post(f"/translate/{job_id}/chapter/ch01")
    assert r.status_code == 200, r.text

    # now a full run with a client that fails EVERYTHING: ch01 must be
    # skipped (still done), only the remaining chapters are attempted
    monkeypatch.setattr("app.translator._make_client", lambda api_key: _FailingDeepSeek())
    r = client.post(f"/translate/{job_id}/all")
    assert r.status_code == 202, r.text

    status = client.get(f"/jobs/{job_id}/status").json()
    by_id = {c["id"]: c["status"] for c in status["chapters"]}
    assert by_id["ch01"] == "done"  # preserved — not re-translated
    assert by_id["ch02"] == "failed"
    assert by_id["ch03"] == "failed"


# --- QA snippets ---------------------------------------------------------------


class _QaCompletions:
    async def create(self, **kwargs):
        content = kwargs["messages"][-1]["content"]
        data = json.loads(content)
        items = data["items"]
        issues = [
            {
                "id": items[0]["id"],
                "issue_type": "fluency",
                "description": "reads awkwardly",
                "suggested_fix": "جمله بهتر",
            }
        ]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(issues)))])


class _QaDeepSeek:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_QaCompletions())


def test_qa_issues_include_original_and_translation_snippets(monkeypatch):
    job_id = _make_job()
    client = TestClient(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: _TranslateDeepSeek())
    client.post(f"/translate/{job_id}/chapter/ch01")

    monkeypatch.setattr("app.translator._make_client", lambda api_key: _QaDeepSeek())
    r = client.post(f"/qa/{job_id}")
    assert r.status_code == 202, r.text
    body = client.get(f"/qa/{job_id}").json()
    issues = body["report"]["chapters"]["ch01"]["issues"]
    assert issues, "expected at least one flagged issue"
    it = issues[0]
    assert it["original"] and it["translation"]
    assert it["issue_type"] and it["suggested_fix"]

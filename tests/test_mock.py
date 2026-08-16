"""Mock/sandbox mode: full pipeline with ZERO API calls (no cost).

The whole flow — glossary extract, translate, QA, finalize — must run
deterministically against an in-process fake when settings.mock_mode is on,
so the UI can be tested freely. Every output is visibly marked as test data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import app.settings as settings_mod  # noqa: E402
from app import jobs  # noqa: E402
from app.main import app  # noqa: E402
from app.mockai import MockCompletions, MOCK_PREFIX  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
EPUB = (FIXTURES / "synthetic.epub").read_bytes()
TRANSLATION_PROMPT = (ROOT / "backend" / "app" / "translation_prompt.txt").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _mock_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "STORE_PATH", tmp_path / "settings.json")
    settings_mod.save_settings({"mock_mode": True})
    yield
    settings_mod.save_settings({"mock_mode": False})


def _mock_client():
    from app.translator import _make_client

    return _make_client(api_key="")

# --- mock client shapes ------------------------------------------------------


def test_mock_translation_payload_marks_output():
    items = [{"id": "n1", "text": "Hello world."}, {"id": "n2", "text": "Second sentence."}]
    c = MockCompletions()
    import asyncio

    resp = asyncio.run(
        c.create(model="x", messages=[{"role": "system", "content": TRANSLATION_PROMPT}, {"role": "user", "content": json.dumps(items)}])
    )
    data = json.loads(resp.choices[0].message.content)
    assert [d["id"] for d in data] == ["n1", "n2"]
    assert data[0]["translation"].startswith(MOCK_PREFIX)
    assert resp.usage.prompt_tokens >= 0  # fake usage keeps the cost UI alive


def test_mock_glossary_returns_valid_terms():
    from app.glossary import extract_glossary, validate_glossary
    from app.mockai import MockCompletions

    text = "Once upon a time there was a village with farmers and animals everywhere."
    terms = extract_glossary(text, "prompt", client=_mock_client())
    ok, errors = validate_glossary(terms)
    assert ok, errors
    assert terms  # deterministic non-empty


def test_mock_qa_returns_scripted_issues():
    from app import qa
    from app.mockai import MockCompletions
    import asyncio

    items = [
        {"id": "n1", "original": "Hello.", "translation": "سلام."},
        {"id": "n2", "original": "Goodbye.", "translation": "خداحافظ."},
    ]
    issues, ignored = asyncio.run(qa._qa_batch(_mock_client(), "m", "qa prompt", items, None))
    assert issues, "mock QA must produce at least one issue to exercise the review UI"
    assert all(i["id"] in {"n1", "n2"} and i["issue_type"] in qa.ISSUE_TYPES for i in issues)
    assert all(i.get("original") and i.get("suggested_fix") for i in issues)


def test_mock_titles_translation():
    from app.finalize import translate_titles

    out = translate_titles([{"id": "t", "text": "The Silent Patient"}], "prompt", api_key="", client=_mock_client())
    assert out["t"].startswith(MOCK_PREFIX)


# --- end-to-end mock book (the cost-free test path) ---------------------------


def test_full_mock_book_flow_without_api():
    """The user's request: test the WHOLE app with zero spend. Upload ->
    glossary extract -> approve -> translate all -> status -> finalize ->
    download, all against the mock client. No DEEPSEEK_API_KEY needed."""
    client = TestClient(app)
    r = client.post("/upload", files={"file": ("book.epub", EPUB, "application/epub+zip")})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    # glossary via mock
    r = client.post(f"/glossary/{job_id}/extract")
    assert r.status_code == 200, r.text
    terms = r.json()["glossary"]
    assert terms, "mock glossary must propose terms"
    r = client.patch(f"/glossary/{job_id}", json={"glossary": terms})
    assert r.status_code == 200, r.text

    # translate the whole book (background) via mock
    r = client.post(f"/translate/{job_id}/all")
    assert r.status_code == 202, r.text
    status = client.get(f"/jobs/{job_id}/status").json()
    by_id = {c["id"]: c["status"] for c in status["chapters"]}
    assert all(v == "done" or v == "skipped" for v in by_id.values())
    assert status["mock_mode"] is True

    # QA via mock
    r = client.post(f"/qa/{job_id}")
    assert r.status_code == 202, r.text
    body = client.get(f"/qa/{job_id}").json()
    assert body["report"]["total_issues"] >= 1

    # finalize via mock (no API key configured at all)
    r = client.post(f"/finalize/{job_id}", json={"translate_title": True})
    assert r.status_code == 200, r.text

    d = client.get(f"/download/{job_id}")
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/epub+zip"


def test_no_api_key_needed_in_mock_mode(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(app)
    s = client.get("/settings").json()
    assert s["mock_mode"] is True
    assert s["provider_configured"] is True  # mock counts as configured


def test_sample_epub_endpoint():
    r = TestClient(app).get("/sample")
    assert r.status_code == 200
    assert r.content.startswith(b"PK\x03\x04")

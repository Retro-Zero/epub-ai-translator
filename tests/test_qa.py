"""Phase 4: QA/consistency review + finalization (metadata, RTL, font, TOC).

All model calls mocked (FakeDeepSeek). Finalization is tested against the
synthetic fixture epub (which now carries dc:creator/dc:publisher so the
keep-author-by-default rule is observable).
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import jobs  # noqa: E402
from app.main import app  # noqa: E402
from app.qa import sample_nodes  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class FakeCompletions:
    def __init__(self, mode="translate"):
        self.mode = mode
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        content = kwargs["messages"][-1]["content"]
        data = json.loads(content)
        items = data["items"] if isinstance(data, dict) else data
        if self.mode == "qa":
            issues = []
            if items:
                it = items[0]
                issues = [{
                    "id": it["id"],
                    "issue_type": "fluency",
                    "description": "reads awkwardly",
                    "suggested_fix": "فا" + it["translation"],
                }]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(issues)))]
            )
        if self.mode == "titles":
            out = [{"id": it["id"], "translation": "ف" + it["text"]} for it in items]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(out)))]
            )
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in items]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )


class FakeDeepSeek:
    def __init__(self, mode="translate"):
        self.chat = SimpleNamespace(completions=FakeCompletions(mode=mode))


def _make_translated_job(monkeypatch) -> str:
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes((FIXTURES / "synthetic.epub").read_bytes())
    jobs.run_pipeline(job_id)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="translate"))
    client = TestClient(app)
    client.post(f"/translate/{job_id}/chapter/ch01")
    return job_id


def _zip_read(path, name):
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


def _finalize(job_id, client, **opts):
    return client.post(f"/finalize/{job_id}", json=opts or {})


# --- sampling ------------------------------------------------------------------


def test_sample_nodes_takes_10_to_15_percent():
    nodes = [{"id": f"n{i}"} for i in range(100)]
    sample = sample_nodes(nodes)
    assert 10 <= len(sample) <= 15
    assert sample_nodes([{"id": "a"}, {"id": "b"}])  # tiny lists still sample >= 1
    # deterministic
    assert sample_nodes(nodes) == sample_nodes(nodes)


# --- QA endpoint ---------------------------------------------------------------


def test_qa_endpoint_runs_and_persists_report(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="qa"))
    r = TestClient(app).post(f"/qa/{job_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_issues"] >= 1
    report = json.loads(jobs.job_paths(job_id)["qa_report"].read_text(encoding="utf-8"))
    assert report["chapters"]["ch01"]["sampled"] >= 1


def test_qa_reports_only_translated_chapters(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="qa"))
    r = TestClient(app).post(f"/qa/{job_id}")
    chapters = r.json()["chapters"]
    assert set(chapters) == {"ch01"}  # only the translated one


def test_put_qa_fixes_persists_and_validates(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    client = TestClient(app)
    ok = client.put(f"/qa/{job_id}/fixes", json={"fixes": {"ch01_n0000": "جمله اصلاح‌شده"}})
    assert ok.status_code == 200
    fixes = json.loads(jobs.job_paths(job_id)["qa_corrections"].read_text(encoding="utf-8"))
    assert fixes["ch01_n0000"] == "جمله اصلاح‌شده"
    bad = client.put(f"/qa/{job_id}/fixes", json={"fixes": {"ch99_n0000": "x"}})
    assert bad.status_code == 400


# --- finalize ------------------------------------------------------------------


def test_finalize_sets_language_and_rtl_on_html_and_body(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    client = TestClient(app)
    r = _finalize(job_id, client)
    assert r.status_code == 200, r.text

    final = jobs.job_paths(job_id)["final"]
    assert final.exists()
    opf_name = _opf_path(final)
    opf = _zip_read(final, opf_name).decode("utf-8")
    assert "<dc:language>fa</dc:language>" in opf

    html = _zip_read(final, "OEBPS/text/chapter1.xhtml").decode("utf-8")
    assert re.search(r'<html[^>]*dir="rtl"[^>]*lang="fa"', html) or re.search(
        r'<html[^>]*lang="fa"[^>]*dir="rtl"', html
    )
    assert re.search(r'<body[^>]*dir="rtl"', html)


def test_finalize_injects_font_and_css(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    _finalize(job_id, TestClient(app))
    final = jobs.job_paths(job_id)["final"]
    names = zipfile.ZipFile(final).namelist()
    assert any("Vazirmatn-Regular.woff2" in n for n in names)
    assert any("OFL" in n for n in names)
    css = _zip_read(final, "OEBPS/style.css").decode("utf-8")
    assert "Vazirmatn" in css and "@font-face" in css


def test_finalize_applies_qa_fixes(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    client = TestClient(app)
    client.put(f"/qa/{job_id}/fixes", json={"fixes": {"ch01_n0000": "جمله اصلاح‌شده"}})
    _finalize(job_id, client)
    html = _zip_read(jobs.job_paths(job_id)["final"], "OEBPS/text/chapter1.xhtml").decode("utf-8")
    assert "جمله اصلاح‌شده" in html


def test_finalize_translates_toc_and_title(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="titles"))
    _finalize(job_id, TestClient(app))
    final = jobs.job_paths(job_id)["final"]
    ncx = _zip_read(final, "OEBPS/toc.ncx").decode("utf-8")
    assert "فOne" in ncx and "فThree" in ncx
    opf = _zip_read(final, _opf_path(final)).decode("utf-8")
    assert "فSynthetic Fixture" in opf  # translated title


def test_finalize_keeps_author_and_publisher_by_default(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="titles"))
    _finalize(job_id, TestClient(app))
    opf = _zip_read(jobs.job_paths(job_id)["final"], _opf_path(jobs.job_paths(job_id)["final"])).decode("utf-8")
    assert "A. Test Author" in opf
    assert "Test Press" in opf


def test_finalize_requires_translated_chapter(monkeypatch):
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes((FIXTURES / "synthetic.epub").read_bytes())
    jobs.run_pipeline(job_id)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    r = TestClient(app).post(f"/finalize/{job_id}", json={})
    assert r.status_code == 422


def test_download_serves_final_epub(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    client = TestClient(app)
    _finalize(job_id, client)
    r = client.get(f"/download/{job_id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    assert zipfile.ZipFile(__import__("io").BytesIO(r.content)).namelist()


def _opf_path(epub_path) -> str:
    with zipfile.ZipFile(epub_path) as zf:
        container = zf.read("META-INF/container.xml").decode("utf-8")
    import re as _re
    return _re.search(r'full-path="([^"]+)"', container).group(1)


import re  # noqa: E402  (used by test_finalize_sets_language_and_rtl_on_html_and_body)

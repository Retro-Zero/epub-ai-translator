"""BYOK settings + usage tracking tests (Phase 5).

All model calls are mocked. Settings persist to a tmp path (never the real
data/settings.json). Covers: store roundtrip with key masking, provider
presets (deepseek vs openai/custom — thinking-disabled is deepseek-only),
connection test endpoint, translator config resolution, per-chapter token
usage capture, and the enriched /status payload (title, usage, cost).
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

import app.settings as settings_mod  # noqa: E402
from app import jobs, translator  # noqa: E402
from app.main import app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PROMPT_PATH = ROOT / "backend" / "app" / "translation_prompt.txt"


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "STORE_PATH", tmp_path / "settings.json")


def _fake_with_usage(calls=0):
    class _Completions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            req = json.loads(kwargs["messages"][-1]["content"])
            payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            )

    c = _Completions()
    c.calls = calls
    return SimpleNamespace(chat=SimpleNamespace(completions=c))


def _make_job() -> str:
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes((FIXTURES / "synthetic.epub").read_bytes())
    jobs.run_pipeline(job_id)
    return job_id


# --- settings store ------------------------------------------------------------


def test_put_get_settings_roundtrip_masks_key():
    client = TestClient(app)
    r = client.put(
        "/settings",
        json={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "sk-test-1234567890abcdef",
            "price_in_per_m": 0.28,
            "price_out_per_m": 1.1,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key_present"] is True
    assert body["api_key_masked"].endswith("cdef")
    assert "api_key" not in body  # never returned in full

    g = client.get("/settings")
    assert g.status_code == 200
    got = g.json()
    assert got["model"] == "deepseek-v4-flash"
    assert got["price_in_per_m"] == 0.28
    assert got["api_key_present"] is True
    assert got["api_key_masked"].endswith("cdef")
    assert "provider_configured" in got


def test_put_without_key_keeps_existing():
    client = TestClient(app)
    client.put("/settings", json={"api_key": "sk-keep-this-key-secret"})
    client.put("/settings", json={"model": "some-other-model"})
    got = client.get("/settings").json()
    assert got["model"] == "some-other-model"
    assert got["api_key_present"] is True
    assert got["api_key_masked"].endswith("cret")


def test_clear_api_key_removes_it():
    client = TestClient(app)
    client.put("/settings", json={"api_key": "sk-temp-key-value"})
    client.put("/settings", json={"clear_api_key": True})
    got = client.get("/settings").json()
    assert got["api_key_present"] is False
    assert got["api_key_masked"] == ""


def test_provider_presets_set_base_url_and_thinking_flag():
    client = TestClient(app)
    r = client.put("/settings", json={"provider": "openai", "model": "gpt-4o-mini"})
    assert r.status_code == 200
    got = client.get("/settings").json()
    assert got["base_url"] == "https://api.openai.com/v1"
    assert got["disable_thinking"] is False

    r = client.put("/settings", json={"provider": "deepseek", "model": "deepseek-v4-flash"})
    got = client.get("/settings").json()
    assert got["base_url"] == "https://api.deepseek.com"
    assert got["disable_thinking"] is True


def test_custom_provider_keeps_given_base_url():
    client = TestClient(app)
    r = client.put(
        "/settings",
        json={"provider": "custom", "base_url": "http://127.0.0.1:11434/v1", "model": "llama3"},
    )
    assert r.status_code == 200
    got = client.get("/settings").json()
    assert got["base_url"] == "http://127.0.0.1:11434/v1"
    assert got["disable_thinking"] is False


def test_gemini_preset_uses_openai_compat_endpoint():
    client = TestClient(app)
    r = client.put("/settings", json={"provider": "gemini", "model": "gemini-2.5-flash"})
    assert r.status_code == 200
    got = client.get("/settings").json()
    assert got["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert got["disable_thinking"] is False  # no deepseek-only param


class _FakeHttp:
    """models endpoint 404s -> falls back to a minimal chat completion."""

    def __init__(self):
        self.get_calls = 0
        self.post_calls = 0

    def get(self, url, headers=None, timeout=None):
        self.get_calls += 1
        raise RuntimeError("404 models endpoint")

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_calls += 1

        def _raise():
            return None

        return SimpleNamespace(
            status_code=200, raise_for_status=_raise, json=lambda: {"id": "ping", "choices": [{}]}
        )


def test_connection_falls_back_to_minimal_completion(monkeypatch):
    http = _FakeHttp()
    out = settings_mod.test_connection(
        "https://api.deepseek.com", "sk-x", model="deepseek-v4-flash", http=http
    )
    assert out["ok"] is True
    assert http.get_calls == 1
    assert http.post_calls == 1


def test_settings_test_endpoint(monkeypatch):
    monkeypatch.setattr(
        settings_mod,
        "test_connection",
        lambda base_url, api_key, **kw: {"ok": True, "models": ["m1", "m2"]},
    )
    client = TestClient(app)
    r = client.post("/settings/test", json={"base_url": "https://api.deepseek.com", "api_key": "sk-x"})
    assert r.status_code == 200, r.text
    assert r.json()["models"] == ["m1", "m2"]


def test_settings_test_endpoint_failure(monkeypatch):
    def boom(base_url, api_key, **kw):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr(settings_mod, "test_connection", boom)
    client = TestClient(app)
    r = client.post("/settings/test", json={"base_url": "https://api.deepseek.com", "api_key": "bad"})
    assert r.status_code == 502
    assert "401" in r.json()["detail"]


# --- translator config resolution -----------------------------------------------


def test_translator_resolves_model_and_thinking_from_settings():
    client = TestClient(app)
    client.put("/settings", json={"provider": "deepseek", "model": "deepseek-v4-flash"})
    assert translator.current_model() == "deepseek-v4-flash"
    assert translator.extra_body() == translator.THINKING_DISABLED

    client.put("/settings", json={"provider": "openai", "model": "gpt-4o-mini"})
    assert translator.current_model() == "gpt-4o-mini"
    assert translator.extra_body() is None  # openai/custom: no deepseek-only param


def test_usage_captured_in_translation_report():
    from app.textnodes import TextNode, extract_chapter
    from app.parser import parse_epub

    book = parse_epub(FIXTURES / "synthetic.epub")
    ch = book.chapters[0]
    data = extract_chapter(ch.content, ch.id, ch.href)
    fake = _fake_with_usage()
    result = translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)
    usage = result.report["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["calls"] == len(translator.build_batches(data.text_nodes))


# --- enriched status payload -----------------------------------------------------


def test_status_includes_title_usage_and_cost(monkeypatch):
    job_id = _make_job()
    client = TestClient(app)
    client.put(
        "/settings",
        json={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "sk-test-usage-key",
            "price_in_per_m": 1.0,
            "price_out_per_m": 1.0,
        },
    )
    monkeypatch.setattr("app.translator._make_client", lambda api_key: _fake_with_usage())

    r = client.post(f"/translate/{job_id}/chapter/ch01")
    assert r.status_code == 200, r.text

    s = client.get(f"/jobs/{job_id}/status").json()
    assert s["title"] == "Synthetic Fixture"
    assert s["usage"]["prompt_tokens"] > 0
    assert s["usage"]["completion_tokens"] > 0
    assert s["usage"]["calls"] >= 1
    assert s["estimated_cost"] > 0  # 1.0 per 1M tokens * (100+50) tokens per batch
    assert s["provider_configured"] is True

    stats = json.loads(jobs.job_paths(job_id)["stats"].read_text(encoding="utf-8"))
    assert "ch01" in stats["chapters"]
    assert stats["totals"]["calls"] >= 1


def test_provider_not_configured_flag(monkeypatch):
    job_id = _make_job()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    client = TestClient(app)
    s = client.get(f"/jobs/{job_id}/status").json()
    assert s["provider_configured"] is False

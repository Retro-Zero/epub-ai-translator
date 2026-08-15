"""Phase 1: translation pipeline tests.

All model calls are mocked (FakeDeepSeek) — no real API, no cost.
The real end-to-end run happens manually with a live DEEPSEEK_API_KEY.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import jobs, translator  # noqa: E402
from app.main import app  # noqa: E402
from app.textnodes import TextNode, extract_chapter  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PROMPT_PATH = ROOT / "backend" / "app" / "translation_prompt.txt"


# --- fake Anthropic client ---------------------------------------------------


class FakeCompletions:
    """Mimics AsyncOpenAI.chat.completions.create; `mode` picks the failure shape."""

    def __init__(self, mode="valid", fail_first=0):
        self.mode = mode
        self.fail_first = fail_first
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        req = json.loads(kwargs["messages"][-1]["content"])
        if self.calls <= self.fail_first:
            payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
            payload[0]["id"] = "WRONG_ID"
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        if self.mode == "invalid_json":
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="this is not json at all"))])
        if self.mode == "missing_id":
            payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
            del payload[0]["id"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        if self.mode == "null_translation":
            payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
            payload[1]["translation"] = None
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        if self.mode == "short":
            payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload[:-1])))])
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


class FakeDeepSeek:
    def __init__(self, mode="valid", fail_first=0):
        self.chat = SimpleNamespace(completions=FakeCompletions(mode=mode, fail_first=fail_first))


def _synthetic_chapter():
    from app.parser import parse_epub

    book = parse_epub(FIXTURES / "synthetic.epub")
    ch = book.chapters[0]
    return ch, extract_chapter(ch.content, ch.id, ch.href)


def _node(text, i=0):
    return TextNode(id=f"n{i:04d}", path=[0, i], text=text)


# --- batching -----------------------------------------------------------------


def test_build_batches_respects_node_limit():
    nodes = [_node(f"text {i}", i) for i in range(120)]
    batches = translator.build_batches(nodes, max_nodes=50, max_tokens=2000)
    assert [len(b) for b in batches] == [50, 50, 20]


def test_build_batches_respects_token_limit():
    long_text = "word " * 500  # ~2000 chars -> ~500 tokens each
    nodes = [_node(long_text, i) for i in range(6)]
    batches = translator.build_batches(nodes, max_nodes=50, max_tokens=2000)
    assert all(sum(translator.estimate_tokens(n.text) for n in b) <= 2000 for b in batches)
    assert len(batches) >= 2  # token limit forced a split


# --- response validation ------------------------------------------------------


def test_validate_response_ok():
    ids = ["a", "b", "c"]
    data = [{"id": "a", "translation": "فا"}, {"id": "b", "translation": "فب"}, {"id": "c", "translation": "فج"}]
    ok, errors = translator.validate_response(ids, data)
    assert ok and not errors


def test_validate_response_rejects_missing_id():
    data = [{"id": "a", "translation": "فا"}, {"translation": "فب"}]
    ok, errors = translator.validate_response(["a", "b"], data)
    assert not ok
    assert any("missing translation" in e or "id" in e for e in errors)


def test_validate_response_rejects_null_and_empty():
    data = [
        {"id": "a", "translation": None},
        {"id": "b", "translation": "  "},
        {"id": "c", "translation": "فج"},
    ]
    ok, errors = translator.validate_response(["a", "b", "c"], data)
    assert not ok
    assert any("null" in e for e in errors)
    assert any("empty" in e for e in errors)


def test_validate_response_rejects_count_mismatch_and_order():
    ok, errors = translator.validate_response(["a", "b"], [{"id": "a", "translation": "فا"}])
    assert not ok and any("count mismatch" in e for e in errors)
    ok, errors = translator.validate_response(
        ["a", "b"],
        [{"id": "b", "translation": "فب"}, {"id": "a", "translation": "فا"}],
    )
    assert not ok and any("order" in e for e in errors)


# --- translation flow ---------------------------------------------------------


def test_translate_chapter_retries_once_then_succeeds():
    _, data = _synthetic_chapter()
    fake = FakeDeepSeek(mode="valid", fail_first=1)
    result = translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)
    assert fake.chat.completions.calls == 2  # first attempt failed, one retry
    assert result.report["retries"] == 1
    assert result.report["nodes"] == len(data.text_nodes)
    assert result.report["changed"] == result.report["nodes"]
    assert all(n.text.startswith("فا") for n in result.chapter.text_nodes)


def test_translate_chapter_fails_loudly_with_node_ids():
    _, data = _synthetic_chapter()
    fake = FakeDeepSeek(mode="short")  # always returns one item too few
    with pytest.raises(translator.TranslationError) as exc:
        translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)
    expected_ids = {n.id for n in data.text_nodes}
    # the systematic short-responder keeps shedding nodes each retry pass,
    # so the raised ids are the still-pending subset — loud, scoped, non-empty
    assert exc.value.failing_ids
    assert set(exc.value.failing_ids) <= expected_ids


def test_translate_chapter_fails_loudly_on_malformed_json():
    _, data = _synthetic_chapter()
    fake = FakeDeepSeek(mode="invalid_json")
    with pytest.raises(translator.TranslationError):
        translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)


class _ProbeCompletions:
    """Counts concurrent in-flight calls; verifies the batch semaphore caps
    concurrency (a chapter's batches must not all fire at once)."""

    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def create(self, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        req = json.loads(kwargs["messages"][-1]["content"])
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in req]
        self.active -= 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def test_batch_concurrency_is_capped():
    """300 nodes -> 6 batches. Without a semaphore all 6 would fire at once;
    with MAX_CONCURRENT_BATCHES the peak must stay at or below the cap."""
    nodes = [_node(f"text {i}", i) for i in range(300)]
    data = _synthetic_chapter()[1]
    data.text_nodes = nodes
    probe = _ProbeCompletions()
    fake = SimpleNamespace(chat=SimpleNamespace(completions=probe))
    result = translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)
    assert result.report["batches"] == 6
    assert 2 <= probe.max_active <= translator.MAX_CONCURRENT_BATCHES


# --- empty-translation resilience ----------------------------------------------
# Live failure mode: deepseek-v4-flash returns "" for specific nodes (even
# plain sentences), deterministically. A single empty must not kill the
# chapter — the node keeps its original text, the rest translates.


class _EmptiesCompletions:
    """Returns "" for `empty_ids` on every call; translates everything else."""

    def __init__(self, empty_ids):
        self.empty_ids = set(empty_ids)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        req = json.loads(kwargs["messages"][-1]["content"])
        items = req["items"] if isinstance(req, dict) else req
        payload = []
        for it in items:
            if it["id"] in self.empty_ids:
                payload.append({"id": it["id"], "translation": ""})
            else:
                payload.append({"id": it["id"], "translation": "فا" + it["text"]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def test_empty_translations_keep_original_and_do_not_fail_chapter():
    """The exact live failure: model returns "" for 2 nodes in a batch, on
    every attempt. The chapter must still translate — those 2 keep English."""
    data = _synthetic_chapter()[1]  # ch01: 17 nodes, 1 batch
    empty_ids = {data.text_nodes[3].id, data.text_nodes[11].id}
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=_EmptiesCompletions(empty_ids))
    )
    result = translator.translate_chapter(
        data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake
    )
    assert result.report["kept_original"] == 2
    assert result.report["nodes"] == 17
    by_id = {n.id: n.text for n in result.chapter.text_nodes}
    for nid in empty_ids:
        assert by_id[nid] == next(n.text for n in data.text_nodes if n.id == nid)  # English kept
    assert all(
        by_id[n.id].startswith("فا")
        for n in data.text_nodes
        if n.id not in empty_ids
    )


def test_null_translation_still_fails_loudly():
    """None is a corrupt response, not an empty quirk — stays a hard failure."""
    data = _synthetic_chapter()[1]
    fake = FakeDeepSeek(mode="null_translation")
    with pytest.raises(translator.TranslationError):
        translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)


class _SubsetCompletions:
    """Stable short-responder: always drops the SAME fixed item (like the live
    ch03 failure: 49 of 50, stably). The missing node must keep its original
    text and the rest must translate on the next pass."""

    def __init__(self):
        self.target = None

    async def create(self, **kwargs):
        req = json.loads(kwargs["messages"][-1]["content"])
        items = req["items"] if isinstance(req, dict) else req
        if self.target is None:
            self.target = items[0]["id"]
        payload = [
            {"id": it["id"], "translation": "فا" + it["text"]}
            for it in items
            if it["id"] != self.target
        ]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def test_clean_subset_missing_node_keeps_original():
    """The live ch03 failure mode: model returns 49 of 50 items, stably.
    The missing node keeps English; the chapter succeeds."""
    data = _synthetic_chapter()[1]
    first_id = data.text_nodes[0].id
    fake = SimpleNamespace(chat=SimpleNamespace(completions=_SubsetCompletions()))
    result = translator.translate_chapter(
        data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake
    )
    assert result.report["kept_original"] == 1
    by_id = {n.id: n.text for n in result.chapter.text_nodes}
    assert by_id[first_id] == data.text_nodes[0].text  # English kept
    assert all(
        by_id[n.id].startswith("فا") for n in data.text_nodes if n.id != first_id
    )


class _ReorderCompletions:
    """Same items, shuffled order — genuine corruption, must fail loudly."""

    async def create(self, **kwargs):
        req = json.loads(kwargs["messages"][-1]["content"])
        items = req["items"] if isinstance(req, dict) else req
        payload = [{"id": it["id"], "translation": "فا" + it["text"]} for it in reversed(items)]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def test_reordered_response_still_fails_loudly():
    data = _synthetic_chapter()[1]
    fake = SimpleNamespace(chat=SimpleNamespace(completions=_ReorderCompletions()))
    with pytest.raises(translator.TranslationError):
        translator.translate_chapter(data, PROMPT_PATH.read_text(encoding="utf-8"), client=fake)


def test_prompt_file_exists_and_nonempty():
    assert PROMPT_PATH.exists()
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert len(text) > 500
    assert "OUTPUT FORMAT" in text and "translation" in text


# --- endpoint ----------------------------------------------------------------


def _make_job():
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes((FIXTURES / "synthetic.epub").read_bytes())
    jobs.run_pipeline(job_id)
    return job_id


def test_translate_endpoint_translates_chapter(monkeypatch):
    job_id = _make_job()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek(mode="valid"))
    client = TestClient(app)

    r = client.post(f"/translate/{job_id}/chapter/ch01")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "translated"
    assert body["report"]["nodes"] > 0
    assert body["report"]["changed"] == body["report"]["nodes"]
    assert body["report"]["integrity"]["well_formed"] is True
    assert body["report"]["integrity"]["structure_preserved"] is True

    paths = jobs.job_paths(job_id)
    assert paths["translated"].exists()
    assert paths["chapters"].joinpath("ch01.translated.json").exists()

    d = client.get(f"/download/{job_id}")
    assert d.status_code == 200
    assert d.headers["content-type"] == "application/epub+zip"


def test_translate_endpoint_404_for_unknown_chapter(monkeypatch):
    job_id = _make_job()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = TestClient(app)
    r = client.post(f"/translate/{job_id}/chapter/ch99")
    assert r.status_code == 404


def test_translate_endpoint_rejects_bad_chapter_id(monkeypatch):
    job_id = _make_job()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = TestClient(app)
    r = client.post(f"/translate/{job_id}/chapter/ch01_extra")
    assert r.status_code == 400

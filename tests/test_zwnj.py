"""Bug #5: Persian half-space (ZWNJ) normalization of model output.

The model occasionally drops نیم‌فاصله in compounds (می‌شود → میشود). The
normalization pass must restore it WITHOUT corrupting valid text: words that
legitimately start with می (میز، میوه، میل، میدان، میراث), the ن negative
prefix (نشده), the silent-ه ezâfe (همهی → all forms), English text, and
already-correct text must all pass through byte-identical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import jobs, zwnj  # noqa: E402
from app.zwnj import normalize_half_spaces  # noqa: E402

Z = "\u200c"


# --- dictionary compounds ------------------------------------------------------


def test_restores_mi_verb_compounds():
    assert normalize_half_spaces("او میشود برود") == f"او می{Z}شود برود"
    assert normalize_half_spaces("میکند و میگوید") == f"می{Z}کند و می{Z}گوید"
    assert normalize_half_spaces("میرفتند") == f"می{Z}رفتند"


def test_mi_rule_covers_verb_forms_not_in_dictionary():
    # شدم isn't a dictionary key — the می+verb whitelist must handle it
    assert normalize_half_spaces("من میشدم") == f"من می{Z}شدم"
    assert normalize_half_spaces("میشنیدند") == f"می{Z}شنیدند"


def test_restores_be_preposition_compounds():
    assert normalize_half_spaces("بهعنوان نمونه") == f"به{Z}عنوان نمونه"
    assert normalize_half_spaces("بهدلیل") == f"به{Z}دلیل"


def test_restores_plural_and_participle_compounds():
    assert normalize_half_spaces("کتابها") == f"کتاب{Z}ها"
    assert normalize_half_spaces("فصلهای") == f"فصل{Z}های"
    assert normalize_half_spaces("انجامشده") == f"انجام{Z}شده"
    assert normalize_half_spaces("اعمالشدهی") == f"اعمال{Z}شدهی"  # the user's example


# --- safety: never corrupt -----------------------------------------------------


def test_does_not_touch_words_that_start_with_mi_but_are_not_verbs():
    for word in ["میز", "میوه", "میل", "میدان", "میراث", "میخ", "میزبان"]:
        assert normalize_half_spaces(word) == word, f"corrupted {word!r}"


def test_does_not_touch_negative_prefix_or_silent_he():
    for word in ["نشده", "نرفته", "نکرد", "همهی", "خانهی", "ماهی"]:
        assert normalize_half_spaces(word) == word, f"corrupted {word!r}"


def test_does_not_fire_inside_longer_words():
    # کتابها must not fire inside کتابهایم (ها followed by یم)
    assert normalize_half_spaces("کتابهایم") == "کتابهایم"
    # میشود must not fire inside میشودن (not a real word, but guard anyway)
    assert normalize_half_spaces("میشودن") == "میشودن"


def test_english_and_ascii_pass_through():
    assert normalize_half_spaces("Hello world 123!") == "Hello world 123!"
    assert normalize_half_spaces("") == ""


def test_already_correct_text_is_unchanged():
    good = f"او می{Z}شود و کتاب{Z}ها را می{Z}خواند"
    assert normalize_half_spaces(good) == good


def test_idempotent_second_pass_is_noop():
    once = normalize_half_spaces("او میشود و کتابها را میخواند")
    assert normalize_half_spaces(once) == once
    assert once.count(Z) == 3


def test_real_kafka_output_stays_correct():
    """The actual model output from the real-API quality test — 15 ZWNJ
    already correct, the pass must not change a single byte."""
    samples = [
        "یک روز صبح، وقتی گرگور زامزا از خواب‌های ناآرام بیدار شد، خود را در بسترش به حشره‌ای غول‌پیکر تبدیل‌شده یافت.",
        "پاهای بی‌شمارش که در مقایسه با بقیه‌ی حجم بدنش به طرز رقت‌باری باریک بودند، با درماندگی جلوی چشمانش تکان می‌خوردند.",
    ]
    for s in samples:
        assert normalize_half_spaces(s) == s


def test_apply_corrections_normalizes_model_fixes(monkeypatch):
    """QA suggested fixes are model output too — ZWNJ-normalized on apply."""
    from app.finalize import apply_corrections
    from app.textnodes import ChapterData, TextNode

    data = ChapterData(
        chapter_id="ch01",
        href="text/chapter1.xhtml",
        text_nodes=[TextNode(id="n1", path=["/p"], text="اصل")],
    )
    out = apply_corrections(data, {"n1": "این یک جمله میشود"})
    assert out.text_nodes[0].text == f"این یک جمله می{Z}شود"


# --- integration through the translator ----------------------------------------


def _make_translated_job(monkeypatch) -> str:
    from types import SimpleNamespace

    class FakeCompletions:
        async def create(self, **kwargs):
            req = json.loads(kwargs["messages"][-1]["content"])
            items = req.get("items", req) if isinstance(req, dict) else req
            payload = [
                {"id": it["id"], "translation": "این یک جمله میشود"}
                for it in items
            ]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    class FakeDeepSeek:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    from app.main import app
    from fastapi.testclient import TestClient

    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes(
        (ROOT / "tests" / "fixtures" / "synthetic.epub").read_bytes()
    )
    jobs.run_pipeline(job_id)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.translator._make_client", lambda api_key: FakeDeepSeek())
    client = TestClient(app)
    r = client.post(f"/translate/{job_id}/chapter/ch01")
    assert r.status_code == 200, r.text
    return job_id


def test_translated_chapter_file_has_normalized_text(monkeypatch):
    job_id = _make_translated_job(monkeypatch)
    data = json.loads(
        (jobs.job_paths(job_id)["chapters"] / "ch01.translated.json").read_text(encoding="utf-8")
    )
    texts = [n["translation"] for n in data["text_nodes"]]
    assert all(f"می{Z}شود" in t for t in texts), texts[:1]
    assert "میشود" not in " ".join(texts)

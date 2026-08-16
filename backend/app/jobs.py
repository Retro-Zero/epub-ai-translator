"""Filesystem job store + pipeline orchestration. No database (v1, single-user).

Layout: data/jobs/<job_id>/{input.epub, chapters/*.json, rebuilt.epub,
translated.epub, report.json, progress.json, glossary_*.json}
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from . import translator
from .parser import parse_epub
from .progress import ProgressTracker, DONE, FAILED, IN_PROGRESS, SKIPPED
from .rebuild import rebuild_epub
from .textnodes import ChapterData, TextNode, chapter_title, extract_chapter, rebuild_chapter
from .verify import verify_roundtrip, verify_translated_chapter

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "jobs"


def _job_dir(job_id: str) -> Path:
    return DATA_DIR / job_id


def job_paths(job_id: str) -> dict:
    d = _job_dir(job_id)
    return {
        "dir": d,
        "input": d / "input.epub",
        "rebuilt": d / "rebuilt.epub",
        "translated": d / "translated.epub",
        "chapters": d / "chapters",
        "report": d / "report.json",
        "translated_report": d / "translated_report.json",
        "progress": d / "progress.json",
        "glossary_proposed": d / "glossary_proposed.json",
        "glossary_approved": d / "glossary_approved.json",
        "qa_report": d / "qa_report.json",
        "qa_corrections": d / "qa_corrections.json",
        "qa_progress": d / "qa_progress.json",
        "final": d / "final.epub",
        "stats": d / "stats.json",
    }


def create_job(job_id: str | None = None) -> str:
    job_id = job_id or uuid.uuid4().hex[:12]
    _job_dir(job_id).mkdir(parents=True, exist_ok=True)
    return job_id


def run_pipeline(job_id: str) -> dict:
    """Parse -> extract (identity) -> rebuild -> verify. Writes all artifacts."""
    paths = job_paths(job_id)
    paths["chapters"].mkdir(exist_ok=True)

    book = parse_epub(paths["input"])

    rebuilt = {}
    chapters_meta = []
    for ch in book.chapters:
        data = extract_chapter(ch.content, ch.id, ch.href)
        (paths["chapters"] / f"{ch.id}.json").write_text(
            json.dumps(
                {
                    "chapter_id": data.chapter_id,
                    "href": data.href,
                    "text_nodes": [
                        {"id": n.id, "path": n.path, "text": n.text} for n in data.text_nodes
                    ],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        rebuilt[ch.href] = rebuild_chapter(ch.content, data)  # identity round-trip
        chapters_meta.append(
            {
                "id": ch.id,
                "href": ch.href,
                "text_nodes": len(data.text_nodes),
                "title": chapter_title(ch.content),
            }
        )

    rebuild_epub(book, rebuilt, paths["rebuilt"])

    report = verify_roundtrip(paths["input"], paths["rebuilt"], [ch.href for ch in book.chapters])
    report["chapters"] = chapters_meta
    report["title"] = book.title
    (paths["report"]).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def run_external(epub_path, job_id: str | None = None) -> dict:
    """Run the round-trip on an arbitrary epub file (demo CLI, fixtures)."""
    job_id = create_job(job_id)
    shutil.copyfile(epub_path, job_paths(job_id)["input"])
    return run_pipeline(job_id)


# --- chapter data helpers ------------------------------------------------------


def load_chapter_file(path: Path) -> ChapterData:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = [
        TextNode(id=item["id"], path=item["path"], text=item["text"])
        for item in payload["text_nodes"]
    ]
    return ChapterData(chapter_id=payload["chapter_id"], href=payload["href"], text_nodes=nodes)


def load_translated_file(path: Path) -> ChapterData:
    """Translated chapter JSON ({id, path, original, translation}) -> ChapterData
    whose node texts are the translations (for rebuilding the epub)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = [
        TextNode(id=item["id"], path=item["path"], text=item["translation"])
        for item in payload["text_nodes"]
    ]
    return ChapterData(chapter_id=payload["chapter_id"], href=payload["href"], text_nodes=nodes)


def first_content_chapter_id(job_id: str, min_nodes: int = 15) -> str | None:
    """First chapter with real content (>= min_nodes text nodes), falling
    back to the first chapter with any nodes (skips title/cover/colophon
    pages that carry no story text)."""
    paths = job_paths(job_id)
    fallback = None
    for path in sorted(paths["chapters"].glob("ch*.json")):
        if path.name.endswith(".translated.json"):
            continue
        data = load_chapter_file(path)
        if not data.text_nodes:
            continue
        if fallback is None:
            fallback = data.chapter_id
        if len(data.text_nodes) >= min_nodes:
            return data.chapter_id
    return fallback


def chapter_text_for(job_id: str, chapter_id: str) -> str:
    data = load_chapter_file(job_paths(job_id)["chapters"] / f"{chapter_id}.json")
    return "\n".join(n.text for n in data.text_nodes)


def load_approved_glossary(job_id: str) -> dict | None:
    """Approved glossary as {original: persian}, or None if not approved."""
    path = job_paths(job_id)["glossary_approved"]
    if not path.exists():
        return None
    terms = json.loads(path.read_text(encoding="utf-8"))
    return {t["original"]: t["persian"] for t in terms}


def persist_translated(job_id: str, data: ChapterData, result) -> None:
    """Persist EN/FA pairs for a translated chapter (glossary review screen)."""
    path = job_paths(job_id)["chapters"] / f"{data.chapter_id}.translated.json"
    path.write_text(
        json.dumps(
            {
                "chapter_id": data.chapter_id,
                "href": data.href,
                "text_nodes": [
                    {"id": n.id, "path": n.path, "original": n.text, "translation": t.text}
                    for n, t in zip(data.text_nodes, result.chapter.text_nodes)
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def rebuild_translated_epub(job_id: str) -> Path:
    """Rezip input.epub with every translated chapter swapped in (RTL)."""
    paths = job_paths(job_id)
    book = parse_epub(paths["input"])
    swapped = {}
    for ch in book.chapters:
        tpath = paths["chapters"] / f"{ch.id}.translated.json"
        if tpath.exists():
            data = load_translated_file(tpath)
            swapped[ch.href] = rebuild_chapter(ch.content, data, rtl=True)
    rebuild_epub(book, swapped, paths["translated"])
    return paths["translated"]


# --- translation ----------------------------------------------------------------


def load_stats(job_id: str) -> dict:
    """Per-chapter token usage: {"chapters": {ch: usage}, "totals": {...}}.
    Totals accumulate across calls (retries cost real tokens too)."""
    path = job_paths(job_id)["stats"]
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("chapters", {})
        data.setdefault("totals", {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
        return data
    return {"chapters": {}, "totals": {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}}


def record_usage(job_id: str, chapter_id: str, usage: dict) -> None:
    stats = load_stats(job_id)
    stats["chapters"][chapter_id] = usage
    for key in ("prompt_tokens", "completion_tokens", "calls"):
        stats["totals"][key] = stats["totals"].get(key, 0) + usage.get(key, 0)
    job_paths(job_id)["stats"].write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def translate_one(job_id: str, chapter_id: str, api_key: str,
                  client=None) -> dict:
    """Translate one chapter with the approved glossary (if any), persist it,
    and rebuild the translated epub. Returns the report dict."""
    paths = job_paths(job_id)
    data = load_chapter_file(paths["chapters"] / f"{chapter_id}.json")
    glossary = load_approved_glossary(job_id)
    prompt = translator.DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
    result = translator.translate_chapter(
        data, prompt, api_key=api_key, client=client, glossary=glossary
    )
    persist_translated(job_id, data, result)
    record_usage(job_id, chapter_id, result.report.get("usage") or {})

    book = parse_epub(paths["input"])
    orig = next((c.content for c in book.chapters if c.href == result.chapter.href), None)
    if orig is None:
        raise ValueError(f"chapter href {result.chapter.href!r} not in original epub")
    rebuilt = rebuild_chapter(orig, result.chapter, rtl=True)
    integrity = verify_translated_chapter(orig, rebuilt)
    rebuild_translated_epub(job_id)
    return {**result.report, "integrity": integrity}


def run_full_book(job_id: str, api_key: str, client=None) -> None:
    """Translate every chapter in spine order, persisting per-chapter status.
    A failing chapter is marked failed and the job continues (GATE: the job
    must survive a mid-run failure; failed chapters retry individually).
    Chapters already DONE are skipped — "translate remaining" semantics, so
    a run never pays to re-translate finished chapters."""
    paths = job_paths(job_id)
    tracker = ProgressTracker(paths["progress"])
    book = parse_epub(paths["input"])
    chapter_ids = [c.id for c in book.chapters]

    tracker.ensure_init(chapter_ids)  # respect existing states (done stays done)
    tracker.set_running(True)
    try:
        for ch in book.chapters:
            data = load_chapter_file(paths["chapters"] / f"{ch.id}.json")
            if not data.text_nodes:
                tracker.set(ch.id, SKIPPED)
                continue
            if tracker.get()["chapters"].get(ch.id) == DONE:
                continue  # already translated — don't redo it
            tracker.set(ch.id, IN_PROGRESS)
            try:
                translate_one(job_id, ch.id, api_key, client=client)
                tracker.set(ch.id, DONE)
            except Exception:
                tracker.set(ch.id, FAILED)  # keep going; retryable individually
    finally:
        tracker.set_running(False)

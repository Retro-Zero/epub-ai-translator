"""FastAPI app.

Phase 0: upload -> extract -> rebuild (identity) -> download.
Phase 1: single-chapter translation (DeepSeek, RTL rebuild).
Phase 3: glossary extraction/approval, full-book queue, progress tracking.
Frontend: plain HTML/JS served from backend/static/.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import finalize, glossary, jobs, qa, settings as settings_mod, translator
from .progress import ProgressTracker, DONE, FAILED, IN_PROGRESS

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="EPUB AI Translator", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ZIP_MAGIC = b"PK\x03\x04"
CHAPTER_ID_RE = re.compile(r"ch\d+")

REPORT_KEYS = (
    "pass",
    "entries_match",
    "untouched_entries_byte_identical",
    "chapters_well_formed",
    "chapters_text_equal",
    "mimetype_stored",
    "chapter_count",
)


def _read_json(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _api_key() -> str:
    """BYOK: settings key first, env fallback (existing deployments).
    Mock/sandbox mode needs no key at all."""
    if settings_mod.mock_enabled():
        return ""
    cfg = settings_mod.load_settings()
    key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise HTTPException(500, "No AI provider key configured — add one in Settings")
    return key


def _require_job(job_id: str) -> None:
    if not jobs.job_paths(job_id)["report"].exists():
        raise HTTPException(404, "job not found")


# --- health / upload / download ------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sample")
def sample_epub():
    """The synthetic sample book (generated, safe to redistribute) — one click
    of cost-free testing in the UI, no upload needed."""
    path = Path(__file__).resolve().parent.parent / "assets" / "sample-book.epub"
    if not path.exists():
        raise HTTPException(404, "sample book not bundled")
    return FileResponse(path, media_type="application/epub+zip", filename="sample-book.epub")


# --- BYOK settings --------------------------------------------------------------


@app.get("/settings")
def get_settings():
    return settings_mod.public_settings()


@app.put("/settings")
def put_settings(payload: dict = Body(...)):
    try:
        settings_mod.save_settings(payload)
    except Exception as e:
        raise HTTPException(400, f"invalid settings: {e}") from e
    return settings_mod.public_settings()


@app.post("/settings/test")
def test_settings(payload: dict = Body(...)):
    if settings_mod.mock_enabled():
        return {"ok": True, "models": ["mock"], "via": "mock"}
    cfg = settings_mod.load_settings()
    base_url = str(payload.get("base_url") or "").strip() or cfg.get("base_url", "")
    api_key = str(payload.get("api_key") or "").strip() or cfg.get("api_key", "")
    model = str(payload.get("model") or "").strip() or cfg.get("model", "")
    if not base_url or not api_key:
        raise HTTPException(400, "base_url and api_key are required (or save settings first)")
    try:
        return settings_mod.test_connection(base_url, api_key, model=model)
    except Exception as e:
        raise HTTPException(502, f"connection failed: {e}") from e


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    if not name.endswith(".epub"):
        raise HTTPException(400, "only .epub files are accepted")
    data = await file.read()
    if not data.startswith(ZIP_MAGIC):
        raise HTTPException(400, "file is not a zip/EPUB container")

    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes(data)
    try:
        report = jobs.run_pipeline(job_id)
    except Exception as e:
        raise HTTPException(422, f"could not process EPUB: {e}") from e

    return {"job_id": job_id, "status": "ready", "report": _summary(report)}


@app.post("/preview")
async def preview(file: UploadFile = File(...)):
    """Parse an epub WITHOUT creating a job — metadata + per-chapter node
    counts for the upload screen's pre-commit confirmation."""
    import shutil
    import tempfile

    name = (file.filename or "").lower()
    if not name.endswith(".epub"):
        raise HTTPException(400, "only .epub files are accepted")
    data = await file.read()
    if not data.startswith(ZIP_MAGIC):
        raise HTTPException(400, "file is not a zip/EPUB container")

    tmp = Path(tempfile.mkdtemp(prefix="epub-preview-"))
    try:
        src = tmp / "book.epub"
        src.write_bytes(data)
        book = jobs.parse_epub(src)
        chapters = []
        for ch in book.chapters:
            extracted = jobs.extract_chapter(ch.content, ch.id, ch.href)
            chapters.append(
                {
                    "id": ch.id,
                    "text_nodes": len(extracted.text_nodes),
                    "title": jobs.chapter_title(ch.content),
                }
            )
        return {
            "filename": file.filename or "",
            "size": len(data),
            "title": book.title,
            "chapter_count": len(chapters),
            "chapters": chapters,
        }
    except Exception as e:
        raise HTTPException(422, f"could not parse EPUB: {e}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    _require_job(job_id)
    paths = jobs.job_paths(job_id)
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    translated = _translated_chapters(job_id)
    return {
        "job_id": job_id,
        "status": "ready",
        "title": report.get("title", ""),
        "chapters": report.get("chapters", []),
        "translated_chapters": translated,
        "report": _summary(report),
    }


@app.get("/jobs/{job_id}/status")
def job_progress(job_id: str):
    _require_job(job_id)
    paths = jobs.job_paths(job_id)
    tracker = ProgressTracker(paths["progress"])
    progress = tracker.get()
    chapters_map = progress.get("chapters")
    if not chapters_map:  # no translation started yet — show the full inventory as pending
        report = json.loads(paths["report"].read_text(encoding="utf-8"))
        chapters_map = {c["id"]: "pending" for c in report.get("chapters", [])}
    chapters = [{"id": cid, "status": st} for cid, st in chapters_map.items()]
    cfg = settings_mod.load_settings()
    totals = jobs.load_stats(job_id)["totals"]
    est_cost = (
        totals["prompt_tokens"] / 1e6 * (cfg["price_in_per_m"] or 0)
        + totals["completion_tokens"] / 1e6 * (cfg["price_out_per_m"] or 0)
    )
    report = _read_json(paths["report"]) or {}
    return {
        "job_id": job_id,
        "running": bool(progress.get("running")),
        "title": report.get("title", ""),
        "mock_mode": settings_mod.mock_enabled(),
        "chapters": chapters,
        "glossary": {
            "proposed": _read_json(paths["glossary_proposed"]),
            "approved": _read_json(paths["glossary_approved"]),
        },
        "translated_chapters": _translated_chapters(job_id),
        "translated_epub": paths["translated"].exists(),
        "final_epub": paths["final"].exists(),
        "qa": _read_json(paths["qa_progress"]) or {"running": False, "done": 0, "total": 0},
        "usage": totals,
        "estimated_cost": round(est_cost, 6),
        "provider_configured": bool(
            cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
        ),
        "updated_at": progress.get("updated_at"),
    }


@app.get("/download/{job_id}")
def download(job_id: str):
    paths = jobs.job_paths(job_id)
    target = (
        paths["final"] if paths["final"].exists()
        else paths["translated"] if paths["translated"].exists()
        else paths["rebuilt"]
    )
    if not target.exists():
        raise HTTPException(404, "job not found or not ready")
    return FileResponse(target, media_type="application/epub+zip", filename=f"{job_id}.epub")


# --- QA / finalize ---------------------------------------------------------------


@app.post("/qa/{job_id}", status_code=202)
def run_qa(job_id: str, background_tasks: BackgroundTasks):
    _require_job(job_id)
    paths = jobs.job_paths(job_id)
    qa_progress = _read_json(paths["qa_progress"]) or {}
    if qa_progress.get("running"):
        raise HTTPException(409, "a QA pass is already running for this job")
    api_key = _api_key()
    background_tasks.add_task(qa.run_qa, job_id, api_key)
    return {"job_id": job_id, "status": "started"}


@app.get("/qa/{job_id}")
def get_qa(job_id: str):
    _require_job(job_id)
    paths = jobs.job_paths(job_id)
    return {
        "job_id": job_id,
        "report": _read_json(paths["qa_report"]) or {},
        "fixes": _read_json(paths["qa_corrections"]) or {},
    }


@app.put("/qa/{job_id}/fixes")
def put_qa_fixes(job_id: str, payload: dict = Body(...)):
    _require_job(job_id)
    fixes = payload.get("fixes") or {}
    if not isinstance(fixes, dict):
        raise HTTPException(400, "fixes must be a {node_id: corrected_text} object")
    known = set()
    for tpath in jobs.job_paths(job_id)["chapters"].glob("*.translated.json"):
        data = json.loads(tpath.read_text(encoding="utf-8"))
        known.update(n["id"] for n in data["text_nodes"])
    unknown = [k for k in fixes if k not in known]
    if unknown:
        raise HTTPException(400, f"unknown node ids: {', '.join(sorted(unknown)[:20])}")
    jobs.job_paths(job_id)["qa_corrections"].write_text(
        json.dumps(fixes, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"job_id": job_id, "fixes": fixes, "count": len(fixes)}


@app.post("/finalize/{job_id}")
def finalize_job(job_id: str, payload: dict = Body(default={})):
    _require_job(job_id)
    api_key = _api_key()
    try:
        result = finalize.build_final_epub(
            job_id,
            api_key,
            translate_title=bool(payload.get("translate_title", True)),
            translate_author=bool(payload.get("translate_author", False)),
            translate_publisher=bool(payload.get("translate_publisher", False)),
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"finalize failed: {e}") from e
    return {"job_id": job_id, **result}


# --- glossary -------------------------------------------------------------------


@app.post("/glossary/{job_id}/extract")
def extract_glossary(job_id: str):
    _require_job(job_id)
    chapter_id = jobs.first_content_chapter_id(job_id)
    if not chapter_id:
        raise HTTPException(422, "no chapter with extractable text content")
    api_key = _api_key()
    text = jobs.chapter_text_for(job_id, chapter_id)
    prompt = glossary.GLOSSARY_PROMPT_PATH.read_text(encoding="utf-8")
    try:
        terms = glossary.extract_glossary(text, prompt, api_key=api_key)
    except glossary.GlossaryError as e:
        raise HTTPException(502, f"glossary extraction failed: {e}") from e
    except Exception as e:
        raise HTTPException(502, f"glossary extraction failed: {e}") from e

    paths = jobs.job_paths(job_id)
    paths["glossary_proposed"].write_text(
        json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"job_id": job_id, "status": "proposed", "chapter_used": chapter_id, "glossary": terms}


@app.patch("/glossary/{job_id}")
def update_glossary(job_id: str, payload: dict = Body(...)):
    _require_job(job_id)
    terms = payload.get("glossary")
    ok, errors = glossary.validate_glossary(terms)
    if not ok:
        raise HTTPException(400, "invalid glossary: " + "; ".join(errors[:5]))
    paths = jobs.job_paths(job_id)
    paths["glossary_approved"].write_text(
        json.dumps(terms, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"job_id": job_id, "approved": True, "glossary": terms}


# --- translation ----------------------------------------------------------------


def _translated_chapters(job_id: str) -> list:
    paths = jobs.job_paths(job_id)
    if not paths["chapters"].exists():
        return []
    return sorted(
        p.name[: -len(".translated.json")] for p in paths["chapters"].glob("*.translated.json")
    )


@app.post("/translate/{job_id}/chapter/{chapter_id}")
def translate_chapter(job_id: str, chapter_id: str):
    if not CHAPTER_ID_RE.fullmatch(chapter_id):
        raise HTTPException(400, "chapter id must look like ch01")
    _require_job(job_id)
    paths = jobs.job_paths(job_id)
    src = paths["chapters"] / f"{chapter_id}.json"
    if not src.exists():
        raise HTTPException(404, f"chapter {chapter_id} not found (upload the epub first)")
    api_key = _api_key()

    tracker = ProgressTracker(paths["progress"])
    book = jobs.parse_epub(paths["input"])
    tracker.ensure_init([c.id for c in book.chapters])
    tracker.set(chapter_id, IN_PROGRESS)
    try:
        report = jobs.translate_one(job_id, chapter_id, api_key)
    except translator.TranslationError as e:
        tracker.set(chapter_id, FAILED)
        reason = str(e)
        if len(reason) > 200:
            reason = reason[:197] + "..."
        detail = f"translation validation failed ({reason})"
        if e.failing_ids:
            detail += f" for nodes: {', '.join(sorted(e.failing_ids)[:20])}"
        raise HTTPException(502, detail) from e
    except Exception as e:
        tracker.set(chapter_id, FAILED)
        raise HTTPException(502, f"translation failed: {e}") from e
    tracker.set(chapter_id, DONE)

    paths["translated_report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"job_id": job_id, "chapter_id": chapter_id, "status": "translated", "report": report}


@app.post("/translate/{job_id}/all", status_code=202)
def translate_all(job_id: str, background_tasks: BackgroundTasks):
    _require_job(job_id)
    paths = jobs.job_paths(job_id)
    if not paths["glossary_approved"].exists():
        raise HTTPException(400, "approve a glossary first (PATCH /glossary/{job_id})")
    tracker = ProgressTracker(paths["progress"])
    if tracker.get().get("running"):
        raise HTTPException(409, "a full-book translation is already running")
    api_key = _api_key()
    background_tasks.add_task(jobs.run_full_book, job_id, api_key)
    return {"job_id": job_id, "status": "started"}


# --- summary / static ------------------------------------------------------------


def _summary(report: dict) -> dict:
    return {k: report[k] for k in REPORT_KEYS if k in report}


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

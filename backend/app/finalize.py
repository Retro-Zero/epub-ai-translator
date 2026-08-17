"""Finalization: apply QA corrections, Persian metadata, RTL html/body,
embedded Vazirmatn font (SIL OFL 1.1 — redistribution permitted, license
file included), translated TOC labels, translated OPF title.

Produces data/jobs/<job_id>/final.epub — everything else copied verbatim.
"""
from __future__ import annotations

import asyncio
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import jobs, translator
from .textnodes import ChapterData, TextNode, rebuild_chapter
from .zwnj import normalize_half_spaces

TITLES_PROMPT_PATH = Path(__file__).with_name("titles_prompt.txt")
ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_FILENAME = "Vazirmatn-Regular.woff2"
FONT_STACK = '"Vazirmatn", "Geeza Pro", "Segoe UI", Tahoma, sans-serif'

DC_NS = "http://purl.org/dc/elements/1.1/"


def _local(tag: str) -> str:
    return tag.split("}")[-1]


# --- corrections ---------------------------------------------------------------


def apply_corrections(chapter_data: ChapterData, corrections: dict) -> ChapterData:
    if not corrections:
        return chapter_data
    # corrections are model output too — restore dropped half-spaces (bug #5)
    nodes = [
        TextNode(
            id=n.id,
            path=n.path,
            text=normalize_half_spaces(corrections.get(n.id, n.text)),
        )
        for n in chapter_data.text_nodes
    ]
    return ChapterData(chapter_id=chapter_data.chapter_id, href=chapter_data.href, text_nodes=nodes)


# --- font css -------------------------------------------------------------------


def font_css_block(rel_url: str) -> bytes:
    return f"""
@font-face {{
  font-family: "Vazirmatn";
  src: url("{rel_url}") format("woff2");
  font-weight: 400;
  font-style: normal;
}}
body {{
  font-family: {FONT_STACK};
  direction: rtl;
}}
""".encode("utf-8")


def inject_font_css(css_bytes: bytes, css_name: str, font_entry: str) -> bytes:
    rel = posixpath.relpath(font_entry, start=posixpath.dirname(css_name))
    return css_bytes + font_css_block(rel)


# --- OPF / NCX ------------------------------------------------------------------


def _parse_opf(opf_bytes: bytes) -> ET.Element:
    return ET.fromstring(opf_bytes)


def opf_fields(opf_bytes: bytes) -> dict:
    root = _parse_opf(opf_bytes)
    fields = {"title": None, "creator": None, "publisher": None, "ncx": None}
    manifest = {}
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "title" and fields["title"] is None:
            fields["title"] = (el.text or "").strip()
        elif tag == "creator" and fields["creator"] is None:
            fields["creator"] = (el.text or "").strip()
        elif tag == "publisher" and fields["publisher"] is None:
            fields["publisher"] = (el.text or "").strip()
        elif tag == "item":
            mt = el.attrib.get("media-type", "")
            href = el.attrib.get("href")
            if mt == "application/x-dtbncx+xml" and href:
                fields["ncx"] = href
    return fields


def update_opf(opf_bytes: bytes, lang: str, replacements: dict) -> bytes:
    root = _parse_opf(opf_bytes)
    applied = set()
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "language":
            el.text = lang
        elif tag in replacements and replacements[tag] and el.text and tag not in applied:
            el.text = replacements[tag]
            applied.add(tag)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def ncx_labels(ncx_bytes: bytes) -> list:
    root = ET.fromstring(ncx_bytes)
    labels = []
    nav_i = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "docTitle":
            for t in el.iter():
                if _local(t.tag) == "text" and t.text:
                    labels.append({"id": "toc_doc", "text": t.text.strip()})
        elif tag == "navLabel":
            for t in el.iter():
                if _local(t.tag) == "text" and t.text:
                    labels.append({"id": f"toc_{nav_i}", "text": t.text.strip()})
            nav_i += 1
    return labels


def update_ncx(ncx_bytes: bytes, label_map: dict) -> bytes:
    root = ET.fromstring(ncx_bytes)
    doc_done = False
    i = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "docTitle" and not doc_done:
            for t in el.iter():
                if _local(t.tag) == "text" and t.text and "toc_doc" in label_map:
                    t.text = label_map["toc_doc"]
            doc_done = True
        elif tag == "navLabel":
            for t in el.iter():
                if _local(t.tag) == "text" and t.text and f"toc_{i}" in label_map:
                    t.text = label_map[f"toc_{i}"]
            i += 1
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# --- titles translation ----------------------------------------------------------


async def _titles_call(client, model: str, prompt: str, items: list) -> dict:
    payload = [{"id": it["id"], "text": it["text"]} for it in items]
    resp = await client.chat.completions.create(
        model=model,
        max_tokens=4096,
        extra_body=translator.THINKING_DISABLED,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    raw = resp.choices[0].message.content or ""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        raise ValueError("titles response contained no JSON array")
    data = json.loads(m.group(0))
    wanted = {it["id"] for it in items}
    return {item["id"]: item["translation"] for item in data if item.get("id") in wanted}


def translate_titles(items: list, prompt: str, api_key: str | None = None,
                     client=None, model: str = translator.DEFAULT_MODEL) -> dict:
    if client is None:
        if not api_key and not translator.settings_mod.mock_enabled():
            raise ValueError("DEEPSEEK_API_KEY is required")
        client = translator._make_client(api_key)
    return asyncio.run(_titles_call(client, model, prompt, items))


# --- final build ------------------------------------------------------------------


def build_final_epub(job_id: str, api_key: str, translate_title: bool = True,
                     translate_author: bool = False, translate_publisher: bool = False,
                     client=None) -> dict:
    paths = jobs.job_paths(job_id)
    if not list(paths["chapters"].glob("*.translated.json")):
        raise ValueError("no translated chapters to finalize")

    book = jobs.parse_epub(paths["input"])
    opf_dir = posixpath.dirname(book.opf_path)
    opf_bytes = next(d for n, d, _ in book.entries if n == book.opf_path)

    corrections = {}
    if paths["qa_corrections"].exists():
        corrections = json.loads(paths["qa_corrections"].read_text(encoding="utf-8"))

    prompt = TITLES_PROMPT_PATH.read_text(encoding="utf-8")
    fields = opf_fields(opf_bytes)
    title_items = []
    if translate_title and fields["title"]:
        title_items.append({"id": "title", "text": fields["title"]})
    if translate_author and fields["creator"]:
        title_items.append({"id": "creator", "text": fields["creator"]})
    if translate_publisher and fields["publisher"]:
        title_items.append({"id": "publisher", "text": fields["publisher"]})
    replacements = {}
    if title_items:
        replacements = translate_titles(title_items, prompt, api_key=api_key, client=client)

    # chapters with corrections + RTL (html/body)
    rebuilt = {}
    for ch in book.chapters:
        tpath = paths["chapters"] / f"{ch.id}.translated.json"
        if not tpath.exists():
            continue
        data = apply_corrections(jobs.load_translated_file(tpath), corrections)
        rebuilt[ch.href] = rebuild_chapter(ch.content, data, rtl=True)

    font_exists = (ASSETS / FONT_FILENAME).exists()
    font_entry_name = posixpath.join(opf_dir, "fonts", FONT_FILENAME)

    entries = []
    for name, data, ctype in book.entries:
        if name in rebuilt:
            entries.append((name, rebuilt[name], ctype))
        elif name.endswith(".css") and font_exists:
            entries.append((name, inject_font_css(data, name, font_entry_name), ctype))
        else:
            entries.append((name, data, ctype))

    if font_exists:
        entries.append((font_entry_name, (ASSETS / FONT_FILENAME).read_bytes(), zipfile.ZIP_DEFLATED))
        ofl = ASSETS / "OFL.txt"
        if ofl.exists():
            entries.append((posixpath.join(opf_dir, "fonts", "OFL.txt"), ofl.read_bytes(), zipfile.ZIP_DEFLATED))

    # OPF: language fa + translated fields
    new_opf = update_opf(opf_bytes, "fa", replacements)
    entries = [(n, new_opf if n == book.opf_path else d, c) for n, d, c in entries]

    # NCX: translated TOC labels
    if fields["ncx"]:
        ncx_name = posixpath.normpath(posixpath.join(opf_dir, fields["ncx"]))
        ncx_bytes = next((d for n, d, _ in entries if n == ncx_name), None)
        if ncx_bytes is not None:
            labels = ncx_labels(ncx_bytes)
            if labels:
                label_map = translate_titles(labels, prompt, api_key=api_key, client=client)
                new_ncx = update_ncx(ncx_bytes, label_map)
                entries = [(n, new_ncx if n == ncx_name else d, c) for n, d, c in entries]

    with zipfile.ZipFile(paths["final"], "w") as zout:
        for name, data, ctype in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = ctype
            zout.writestr(info, data)

    return {
        "status": "finalized",
        "final_epub": str(paths["final"]),
        "title": replacements.get("title"),
        "language": "fa",
        "font": FONT_FILENAME if font_exists else None,
        "notes": {
            "author": fields["creator"],
            "publisher": fields["publisher"],
            "author_translated": bool(replacements.get("creator")),
            "publisher_translated": bool(replacements.get("publisher")),
        },
    }

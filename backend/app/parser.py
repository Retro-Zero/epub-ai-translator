"""EPUB container parsing: container.xml -> OPF -> manifest/spine.

Uses ebooklib for the EPUB model (project stack) and stdlib zipfile +
ElementTree as the authoritative source for href -> zip-entry resolution
(ebooklib's item names are not always zip-resolvable as-is).
"""
from __future__ import annotations

import logging
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import ebooklib
from ebooklib import epub

log = logging.getLogger(__name__)

XHTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}


@dataclass
class Chapter:
    id: str  # ch01, ch02, ... (spine order, 1-based)
    href: str  # zip entry path of the chapter file
    spine_index: int
    media_type: str
    content: bytes


@dataclass
class Book:
    chapters: list  # [Chapter, ...] in spine order
    entries: list  # (name, data, compress_type) verbatim from the original zip
    opf_path: str
    spine_idrefs: list
    title: str = ""


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _find_rootfile(zf: zipfile.ZipFile) -> str:
    if "META-INF/container.xml" not in zf.namelist():
        raise ValueError("not a valid EPUB: missing META-INF/container.xml")
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    for el in root.iter():
        if _local(el.tag) == "rootfile":
            full = el.attrib.get("full-path")
            if full:
                return full
    raise ValueError("not a valid EPUB: container.xml has no rootfile")


def parse_epub(path) -> Book:
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        entries = [(i.filename, zf.read(i.filename), i.compress_type) for i in zf.infolist()]

        opf_path = _find_rootfile(zf)
        if opf_path not in names:
            raise ValueError(f"container.xml points to missing OPF: {opf_path!r}")
        opf_dir = posixpath.dirname(opf_path)
        root = ET.fromstring(zf.read(opf_path))

        manifest = {}  # id -> (zip entry path, media type)
        for el in root.iter():
            if _local(el.tag) == "item":
                iid = el.attrib.get("id")
                href = el.attrib.get("href")
                mt = el.attrib.get("media-type", "")
                if iid and href:
                    manifest[iid] = (posixpath.normpath(posixpath.join(opf_dir, href)), mt)

        spine_idrefs = [
            el.attrib["idref"]
            for el in root.iter()
            if _local(el.tag) == "itemref" and el.attrib.get("idref")
        ]
        if not spine_idrefs:
            raise ValueError("EPUB has an empty spine")

        title = ""
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "title" and el.text and el.text.strip():
                title = el.text.strip()
                break

        chapters = []
        for idx, idref in enumerate(spine_idrefs, start=1):
            if idref not in manifest:
                log.warning("spine idref %r missing from manifest; skipping", idref)
                continue
            href, media_type = manifest[idref]
            if media_type not in XHTML_MEDIA_TYPES:
                continue
            if href.rsplit(".", 1)[-1].lower() in {"svg", "xml"}:
                continue
            if href not in names:
                log.warning("chapter %r not present in zip; skipping", href)
                continue
            chapters.append(
                Chapter(
                    id=f"ch{idx:02d}",
                    href=href,
                    spine_index=idx,
                    media_type=media_type,
                    content=zf.read(href),
                )
            )

    # Cross-check spine order with ebooklib when possible (stack compliance;
    # the stdlib parse above stays authoritative).
    try:
        book = epub.read_epub(str(path))
        lib_spine = [idref for idref, _ in (book.spine or [])]
        if lib_spine and lib_spine != spine_idrefs:
            log.warning("ebooklib spine order differs from OPF parse; using OPF parse")
    except Exception as e:  # ebooklib can be picky; our parse stands
        log.debug("ebooklib read failed (%s); continuing with stdlib parse", e)

    return Book(
        chapters=chapters,
        entries=entries,
        opf_path=opf_path,
        spine_idrefs=spine_idrefs,
        title=title,
    )

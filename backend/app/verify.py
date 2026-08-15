"""Round-trip verification: structure, byte-identity of untouched entries,
XML well-formedness of rebuilt chapters, plain-text equality per chapter."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree


def plain_text(xhtml_bytes: bytes) -> str:
    """All visible text (incl. tails), whitespace-normalized."""
    try:
        root = etree.fromstring(xhtml_bytes)
        text = etree.tostring(root, method="text", encoding="unicode")
    except Exception:
        text = BeautifulSoup(xhtml_bytes, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _well_formed(xhtml_bytes: bytes) -> bool:
    try:
        etree.fromstring(xhtml_bytes)
        return True
    except Exception:
        return False


def _tag_skeleton(xhtml_bytes: bytes) -> list:
    root = etree.fromstring(xhtml_bytes)
    return [el.tag for el in root.iter()]


def verify_translated_chapter(original_bytes: bytes, rebuilt_bytes: bytes) -> dict:
    """DOM-integrity check for a translated chapter: still well-formed XML and
    the exact same tag structure (only text content may differ)."""
    return {
        "well_formed": _well_formed(rebuilt_bytes),
        "structure_preserved": _tag_skeleton(original_bytes) == _tag_skeleton(rebuilt_bytes),
    }


def verify_roundtrip(original_path, rebuilt_path, chapter_hrefs) -> dict:
    failures = {"entries": [], "bytes": [], "xml": [], "text": []}
    with zipfile.ZipFile(original_path) as oz, zipfile.ZipFile(rebuilt_path) as rz:
        orig_names, rebuilt_names = oz.namelist(), rz.namelist()

        if orig_names != rebuilt_names:
            failures["entries"] = [n for n in set(orig_names) ^ set(rebuilt_names)]

        for name in orig_names:
            if name in chapter_hrefs:
                continue
            if name in rebuilt_names and oz.read(name) != rz.read(name):
                failures["bytes"].append(name)

        for href in chapter_hrefs:
            if href not in orig_names or href not in rebuilt_names:
                failures["entries"].append(href)
                continue
            rebuilt = rz.read(href)
            if not _well_formed(rebuilt):
                failures["xml"].append(href)
            elif plain_text(oz.read(href)) != plain_text(rebuilt):
                failures["text"].append(href)

        mimetype_stored = (
            "mimetype" in rebuilt_names
            and rz.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        )

    ok = not any(failures.values()) and mimetype_stored
    return {
        "pass": ok,
        "entries_match": not failures["entries"],
        "untouched_entries_byte_identical": not failures["bytes"],
        "chapters_well_formed": not failures["xml"],
        "chapters_text_equal": not failures["text"],
        "mimetype_stored": mimetype_stored,
        "chapter_count": len(chapter_hrefs),
        "failures": failures,
    }

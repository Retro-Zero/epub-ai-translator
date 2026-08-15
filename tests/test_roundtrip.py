"""Phase-0 GATE: extract -> rebuild (identity) -> verify, on real-structure epubs.

Auto-discovers fixtures in tests/fixtures/ and any user-dropped epubs in
test-epubs/ (project root). Run:

    .venv/bin/python backend/tests/make_fixture.py
    .venv/bin/pytest backend/tests -v
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # project root
sys.path.insert(0, str(ROOT / "backend"))

from app import jobs  # noqa: E402
from app.parser import parse_epub  # noqa: E402
from app.rebuild import rebuild_epub  # noqa: E402
from app.textnodes import extract_chapter, rebuild_chapter  # noqa: E402
from app.verify import plain_text, verify_roundtrip  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
USER_EPUBS = ROOT / "test-epubs"


def all_epubs() -> list:
    epubs = sorted(FIXTURES.glob("*.epub"))
    if USER_EPUBS.is_dir():
        epubs += sorted(USER_EPUBS.glob("*.epub"))
    return epubs


@pytest.fixture(
    params=[str(p) for p in all_epubs()],
    ids=[p.name for p in all_epubs()],
    scope="session",
)
def epub_path(request):
    return request.param


def _zip_read(path, name):
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


# --- GATE: full round-trip through the same code path the API uses ----------


def test_roundtrip_preserves_content(epub_path):
    """The whole pipeline: upload -> parse -> extract -> rebuild -> verify."""
    job_id = jobs.create_job()
    jobs.job_paths(job_id)["input"].write_bytes(Path(epub_path).read_bytes())
    report = jobs.run_pipeline(job_id)
    assert report["pass"], f"round-trip failed for {epub_path}: {report['failures']}"
    assert report["chapter_count"] >= 1


def test_rebuilt_renders_same_plain_text(epub_path, tmp_path):
    book = parse_epub(epub_path)
    rebuilt = {}
    for ch in book.chapters:
        data = extract_chapter(ch.content, ch.id, ch.href)
        rebuilt[ch.href] = rebuild_chapter(ch.content, data)
    out = tmp_path / "rebuilt.epub"
    rebuild_epub(book, rebuilt, out)
    for ch in book.chapters:
        assert plain_text(ch.content) == plain_text(
            _zip_read(out, ch.href)
        ), f"text mismatch in {ch.href}"


# --- unit: extraction semantics ---------------------------------------------


def test_extract_assigns_stable_ids_and_skips_noise():
    book = parse_epub(FIXTURES / "synthetic.epub")
    ch = book.chapters[0]
    data = extract_chapter(ch.content, ch.id, ch.href)
    ids = [n.id for n in data.text_nodes]
    assert ids == [f"{ch.id}_n{i:04d}" for i in range(len(ids))], "ids not monotonic/stable"
    assert all(n.text.strip() for n in data.text_nodes), "whitespace-only nodes leaked in"
    texts = " ".join(n.text for n in data.text_nodes)
    assert "curious developer" in texts, "body text missing"
    assert "var junk" not in texts, "script content was extracted"
    assert "must never become a text node" not in texts, "comment was extracted"


def test_paths_resolve_to_same_text_on_reparse():
    """Stable IDs: a path recorded at extract time must resolve to the same
    string when the ORIGINAL bytes are parsed again (proves reinsertion target
    is deterministic across parses)."""
    from bs4 import BeautifulSoup

    def resolve(xhtml_bytes, path):
        body = BeautifulSoup(xhtml_bytes, "lxml").body
        cur = body
        for i in path:
            cur = cur.contents[i]
        return str(cur)

    book = parse_epub(FIXTURES / "synthetic.epub")
    for ch in book.chapters:
        data = extract_chapter(ch.content, ch.id, ch.href)
        assert data.text_nodes, f"{ch.href}: expected text nodes"
        for node in data.text_nodes:
            assert resolve(ch.content, node.path) == node.text, (
                f"{node.id}: path resolves to {resolve(ch.content, node.path)!r}, "
                f"expected {node.text!r}"
            )


def _body_text(xhtml_bytes: bytes) -> str:
    """Plain text of <body> only (extraction intentionally skips <head>)."""
    from lxml import etree

    root = etree.fromstring(xhtml_bytes)
    head = root.find(".//{http://www.w3.org/1999/xhtml}head")
    if head is not None:
        head.getparent().remove(head)
    return re.sub(r"\s+", " ", etree.tostring(root, method="text", encoding="unicode")).strip()


def test_translation_replaces_text_in_place():
    """The Phase-1 mechanism: a translator function's output lands at the
    exact same nodes, leaving structure untouched."""
    book = parse_epub(FIXTURES / "synthetic.epub")
    ch = book.chapters[0]
    data = extract_chapter(ch.content, ch.id, ch.href)
    rebuilt = rebuild_chapter(ch.content, data, lambda t: t.upper())
    assert _body_text(rebuilt) == _body_text(ch.content).upper()


def test_rebuilt_chapters_are_well_formed_xml():
    from lxml import etree

    book = parse_epub(FIXTURES / "synthetic.epub")
    for ch in book.chapters:
        data = extract_chapter(ch.content, ch.id, ch.href)
        rebuilt = rebuild_chapter(ch.content, data)
        etree.fromstring(rebuilt)  # raises on malformed XML

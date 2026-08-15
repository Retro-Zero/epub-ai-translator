"""Text-node extraction and re-insertion for XHTML chapters.

Engine: BeautifulSoup with the lxml parser (project stack). Each visible text
string inside <body> gets a stable id (chXX_nNNNN) and a structural path — the
chain of child indices from <body> into .contents — used to re-insert
translated text at exactly the same node.

Skipped: <script>/<style>/<svg>/<noscript> subtrees, HTML comments, and
whitespace-only strings (their index positions are still counted so paths
stay valid).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import warnings

from bs4 import BeautifulSoup, Comment, NavigableString, Tag, XMLParsedAsHTMLWarning

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def chapter_title(html_bytes: bytes) -> str:
    """First non-empty body heading, falling back to <title>. Used for the
    dashboard's chapter list (stable, cheap, no AI involved)."""
    soup = BeautifulSoup(html_bytes, "lxml")
    body = soup.body or soup
    for tag in body.find_all(HEADING_TAGS):
        text = tag.get_text(" ", strip=True)
        if text:
            return text[:120]
    t = soup.title
    if t:
        text = t.get_text(" ", strip=True)
        if text:
            return text[:120]
    return ""

# Deliberate: real-world XHTML chapters contain named entities (&nbsp;,
# &copy;, …) that only the HTML parser tolerates — lxml's strict XML parser
# would reject the whole chapter. The HTML parser is therefore the right
# engine for extraction; re-serialized output is still verified as
# well-formed XML by app.verify before a job is accepted.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SKIP_TAGS = {"script", "style", "svg", "noscript"}
_XML_DECL_RE = re.compile(rb"^\s*<\?xml[^>]*\?>")
_ENCODING_RE = re.compile(rb'encoding=["\'][^"\']*["\']')


@dataclass
class TextNode:
    id: str
    path: list  # child indices from <body>; final index lands on this string
    text: str


@dataclass
class ChapterData:
    chapter_id: str
    href: str
    text_nodes: list


def _find_body(soup):
    body = soup.body
    if body is not None:
        return body
    for el in soup.find_all(True):
        if isinstance(el, Tag) and (el.name or "").split(":")[-1] == "body":
            return el
    return None


def extract_chapter(xhtml_bytes: bytes, chapter_id: str, href: str) -> ChapterData:
    soup = BeautifulSoup(xhtml_bytes, "lxml")
    body = _find_body(soup)
    nodes = []
    if body is not None:
        _walk(body, [], nodes, chapter_id)
    return ChapterData(chapter_id=chapter_id, href=href, text_nodes=nodes)


def _walk(tag: Tag, path: list, nodes: list, chapter_id: str) -> None:
    for i, child in enumerate(tag.contents):
        if isinstance(child, Tag):
            if child.name in SKIP_TAGS:
                continue
            _walk(child, path + [i], nodes, chapter_id)
        elif isinstance(child, NavigableString):
            if isinstance(child, Comment):
                continue
            text = str(child)
            if not text.strip():
                continue
            nodes.append(
                TextNode(id=f"{chapter_id}_n{len(nodes):04d}", path=path + [i], text=text)
            )


def rebuild_chapter(xhtml_bytes: bytes, data: ChapterData, translate=None, rtl: bool = False) -> bytes:
    """Re-insert text at the recorded paths and re-serialize the chapter.

    translate: callable str -> str applied to every extracted node. Identity
    for the round-trip proof; the Anthropic call plugs in here in Phase 1.
    rtl: add dir="rtl" lang="fa" to <body> (Persian rendering) — attributes
    only, so recorded paths stay valid.
    """
    if translate is None:
        translate = lambda t: t  # noqa: E731
    soup = BeautifulSoup(xhtml_bytes, "lxml")
    body = _find_body(soup)
    if body is None:
        raise ValueError(f"chapter {data.chapter_id}: no <body> found")

    for node in data.text_nodes:
        cur = body
        for i in node.path:
            try:
                cur = cur.contents[i]
            except (IndexError, AttributeError) as e:
                raise ValueError(
                    f"chapter {data.chapter_id}: node {node.id} path {node.path} out of range"
                ) from e
        if not isinstance(cur, NavigableString) or isinstance(cur, Comment):
            raise ValueError(
                f"chapter {data.chapter_id}: node {node.id} no longer resolves to a text node"
            )
        new_text = translate(node.text)
        if new_text != str(cur):
            cur.replace_with(NavigableString(new_text))

    if rtl and body is not None:
        html = soup.html
        if html is not None:
            html["dir"] = "rtl"
            html["lang"] = "fa"
        body["dir"] = "rtl"
        body["lang"] = "fa"

    return _serialize(soup, xhtml_bytes)


def _serialize(soup: BeautifulSoup, original_bytes: bytes) -> bytes:
    return _xml_decl(original_bytes) + soup.encode("utf-8")


def _xml_decl(original_bytes: bytes) -> bytes:
    """Keep the original XML declaration (rewritten to UTF-8 since we always
    emit UTF-8 bytes); add a standard one if the original had none."""
    m = _XML_DECL_RE.search(original_bytes)
    if m:
        return _ENCODING_RE.sub(b'encoding="utf-8"', m.group(0))
    return b'<?xml version="1.0" encoding="utf-8"?>'

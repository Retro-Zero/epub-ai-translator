"""Generate a synthetic multi-chapter EPUB2 fixture (CSS, image, footnotes,
mixed inline markup, script/comment noise) so the automated suite has a
deterministic, real-structure input.

Usage:  python tests/make_fixture.py   ->  tests/fixtures/synthetic.epub
"""
from __future__ import annotations

import base64
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

CSS = b"""body { font-family: serif; margin: 1em; }
p { text-indent: 1.5em; }
.footnote { font-size: 0.85em; color: #444; }
"""

NCX = b"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:fixture-synthetic"/></head>
  <docTitle><text>Synthetic Fixture</text></docTitle>
  <navMap>
    <navPoint id="np1" playOrder="1"><navLabel><text>One</text></navLabel><content src="text/chapter1.xhtml"/></navPoint>
    <navPoint id="np2" playOrder="2"><navLabel><text>Two</text></navLabel><content src="text/chapter2.xhtml"/></navPoint>
    <navPoint id="np3" playOrder="3"><navLabel><text>Three</text></navLabel><content src="text/chapter3.xhtml"/></navPoint>
  </navMap>
</ncx>
"""

OPF = b"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>Synthetic Fixture</dc:title>
    <dc:creator>A. Test Author</dc:creator>
    <dc:publisher>Test Press</dc:publisher>
    <dc:identifier id="uid">urn:uuid:fixture-synthetic</dc:identifier>
    <dc:language>en</dc:language>
    <meta name="cover" content="cover"/>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="cover" href="images/cover.png" media-type="image/png"/>
    <item id="ch1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="text/chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch3" href="text/chapter3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
    <itemref idref="ch3"/>
  </spine>
</package>
"""

CONTAINER = b"""<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

CHAPTERS = [
    ("chapter1.xhtml", """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Chapter One</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
  <h1>The Beginning</h1>
  <p>Once upon a time, in a <em>faraway</em> land, there lived a curious developer.</p>
  <p>He opened <strong>EPUB</strong> files &amp; found <a href="#fn1" id="fnref1">footnotes</a> inside.</p>
  <p>She asked: <q>Can the round-trip survive?</q><br/>The answer was silence.</p>
  <p><img src="../images/cover.png" alt="a tiny pixel"/></p>
  <p class="footnote" id="fn1">Footnote one: an <code>inline</code> note. <a href="#fnref1">back</a>.</p>
  <!-- a comment that must never become a text node -->
</body>
</html>"""),
    ("chapter2.xhtml", """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter Two</title></head>
<body>
  <h2>Lists &amp; Quotes</h2>
  <ol>
    <li>First item with <span class="hl">highlighted</span> text.</li>
    <li>Second item, plain.</li>
  </ol>
  <blockquote><p>To be, or not to be — <em>that</em> is the question.</p></blockquote>
  <p style="display:none">Hidden content stays but must not be translated.</p>
</body>
</html>"""),
    ("chapter3.xhtml", """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter Three</title></head>
<body>
  <div class="scene">
    <p>Act III. A <b>windy</b> plain.</p>
    <p>Heavy <i>rain</i> fell. Nobody noticed.</p>
    <script type="text/javascript">var junk = "not visible text";</script>
  </div>
</body>
</html>"""),
]


def build(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/toc.ncx", NCX)
        zf.writestr("OEBPS/style.css", CSS)
        zf.writestr("OEBPS/images/cover.png", PNG_1PX)
        for name, html in CHAPTERS:
            zf.writestr(f"OEBPS/text/{name}", html.encode("utf-8"))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    build(FIXTURES / "synthetic.epub")

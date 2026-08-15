"""Rezip: copy every original entry verbatim, swapping in rebuilt chapter files.

Nothing but the chapter files changes; compression types, entry order
(mimetype first, stored) and all other bytes are preserved.
"""
from __future__ import annotations

import zipfile
from pathlib import Path


def rebuild_epub(book, rebuilt_chapters: dict, out_path) -> Path:
    """rebuilt_chapters: {zip entry href: new bytes}. All other entries are
    copied byte-for-byte with their original compression."""
    out_path = Path(out_path)
    with zipfile.ZipFile(out_path, "w") as zout:
        for name, data, compress_type in book.entries:
            if name in rebuilt_chapters:
                data = rebuilt_chapters[name]
            info = zipfile.ZipInfo(name)
            info.compress_type = compress_type
            zout.writestr(info, data)
    return out_path

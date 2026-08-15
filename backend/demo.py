"""Phase-0 demo: run the identity round-trip on any .epub and print the report.

Usage: .venv/bin/python backend/demo.py path/to/book.epub
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import jobs  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python demo.py <file.epub>")
        return 2
    epub = sys.argv[1]
    print(f"round-tripping {epub} ...")
    report = jobs.run_external(epub)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

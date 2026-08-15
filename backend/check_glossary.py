"""Glossary consistency QA (the Phase 3 GATE check).

For every approved glossary term: each chapter whose SOURCE contains the
English term must also contain the approved Persian form in its translation.
Also flags English leftover occurrences of glossary terms in translated text.

Usage: .venv/bin/python backend/check_glossary.py data/jobs/<job_id>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python check_glossary.py data/jobs/<job_id>")
        return 2
    job_dir = Path(sys.argv[1])
    chapters_dir = job_dir / "chapters"

    approved = json.loads((job_dir / "glossary_approved.json").read_text(encoding="utf-8"))

    missing = []      # English term present in source, Persian form absent in translation
    warnings = []     # non-fatal: category "term"/"other" phrasing variants
    leftovers = []    # English glossary form found inside translated text
    for tpath in sorted(chapters_dir.glob("*.translated.json")):
        data = json.loads(tpath.read_text(encoding="utf-8"))
        cid = data["chapter_id"]
        orig_text = " ".join(n["original"] for n in data["text_nodes"])
        trans_text = " ".join(n["translation"] for n in data["text_nodes"])
        for term in approved:
            original, persian = term["original"], term["persian"]
            if original.lower() in orig_text.lower():
                if persian not in trans_text:
                    entry = {"chapter": cid, "term": original, "persian": persian}
                    if term.get("category") in ("character", "place", "title"):
                        missing.append(entry)
                    else:
                        warnings.append({**entry, "reason": "phrasing variant (term/other category)"})
            for m in re.finditer(rf"\b{re.escape(original)}\b", trans_text):
                leftovers.append({"chapter": cid, "term": m.group(0)})

    report = {
        "terms": len(approved),
        "chapters_translated": len(list(chapters_dir.glob("*.translated.json"))),
        "missing_persian_forms": missing,
        "term_warnings": warnings,
        "english_leftovers": leftovers,
        "pass": not missing and not leftovers,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

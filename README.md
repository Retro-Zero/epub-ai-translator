# EPUB AI Translator

**🌐 Languages:** English · [فارسی](README.fa.md)

A self-hosted web app that turns English EPUBs into Persian — with a human in
the loop at every step that matters. Upload a book, approve a glossary of names
and terms, watch per-chapter progress, review AI-flagged issues, and download a
finished RTL Persian EPUB with the original structure, images, CSS and TOC
intact.

Single-user, runs entirely on your machine, no accounts, no cloud. Bring your
own API key — you only pay your provider for the tokens you actually use.

## What it does

1. **Upload** — drop an `.epub`; it is parsed locally and you see title, size
   and chapter count *before* anything is created.
2. **BYOK provider** — DeepSeek, OpenAI, Gemini or any OpenAI-compatible
   endpoint (Ollama, Groq, …). The key lives in a local config file on your
   machine and is never sent anywhere else.
3. **Glossary** — extract the book's names and recurring terms from the first
   content chapter, edit the proposed Persian forms, approve. Every translation
   call then treats those terms as fixed, mandatory translations.
4. **Translate** — full-book background queue with live per-chapter status.
   Failures are scoped: a failed chapter never blocks the book and retries
   inline.
5. **QA review** — an optional consistency pass on a sample of translated
   nodes (glossary use / meaning / fluency / tone) with original + current text
   side by side, editable fixes, and accept-or-keep per issue.
6. **Finalize** — applies accepted fixes, sets `lang="fa"` + `dir="rtl"` on
   every chapter, embeds the Vazirmatn font (SIL OFL 1.1, shipped with license),
   translates the TOC/title, and produces the final downloadable EPUB.

Cost visibility is front and center: tokens used per job, estimated cost from
your provider's rates (hardcoded table, editable in settings), and an estimate
of what's left mid-run.

## Stack

- **Backend** — Python 3.11, FastAPI, ebooklib (OPF/spine model), BeautifulSoup
  + lxml (XHTML DOM), stdlib zip surgery
- **Frontend** — React 18 + Vite (functional components + hooks, flat minimal
  CSS, poll-based status — no websockets, no UI framework)
- **Storage** — local filesystem `data/jobs/<job_id>/`, no database
- **Translation** — any OpenAI-compatible API via the `openai` SDK
  (DeepSeek preset tuned for `deepseek-v4-flash`: thinking disabled,
  rate-limit-aware batching, empty-response recovery)

## Setup & run

Requires Python 3.10+ (3.11 recommended) and Node 18+ for the frontend build.

```bash
# 1. Backend
uv venv --python 3.11
uv pip install --python .venv/bin/python -r backend/requirements.txt
cp backend/.env.example backend/.env    # optional: env-key fallback

# 2. Frontend (build once; output goes to backend/static)
cd frontend && npm install && npm run build && cd ..

# 3. Run
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000 — the settings screen takes your provider, model and
key (or just use the `DEEPSEEK_API_KEY` env fallback), and "Test connection"
validates the key with one cheap call before you commit to a book.

Frontend dev mode (hot reload, proxies API to :8000): `cd frontend && npm run dev`.

## BYOK configuration

| Field | Notes |
|---|---|
| Provider | DeepSeek / OpenAI / Gemini / Custom (OpenAI-compatible base URL) |
| Model | per-provider picker (DeepSeek V4 flash, GPT-4o mini, Gemini 2.5 flash, …) or free text for custom |
| API key | stored in `data/settings.json` on your machine (gitignored, chmod 600), masked in the UI, never returned by the API |
| Prices | per-1M-token input/output rates for the cost estimate — built-in table, editable |

## API

| Method | Path | Description |
|---|---|---|
| POST | `/preview` | parse an epub without creating a job → title, chapter count, node counts |
| POST | `/upload` | multipart `file` (.epub) → `{job_id, report}`; extract + rebuild + verify |
| GET | `/jobs/{id}` / `/jobs/{id}/status` | book meta / live per-chapter status + usage + cost |
| POST | `/glossary/{id}/extract` | propose glossary terms from the first content chapter |
| PATCH | `/glossary/{id}` | edit/approve glossary `{glossary: [{original, persian, category, note}]}` |
| POST | `/translate/{id}/chapter/{ch}` | translate one chapter (approved glossary applied) |
| POST | `/translate/{id}/all` | background full-book run; skips already-done chapters |
| POST | `/qa/{id}` · GET `/qa/{id}` · PUT `/qa/{id}/fixes` | run / read / apply QA review |
| POST | `/finalize/{id}` | QA fixes + RTL metadata + font + translated TOC/title → `final.epub` |
| GET | `/download/{id}` | final → translated → round-trip epub, in that priority |
| GET | `/settings` · PUT · POST `/settings/test` | BYOK store (masked) + connection check |
| GET | `/health` | liveness |

## Verification (the GATE)

Every upload runs a round-trip proof before translation is allowed to touch
anything: the rebuilt epub must render identically to the original —

- zip entry lists identical (order included)
- every untouched entry (CSS, images, fonts, OPF, NCX, TOC) byte-identical
- `mimetype` still stored, not deflated (EPUB spec)
- every rebuilt chapter is well-formed XML
- extracted plain text identical per chapter (whitespace-normalized)

`report.json` per job records all five checks; a failing check fails the job.

## Tests

```bash
.venv/bin/python -m pytest        # 66 tests: round-trip, translator, glossary,
                                  # QA, finalize, settings, preview
```

Drop real-world epubs into `test-epubs/` (gitignored) — they are picked up
automatically as round-trip fixtures. `backend/demo.py book.epub` runs the
round-trip on any file from the CLI.

## Project layout

```
backend/app/          FastAPI app: parser, textnodes, translator, jobs,
                      glossary, qa, finalize, settings, verify, rebuild
backend/static/       built React frontend (served by FastAPI)
backend/assets/       Vazirmatn font + OFL license (embedded at finalize)
frontend/             React source (Vite)
tests/                66 pytest tests + fixture builder
data/jobs/<job_id>/   per-job artifacts (gitignored)
```

## Roadmap

EPUB3 output polish · glossary re-approval after mid-book edits · CI workflow
for the test suite · automatic provider-price refresh.

## Non-goals (v1)

Multi-language beyond EN→FA · user accounts / multi-tenant · payments ·
collaborative editing · mobile app.

## License

MIT — see [LICENSE](LICENSE). Vazirmatn font is SIL OFL 1.1.

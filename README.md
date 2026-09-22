# TuxBook (tuxbook)

[![CI](https://github.com/o-valo/TuxBook/actions/workflows/ci.yml/badge.svg)](https://github.com/o-valo/TuxBook/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

Translate whole books — a PDF, or a ZIP of single pages — page by page into
another language and re-typeset them into a clean PDF. Built for thick books
(1000+ pages): interruptible, cache-based, parallel.

*German version of this document: [README.ger.md](README.ger.md)*

## Features

- **Input:** a single PDF *or* a ZIP (a complete PDF and/or numbered single
  pages — sorted naturally into one master PDF, `seite_2` before `seite_10`)
- **Two layout modes:** `page` (1:1, translated text at the original position)
  and `flow` (a freshly typeset A4 book with title page, justified text and
  page numbers)
- **Markdown export** on every run (with detected headings)
- **Images in Markdown:** content images are extracted per page, linked in the
  MD and placed as numbered figures when re-typesetting
- **`tuxbook md2pdf`:** re-typesets the — hand-correctable — Markdown export into a
  freshly set book PDF (title page, chapters starting on a new page, TOC,
  page numbers)
- **Selectable text source:** use the embedded text layer (`auto`/`embedded`)
  or re-OCR everything (`ocr`)
- **OCR:** local Tesseract by default (fast & accurate), Ollama vision as a
  fallback for hard cases
- **Cleanup layer** before translation: scan artefacts (`i94o`→`1940`,
  `jf`→`fl`), noise lines and shredded tables of contents are repaired
- **Terminology lock:** key terms are extracted from the first pages and given
  to every page request consistently
- **Page-boundary context:** neighbouring page texts mitigate sentence breaks
- **Resume/cache:** every run is interruptible (Ctrl+C is safe) and resumes
  exactly where it stopped; changing engine or extraction invalidates the
  cache automatically

## Setup

```bash
git clone <this-repo> && cd TuxBook
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# OCR (default engine, entirely local):
sudo apt-get install tesseract-ocr tesseract-ocr-deu   # + more language packs as needed
```

**Venv:** `./tuxbook` activates the project venv (`.venv`) automatically — the
command works **without** a prior `source .venv/bin/activate`. Only if you need
`python3` directly (tools, tests, your own scripts), activate it first:

```bash
source .venv/bin/activate
```

### Configuration

Endpoints are read from `tuxbook.conf` (see `tuxbook.conf.example`):

```bash
cp tuxbook.conf.example tuxbook.conf
# then enter your own chat API (OpenAI-compatible) and, optionally, an
# Ollama endpoint for vision OCR
```

Environment variables work as well
(`TUXBOOK_BAHNHOF_URL`, `TUXBOOK_BAHNHOF_MODEL`, `TUXBOOK_OLLAMA_URL`, `TUXBOOK_OLLAMA_MODEL`).
Without any configuration the defaults are `localhost` — so you need:

1. an **OpenAI-compatible chat endpoint** for translation
   (any self-hosted LLM works, e.g. vLLM/llama.cpp/LM Studio)
2. optionally an **Ollama endpoint** for vision OCR and mini translators

## Usage

```bash
# 1) Translate + re-typeset 1:1 (source page N -> target page N)
./tuxbook run book.pdf --from auto --to de --mode page

# 2) Translate + typeset as a book (A4, justified, page numbers)
./tuxbook run book.pdf --from en --to de --mode flow --title "Book title"

# 3) ZIP of single pages — merged into a master PDF automatically
./tuxbook run pages.zip --to de --job mybook

# 4) Large books: work in batches (resume uses the cache)
./tuxbook run book.pdf --pages 1-250 --job mybook
./tuxbook run book.pdf --pages 251-500 --job mybook

# 5) Render only, once every page is cached
./tuxbook run book.pdf --mode flow --job mybook --render-only --title "Title"

# 6) Status / OCR comparison / visual quality check
#    (for the python3 tools: source .venv/bin/activate first)
./tuxbook status --job mybook
python3 tools/ocr_compare.py book.pdf --page 42
python3 tools/pdf_look.py out/mybook_page.pdf --pages 2,4,10
```

Important flags:

| Flag | Effect |
|---|---|
| `--mode page` | 1 source page → 1 target page, text at the original position (default) |
| `--mode flow` | freshly typeset book, paragraphs flow naturally |
| `--text-source auto` | embedded text, OCR only as fallback (default) |
| `--text-source embedded` | never OCR — embedded text layer only |
| `--text-source ocr` | ignore embedded text, OCR every page |
| `--pages` | page ranges such as `1-50,60,71-80` |
| `--job NAME` | job name = resume key (cache in `jobs/NAME/pages/`) |
| `--glossary file` | lines `term = translation` (to be respected by the LLM) |
| `--no-term-lock` | disable terminology extraction |
| `--no-render` | translate only, render later (e.g. to correct the MD first) |
| `--workers N` | parallel pages (default 3) |
| `--engine bahnhof` | translate via the configured chat endpoint (default) |
| `--engine ollama --translate-model M` | mini translation model on Ollama (e.g. a dedicated 1B translator); the cache is engine-specific |
| `--ocr tesseract` | default. `auto` = Ollama vision as fallback, `ollama` forces vision OCR |
| `--retranslate` | ignore the cache, redo everything |

## Recommended workflow: PDF → OCR → Markdown → PDF

For scanned books (or when the embedded text layer is unusable) this is the way
to a clean, human-readable result:

```bash
# 1) Translate — force OCR (every page is rendered and OCR'd)
./tuxbook run book.pdf --from auto --to de --mode page \
    --text-source ocr --job mybook

# 2) Status: is every page cached?
./tuxbook status --job mybook

# 3) Render Markdown from the cache (the 1:1 PDF comes for free)
./tuxbook run book.pdf --job mybook --render-only
#    -> out/mybook_page.md + out/mybook_page.pdf

# 4) Correct the Markdown by hand — it is the correctable source;
#    the images sit next to it (out/mybook_page_bilder/) and are linked
#    (optionally: translate with --no-render to separate this step)

# 5) Re-typeset a clean book PDF from the Markdown
./tuxbook md2pdf out/mybook_page.md --title "Book title"
#    -> out/mybook_page_neu.pdf
```

Notes:

- **`--mode page` + `--render-only`** yields the MD as an intermediate product;
  the actual book PDF is created in step 5 from the MD (justified text, real
  headings, chapters starting on a new page, title page).
- With **large books** work in batches (step 1 with `--pages 1-250`, then
  `251-500`, …) — the cache makes any interruption safe.
- The **MD is the source of truth**: corrections (e.g. OCR errors in proper
  names) belong in the Markdown before step 5, not in the PDF.
- If the MD and the images folder were moved, `md2pdf --images FOLDER` points
  at the images; `--out FILE` sets a different output name.

## Pipeline

1. **Preparation:** unpack/merge the ZIP if needed (cached), extraction with the
   cleanup layer (artefact fixes, noise filter, TOC fusion, paragraph merge)
2. **OCR**, if a page contains barely any text and does have an image
   (depending on `--text-source`)
3. **Translation** in parallel (`--workers`): paragraphs numbered (the `Pn:`
   protocol) with verification — missing paragraphs are requested individually;
   if a page fails completely it is not cached and is retried on the next run
4. **Rendering** at the end (or via `--render-only`): PDF + Markdown

## Structure

```
tuxbook                     CLI entry point (run/status/md2pdf/make-test-pdf/ocr-test)
tuxbook_lib/
  config.py             endpoints (tuxbook.conf/env), fonts, guard window
  llm.py                chat client + Ollama client (guard, retries)
  zipsrc.py             ZIP preparation (master PDF selection/merge)
  extract.py            PDF extraction, cleanup, TOC fusion, paragraph merge
  ocr.py                Tesseract primary, Ollama vision fallback
  translate.py          Pn protocol, verification, term lock, context
  images.py             extract content images per page (for the MD export)
  render_page.py        page mode (original covered + translation)
  render_flow.py        flow mode (ReportLab, A4, justified, title page)
  render_md.py          Markdown export
  render_md2pdf.py      Markdown → freshly typeset book PDF
  project.py            jobs, manifest, resume, glossary
tools/
  ocr_compare.py        Tesseract vs. vision OCR on a degraded page
  pdf_look.py           visual quality check via a vision model
  make_test_pdf.py      build a test PDF for CI
jobs/<name>/pages/*.json  page cache
out/<name>_<mode>.pdf     output PDF (+ .md, + _bilder/)
```

## Tests & development

Offline unit tests (no LLM, no network) for extraction, cleanup, TOC fusion,
stitching, ZIP preparation, image extraction and Markdown→PDF:

```bash
pip install -r requirements-dev.txt
pytest tests/
```

CI (GitHub Actions) checks on every push: syntax of all modules, unit tests,
CLI smoke (`--version`, `make-test-pdf`) and an OCR smoke test with Tesseract.

> Badge note: the badge URL points at <https://github.com/o-valo/TuxBook> —
> adjust it if the repository lives elsewhere.

## Known limits

- **Page mode:** text search in the output PDF also finds the covered original
  layer (visually correct; use `--mode flow` for clean text).
- Complex column/footnote layouts are carried over as a paragraph stream.
- Vision OCR happily hallucinates plausible words — which is why Tesseract is
  the default and vision only a fallback (measure with `tools/ocr_compare.py`).
- Spelling/typography of the original (ligatures, small caps) is carried over in
  a simplified form.

## License

**GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later) — the
unmodified license text is in [LICENSE](LICENSE),
Copyright (C) 2026 Olav Surawski (<https://github.com/o-valo>).

In short: you may use, modify and redistribute it freely, as long as derived
versions stay under the AGPL. Section 13 applies if you make a **modified**
version publicly reachable as a network service — then the source code of that
version must be available to its users. Nothing changes for running it on your
own machine.

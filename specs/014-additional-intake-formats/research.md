# Phase 0 Research: Additional Document Formats (`014-additional-intake-formats`)

**Feature Branch**: `014-additional-intake-formats` (note: local repo is currently on `main` @ `93f5302`; branch `feat/014-additional-intake-formats` to be created prior to implementation)  
**Date**: 2026-11-17

---

## 1. Empty-Document Handling vs. `EmptyDocumentError` Gate Finding

- **Observation in Codebase**:
  - `EmptyDocumentError` is mentioned historically in `.specify/memory/constitution.md` (`Quality Gates`), and echoed in `specs/014-additional-intake-formats/spec.md` (`FR-002`, `FR-008`, `SC-004`).
  - However, `src/docpipe_maestro/types.py` defines **no** `EmptyDocumentError` class, `tests/test_api_stability.py` locks `len(docpipe_maestro.__all__) == 36` to exact symbol names (`EXPECTED_ALL`), all 5 existing built-in parsers (`TextParser`, `MarkdownParser`, `HtmlParser`, `PdfParser`, `DocxParser`) return `ParsedDocument(source=source_key, format_name=..., sections=[])` on empty/textless valid files, and `tests/test_hybrid_search.py::test_lexical_lifecycle_ingest_sync_remove_and_empty_file` explicitly asserts that ingesting an empty file succeeds cleanly with `0` indexed rows.
- **Decision**:
  - Keep existing uniform codebase behavior across all parsers: valid empty/header-only/blank-only inputs return `ParsedDocument(source=source_key, format_name=..., sections=[])` without mutating `EXPECTED_ALL` (`36` exports) or crashing multi-file directory ingestion, while malformed/corrupted files, invalid UTF-8 byte sequences, zip bombs, and unsupported legacy binary formats raise `UnsupportedFormatError`.
  - Flag the spec wording alignment (`"raise an empty-document error"` → `"return empty sections cleanly without crashing or storing spurious chunks"`) prominently in `plan.md` Constitution Check so `/speckit-analyze` or explicit user review resolves it cleanly before tasks execute.
- **Alternatives Considered**:
  - Adding `EmptyDocumentError` to `types.py` and `__all__`: rejected because it breaks `len(docpipe_maestro.__all__) == 36` (`SC-005` / `test_api_stability.py`).
  - Raising unexported `EmptyDocumentError` or `UnsupportedFormatError` only on new formats: rejected because an empty `.csv` would abort `ingest(directory)` while an empty `.txt` succeeds with `0` rows.

---

## 2. Shared Intake Discovery, Lazy Registry & Custom Override Precedence

- **Observation in Codebase**:
  - `src/docpipe_maestro/ingest/intake/__init__.py` registers built-in parsers via `PARSERS.register_lazy(key, module_path, class_name)` and mirrors exports in `_LAZY_PARSER_EXPORTS` + `TYPE_CHECKING`.
  - `src/docpipe_maestro/_resolve.py` uses `_BUILTIN_PARSER_KEYS = frozenset({"docx", "html", "md", "pdf", "txt"})` so user-registered `@register_parser(...)` extensions run before built-in defaults.
- **Decision**:
  - Register `"csv"`, `"tsv"`, `"xlsx"`, `"pptx"`, `"epub"`, and `"rst"` via `PARSERS.register_lazy(...)` and `_LAZY_PARSER_EXPORTS`, and add all 6 keys to `_BUILTIN_PARSER_KEYS` in `_resolve.py` and all new extensions (`".csv"`, `".tsv"`, `".xlsx"`, `".pptx"`, `".epub"`, `".rst"`) to `SUPPORTED_EXTENSIONS` in `src/docpipe_maestro/ingest/intake/_common.py`.
  - Preserve `docpipe_maestro.__all__` untouched at `36` exports.
  - Extend `tests/test_library_purity.py` to verify importing `docpipe_maestro` or building the CLI parser never eagerly imports `openpyxl`, `pptx`, `ebooklib`, or `docutils`.
- **Rationale**: Maintains Constitution Footprint compliance ("additive — no existing module should need modification beyond registration") and zero startup import overhead.

---

## 3. Core Delimited Text Parser (`.csv` / `.tsv` without Python Module Shadowing)

- **Decision**:
  - Implement CSV (`delimiter=","`) and TSV (`delimiter="\t"`) parsing in `src/docpipe_maestro/ingest/intake/delimited.py` (intentionally **not** named `csv.py` so Python's stdlib `import csv` is never shadowed inside `intake/`).
  - Expose `CsvParser` (`PARSERS["csv"]`, `extensions = (".csv",)`) and `TsvParser` (`PARSERS["tsv"]`, `extensions = (".tsv",)`) sharing one parameterized parsing helper.
  - Enforce strict UTF-8 / UTF-8-SIG (`encoding="utf-8-sig"`) decoding cleanly via `read_text(encoding="utf-8-sig")`; any `UnicodeDecodeError` or embedded NUL byte (`"\x00"` raises `csv.Error` in CPython's `csv` module anyway — check NUL bytes upfront too) raises `UnsupportedFormatError`.
  - Header & row extraction: first non-empty row provides normalized column headers; empty header slots default to `Column {col_idx + 1}` and ragged extra cells on wider rows map to `Column {col_idx + 1}`. Blank cells in a row are omitted; rows whose cells are all whitespace are skipped.
  - Partition non-empty formatted data rows (`" | ".join(f"{header}: {value}" for ...)` into fixed `25`-row window `ParsedSection` blocks titled `f"{source_key} (Rows {start}-{end})"`, setting `heading_level=1`, `page=None`, and preserving row provenance cleanly without generating oversized parent sections.
- **Alternatives Considered**:
  - Falling back to `cp1252` on decode error: rejected per `Q3 -> A` (prevents silent garbling and aligns with `TextParser`/`MarkdownParser`/`HtmlParser`).
  - Emitting 1 section per row or 1 section per entire file: rejected per `Q2 -> A`.

---

## 4. Generalized ZIP Container Security & Extensionless Magic-Byte Routing

- **Observation in Codebase**:
  - `_common.py` currently validates only DOCX archives via `_validate_docx_zip` (`_MAX_DOCX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024`, checking `word/document.xml`).
  - `.docx`, `.xlsx`, `.pptx`, and `.epub` ALL use `PK\x03\x04` ZIP containers, whereas legacy binary `.xls` and `.ppt` use OLE2 Compound Document headers (`\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`).
- **Decision**:
  - Rename/generalize `_validate_docx_zip` into `_validate_zip_container(path, *, source_key, required_entry, max_bytes=256 MiB)` (keeping `_validate_docx_zip` as a tiny thin alias if any internal caller/test references it, or updating `docx.py` and checking all tests first).
  - Required container markers:
    - `docx`: `"word/document.xml"`
    - `xlsx`: `"xl/workbook.xml"`
    - `pptx`: `"ppt/presentation.xml"`
    - `epub`: `"META-INF/container.xml"`
  - Enforce uncompressed total byte limit (`_MAX_ZIP_UNCOMPRESSED_BYTES = 256 * 1024 * 1024`) and catch `zipfile.BadZipFile` / `OSError` cleanly in `_validate_zip_container` BEFORE any format parser library touches the ZIP archive.
  - Add OLE2 magic prefix rejection (`\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`) and extension handling in `detect_format(path)`:
    - Known extensions `.xlsx`, `.pptx`, `.epub`, `.rst`, `.csv`, `.tsv` map directly in `detect_format`.
    - Unsupported legacy `.xls` / `.ppt` hit the unknown-extension `UnsupportedFormatError` with an explicit hint recommending conversion to `.xlsx`/`.pptx` or `.csv`.
    - Extensionless files beginning with `PK\x03\x04` are inspected safely against the 4 known archive markers (`word/document.xml` → `docx`, `xl/workbook.xml` → `xlsx`, `ppt/presentation.xml` → `pptx`, `META-INF/container.xml` → `epub`); any other ZIP container raises `UnsupportedFormatError`.
  - Keep extensionless `.csv`/`.tsv`/`.rst` out of fragile heuristic sniffing unless explicitly unambiguous (extensionless UTF-8 prose continues defaulting to `md`/`txt` cleanly).

---

## 5. Rich Format Extraction Design

1. **Excel (`.xlsx` via `openpyxl>=3.1.0` — `[xlsx]` extra)**
   - Lazy import `openpyxl` inside `xlsx.py`; missing import raises `MissingExtraError("XLSX support requires the 'xlsx' extra: pip install docpipe-maestro[xlsx]")`.
   - Validate ZIP container (`xl/workbook.xml`) before calling `openpyxl.load_workbook(str(path), read_only=True, data_only=True)`. Always close workbook inside `finally:`.
   - Skip hidden sheets (`ws.sheet_state != "visible"`, per `Q1 -> A`).
   - Extract rows using `ws.iter_rows(values_only=True)`: normalize scalar values safely (bool/int/float/date/datetime/str), skip leading blank rows, treat the first non-empty row as column headers, pair each subsequent non-empty row with headers (`Header: Value | ...`), and chunk into bounded 25-row windows `f"{ws.title} (Rows {start}-{end})"`.

2. **PowerPoint (`.pptx` via `python-pptx>=1.0.0` — `[pptx]` extra)**
   - Lazy import `pptx.Presentation` inside `pptx.py`; missing import raises `MissingExtraError("PPTX support requires the 'pptx' extra: pip install docpipe-maestro[pptx]")`.
   - Validate ZIP container (`ppt/presentation.xml`) before calling `Presentation(str(path))`.
   - Iterate `prs.slides` with 1-based `page = idx + 1`. Extract title from `slide.shapes.title.text` (fallback `f"Slide {idx + 1}"`). Recursively walk shapes (`has_text_frame`, `has_table`, grouped `shapes`) in slide order, formatting table rows as `" | ".join(cells)`. Append `Speaker Notes:\n<notes>` when `slide.has_notes_slide` yields non-empty text. Emit one `ParsedSection` per non-empty slide.

3. **EPUB (`.epub` via `ebooklib>=0.18` + stdlib `html.parser` — `[epub]` extra)**
   - Lazy import `ebooklib` & `ebooklib.epub` inside `epub.py`; missing import raises `MissingExtraError("EPUB support requires the 'epub' extra: pip install docpipe-maestro[epub]")`.
   - Crucially, **do NOT depend on `beautifulsoup4`** so `[epub]` works standalone without `[html]`. Implement a clean stdlib `html.parser.HTMLParser` DOM/tag filter (`_HiddenSafeHtmlExtractor`) that skips `<script>`, `<style>`, `<nav>`, `<footer>`, `<noscript>`, `<template>`, `<svg>`, hidden attributes (`hidden`, `aria-hidden="true"`, `display:none`/`visibility:hidden` per `Q1 -> A`), extracts `<h1>`–`<h6>` section splits cleanly, and executes strictly offline with zero external entity resolution.
   - Validate ZIP container (`META-INF/container.xml`) before calling `epub.read_epub(str(path))`. Iterate ordered spine items (`book.spine`) filtering to document items (`ITEM_DOCUMENT`), preserving chapter titles/sections in reading order while skipping empty nav/boilerplate pages.

4. **reStructuredText (`.rst` via `docutils>=0.20` — `[rst]` extra)**
   - Lazy import `docutils.core` & `docutils.nodes` inside `rst.py`; missing import raises `MissingExtraError("RST support requires the 'rst' extra: pip install docpipe-maestro[rst]")`.
   - Strict UTF-8 / UTF-8-SIG file read (raising `UnsupportedFormatError` on decode errors).
   - Parse via `publish_doctree(raw, settings_overrides={"file_insertion_enabled": False, "raw_enabled": False, "report_level": 5, "halt_level": 5, "warning_stream": io.StringIO()})` so local file-inclusion (`.. include::`), raw passthrough (`.. raw::`), external DTDs, and stderr warning noise are completely disabled.
   - Traverse `doctree` sections (`nodes.section` + `nodes.title`) iteratively/recursively to produce hierarchical `ParsedSection` blocks preserving `heading_level`, paragraphs, lists, literal blocks, admonitions, and tables (`" | ".join(cells)`).

---

## 6. Packaging, Static Typing & Minimal-Core CI

- `pyproject.toml`:
  - Add `xlsx = ["openpyxl>=3.1.0"]`, `pptx = ["python-pptx>=1.0.0"]`, `epub = ["ebooklib>=0.18"]`, `rst = ["docutils>=0.20"]`.
  - Expand `all` extra to include `docpipe-maestro[pdf]`, `[docx]`, `[html]`, `[xlsx]`, `[pptx]`, `[epub]`, `[rst]` (keeping `rerank` and `pii` separate).
  - Add `"openpyxl.*"`, `"pptx.*"`, `"ebooklib.*"`, `"docutils.*"` to `[tool.mypy.overrides]` `ignore_missing_imports = true`.
- Update `uv.lock` after editing `pyproject.toml` so `uv lock --check` and `uv sync --locked --all-extras --group dev` pass cleanly.
- Update `.github/workflows/ci.yml` `minimal-core` job:
  - Test core `.csv` and `.tsv` intake/retrieval cleanly with zero optional extras installed.
  - Assert `MissingExtraError` on `.xlsx`, `.pptx`, `.epub`, `.rst` alongside `.pdf`, `.docx`, `.html`.
  - Keep optional-extra format tests cleanly isolated (`tests/test_intake_formats_optional.py`) and added to `minimal-core` `--ignore` list (matching existing `--ignore=tests/test_intake_clean.py`).

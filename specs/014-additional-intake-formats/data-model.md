# Data Model: Additional Document Formats (`014-additional-intake-formats`)

**Feature Branch**: `014-additional-intake-formats` | **Date**: 2026-11-17

---

## 1. Extension & Registry Entries (`docpipe_maestro.ingest.intake`)

No changes to `src/docpipe_maestro/types.py` or root `docpipe_maestro.__all__` (`36` exports remain fixed). Existing shared intake data shapes (`ParsedDocument`, `ParsedSection`, `ParsedClause`) carry all new formats cleanly.

| Format Key | Extensions | Install Scope | Lazy Parser Class | Container / Magic Check |
|---|---|---|---|---|
| `"csv"` | `(".csv",)` | Core (stdlib `csv`) | `CsvParser` (`delimited.py`) | Strict `utf-8-sig`, zero NUL bytes |
| `"tsv"` | `(".tsv",)` | Core (stdlib `csv`) | `TsvParser` (`delimited.py`) | Strict `utf-8-sig`, zero NUL bytes |
| `"xlsx"` | `(".xlsx",)` | Optional `[xlsx]` | `XlsxParser` (`xlsx.py`) | `PK\x03\x04` + `xl/workbook.xml` + `<= 256 MiB` uncompressed |
| `"pptx"` | `(".pptx",)` | Optional `[pptx]` | `PptxParser` (`pptx.py`) | `PK\x03\x04` + `ppt/presentation.xml` + `<= 256 MiB` uncompressed |
| `"epub"` | `(".epub",)` | Optional `[epub]` | `EpubParser` (`epub.py`) | `PK\x03\x04` + `META-INF/container.xml` + `<= 256 MiB` uncompressed |
| `"rst"` | `(".rst",)` | Optional `[rst]` | `RstParser` (`rst.py`) | Strict `utf-8-sig` (after optional lib check) |

### Extension & Priority Mapping Rules
- `_BUILTIN_PARSER_KEYS` (`src/docpipe_maestro/_resolve.py`) expands from `{"docx", "html", "md", "pdf", "txt"}` to `{"csv", "docx", "epub", "html", "md", "pdf", "pptx", "rst", "tsv", "txt", "xlsx"}`.
- `SUPPORTED_EXTENSIONS` (`src/docpipe_maestro/ingest/intake/_common.py`) adds `".csv"`, `".tsv"`, `".xlsx"`, `".pptx"`, `".epub"`, `".rst"`.
- Custom `@register_parser(...)` extensions take precedence over built-in keys cleanly via sorted custom-first iteration in `resolve_parser()`.

---

## 2. Format-to-`ParsedDocument` Structural Mapping

### A. Tabular Windowing (`.csv`, `.tsv`, `.xlsx`)
- **Row Window Size**: Constant `25` consecutive non-empty data rows per `ParsedSection`.
- **Header Extraction & Trailing Blank Trimming**: Strip trailing empty/`None`/whitespace-only cells from header and row sequences (preventing Excel `XFD` empty trailing column bloat); first non-empty row defines column names (fallback `Column {index + 1}` for internal blank header cells or ragged extra cells beyond header length).
- **Row Line Format**: `" | ".join(f"{header}: {value}" for ...)` omitting blank cells in that row.
- **`ParsedSection` Attributes**:
  - `.csv` / `.tsv`: `source=source_key`, `section_label=f"{source_key} (Rows {start}-{end})"`, `heading_level=1`, `raw_text="\n".join(rows)`, `page=None`.
  - `.xlsx`: Visible sheets only (`sheet_state == "visible"`); `source=source_key`, `section_label=f"{sheet_title} (Rows {start}-{end})"`, `heading_level=1`, `raw_text="\n".join(rows)`, `page=None`.
- **Empty / Header-Only Behavior**: Returns `ParsedDocument(source=source_key, format_name=..., sections=[])` cleanly (uniform with existing `txt`, `md`, `html`, `docx`, `pdf` parsers).

### B. Presentation Slides (`.pptx`)
- **Slide Grouping**: One `ParsedSection` per non-empty slide in presentation order.
- **`ParsedSection` Attributes**: `source=source_key`, `section_label=slide_title` (fallback `f"Slide {slide_num}"`), `heading_level=1`, `raw_text=body_and_notes`, `page=slide_num` (`1`-based).
- **Shape Traversal**: Paragraphs (recursive inside grouped shapes), tables (`" | ".join(cells)`), and optional `[Speaker Notes]` block when `notes_text_frame` is non-empty.

### C. Digital Book Chapters (`.epub`)
- **Chapter Traversal**: Ordered spine document items (`ITEM_DOCUMENT`) decoded as UTF-8/BOM HTML with `<script>`, `<style>`, `<nav>`, `<footer>`, `<noscript>`, `<template>`, `<svg>`, and hidden elements (`hidden`, `aria-hidden="true"`, `display:none`/`visibility:hidden`) stripped before section extraction.
- **`ParsedSection` Attributes**: Heading hierarchy (`<h1>`–`<h6>`) sets `section_label` and `heading_level`; fallback label uses spine title or `Chapter {idx}`; `page=None`.

### D. reStructuredText Sections (`.rst`)
- **Doctree Traversal**: `publish_doctree` with `file_insertion_enabled=False`, `raw_enabled=False`, offline `report_level=5`, `halt_level=5`, suppressed warning stream.
- **`ParsedSection` Attributes**: Section nodes yield `section_label=title`, `heading_level=depth` (clamped `1..6`), paragraphs, lists, tables (`" | ".join(cells)`), literal blocks, and admonitions; body preceding any heading uses `"Introduction"` (`heading_level=1`); `page=None`.

---

## 3. Validation & Error Semantics

| Condition | Exception / Outcome |
|---|---|
| Missing optional package (`openpyxl`, `pptx`, `ebooklib`, `docutils`) | `MissingExtraError` naming exact extra & install command |
| Legacy binary office extension (`.xls`, `.ppt`), extensionless OLE2 `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1`, or unknown extension | `UnsupportedFormatError` |
| Unrecognized extensionless binary or non-UTF-8 `.csv`/`.tsv`/`.rst` | `UnsupportedFormatError` |
| Corrupt ZIP, missing required inner XML marker, or uncompressed size `> 256 MiB` (checked in one pass by shared `_inspect_zip_container` helper for both `detect_format` and `_validate_zip_container`) | `UnsupportedFormatError` |
| Malformed library parse failure (`BadZipFile`, `InvalidFileException`, `EpubException`, etc.) | `UnsupportedFormatError` (wrapping exception cleanly, never swallowing `MissingExtraError`) |
| Valid file containing `0` extractable text rows/slides/chapters/sections | `ParsedDocument(..., sections=[])` (zero store mutations / `0` rows indexed) |

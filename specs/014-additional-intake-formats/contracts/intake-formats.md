# Contract: Additional Document Formats (`014-additional-intake-formats`)

**Feature Branch**: `014-additional-intake-formats` | **Date**: 2026-11-17

---

## 1. Public & Semi-Public Interfaces

### Root Package (`docpipe_maestro`)
- `__all__` stays strictly locked at **`36` exports** (verified by `tests/test_api_stability.py`).
- Existing public functions `ingest()`, `sync()`, `remove()`, `status()`, `reindex()`, `retrieve()`, `evaluate()` accept `.csv`, `.tsv`, `.xlsx`, `.pptx`, `.epub`, `.rst` files automatically with zero signature changes.
- **Empty Documents Contract**: Matches all 5 existing built-in parsers (`txt`, `md`, `html`, `docx`, `pdf`) and preserves the locked `36`-export contract: valid empty, blank-only, or header-only files return `ParsedDocument(source=source_key, format_name=..., sections=[])` cleanly (`0` indexed rows), while invalid/corrupt inputs raise `UnsupportedFormatError`.

### Intake Subpackage (`docpipe_maestro.ingest.intake`)
Exports updated cleanly via lazy wrappers:
- `SUPPORTED_EXTENSIONS` includes: `".md"`, `".markdown"`, `".txt"`, `".html"`, `".htm"`, `".pdf"`, `".docx"`, `".csv"`, `".tsv"`, `".xlsx"`, `".pptx"`, `".epub"`, `".rst"`.
- `PARSERS` registers lazy builtins: `"csv"`, `"tsv"`, `"xlsx"`, `"pptx"`, `"epub"`, `"rst"`.
- `CsvParser`, `TsvParser`, `XlsxParser`, `PptxParser`, `EpubParser`, `RstParser` resolve lazily via `__getattr__` / `_LAZY_PARSER_EXPORTS` and `parse_file(path, source_key=...)`.

---

## 2. Optional Dependencies (`pyproject.toml`)

```toml
[project.optional-dependencies]
pdf = ["pypdf>=6.21.3"]
docx = ["python-docx>=1.1.0"]
html = ["beautifulsoup4>=4.12.0"]
xlsx = ["openpyxl>=3.1.0"]
pptx = ["python-pptx>=1.0.0"]
epub = ["ebooklib>=0.18"]
rst = ["docutils>=0.20"]
rerank = ["sentence-transformers>=3.0.0"]
pii = ["presidio-analyzer>=2.2.0", "presidio-anonymizer>=2.2.0"]
all = [
    "docpipe-maestro[pdf]",
    "docpipe-maestro[docx]",
    "docpipe-maestro[html]",
    "docpipe-maestro[xlsx]",
    "docpipe-maestro[pptx]",
    "docpipe-maestro[epub]",
    "docpipe-maestro[rst]",
]
```

### Missing-Extra Contract
When an optional extra package cannot be imported inside its parser:
- `"xlsx"` → `MissingExtraError("XLSX support requires the 'xlsx' extra: pip install 'docpipe-maestro[xlsx]'")`
- `"pptx"` → `MissingExtraError("PPTX support requires the 'pptx' extra: pip install 'docpipe-maestro[pptx]'")`
- `"epub"` → `MissingExtraError("EPUB support requires the 'epub' extra: pip install 'docpipe-maestro[epub]'")`
- `"rst"` → `MissingExtraError("RST support requires the 'rst' extra: pip install 'docpipe-maestro[rst]'")`

Notice: In `parse(path, source_key=...)`, check the optional import **before** opening/parsing with that third-party library so `minimal-core` (no optional extras installed) ALWAYS raises `MissingExtraError` cleanly even when tested on dummy/minimal fixture bytes!

---

## 3. Container, Tabular & Security Contract

1. **Single-Pass Archive Validation**: Any `PK\x03\x04` file routed as `docx`, `xlsx`, `pptx`, or `epub` — or inspected extensionlessly by `detect_format()` — checks `total_uncompressed <= 256 * 1024 * 1024` bytes **once** via `_inspect_zip_container` prior to checking the required marker (`word/document.xml`, `xl/workbook.xml`, `ppt/presentation.xml`, `META-INF/container.xml`). Generic extensionless ZIPs and legacy OLE2 `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1` binaries raise `UnsupportedFormatError`.
2. **Hidden Content Filtering & Blank Column Trimming**:
   - `.csv`/`.tsv`/`.xlsx`: trim trailing `None`/whitespace-only columns from headers and rows so Excel `XFD` empty tail formatting never bloats `Header: Value` rows.
   - `.xlsx`: skip worksheets where `ws.sheet_state != "visible"`.
   - `.epub`: strip `<script>`, `<style>`, `<nav>`, `<footer>`, `<noscript>`, `<template>`, `<svg>`, `[hidden]`, `[aria-hidden="true"]`, `display:none`, `visibility:hidden`.
3. **reStructuredText Safety & Fallback**: `file_insertion_enabled=False`, `raw_enabled=False`, `report_level=5`, and `halt_level=5` are always enforced on docutils parser settings so `.. include:: /etc/passwd` never reads filesystem files and minor syntax warnings stay silent; headingless prose falls back to `section_label="Introduction"`, `heading_level=1`.
4. **Corrupt / Unsupported Legacy Files**: `.xls`, `.ppt` (and OLE2 binary bytes), invalid UTF-8 CSV/TSV/RST, malformed ZIPs, and generic ZIPs raise `UnsupportedFormatError`.
5. **CLI & Transactional Parity**: CLI `ingest`, `sync` (including `--dry-run`), `reindex`, `query`, `ask` (including `--stream`), and `eval` work transparently across all formats; failures abort cleanly without leaving partial store/manifest writes.

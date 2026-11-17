# Implementation Plan: Additional Document Formats

**Branch**: `014-additional-intake-formats` (local repo currently on `main` @ `93f5302`; create `feat/014-additional-intake-formats` prior to implementation) | **Date**: 2026-11-17 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/014-additional-intake-formats/spec.md`

## Summary

Add Phase 1 ingestion support for `.csv`/`.tsv` in the zero-dependency core and `.xlsx`, `.pptx`, `.epub`, and `.rst` behind isolated lazy optional extras (`xlsx`, `pptx`, `epub`, `rst`, plus expanded `all`), generalized ZIP-bomb/container validation in `_common.py`, strict UTF-8 delimited decoding with 25-row bounded `Header: Value` sections, hidden-sheet/hidden-HTML stripping, `.rst` local file-inclusion disabling, `minimal-core` CI parity, and full user-facing documentation updates while preserving `len(docpipe_maestro.__all__) == 36`.

## Technical Context

**Language/Version**: Python `>=3.10` (`3.10`–`3.13` tested in CI; strict typing via `mypy --strict`)  
**Primary Dependencies**: Core uses stdlib `csv`, `zipfile`, `html.parser`, `io`; optional extras add `openpyxl>=3.1.0` (`xlsx`), `python-pptx>=1.0.0` (`pptx`), `ebooklib>=0.18` (`epub`), `docutils>=0.20` (`rst`)  
**Storage**: Existing ChromaDB `PersistentClient` + collocated SQLite FTS5 & ingestion manifest (zero schema changes)  
**Testing**: `pytest` + `pytest-cov` (`fail_under = 80`), `@pytest.mark.reverse`, `@pytest.mark.pii`, `minimal-core` CI verification  
**Target Platform**: Cross-platform (`linux`, `macos`, `windows`) running comfortably within `< 16 GiB` RAM / offline local environments  
**Project Type**: Minimal two-phase Python library (`docpipe_maestro`) + CLI (`docpipe-maestro`)  
**Performance Goals**: Streaming `openpyxl` (`read_only=True`) and bounded `25`-row tabular `ParsedSection` windows prevent memory bloat and oversized parent-chunk expansion  
**Constraints**: Root `docpipe_maestro.__all__` fixed at `36` exports; zero eager optional imports; ZIP uncompressed ceiling `256 MiB`; `file_insertion_enabled=False` & `raw_enabled=False` on `.rst`; strict UTF-8 / UTF-8-SIG decoding  
**Scale/Scope**: 6 new extensions (`csv`, `tsv`, `xlsx`, `pptx`, `epub`, `rst`), 5 new lazy parser modules, generalized container security helpers, packaging/CI updates, unit/integration/security tests, and 100% user-facing docs parity

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Verification |
|---|---|---|
| **I. Engine Scope (`v1.4.0`)** | Pass | Pure Phase 1 additive intake parsers; zero server/UI/session/auth code; OCR (`1.3`) excluded. |
| **II. Strict Two-Phase Separation** | Pass | Changes scoped exclusively to Phase 1 (`src/docpipe_maestro/ingest/intake/` & `_resolve.py` routing); Phase 2 remains strictly read-only. |
| **III. Library Purity & No Hardcoded Provider Registries** | Pass | Parsers read only supplied `Path`; `PARSERS` uses existing `Registry` lazy registration; zero config file reads in library modules. |
| **IV. Schema Single Source (`types.py`)** | Pass (with Gate Note below) | Reuses existing `ParsedDocument`, `ParsedSection`, `MissingExtraError`, `UnsupportedFormatError`; zero parallel schemas. |
| **V. Fail-Loud Errors & Security** | Pass | Missing extras raise `MissingExtraError`; corrupt ZIPs, oversized containers, legacy `.xls`/`.ppt`, non-UTF-8 bytes, and invalid files raise `UnsupportedFormatError`; `.rst` file insertion disabled; hidden Excel/EPUB content skipped. |
| **VI. Offline / Local-Only Compatibility** | Pass | Zero network calls in all intake parsers (`docutils` local file/network insertion disabled; EPUB offline HTML extraction via stdlib `HTMLParser`). |
| **VII. Structured Correctness Over Speed** | Pass | Preserves sheet/slide/chapter/heading provenance (`section_label`, `heading_level`, `page`) and bounded `25`-row `Header: Value` sections. |
| **Footprint & `36`-Export API Lock** | Pass (with Gate Note below) | `docpipe_maestro.__all__` remains `36` exports; `[all]` excludes heavy ML extras (`rerank`, `pii`); additive intake registration + zero eager imports tested via `test_library_purity.py`. |

### Empty-Document Gate Resolution (`C1` — Resolved)

- **Context**: Earlier drafts referenced `"empty-document error"` (`EmptyDocumentError`), whereas `src/docpipe_maestro/types.py` defines no `EmptyDocumentError`, `tests/test_api_stability.py` locks `len(__all__) == 36`, all 5 existing parsers (`TextParser`, `MarkdownParser`, `HtmlParser`, `PdfParser`, `DocxParser`) return `ParsedDocument(source=source_key, format_name=..., sections=[])`, and `tests/test_hybrid_search.py` expects empty-file `ingest` to succeed with `0` indexed rows.
- **Resolution Applied**: Reconciled `spec.md` (`US1.3`, `US3.3`, `FR-002`, `FR-008`, `SC-004`, `Assumptions`), `plan.md`, and `tasks.md` so all valid zero-content/blank-only/header-only documents uniformly return `ParsedDocument(..., sections=[])` (zero store/row bloat while preserving `36` root exports), whereas invalid UTF-8, corrupt archives, ZIP bombs, and legacy `.xls`/`.ppt` binaries raise `UnsupportedFormatError`.

## Project Structure

### Documentation (this feature)

```text
specs/014-additional-intake-formats/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── intake-formats.md
├── checklists/
│   └── requirements.md
└── spec.md
```

### Source Code (repository root)

```text
pyproject.toml                                    # Add xlsx, pptx, epub, rst extras, expand all, mypy overrides
uv.lock                                           # Locked dependency resolution update
.github/workflows/ci.yml                          # Align minimal-core job with csv/tsv core + MissingExtraError on new extras

src/docpipe_maestro/
├── _resolve.py                                   # Expand _BUILTIN_PARSER_KEYS with csv, tsv, xlsx, pptx, epub, rst
└── ingest/intake/
    ├── __init__.py                               # Register lazy parsers & _LAZY_PARSER_EXPORTS + TYPE_CHECKING
    ├── _common.py                                # SUPPORTED_EXTENSIONS, generalized _validate_zip_container, detect_format, tabular row helper
    ├── docx.py                                   # Use generalized _validate_zip_container
    ├── delimited.py                              # Core CsvParser & TsvParser (zero third-party deps)
    ├── xlsx.py                                   # Optional [xlsx] XlsxParser via openpyxl
    ├── pptx.py                                   # Optional [pptx] PptxParser via python-pptx
    ├── epub.py                                   # Optional [epub] EpubParser via ebooklib + hardened stdlib HTMLParser
    └── rst.py                                    # Optional [rst] RstParser via docutils with file_insertion/raw disabled

tests/
├── test_intake_delimited.py                      # Core CSV/TSV unit/edge tests executed in minimal-core CI (UTF-8 BOM, ragged rows, invalid encoding, empty)
├── test_intake_formats_optional.py               # Optional XLSX/PPTX/EPUB/RST extraction, MissingExtraError, security & lifecycle tests
├── test_api_stability.py                         # 36 exports invariant, new lazy intake symbols & SUPPORTED_EXTENSIONS assertions
├── test_library_purity.py                        # Assert zero eager imports of openpyxl, pptx, ebooklib, docutils
└── test_security_hardening.py                    # ZIP bomb, spoofed/extensionless ZIP, OLE2 .xls/.ppt, RST include blocking, hidden Excel/EPUB

README.md, PRODUCT.md, docs/*, CHANGELOG.md       # Complete FR-011 user-facing docs parity
```

**Structure Decision**: Additive strategy modules cleanly isolated inside existing `src/docpipe_maestro/ingest/intake/`, preserving core API boundaries and `docpipe_maestro.__all__` (`36` exports).

## Complexity Tracking

| Consideration | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Dedicated `delimited.py` module & `test_intake_delimited.py` suite | Implements core `.csv`/`.tsv` without shadowing stdlib `csv` and keeps core delimited tests active inside `minimal-core` CI (`test_intake_clean.py` is ignored there for `[pdf]/[docx]/[html]` tests) | Naming `csv.py` shadows stdlib `csv`, and placing CSV/TSV tests inside `test_intake_clean.py` skips them during `minimal-core` runs |
| Stdlib `HTMLParser` helper in `epub.py` | `[epub]` extra depends only on `ebooklib>=0.18` (not `beautifulsoup4`) | Reusing `HtmlParser`'s `bs4` import would cause `docpipe-maestro[epub]` standalone installs to fail unless `[html]` were pulled in |
| Uniform empty `sections=[]` return | Preserves `36` exports invariant and `Txt/Md/Html/Pdf/Docx` directory-ingest parity | Raising `EmptyDocumentError` creates an unexported exception or violates `36`-export stability and `test_hybrid_search.py` |

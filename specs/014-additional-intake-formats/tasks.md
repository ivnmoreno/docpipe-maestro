---

description: "Task list for feature implementation: 014-additional-intake-formats"
---

# Tasks: Additional Document Formats (`014-additional-intake-formats`)

**Input**: Design documents from `specs/014-additional-intake-formats/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/intake-formats.md`, `quickstart.md`

**Organization**: Tasks are grouped by user story (`US1`–`US4`) so core CSV/TSV support (`US1`), lazy optional packaging & guards (`US2`), rich structured extraction & hardening (`US3`), and CI/docs parity (`US4`) can each be verified independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story from `spec.md` (`[US1]`, `[US2]`, `[US3]`, `[US4]`)
- **Empty-Document Note**: Reconciled via `/speckit-analyze` (`C1`): empty/header-only/blank valid inputs return `ParsedDocument(..., sections=[])` uniformly across formats to preserve `36` exports and existing empty-file tests.

---

## Phase 1: Setup (Shared Infrastructure & Packaging Baseline)

**Purpose**: Establish branch, dependency groups, typing overrides, and lockfile parity.

- [X] T001 Create branch `feat/014-additional-intake-formats` from `main` (`93f5302`) and verify baseline `uv lock --check` & `uv run --no-sync ruff check .` from `pyproject.toml`
- [X] T002 Add optional extras (`xlsx = ["openpyxl>=3.1.0"]`, `pptx = ["python-pptx>=1.0.0"]`, `epub = ["ebooklib>=0.18"]`, `rst = ["docutils>=0.20"]`), extend `all` extra (`pdf`, `docx`, `html`, `xlsx`, `pptx`, `epub`, `rst` excluding heavy ML/NER extras), add mypy `ignore_missing_imports` overrides (`"openpyxl.*"`, `"pptx.*"`, `"ebooklib.*"`, `"docutils.*"`), regenerate `uv.lock`, and run `uv sync --locked --all-extras --group dev` in `pyproject.toml`

---

## Phase 2: Foundational (Shared Intake Infrastructure & Registry Contracts)

**Purpose**: Generalized ZIP validation, delimited row-window helpers, extension registry, and custom-over-builtin routing required across all user stories.

**⚠️ CRITICAL**: No user story parser or test work begins until this phase completes.

- [X] T003 Implement single-pass ZIP inspector `_inspect_zip_container(path, *, source_key, max_bytes=256 * 1024 * 1024)` enforcing uncompressed size limit before archive-marker inspection, expose `_validate_zip_container(path, *, source_key, required_entry, max_bytes=256 * 1024 * 1024)` (keeping `_validate_docx_zip` alias if needed), implement `_format_tabular_sections(rows, *, source_key, section_prefix, rows_per_section=25)` (trimming trailing `None`/whitespace-only cells from header and row slices, `"Header: Value"` pairs with `"Column {i}"` fallback, 25-row section windows, returning `[]` on zero non-empty data rows), expand `SUPPORTED_EXTENSIONS` (`".csv"`, `".tsv"`, `".xlsx"`, `".pptx"`, `".epub"`, `".rst"`), and update `detect_format(path)` (extension mapping, extensionless `PK\x03\x04` inspection via `_inspect_zip_container` for `word/document.xml`/`xl/workbook.xml`/`ppt/presentation.xml`/`META-INF/container.xml`, OLE2 `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1` `.xls`/`.ppt` rejection on both typed & extensionless files, and generic ZIP rejection) in `src/docpipe_maestro/ingest/intake/_common.py` and `src/docpipe_maestro/ingest/intake/docx.py`
- [X] T004 [P] Update `_BUILTIN_PARSER_KEYS` (`{"csv", "docx", "epub", "html", "md", "pdf", "pptx", "rst", "tsv", "txt", "xlsx"}`) in `src/docpipe_maestro/_resolve.py` and register lazy built-ins (`PARSERS.register_lazy`, `_LAZY_PARSER_EXPORTS`, `TYPE_CHECKING`, `__all__`) for `CsvParser`, `TsvParser`, `XlsxParser`, `PptxParser`, `EpubParser`, and `RstParser` in `src/docpipe_maestro/ingest/intake/__init__.py` without altering `36` exports in `src/docpipe_maestro/__init__.py`

**Checkpoint**: Shared container security, tabular windowing, format detection, and lazy parser routing ready.

---

## Phase 3: User Story 1 — Zero-Dependency Core CSV & TSV Ingestion (Priority: P1) 🎯 MVP

**Goal**: Enable built-in `.csv` and `.tsv` ingestion in core installs with zero third-party parser dependencies, bounded 25-row `Header: Value` sections, strict UTF-8 / UTF-8-SIG validation, and ragged-row tolerance.

**Independent Test**: Core `.csv`/`.tsv` parsing, strict UTF-8 decoding errors, ragged rows, empty/header-only inputs, custom override precedence, and `ingest`/`sync`/`retrieve` work offline without optional extras (`tests/test_intake_delimited.py`, executed in `minimal-core` CI).

### Tests for User Story 1

- [X] T005 [P] [US1] Create `tests/test_intake_delimited.py` (un-ignored in `minimal-core` CI) covering `.csv`/`.tsv` UTF-8 & UTF-8-SIG BOM decoding, 25-row bounded sections (`<filename> (Rows 1-25)`), `Header: Value` cell pairs, ragged shorter/wider rows (`Column N`), trailing blank column trimming, blank/header-only inputs returning `sections=[]`, invalid UTF-8 / Windows-1252 / NUL-byte `UnsupportedFormatError`, custom `@register_parser` override precedence, and `ingest`/`sync`/`retrieve` lifecycle

### Implementation for User Story 1

- [X] T006 [US1] Implement stdlib `csv`-backed `CsvParser` (`delimiter=","`) and `TsvParser` (`delimiter="\t"`) enforcing strict `utf-8-sig` decoding + NUL-byte pre-check (`UnsupportedFormatError`) and delegating 25-row `Header: Value` section construction to `_format_tabular_sections(...)` in `src/docpipe_maestro/ingest/intake/delimited.py`

**Checkpoint**: User Story 1 MVP works independently in core-only environments.

---

## Phase 4: User Story 2 — Optional Format Extras, Lazy Loading & Fail-Loud Dependency Guards (Priority: P1)

**Goal**: Guarantee zero eager loading of `openpyxl`, `python-pptx`, `ebooklib`, or `docutils`, preserve `36` root exports, and fail loudly with exact `MissingExtraError` hints prior to any store/manifest mutation.

**Independent Test**: Subprocess purity assertions (`tests/test_library_purity.py`), root API/intake surface checks (`tests/test_api_stability.py`), and missing-extra failure checks with mocked uninstalled packages (`tests/test_intake_formats_optional.py`).

### Tests for User Story 2 (TDD Fail-First Before T009)

> **NOTE**: `T007` and `T008` expect initial collection/import failures on the 4 new parser classes until `T009` creates their lazy stubs.

- [X] T007 [P] [US2] Add zero-eager-import guards (`openpyxl`, `pptx`, `ebooklib`, `docutils` not in `sys.modules` on `import docpipe_maestro` & CLI build) in `tests/test_library_purity.py` and assert `len(root.__all__) == 36`, updated `SUPPORTED_EXTENSIONS`, and lazy intake parser exports (`CsvParser`, `TsvParser`, `XlsxParser`, `PptxParser`, `EpubParser`, `RstParser`) in `tests/test_api_stability.py`
- [X] T008 [P] [US2] Add fail-loud `MissingExtraError` tests verifying exact install instructions (`docpipe-maestro[xlsx|pptx|epub|rst]`) and zero vector-store/manifest writes when optional dependencies are shadowed (`None` in `sys.modules`) in `tests/test_intake_formats_optional.py`

### Implementation for User Story 2

- [X] T009 [US2] Create lazy-imported parser entrypoints (`XlsxParser`, `PptxParser`, `EpubParser`, `RstParser`) with fail-loud `MissingExtraError` import guards ahead of any library/container parse calls in `src/docpipe_maestro/ingest/intake/xlsx.py`, `src/docpipe_maestro/ingest/intake/pptx.py`, `src/docpipe_maestro/ingest/intake/epub.py`, and `src/docpipe_maestro/ingest/intake/rst.py`

**Checkpoint**: Lazy imports, `36`-export stability, and fail-loud `MissingExtraError` contracts verified before store/manifest side effects.

---

## Phase 5: User Story 3 — Structure-Aware Extraction & Security Hardening for Rich Formats (Priority: P2)

**Goal**: Extract structure-aware `ParsedSection` provenance across `.xlsx`, `.pptx`, `.epub`, and `.rst` while skipping hidden sheets/HTML and enforcing ZIP-bomb, extensionless container, legacy OLE2 binary, and disabled `.rst` file-inclusion protections.

**Independent Test**: Offline multi-part fixtures (`tests/test_intake_formats_optional.py`) and adversarial security/corruption suite (`tests/test_security_hardening.py`) pass with `0` crashes, `0` partial store writes, and `0` unauthorized file reads.

### Tests for User Story 3

- [X] T010 [P] [US3] Add offline fixture extraction, provenance (`section_label`, `heading_level`, `page`), visible-only `.xlsx` sheet filtering, trailing blank column trimming, cached formula (`data_only=True`) handling, slide/table/group-shape/speaker-note `.pptx` tests, spine `.epub` chapter tests, `.rst` heading & `"Introduction"` fallback tests, blank-input `sections=[]` tests, and incremental `ingest`/`sync`/`--dry-run`/`retrieve`/`PiiEnricher` lifecycle tests in `tests/test_intake_formats_optional.py`
- [X] T011 [P] [US3] Add security and malformed-input tests covering `> 256 MiB` uncompressed ZIP bombs across typed & extensionless `.xlsx`/`.pptx`/`.epub` containers, extensionless ZIP container disambiguation vs generic `.zip` rejection, OLE2 legacy `.xls`/`.ppt` rejection (`UnsupportedFormatError`), corrupt archive / malformed UTF-8 `.rst` rejection, hidden `.xlsx` sheet & hidden `.epub` HTML suppression, and blocked `.rst` `.. include::` / `.. raw::` filesystem traversal in `tests/test_security_hardening.py`

### Implementation for User Story 3

- [X] T012 [P] [US3] Implement structure-aware `.xlsx` extraction in `src/docpipe_maestro/ingest/intake/xlsx.py` (`_validate_zip_container` checking `xl/workbook.xml`, `openpyxl.load_workbook(..., read_only=True, data_only=True)` closed in `finally:`, skipping `ws.sheet_state != "visible"`, trimming formatted empty trailing Excel columns & normalizing scalar cell values via `ws.iter_rows(values_only=True)`, and delegating 25-row `Header: Value` sections to `_format_tabular_sections(..., section_prefix=ws.title)`)
- [X] T013 [P] [US3] Implement structure-aware `.pptx` extraction in `src/docpipe_maestro/ingest/intake/pptx.py` (`_validate_zip_container` checking `ppt/presentation.xml`, 1-based slide `page` numbers, slide title fallback `f"Slide {idx + 1}"`, recursive group-shape/text-frame/table traversal, and optional `Speaker Notes:` block)
- [X] T014 [P] [US3] Implement structure-aware `.epub` extraction in `src/docpipe_maestro/ingest/intake/epub.py` (`_validate_zip_container` checking `META-INF/container.xml`, iterating ordered `ITEM_DOCUMENT` spine items from `ebooklib.epub.read_epub`, and extracting headings/prose with an offline stdlib `html.parser.HTMLParser` helper that strips `<script>`, `<style>`, `<nav>`, `<footer>`, `<noscript>`, `<template>`, `<svg>`, `[hidden]`, `[aria-hidden="true"]`, `display:none`, `visibility:hidden` with zero `beautifulsoup4` dependency)
- [X] T015 [P] [US3] Implement structure-aware `.rst` extraction in `src/docpipe_maestro/ingest/intake/rst.py` (strict `utf-8-sig` decode, offline `publish_doctree` with `{"file_insertion_enabled": False, "raw_enabled": False, "report_level": 5, "halt_level": 5, "warning_stream": io.StringIO()}`, recursive `section`/`title` traversal preserving `heading_level`, `"Introduction"` fallback label for headingless prose, paragraphs, lists, literal blocks, admonitions, and tables)

**Checkpoint**: All 6 new document formats extract clean structure and pass container, encoding, and file-inclusion hardening.

---

## Phase 6: User Story 4 — Minimal-Core Verification & User-Facing Documentation Parity (Priority: P3)

**Goal**: Align CI `minimal-core` workflow verification and update every user-facing document in the repository.

**Independent Test**: `minimal-core` workflow commands execute `tests/test_intake_delimited.py` plus `.csv`/`.tsv` & `MissingExtraError` across all 7 optional format extensions, and docs audit confirms `100%` of user-facing docs match implementation.

- [X] T016 [US4] Update `minimal-core` job in `.github/workflows/ci.yml` (add `--ignore=tests/test_intake_formats_optional.py` while keeping `tests/test_intake_delimited.py` active, assert core `.csv`/`.tsv` ingestion & retrieval succeeds with zero optional extras installed, and assert `MissingExtraError` across `.pdf`, `.docx`, `.html`, `.xlsx`, `.pptx`, `.epub`, `.rst`)
- [X] T017 [P] [US4] Update EVERY user-facing file per `FR-011` (`README.md`, `PRODUCT.md`, `docs/README.md`, `docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/development.md`, `docs/future-features.md` §1.2 & matrix row `*Implemented* (014-additional-intake-formats)`, and `CHANGELOG.md` `## Unreleased`)

---

## Phase 7: Polish, Cross-Cutting Cleanup & Full Safety/Coverage Gates

**Purpose**: Final refactoring check, formatting, static checks, quickstart execution, and resource-safe full test suite verification.

- [X] T018 Audit shared helpers, docstrings, edge-case guards, and code style across `src/docpipe_maestro/ingest/intake/` and `src/docpipe_maestro/_resolve.py`
- [X] T019 Run validation scenarios from `specs/014-additional-intake-formats/quickstart.md` and ALL full quality/safety/coverage gates under resource-safe cgroup caps (`uv lock --check`, `uv run --no-sync ruff format --check .`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff check --select S src/`, `uv run --no-sync mypy src tests`, `uv run --no-sync pytest -m reverse -v`, `uv run --no-sync pytest -m pii -v`, and combined `LITELLM_LOCAL_MODEL_COST_MAP=true pytest -v --cov` across all test files passing `100%` with `>= 80%` branch coverage)

---

## Dependencies & Execution Order

### Phase Dependencies

1. **Setup (`Phase 1`: `T001`–`T002`)**: Starts immediately on `main` (`93f5302`), creates branch `feat/014-additional-intake-formats`, locks & syncs dependencies.
2. **Foundational (`Phase 2`: `T003`–`T004`)**: Depends on `T002`; BLOCKS all user stories (`US1`–`US4`).
3. **User Story 1 (`Phase 3`: `T005`–`T006`, P1 MVP)**: Depends on Phase 2; delivers core `.csv`/`.tsv` independently.
4. **User Story 2 (`Phase 4`: `T007`–`T009`, P1)**: Depends on Phase 2; verifies zero eager imports, `36`-export stability, and fail-loud `MissingExtraError` stubs.
5. **User Story 3 (`Phase 5`: `T010`–`T015`, P2)**: Depends on `T009` (`T012`–`T015` fill in the 4 optional parser files in parallel; `T010`–`T011` run independently in parallel).
6. **User Story 4 (`Phase 6`: `T016`–`T017`, P3)**: `T016` depends on `US1`–`US2` contracts (`minimal-core` & `MissingExtraError`); `T017` can execute alongside `US3` completion before final gates.
7. **Polish & Gates (`Phase 7`: `T018`–`T019`)**: Depends on Phases 1–6 completion; mandatory full verification pass before completion report.

### Parallel Examples

```text
# Phase 2 parallel tasks:
T003 (_common.py + docx.py)  ||  T004 (_resolve.py + intake/__init__.py)

# Phase 5 parallel rich parser implementations (different files):
T012 (xlsx.py)  ||  T013 (pptx.py)  ||  T014 (epub.py)  ||  T015 (rst.py)

# Phase 5 parallel test additions (different files):
T010 (test_intake_formats_optional.py)  ||  T011 (test_security_hardening.py)
```

---

## Implementation Strategy

- **MVP First (`T001`–`T006`)**: Ship zero-dependency core `.csv`/`.tsv` parsing and validate cleanly in isolation.
- **Safety & Dependency Boundaries Next (`T007`–`T009`)**: Lock down zero eager imports, `36` exports, and `MissingExtraError` guards before adding parser bodies.
- **Parallel Rich Format Expansion (`T010`–`T015`)**: Implement `.xlsx`, `.pptx`, `.epub`, and `.rst` extraction + security tests cleanly in parallel modules.
- **CI, Docs & Laptop-Safe Gates (`T016`–`T019`)**: Align `minimal-core` CI, update all user-facing docs, and run every check inside `systemd-run --user --scope` (`CPUQuota=300%`, `MemoryHigh=700M`, `MemoryMax=950M`, `MemorySwapMax=0`) with `0` failures.

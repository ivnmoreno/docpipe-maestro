# Feature Specification: Additional Document Formats

**Feature Branch**: `014-additional-intake-formats`  
**Created**: 2026-11-17  
**Status**: Draft  
**Input**: User description: "Implement roadmap item 1.2 (Additional Document Formats) under Constitution v1.4.0 so Phase 1 ingestion supports spreadsheets, presentations, digital books, reStructuredText, and delimited text cleanly without bloating core installs: 1. Core built-in CSV/TSV intake ... 2. Optional format extras & packaging ... 3. Additive lazy parsers & fail-loud dependency guards ... 4. Structure-aware extraction & archive/XXE safety parity ... 5. Minimal-core & documentation parity ... Keep OCR (1.3) and server/UI features strictly out of scope per Constitution Principle I."

## Clarifications

### Session 2026-11-17

- Q: How should the engine handle hidden worksheets in `.xlsx` spreadsheets and hidden HTML elements in `.epub` chapters during extraction? → A: Skip hidden and very-hidden `.xlsx` worksheets as well as hidden `.epub` HTML subtrees (`hidden`, `aria-hidden="true"`, `display:none`/`visibility:hidden`) by default.
- Q: How should multi-row tables in `.csv`, `.tsv`, and `.xlsx` worksheets be partitioned into sections and formatted for retrieval? → A: Group consecutive non-empty data rows into bounded 25-row window sections labeled with the row range (for example `<Source or Sheet> (Rows 1-25)`), formatting each row as `Header: Value` pairs.
- Q: How should `.csv` and `.tsv` intake handle files that contain non-UTF-8 byte sequences (such as legacy Windows-1252 spreadsheets vs corrupt binary files)? → A: Enforce strict UTF-8 / UTF-8-SIG decoding only and reject any invalid UTF-8 byte sequence (including legacy single-byte encodings or binary bytes) with a typed unsupported-format error.
- Q (Analyze Remediation C1): How should valid zero-content / header-only / blank files behave across new formats given `36` locked root exports and no `EmptyDocumentError` in `types.py`? → A: Return an empty section list cleanly (`0` indexed chunks/rows, matching existing plain-text, Markdown, HTML, PDF, and DOCX parsers and preserving `36` root exports), while malformed UTF-8, corrupt archives, ZIP bombs, and legacy binaries raise an unsupported-format error.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Zero-Dependency Core CSV & TSV Ingestion (Priority: P1)

As a user running the lean core installation of `docpipe-maestro` without any optional extras, I want to ingest `.csv` and `.tsv` tabular data files through the library and CLI so that spreadsheets exported as delimited text become searchable and citable alongside Markdown and plain text.

**Why this priority**: Delimited tables (`CSV` and `TSV`) are ubiquitous in enterprise exports and require zero third-party dependencies, delivering immediate core ingestion value with zero install bloat.

**Independent Test**: Can be fully tested in a core-only installation (with zero optional format packages installed) by ingesting, syncing, reindexing, querying, and asking grounded questions over `.csv` and `.tsv` files, plus verifying empty or malformed-encoding files fail with clear typed errors.

**Acceptance Scenarios**:

1. **Given** valid UTF-8 (including UTF-8 with BOM) `.csv` and `.tsv` files containing column headers and data rows, **When** a user runs ingestion, sync, or reindex, **Then** each data row retains its column header context alongside source provenance and becomes retrievable and citable by row/section.
2. **Given** a `.csv` or `.tsv` file with ragged rows (fewer or extra fields compared to the header row), **When** ingested, **Then** extra values and missing trailing cells are handled cleanly without crashing or silently corrupting subsequent rows.
3. **Given** an empty or header-only `.csv`/`.tsv` file with zero data rows, or a file containing invalid non-UTF-8 binary/encoded bytes, **When** ingested, **Then** valid empty inputs produce empty section lists cleanly (`0` indexed rows, consistent with plain text and Markdown) and invalid encodings fail loudly with an unsupported-format error.

---

### User Story 2 - Optional Format Extras, Lazy Loading & Fail-Loud Dependency Guards (Priority: P1)

As a maintainer or user, I want `.xlsx` spreadsheets, `.pptx` slide decks, `.epub` digital books, and `.rst` reStructuredText documents packaged as isolated optional installation groups (`xlsx`, `pptx`, `epub`, `rst`, plus an expanded `all` format bundle that keeps heavy ML/NER extras separate) so core installs stay small while missing extras produce clear installation guidance.

**Why this priority**: Constitution footprint rules mandate keeping core installations lean and free of heavy or rarely needed format dependencies, while preventing silent failures or confusing import tracebacks when users pass unsupported-until-installed files.

**Independent Test**: Can be tested cleanly by importing the package and inspecting loaded optional dependencies (confirming zero eager loads), passing `.xlsx`, `.pptx`, `.epub`, and `.rst` files in an environment lacking those extras to assert actionable missing-extra errors with exact install hints, and verifying the public export count remains locked at `36`.

**Acceptance Scenarios**:

1. **Given** an installation with only core dependencies (`csv`/`tsv` built in, no format extras installed), **When** a user imports the library or ingests Markdown, plain text, CSV, or TSV files, **Then** no optional format-parsing dependencies are loaded eagerly and all core operations succeed.
2. **Given** an installation lacking a format's optional extra, **When** a user attempts to ingest a `.xlsx`, `.pptx`, `.epub`, or `.rst` file, **Then** the engine fails loudly before writing to the vector store or manifest with a missing-extra error naming the exact optional extra install command (for example `pip install 'docpipe-maestro[xlsx]'`).
3. **Given** a user installs `docpipe-maestro[all]`, **When** resolving installation extras, **Then** all optional document format parsers (`pdf`, `docx`, `html`, `xlsx`, `pptx`, `epub`, `rst`) are included without automatically pulling heavy optional ML reranking or NER dependencies, and the public root export surface stays unchanged at `36` exports.

---

### User Story 3 - Structure-Aware Extraction & Security Hardening for Rich Formats (Priority: P2)

As an operator ingesting real-world enterprise corpora, I want `.xlsx`, `.pptx`, `.epub`, and `.rst` files to extract meaningful hierarchy (sheets, slides, chapters, sections) with source location provenance while defending against ZIP bombs, XXE/XML entity expansion, corrupted archives, and unsupported legacy binary formats.

**Why this priority**: Rich container formats share compressed archive and XML attack surfaces; extracting structure cleanly makes citations useful while archive and XML guards keep local ingestion safe on untrusted corpora.

**Independent Test**: Can be tested with synthetically constructed (offline) `.xlsx`, `.pptx`, `.epub`, and `.rst` fixtures (including multi-sheet/multi-slide/multi-chapter content, speaker notes, nested headings, corrupt archives, oversized ZIP entries, extensionless files identified by signature, and legacy `.xls`/`.ppt` bytes).

**Acceptance Scenarios**:

1. **Given** valid multi-part fixtures for each new format:
   - `.xlsx` workbook with multiple worksheets and header rows
   - `.pptx` presentation with numbered slides, titles, body text, and speaker notes
   - `.epub` book with ordered spine chapters and section titles
   - `.rst` document with multi-level section headings and paragraphs
   **When** ingested under core or policy profiles, **Then** the engine preserves structural hierarchy (sheet names and header-paired rows, slide numbers/titles and notes, chapter titles/order, and RST section headings/hierarchy) with non-empty source provenance suitable for chunking and citations.
2. **Given** an archive-based upload (`.xlsx`, `.pptx`, `.epub`, or an extensionless ZIP container) that is corrupted, spoofed, missing required internal structure, or exceeds uncompressed size limits, **When** detected or parsed, **Then** ingestion rejects it cleanly with a typed unsupported-format error before allocating excessive memory or modifying any stored collection.
3. **Given** legacy pre-XML binary office files (such as `.xls` or `.ppt`) or empty-content rich documents (such as a workbook with only blank cells or slides with no text), **When** ingested, **Then** legacy binary formats fail loudly with a clear unsupported-format error (never treated as valid modern containers or corrupted silently) and textless valid documents produce empty section lists cleanly (`0` indexed rows, consistent with plain text and Markdown).

---

### User Story 4 - Minimal-Core Verification & User-Facing Documentation Parity (Priority: P3)

As a contributor or end user consulting repository documentation and CI checks, I want core-only installation verification, full regression tests, and every user-facing document to accurately reflect the new built-in and optional document formats so documentation and runtime behavior stay aligned.

**Why this priority**: Keeps installation matrices, CLI/library docs, architecture diagrams, changelog, and backlog tracking synchronized with the codebase as explicitly requested.

**Independent Test**: Can be verified by checking the minimal-core test/smoke pipeline (core `.csv`/`.tsv` succeed, uninstalled extras raise missing-extra errors) alongside a complete documentation audit confirming all user-facing docs reflect `014`.

**Acceptance Scenarios**:

1. **Given** the minimal-core verification workflow (core package installed without optional format extras), **When** automated verification runs, **Then** `.csv` and `.tsv` intake succeeds end-to-end, uninstalled optional formats fail loudly with missing-extra errors, and the existing core suite passes cleanly.
2. **Given** all user-facing project documentation (`README.md`, `PRODUCT.md`, `docs/*`, and `CHANGELOG.md`), **When** implementation completes, **Then** supported format matrices, install extras (`xlsx`, `pptx`, `epub`, `rst`, expanded `all`), structural extraction rules, and roadmap completion status match the implemented behavior.

---

### Edge Cases

- What happens when an extensionless file begins with ZIP container magic bytes (`PK\x03\x04`) belonging to `.docx`, `.xlsx`, `.pptx`, `.epub`, or an unrelated generic ZIP (such as a `.zip` software bundle)? The detector MUST validate uncompressed size bounds in a single pass before distinguishing supported containers by inner marker and rejecting unrecognized ZIPs cleanly (and rejecting extensionless legacy binary signatures too).
- What happens when an `.xlsx` cell contains a formula (`=A1+B1`), numeric/date/boolean value, or formatted empty trailing columns up to worksheet bounds? Cached evaluated values (when available), formatted primitives, trimmed trailing blank header/row cells, and skipped completely blank rows/sheets MUST produce clean readable text without crashing or padding noise.
- What happens when an `.xlsx` sheet has blank leading rows or irregular row widths, or a `.csv`/`.tsv` file starts with UTF-8 BOM (`\ufeff`) or CRLF/LF line endings? BOM markers, trailing blank cells, and line endings MUST be normalized before parsing header names so column keys remain clean.
- What happens when a `.pptx` slide has shapes inside tables or grouped shapes or empty placeholder boxes, alongside speaker notes? Text across paragraphs, table cells, grouped shapes (if present), and speaker notes MUST be extracted in deterministic reading order while ignoring empty boxes.
- What happens when an `.epub` archive contains navigation/cover HTML documents with minimal boilerplate, non-chapter assets (CSS/images/fonts), or malformed XML entities? Only textual spine content documents are extracted, non-HTML assets are ignored safely, and safe archive/HTML parsing avoids external entity expansion or network fetches.
- What happens when an `.rst` file contains directives (e.g., `.. note::`, code blocks, comments), minor syntax warnings, or local/raw file inclusion directives? Minor syntax warnings MUST NOT pollute stdout or abort valid content extraction, while external local file inclusion and raw passthrough directives MUST be disabled so arbitrary filesystem reads are blocked cleanly.
- What happens when ingestion of one corrupt `.xlsx` or invalid-encoding `.csv` fails inside a multi-file `ingest` or `sync` directory call? Existing transactional / collection isolation guarantees remain intact (zero partial corrupt chunks stored; prior version preserved on incremental sync update failure).
- What happens when an optional library dependency in an existing environment is partially present or intentionally shadowed (`None` in module cache) during missing-extra tests? Missing-extra detection triggers cleanly and deterministically with the exact extra install instruction.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support built-in `.csv` and `.tsv` ingestion in the lean core installation with zero external third-party dependencies, reachable via `ingest`, `sync`, `reindex`, CLI commands, and single-file parsing utilities.
- **FR-002**: Built-in `.csv` and `.tsv` parsing MUST enforce strict UTF-8 / UTF-8-SIG decoding (normalizing optional UTF-8 BOM and rejecting invalid UTF-8 bytes, legacy single-byte encodings such as Windows-1252, and binary/NUL bytes with an unsupported-format error), trim trailing empty columns, group consecutive non-empty data rows into bounded 25-row sections labeled with source and row range (for example `<filename> (Rows 1-25)`), format each row with column headers as `Header: Value` pairs, handle ragged rows safely without runtime errors, and return an empty section list cleanly (`0` indexed rows) when no non-empty data rows exist.
- **FR-003**: System MUST define isolated optional installation groups `xlsx`, `pptx`, `epub`, and `rst`, update the combined `all` format installation bundle to include all document format extras (`pdf`, `docx`, `html`, `xlsx`, `pptx`, `epub`, `rst`) while keeping heavy ML/NER extras (`rerank`, `pii`) separate, and keep lockfile dependencies updated and reproducible.
- **FR-004**: System MUST integrate new formats strictly through additive parser registration and lazy resolution so importing the top-level package or running core workflows never eagerly loads optional format libraries, and core root exports MUST remain unchanged at `36` exports.
- **FR-005**: Attempting to parse `.xlsx`, `.pptx`, `.epub`, or `.rst` without the corresponding optional dependency installed MUST fail loudly with a missing-extra error naming the exact extra (`xlsx`, `pptx`, `epub`, or `rst`) and installation command hint before mutating any vector store or manifest state.
- **FR-006**: Format detection MUST recognize `.csv`, `.tsv`, `.xlsx`, `.pptx`, `.epub`, and `.rst` extensions case-insensitively and MUST validate extensionless ZIP container payloads (`.docx`, `.xlsx`, `.pptx`, `.epub`) against uncompressed size bounds in a single pass before verifying archive markers while rejecting generic ZIP files, corrupt archives, legacy binary office formats (both typed `.xls`/`.ppt` and extensionless OLE2 signatures), and unrecognized binary bytes with a typed unsupported-format error.
- **FR-007**: Generalized container validation MUST enforce ZIP-bomb protection (uncompressed total size limit and corrupt-archive handling) across all ZIP-backed document formats (`.docx`, `.xlsx`, `.pptx`, `.epub`) before full extraction occurs.
- **FR-008**: Structure-aware extraction for each new format MUST preserve domain structure and source provenance metadata cleanly:
  - `.xlsx`: Extract visible worksheets only (skipping `hidden` and `veryHidden` worksheets), trim formatted blank trailing header and row columns, group consecutive non-empty data rows into bounded 25-row sections labeled `<Sheet Name> (Rows <start>-<end>)`, pair column headers with row cells as `Header: Value` entries (reading cached values safely when formulas are present), skip completely blank sheets/rows, and return empty sections cleanly (`0` indexed rows) if no visible worksheet yields extractable text.
  - `.pptx`: Preserve sequential slide numbering (as page/location metadata), slide titles, body/table text, and speaker notes when present, skipping empty slides and returning empty sections cleanly (`0` indexed rows) if no slide contains text.
  - `.epub`: Extract ordered book spine chapters/documents with readable section headings/titles while ignoring non-content assets, decomposing hidden HTML subtrees (`hidden`, `aria-hidden="true"`, `display:none`/`visibility:hidden`), and safely neutralizing external XML/HTML entity resolution; return empty sections cleanly (`0` indexed rows) if no readable chapter text exists.
  - `.rst`: Extract section titles and hierarchical body/list/block text via offline document-tree parsing (falling back to section label `"Introduction"` for headingless prose and suppressing minor non-fatal syntax warnings) with external local file inclusion and raw passthrough directives disabled so arbitrary filesystem read directives inside untrusted `.rst` files are blocked, returning empty sections cleanly (`0` indexed rows) if no extractable text exists.
- **FR-009**: All newly supported formats MUST preserve full downstream compatibility with Phase 1 cleaning, PII pre-chunking enrichment (`redact`, `tokenize`, `block`), cross-reference resolution, structure-aware chunking, deterministic SHA-256 content-addressed chunk IDs, incremental `sync` / `--dry-run`, `reindex`, and Phase 2 citations/retrieval/metadata filtering (`source`, `section`, `page`).
- **FR-010**: Minimal-core installation verification (including automated CI minimal-core checks) MUST run full core delimited (`.csv`/`.tsv`) tests alongside `MissingExtraError` enforcement for uninstalled optional formats (`.pdf`, `.docx`, `.html`, `.xlsx`, `.pptx`, `.epub`, `.rst`), without requiring optional format extras to pass core tests.
- **FR-011**: Every user-facing document in the repository (`README.md`, `PRODUCT.md`, `docs/README.md`, `docs/cli-reference.md`, `docs/api-reference.md`, `docs/architecture.md`, `docs/development.md`, `docs/future-features.md` §1.2 and matrix row marked `*Implemented*`, and `CHANGELOG.md` `## Unreleased`) MUST be updated before feature completion.
- **FR-012**: OCR for image-only scanned documents (`1.3`), legacy proprietary binary formats (`.xls`, `.ppt`), and server/UI/framework layers MUST remain out of scope per Constitution Principle I (`v1.4.0`).

### Key Entities

- **Format Descriptor & Extension Registry**: Mapping from supported document extensions and container/content signatures to lazy format parsers and missing-extra hints, preserving zero eager imports.
- **Tabular Record Group (CSV / TSV / XLSX)**: Header-contextualized (`Header: Value`) collection of up to 25 consecutive non-empty data rows (with trailing empty columns trimmed) grouped deterministically into range-labeled sections (`<Source or Sheet> (Rows <start>-<end>)`) with sheet or table provenance.
- **Slide Deck Section (PPTX)**: Slide-indexed structured section holding slide number provenance, slide heading, body/table text, and optional speaker notes in reading order.
- **Spine Chapter Section (EPUB)**: Reading-order digital book section extracted from container spine metadata, capturing chapter title and cleaned prose without non-content assets.
- **Restructured Section (RST)**: Heading-delimited section parsed safely from reStructuredText syntax with external file insertion disabled and `"Introduction"` fallback for headingless prose.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users on a core-only installation (zero optional extras installed) can ingest, sync, dry-run preview, retrieve, and cite valid `.csv` and `.tsv` files in `100%` of offline test runs with zero third-party parser package imports.
- **SC-002**: Importing the top-level package loads `0` optional format-parsing libraries eagerly, and attempting to parse any of the four optional new formats without its corresponding extra fails loudly `100%` of the time before any vector store or manifest write occurs.
- **SC-003**: Valid multi-section fixtures across all six newly supported extensions (`.csv`, `.tsv`, `.xlsx`, `.pptx`, `.epub`, `.rst`) produce non-empty structured sections carrying accurate source provenance (`source`, `section`, and sheet/slide/chapter/page context) and pass incremental unchanged-file skip (`0` re-embeddings on follow-up `sync`) and end-to-end grounded retrieval checks.
- **SC-004**: `100%` of malformed inputs tested — corrupt archives, oversized uncompressed ZIP payloads exceeding safety limits, legacy binary `.xls`/`.ppt` signatures, invalid binary/encoding `.csv`/`.tsv`/`.rst`, and `.rst` local file-inclusion attempts — fail cleanly with typed errors (`0` unhandled crashes, `0` vector-store mutations, `0` arbitrary file reads), while `100%` of valid zero-content/blank/header-only inputs produce `0` indexed rows cleanly without crashing batch ingestion.
- **SC-005**: The public root export contract stays unchanged at `36` exports, all existing unit, integration, minimal-core, security, static-analysis, lockfile, `@pytest.mark.reverse`, and `@pytest.mark.pii` safety suites pass with `0` regressions, and combined test branch coverage stays at or above `80%`.
- **SC-006**: `100%` of user-facing documentation files and roadmap status matrices accurately document `.csv`/`.tsv` core intake, all optional format extras (`xlsx`, `pptx`, `epub`, `rst`, `all`), security boundaries, and `014` completion status prior to completion.

## Assumptions

- **CSV/TSV Default Delimiters & Header Handling**: `.csv` uses standard comma separation (RFC 4180 quoting rules) and `.tsv` uses tab (`\t`) separation; the first non-empty row (after trimming trailing empty cells) acts as column headers when formatting subsequent rows as `Header: Value` pairs, and whitespace-only or header-only files with zero data rows return empty section lists (`0` indexed rows), matching existing plain-text, Markdown, HTML, PDF, and DOCX behavior and preserving the locked `36`-export contract.
- **CSV/TSV/XLSX Row Grouping**: Delimited tables and spreadsheets partition non-empty data rows into fixed 25-row sections (`Rows 1-25`, `Rows 26-50`, ...) under source/sheet headings so parent sections stay bounded during retrieval, leaving multi-table page-boundary header replication inside PDF/DOCX/HTML/MD (`1.1`) as a separate roadmap item.
- **XLSX Formula Handling**: Workbooks are opened in read-only evaluated-value mode so cached computed spreadsheet values are indexed cleanly; formulas with no cached value skip unset cells cleanly without failing extraction.
- **Legacy Binary Formats Rejected**: Legacy Microsoft binary formats (`.xls`, `.ppt` — OLE2 Compound Document headers) remain explicitly unsupported and raise an unsupported-format error recommending conversion to `.xlsx`/`.pptx` or `.csv`.
- **Git Branch Timing**: Repository currently rests cleanly on `main` (`93f5302`) because `.specify/extensions.yml` is absent (`before_specify` hook skipped per Spec Kit rules); a dedicated feature branch (`feat/014-additional-intake-formats`) should be created prior to implementation.

# Feature Specification: Baseline Housekeeping and Alignment

**Feature Branch**: `chore/003-baseline-housekeeping`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Establish a clean, accurate documentation, packaging, and CLI baseline for docpipe-maestro before starting the modular registry refactor program. Context: (1) Product.md -> PRODUCT.md casing rename across git/packaging/docs; (2) PRODUCT.md §7.3 and constitution.md Footprint stale [generation] optional extra claims; (3) PRODUCT.md §7.5 omitted public symbols (build_chat_messages, answer_detailed, GenerationResult) and §20.1 stale flat filenames instead of ingest/ and query/ subpackages; (4) README.md POLICY profile table missing note that PDF clause detection is heuristic; (5) docpipe-maestro query lacks --json structured output mode (including chunk id, parent_id, score, text, metadata) documented in docs/cli-reference.md; preserve pyproject.toml dependency pins, urls, and tooling configs while passing all checks, packaging build, and reverse safety gate."

## Clarifications

### Session 2026-11-13

- Q: What top-level JSON structure should `docpipe-maestro query "<question>" --json` emit on standard output? → A: Wrapper object with `"query"`, `"collection"`, `"expand_parent"`, and `"results"` (list of retrieved items, `[]` when empty).
- Q: Should `PRODUCT.md` (§7.5) and the constitution's public interface list be reconciled to cover every currently exported symbol, or only add the three recently shipped generation capabilities? → A: Align `PRODUCT.md` (§7.5) with every currently shipped public export and sync the constitution's Quality Gates API list to match.
- Q: How should `docpipe-maestro query "<question>" --json` report validation or runtime errors (such as an invalid threshold or embedding model mismatch)? → A: Plain diagnostic message on standard error, empty standard output, and exit code `1` (matching `status --json` and `ask --json`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Consistent Governance, Product Documentation, and Filename Baseline (Priority: P1)

Contributors, maintainers, and downstream users reading the repository overview, documentation index, product specification, and project constitution encounter one consistent, truthful description of tracked files, shipped public capabilities, package footprint, profile behavior, and release safety gates, with the canonical `PRODUCT.md` filename applied everywhere.

**Why this priority**: Accurate baseline documentation and governance alignment prevent contributors and automated planning tools from acting on stale file paths, contradicted dependency claims, or incomplete public interface lists before modular refactoring begins.

**Independent Test**: Inspect all internal file links, filename references, governance version logs, public capability catalogs, footprint descriptions, and profile capability notes across repository documentation and constitution records to confirm zero broken links, zero stale `Product.md` casing references, and full parity with current project assets.

**Acceptance Scenarios**:

1. **Given** a contributor navigates from the repository overview (`README.md`) or documentation index (`docs/README.md`) to the product specification, **When** inspecting every cross-reference and repository file tree entry, **Then** every reference points cleanly to `PRODUCT.md` with exact filename casing and zero broken or stale `Product.md` links remain.
2. **Given** a contributor reads `PRODUCT.md` (§7.3, §7.5, and §20.1), **When** comparing it against current project capabilities and repository structure, **Then** §7.3 states that answer generation is optional for callers to invoke while bundled in the core install, §7.5 includes every currently shipped public export (adding the omitted generation helpers and result type alongside lifecycle summary records, source records, version metadata, and public error types), and §20.1 maps the organized two-phase ingestion (`ingest/`) and retrieval/answering (`query/`) directories instead of pre-refactor flat filenames.
3. **Given** a maintainer reviews `.specify/memory/constitution.md`, **When** checking version metadata, amendment log, principles, release gates, and footprint rules, **Then** the constitution is at version `1.2.0` with a dated Amendment Log entry clarifying Principle I ("minimal in promise, not in rigor"), designating mandatory reverse safety testing as Release Gate #1 while reserving Release Gate #2 for PII safety across Principle V and Quality Gates, syncing the Quality Gates public interface contract with the complete shipped surface, and removing the obsolete optional-extra generation claim from Footprint while preserving the 16 GB RAM CPU-only constraint.
4. **Given** a user compares processing profiles in `README.md`, **When** reading the `POLICY` profile summary table, **Then** the table explicitly notes that PDF clause boundary detection relies on heuristic rules.

---

### User Story 2 - Machine-Readable Retrieval Output from CLI `query` (Priority: P1)

Developers, integrators, and evaluation dataset authors can invoke `docpipe-maestro query "<question>" --json` to retrieve structured, machine-readable JSON output containing chunk identifiers, parent section identifiers, similarity scores, text content, and provenance metadata so evaluation fixtures and automated workflows do not have to parse human-formatted console text.

**Why this priority**: Upcoming evaluation dataset authoring and programmatic integrations require stable machine-readable identifiers and metadata directly from retrieval runs, bringing `query` into CLI feature parity with `status --json` and `ask --json`.

**Independent Test**: Execute `docpipe-maestro query` with and without `--json` against an indexed collection covering parent-expanded retrieval, raw child-chunk retrieval, and zero-match threshold filtering, confirming valid structured JSON when `--json` is passed and unchanged plain-text formatting when omitted.

**Acceptance Scenarios**:

1. **Given** an indexed collection with relevant documents, **When** a developer runs `docpipe-maestro query "<question>" --json`, **Then** standard output emits a valid JSON wrapper object containing `"query"`, `"collection"`, `"expand_parent"` (`true`), and `"results"`, where each item in `"results"` exposes its chunk identifier (`id`), parent identifier (`parent_id`), similarity score (`score`), body text (`text`), and citation/provenance metadata (`metadata`).
2. **Given** an indexed collection, **When** a developer passes raw child-chunk mode alongside `--json`, **Then** the JSON output sets `"expand_parent"` to `false` and `"results"` returns matched child-chunk records with their chunk identifiers, parent identifiers, similarity scores, text, and provenance metadata instead of expanded parent sections.
3. **Given** an empty collection or a relevance threshold that eliminates all candidates, **When** a developer runs `docpipe-maestro query "<question>" --json`, **Then** standard output emits the valid JSON wrapper object with `"query"`, `"collection"`, `"expand_parent"`, and `"results": []`, exiting cleanly (`0`) without mixing human prose into JSON output.
4. **Given** a user runs `docpipe-maestro query "<question>"` without `--json`, **When** results or empty matches are printed, **Then** existing human-readable output formatting remains completely preserved.
5. **Given** a developer consults `docs/cli-reference.md`, **When** reviewing the `query` subcommand reference, **Then** the `--json` option, behavior on empty results and raw child mode, and output payload fields are clearly documented.

---

### User Story 3 - Reliable Packaging Baseline and Zero-Regression Quality Gates (Priority: P2)

Maintainers preparing package distributions and verifying baseline health confirm that source and wheel distribution artifacts bundle `PRODUCT.md`, the governance constitution, documentation, and typed-package marker cleanly while all declared dependency constraints, metadata links, tests, static checks, and safety gates remain unbroken.

**Why this priority**: Establishing a verified, cleanly packaging baseline before beginning multi-stage architectural refactoring ensures every subsequent stage inherits passing release gates and trustworthy distribution artifacts.

**Independent Test**: Build source and wheel packages, validate archive membership and distribution metadata, confirm runtime/optional dependencies and tooling rules match baseline expectations, and run the complete safety, regression coverage, lint, and strict static typing suite.

**Acceptance Scenarios**:

1. **Given** updated packaging inclusion settings, **When** source and wheel distributions are built and verified, **Then** archives include `PRODUCT.md`, `.specify/memory/constitution.md`, project documentation under `docs/`, and the package typed marker cleanly with zero stale filename references or metadata check failures.
2. **Given** baseline housekeeping updates are applied, **When** inspecting package dependency rules, project URLs, and lint/type/coverage thresholds, **Then** all existing dependency bounds, metadata links, and quality settings remain preserved without regressions.
3. **Given** all documentation, governance, packaging, and CLI edits are complete, **When** executing the repository verification suite, **Then** the mandatory reverse safety gate passes, overall branch coverage meets or exceeds 80%, formatting/lint/security rules pass, and strict static type checking across source and tests passes cleanly.

---

### Edge Cases

- What happens on case-insensitive or case-preserving filesystems regarding the `Product.md` to `PRODUCT.md` rename? Version control tracking, packaging manifests, and all markdown references MUST point strictly to `PRODUCT.md`, with no duplicate `Product.md` references or broken paths remaining.
- What happens when global CLI options (`--collection`, `--persist-dir`, `--config`, `--no-config`) are placed either before or after `query` together with `--json`? Option resolution and JSON emission MUST behave identically regardless of flag placement, matching `status --json` and `ask --json`.
- What happens when retrieved records in `query --json` come from non-paginated document formats (such as Markdown or plain text) where optional provenance attributes like page number are absent? Missing optional metadata fields MUST serialize cleanly as structured metadata without failing JSON generation or inventing synthetic values.
- What happens when `docpipe-maestro query "<question>" --json` encounters an invalid parameter (such as an out-of-range relevance threshold) or runtime retrieval error (such as an embedding model mismatch)? The command MUST print a plain diagnostic `Error: ...` message to standard error, leave standard output empty, and exit with status `1` (matching `status --json` and `ask --json`).
- What happens when `docpipe-maestro query "<question>" --json` passes `--threshold` and all candidate matches fall below it? Standard output MUST remain valid JSON with zero retrieved results rather than printing plain-text fallback prose.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Version control tracking, package distribution configuration, documentation index (`docs/README.md`), repository overview (`README.md`), internal markdown cross-references, and repository test fixtures referencing the file MUST consistently use `PRODUCT.md`, eliminating all stale `Product.md` references.
- **FR-002**: `PRODUCT.md` MUST be reconciled so:
  - §7.3 (along with companion dependency/decision notes in §14.3, §16, and §18) accurately describes answer generation as optional to invoke at runtime while included within core dependencies (no separate generation extra).
  - §7.5 catalogs 100% of currently shipped public exports, adding the omitted structured chat message helper, detailed answer generation helper, and structured generation result type alongside lifecycle summary records, source records, public error types, and package version metadata.
  - §20.1 reflects the current organized two-phase ingestion (`ingest/`) and retrieval/answering (`query/`) directory layout instead of obsolete pre-refactor flat filenames.
- **FR-003**: `.specify/memory/constitution.md` MUST be amended to version `1.2.0` with a dated Amendment Log entry that:
  - Clarifies Principle I so "minimal" means minimal in feature surface and scope promise rather than minimal in engineering rigor.
  - Designates mandatory reverse safety testing as Release Gate #1 and explicitly reserves Release Gate #2 for PII safety across Principle V and Quality Gates.
  - Reconciles Additional Constraints -> Quality Gates so its public API surface statement aligns with the full shipped public contract (functions, shared types/records, and public exceptions).
  - Reconciles Additional Constraints -> Footprint by removing the obsolete claim that generation is an optional dependency extra while preserving the 16 GB RAM CPU-only constraint.
- **FR-004**: `README.md` MUST explicitly note in its `POLICY` profile summary table that PDF clause boundary detection is heuristic, and MUST maintain an accurate repository structure tree aligned with tracked files (`PRODUCT.md`, `.specify/memory/constitution.md`, `docs/`, `py.typed`, `.env.example`, `.pre-commit-config.yaml`, `LICENSE`, and `README.md`).
- **FR-005**: The `docpipe-maestro query` CLI subcommand MUST support an optional `--json` flag that emits a valid, deterministic JSON wrapper object on standard output (`{"query", "collection", "expand_parent", "results"}`), consistent with existing CLI object-envelope JSON conventions (`status --json` and `ask --json`).
- **FR-006**: Each entry in the `"results"` array emitted by `docpipe-maestro query "<question>" --json` MUST include its chunk identifier (`id`), parent section identifier (`parent_id`), similarity score (`score`), body text (`text`), and citation/provenance metadata (`metadata`), whether returning expanded parent sections (`expand_parent: true`, default) or raw child chunks (`expand_parent: false`).
- **FR-007**: When zero results match a `docpipe-maestro query "<question>" --json` call (empty collection or filtered out by threshold), the CLI MUST emit the JSON wrapper object (`"query"`, `"collection"`, `"expand_parent"`, `"results": []`) on standard output and exit `0` cleanly without printing plain-text prose to standard output.
- **FR-008**: Default text output formatting and exit behavior of `docpipe-maestro query` when `--json` is omitted MUST remain completely unchanged for backward compatibility.
- **FR-009**: `docs/cli-reference.md` (and any CLI command summaries in `README.md` listing `query` options) MUST document the `query --json` flag, its wrapper schema (`query`, `collection`, `expand_parent`, `results`), per-item output fields, raw child-chunk behavior, empty-result behavior, and failure behavior (`Error: ...` on standard error, empty standard output, exit `1`).
- **FR-010**: Package configuration MUST preserve all existing runtime and optional dependency version constraints, project metadata URLs, and code-quality/test/coverage configurations without regression, while ensuring distribution builds include `PRODUCT.md`, `.specify/memory/constitution.md`, `docs/`, and the package typed marker cleanly.
- **FR-011**: On validation or runtime failures during `docpipe-maestro query "<question>" --json`, the CLI MUST write a plain diagnostic message (`Error: ...`) to standard error, keep standard output empty, and exit with status `1` consistently with `status --json` and `ask --json`.

### Key Entities *(include if feature involves data)*

- **Baseline Documentation Set**: The coordinated repository truth sources (`PRODUCT.md`, `README.md`, documentation under `docs/`, and `.specify/memory/constitution.md`) describing product scope, public interface, file organization, safety gates, and CLI behavior.
- **Constitutional Amendment Record**: Version `1.2.0` governance revision capturing Principle I rigor clarification, Release Gate #1 and reserved Release Gate #2 definitions, corrected Footprint language, and audit trail in the Amendment Log.
- **Structured Query Result Envelope**: Machine-readable JSON wrapper object (`"query"`, `"collection"`, `"expand_parent"`, `"results"`) emitted by `docpipe-maestro query --json`, pairing query context with an ordered collection of retrieved chunk records (`id`, `parent_id`, `score`, `text`, `metadata`).
- **Distribution Inclusion Manifest**: Packaging inclusion rules ensuring source and built distributions contain `PRODUCT.md`, `.specify/memory/constitution.md`, project documentation, and the typed-package marker.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of internal relative markdown file links across `README.md`, `PRODUCT.md`, `docs/`, and `.specify/memory/constitution.md` resolve to existing files with exact filename casing (zero broken links and zero stale `Product.md` references).
- **SC-002**: 100% of shipped public package exports (functions, data/result shapes, public error classes, and version identifier) and organized source directories match `PRODUCT.md` (§7.3, §7.5, and §20.1) with zero undocumented public capabilities and zero obsolete flat file references.
- **SC-003**: `.specify/memory/constitution.md` reflects version `1.2.0` with a complete Amendment Log entry and zero internal contradictions regarding generation core inclusion, Principle I rigor, Quality Gates public API contract parity, or Release Gates #1 and #2.
- **SC-004**: `docpipe-maestro query "<question>" --json` produces 100% valid JSON parseable by standard JSON tooling conforming to the `{"query", "collection", "expand_parent", "results"}` envelope across default parent-expanded retrieval, raw child-chunk retrieval, and zero-match threshold filtering, exposing `id`, `parent_id`, `score`, `text`, and `metadata` for every returned record while leaving non-JSON text output unchanged.
- **SC-005**: Source and wheel distributions build in a single pass with zero warnings for missing or mis-cased files, include `PRODUCT.md`, `.specify/memory/constitution.md`, documentation, and the typed-package marker, and pass distribution metadata verification checks cleanly.
- **SC-006**: 100% of automated verification gates pass after final baseline edits without regression: the mandatory reverse safety gate passes, the full test suite meets or exceeds the 80% branch coverage threshold, formatting/lint/security rules pass, and strict static type checking across source and tests passes.

## Assumptions

- Stage 0 is strictly a documentation, packaging, governance, and CLI `query --json` alignment baseline prior to executing the modular registry refactor program; registry abstractions, pipeline refactors, and PII redaction logic remain explicitly out of scope for this stage.
- Release Gate #2 (PII safety gate) is reserved structurally inside `.specify/memory/constitution.md` (`v1.2.0`) during this stage, with its concrete detection rules and automated safety tests slated for a subsequent dedicated feature stage.
- Existing declared core runtime dependencies, optional parser extras, project URLs, and quality tool thresholds are already settled and must be preserved unchanged rather than upgraded or loosened.
- `docpipe-maestro query --json` reuses existing retrieval execution and configuration precedence without modifying semantic search scoring, parent-expansion logic, or persistence formats.

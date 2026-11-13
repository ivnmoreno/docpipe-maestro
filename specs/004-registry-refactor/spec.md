# Feature Specification: Pluggable Pipeline Stage Registries

**Feature Branch**: `refactor/004-registry-refactor`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Refactor docpipe-maestro's ingestion and retrieval pipeline stages to use a uniform Strategy + Registry extension pattern with zero behavioral changes."

## Clarifications

### Session 2026-11-13

- Q: Should public ingestion and retrieval functions accept optional keyword-only stage selector parameters (defaulting to built-in stages), or keep zero new parameters in this refactor? -> A: Add optional keyword-only stage selector parameters (`cleaner`, `chunker`, `embedder`, `store` defaulting to `"default"`) on applicable ingestion, management, and retrieval public functions.
- Q: What exception hierarchy should stage registration duplicate and unknown-key lookup errors follow? -> A: `RegistryError` inherits from `DocpipeError` and is exported as part of the public exception hierarchy (`KeyError` caught internally and converted to `RegistryError` with available keys).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extend Pipeline Stages Without Modifying Core Orchestration (Priority: P1)

A library user registers a custom document format parser, text cleaner, chunking strategy, embedder, vector store, candidate searcher, or result reranker using the public extension registration interface, and runs document ingestion or question retrieval through that custom stage without forking or editing core pipeline orchestrators.

**Why this priority**: Enabling additive extensibility without modifying orchestrators is the core architectural goal of this refactor and directly unlocks every downstream feature stage (enrichment, privacy redaction, reranking, hybrid search, and metadata filtering).

**Independent Test**: Register a custom stage implementation (such as a custom format parser, text cleaner, or chunker) under a custom identifier, execute an ingestion and retrieval pass targeting a sample document through that identifier, and verify the custom stage executes cleanly and produces queryable results with zero edits to core orchestrators.

**Acceptance Scenarios**:

1. **Given** a library user defines a custom format parser, text cleaner, chunker, embedder, or store matching the documented stage contract and registers it via the corresponding public registration entry point, **When** a document is ingested (via extension routing for parsers or optional keyword-only stage selectors such as `cleaner`, `chunker`, `embedder`, `store`) and queried, **Then** orchestration resolves the registered stage automatically and stores/retrieves the resulting sections without altering any core library file.
2. **Given** a built-in or user-registered stage key already exists in a registry, **When** a caller attempts to register another implementation under the same key (even if the built-in entry has not yet been materialized), **Then** registration fails immediately with a clear duplicate-key diagnostic error without overwriting the existing entry.
3. **Given** an unregistered or misspelled stage key, **When** orchestration or a caller resolves that key, **Then** resolution raises a clear diagnostic error listing every available registered key (or indicating an empty registry).

---

### User Story 2 - Uniform Stage Contracts and Deferred Backend Loading (Priority: P1)

A contributor inspects or integrates with the library and sees uniform, strongly typed behavioral contracts across all offline ingestion stages (Parser, Cleaner, Enricher, Chunker, Embedder, Store) and online retrieval stages (Searcher, Reranker), while deferred built-in loading keeps CLI help/argument initialization and top-level imports free from heavy vector-storage or model-client runtimes.

**Why this priority**: Enforcing strict two-phase boundaries (Principles II and III) and preserving instantaneous CLI startup latency prevents circular dependencies and ensures reserved future extension stages start with clean, non-invasive contracts.

**Independent Test**: Inspect all eight stage registries (five active with built-in defaults, three reserved/extension-ready), verify key listing, membership checks, lazy resolution on demand, and confirm CLI help/parser startup imports zero heavy vector-store or model-client runtimes.

**Acceptance Scenarios**:

1. **Given** built-in stage implementations are declared lazily rather than eagerly loaded at package import time, **When** a consumer initializes top-level exports or invokes CLI help/argument parsing, **Then** heavy vector-database and model-client libraries remain unloaded in memory until an actual ingestion or retrieval command resolves a backend.
2. **Given** the three newly standardized extension points (`Enricher`, `Searcher`, `Reranker`), **When** a consumer inspects their registries out of the box, **Then** their typed contracts are exported and inspectable, key lookup on unpopulated keys yields a clear diagnostic error, and newly registered implementations resolve identically to core stages.
3. **Given** an automated test resets and re-populates registry state during test isolation, **When** registry lookup and key enumeration run before and after registration, **Then** membership checks (`in`), sorted key listing, and resolution behave consistently and deterministically.

---

### User Story 3 - Zero-Behavior-Change Preservation & Automated Regression Guards (Priority: P1)

Existing CLI users, library API consumers, and internal callers experience identical retrieval scores, chunk boundaries, formatting, error behavior, security safeguards, and compatibility helper behavior before and after the refactor, verified continuously by automated signature-stability, library-purity, invariant-regression, and offline golden-equivalence checks.

**Why this priority**: Zero behavioral drift across 14 load-bearing safety, crash-recovery, and security invariants is mandatory before building evaluation benchmarks or adding new retrieval stages.

**Independent Test**: Run the full unmodified baseline suite (including mandatory exception preservation), together with automated signature stability verification across every public export, static library purity checks excluding user-config loading outside the CLI, and an offline deterministic golden-query snapshot comparison.

**Acceptance Scenarios**:

1. **Given** a multi-document policy fixture corpus ingested and queried offline under deterministic mock embeddings, **When** comparing retrieval output before and after the registry refactor, **Then** returned parent identifiers, similarity scores, text, citations, and provenance metadata match the golden baseline snapshot identically.
2. **Given** existing callers invoking public library operations (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, prompt builders, answer helpers) or legacy helper entry points (such as extensionless content-based format detection, text cleaning, chunking, and store access), **When** called with baseline arguments, **Then** all required positional/keyword parameters, optional keyword-only extensions, return shapes, and error types remain unchanged.
3. **Given** the 14 baseline safety, persistence, and security invariants (including uncommitted-version sweeps, model locking, HTML tag/hidden-content filtering, zip-bomb limits, symlink/traversal guards, owner-only storage permissions, loopback HTTP/secret redaction checks, and exception preservation), **When** automated tests execute across the refactored codebase, **Then** 100% of existing and newly guarded invariant checks pass without relaxed assertions.
4. **Given** automated static structural inspection across all non-CLI library modules, **When** scanning imports and calls for user configuration or `.env` loading logic, **Then** zero non-CLI library modules read user config files or `.env` files while document and manifest persistence reads remain unrestricted.

---

### Edge Cases

- What happens when a duplicate key conflicts with a lazy built-in declaration that has not yet been imported? Registration MUST trigger or check against declared keys cleanly so duplicates are always rejected.
- What happens when an unrecognized key is resolved before any built-ins are loaded? All lazy built-ins for that registry MUST materialize before generating the available-keys diagnostic list, except on empty registries where an explicit `<empty>` indication is shown.
- How are extensionless files handled when routing through parser resolution? Format resolution MUST still fall back cleanly to header/content inspection (detecting PDF, DOCX archive structures, HTML roots, Markdown headings, or valid plain text) before resolving the matching parser key.
- What happens when a newly registered custom parser claims a file extension already claimed by a built-in default parser? Custom non-built-in registered parsers claiming the file's lowercased extension MUST take precedence over built-in defaults, with ties among multiple custom parsers resolved deterministically in sorted registry-key order.
- How does test cleanup affect built-in stages? Clearing runtime entries in tests MUST be explicit so production code never accidentally loses built-in defaults.
- What happens if an empty file or empty batch produces zero chunks during ingestion? Embedding dimension locking MUST still skip locking when no vector dimensions were observed (`dim == 0`), matching baseline behavior.
- What happens when a section or clause contains exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`)? Child retrieval and parent expansion MUST preserve exception clauses intact identically to the baseline.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a generic named registry mechanism supporting decorator-based class registration, lazy built-in declarations loaded only on demand, membership testing, sorted key enumeration, resolution by string key, and explicit clearing for test isolation.
- **FR-002**: Registry operations MUST enforce key uniqueness by raising `RegistryError` (inheriting from `DocpipeError`) on duplicate registration (including conflicts with deferred built-ins) and MUST catch internal lookup misses (`KeyError`) and raise `RegistryError` listing sorted available keys (or explicitly indicating an empty registry) whenever an unknown key is requested.
- **FR-003**: System MUST define clean, strongly typed interface contracts for all six Phase 1 ingestion stages (`Parser`, `Cleaner`, `Enricher`, `Chunker`, `Embedder`, `Store`) and both Phase 2 retrieval stages (`Searcher`, `Reranker`), preserving all baseline parameter requirements (`source_key`, chunking `profile`, content-addressed `doc_version`, `embed_model`, optional `api_base`, manifest/version cleanup lifecycle methods, and bounded similarity scores).
- **FR-004**: System MUST wrap all built-in ingestion parsers (Markdown, plain text, HTML, PDF, DOCX), the built-in text cleaner, the structure-aware chunker, the embedding client adapter, and the default persistent vector store as registered default stage implementations, while creating empty, contract-only registries for `Enricher`, `Searcher`, and `Reranker`.
- **FR-005**: System MUST expose `RegistryError` (as a `DocpipeError` subclass) and all eight public extension registration functions (`register_parser`, `register_cleaner`, `register_enricher`, `register_chunker`, `register_embedder`, `register_store`, `register_searcher`, `register_reranker`) from the top-level public package surface using deferred loading where needed so top-level imports and CLI help/parser startup never eagerly load heavy vector-storage or model-client runtimes.
- **FR-006**: System MUST preserve full compatibility re-exports for existing module-level helper entry points and shared data/exception shapes, including extensionless content-based format detection fallback, text cleaning, chunking, token estimation, and vector store access, while adding strictly optional keyword-only stage selector parameters defaulting to `"default"` on applicable public functions (`cleaner`, `chunker`, `embedder`, `store` on `ingest`/`sync`; `store` on `remove`/`status`, where `status` validates non-default `store` keys against registered backends while reading collection metrics from the shared collection manifest; `embedder`, `store` on `reindex`/`retrieve`) so existing caller invocations remain 100% compatible.
- **FR-007**: System MUST route Phase 1 orchestration (`ingest`, `sync`, `remove`, `status`, `reindex`) and Phase 2 retrieval (`retrieve`) through the stage registries while preserving exact baseline chunking rules, similarity scoring formulas, cross-reference behavior, CLI subcommands/flags, and output formatting (zero behavior change).
- **FR-008**: System MUST preserve all 14 load-bearing baseline invariants without regression:
  1. Deterministic 12-character content-addressed document version identifiers.
  2. Pre-write sweeping of uncommitted chunk versions before ingest commits.
  3. Deferring collection embedding-dimension locks until a non-zero embedding dimension is produced.
  4. Collection embedding model lock verification rejecting mismatched models on ingest and query.
  5. Query-time verification of committed source versions plus oversampled child lookup when filtering.
  6. Linear-time HTML tag removal preserving numeric inequalities and bracketed placeholders.
  7. Parent-section-scoped chunk overlap resetting cleanly at section boundaries.
  8. Deterministic content-addressed chunk IDs incorporating document version and parent link.
  9. Child provenance headers paired with excluded parent records tagged so parents never match direct vector search.
  10. Hidden HTML prompt-injection filtering, deep-nesting guards, and archive decompression size limits.
  11. Symlink skipping during directory discovery, collection path-traversal rejection, and owner-only storage permissions.
  12. Loopback-only unencrypted endpoint allowance, credential pattern/secret scrubbing in errors, and offline local cost-map support.
  13. Deferred loading of heavy database/LLM runtimes during CLI parser initialization.
  14. Passing the mandatory exception-preservation safety gate (`Release Gate #1`) unmodified.
- **FR-009**: System MUST include automated verification suites validating:
  - Registry registration, resolution, duplicate rejection, missing-key diagnostics, membership, sorted listing, and lazy loading contracts.
  - Public API signature stability across every exported top-level symbol (verifying required parameters stay exact and any optional additions default transparently to baseline behavior).
  - Automated static source purity checking that non-CLI library modules never invoke user configuration file parsers or environment-file loaders (while permitting legitimate document and manifest filesystem reads).
  - Offline deterministic golden retrieval equivalence proving identical ranked outputs before and after refactoring.
  - Complete automated regression coverage across all 14 load-bearing invariants.

### Key Entities

- **Stage Registry**: Named lookup table associating string keys with pluggable stage classes, supporting deferred built-in registration, uniqueness validation, sorted enumeration, and clear diagnostic errors.
- **Ingestion & Query Stage Contracts**: Typed behavioral contracts separating offline Phase 1 stages (`Parser`, `Cleaner`, `Enricher`, `Chunker`, `Embedder`, `Store`) from online read-only Phase 2 stages (`Searcher`, `Reranker`).
- **Ingestion Context**: Shared per-document metadata context passed through Phase 1 stages (collection name, source key, content hash, 12-character document version, embedding model identifier, and active profile name).
- **Golden Query Baseline Snapshot**: Committed deterministic reference output for offline policy corpus queries used to detect any unintended retrieval shift across the refactor.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of existing baseline unit, integration, security, CLI, and mandatory exception-preservation tests pass without altering baseline test assertions, maintaining at least 80% branch coverage across the codebase.
- **SC-002**: Users can register custom implementations in any of the eight stage categories and run end-to-end ingestion or retrieval through them with zero modifications required to core orchestration modules.
- **SC-003**: Deterministic offline retrieval against the policy fixture corpus produces 100% identical result identifiers, parent associations, similarity scores, text, and provenance metadata before and after the refactor.
- **SC-004**: Package top-level imports and CLI help/argument parser initialization trigger zero eager imports of heavy vector-database or model-client runtimes.
- **SC-005**: 100% of exported top-level public functions pass automated signature-stability checks, and 100% of non-CLI library modules pass automated source-purity checks showing zero user-config or environment-file loading calls.
- **SC-006**: All automated code formatting, linting, static security checks, and strict static type checks across source and tests pass with zero warnings or errors.

## Assumptions

- Only typed contracts and empty registration containers are created for `Enricher`, `Searcher`, and `Reranker` in this stage; concrete implementations for document enrichment (Stage 3), PII protection (Stage 4), cross-encoder reranking (Stage 5), and hybrid lexical search (Stage 6) remain strictly out of scope.
- Adding new extension selectors to public callables must use keyword-only parameters with defaults matching current built-in behavior so existing caller invocations require zero edits.
- Any file reads for document intake or persistence manifests remain permitted inside non-CLI library modules; library purity strictly prohibits reading user configuration files or `.env` files outside the CLI layer.

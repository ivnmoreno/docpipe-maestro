# Feature Specification: Hybrid Lexical Search with Reciprocal Rank Fusion

**Feature Branch**: `feature/005-hybrid-search`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Implement a hybrid lexical searcher extension stage using BM25 / SQLite FTS5 fused via Reciprocal Rank Fusion (RRF) with vector cosine retrieval under docpipe-maestro's Strategy + Registry pattern."

## Clarifications

### Session 2026-11-13

- Q: How should hybrid search behave when invoked against an existing collection that already has vector records but no populated lexical index? -> A: Require re-indexing or re-ingesting first, failing cleanly with an actionable error instructing the user to run `reindex` (or re-ingest), preserving strict Phase 1 write / Phase 2 read-only separation.
- Q: How should RRF fused scores be normalized into `[0.0, 1.0]` and interact with optional `threshold` filtering? -> A: Normalize by dividing raw RRF scores by the theoretical maximum dual-rank score (so matches ranking near top in both semantic and lexical signals approach `1.0` while single-signal top matches cap near `0.5`), and apply optional `threshold` filtering directly to those normalized hybrid scores.
- Q: Should v1 expose fusion weights or RRF smoothing parameter $k$ as public API/CLI knobs, or keep fixed balanced defaults? -> A: Ship fixed balanced defaults (`k=60`, equal 50/50 weighting) in v1 to preserve a minimal public surface; advanced library users can still customize ratios via custom registered searchers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Exact-Match and Semantic Hybrid Retrieval (Priority: P1)

A library user or researcher querying technical specifications, contracts, or policy documents often searches for exact terms—such as incident codes (`SEV-1`), encryption standards (`AES-256`), protocol acronyms (`WPA3`), or clause identifiers (`Clause 1.2`)—whose meaning or exact phrasing pure semantic embeddings may rank below loosely related prose. By selecting the built-in hybrid search mode during retrieval or question answering, the system searches both dense semantic similarity and full-text lexical relevance (BM25), fusing their rankings via Reciprocal Rank Fusion (RRF) while expanding results to deduplicated parent sections with preserved provenance and exception clauses.

**Why this priority**: Solves lexical blindspots on identifiers, codes, and exact policy terminology—the primary retrieval accuracy gap when relying strictly on dense vector similarity—using the pluggable searcher extension architecture.

**Independent Test**: Index a multi-document policy corpus containing distinctive codes and clause numbers, execute identical queries using both the default semantic searcher and the hybrid searcher, and verify that exact-term queries rank the matching section higher with hybrid search enabled while keeping pure semantic default retrieval unchanged.

**Acceptance Scenarios**:

1. **Given** an indexed document collection, **When** a user runs retrieval or question answering selecting the hybrid searcher, **Then** matching child passages from both dense semantic search and lexical BM25 search are merged using Reciprocal Rank Fusion, expanded to unique parent sections with full citations and cross-reference context, and ordered by descending normalized relevance score.
2. **Given** a query referencing an exact identifier, numeric clause, or specialized acronym present in one document section, **When** hybrid retrieval is executed, **Then** the matching section ranks higher than with pure semantic similarity alone and retains all associated exception conditions in its expanded parent context.
3. **Given** the default searcher setting (pure semantic search), **When** queries are run after adding hybrid search, **Then** retrieved section identifiers, order, scores, text, and provenance remain identical to pre-feature behavior.

---

### User Story 2 - Consistent Read-Only Queries and Synchronized Index Lifecycle (Priority: P2)

A maintainer ingests, updates, or deletes documents over time via collection ingestion, directory synchronization, removal, or re-indexing. The full-text lexical index stays synchronized with committed collection contents—cleaning up stale or uncommitted document versions automatically—while online queries treat all persistent stores strictly as read-only and introduce zero external service dependencies.

**Why this priority**: Guarantees retrieval correctness across shrinking edits, deletions, and interrupted writes (preventing phantom matches for deleted clauses) without sacrificing offline portability or read-only query guarantees.

**Independent Test**: Ingest a directory of documents, verify hybrid retrieval matches expected terms, update one document removing a keyword and delete another document entirely, synchronize the collection, and confirm neither the removed keyword nor deleted document ever appears in subsequent lexical or hybrid results.

**Acceptance Scenarios**:

1. **Given** an initial document batch is ingested or re-indexed, **When** ingestion completes successfully, **Then** committed child passages are indexed for lexical lookup alongside vector embeddings using zero external database servers or network calls.
2. **Given** an interrupted write or failed update occurs mid-batch, **When** the next ingestion or synchronization runs, **Then** uncommitted lexical entries are purged atomically alongside uncommitted vector records so deleted or rolled-back passages never leak into query results.
3. **Given** a document is removed or updated via synchronization, **When** removal completes, **Then** stale lexical entries belonging to the removed or superseded document version are deleted.
4. **Given** an existing collection ingested prior to this feature without a lexical index yet built, **When** hybrid search is invoked on that collection, **Then** retrieval fails fast with a clear, actionable error instructing the user to run `reindex` (or re-ingest) rather than performing Phase 2 writes or masking missing lexical capability.

---

### User Story 3 - Score Normalization, Thresholding, and Configuration Integration (Priority: P3)

An application builder or CLI user switches between search strategies from library calls, CLI subcommands, or optional project defaults, and sets minimum relevance thresholds without breaking downstream prompt assembly, score ordering, or error reporting.

**Why this priority**: Ensures hybrid search integrates cleanly into existing evaluation workflows, CLI UX, and score-filtering contracts.

**Independent Test**: Execute hybrid search via programmatic retrieval, CLI query/ask options, and optional project defaults with empty queries, punctuation-heavy queries, and minimum score thresholds, verifying clean score bounds in `[0.0, 1.0]` and graceful error handling for unknown searcher names.

**Acceptance Scenarios**:

1. **Given** an application caller or CLI user specifies the hybrid searcher (or configures it in project defaults), **When** querying or asking questions, **Then** execution resolves the selected searcher through the public searcher registry; specifying an unrecognized searcher name produces a clear error listing valid registered searchers.
2. **Given** fused hybrid results are returned, **When** scores are normalized and checked against an optional minimum relevance threshold, **Then** raw RRF scores are divided by the theoretical maximum achievable dual-signal RRF score into `[0.0, 1.0]` (rewarding dual semantic + lexical agreement above single-signal matches), and optional `threshold` filtering evaluates against those normalized scores.
3. **Given** standard hybrid retrieval execution in v1, **When** invoking hybrid search through public API or CLI entry points, **Then** the system applies fixed balanced fusion defaults (rank-smoothing constant `k=60` with equal 50/50 semantic and lexical weighting) without cluttering the public surface with tuning knobs; advanced users requiring custom weights can register a custom searcher.

---

### Edge Cases

- **No Lexical Matches Found**: When a conceptual query shares zero exact keywords with any indexed chunk, hybrid search degrades gracefully using dense semantic candidates without failing or returning empty results unnecessarily.
- **Special Characters and Query Operators**: When raw user questions include unbalanced quotes, hyphens (`SEV-1`), slashes, colons, wildcards, or Boolean keywords (`AND`, `OR`, `NOT`), query parsing sanitizes input cleanly so lexical search never fails with syntax errors.
- **Empty or Whitespace Queries**: Empty or punctuation-only queries return empty results safely without crashing.
- **Strict Scope & Read-Only Phase 2**: Online hybrid retrieval performs zero persistent writes to disk stores or collection manifests, runs completely offline for local models, and respects collection-locked embedding models and owner-only storage permissions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a built-in hybrid searcher registered under the existing retrieval searcher extension registry that combines dense semantic similarity and BM25 full-text lexical search via Reciprocal Rank Fusion (RRF).
- **FR-002**: Default retrieval behavior (when no custom searcher is specified) MUST remain pure dense semantic search so all existing callers, CLI users, and golden outputs see zero unintended behavioral change.
- **FR-003**: System MUST maintain a collocated lexical search index using only built-in standard capabilities (requiring no external search daemons or heavy additional third-party runtime dependencies).
- **FR-004**: System MUST keep the lexical index lifecycle synchronized with collection ingestion, incremental directory synchronization, source removal, and re-indexing—including cleaning up uncommitted or superseded document versions so stale clauses never reappear.
- **FR-005**: Online retrieval using the hybrid searcher MUST treat persistent collection state (vector database, lexical index, and manifest) strictly as read-only and preserve lazy startup (avoiding eager heavy database or model imports on CLI parser initialization).
- **FR-006**: Lexical query execution MUST safely escape or neutralize raw user punctuation, hyphens, quotes, and reserved operators so arbitrary natural-language or code questions never trigger query syntax failures.
- **FR-007**: Hybrid retrieval MUST preserve the "Search Small, Return Big" safety guarantee: lexical and dense matching both operate exclusively on committed child passages, expand selected matches to deduplicated parent sections, resolve 1-hop cross-document references when enabled, and preserve all exception clauses (passing mandatory Release Gate #1).
- **FR-008**: Programmatic retrieval, question-answering entry points, and query/ask CLI subcommands MUST allow callers to choose any registered searcher by name and validate unrecognized searcher names immediately with descriptive diagnostics.
- **FR-009**: Returned relevance scores from hybrid search MUST be normalized relative to the theoretical maximum dual-signal RRF score (with fixed balanced defaults `k=60` and equal 50/50 semantic/lexical weights) into finite values within `[0.0, 1.0]`, ordered in strictly non-increasing score order, evaluated directly by optional minimum `threshold` filtering, and preserving full source, section, page, and document-version provenance metadata.
- **FR-010**: Library purity boundaries MUST remain intact: non-CLI library components MUST never read user configuration files or environment files.
- **FR-011**: When hybrid search is invoked against a non-empty collection that lacks a populated lexical index (such as collections indexed prior to this feature), retrieval MUST fail fast with a clear, actionable error instructing the user to re-index or re-ingest rather than writing during Phase 2 or masking missing lexical capability.
- **FR-012**: Public retrieval APIs and CLI subcommands MUST keep v1 hybrid fusion defaults fixed (`k=60`, 50/50 weights) without adding fusion-tuning flags or parameters (custom ratios remain achievable through custom registered searchers).

### Constitution Alignment

- **Principles I–VII Compliance**: Additive extension via existing Strategy + Registry stage (`Searcher`) and storage lifecycle; strict Phase 1 (lexical writes during ingest/sync/remove/reindex) vs. Phase 2 (strictly read-only query/answer) separation; zero external daemon/network footprint; "Search Small, Return Big" parent expansion and exception preservation kept intact; single canonical data shapes.

### Key Entities

- **Hybrid Search Strategy**: Registered retrieval strategy coordinating dense vector candidates and lexical BM25 candidates through Reciprocal Rank Fusion and outputting normalized, provenance-complete sections.
- **Collocated Lexical Index**: Local full-text index partitioned per collection alongside the vector database, storing committed child passages with source and version metadata for version-safe deletion and retrieval.
- **Fused Candidate Ranking**: Ranked list combining positional contributions from dense and lexical result lists prior to parent deduplication and optional cross-reference resolution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Exact-identifier retrieval test queries (matching codes, clause identifiers, or hyphenated tokens across the corpus) achieve higher top-1 hit accuracy with hybrid search enabled than pure dense vector search on the same test set.
- **SC-002**: Queries run with the default searcher produce 100% identical outputs (same section identifiers, order, scores, text, and provenance) compared to pre-feature golden baseline outputs.
- **SC-003**: After updating or removing source documents in incremental synchronization tests, 0% of deleted or superseded terms remain searchable via hybrid search.
- **SC-004**: On collections up to 5,000 child chunks, hybrid search execution adds under 20 ms latency over pure dense vector lookup in offline benchmarks.
- **SC-005**: CLI parser help startup continues to defer heavy database and model-client initialization, and all automated safety gates (including Release Gate #1 exception preservation, crash recovery, and library purity checks) pass 100%.

## Assumptions

- Target execution environments support embedded full-text BM25 search capabilities out of the box without needing separate OS packages or network services.
- Existing vector collections without prior lexical indexing remain unaffected when queried with the default searcher; hybrid behavior on unindexed collections follows the clarified resolution policy from Q1 above.
- Hybrid search runs strictly over committed child passages (matching vector storage visibility rules) so uncommitted staging chunks are invisible to queries.

# Feature Specification: Structured Metadata Pre-Filtering (`where`)

**Feature Branch**: `feat/010-metadata-filtering`  
**Created**: 2026-11-16  
**Status**: Draft  
**Input**: User description: "Expose structured metadata filtering (`where`) on retrieval queries and CLI commands, supporting both stored chunk metadata fields and manifest-derived document attributes safely without breaking existing collections."

## Clarifications

### Session 2026-11-16

- Q: How should retrieval behave when a caller supplies an unrecognized metadata key in `where` or CLI `--where`? → A: Reject any key outside supported chunk and manifest attributes upfront with a clear validation error listing valid filter keys.
- Q: How should retrieval respond if a caller passes the internal record-type key `type` in a filter (e.g., `where={"type": "parent"}`)? → A: Reject user-supplied `"type"` keys upfront with a clear reserved-key validation error, while preserving the mandatory `type="child"` conjunction in underlying child queries as defense-in-depth.
- Q: Should hybrid search (`fts5_hybrid`) support all documented structured filter operators identically to dense search? → A: Support the full documented operator set (`$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, `$or`) identically across both dense and hybrid search, rejecting only malformed or unrecognized operators.
- Q: How should manifest-derived keys (`profile`, `ingested_after`, `ingested_before`) behave when combined with structured filter operators? → A: Evaluate manifest keys at the top level only—supporting scalars or `$eq`/`$ne`/`$in`/`$nin` on `profile`, ISO-8601 strings on `ingested_after`/`ingested_before`, and conjunctive combination with top-level or nested chunk filters—while rejecting manifest keys nested inside `$or`/`$and` operator branches or unsupported operators.
- Q: How should the CLI handle repeating the same equality key across multiple `--where` flags (e.g., `--where source=hr.md --where source=travel.md`)? → A: Combine repeated values for the same equality key (`source`, `profile`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`) into a set-membership (`$in`) filter, while rejecting duplicate `ingested_after` or `ingested_before` flags with a validation error.

## Constitution Check

All requirements comply with [constitution.md](../../.specify/memory/constitution.md) (`v1.3.1`, ratified `2026-11-12`, last amended `2026-11-15`):

- **Scope Discipline (I)**: Exposes metadata pre-filtering strictly through the existing programmatic retrieval interface and command-line query, question-answering, and evaluation entry points—keeping the library scoped to the core RAG engine without application UI, server state, or arbitrary schema-management workflows.
- **Two-Phase Architecture (II)**: Operates exclusively during Phase 2 read-only retrieval against existing persisted chunk attributes and collection manifests, with zero Phase 1 ingestion changes and zero re-ingestion requirements for existing collections.
- **Library Purity (III)**: Core library retrieval accepts structured filter criteria programmatically without reading user configuration files; parsing command-line `--where key=value` arguments resides solely in the CLI boundary.
- **Search Small, Return Big (IV — NON-NEGOTIABLE)**: Always constrains vector and lexical child matching to active child records combined conjunctively with user filter predicates, ensuring no caller filter (including attempts to request `type="parent"`) can expose internal parent placeholder records.
- **Exception Preservation & PII Safety (V)**: Filtered child matches expand to complete parent sections when parent expansion is enabled, preserve all exception-preservation guarantees (**Release Gate #1**), and preserve all PII redaction, egress, audit, and local-only guarantees (**Release Gate #2**).
- **Provider Agnosticism, Local-First & Correctness (VI, VII, Footprint)**: Executes consistently across both dense semantic search and hybrid lexical+semantic search using zero new dependencies and zero breaking changes when no filter is supplied.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Filter Retrieval by Document & Structural Attributes (Priority: P1)

A developer or analyst querying a multi-document corpus needs to restrict search results to a specific document source, section heading, clause identifier, page number, document version hash, or embedding model identifier using either the programmatic retrieval entry point or the command-line `query`, `ask`, and `eval` commands. Filtered queries execute consistently regardless of whether dense vector search or hybrid lexical+vector search is selected, and compose cleanly with optional post-retrieval reranking.

**Why this priority**: Scoping retrieval to a target policy document, chapter, or page is the foundational multi-document filtering workflow in both programmatic integrations and CLI lookups.

**Independent Test**: Can be fully tested against a multi-document collection by executing filtered retrieval queries across dense search, hybrid search, and reranked search and verifying returned chunks and expanded parent sections originate strictly from the matching source, section, clause, page, or version criteria while unrelated documents are excluded.

**Acceptance Scenarios**:

1. **Given** an indexed multi-document collection containing policy, manual, and billing files, **When** a user queries `"leave days"` filtered to `source="hr_policy.md"` via the retrieval operation or `--where source=hr_policy.md` on the CLI, **Then** every returned passage comes strictly from `hr_policy.md` across both dense and hybrid search modes (and with reranking enabled).
2. **Given** a paginated document collection containing multiple numbered pages and labeled clauses, **When** a user supplies `--where page=2` or `where={"page": 2, "clause": "1.2"}`, **Then** only child passages matching page `2` (and clause `"1.2"`, when both are supplied) are considered and expanded cleanly without type-mismatch errors.
3. **Given** an evaluation benchmark suite run via the evaluation interface or `eval --where ...`, **When** a metadata filter is provided, **Then** evaluation forwards the filter to retrieval identically to standard queries and computes metrics strictly over the filtered subset.

---

### User Story 2 - Filter Existing Collections by Chunking Profile & Ingestion Window (Priority: P1)

A maintainer querying an existing collection wants to scope retrieval to documents ingested with a particular chunking profile (such as `POLICY` vs `DEFAULT`) or within an ingestion time window (`ingested_after` / `ingested_before` ISO-8601 timestamps) without having to rebuild or migrate collections already on disk. Because `profile` and ingestion timestamps live per document in the collection manifest rather than on individual chunks, the system resolves manifest constraints in memory into an allowed document set prior to vector or lexical search, and short-circuits cleanly with empty results whenever no indexed documents qualify.

**Why this priority**: Users already have indexed collections on disk and expect filtering by `profile` and ingestion timeframe to work immediately without destructive re-ingestion or vector-store range crashes on ISO-8601 strings.

**Independent Test**: Can be fully tested against an existing collection containing documents ingested under different profiles and recorded timestamps by filtering on `profile`, `ingested_after`, `ingested_before`, and combined manifest + chunk source filters, including empty-match ranges that confirm zero embedding calls occur.

**Acceptance Scenarios**:

1. **Given** an existing collection containing documents ingested under both `POLICY` and `DEFAULT` profiles at different timestamps, **When** a query filters by `--where profile=POLICY` or `--where ingested_after=2026-11-13T00:00:00Z`, **Then** only passages belonging to manifest documents matching those constraints are retrieved—with zero collection migration or re-ingestion.
2. **Given** a filter whose manifest criteria match zero documents (such as a future `ingested_after` timestamp, an unknown profile name, or an explicit `source` filter combined with a non-overlapping `profile`), **When** retrieval executes, **Then** the system immediately returns an empty result list with zero embedding requests and zero empty-list query errors.
3. **Given** a filter combining manifest attributes (`profile="POLICY"`) and a matching explicit `source` filter (either scalar or list expression), **When** retrieval resolves candidate sources, **Then** the effective allowed document set is the intersection of both constraints before searching child passages.

---

### User Story 3 - Enforce Child-Only Search Safety & Explicit Validation on Advanced Operators (Priority: P1)

An application developer passes structured comparison or logical filter operators programmatically (such as set membership `$in`, exclusion `$ne`, comparisons, or compound `$and`/`$or` expressions), including potentially unsafe inputs such as attempting to select `type="parent"`. The pipeline rejects reserved internal keys (including `"type"`) upfront while still binding user filters inside a mandatory child-only conjunction alongside active committed-version checks as defense-in-depth so internal parent placeholder vectors are never returned by search, and rejects malformed CLI expressions, invalid integer page values, malformed dates, or unsupported filter fields/operators with clear, actionable errors.

**Why this priority**: Constitution §IV makes child-only search safety non-negotiable; a user filter must never leak unembedded parent zero-vector placeholders or silently ignore malformed criteria.

**Independent Test**: Can be fully tested by passing adversarial filters such as `where={"type": "parent"}` (verifying upfront reserved-key rejection at retrieval boundaries plus defense-in-depth child-only filtering in underlying queries), testing supported structured operators across dense and hybrid search, and verifying malformed CLI syntax, non-integer numeric inputs, and invalid timestamps fail fast with clear typed errors.

**Acceptance Scenarios**:

1. **Given** an indexed collection with child chunks and parent placeholder sections, **When** a caller passes `where={"type": "parent"}` or `--where type=parent` (directly or nested inside an operator expression), **Then** validation rejects `"type"` upfront as a reserved internal key, and underlying child queries enforce `type="child"` conjunctively so zero parent placeholder records can ever be returned.
2. **Given** structured operator predicates passed programmatically (such as `{"source": {"$in": ["a.md", "b.md"]}}`, `{"page": {"$ne": 1}}`, or compound `$and`/`$or` expressions), **When** queried under either dense or hybrid search modes, **Then** matching child passages honor the exact operator semantics identically across both search modes (or fail upfront with an explicit validation error if an operator expression is malformed or unrecognized).
3. **Given** malformed CLI flags such as `--where broken_no_equals`, `--where =val`, `--where source=`, `--where page=abc`, or `--where ingested_after=not-a-date`, **When** `query`, `ask`, or `eval` runs, **Then** the CLI exits non-zero with a clear validation error before executing retrieval or generation.

---

### Edge Cases

- **Empty `$in` / zero-document intersections**: If resolving `profile`, `ingested_after`, `ingested_before`, and an explicit `source` filter yields an empty allowed source set, retrieval must short-circuit with `[]` prior to embedding or querying underlying stores rather than sending an empty membership predicate that triggers storage query errors.
- **Attempts to override internal metadata keys**: User filters referencing the reserved `"type"` key (directly or inside compound expressions) fail upfront with a clear reserved-key validation error, and underlying child store queries also enforce `type="child"` conjunctively alongside committed document versions (`doc_version`) as defense-in-depth so parent placeholders or uncommitted chunks never surface.
- **Optional missing metadata fields (`clause` / `page`)**: Filtering for `clause` or `page` on collections containing chunks without clause labels or page numbers handles absent/null fields cleanly in both vector and lexical indexes without false crashes.
- **CLI repeated flags & string values containing `=`**: Splitting CLI `--where key=value` only on the first `=` preserves literal `=` characters inside filter values (such as section titles), rejects empty keys or empty values cleanly, and handles multiple occurrences safely (`AND` across distinct keys; set membership across repeated equality keys; clear rejection if conflicting duplicate time bounds are supplied).
- **Backward compatibility when omitted**: Omitting `where` / `--where` preserves pre-existing retrieval, prompt generation, evaluation, reranking, and PII/exception gate behavior completely unchanged.
- **Collection empty or missing**: Filtering against an empty or nonexistent collection after preflight validation cleanly returns `[]` (consistent with existing unfiltered `retrieve()` behavior) while still validating filter syntax, allowed field keys, and value types upfront.
- **Unrecognized filter fields**: Passing an unknown metadata attribute name (such as a misspelled key) via CLI or programmatic queries raises a clear validation error listing supported chunk and manifest keys rather than silently returning zero results.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Programmatic retrieval MUST accept an optional keyword-only `where` filter mapping (defaulting to `None`) and pass resolved child-level constraints forward to the active search strategy and underlying dense and lexical indexes, while evaluation workflows MUST support passing the same `where` criteria through to retrieval.
- **FR-002**: Any intentional signature additions for the retrieval filter parameter MUST update public API stability contracts transparently while preserving all existing public exports, defaults, and caller compatibility when `where` is omitted.
- **FR-003**: Command-line retrieval, question-answering, and evaluation subcommands (`query`, `ask`, and `eval`) MUST accept repeatable `--where key=value` options, splitting only on the first `=`, rejecting malformed expressions (missing separator, empty key, or empty value) with clear error diagnostics and non-zero exit status, combining distinct keys with logical conjunction (`AND`), aggregating repeated occurrences of the same equality key (`source`, `profile`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`) into a set-membership (`$in`) list, rejecting duplicate `ingested_after` or `ingested_before` flags upfront, and converting command-line values solely within the CLI boundary before calling library retrieval.
- **FR-004**: Convenience filters MUST support stored chunk attributes (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, and `embed_model`):
  - Multi-key convenience mappings and distinct CLI `--where` options MUST combine with logical conjunction (`AND`).
  - Integer numeric attributes (`page`, `chunk_index`) supplied via CLI strings MUST parse strictly as integers and reject non-integer text cleanly.
  - Missing or null chunk attributes (`clause`, `page`) MUST be handled safely without false errors in either dense or hybrid lexical+vector searches.
  - Any key outside the documented chunk and manifest filter attributes MUST fail fast with a clear validation error listing supported filter keys.
- **FR-005**: Manifest-level convenience keys (`profile`, `ingested_after`, `ingested_before`) MUST resolve cleanly at the top level in memory from the collection manifest's per-source metadata—requiring zero schema migration or re-ingestion of existing collections:
  - `profile` MUST support scalar strings as well as top-level `$eq`, `$ne`, `$in`, and `$nin` operator predicates, matching recorded document profiles consistently with profile normalization conventions.
  - `ingested_after` and `ingested_before` MUST accept valid ISO-8601 date/time strings at top level and match document commit timestamps using inclusive window boundaries.
  - Nesting manifest keys inside `$or` / `$and` branches or pairing them with unsupported operators (such as range operators on `profile` or operator dicts on `ingested_after` / `ingested_before`) MUST fail upfront with a clear validation error.
  - All resolved manifest filters MUST combine conjunctively with any chunk-level constraints (including intersecting/pruning explicit top-level `source` scalar, `$eq`, `$in`, `$ne`, and `$nin` predicates) into an allowed source set; if the resulting source set is empty, retrieval MUST immediately return an empty list without invoking embeddings or underlying stores.
- **FR-006**: Direct structured filter operator expressions (`$eq`, `$ne`, `$in`, `$nin`, `$gt`, `$gte`, `$lt`, `$lte`, `$and`, `$or`) passed programmatically MUST execute with equivalent filtering semantics across both dense vector and hybrid lexical search, while rejecting malformed or unrecognized operators upfront via explicit validation errors—never silently dropping predicates.
- **FR-007**: User filters referencing the reserved internal `"type"` key MUST be rejected upfront with a clear validation error; in addition, underlying child chunk queries MUST unconditionally isolate active child records (`type = "child"`) in conjunction with any user filters as defense-in-depth, while continuing to enforce committed active document version filtering across both dense and hybrid search paths.
- **FR-008**: All user-facing reference documentation (API reference, CLI reference, and project README) MUST accurately document `where` programmatic usage, supported chunk/manifest keys, CLI `--where` syntax, and operator validation behavior.

### Key Entities

- **Filter Criteria (`where`)**: Optional structured key-value or operator mapping supplied by callers or assembled from CLI `--where key=value` flags specifying metadata constraints over indexed documents and chunks.
- **Chunk Attributes**: Per-segment persisted metadata recorded at ingestion time (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`, plus internal `type`).
- **Manifest Attributes**: Per-document provenance recorded in the collection manifest (`profile`, `ingested_at`) used to derive allowed source lists without altering stored chunks.
- **Allowed Source Set**: In-memory intersection of sources satisfying manifest-level constraints (`profile`, `ingested_after`, `ingested_before`) and any explicit source filter prior to issuing search queries.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of filtered queries specifying valid chunk attributes (`source`, `section`, `clause`, `page`, `chunk_index`, `doc_version`, `embed_model`) or manifest attributes (`profile`, `ingested_after`, `ingested_before`) return only passages belonging to matching committed documents and child segments across both dense and hybrid search modes (and with reranking enabled), with zero re-ingestion required for pre-existing collections.
- **SC-002**: 100% of filter combinations yielding zero matching documents in the manifest or zero intersection with an explicit source filter return an empty list immediately with 0 embedding calls and 0 storage query errors.
- **SC-003**: 100% of attempts to filter by the reserved internal `"type"` key fail upfront with explicit reserved-key errors, 100% of underlying child queries return zero parent placeholder records even under adversarial inputs, and all child-to-parent expansion semantics remain intact.
- **SC-004**: 100% of malformed `--where` CLI arguments, unrecognized metadata keys, invalid non-integer numeric filters (`page`, `chunk_index`), malformed ISO-8601 date strings, and unsupported structured filter expressions fail cleanly with clear diagnostic messages before executing retrieval or generation.
- **SC-005**: 100% of mandatory safety gates (**Release Gate #1** Exception Preservation and **Release Gate #2** PII Safety) and repository verification checks pass with zero regressions to unfiltered retrieval or evaluation workflows.

## Assumptions

- **Case sensitivity & normalization**: Convenience `profile` filtering matches document profile names case-insensitively when uppercase normalized names match collection records (`DEFAULT`, `POLICY`), whereas content metadata values (`source`, `section`, `clause`) match their stored normalized values exactly.
- **Date/time interpretation & bounds**: `ingested_after` and `ingested_before` evaluate inclusive boundaries (`>= ingested_after` and `<= ingested_before`). Full timestamps accept explicit offsets or trailing `"Z"` UTC markers across all supported runtime environments; timezone-naive timestamps assume UTC, and date-only `YYYY-MM-DD` strings map cleanly to inclusive UTC day bounds (`00:00:00+00:00` for `ingested_after` and `23:59:59.999999+00:00` for `ingested_before`) so same-day date filters behave intuitively.
- **Empty filter mapping**: Passing an empty filter mapping (`{}`) programmatically is normalized identically to omitting `where` (`None`), whereas empty compound operator lists (such as `{"$and": []}` or `{"$in": []}`) fail validation clearly before store execution.
- **Cross-reference enrichment scope**: When parent expansion and cross-reference resolution are active, retrieved matching parent sections preserve existing cross-reference resolution semantics; metadata filters scope which candidate child matches qualify retrieval.
- **Out of Scope**: Schema migration CLI commands, injecting arbitrary custom user key-value tags at ingestion time, persistent configuration-file default filter sections, or changing persisted chunk schema requirements in ways that invalidate existing collections.

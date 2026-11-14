# Feature Specification: First-Class Enricher Stage & Cross-Reference Migration

**Feature Branch**: `feat/008-enricher-stage`  
**Created**: 2026-11-14  
**Status**: Draft  
**Input**: User description: "Formalize post-clean, pre-chunk document transformation as a first-class Enricher pipeline stage and migrate intra-document cross-reference resolution into it while preserving clean phase boundaries."

## Clarifications

### Session 2026-11-14

- Q: How should the system handle a custom chunking profile that sets the legacy cross-reference toggle (`resolve_crossrefs`) to enabled while leaving its explicit sequence of enrichers (`enrichers`) empty? → A: Automatically populate `enrichers` with `["crossrefs"]` when `resolve_crossrefs` is enabled and `enrichers` is omitted or empty (while leaving `resolve_crossrefs=False` profiles untouched and letting any explicit non-empty `enrichers` sequence apply directly).
- Q: When should declared enricher names be looked up in the registry, and how should a chunking profile that lists the same enricher name more than once be handled? → A: Resolve and instantiate all declared enrichers up front before checking or skipping files, and execute repeated names sequentially in exact declared list order.
- Q: How should legacy entry points for the existing cross-reference helpers behave after migrating cross-reference logic into the Enricher and phase-neutral components? → A: Preserve all five existing cross-reference helpers (`resolve_crossrefs`, `extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `truncate_excerpt`) as silent compatibility re-exports from their legacy location with zero deprecation warnings.

## Constitution Check

All requirements comply with `.specify/memory/constitution.md` (`v1.2.2`, Principles I–VII and Quality Gates): Scope Discipline (`I`, realized through existing Enricher stage without expanding public scope), Two-Phase Isolation (`II`, phase-neutral cross-reference core with zero Phase 2 → Phase 1 dependencies), Library Purity (`III`), Search Small Return Big (`IV`), Exception Preservation & Release Gate #1 (`V`), Local-First execution (`VI`), and Structured Correctness with mandatory full test suite pass (`VII`). Full gate matrix verified in [plan.md](plan.md#constitution-check).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extensible Ordered Enricher Pipeline Stage (Priority: P1)

A developer implements a custom post-clean document transformation (such as future PII scrubbing) by registering an enricher component in the Enricher registry under a unique name and listing that name on a chunking profile's ordered enricher sequence, without modifying core pipeline orchestration logic. During Phase 1 ingestion and synchronization, the pipeline executes the profile's declared enrichers in exact sequence order between document cleaning and chunking, providing full ingestion context (including document version) to each stage.

**Why this priority**: Formalizing enrichment as a registry-backed, profile-driven stage unlocks modular document transformations across future pipeline capabilities without accumulating conditional branches in core ingestion orchestration.

**Independent Test**: Can be fully tested by registering custom test enrichers that append observable ordering markers and record received ingestion context fields, ingesting and syncing documents under profiles declaring multiple ordered enrichers (plus profiles declaring unknown or failing enrichers), and verifying execution order, context completeness, and clean store/manifest preservation upon failure.

**Acceptance Scenarios**:

1. **Given** custom enrichers `"first"` and `"second"` registered in the Enricher registry and a chunking profile specifying `enrichers` as `["first", "second"]`, **When** a document is ingested or synchronized under that profile, **Then** `"first"` executes immediately after document cleaning, `"second"` executes on the output of `"first"` immediately before chunking, and both receive the complete ingestion context including document version.
2. **Given** a chunking profile whose declared enricher sequence contains an unregistered name or an enricher that fails during execution, **When** ingestion or synchronization runs for a document batch, **Then** the pipeline fails loudly and aborts cleanly before committing any changes to the vector store, lexical index, or manifest.
3. **Given** a newly registered custom enricher added solely through the Enricher registry and referenced by name in a profile, **When** documents are ingested using that profile, **Then** the custom transformation runs end-to-end without any modifications to core Phase 1 pipeline orchestration.

---

### User Story 2 - Built-In Cross-Reference Enricher on Policy Profile (Priority: P1)

Intra-document cross-reference resolution operates as a built-in `"crossrefs"` enricher registered in the Enricher registry rather than a special-case inline pipeline branch. Users ingesting with the `POLICY` chunking profile continue receiving identical intra-document cross-reference enrichment (`[Crossref ...]` annotations), while users ingesting with the `DEFAULT` profile execute zero enrichers.

**Why this priority**: Migrating the existing production cross-reference behavior validates the new Enricher stage under real workloads and enforces zero behavioral or safety regressions across policy document ingestion and retrieval.

**Independent Test**: Can be fully tested by ingesting policy documents with both `POLICY` and `DEFAULT` profiles, running existing cross-reference resolution scenarios, golden retrieval benchmarks, and Reverse Safety Gate verifications, and asserting exact parity with pre-migration behavior.

**Acceptance Scenarios**:

1. **Given** a document containing intra-document section cross-references ingested under the `POLICY` profile (`enrichers` containing only `"crossrefs"`), **When** ingestion completes, **Then** resulting chunks contain the exact same `[Crossref ...]` enrichment, cycle prevention, and unresolved-reference warning logs produced prior to migration.
2. **Given** a document ingested under the `DEFAULT` profile (empty `enrichers` sequence), **When** ingestion runs, **Then** zero enrichers are invoked and document text proceeds unaltered from cleaning directly to chunking.
3. **Given** ingested policy rules containing exceptions, exclusions, and nested cross-references, **When** golden retrieval evaluations and Reverse Safety Gate checks run after ingestion, **Then** retrieval outputs and exception-preservation guarantees match baseline expectations with zero regressions.

---

### User Story 3 - Phase-Neutral Cross-Reference Core & Phase Isolation (Priority: P2)

Pure cross-reference parsing, source matching, heading target indexing, and bounded excerpt formatting reside in a shared phase-neutral component used independently by both the Phase 1 `"crossrefs"` enricher and Phase 2 query-time cross-document reference enrichment. Existing compatibility entry points for intra-document cross-reference helpers continue operating cleanly without introducing dependencies from Phase 2 retrieval into Phase 1 ingestion.

**Why this priority**: Moving cross-reference logic cleanly preserves Two-Phase Architecture isolation by eliminating cross-phase dependencies while preventing duplicate pattern, indexing, and truncation rules across ingest and query workflows.

**Independent Test**: Can be tested by running automated architectural boundary checks confirming zero dependencies from Phase 2 query components into Phase 1 ingestion components, running multi-document query-time cross-document reference enrichment, and running existing cross-reference verification suites without broken references.

**Acceptance Scenarios**:

1. **Given** the refactored Phase 1 enricher and Phase 2 query retrieval subsystems, **When** component dependencies across Phase 2 query components are inspected, **Then** zero Phase 2 components depend upon or reference any Phase 1 ingestion component.
2. **Given** both Phase 1 intra-document enrichment and Phase 2 query-time cross-document enrichment operating on matching section references and headings, **When** references are extracted and formatted, **Then** both phases apply the exact same canonical pattern matching, source matching, target indexing, and bounded excerpt truncation logic from the shared phase-neutral component.
3. **Given** existing external callers or test suites referencing established intra-document cross-reference helper entry points, **When** those suites execute after migration, **Then** compatibility entry points continue working seamlessly without broken references.

---

### Edge Cases

- **Empty enricher sequence (`DEFAULT` or custom empty profile)**: The pipeline skips enrichment immediately without performing unnecessary registry lookups and passes the cleaned document straight to chunking.
- **Unregistered enricher name on a profile**: Fails immediately during upfront enricher resolution before scanning, skipping unchanged files, or touching persistent stores or manifest state, raising a clear registry lookup error even when zero files need re-ingestion.
- **Failure mid-sequence or mid-batch**: If a later enricher (for example, the second of two enrichers) or a later document in a batch fails, transactional staging ensures zero partial chunk embeddings, lexical index entries, or manifest records remain committed.
- **Repeated enricher execution or chained mutations**: If a profile declares multiple enrichers—including duplicate names in sequence—all instances run sequentially in strict declared order, where each enricher receives the document as modified by its predecessor.
- **Legacy custom profiles constructed with the historical cross-reference toggle**: Custom profiles created with `resolve_crossrefs` enabled and an omitted or empty `enrichers` sequence automatically populate `enrichers` with `["crossrefs"]` at profile initialization, keeping orchestration strictly `enrichers`-driven without ad-hoc conditional branches.
- **Cyclic, self-referential, or unresolved cross-references**: Self-links and cyclic section references never trigger infinite expansion or recursive re-enrichment, and unresolved targets emit clear warning logs rather than failing ingestion.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Phase 1 document pipeline MUST execute document enrichment as a formal, profile-driven stage deterministically between document cleaning and document chunking during both document ingestion and incremental synchronization.
- **FR-002**: Chunking profiles MUST support an immutable ordered sequence of enricher names (`enrichers`), empty for `DEFAULT` (running zero enrichers) and `["crossrefs"]` for `POLICY`, automatically populating `enrichers` with `["crossrefs"]` whenever `resolve_crossrefs` is enabled with an omitted or empty `enrichers` sequence, while preserving all existing profile attributes cleanly.
- **FR-003**: Core Phase 1 pipeline orchestration MUST resolve and instantiate every enricher name listed in the active profile's `enrichers` sequence from the Enricher registry up front before scanning or skipping files, and execute those instances sequentially in exact declared order (including any repeated entries) between cleaning and chunking, passing each enricher the document and complete ingestion context (including collection, source, content hash, document version `doc_version`, embedding model, and active profile).
- **FR-004**: Core Phase 1 pipeline orchestration MUST dispatch post-clean transformations exclusively through the Enricher stage and profile enricher list rather than hardcoding specific enricher transformations inline.
- **FR-005**: Any failure to resolve a declared enricher name or any exception raised by an executing enricher MUST abort ingestion or synchronization prior to modifying the vector store, lexical index, or ingestion manifest.
- **FR-006**: Intra-document cross-reference resolution MUST be implemented as a built-in `"crossrefs"` enricher registered in the Enricher registry.
- **FR-007**: Shared pure cross-reference domain logic—specifically pattern matching, source matching, target heading indexing, and bounded excerpt truncation—MUST be extracted into a single phase-neutral component shared by both the Phase 1 `"crossrefs"` enricher and Phase 2 query-time cross-document enrichment.
- **FR-008**: Phase 2 query and retrieval components MUST NOT depend upon or reference any Phase 1 ingestion component.
- **FR-009**: Migration into the `"crossrefs"` enricher MUST preserve existing intra-document cross-reference resolution output (`[Crossref ...]` annotations), cycle prevention, unresolved-reference warning behavior, golden retrieval results, and Reverse Safety Gate compliance with zero regressions.
- **FR-010**: Existing legacy entry points for cross-reference utilities (`resolve_crossrefs`, `extract_doc_crossrefs`, `index_section_targets`, `match_source_key`, `truncate_excerpt`) MUST be preserved as silent backward-compatible re-exports with zero deprecation warnings so existing callers and stability suites continue passing unchanged.

### Key Entities

- **Enricher**: A named, registered document-transformation component that receives a post-clean document and ingestion context and produces a transformed document prior to chunking.
- **Enricher Registry**: Central registry mapping string identifiers (such as `"crossrefs"`) to enricher implementations for declarative lookup and extension without core pipeline edits.
- **Chunking Profile**: Immutable ingestion configuration specifying chunking rules alongside an ordered sequence of enricher identifiers (`enrichers`) to execute for documents ingested with that profile.
- **Ingestion Context**: Contextual metadata carrier passed to pipeline stages containing the collection identifier, source identifier, content hash, document version (`doc_version`), embedding model identifier, and active chunking profile.
- **Phase-Neutral Cross-Reference Core**: Shared cross-reference utility providing pure pattern recognition, source matching, heading target indexing, and bounded excerpt formatting independently accessible to both Phase 1 ingestion enrichment and Phase 2 query-time cross-document enrichment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of Phase 2 query and retrieval components exhibit zero direct or transitive dependencies on Phase 1 ingestion components, verified by automated architectural boundary inspection.
- **SC-002**: 100% of golden retrieval evaluations, existing cross-reference verification tests, and Reverse Safety Gate checks pass with zero regressions in enriched chunk content, cycle prevention, or unresolved-reference warning output compared to pre-migration baseline.
- **SC-003**: Custom user-registered enrichers execute in exact profile-declared sequence without requiring edits to core pipeline orchestration, verified with multi-enricher ordering tests.
- **SC-004**: 100% of simulated unknown-enricher lookups and failing custom enrichers abort document ingestion cleanly, leaving vector storage, lexical index entries, and manifest state completely unchanged relative to pre-run snapshots.
- **SC-005**: Documents ingested under the `DEFAULT` profile invoke 0 enrichers, while documents ingested under the `POLICY` profile invoke the `"crossrefs"` enricher and produce output identical to baseline `POLICY` ingestion.

## Assumptions

- **Legacy Profile Explicit Override**: When a custom profile explicitly specifies a non-empty `enrichers` sequence (regardless of `resolve_crossrefs`) or leaves both `resolve_crossrefs=False` and `enrichers` empty, the explicit `enrichers` sequence governs pipeline execution directly without overriding user-supplied enrichers.
- **Existing Public Enricher Contract**: The existing Enricher stage contract and public registration surface remain stable so third-party or internal custom enrichers register seamlessly without altering documented public capabilities.
- **Out of Scope**: Adding new enricher implementations beyond migrating `"crossrefs"` (such as PII scrubbing, which is scheduled for Stage 4) is explicitly out of scope for this feature.

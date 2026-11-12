# Feature Specification: Core RAG Pipeline

**Feature Branch**: `001-core-rag-pipeline`

**Created**: 2026-11-12

**Status**: Draft

**Input**: User description: "Product.md"

## Clarifications

### Session 2026-11-12

- Q: When ingesting a directory containing multiple files, how should the system behave if one file is unsupported or corrupted? (FR-001) → A: Fail-fast (atomic batch): abort the run with a descriptive error before modifying the store
- Q: When multiple child chunks match the same parent section during retrieval, which similarity score and rank position should the deduplicated parent section receive? (FR-012) → A: Maximum child score (`max(score)`), ordered descending by that score
- Q: How should cross-reference resolution operate across document boundaries during ingestion? (FR-003) → A: Intra-document resolution only; log inter-document or missing target references
- Q: How should a document be uniquely identified when purging and replacing its previous records during incremental re-ingestion? (FR-010) → A: Relative path from ingested root directory (or filename when ingesting a single file)
- Q: When running `docpipe ask` or calling the `answer` workflow and zero sections meet the similarity threshold (empty retrieval), should the system still call the LLM or return a deterministic no-context message immediately? (FR-014) → A: Short-circuit: return a deterministic refusal message immediately without calling the LLM
- Q: When `reindex` runs to migrate a collection to a new embedding model, should it re-embed the existing chunks already stored in the database or re-ingest the original files from disk? (FR-011) → A: Re-embed existing stored child chunks directly from the vector database
- Q: How should the `LEGAL` chunking profile be handled in the v0.1 release? (Key Entities) → A: Ship `DEFAULT` and `POLICY` only in v0.1; defer `LEGAL` to post-v0.1 (tracked in `docs/future-features.md`)
- Q: What scale and direction should `RetrievedChunk.score` and the `threshold` parameter use? (FR-014) → A: Normalized cosine similarity in `[0.0, 1.0]` where higher is more similar (`score >= threshold`)
- Q: When `ingest` is called on a file or directory whose content hash matches an existing entry in the manifest, should it skip the unchanged file or force re-ingestion? (FR-010) → A: Skip unchanged files via manifest hash check (plus optional `--force` flag to re-ingest)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Semantic Search Without Generation (Priority: P1)

A user or developer ingests documents (such as PDF, DOCX, HTML, Markdown, or plain text files) into a local repository and issues queries to retrieve the most relevant sections, inspecting exact source citations and parent contexts without invoking an LLM.

**Why this priority**: Core retrieval is the essential prerequisite for RAG and delivers immediate standalone value as an offline-capable, structure-aware semantic document search engine.

**Independent Test**: Ingest a multi-format document corpus (including policies and contracts) and query for specific topics via the CLI or Python API; verify that deduplicated parent sections containing precise source metadata (document, section, page) are returned without any LLM or cloud connection.

**Acceptance Scenarios**:

1. **Given** a directory containing supported document formats (PDF, DOCX, HTML, Markdown, TXT), **When** the user runs the ingestion command with a chosen profile, **Then** the documents are cleaned, structure-chunked, embedded, and indexed with stable IDs and explicit child/parent relationships.
2. **Given** an indexed document collection, **When** a user queries for a concept, **Then** matching child chunks are searched and their expanded parent sections are returned deduplicated, preserving full section context.
3. **Given** an indexed collection, **When** a user queries with parent expansion disabled, **Then** raw child chunks with prepended context headers are returned.
4. **Given** an indexed collection and a similarity threshold, **When** a query matches only items below the threshold, **Then** no irrelevant sections are returned.

---

### User Story 2 - Policy Retrieval with Exception Preservation (Reverse Safety Gate) (Priority: P1)

An analyst or compliance officer queries policy or legal documents where rules contain exceptions, disqualifiers, or conditions (e.g., "except for new hires", "unless authorized"). The retrieval system guarantees that whenever a rule is returned, its associated exceptions are also present in the context.

**Why this priority**: Incomplete retrieval that omits exceptions inverts rule meaning and produces dangerous hallucinations. This is a non-negotiable safety requirement and release gate.

**Independent Test**: Execute the reverse safety test suite against a fixture policy corpus containing exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`); verify 100% of queries against rule clauses return contexts containing the necessary exception clauses.

**Acceptance Scenarios**:

1. **Given** a policy document where a general entitlement has an exception clause in the same section, **When** a user queries about the general entitlement, **Then** the retrieved parent context contains both the entitlement and the exception clause.
2. **Given** a document with internal cross-references (e.g., "subject to Section 4"), **When** the document is ingested, **Then** the cross-reference is resolved or logged, ensuring the referring chunk remains complete and interpretable.

---

### User Story 3 - Grounded Question Answering via Local or Cloud Providers (Priority: P2)

A developer or privacy-conscious user poses questions against their ingested documents and receives concise, grounded answers generated by a local or cloud LLM, strictly adhering to the retrieved context and citing source references.

**Why this priority**: Provides the end-to-end RAG experience for users who want direct answers, building cleanly on top of the P1 retrieval foundation as an optional capability.

**Independent Test**: Start a local LLM (e.g., via Ollama) with no external network access, ask a question via CLI or API, and verify the answer is factually grounded in the retrieved text with no internet traffic. Then pass a cloud provider model string and confirm it uses environment variable credentials seamlessly.

**Acceptance Scenarios**:

1. **Given** an indexed collection and a running local LLM, **When** the user asks a question, **Then** prompt construction compiles a context-bounded prompt and the LLM returns an answer citing source sections without network calls.
2. **Given** an indexed collection and a question whose answer is absent from the corpus, **When** the answer function executes, **Then** the response explicitly indicates that the answer is not present in the provided context.
3. **Given** an environment variable configured with a cloud provider API key, **When** the user specifies a cloud provider/model string, **Then** the system successfully completes generation without requiring codebase modifications or hardcoded credentials.

---

### User Story 4 - Corpus Incremental Maintenance & Synchronization (Priority: P2)

A user updates, adds, or deletes documents in their corpus directory, or migrates to a new embedding model. The system tracks file state via an ingestion manifest (`mtime` fast path + `sha256` content hash), skips unchanged files, replaces modified documents via transactional delete-then-reinsert without leaving orphaned clauses when a document shrinks, removes deleted files during synchronization, and preserves the previous document version if re-ingestion fails midway.

**Why this priority**: Essential for operational correctness and safety in evolving policy/legal repositories; prevents stale or deleted clauses from remaining retrievable and misleading the LLM (Principle V & VII).

**Independent Test**: Ingest a directory containing documents A and B; shrink document A (deleting a clause), touch document B (changing `mtime` without changing content), delete document C, and run `sync`. Verify that document B is skipped, document A's deleted clause is completely absent from the store (zero orphans), and simulating an ingestion failure on a subsequent edit leaves the prior version of document A intact and queryable.

**Acceptance Scenarios**:

1. **Given** an indexed document that shrinks (a section or clause is deleted), **When** the document is re-ingested or synced, **Then** updates use source-scoped delete-then-reinsert (never ID-only upsert) so zero orphaned chunks from the deleted section remain in the store.
2. **Given** a directory of documents tracked in the ingestion manifest, **When** `sync` is executed after adding a new file, modifying an existing file, touching an unchanged file, and deleting a file, **Then** the unchanged file is skipped via `mtime`/`sha256` checks, the new and modified files are indexed, and the deleted file's records and manifest entry are purged.
3. **Given** an existing indexed document, **When** a re-ingestion attempt fails midway (e.g., due to a corrupted edit or provider interruption), **Then** the staging/version-flip mechanism preserves the previous version intact and queryable.
4. **Given** an existing collection, **When** a user runs `status`, `remove`, or `reindex` with a new embedding model, **Then** the system accurately reports manifest state, removes the specified source document, or re-embeds the entire collection under the new model lock.

---

### Edge Cases

- **Corrupted or Unsupported File Format**: What happens when an unsupported file type or a malformed PDF is provided (individually or inside a batch directory)? The system MUST fail fast (atomic batch), aborting the entire ingestion run with a descriptive error message before writing any changes to the vector store.
- **Shrinking Document or Mid-Update Failure**: What happens when an edited document has fewer sections than before, or when re-ingestion fails halfway through embedding? The system MUST stage new records under a new `doc_version` (content hash prefix), flip the manifest version pointer upon completion, and purge all old records for that source (`delete-then-reinsert` semantics) so shrinking files never leave orphaned chunks and failed updates leave the prior version untouched.
- **Clause Exceeding Target Chunk Size**: What happens when an indivisible legal or policy clause exceeds the target token limit of a chunking profile? The clause MUST NOT be severed; it is retained intact as a single chunk to preserve semantic integrity.
- **No Results Above Similarity Threshold**: What happens when a query matches nothing in the vector store or all matches fall below the caller's score threshold? The system MUST return an empty list of sections, and when answering (`docpipe ask` or `answer`), short-circuit to return a deterministic "not found in context" message immediately without invoking the LLM.
- **Embedding Model Mismatch**: What happens when a user attempts to ingest or query a collection using an embedding model different from the one recorded in the collection's manifest? The system MUST detect the mismatch against the manifest's `embed_model` lock and refuse to proceed with an explicit error directing the user to `reindex`, rather than silently mixing vector spaces.
- **Missing or Empty Provider Credentials**: What happens when a cloud provider model is requested but its corresponding environment variable is missing? The system MUST return a clear error stating the missing environment variable without leaking any environment variables or attempting network fallbacks.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept documents in PDF, DOCX, HTML, Markdown, and plain text formats, extracting raw text while preserving structural elements (headings, section labels, clause numbers, and page numbers), and aborting the entire batch ingestion atomically before modifying the store if any file is unsupported or corrupted.
- **FR-002**: System MUST clean extracted text by removing HTML/script tags, normalizing whitespace, and removing repetitive headers/footers without stripping semantic clause identifiers.
- **FR-003**: System MUST identify internal (intra-document) cross-references within each ingested document, resolving references to sections/clauses in the same document by attaching referenced text to ensure self-contained context, and logging any inter-document or missing target references.
- **FR-004**: System MUST chunk cleaned text using structure-aware boundaries (headings, sections, clauses), never splitting within a clause in policy profiles.
- **FR-005**: System MUST produce two distinct tiers of chunks for each document: searchable child chunks (clauses/paragraphs) and retrievable parent sections, linked by a parent identifier.
- **FR-006**: System MUST prepend a context header (source document name, section label, clause label) to every child chunk.
- **FR-007**: System MUST scope chunk overlap strictly within parent sections, resetting overlap counters at section boundaries.
- **FR-008**: System MUST embed child chunks into dense vector representations using a unified, provider-agnostic interface, supporting local and cloud models via `provider/model` strings.
- **FR-009**: System MUST persist child chunks (with vectors) and parent sections (with placeholder vectors and parent identifiers) in a local vector database, assigning `type` (`"child"` vs `"parent"`) and `doc_version` metadata tags.
- **FR-010**: System MUST maintain a database-collocated ingestion manifest per collection recording each source document's relative path (or filename for single-file ingest), `sha256` content hash, file size, `mtime`, ingestion timestamp, `embed_model`, and derived chunk/parent IDs; detect changes via `mtime` fast-path hint plus `sha256` verification so `ingest` and `sync` skip unchanged files (with an optional `--force` override on `ingest`); and perform updates via transactional staging and source-scoped delete-then-reinsert so shrinking files leave zero orphans and failed updates preserve the prior version.
- **FR-011**: System MUST support three-way directory reconciliation (`sync`) against the manifest (ingesting new files, skipping unchanged files, replacing modified files, and purging deleted files), single-source deletion (`remove`), manifest inspection (`status`), and full collection re-embedding upon model change (`reindex`, which re-embeds existing stored child chunks directly from the vector database under the new model).
- **FR-012**: System MUST perform similarity search exclusively against active child chunks (`where={"type": "child"}`) after verifying the query embedding model matches the manifest's `embed_model`, and expand returned matches to their parent sections by ID.
- **FR-013**: System MUST deduplicate expanded parent sections before returning results to the caller or prompt builder, assigning each parent the highest similarity score (`max(score)`) among its matching child chunks and ordering returned parents by that score descending.
- **FR-014**: System MUST support configurable retrieval parameters: `top_k`, optional minimum similarity threshold (`score >= threshold` on a normalized cosine similarity scale of `[0.0, 1.0]`), and an option to disable parent expansion (`expand_parent=false`).
- **FR-015**: System MUST construct prompts as a pure function (no network calls, no side effects) combining user questions and retrieved contexts with instructions enforcing context grounding and citation.
- **FR-016**: System MUST optionally generate grounded answers using a language model via a provider-agnostic interface reading credentials solely from environment variables, and MUST short-circuit with a deterministic refusal message without calling the LLM when zero retrieved sections are available.
- **FR-017**: System MUST default to a local model (Ollama) for generation and embeddings, ensuring the entire pipeline can execute with zero external network connectivity.
- **FR-018**: System MUST expose a public Python API surface consisting of `ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, optional `answer`, and shared data types (`Chunk`, `EmbeddedChunk`, `RetrievedChunk`).
- **FR-019**: System MUST provide a command-line interface with Phase 1 commands (`docpipe ingest`, `docpipe sync`, `docpipe status`, `docpipe remove`, `docpipe reindex`) and Phase 2 commands (`docpipe query`, `docpipe ask`).
- **FR-020**: System MUST enforce that no library module reads user configuration files; user configuration file reading is restricted solely to the CLI.
- **FR-021**: System MUST enforce exception preservation verified by a reverse test suite that acts as a mandatory release gate.

### Key Entities *(include if feature involves data)*

- **Chunk**: The foundational text unit containing a unique content-addressed ID, text content (with prepended context header if child), optional `parent_id`, and metadata (source document, `doc_version`, section, clause, page, index, `type`).
- **EmbeddedChunk**: A Chunk augmented with a vector embedding (real embedding vector for child chunks, placeholder vector for parent sections).
- **RetrievedChunk**: An EmbeddedChunk returned from similarity retrieval, carrying its normalized cosine relevance similarity score (`[0.0, 1.0]`, higher is more similar).
- **Ingestion Manifest**: A database-collocated state record tracking the collection's locked `embed_model` and per-source metadata (`content_hash`, `size`, `mtime`, `ingested_at`, `doc_version`, `chunk_ids`, `parent_ids`) to drive fast change detection, transactional replacement, and three-way directory synchronization.
- **Chunking Profile**: A static configuration constant defining chunk token limits, overlap limits, and structure preservation rules (`DEFAULT` and `POLICY` in v0.1; `LEGAL` deferred post-v0.1).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of policy queries containing exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) retrieve contexts that include the necessary exception text in the reverse test suite.
- **SC-002**: Re-ingesting or syncing a modified or shrinking document replaces 100% of its previous child and parent records (zero orphaned chunks remain from deleted clauses), skips unchanged files via `mtime`/`sha256` verification without re-embedding, and preserves 100% of the prior version's records if re-ingestion fails midway.
- **SC-003**: The full pipeline (ingest, query, ask) executes successfully in an offline environment (zero outbound network packets) using default local configurations.
- **SC-004**: Parent section retrieval returns zero duplicate parent sections across top-k child matches.
- **SC-005**: Prompt construction operates in sub-millisecond time with zero external network dependencies.
- **SC-006**: Core package installation without generation extras remains lightweight and functional for all Phase 1 and Phase 2 retrieval operations.
- **SC-007**: 100% of retrieved sections contain sufficient source metadata (source file, section label, and page number where available) to enable verifiable human attribution.

## Assumptions

- **A-001**: Users running local embedding and generation have a working local runtime (e.g., Ollama) installed and operational on their machine.
- **A-002**: A local vector database instance (ChromaDB) can run embedded in-process on the local filesystem without requiring an external database daemon.
- **A-003**: A machine with 16 GB RAM and standard CPU capabilities is sufficient to run local embedding, storage, retrieval, and standard 7B-class local LLM generation.
- **A-004**: Advanced search enhancements such as reranking, hybrid search, multi-turn memory, and web dashboards are intentionally out of scope for v0.1.
- **A-005**: All credentials for third-party cloud providers are supplied via standard environment variables and never persisted to disk or emitted to logs.

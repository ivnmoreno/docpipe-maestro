# docpipe-maestro — Product Description

> **Purpose of this document:** This is a *product description*, not a specification. It is written to be ingested by an AI-driven specification skill (e.g., GitHub SpecKit's `/specify` command) to generate a formal, implementation-ready specification. It intentionally states **what** the product is and **why** it is that way, leaving **how** (detailed interface contracts, task breakdowns, implementation plans) to be generated downstream.

| Field | Value |
|---|---|
| Product name | `docpipe-maestro` |
| Import name | `docpipe_maestro` |
| CLI command | `docpipe-maestro` |
| Version under description | 0.1.0 |
| Document status | Description complete; specification pending |
| Intended consumer | AI specification skill (SpecKit `/specify`) |
| Author | Project owner |
| Date | 2026-11-12 |

---

## 1. Executive Summary

`docpipe-maestro` is a **Python library** that implements a **minimal Retrieval-Augmented Generation (RAG) pipeline**. It accepts documents in a variety of file formats, cleans and chunks them with structure-awareness, embeds the chunks into vectors, stores them in a local vector database, retrieves the most relevant sections in response to a question, and optionally generates a grounded answer using a language model.

It is deliberately scoped: it is a **pipeline library**, not an application, not a framework, and not a platform. It provides the reusable engine that future projects (chatbots, search tools, assistants) will import and build upon.

The library is designed to be **provider-agnostic** at every layer that touches an external service: embeddings and generation can run entirely locally (via Ollama) or through any of the major cloud providers (OpenAI, Anthropic, Google Gemini, Groq, Together AI, and others), through a single unified interface.

---

## 2. Problem Statement

Building a RAG system from scratch requires solving a set of recurring, non-trivial problems:

1. **Ingesting heterogeneous documents.** PDFs, DOCX files, HTML pages, Markdown, and plain text all require different parsing strategies. Naïve extraction loses structure and produces noisy text.
2. **Chunking correctly.** Embedding models have input limits, and retrieving whole documents is imprecise. Naïve chunking cuts mid-sentence or mid-clause, which produces vectors that misrepresent the source text.
3. **Retrieving with precision *and* completeness.** Small chunks retrieve precisely but arrive incomplete. Large chunks arrive complete but retrieve imprecisely. A correct system must do both.
4. **Preserving domain-critical structure.** In policy, legal, and technical documents, a cut clause can *invert* the meaning of a rule. A retrieval system that returns a rule without its exception is not merely imprecise — it is actively misleading to the language model that consumes it.
5. **Managing provider churn.** Embedding and generation providers differ in API shape, authentication, and rate limits. Building against one provider and later switching is expensive if the architecture is not abstracted from the start.

Every RAG project re-solves these problems. `docpipe-maestro` solves them once, in a clean, tested, reusable library, so that future projects can focus on the application layer — the UI, the sessions, the deployment — rather than the pipeline beneath it.

---

## 3. Target Users and Personas

| Persona | Description | How they use docpipe-maestro |
|---|---|---|
| **Solo developer / learner** | An individual building their first RAG project, learning the concepts by building them | Uses the CLI to ingest a personal document collection; imports the library into a small Streamlit or Gradio app |
| **Application developer** | A developer building a RAG-backed product (chatbot, search tool, assistant) | Imports `ingest`, `retrieve`, `build_prompt`, and optionally `answer` into a FastAPI service or desktop application |
| **Researcher / analyst** | A user who needs to query a large personal or organizational document corpus | Uses the CLI directly for semantic search over policy manuals, research papers, or contracts |
| **Privacy-conscious user** | A user whose documents must not leave their machine | Runs the entire pipeline locally with Ollama for embeddings and generation, and ChromaDB for storage |

All personas share one need: **a reliable, complete pipeline they do not have to rebuild.**

---

## 4. Core Concepts and Glossary

These terms are used throughout this document and should be preserved in the generated specification.

| Term | Definition |
|---|---|
| **Chunk** | A unit of text extracted from a document, sized for embedding. Each chunk has a unique ID, text content, optional parent reference, and metadata. |
| **Child chunk** | A small, precise unit of text (typically a clause or paragraph). Children are embedded with real vectors and are the units searched during retrieval. |
| **Parent section** | A larger unit of text (typically a section or subsection) that contains one or more children. Parents are stored without meaningful vectors and are fetched by ID to provide complete context. |
| **Parent-child retrieval** | The retrieval strategy in which the system *searches* child chunks for precision but *returns* parent sections for completeness. |
| **Embedding** | A dense numeric vector representation of text. Texts with similar meaning produce similar vectors. |
| **Vector database** | A storage system that indexes embeddings for fast similarity search. `docpipe-maestro` uses ChromaDB. |
| **Ingest** | The offline phase in which documents are read, cleaned, chunked, embedded, and stored. |
| **Query** | The online phase in which a user question is embedded, matched against stored vectors, and used to retrieve relevant sections. |
| **Crossref** | An internal reference within a document (e.g., "see §2.1", "as defined in Section 7", "subject to Article 4"). Crossrefs must be resolved so that a retrieved clause is not meaningless in isolation. |
| **Profile** | A named set of chunking parameters tailored to a document domain (e.g., `DEFAULT`, `POLICY`, `LEGAL`). |
| **Reverse test** | A safety test that asserts every retrieved context containing a rule also contains that rule's exceptions and conditions. |
| **Provider** | An external service supplying embeddings or generation. Providers are addressed by `provider/model` strings and configured via environment variables. |

---

## 5. Product Scope

### 5.1 In Scope

- Reading documents from PDF, DOCX, HTML, Markdown, and plain text files
- Preserving document structure (headings, sections, clauses) during ingestion
- Cleaning extracted text (removing HTML artifacts, normalizing whitespace, stripping boilerplate)
- Chunking text with awareness of document structure and clause boundaries
- Producing both child chunks and parent sections, linked by a parent identifier
- Detecting and resolving internal cross-references
- Embedding chunks via a provider-agnostic interface
- Storing chunks, vectors, and metadata in a local vector database
- Retrieving parent sections in response to a question
- Constructing prompts from retrieved sections and a question
- Optionally generating a grounded answer using a language model
- Exposing a Python library API and a command-line interface
- Running entirely locally or entirely in the cloud, or in a hybrid configuration
- Testing, including a dedicated safety test for exception-preservation

### 5.2 Explicitly Out of Scope (Non-Goals)

The following are **deliberately excluded**. Their absence is a design decision, not an oversight. Each belongs either to an application built *on top of* `docpipe-maestro` or to a future, separately scoped project.

| Excluded | Rationale |
|---|---|
| Web UI, desktop UI, chat interface | Belongs to the consuming application |
| HTTP API server (FastAPI, Flask) | Belongs to the consuming application |
| Authentication, authorization, multi-tenancy | Belongs to the consuming application |
| Conversation state, multi-turn memory | Belongs to the consuming application |
| Streaming responses | Belongs to the consuming application |
| Reranking, query rewriting, hybrid search | Future optional modules, not v0.1 |
| Evaluation harness for answer quality | Separate tooling |
| Deployment tooling (Docker, CI/CD for the app) | Belongs to the consuming application |
| A hosted service, SaaS offering, or web dashboard | Out of product category entirely |

**Rule of thumb for future contributions:** *Anything that assumes "a user is waiting" belongs to the application. Anything that is "given input, produce output" belongs to the library.*

---

## 6. Architecture: The Two-Phase Model

The entire library is organized around **two phases that run at different times, at different frequencies, for different reasons.** This is the organizing principle of the package layout, the API surface, the CLI, and the test strategy.

### 6.1 Phase 1 — Ingest (Offline)

Runs once per document batch. Triggered when documents are added, updated, or removed. Latency is not critical; correctness is.

```
files → intake → clean → crossrefs → chunker → embedder → store
```

**Output:** a populated vector database containing child chunks (with vectors) and parent sections (fetchable by ID).

### 6.2 Phase 2 — Query (Online)

Runs on every user question. Latency matters. The database is read-only in this phase.

```
question → embed → retrieve (match children, return parents) → build prompt → [optional: generate answer]
```

**Output:** either a list of relevant parent sections (retrieval-only) or a grounded answer with source attribution (full RAG).

### 6.3 Why the Phases Are Separate

- **Different frequencies.** Phase 1 runs occasionally; Phase 2 runs constantly.
- **Different performance requirements.** Phase 1 can take minutes; Phase 2 must be fast.
- **Different failure modes.** A Phase 1 bug produces a bad index; a Phase 2 bug produces bad answers from a good index.
- **Shared components.** Both phases use the same embedding interface and the same vector store. The phases are separate, but they are not duplicated.

---

## 7. Functional Requirements

### 7.1 Phase 1 — Document Ingestion

#### 7.1.1 Intake

The system shall accept a file path (or directory of files) and produce raw text plus structure metadata.

- The system shall detect file format from the extension, falling back to content inspection for ambiguous cases.
- The system shall support at minimum: PDF, DOCX, HTML, Markdown, and plain text.
- The system shall preserve structural metadata (headings, section boundaries, clause numbering, page numbers) where the source format provides it.
- The system shall fail loudly with a clear error message for unsupported formats rather than producing silently corrupted output.

#### 7.1.2 Cleaning

The system shall transform raw extracted text into clean text suitable for chunking.

- The system shall remove HTML tags, script and style content, and formatting artifacts.
- The system shall normalize whitespace (collapse multiple blank lines, trim leading and trailing whitespace).
- The system shall remove repeated boilerplate (page headers, footers, navigation elements) where detectable.
- The system shall **not** remove text that is semantically meaningful, including clause numbering, section labels, and legal qualifiers.

#### 7.1.3 Crossref Resolution

The system shall detect and resolve internal cross-references.

- The system shall detect reference patterns including but not limited to: `§2.1`, `Section 7`, `Article 4`, `Clause 3.2.1`, "as defined in", "subject to", "see above".
- The system shall resolve each detected reference to the referenced section's text, where that section exists in the ingested corpus.
- The system shall append or embed the referenced text into the referring chunk (or its parent section) so that the resulting chunk is self-contained.
- The system shall log unresolved references for manual review rather than silently dropping them.

#### 7.1.4 Chunking

The system shall split clean text into child chunks and parent sections.

- The system shall be **structure-aware**: it shall prefer to split at heading boundaries, section boundaries, and clause boundaries, in that order, before falling back to sentence boundaries, and only as a last resort to character boundaries.
- The system shall **never split inside a clause**. A clause that exceeds the nominal chunk size shall be kept intact as a single chunk.
- The system shall produce **both** child chunks and parent sections for each document, linked by a parent identifier.
- The system shall prepend a context header to each child chunk's text, containing at minimum: document name, section label, and clause label (where available). This ensures each chunk is self-contained and traceable to its source.
- The system shall apply overlap **only within a parent section**, resetting at section boundaries. Overlap shall not span unrelated sections.
- The system shall attach metadata to each chunk including: source filename, section label, clause label, page number (where available), chunk index within its parent, and a `type` field distinguishing child from parent.

#### 7.1.5 Embedding

The system shall convert child chunks into vector embeddings.

- The system shall use a provider-agnostic embedding interface.
- The system shall support local embedding providers (e.g., Ollama) and cloud embedding providers through a single unified call.
- The system shall batch embedding requests to reduce latency and cost.
- The system shall embed **only child chunks**. Parent sections shall not be embedded with meaningful vectors.
- The system shall record the embedding model identifier alongside each stored vector, so that model mismatches between ingest and query can be detected and reported.

#### 7.1.6 Storage

The system shall persist chunks, vectors, and metadata in a local vector database.

- The system shall use a single ChromaDB collection for v0.1.
- Each stored record shall carry a `type` field with value `"child"` or `"parent"`.
- Child records shall carry real embedding vectors.
- Parent records shall carry a zero vector (or an equivalent placeholder) so the database accepts them, and shall be excluded from similarity search by an explicit `where={"type": "child"}` filter.
- The system shall support fetching records by ID, used to expand child matches to their parent sections.
- The system shall support deletion of all records belonging to a given source document, enabling re-ingestion without duplication.

#### 7.1.7 Update and Synchronization

The system shall manage file updates, deletions, and model consistency through a database-collocated ingestion manifest.

- The system shall maintain an **ingestion manifest** recording, per source file: content hash (`sha256`), file size, `mtime`, ingestion timestamp, active `doc_version`, embedding model, and the IDs of all child and parent records derived from it.
- The system shall detect changes via **content hash**, using `mtime` and `size` as a fast-path hint only (skipping file reads when `mtime` and `size` are unchanged, and skipping re-ingestion when `mtime` changed but `sha256` is identical).
- The system shall implement updates as **source-scoped delete-then-reinsert**, never as ID-only upsert, to prevent orphaned records when documents shrink or clauses are deleted.
- The system shall wrap updates in a **staging/version-flip envelope** (`doc_version` metadata field) so that a failed re-ingestion leaves the previous version intact and queryable.
- The system shall support **three-way directory reconciliation** (`sync`) between a target directory and the manifest: ingesting new files, skipping unchanged files, re-ingesting changed files, and removing records for deleted files.
- The system shall enforce an **embedding model lock** per collection in the manifest, detecting model mismatches between ingest and query and refusing to proceed unless the collection is explicitly reindexed (`reindex`).
- The system shall expose a manifest inspection capability (`status`) so a user can see indexed files, hashes, timestamps, embedding model, and record counts.

### 7.2 Phase 2 — Retrieval

#### 7.2.1 Query Embedding

- The system shall embed the user's question using the **same embedding model** used at ingest time.
- The system shall detect and report model mismatches rather than silently producing meaningless similarity scores.

#### 7.2.2 Similarity Search and Parent Expansion

- The system shall perform similarity search against child chunks only, using a `where={"type": "child"}` filter.
- The system shall return the top *k* child matches, where *k* is configurable and defaults to 5.
- The system shall optionally apply a minimum similarity threshold, filtering out matches below it. This prevents the system from confidently answering when no relevant content exists.
- The system shall expand matched children to their parent sections by fetching parents by ID.
- The system shall deduplicate parent sections, so that multiple matching children from the same parent produce a single returned section.
- The system shall expose a configuration flag allowing parent expansion to be disabled, for cases where raw child chunks are desired.

#### 7.2.3 Prompt Construction

- The system shall construct a prompt string from a question and a set of retrieved sections.
- The prompt shall instruct the language model to answer using only the provided context, and to indicate when the answer is not present in the context.
- The prompt shall preserve source attribution metadata so that the consuming application can surface citations.
- Prompt construction shall be a **pure function**: it shall perform no network calls and have no side effects.

### 7.3 Phase 2 — Optional Generation

- The system shall optionally generate an answer by sending a constructed prompt to a language model.
- Generation shall be an **optional capability**, not part of the core install.
- The system shall use a provider-agnostic generation interface.
- The system shall support local providers (e.g., Ollama) and cloud providers (OpenAI, Anthropic, Google Gemini, Groq, Together AI, and others) through `provider/model` string addressing.
- The system shall read provider credentials exclusively from environment variables. No credential shall ever be read from a file, hardcoded, or logged.
- The system shall not maintain a hardcoded registry of providers. Provider resolution shall be delegated to the unified client library.
- The system shall define a single default model, which shall be a local model, so that the default configuration requires no API key and no network access to a third-party service.

### 7.4 Command-Line Interface

The system shall provide a CLI aligned with the two-phase model, offering ingestion and corpus lifecycle commands for Phase 1 and retrieval/RAG commands for Phase 2.

| Command | Phase | Purpose |
|---|---|---|
| `docpipe-maestro ingest <path>` | Phase 1 | Ingest a file or directory into the vector database |
| `docpipe-maestro sync <directory>` | Phase 1 | Reconcile a directory against the manifest (add new, update changed, remove deleted) |
| `docpipe-maestro status` | Phase 1 / 2 | Inspect the manifest: indexed files, hashes, embedding model, and record counts |
| `docpipe-maestro remove <path>` | Phase 1 | Delete all records and manifest entry for a specific source document |
| `docpipe-maestro reindex --model <m>` | Phase 1 | Re-embed and re-ingest all tracked corpus sources under a new embedding model |
| `docpipe-maestro query "<question>"` | Phase 2 (retrieval only) | Return relevant sections without generating an answer |
| `docpipe-maestro ask "<question>"` | Phase 2 (full RAG) | Generate an answer using retrieved sections |

- `ingest` and `sync` shall accept a `--profile` flag selecting a chunking profile.
- All commands shall accept a `--collection` flag selecting the target collection.
- `query` and `ask` shall accept a `--top-k` flag.
- `query` shall accept `--expand-parent` / `--no-expand-parent` flags.
- `ask` shall accept a `--model` flag taking a `provider/model` string.
- The CLI shall be the **only** component permitted to read a user configuration file, if the user supplies one. All library modules shall take configuration via arguments.

### 7.5 Public Library API

The library shall expose a deliberately minimal public surface. Anything not reachable through this surface does not belong in the core.

| Symbol | Kind | Purpose |
|---|---|---|
| `ingest` | function | Phase 1 orchestration: path → populated store |
| `sync` | function | Phase 1 directory reconciliation: directory → updated store + manifest |
| `remove` | function | Phase 1 deletion: source path → purged from store and manifest |
| `status` | function | Phase 1 / 2 inspection: collection → manifest status summary |
| `reindex` | function | Phase 1 model migration: collection + new embed model → re-embedded store |
| `retrieve` | function | Phase 2 retrieval: question → list of retrieved sections |
| `build_prompt` | function | Phase 2 prompt construction: question + sections → prompt string |
| `answer` | function (optional extra) | Phase 2 generation: prompt → answer string |
| `Chunk` | type | The base data shape |
| `EmbeddedChunk` | type | A chunk with a vector |
| `RetrievedChunk` | type | An embedded chunk with a similarity score |

---

## 8. Data Model

All modules that handle chunks shall use a shared, centrally defined data shape. This shape shall be defined in a single module and imported everywhere, to prevent drift between components.

### 8.1 Chunk

The base unit. Produced by chunking; consumed by embedding, storage, retrieval, and prompt construction.

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier, stable across re-ingestion |
| `text` | string | The chunk's text, including prepended context header for children |
| `parent_id` | string or null | ID of the parent section, or null for parent records themselves |
| `metadata` | mapping | Source filename, section label, clause label, page number, chunk index, `type` field |

### 8.2 EmbeddedChunk

A chunk with its vector representation.

| Field | Type | Description |
|---|---|---|
| *(all Chunk fields)* | | |
| `vector` | list of floats | The embedding; a zero vector for parent records |

### 8.3 RetrievedChunk

A chunk returned from retrieval, with its relevance score.

| Field | Type | Description |
|---|---|---|
| *(all EmbeddedChunk fields)* | | |
| `score` | float | Similarity score from the vector database |

### 8.4 Storage Record Shape

Each record in the single ChromaDB collection shall have the following logical shape:

```
{
  "id":         "<stable content-addressed id>",
  "vector":     [floats] | [0.0, 0.0, ...],
  "text":       "<chunk text, header included for children>",
  "parent_id":  "<parent id>" | null,
  "metadata": {
     "type":         "child" | "parent",
     "source":       "<filename>",
     "doc_version":  "<sha256 content hash prefix>",
     "section":      "<section label>",
     "clause":       "<clause label>" | null,
     "page":         <int> | null,
     "chunk_index":  <int>,
     "embed_model":  "<model identifier>"
  }
}
```

The `type` field is load-bearing: every similarity query must filter on `where={"type": "child"}`. The `doc_version` field enables transactional staging/version-flip updates so failed re-ingestions never corrupt the active version.

---

## 9. Configuration Rules

These rules are **locked** and must be preserved verbatim in the generated specification.

1. **No module in the library reads a config file.** `cli.py` is the only file that may.
2. **Chunking profiles are Python constants**, defined in a dedicated configuration module. They are data structures, not files, and are not user-editable at runtime without code changes.
3. **Provider credentials come exclusively from environment variables.** No credential shall appear in source code, configuration files, logs, or error messages.
4. **Provider selection is per-call**, via a `provider/model` string argument. There is no registry, allowlist, or enumeration of providers in the codebase.
5. **The default generation model is local**, so that the out-of-the-box configuration requires no third-party account.

---

## 10. Chunking Profiles

The system shall ship with named chunking profiles. Profiles are selected per ingestion run.

| Profile | Intended for | Chunk size (tokens) | Overlap (tokens) | Special behavior |
|---|---|---|---|---|
| `DEFAULT` | General prose, articles, notes | 512 | 64 | Structure-aware splitting |
| `POLICY` | Policies, procedures, handbooks | 1000 | 80 | Clause-preserving; parent-child enabled; crossref resolution enabled |
| `LEGAL` | Contracts, terms, regulations | *to be determined* | *to be determined* | Clause-preserving; crossref resolution mandatory; reverse test mandatory |

The `POLICY` profile is the reference implementation of the parent-child strategy and is the profile against which the reverse test is run.

---

## 11. Retrieval Strategy (Detailed)

The retrieval strategy is the most consequential design decision in the product and must be preserved exactly in the specification.

### 11.1 The Core Principle

**Search small, return big.**

Child chunks are small and precise, making them good *search targets*. Parent sections are large and complete, making them good *answer sources*. The system searches the former and returns the latter.

### 11.2 Why This Is Necessary

A chunked rule that reads *"Employees are entitled to 20 days of annual leave"* can be **semantically inverted** by an adjacent exception clause that reads *"Employees with less than one year of service are not entitled to the full allowance."*

If retrieval returns only the first chunk, the language model will confidently produce an incorrect answer. This is not a precision problem; it is a **correctness and safety problem**. Parent-child retrieval ensures that the exception travels with the rule.

### 11.3 The Pipeline

1. Embed the question using the ingest-time embedding model.
2. Query the vector database with `where={"type": "child"}` and `top_k` set by the caller (default 5).
3. Optionally filter results below a similarity threshold.
4. Collect the unique `parent_id` values from the matched children.
5. Fetch each unique parent section by ID.
6. Return the parent sections to the caller (or to prompt construction).

### 11.4 Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `top_k` | 5 | Number of child matches to retrieve |
| `threshold` | none | Minimum similarity score; below this, results are discarded |
| `expand_parent` | true | Whether to expand children to parents |

---

## 12. Generation and Provider Strategy

### 12.1 Unified Provider Interface

Both embeddings and generation shall be routed through a single unified client library that resolves `provider/model` strings to the appropriate backend. This eliminates the need for a provider registry in the product's own code.

### 12.2 Supported Providers

The system shall support, at minimum, the following providers through the unified interface:

- **Local:** Ollama (chat and embedding models)
- **Cloud:** OpenAI, Anthropic (Claude), Google Gemini, Groq, Together AI
- **Any OpenAI-compatible endpoint** reachable by base URL override

### 12.3 Credentials

Credentials shall be read from environment variables only, following the naming conventions of the unified client library. The system shall not validate, store, or log credentials.

### 12.4 Default Behavior

The default generation model shall be a local model served by Ollama, so that a new user can run the full pipeline — ingest, query, and answer — without creating an account with any cloud provider.

### 12.5 Extensibility

Adding a new provider shall require **no code change** to `docpipe-maestro`. It shall be sufficient to install the provider's SDK (if the unified client requires it) and pass the appropriate `provider/model` string.

---

## 13. Testing and Quality Gates

### 13.1 Unit Tests

| Test file | Covers |
|---|---|
| `test_chunker.py` | Structure-aware splitting; clause preservation; parent-child linking; scoped overlap |
| `test_store.py` | Round-trip of `parent_id`; `type` field filtering; retrieval by ID; deletion by source; staging/version flip |
| `test_manifest.py` | `mtime` fast path; `sha256` change detection; 3-way directory sync; shrinking file orphan cleanup; model mismatch lock |
| `test_retriever.py` | Parent expansion; deduplication; threshold filtering; `expand_parent=false` behavior |

### 13.2 The Reverse Test (Safety Test)

The system shall include a dedicated test that enforces exception preservation:

> For every clause in the test corpus that contains an exception marker (`except`, `unless`, `not entitled`, `subject to`, `provided that`), querying that clause's topic shall return a context that **also contains the exception text**.

This test shall be run against a fixture policy corpus and shall be treated as a release gate. A failure indicates that retrieval can mislead the language model, and the release shall be blocked.

This test is not a unit test of a single function. It is a **property test of the whole retrieval system**, and it is the primary evidence that the product's central safety claim holds.

### 13.3 Static Checks

The project shall run, in CI, at minimum:

- A linter and formatter
- A static type checker, consistent with the package shipping type information
- The full test suite

A release shall not be published if any of these checks fail.

---

## 14. Packaging and Distribution

### 14.1 Identity

| Attribute | Value |
|---|---|
| Distribution name | `docpipe-maestro` |
| Import name | `docpipe_maestro` |
| CLI command | `docpipe-maestro` |
| License | MIT or Apache-2.0 (to be finalized) |
| Minimum Python | 3.10 |

### 14.2 Build

The project shall use a modern build backend with versioning derived from version control tags, so that the version number has a single source of truth.

### 14.3 Dependencies

**Core runtime dependencies:**

- A unified provider client library (for embeddings and generation)
- A text-splitting library with structure-aware capabilities
- A document parsing library capable of handling multiple formats
- A local vector database

**Optional extras:**

- An extra enabling the optional generation capability
- Per-format extras for document parsing, so that users install only the parsers they need

**Development dependencies:**

- Test runner and coverage tool
- Linter and formatter
- Static type checker
- Build and publishing tools

### 14.4 Publishing

The project shall be published to TestPyPI before PyPI, and shall use a trusted publishing flow rather than long-lived API tokens. The distribution name shall be verified as available before the first upload, and the name shall be reserved via a pending trusted publisher until the first real release.

---

## 15. Non-Functional Requirements

| Requirement | Description |
|---|---|
| **Privacy** | The full pipeline shall be runnable with zero external network calls when configured with local providers |
| **Provider independence** | No layer of the product shall require a specific provider |
| **Traceability** | Every retrieved section shall carry metadata sufficient to cite its source document, section, and page |
| **Determinism** | Given identical inputs and configuration, ingestion shall produce identical chunk identifiers |
| **Incrementality** | A single document shall be re-ingestable without disturbing the rest of the collection |
| **Failure clarity** | Unsupported formats, missing credentials, and model mismatches shall produce clear, actionable error messages |
| **Footprint** | A default local configuration shall run comfortably on a laptop with 16 GB of RAM and no GPU |
| **Extensibility** | Adding a provider, a file format, or a chunking profile shall not require modifying existing modules beyond registration |

---

## 16. Locked Technical Decisions

The following decisions have been made and shall be preserved in the specification unless the user explicitly reopens them.

| # | Decision | Rationale |
|---|---|---|
| 1 | Name: `docpipe-maestro` / `docpipe_maestro` | Avoids collision with an existing package; matches distribution and import names |
| 2 | Two-phase architecture with phase-grouped module layout | Makes the operational model legible from the file tree |
| 3 | Shared data types in a dedicated module | Prevents schema drift across seven modules |
| 4 | Chunking profiles as Python constants, not files | Profiles are code-level configuration, not user data |
| 5 | Single vector collection with a `type` field | Simplest correct design for v0.1; two-collection split is the documented migration path |
| 6 | Parent records stored with zero vectors, excluded by filter | ChromaDB requires a vector per record; filtering is the correct way to hide parents from search |
| 7 | No provider registry in code | The unified client already resolves provider strings; a registry would duplicate and stale |
| 8 | Credentials from environment variables only | Prevents secret leakage via source control or logs |
| 9 | Default model is local | Zero-friction first run; no third-party account required |
| 10 | Generation is an optional extra | Keeps the core install small and the library's promise honest |
| 11 | Reverse test as a release gate | The product's safety claim is only credible if it is tested |
| 12 | The library reads no config file; the CLI may | Preserves library purity and app-layer flexibility |

---

## 17. User Stories

These stories illustrate intended use and shall inform acceptance criteria.

**US-1 — Personal document Q&A (local)**
> As a privacy-conscious user, I want to ingest my lease, insurance policy, and warranty documents and ask questions about them, with all processing happening on my own machine, so that my personal documents never leave my computer.

**US-2 — Policy compliance lookup**
> As an HR analyst, I want to ask "how many days of leave does a new employee get?" and receive an answer that includes both the general rule and the new-hire exception, so that I do not give incorrect guidance.

**US-3 — Developer integration**
> As an application developer, I want to import three functions from the library and have a working retrieval backend in my FastAPI service, so that I can focus on building the product rather than the pipeline.

**US-4 — Provider flexibility**
> As a developer, I want to switch from a cloud model to a local model by changing one argument, so that I can develop offline and deploy to the cloud without rewriting code.

**US-5 — Corpus maintenance**
> As a user, I want to re-ingest a document after editing it and have the old version fully replaced, so that my answers reflect the current document rather than a stale copy.

**US-6 — Semantic search without generation**
> As a researcher, I want to retrieve relevant passages without generating an answer, so that I can read the source material myself.

---

## 18. Acceptance Criteria

The v0.1 release shall be accepted when all of the following hold.

**Phase 1**
1. A PDF, a DOCX file, an HTML file, a Markdown file, and a plain text file can each be ingested without error.
2. Ingested documents produce both child chunks and parent sections, linked by `parent_id`.
3. Every child chunk's text contains a context header identifying its source document and section.
4. No clause is split across two chunks in the `POLICY` profile.
5. A document can be re-ingested and its previous records are fully replaced.

**Phase 2**
6. A question returns parent sections, deduplicated, with `top_k` respected.
7. Setting `expand_parent=false` returns raw child chunks instead.
8. A similarity threshold can be applied and excludes low-scoring results.
9. `build_prompt` is a pure function with no network calls.

**Generation**
10. With Ollama running locally, `docpipe-maestro ask "<question>"` returns a grounded answer with no cloud credentials configured.
11. Switching `--model` to a cloud provider string works without any code change.
12. No credential appears in any log or error message.

**Safety**
13. The reverse test passes against the fixture policy corpus.
14. Every clause containing an exception marker, when queried, returns context containing that exception.

**Quality**
15. The full test suite passes in CI.
16. Linting and type checking pass in CI.

**Packaging**
17. The package installs from TestPyPI in a clean virtual environment.
18. The CLI is available as `docpipe-maestro` after installation.
19. The optional generation extra installs and enables `answer` without affecting the core install.

---

## 19. Open Questions and Future Work

These are explicitly **out of scope for v0.1** but noted for continuity.

| Item | Status |
|---|---|
| `LEGAL` profile parameters | To be determined after `POLICY` is validated |
| Two-collection storage split | Migration path if the single collection grows large |
| Reranking | Future optional module |
| Hybrid (keyword + vector) search | Future optional module |
| Query rewriting | Future optional module |
| Evaluation harness for answer quality | Separate tooling |
| Additional file formats (XLSX, PPTX) | Additive, no architectural change |
| Additional vector database backends | Additive, via the storage adapter interface |

---

## 20. Appendix

### 20.1 Module Responsibilities

| Module | Phase | Responsibility |
|---|---|---|
| `types.py` | both | Shared data shapes |
| `config.py` | both | Chunking profiles as Python constants |
| `manifest.py` | 1 and 2 | Database-collocated ingestion manifest: hash tracking, `mtime` fast path, 3-way reconciliation, and model lock |
| `intake.py` | 1 | File → raw text + structure metadata |
| `clean.py` | 1 | Raw text → clean text |
| `crossrefs.py` | 1 | Detect and resolve internal references |
| `chunker.py` | 1 | Clean text → child chunks + parent sections |
| `embedder.py` | 1 | Chunks → vectors |
| `store.py` | 1 and 2 | Persist and fetch chunks, vectors, metadata, and transactional version cleanup |
| `ingest.py` | 1 | Orchestrate Phase 1 (`ingest`, `sync`, `remove`, `status`, `reindex`) |
| `retriever.py` | 2 | Question → parent sections |
| `prompts.py` | 2 | Sections + question → prompt string |
| `answer.py` | 2 | Prompt → answer (optional extra) |
| `cli.py` | both | Command-line interface; the only module permitted to read a user config file |

### 20.2 The One-Sentence Positioning

> **`docpipe-maestro` is a minimal RAG pipeline: it ingests any document, chunks it correctly (including policy-grade parent-child retrieval and cross-reference resolution), embeds it, stores it, retrieves the right sections for a question, and optionally generates a grounded answer. It is the engine — not the app, not the framework.**

### 20.3 The Rule for Future Contributions

> If a proposed feature cannot be reached through the public API surface described in Section 7.5, or does not fit the one-sentence positioning in Section 20.2, it does not belong in the core.

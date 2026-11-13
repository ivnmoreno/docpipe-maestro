# Tasks: Core RAG Pipeline

**Input**: Design documents from `/specs/001-core-rag-pipeline/` (`spec.md`, `plan.md`, `data-model.md`, `contracts/`, `research.md`, `quickstart.md`, `.specify/memory/constitution.md`)

**Prerequisites**: Python 3.10+, `uv`, ChromaDB, LiteLLM

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. Tests are included per Constitution Quality Gates ("Every behavioral change ships with tests") and Constitution Principle V (Reverse Safety Test release gate).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`US1`, `US2`, `US3`, `US4`)
- Exact file paths are specified for every task

---

## Phase 1: Setup (Project Initialization & Build System)

**Purpose**: Establish package structure, packaging metadata, tools, and shared testing fixtures per `plan.md`.

- [X] T001 Initialize package structure and PEP 561 marker in `src/docpipe_maestro/py.typed` and directories `src/docpipe_maestro/ingest/`, `src/docpipe_maestro/query/`, and `tests/fixtures/`
- [X] T002 [P] Create `pyproject.toml` with `hatchling` + `hatch-vcs` build backend, core dependencies (`chromadb`, `litellm`, `langchain-text-splitters`), optional extras (`pdf`, `docx`, `html`, `generation`, `all`), `docpipe-maestro` CLI script entry point, and PEP 735 dev groups (`pytest`, `ruff`, `mypy`)
- [X] T003 [P] Create root `README.md` and `LICENSE` (MIT) aligned with `Product.md` and `plan.md`
- [X] T004 [P] Create test configuration and deterministic offline test doubles (dummy vector embedder and stubbed LLM client) in `tests/conftest.py`

---

## Phase 2: Foundational (Blocking Prerequisites & Shared State)

**Purpose**: Implement shared domain models, static chunking profiles, embedding adapter, vector store adapter, and manifest persistence before any user story begins.

**⚠️ CRITICAL**: No user story phase work can begin until this phase is complete.

- [X] T005 Implement shared domain types and exceptions in `src/docpipe_maestro/types.py` (`ChunkMetadata` with `type` in `{"child", "parent"}` and `doc_version`; `Chunk` with deterministic 16-char ID `sha256(source|doc_version|type|section|clause|chunk_index|text)[:16]`; `EmbeddedChunk` with `vector: list[float]`; `RetrievedChunk` with normalized cosine `score: float` in `[0.0, 1.0]`; `ChunkingProfile`; `SourceRecord`; `Manifest`; `IngestResult`; `SyncResult`; `CollectionStatus`; `DocpipeError` hierarchy)
- [X] T006 [P] Implement static profiles and defaults in `src/docpipe_maestro/config.py` (`DEFAULT` profile with `chunk_size=512, overlap=64`; `POLICY` profile with `chunk_size=1000, overlap=80, clause_preserving=True, parent_child=True, resolve_crossrefs=True`; default models `ollama/nomic-embed-text` and `ollama/llama3.2`)
- [X] T007 [P] Implement shared unified embedding adapter in `src/docpipe_maestro/embedder.py` wrapping `litellm.embedding` with batching, dimension validation, and environment variable authentication
- [X] T008 Implement database-collocated manifest manager in `src/docpipe_maestro/manifest.py` (`<persist_dir>/manifests/<collection>.json`, `mtime` and `size` fast-path check, `sha256` content hashing, collection `embed_model` lock check, atomic commit via temporary file and `os.replace`)
- [X] T009 Implement ChromaDB persistent store adapter in `src/docpipe_maestro/store.py` (`chromadb.PersistentClient`, collection configuration `metadata={"hnsw:space": "cosine"}`, `None`-value metadata stripping on write / restoration on read, parent placeholder vectors `[0.0] * dim`, child-only query `where={"type": "child"}`, batch fetch by IDs, and source/version scoped deletion)
- [X] T010 Unit test foundational store and manifest components in `tests/test_store.py` and `tests/test_manifest.py` (verifying `None` metadata roundtrip, zero-vector parents, cosine distance conversion, fast-path hash skip, atomic manifest swap, and model lock enforcement)

**Checkpoint**: Core foundation ready. User story implementation can now begin.

---

## Phase 3: User Story 1 - Semantic Search Without Generation (Priority: P1) 🎯 MVP

**Goal**: Ingest multi-format documents (PDF, DOCX, HTML, Markdown, TXT) with structure-aware chunking and retrieve deduplicated parent sections using normalized cosine similarity scores without calling an LLM.

**Independent Test**: Ingest a corpus containing diverse formats; run `docpipe-maestro query "<question>"` and verify deduplicated parent sections with exact source citations (`source`, `section`, `clause`, `page`) are returned offline.

### Tests for User Story 1
- [X] T011 [P] [US1] Create sample multi-format fixture documents in `tests/fixtures/docs/` (`sample.md`, `sample.txt`, `sample.html`, `sample.docx`, `sample.pdf`)
- [X] T012 [P] [US1] Create unit tests for intake and cleaning in `tests/test_intake_clean.py` (verifying format detection, magic bytes fallback, HTML script/style stripping, whitespace normalization, and atomic fail-fast abort on corrupted/unsupported files per FR-001)
- [X] T013 [P] [US1] Create unit tests for hierarchical chunking in `tests/test_chunker.py` (verifying heading/section/clause splitting, parent-child ID linking, context header generation, and section-scoped overlap)
- [X] T014 [P] [US1] Create unit tests for Phase 2 retrieval in `tests/test_retriever.py` (verifying child query `where={"type": "child"}`, parent expansion by ID, `max(score)` parent deduplication, descending sort, threshold cutoff `score >= threshold`, and `expand_parent=False` raw child return)

### Implementation for User Story 1
- [X] T015 [US1] Implement document intake parser in `src/docpipe_maestro/ingest/intake.py` (detect extension, magic byte validation for PDF/DOCX/HTML, extract headings, section labels, clause labels, and page numbers; raise `UnsupportedFormatError` or `MissingExtraError`)
- [X] T016 [US1] Implement text cleaner in `src/docpipe_maestro/ingest/clean.py` (remove HTML/script/style tags, normalize whitespace, strip repetitive headers/footers while strictly retaining clause labels and numbering per FR-002)
- [X] T017 [US1] Implement structure-aware hierarchical chunker in `src/docpipe_maestro/ingest/chunker.py` (split by headings, sections, clauses, and sentences using offline-safe token counting; produce parent sections and child chunks; prepend `[Source: ... | Section: ... | Clause: ...]` context header to children; scope overlap strictly within parent sections per FR-004, FR-005, FR-006, FR-007)
- [X] T018 [US1] Implement Phase 1 single-document ingestion pipeline in `src/docpipe_maestro/ingest/pipeline.py` (orchestrate intake → clean → chunk → embed child chunks → initial ChromaDB write and manifest registration)
- [X] T019 [US1] Implement Phase 2 semantic retriever in `src/docpipe_maestro/query/retriever.py` (embed question, verify model lock, execute child search `where={"type": "child"}`, convert cosine distance to `score = 1.0 - distance`, filter `score >= threshold`, expand parent sections by ID, deduplicate parents with `max(score)`, and sort descending per FR-012, FR-013, FR-014)
- [X] T020 [US1] Implement public `ingest` and `retrieve` functions in `src/docpipe_maestro/__init__.py` matching contracts in `specs/001-core-rag-pipeline/contracts/python-api.md`
- [X] T021 [US1] Implement CLI commands `docpipe-maestro ingest <path>` and `docpipe-maestro query "<question>"` in `src/docpipe_maestro/cli.py` with flags `--profile`, `--collection`, `--persist-dir`, `--embed-model`, `--force`, `--top-k`, `--threshold`, `--expand-parent`/`--no-expand-parent`, and global `--version`

**Checkpoint**: User Story 1 complete and independently testable as a standalone semantic search engine (MVP).

---

## Phase 4: User Story 2 - Policy Retrieval with Exception Preservation (Priority: P1)

**Goal**: Guarantee that retrieval contexts for rules containing exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) always include the associated exception text via intra-document crossref resolution, clause preservation, and the mandatory Reverse Safety Test release gate.

**Independent Test**: Execute `pytest tests/test_reverse_safety.py` against the fixture policy corpus; verify 100% of queries against rule clauses return contexts containing the necessary exception text (SC-001).

### Tests for User Story 2
- [X] T022 [P] [US2] Create curated policy corpus fixtures in `tests/fixtures/policy_corpus/` containing clauses with all 5 exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) and internal cross-references (`Section 4`, `§2.1`, `Clause 3.2`)
- [X] T023 [P] [US2] Create unit tests for cross-reference detection and resolution in `tests/test_crossrefs.py` (verifying intra-document link resolution, circular reference guard, and logging of inter-document/missing targets per FR-003)
- [X] T024 [P] [US2] Implement the mandatory Reverse Safety Test suite in `tests/test_reverse_safety.py` (property test ingesting policy corpus with `POLICY` profile and asserting 100% exception preservation across all exception clauses per FR-021 and SC-001)

### Implementation for User Story 2
- [X] T025 [US2] Implement intra-document cross-reference resolver in `src/docpipe_maestro/ingest/crossrefs.py` (regex pattern detection for section/clause symbols, target lookup within current parsed document, append referenced text, cycle prevention, and warning logger for missing targets)
- [X] T026 [US2] Enforce non-splitting clause preservation in `src/docpipe_maestro/ingest/chunker.py` when `profile.clause_preserving` is `True` (keeping clauses and their subordinate exceptions intact in single chunks even if nominal token limit is exceeded)
- [X] T027 [US2] Integrate cross-reference resolution into the ingestion pipeline in `src/docpipe_maestro/ingest/pipeline.py` between `clean` and `chunker` steps

**Checkpoint**: User Stories 1 and 2 pass. The Reverse Safety Test gate is fully operational.

---

## Phase 5: User Story 3 - Grounded Question Answering via Local or Cloud Providers (Priority: P2)

**Goal**: Construct pure, offline, citation-grounded prompts and optionally generate answers using local (Ollama) or cloud LLMs, with zero network calls on default local runs and deterministic refusal on empty retrieval.

**Independent Test**: Ask a question against indexed documents using default local Ollama configuration; verify the answer cites source documents and sections without internet access. Run an out-of-domain query with a threshold and verify deterministic immediate refusal without calling the LLM.

### Tests for User Story 3
- [X] T028 [P] [US3] Create prompt construction and generation tests in `tests/test_prompts_answer.py` (verifying pure sub-millisecond `build_prompt` execution, source citation formatting, short-circuit refusal on empty retrieval, env var credential handling, and zero credential leakage in error messages per FR-015, FR-016, and SC-005)

### Implementation for User Story 3
- [X] T029 [US3] Implement pure prompt builder in `src/docpipe_maestro/query/prompts.py` (format retrieved sections with `[Source: ... | Section: ... | Clause: ... | Page: ...]`, embed strict grounding instructions, assert no side effects or network calls per FR-015)
- [X] T030 [US3] Implement optional answer generation in `src/docpipe_maestro/query/answer.py` (short-circuit when `has_context=False` or empty sections; delegate `provider/model` to `litellm.completion`; read credentials strictly from environment variables; raise `MissingCredentialError` without leaking values per FR-016, FR-017)
- [X] T031 [US3] Expose `build_prompt` and lazy optional `answer` in `src/docpipe_maestro/__init__.py` (deferring import of `query.answer` until accessed and raising `MissingExtraError` with `[generation]` install instructions if generation dependencies are unavailable)
- [X] T032 [US3] Implement CLI command `docpipe-maestro ask "<question>"` in `src/docpipe_maestro/cli.py` with flags `--model`, `--top-k`, `--threshold`, `--embed-model`, and `--api-base`

**Checkpoint**: Full RAG pipeline operational with both retrieval-only and grounded generation workflows.

---

## Phase 6: User Story 4 - Corpus Incremental Maintenance & Synchronization (Priority: P2)

**Goal**: Support three-way directory reconciliation (`sync`), fast-path hash skipping, source deletion (`remove`), manifest inspection (`status`), model migration (`reindex`), and crash-safe transactional staging so shrinking files leave zero orphaned clauses.

**Independent Test**: Ingest a corpus; shrink a document by deleting a clause, touch an unchanged document, delete a third document, and run `docpipe-maestro sync`. Verify unchanged file is skipped, deleted file is purged, shrinking document has zero orphaned records (SC-002), and model mismatch is refused until `reindex` is run.

### Tests for User Story 4
- [X] T033 [P] [US4] Create synchronization and lifecycle tests in `tests/test_sync_lifecycle.py` (verifying `sync` three-way reconciliation `added`/`updated`/`skipped`/`removed`, shrinking file orphan elimination, mid-update crash rollback preserving prior version, `remove` single-file deletion, `status` reporting, and `reindex` re-embedding stored chunks under a new model lock)

### Implementation for User Story 4
- [X] T034 [US4] Implement transactional staging, version flip, and crash-recovery debris sweep in `src/docpipe_maestro/ingest/pipeline.py` and `src/docpipe_maestro/store.py` (write updated records under `doc_version=content_hash[:12]`, flip manifest pointer via atomic `os.replace`, purge prior `doc_version != active_version` records, and sweep uncommitted staging debris on Phase 1 startup)
- [X] T035 [US4] Implement directory reconciliation (`sync`) in `src/docpipe_maestro/ingest/pipeline.py` (scan directory against manifest keys: ingest `NEW`, verify `mtime`/`sha256` for `UNCHANGED`, stage re-ingest for `CHANGED`, and delete records for `REMOVED` per FR-010, FR-011)
- [X] T036 [US4] Implement `remove`, `status`, and `reindex` operations in `src/docpipe_maestro/ingest/pipeline.py` (`reindex` re-embeds stored child chunk texts directly from ChromaDB under new `embed_model`, updates parent zero-vector dimensions, updates record metadata, and re-locks manifest)
- [X] T037 [US4] Expose `sync`, `remove`, `status`, and `reindex` in public Python API `src/docpipe_maestro/__init__.py`
- [X] T038 [US4] Implement CLI commands `docpipe-maestro sync <directory>`, `docpipe-maestro status`, `docpipe-maestro remove <source>`, and `docpipe-maestro reindex --model <m>` in `src/docpipe_maestro/cli.py`

**Checkpoint**: All user stories functional. Corpus lifecycle and synchronization complete.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validation across all user stories, CLI configuration purity, static analysis, and end-to-end quickstart execution.

- [X] T039 Implement isolated TOML config file parsing in `src/docpipe_maestro/cli.py` via `--config <path>` (verifying no library module reads config files, enforcing Constitution Principle III)
- [X] T040 [P] Create CLI integration tests in `tests/test_cli.py` (verifying all 7 CLI subcommands, exit codes, `--config` resolution, and stdout/stderr formatting)
- [X] T041 [P] Configure and verify code quality tooling: run `ruff check .`, `ruff format --check .`, and `mypy --strict src tests`
- [X] T042 Run and validate all scenarios from `specs/001-core-rag-pipeline/quickstart.md` (verifying multi-format ingest, reverse safety gate, grounded ask, threshold short-circuit, and incremental sync)

---

## Dependencies & Execution Order

### Phase Dependencies

```text
Phase 1: Setup
    │
    ▼
Phase 2: Foundational (BLOCKS all User Stories)
    │
    ├───────────────────────────────────────────┐
    ▼                                           ▼
Phase 3: User Story 1 (P1 - MVP)        Phase 4: User Story 2 (P1 - Safety Gate)
    │                                           │
    └─────────────────────┬─────────────────────┘
                          ▼
                Phase 5: User Story 3 (P2 - RAG Generation)
                          │
                          ▼
                Phase 6: User Story 4 (P2 - Sync & Maintenance)
                          │
                          ▼
                Phase 7: Polish & Quality Gates
```

### User Story Dependencies

- **User Story 1 (P1)**: Can begin immediately after Phase 2 (Foundational). Delivers the core retrieval engine.
- **User Story 2 (P1)**: Extends US1 chunking with crossrefs and clause preservation; runs the reverse test gate.
- **User Story 3 (P2)**: Depends on US1 retrieval to construct prompts and generate grounded answers.
- **User Story 4 (P2)**: Builds upon US1/US2 ingestion pipelines to add three-way directory sync, staging, and reindexing.
- **Polish (Phase 7)**: Depends on all user story phases being complete.

---

## Parallel Opportunities

### Foundational Phase (Phase 2)
```bash
# Can run concurrently once T005 (types.py) is defined:
T006 (config.py)
T007 (embedder.py)
T008 (manifest.py)
T009 (store.py)
```

### User Story Tests (Write tests first & verify failure)
```bash
# In parallel for US1:
T011 (test docs) + T012 (test_intake_clean.py) + T013 (test_chunker.py) + T014 (test_retriever.py)

# In parallel for US2:
T022 (policy fixtures) + T023 (test_crossrefs.py) + T024 (test_reverse_safety.py)

# In parallel for US3 & US4:
T028 (test_prompts_answer.py)
T033 (test_sync_lifecycle.py)
```

---

## Implementation Strategy & MVP Scope

1. **MVP (Phases 1, 2, 3)**: Setup, foundational state, multi-format intake, structure-aware chunking, vector storage, and `retrieve` / `docpipe-maestro query`. This delivers a fully functional, offline semantic search engine.
2. **Safety Release Gate (Phase 4)**: Implement intra-document crossrefs, clause preservation, and pass 100% of the reverse safety test suite (`tests/test_reverse_safety.py`).
3. **End-to-End RAG (Phase 5)**: Add pure prompt building and local/cloud generation with threshold short-circuiting.
4. **Lifecycle & Sync (Phase 6)**: Add 3-way directory reconciliation, staging/version flip, model locks, and reindexing.
5. **Quality Polish (Phase 7)**: Ruff, Mypy strict, and quickstart end-to-end validation.

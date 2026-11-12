# Research & Technical Decisions: Core RAG Pipeline

**Feature**: `001-core-rag-pipeline` | **Date**: 2026-11-12

This document consolidates the architectural and dependency decisions resolving all Technical Context items for `docpipe-maestro` v0.1.

---

## 1. Build System, Packaging & Toolchain

- **Decision**: Use `hatchling` + `hatch-vcs` with a `src/docpipe_maestro/` layout, PEP 561 `py.typed` marker, MIT license, `requires-python = ">=3.10"`, and PEP 735 `[dependency-groups] dev` (`pytest`, `pytest-cov`, `ruff`, `mypy`).
- **Rationale**: `hatch-vcs` derives package versions directly from Git tags (single source of truth per `Product.md` §14.2), `src/` layout guarantees tests import the installed package rather than stale local directories, and `uv` natively supports PEP 735 dependency groups and `hatchling`.
- **Alternatives Considered**: `setuptools` + `setuptools-scm` (more verbose `MANIFEST.in`/config), `poetry-core` (non-standard lock/metadata quirks compared to PEP 621/735).

---

## 2. Unified Provider Interface & Optional Generation Extra

- **Decision**: Use `litellm` (base SDK package, excluding `[proxy]`) as the unified provider client for `provider/model` resolution in both `embedder.py` (`litellm.embedding`) and `query/answer.py` (`litellm.completion`), with `ollama/nomic-embed-text` as default embedding model and `ollama/llama3.2` (or configurable local 7B-class Ollama model fitting 16 GB RAM) as default generation model.
- **Rationale**: Constitution Principles III and VI forbid maintaining a provider registry in codebase and require zero-code addition of providers via `provider/model` strings and environment variables. `litellm` resolves Ollama (`ollama/...`), OpenAI (`openai/...`), Anthropic (`anthropic/...`), Google Gemini (`gemini/...`), Groq (`groq/...`), Together AI (`together_ai/...`), and OpenAI-compatible `api_base` overrides natively. Omitting `[proxy]` keeps FastAPI/Uvicorn/gateway dependencies out of the install.
- **Handling the `[generation]` Optional Extra**:
  - `litellm` is included in core `dependencies` so provider-agnostic embeddings work in `ingest`, `sync`, `reindex`, and `retrieve` without requiring extras.
  - `pyproject.toml` declares `[project.optional-dependencies] generation = ["litellm>=1.55.0"]` (plus optional provider SDK helpers) and isolates generation logic inside `src/docpipe_maestro/query/answer.py`, lazily loaded from `__init__.py` via `__getattr__` so retrieval-only consumers never load completion machinery.
- **Alternatives Considered**: Writing custom HTTP wrappers for Ollama + OpenAI + Anthropic (rejected: violates Principle III ban on custom provider registries), `aisuite` (rejected: lacks unified embedding support).

---

## 3. Vector Database, Cosine Similarity & Transactional Staging

- **Decision**: Use embedded `chromadb.PersistentClient(path=persist_dir)` with a single collection per logical corpus configured with `metadata={"hnsw:space": "cosine"}`.
- **Rationale**:
  - Cosine space computes `cosine_distance = 1 - cosine_similarity`, allowing clean conversion `score = max(0.0, min(1.0, 1.0 - distance))` onto `[0.0, 1.0]` where higher means more similar (`score >= threshold`), matching the clarified `FR-014` contract.
  - Single-collection design satisfies `Product.md` §16 #5 with explicit `where={"type": "child"}` filtering for search and `collection.get(ids=...)` for parent expansion.
  - **ChromaDB Metadata Constraint**: ChromaDB rejects `None` metadata values. `store.py` omits `None` keys (`clause`, `page`) when writing to Chroma and restores `None` defaults when hydrating `Chunk`/`EmbeddedChunk`/`RetrievedChunk`.
  - **Parent Vector Placeholder**: ChromaDB requires every record to have a vector matching collection dimensionality. Parent records store `[0.0] * embed_dim` and are strictly excluded from vector search via `where={"type": "child"}`.
- **Crash-Safe Delete-Then-Reinsert Protocol**:
  1. Parse, clean, crossref, chunk, and **embed all child chunks in memory first** — parse or API failures leave the store completely untouched.
  2. Assign `doc_version = content_hash[:12]` and deterministic IDs `sha256(f"{source}|{doc_version}|{type}|{section}|{clause}|{chunk_index}|{text}")[:16]`.
  3. Insert new child + parent records into ChromaDB under `doc_version`.
  4. Atomically update the database-collocated manifest JSON (`<persist_dir>/manifests/<collection>.json`) via temp-file + `os.replace`.
  5. Purge all prior versions for that source: `collection.delete(where={"$and": [{"source": {"$eq": source}}, {"doc_version": {"$ne": new_doc_version}}]})`.
  6. Phase 2 `retrieve()` verifies returned records match `manifest.sources[source].doc_version` (ignoring uncommitted staging debris after a hard crash), and Phase 1 sweeps uncommitted debris on startup.
- **Alternatives Considered**: ID-only `collection.upsert` (rejected: leaves orphaned clauses when a document shrinks, violating Constitution Principle V), Qdrant/SQLite-vec (rejected: ChromaDB is locked in `Product.md` §16).

---

## 4. Document Parsing & Per-Format Extras

- **Decision**:
  - Built-in (core, zero external dependencies): Markdown (`.md`, `.markdown`) and plain text (`.txt`).
  - Optional extras with permissive licenses (MIT/BSD-3-Clause, compatible with MIT package license):
    - `pdf = ["pypdf>=4.0.0"]` (pure Python, BSD-3-Clause, extracts per-page text without C build dependencies or AGPL licensing conflicts)
    - `docx = ["python-docx>=1.1.0"]` (MIT, preserves `Heading 1`–`Heading 6` styles and paragraphs/tables)
    - `html = ["beautifulsoup4>=4.12.0"]` (MIT, strips `<script>`/`<style>`/`<nav>`/`<footer>` boilerplate while preserving headings and paragraph structure)
    - `all = ["docpipe-maestro[pdf,docx,html,generation]"]`
- **Format Detection & Failure Handling**: `intake.py` checks extension first and falls back to content/magic-byte inspection (`%PDF-`, ZIP + `word/document.xml`, HTML root/doctype tags, UTF-8 text). Missing optional parser raises `MissingExtraError` with install hint (`pip install docpipe-maestro[pdf]`). Any unsupported or unreadable file in a batch aborts atomically before store mutation (`FR-001`).
- **Alternatives Considered**: `pymupdf` (rejected: AGPL-3.0 license conflict with MIT/Apache-2.0), `unstructured` (rejected: multi-GB dependency footprint violates 16 GB RAM / small core install constraints).

---

## 5. Structure-Aware Chunking & Offline Token Counting

- **Decision**:
  - Combine a deterministic heading/section/clause structural parser (`ingest/chunker.py`) with `langchain-text-splitters` (`RecursiveCharacterTextSplitter`) used solely for paragraph/sentence/character fallback when a non-policy block exceeds budget.
  - **Offline-Safe Token Counting**: Use a deterministic zero-network token estimator (`max(1, round(len(text.split()) * 1.33))` / character-bounded ceiling) by default so first-run offline execution never attempts to download `tiktoken` BPE encoding files from the internet (enforcing Constitution Principle VI zero outbound network calls).
  - **Clause Preservation & Scoped Overlap**: In `POLICY` profile (`chunk_size=1000`, `overlap=80`, `clause_preserving=True`), clauses and their inline/subordinate exception clauses are kept intact inside single child chunks (never split mid-clause even if > 1000 tokens). Overlap applies strictly between consecutive child chunks sharing the same `parent_id` and resets at every section boundary.
- **Alternatives Considered**: Mandatory `tiktoken` BPE download (rejected: breaks air-gapped/offline execution on fresh virtualenvs), blind fixed-token splitting (rejected: splits mid-clause and violates Principles V and VII).

---

## 6. CLI & Configuration Purity

- **Decision**: Build `src/docpipe_maestro/cli.py` with standard library `argparse` and optional TOML config file loading (`tomllib` on Python 3.11+ / `tomli` on Python 3.10 if `--config` is passed).
- **Rationale**: `argparse` adds zero runtime dependencies, keeps CLI startup sub-50ms, and enforces Constitution Principle III (`cli.py` is the only module permitted to read a user config file, passing resolved scalar arguments into the library API).
- **Alternatives Considered**: `typer` / `click` (acceptable, but unnecessary dependency for 7 straightforward subcommands).

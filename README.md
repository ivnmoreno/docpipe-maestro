# docpipe-maestro

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

> **"docpipe-maestro is a minimal RAG pipeline: it ingests any document, chunks it correctly, embeds it, stores it, retrieves the right sections, and optionally generates a grounded answer. It is the engine — not the app, not the framework."**

`docpipe-maestro` is a provider-agnostic, structure-aware Python RAG (Retrieval-Augmented Generation) pipeline library and CLI. It is built to solve the hardest data-preparation and retrieval problems in RAG systems: preserving document hierarchy, preventing clause cutting, resolving internal cross-references, and guaranteeing that policy exceptions travel with their rules.

---

## Table of Contents

- [Key Architecture & Core Concepts](#key-architecture--core-concepts)
- [Installation Guide](#installation-guide)
  - [Core Install](#core-install)
  - [Optional Extras](#optional-extras)
  - [Development Setup](#development-setup)
- [Configuration Guide](#configuration-guide)
  - [1. Local Execution (Default: Zero Cloud Accounts Required)](#1-local-execution-default-zero-cloud-accounts-required)
  - [2. Cloud Provider API Keys](#2-cloud-provider-api-keys)
  - [3. Local Persistence Storage Directory](#3-local-persistence-storage-directory)
  - [4. CLI Configuration File (`docpipe.toml`)](#4-cli-configuration-file-docpipetoml)
  - [5. Chunking Profiles (`DEFAULT` vs `POLICY`)](#5-chunking-profiles-default-vs-policy)
- [Quickstart: CLI Usage Guide](#quickstart-cli-usage-guide)
  - [1. Ingest Documents (`docpipe ingest`)](#1-ingest-documents-docpipe-ingest)
  - [2. Keep Collections in Sync (`docpipe sync`)](#2-keep-collections-in-sync-docpipe-sync)
  - [3. Inspect Collection Status (`docpipe status`)](#3-inspect-collection-status-docpipe-status)
  - [4. Remove a Source Document (`docpipe remove`)](#4-remove-a-source-document-docpipe-remove)
  - [5. Migrate Embedding Models (`docpipe reindex`)](#5-migrate-embedding-models-docpipe-reindex)
  - [6. Semantic Search Without an LLM (`docpipe query`)](#6-semantic-search-without-an-llm-docpipe-query)
  - [7. Grounded Question Answering (`docpipe ask`)](#7-grounded-question-answering-docpipe-ask)
- [Python Library API Guide](#python-library-api-guide)
  - [Phase 1: Ingestion & Lifecycle Workflow](#phase-1-ingestion--lifecycle-workflow)
  - [Phase 2: Semantic Retrieval & Grounded RAG Workflow](#phase-2-semantic-retrieval--grounded-rag-workflow)
  - [Core Data Shapes](#core-data-shapes)
- [Safety & Verification](#safety--verification)
- [Documentation](#documentation)
- [License](#license)

---

## Key Architecture & Core Concepts

1. **Two-Phase Separation**:
   - **Phase 1 (Offline Ingestion)**: Files $\to$ Parse $\to$ Clean $\to$ Cross-Reference Resolution $\to$ Structure-Aware Chunking $\to$ Embeddings $\to$ Vector Database. Correctness and crash safety matter.
   - **Phase 2 (Online Query)**: Question $\to$ Embed $\to$ Retrieve (Match Children, Return Deduplicated Parents) $\to$ Build Prompt $\to$ Optional Grounded LLM Generation. Read-only and low-latency.
2. **Search Small, Return Big (Parent-Child Retrieval)**:
   - Small **child chunks** (individual clauses/paragraphs) are embedded and searched for high precision.
   - Large **parent sections** (complete contextual sections) are stored and returned to the prompt.
3. **Exception Preservation & Reverse Safety Gate**:
   - In policy and legal documents, a rule without its exception is actively misleading (e.g., *"Employees receive 20 days leave"* without *"unless probationary"*). In `POLICY` profile, clauses are kept intact and parent sections ensure exceptions always accompany their rules.
4. **Crash-Safe Transactional Synchronization**:
   - Ingestion maintains an atomic database-collocated manifest (`.docpipe/manifests/<collection>.json`) tracking `sha256` content hashes, `mtime`, and document versions.
   - Modifying a document performs a staged delete-then-reinsert, preventing orphaned clauses when documents shrink.
5. **Embedding Model Lock**:
   - The manifest locks the collection to the embedding model used during ingestion. Attempting to query with a different model raises an immediate error rather than returning corrupt similarity scores. Model migration is handled cleanly via `reindex`.

---

## Installation Guide

`docpipe-maestro` requires **Python 3.10+**.

### Core Install

The core installation includes Markdown (`.md`) and plain text (`.txt`) parsing, embedding generation, ChromaDB vector storage, and semantic retrieval:

```bash
pip install docpipe-maestro
```

### Optional Extras

Install additional document format parsers or cloud LLM generation features as needed:

| Extra | Purpose | Dependencies Installed |
|---|---|---|
| `pdf` | Extract text, page numbers, and heuristic section headings (`Section X.Y`) from PDF files | `pypdf>=4.0.0` (BSD-3-Clause) |
| `docx` | Extract text, style-based headings (`Heading 1`–`Heading 6`), and tables from Word documents | `python-docx>=1.1.0` |
| `html` | Strip boilerplate and parse `<h1–h6>` headings from web pages / HTML exports | `beautifulsoup4>=4.12.0` |
| `generation` | Semantic alias for grounded question answering (`litellm` is already installed in core) | `litellm>=1.55.0` |
| `all` | Installs **all** optional format parsers (`pdf`, `docx`, `html`, `generation`) | `pypdf`, `python-docx`, `beautifulsoup4`, `litellm` |

> **Note on Structure Extraction & Optional Generation**:
> - **Structure-awareness across formats**: Markdown (`.md`, `.markdown`), plain text (`.txt`), HTML (`.html`, `.htm`), DOCX (`.docx`), and PDF (`.pdf`) are supported, with content/magic-byte fallback for extensionless files (`%PDF-`, ZIP `word/document.xml`, HTML root tags, Markdown headings, and UTF-8 text).
> - **Fenced blocks & tables**: Markdown preserves `#` comments inside code fences (` ``` ` / `~~~`); HTML and DOCX preserve tables as pipe-delimited rows (` | `); PDFs extract per-page heuristic headings and 1-based page numbers.
> - **Generation capability**: Because `litellm` powers both embeddings and completions, `answer()` is available in the base install; the `[generation]` extra is retained as a backwards-compatible alias.

Install specific extras:
```bash
# PDF support only
pip install "docpipe-maestro[pdf]"

# PDF and DOCX support
pip install "docpipe-maestro[pdf,docx]"

# Full installation with all formats and generation
pip install "docpipe-maestro[all]"
```

### Development Setup

To contribute or run tests locally (uses PEP 735 `[dependency-groups]`):

```bash
# Clone the repository
git clone https://github.com/ivnmoreno/docpipe-maestro.git
cd docpipe-maestro

# Option A: Using uv (recommended)
uv sync --all-extras --group dev

# Option B: Using pip 24.1+ (PEP 735 dependency groups)
pip install --group dev -e ".[all]"
pre-commit install --hook-type commit-msg
```

> **Note on Versioning & Commitizen**: Package versions are derived dynamically from Git tags via `hatch-vcs`. Use `cz check` (to validate Conventional Commits) and `cz changelog` (to update `CHANGELOG.md`), rather than `cz bump`.

---

## Configuration Guide

`docpipe-maestro` follows strict architectural rules: **no library module reads configuration files**. Configuration is passed via function arguments or environment variables. The `docpipe` CLI is the only component that can optionally read a `--config` TOML file.

### 1. Local Execution (Default: Zero Cloud Accounts Required)

Out of the box, `docpipe-maestro` defaults to local execution with [Ollama](https://ollama.com/):
- **Default Embeddings Model**: `ollama/nomic-embed-text`
- **Default Generation Model**: `ollama/llama3.2`

Make sure Ollama is installed and running, then pull the default models:

```bash
ollama pull nomic-embed-text
ollama pull llama3.2
```

When run locally, `docpipe-maestro` makes **zero outbound network calls**.

### 2. Cloud Provider API Keys

To use cloud embedding or generation models, set the standard environment variables required by LiteLLM:

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic (Claude)
export ANTHROPIC_API_KEY="sk-ant-..."

# Google Gemini
export GEMINI_API_KEY="..."

# Groq
export GROQ_API_KEY="gsk_..."

# Together AI
export TOGETHERAI_API_KEY="..."
```

You can then pass any model string directly to `--embed-model` or `--model`, e.g., `openai/text-embedding-3-small`, `openai/gpt-4o-mini`, `gemini/gemini-1.5-flash`, `anthropic/claude-3-5-haiku-20241022`.

### 3. Local Persistence Storage Directory

By default, data is stored in the relative directory `./.docpipe`:
```text
.docpipe/
├── chroma.sqlite3          # ChromaDB embedded vector database
├── <uuid>/                 # ChromaDB vector segments and HNSW index files
└── manifests/
    └── <collection>.json   # Atomic JSON manifest tracking file hashes, versions, and locked model
```
You can customize the persistence directory using the `--persist-dir` CLI flag or the `persist_dir` argument in the Python API.

### 4. CLI Configuration File (`docpipe.toml`)

You can create an optional TOML configuration file to store default CLI options (never store secrets/API keys here):

```toml
# docpipe.toml
collection = "my_kb"
persist_dir = "./data/docpipe_index"
embed_model = "ollama/nomic-embed-text"
model = "ollama/llama3.2"
profile = "POLICY"
top_k = 5
threshold = 0.4
```

Pass it to any CLI command using `--config`:
```bash
docpipe query "What is the probation period?" --config docpipe.toml
```

### 5. Chunking Profiles (`DEFAULT` vs `POLICY`)

Profiles are immutable presets calibrated for specific document types:

| Parameter | `DEFAULT` Profile | `POLICY` Profile |
|---|---|---|
| **Intended For** | Notes, general prose, articles, documentation | Handbooks, compliance policies, HR manuals, contracts |
| **Target Chunk Size** | ~512 tokens | ~1000 tokens |
| **Chunk Overlap** | ~64 tokens (scoped within section) | ~80 tokens (scoped within section) |
| **Clause Preservation** | Disabled (splits on sentences/paragraphs) | **Enabled** (never splits inside numbered clauses) |
| **Cross-Reference Resolution** | Disabled | **Enabled** (resolves `§2.1`, `Section 4`, etc.) |
| **Parent-Child Expansion** | Enabled | **Enabled** |

---

## Quickstart: CLI Usage Guide

Run `docpipe --help` to see all available subcommands (global flags `--config`, `--collection`, and `--persist-dir` work either before or after any subcommand):

```text
usage: docpipe [-h] [--version] [--config CONFIG] [--collection COLLECTION]
               [--persist-dir PERSIST_DIR]
               {ingest,sync,status,remove,reindex,query,ask} ...
```

See the full [CLI Reference](docs/cli-reference.md) for all flags, TOML keys, exit codes, and output schemas.

### 1. Ingest Documents (`docpipe ingest`)

Ingest a single file or an entire directory of documents:

```bash
# Ingest with default profile
docpipe ingest ./docs --collection knowledge_base

# Ingest policy documents with clause-preservation and cross-reference resolution
docpipe ingest ./company_policies --profile POLICY --collection hr_policy

# Force re-ingestion even if files have not changed on disk
docpipe ingest ./docs --force --collection knowledge_base
```

### 2. Keep Collections in Sync (`docpipe sync`)

Reconciles a target directory with the database manifest (adds new files, updates modified files, and removes deleted files):

```bash
docpipe sync ./company_policies --profile POLICY --collection hr_policy
```
**Example output**:
```text
Synced 'hr_policy': added=1, updated=2, skipped=10, removed=1.
```

### 3. Inspect Collection Status (`docpipe status`)

View indexed files, version hashes, chunk counts, and locked embedding model:

```bash
docpipe status --collection hr_policy
```
**Example output**:
```text
Collection: hr_policy | Model: ollama/nomic-embed-text (dim=768) | Sources: 2 | Children: 18 | Parents: 6
  - hr_leave_policy.md [4f1a29b01c3d] (10 children, 3 parents)
  - travel_expenses_policy.md [a8c2194ef001] (8 children, 3 parents)
```

Use `--json` for machine-readable output:
```bash
docpipe status --collection hr_policy --json
```

### 4. Remove a Source Document (`docpipe remove`)

Purge all child chunks, parent sections, and manifest entries for a specific file:

```bash
docpipe remove hr_leave_policy.md --collection hr_policy
```

### 5. Migrate Embedding Models (`docpipe reindex`)

Re-embeds all existing child chunks stored in the database under a new embedding model, updates vector embeddings, and re-locks the collection:

```bash
# Migrate collection to OpenAI embeddings
export OPENAI_API_KEY="sk-..."
docpipe reindex --model openai/text-embedding-3-small --collection hr_policy
```

### 6. Semantic Search Without an LLM (`docpipe query`)

Perform Phase 2 semantic retrieval to get relevant context passages without invoking a language model:

```bash
# Basic semantic query
docpipe query "How many vacation days do full-time employees accrue?" --collection hr_policy

# Restrict to top 3 sections with a minimum similarity threshold (0.0 to 1.0)
docpipe query "What is the flight reimbursement policy?" --top-k 3 --threshold 0.5 --collection hr_policy

# Return raw child chunks instead of expanded parent sections
docpipe query "annual leave" --no-expand-parent --collection hr_policy
```

**Example output**:
```text
[1] score=0.8421 | Source: hr_leave_policy.md | Section: 3. Annual Leave
3.1 Full-time employees accrue 20 days of paid annual leave per calendar year.
3.2 Employees with less than one year of tenure accrue leave on a pro-rata basis.
------------------------------------------------------------
```

### 7. Grounded Question Answering (`docpipe ask`)

Retrieve relevant context and generate a grounded answer:

```bash
# Using local Ollama (default)
docpipe ask "How many days of leave does a first-year employee get?" --collection hr_policy

# Using a cloud model or custom OpenAI-compatible base URL
export OPENAI_API_KEY="sk-..."
docpipe ask "Summarize travel meal allowance limits." --model openai/gpt-4o-mini --collection hr_policy
docpipe ask "Summarize travel policy." --model openai/my-local-model --api-base http://localhost:8000/v1 --collection hr_policy

# Safe thresholding: if no retrieved content matches threshold, short-circuits with a refusal
docpipe ask "What is the recipe for lasagna?" --threshold 0.7 --collection hr_policy
```

---

## Python Library API Guide

See the complete [Python API Reference](docs/api-reference.md) for every signature, parameter default, config constant, and exception class.

### Phase 1: Ingestion & Lifecycle Workflow

```python
from pathlib import Path
from docpipe_maestro import ingest, sync, status, remove, reindex

# 1. Ingest a document or directory
result = ingest(
    Path("./policies"),
    profile="POLICY",  # "DEFAULT", "POLICY", or custom ChunkingProfile
    collection="handbook",
    persist_dir=".docpipe",
    embed_model="ollama/nomic-embed-text",
)
print(
    f"Ingested {len(result.ingested)} files "
    f"({result.chunks_written} children, {result.parents_written} parents)."
)

# 2. Synchronize folder after changes (adds, edits, deletions)
sync_result = sync(
    Path("./policies"),
    profile="POLICY",
    collection="handbook",
)
print(
    f"Added: {len(sync_result.added)}, Updated: {len(sync_result.updated)}, "
    f"Skipped: {len(sync_result.skipped)}, Removed: {len(sync_result.removed)}"
)

# 3. Check collection metadata and tracked documents
coll_status = status(collection="handbook")
print(
    f"Locked embed model: {coll_status.embed_model}, "
    f"Tracked files: {coll_status.total_sources}, "
    f"Children: {coll_status.total_children}"
)

# 4. Remove a document from the index
removed = remove("outdated_policy.md", collection="handbook")

# 5. Reindex collection with a new embedding model
reindexed_count = reindex(
    embed_model="openai/text-embedding-3-small",
    collection="handbook",
)
```

### Phase 2: Semantic Retrieval & Grounded RAG Workflow

```python
from docpipe_maestro import retrieve, build_prompt, answer

question = "What is the travel meal reimbursement rate?"

# 1. Retrieve deduplicated parent sections
retrieved_sections = retrieve(
    question=question,
    collection="handbook",
    top_k=5,
    threshold=0.35,  # Normalized cosine similarity [0.0, 1.0]
    expand_parent=True,  # Expand child matches to full parent section
)

for section in retrieved_sections:
    print(f"[{section.score:.2f}] {section.metadata['source']} - {section.metadata['section']}")
    print(section.text)

# 2. Build a grounded prompt (Pure function, zero network calls)
prompt = build_prompt(question=question, sections=retrieved_sections)

# 3. Generate a grounded answer (uses local Ollama by default)
response = answer(
    prompt=prompt,
    model="ollama/llama3.2",  # or "openai/gpt-4o-mini", "anthropic/claude-3-5-haiku", etc.
    has_context=bool(retrieved_sections),  # Short-circuits with refusal if context is empty
)
print("Answer:\n", response)
```

### Core Data Shapes & Exceptions

Exported from `docpipe_maestro` (`docpipe_maestro.types`):

- `Chunk`: Base unit (`id`, `text`, `parent_id`, `metadata: ChunkMetadata`).
- `EmbeddedChunk`: `Chunk` with dense embedding (`vector: list[float]`).
- `RetrievedChunk`: `EmbeddedChunk` with normalized cosine similarity (`score: float` in `[0.0, 1.0]`).
- `IngestResult`: Summary (`collection`, `embed_model`, `ingested`, `skipped`, `chunks_written`, `parents_written`).
- `SyncResult`: Summary (`collection`, `embed_model`, `added`, `updated`, `skipped`, `removed`).
- `CollectionStatus`: Manifest overview (`collection`, `embed_model`, `embed_dim`, `total_sources`, `total_children`, `total_parents`, `sources`).
- `SourceRecord`: Per-file manifest tracking record (`source`, `content_hash`, `doc_version`, `size`, `mtime`, `ingested_at`, `embed_model`, `profile`, `chunk_ids`, `parent_ids`).
- Exceptions: `DocpipeError` (base) with `UnsupportedFormatError`, `MissingExtraError`, `ModelMismatchError`, and `MissingCredentialError`.

---

## Safety & Verification

`docpipe-maestro` includes a mandatory **Reverse Safety Test Gate** (`tests/test_reverse_safety.py`). It enforces that every clause containing an exception marker (`except`, `unless`, `not entitled`, `subject to`, `provided that`) always retrieves a parent context that contains the exception text alongside the general rule.

Run the test suite and quality gates:

```bash
# Run linters and formatting checks
uv run ruff check .
uv run ruff format --check .

# Run static type checking
uv run mypy src tests

# Run all unit, integration, and safety tests with branch coverage
uv run pytest -v --cov

# Verify reverse safety gate and extended complex integration tests individually
uv run pytest -m reverse -v
uv run pytest -m integration -v
```

---

## Documentation

- **[Documentation Index](docs/README.md)** — Full guide overview
- **[Architecture & Internals](docs/architecture.md)** — Two-phase pipeline flow, intake, crossref resolution, chunking, and transactional staging
- **[Python API Reference](docs/api-reference.md)** — Signatures, profiles, data shapes, and error handling
- **[CLI Reference](docs/cli-reference.md)** — `docpipe` commands, TOML config, outputs, and troubleshooting
- **[Development & Testing Guide](docs/development.md)** — Setup, quality gates, offline test doubles, and Ollama live runs
- **[Future Features Backlog](docs/future-features.md)** — Post-v0.1 roadmap
- **[Changelog](CHANGELOG.md)** — Release history

---

## License

This project is licensed under the [MIT License](LICENSE).

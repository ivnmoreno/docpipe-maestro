# Command-Line Interface Contract (`docpipe-maestro`)

**Entry Point**: `docpipe-maestro` (`docpipe_maestro.cli:main`; also invocable via `python -m docpipe_maestro`)

Per Constitution Principle III, `cli.py` is the **only** module permitted to read a user configuration file (e.g., via `--config <path>` TOML file). All library calls receive explicit arguments.

---

## Global Options

| Flag | Default | Description |
|---|---|---|
| `--collection <name>` | `"default"` | Target ChromaDB collection name |
| `--persist-dir <path>` | `".docpipe"` | Local persistence directory for ChromaDB and manifests |
| `--config <path>` | `None` | Optional TOML config file (parsed solely in `cli.py`; never stores credentials) |
| `--version` | — | Print `docpipe-maestro` version and exit |

---

## Phase 1 Commands (Offline Ingestion & Lifecycle)

### 1. `docpipe-maestro ingest <path>`
Ingest a file or directory into the collection.
- **Arguments**: `path` (file or directory)
- **Options**:
  - `--profile {DEFAULT,POLICY}` (default: `"DEFAULT"`)
  - `--embed-model <provider/model>` (default: `"ollama/nomic-embed-text"`)
  - `--force` (re-ingest even if `sha256` hash matches manifest)
- **Exit codes**: `0` on success; non-zero on unsupported/corrupted file (atomic abort), `ModelMismatchError`, or `MissingExtraError`.

### 2. `docpipe-maestro sync <directory>`
Three-way reconcile `<directory>` against the collection manifest (add new, skip unchanged, replace changed, delete removed).
- **Arguments**: `directory`
- **Options**:
  - `--profile {DEFAULT,POLICY}` (default: `"DEFAULT"`)
  - `--embed-model <provider/model>` (default: `"ollama/nomic-embed-text"`)
- **Output**: Summary of `added`, `updated`, `skipped`, and `removed` counts.

### 3. `docpipe-maestro status`
Inspect manifest state for the collection (locked `embed_model`, vector dimension, tracked files, `sha256` prefixes, timestamps, chunk/parent counts).
- **Options**: `--json` (optional machine-readable output)

### 4. `docpipe-maestro remove <source>`
Delete all records and manifest entry for `<source>` from the collection.
- **Exit codes**: `0` if removed; `1` if source not tracked in manifest.

### 5. `docpipe-maestro reindex --model <provider/model>`
Re-embed all existing stored child chunks under a new embedding model and update the manifest lock.
- **Options**: `--model <provider/model>` (required)

---

## Phase 2 Commands (Online Retrieval & Optional RAG)

### 6. `docpipe-maestro query "<question>"`
Run Phase 2 semantic retrieval without calling an LLM.
- **Arguments**: `question`
- **Options**:
  - `--top-k <int>` (default: `5`)
  - `--threshold <float>` (default: `None`, cosine similarity `[0.0, 1.0]`)
  - `--expand-parent` / `--no-expand-parent` (default: `--expand-parent`)
  - `--embed-model <provider/model>` (default: `"ollama/nomic-embed-text"`)
- **Output**: Ranked retrieved sections with `score`, `source`, `section`, `clause`, `page`, and full text.

### 7. `docpipe-maestro ask "<question>"`
Run full Phase 2 RAG (retrieve → build_prompt → generate answer, or short-circuit if empty retrieval).
- **Arguments**: `question`
- **Options**:
  - `--top-k <int>` (default: `5`)
  - `--threshold <float>` (default: `None`)
  - `--model <provider/model>` (default: `"ollama/llama3.2"`)
  - `--embed-model <provider/model>` (default: `"ollama/nomic-embed-text"`)
  - `--api-base <url>` (optional OpenAI-compatible base URL override)
- **Output**: Grounded answer with source attribution references (or deterministic refusal if 0 sections retrieved).

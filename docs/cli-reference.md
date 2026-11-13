# CLI Reference (`docpipe`)

The `docpipe` CLI (`docpipe_maestro.cli:main`) provides subcommands mirroring the two-phase pipeline. It is the **only** component in `docpipe-maestro` permitted to read an optional user configuration file (`--config`).

---

## 1. Global Options & Flag Placement

```text
usage: docpipe [-h] [--version] [--config CONFIG] [--collection COLLECTION]
               [--persist-dir PERSIST_DIR]
               {ingest,sync,status,remove,reindex,query,ask} ...
```

| Flag | Default | Description |
|---|---|---|
| `--config <path>` | `None` | Optional TOML file providing CLI defaults |
| `--collection <name>` | `"default"` | Target ChromaDB collection & manifest identifier (ChromaDB requires $\ge 3$ characters matching `[a-zA-Z0-9._-]`) |
| `--persist-dir <path>` | `".docpipe"` | Directory storing `chroma.sqlite3` and `manifests/<collection>.json` |
| `--version` | — | Print `docpipe-maestro <version>` and exit |

All global options (`--config`, `--collection`, `--persist-dir`) are attached via a shared parent parser so they work identically **before or after** any subcommand:

```bash
docpipe --collection hr status --json
docpipe status --json --collection hr
```

---

## 2. Optional TOML Configuration (`--config`)

Supported keys in `docpipe.toml` correspond 1-to-1 with CLI option names in `src/docpipe_maestro/cli.py`:

```toml
collection = "hr_policy"
persist_dir = "./.docpipe"
embed_model = "ollama/nomic-embed-text"
model = "ollama/llama3.2"          # Generation model for `docpipe ask`
profile = "POLICY"                 # "DEFAULT" or "POLICY"
top_k = 5                          # Default candidate child count
threshold = 0.35                   # Optional cosine similarity floor [0.0, 1.0]
```

**Precedence order**: Explicit CLI flags > `--config` TOML values > Built-in `config.py` defaults.

> **Security Rule**: Never place API keys or secrets in `docpipe.toml`. Set provider credentials solely through environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, etc.).

---

## 3. Phase 1 Subcommands (Offline Ingestion & Lifecycle)

### `docpipe ingest <path>`

Ingest a single file or recursively scan a directory atomically.

```text
docpipe ingest [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR]
               [--profile PROFILE] [--embed-model EMBED_MODEL] [--force] path
```

- `--profile`: `"DEFAULT"` or `"POLICY"` (case-insensitive; default: `"DEFAULT"` or TOML `profile`).
- `--embed-model`: Provider/model string (default: `"ollama/nomic-embed-text"`).
- `--force`: Re-parse, re-chunk, and re-embed even when `mtime`, `size`, and `sha256` are unchanged.
- **Example output**:
  ```text
  Ingested 3 file(s), skipped 0 unchanged (42 children, 18 parents) into collection 'hr_policy'.
  ```

---

### `docpipe sync <directory>`

Three-way reconcile `<directory>` against the stored manifest (adds new files, skips unchanged files, replaces changed files via staged delete-then-reinsert, deletes missing files).

```text
docpipe sync [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR]
             [--profile PROFILE] [--embed-model EMBED_MODEL] directory
```

- **Example output**:
  ```text
  Synced 'hr_policy': added=1, updated=1, skipped=5, removed=1.
  ```

---

### `docpipe status`

Inspect the collection manifest without reading source documents or calling an embedding provider.

```text
docpipe status [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR] [--json]
```

- **Example text output**:
  ```text
  Collection: hr_policy | Model: ollama/nomic-embed-text (dim=768) | Sources: 2 | Children: 18 | Parents: 6
    - hr_leave_policy.md [4f1a29b01c3d] (10 children, 3 parents)
    - travel_expenses_policy.md [a8c2194ef001] (8 children, 3 parents)
  ```
- **Example `--json` schema**:
  ```json
  {
    "collection": "hr_policy",
    "embed_model": "ollama/nomic-embed-text",
    "embed_dim": 768,
    "total_sources": 2,
    "total_children": 18,
    "total_parents": 6,
    "sources": [
      {
        "source": "hr_leave_policy.md",
        "content_hash": "sha256:...",
        "doc_version": "4f1a29b01c3d",
        "size": 1842,
        "mtime": 1762980000.0,
        "ingested_at": "2026-11-12T20:00:00+00:00",
        "embed_model": "ollama/nomic-embed-text",
        "profile": "POLICY",
        "chunk_ids": ["..."],
        "parent_ids": ["..."]
      }
    ]
  }
  ```

---

### `docpipe remove <source>`

Delete all child chunks, parent sections, and manifest tracking for a single source key.

```text
docpipe remove [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR] source
```

- Uses the relative POSIX key shown by `docpipe status` (e.g., `guides/setup.md` or `policy.md`).
- **Exit code**: `0` when removed (`Removed 'guides/setup.md' from collection 'hr_policy'.`); `1` if not found in manifest (`Source not found in collection 'hr_policy': guides/setup.md`).

---

### `docpipe reindex --model <provider/model>`

Re-embed all existing child chunks stored in ChromaDB under a new embedding model, update parent zero-vector dimensions, rebuild the vector index cleanly, and re-lock the manifest.

```text
docpipe reindex [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR] --model MODEL
```

- **Note**: `reindex` uses `--model` (required) rather than `--embed-model`.
- **Example output**:
  ```text
  Reindexed 42 child chunk(s) in collection 'hr_policy' with model 'openai/text-embedding-3-small'.
  ```

---

## 4. Phase 2 Subcommands (Online Read-Only Retrieval & QA)

### `docpipe query "<question>"`

Run semantic search without invoking an LLM.

```text
docpipe query [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR]
              [--top-k TOP_K] [--threshold THRESHOLD] [--embed-model EMBED_MODEL]
              [--expand-parent | --no-expand-parent] question
```

- `--top-k`: Maximum child chunk hits prior to parent deduplication (default: `5`).
- `--threshold`: Minimum cosine similarity in `[0.0, 1.0]` (default: `None`).
- `--embed-model`: Embedding model string matching the collection lock (default: `"ollama/nomic-embed-text"`).
- `--expand-parent` / `--no-expand-parent`: Return deduplicated parent sections (`True`, default) or raw matched child chunks (`False`).
- **Example output**:
  ```text
  [1] score=0.8421 | Source: hr_leave_policy.md | Section: 3. Annual Leave | Page: 2
  3.1 Full-time employees accrue 20 days of paid annual leave per calendar year.
  3.2 Employees with less than 90 days of tenure are ineligible except with written waiver.
  ------------------------------------------------------------
  ```
  (The ` | Page: <n>` suffix appears only for paginated formats such as PDF; when no results pass `--threshold`, prints `No matching sections found.` and exits `0`.)

---

### `docpipe ask "<question>"`

Retrieve deduplicated parent sections, construct a grounded prompt via `build_prompt()`, and generate an answer via `answer()`.

```text
docpipe ask [--config CONFIG] [--collection COLLECTION] [--persist-dir PERSIST_DIR]
            [--top-k TOP_K] [--threshold THRESHOLD] [--model MODEL]
            [--embed-model EMBED_MODEL] [--api-base API_BASE] question
```

- `--top-k`, `--threshold`, `--embed-model`: Same semantics as `docpipe query` (`expand_parent` is always `True`).
- `--model`: LLM generation model string (default: `"ollama/llama3.2"` or TOML `model`).
- `--api-base`: Optional custom OpenAI-compatible server base URL (e.g., `http://localhost:8000/v1`).
- If zero sections satisfy `--threshold` (or the collection is empty), prints `Not found in the provided context.` without invoking the LLM.

---

## 5. Exit Codes & Troubleshooting

| Condition | Exit Code | Output Channel & Message |
|---|---|---|
| Success (`remove` absent excluded) | `0` | Normal output on `stdout` |
| `docpipe remove` source missing | `1` | `Source not found in collection '<name>': <source>` on `stdout` |
| Missing/unknown CLI arguments | `2` | Standard `argparse` usage error on `stderr` |
| Any `DocpipeError` or `ValueError` | `1` | Single-line `Error: <message>` on `stderr` (never prints stack traces or API keys) |

Common runtime fixes:
- **`ModelMismatchError`**: Your `--embed-model` differs from the locked model shown by `docpipe status`. Query with the locked model or migrate via `docpipe reindex --model <new_model>`.
- **`MissingExtraError`**: Install the missing format parser extra: `pip install "docpipe-maestro[pdf]"` (or `docx`, `html`, `all`).
- **`Invalid or unusable collection`**: ChromaDB collection names must be at least 3 characters long and contain only `[a-zA-Z0-9._-]`.
- **`Error: Config file not found`**: Check the relative or absolute path passed to `--config`.

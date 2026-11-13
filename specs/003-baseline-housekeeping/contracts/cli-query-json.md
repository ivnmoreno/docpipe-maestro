# CLI Contract Extension: `docpipe-maestro query --json`

**Feature**: `003-baseline-housekeeping` | **Entry Point**: `docpipe-maestro` (`docpipe_maestro.cli:main`)

This contract extends the existing Phase 2 retrieval subcommand (`docpipe-maestro query`) with structured JSON output (`--json`), preserving full backward compatibility for default human-readable output and matching the envelope conventions of `status --json` and `ask --json`.

---

## 1. Command Signature & Options

```text
docpipe-maestro query [--config CONFIG] [--no-config] [--collection COLLECTION]
                      [--persist-dir PERSIST_DIR] [--top-k TOP_K]
                      [--threshold THRESHOLD] [--embed-model EMBED_MODEL]
                      [--expand-parent | --no-expand-parent] [--json] question
```

| Flag | Type | Default | Action | Description |
|---|---|---|---|---|
| `--json` | `bool` | `False` | `store_true` (`dest="as_json"`) | Emit structured JSON envelope on `stdout` instead of human-formatted text |

- **Global Flag Placement**: Works identically whether global options (`--config`, `--no-config`, `--collection`, `--persist-dir`) appear before `query` or after `query`.
- **TOML Defaults**: Existing `docpipe.toml` keys (`collection`, `persist_dir`, `embed_model`, `top_k`, `threshold`) apply identically before `retrieve(...)`. `--json` is an explicit per-invocation CLI output switch (not stored in TOML).

---

## 2. Output Channel & Payload Contract

### Case A — Success with Matches (`--json`, exit `0`)

`stdout` receives pretty-printed JSON (`indent=2`); `stderr` is empty.

```json
{
  "query": "How many annual leave days do employees accrue?",
  "collection": "hr_policy",
  "expand_parent": true,
  "results": [
    {
      "id": "a1b2c3d4e5f60718",
      "parent_id": null,
      "score": 0.8421374912,
      "text": "3.1 Full-time employees accrue 20 days of paid annual leave per calendar year.",
      "metadata": {
        "type": "parent",
        "source": "hr_leave_policy.md",
        "doc_version": "4f1a29b01c3d",
        "section": "3. Annual Leave",
        "clause": null,
        "page": null,
        "chunk_index": 0,
        "embed_model": "ollama/nomic-embed-text"
      }
    }
  ]
}
```

### Case B — Raw Child Chunk Mode (`--no-expand-parent --json`, exit `0`)

- Top-level `"expand_parent"` is `false`.
- Each item in `"results"` has `"parent_id"` populated with its parent section's 16-char hex ID (non-null string) and `"metadata.type": "child"`.
- `"metadata.clause"` is string (when detected) or `null`; `"metadata.page"` is 1-based integer (PDF) or `null` (Markdown/TXT/DOCX/HTML).

### Case C — Zero Matches (`--json`, exit `0`)

When the collection is empty or `--threshold` eliminates every candidate:

```json
{
  "query": "nonexistent clause",
  "collection": "hr_policy",
  "expand_parent": true,
  "results": []
}
```

- `stdout` contains ONLY valid JSON (never `"No matching sections found."`).
- Exit status is `0`.

### Case D — Validation or Runtime Failure (`--json`, exit `1`)

When `retrieve(...)` raises `DocpipeError`, `ValueError` (e.g., invalid `--threshold` outside `[0.0, 1.0]`, invalid collection name), or `TypeError` (e.g., invalid TOML config):

- `stdout` is completely empty (no malformed or partial JSON).
- `stderr` contains single-line `Error: <message>`.
- Exit status is `1` (identical to `status --json` and `ask --json`).

### Case E — Default Text Mode (`--json` omitted)

- Exact existing stdout formatting preserved (`[1] score=...` lines + 60-dash separator, or `No matching sections found.` on empty results).

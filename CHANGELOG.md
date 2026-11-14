## Unreleased

### Feat

- **searcher**: add hybrid SQLite FTS5 BM25 + dense vector RRF search (`--searcher fts5_hybrid`) and collocated `LexicalIndex` lifecycle sync
- **pipeline**: implement v0.1 core RAG pipeline, CLI, and quality gates

### Fix

- **security**: harden pipeline, add CI workflow, and update gitignore

### Refactor

- **pipeline**: introduce Strategy + Registry extension architecture (`register_*` entry points)
- **cli**: rename CLI command to docpipe-maestro

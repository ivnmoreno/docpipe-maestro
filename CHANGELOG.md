# Changelog

All notable changes to `docpipe-maestro` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
and [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

## [Unreleased]

### Added
- Phase 1 offline ingestion pipeline (`ingest`, `sync`, `remove`, `status`, `reindex`) with multi-format support (Markdown, TXT, HTML, DOCX, PDF).
- Structure-aware chunking (`DEFAULT` and `POLICY` profiles) with clause preservation, scoped overlap, and intra-document cross-reference resolution.
- Database-collocated atomic manifest (`sha256` content hashing, `mtime` fast-path, staged `doc_version` delete-then-reinsert updates, and collection `embed_model` lock).
- Phase 2 online retrieval and optional RAG (`retrieve`, `build_prompt`, `answer`) with parent-child expansion (`where={"type": "child"}`) and deterministic empty-context refusal.
- `docpipe` CLI supporting `ingest`, `sync`, `status`, `remove`, `reindex`, `query`, and `ask` subcommands plus `--config` TOML loading.
- Mandatory Reverse Safety Test Gate (`tests/test_reverse_safety.py`) enforcing 100% exception-clause preservation.

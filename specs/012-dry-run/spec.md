# Feature Specification: Dry-Run Preview Mode for `sync` and `reindex`

**Feature Branch**: `feat/012-dry-run`  
**Created**: 2026-11-17  
**Status**: Draft  
**Input**: User description: "Add non-mutating --dry-run preview mode for sync and reindex workflows reporting file changes, chunk counts, estimated embedding tokens, and estimated offline cost without mutating collection state or invoking embedding providers."

## Clarifications

### Session 2026-11-17

- Q: How should `reindex --dry-run` respond when the target collection has no existing manifest or zero committed documents? → A: Return a zero-work dry-run summary (`0` sources, `0` chunks, `0` tokens, `$0.00`, exit `0`) without creating `.docpipe/`, preserving parity with live `reindex` (`0`).
- Q: Should live `sync()` also populate the chunk, token, and cost preview fields on `SyncResult`, or should those fields apply only in dry-run mode? → B: Extend `SyncResult` with defaulted preview fields (`dry_run`, `estimated_children`, `estimated_parents`, `estimated_tokens`, `estimated_cost_usd`) and populate chunk, token, and cost metrics consistently across both live `sync()` and `dry_run=True`.
- Q: Must `reindex --dry-run` guarantee zero byte changes on existing database files even when invoked in a fresh CLI process? → A: Guarantee strict `0`-byte immutability across cold CLI invocations and read-only directories for default local storage (falling back to the registered `Store` only for custom stores).

## Constitution Check

All requirements comply with [constitution.md](../../.specify/memory/constitution.md) (`v1.3.1`, ratified `2026-11-12`, last amended `2026-11-15`):

- **Scope Discipline (I)**: Exposes dry-run preview strictly through the existing Phase 1 library operations and CLI subcommands (`sync`, `reindex`), without adding background daemons, servers, or framework layers.
- **Two-Phase Architecture (II)**: Stays strictly inside Phase 1 document lifecycle planning (`sync`, `reindex`), keeping Phase 2 read-only paths untouched and adding zero mutation to dry-run invocations.
- **Library Purity (III)**: Reads zero external configuration or policy files inside library modules; CLI flags (`--dry-run`, `--json`) remain isolated in `cli.py`, and cost lookup uses bundled offline pricing data without credentials or network calls.
- **Search Small, Return Big & Exception Preservation (IV, V)**: Reuses existing pre-chunking cleaning, enrichment (including PII blocking checks without writing audit files), and chunking logic so dry-run chunk counts match live execution accurately and Safety Gates (`reverse`, `pii`) remain green.
- **Provider Agnosticism & Local-First (VI)**: Runs completely offline with zero embedding API calls and zero new third-party dependencies; local/loopback models deterministically estimate `$0.00` cost while unknown cloud pricing degrades cleanly to unavailable without failing.
- **Structured Correctness (VII)**: Enforces zero byte drift and zero creation of missing persistence directories during dry-run previews while preserving existing return contracts for non-dry-run callers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preview Directory Synchronization Without Mutations or Embedding Calls (Priority: P1)

A developer or operator managing an indexed collection wants to inspect what a directory synchronization run would change before incurring embedding API costs or modifying committed records. When running synchronization in dry-run mode (either programmatically or via CLI), the system classifies all candidate files against the existing collection state, executes all offline document preparation (parsing, cleaning, enrichment, and chunking) on changed files to compute exact chunk and token volumes, and outputs a summary covering added, modified, unchanged, and removed files alongside estimated child chunks, estimated embedding tokens, and estimated embedding cost — while leaving the collection directory, manifest, audit log, and stores completely untouched and making zero embedding calls.

**Why this priority**: Sync runs on large or newly modified folders can trigger costly external embedding batches or delete stale sources; operators need a safe, exact preflight report before committing changes.

**Independent Test**: Can be fully tested against both an uninitialized collection directory (non-existent persistence directory) and a previously seeded collection containing new, edited, unchanged (including timestamp-only drift), and deleted files, verifying identical filesystem hashes and zero embedding provider calls.

**Acceptance Scenarios**:

1. **Given** an uninitialized persistence directory and a folder of supported documents, **When** a user runs `sync` in dry-run mode, **Then** the report lists all discovered files under `added`, reports accurate child chunk counts, parent section counts, and estimated embedding tokens, and creates neither the persistence directory nor any manifest/store files on disk.
2. **Given** an existing seeded collection where one file is unchanged, one file changed only its filesystem timestamp, one file has modified content, one new file was added, and one tracked file was deleted from disk, **When** `sync` runs in dry-run mode, **Then** the dry-run report classifies all four buckets accurately (`added`, `updated`, `skipped`, `removed`), counts tokens only for chunks belonging to `added` and `updated` files, and leaves every byte of the persistence directory unchanged (including preserving the prior manifest metadata on timestamp-only drift).
3. **Given** a collection synced under PII block enforcement or a mismatched embedding model lock, **When** `sync` runs in dry-run mode on blocked PII or a mismatched model, **Then** it fails loudly with the same typed refusal before embedding, without writing a PII block audit entry or modifying persisted state.

---

### User Story 2 - Preview Full Collection Re-Embedding Volume and Cost (Priority: P2)

An engineer preparing to migrate an existing collection to a new embedding model wants to verify how many active chunks and estimated tokens will be re-embedded and what the offline cost estimate is before dropping and rebuilding the collection index. Running reindex in dry-run mode reports the target collection, target embedding model, number of active committed sources and child chunks to re-embed, estimated embedding tokens, and offline estimated cost, without resetting, writing to, or creating any store, lexical index, or manifest files and without calling the embedding provider.

**Why this priority**: Reindexing re-embeds every active child chunk in a collection and resets existing vector/lexical indices; previewing volume and cost prevents accidental expensive or destructive runs.

**Independent Test**: Can be verified by creating an existing multi-document collection (with stale staging excluded via active versions), capturing a byte-level snapshot of the persistence directory, running `reindex` in dry-run mode, and asserting exact active child counts, deterministic token estimates, zero embedding calls, and zero persisted byte changes.

**Acceptance Scenarios**:

1. **Given** a populated collection with committed documents and an active embedding model lock, **When** a user runs `reindex` toward a new model in dry-run mode, **Then** the report accurately reflects the count of active child chunks and active sources, reports non-zero estimated tokens (and offline cost estimate for the new model), makes zero embedding requests, and leaves the existing manifest lock, vector collection, and lexical index unmodified.
2. **Given** a target persistence directory or collection that has no existing manifest, **When** a user runs `reindex` in dry-run mode, **Then** the system does not create missing persistence directories on disk and cleanly reports a zero-work dry-run summary (0 sources, 0 chunks, 0 tokens).

---

### User Story 3 - Machine-Readable JSON Reports & Dry-Run Previews via CLI (Priority: P2)

A CI script or automation operator invokes `docpipe-maestro sync <dir> [--dry-run] --json` or `docpipe-maestro reindex --model <model> [--dry-run] --json` to gate automated ingestion pipelines on budget thresholds or change counts and parse live outcomes consistently. Passing `--dry-run` emits a clear human-readable preview by default and structured JSON on standard output when combined with `--json`, while passing `--json` without `--dry-run` emits matching live JSON output on standard output and preserves structured logging separation on standard error (`--log-json`).

**Why this priority**: Automated ingestion jobs need stable machine-readable diff, token, cost, and completion counts across both dry-run and live runs without screen-scraping human text.

**Independent Test**: Can be validated via CLI integration tests invoking both human text and `--json` modes for `sync --dry-run`, live `sync --json`, `reindex --dry-run`, and live `reindex --json`, parsing JSON `stdout` cleanly and confirming exit code `0` (with zero store mutations in dry-run modes).

**Acceptance Scenarios**:

1. **Given** a directory ready to sync, **When** an operator runs `docpipe-maestro sync <dir> --dry-run --json`, **Then** standard output is valid JSON containing `dry_run: true`, collection, model, `added`, `updated`, `skipped`, `removed`, chunk counts (`children_indexed`, `parents_indexed`, `estimated_children`, `estimated_parents`), `estimated_tokens`, and `estimated_cost_usd`, and the command exits `0`.
2. **Given** a directory ready to sync, **When** an operator runs `docpipe-maestro sync <dir> --json` without `--dry-run`, **Then** standard output is valid JSON with the same `SyncResult` schema and `dry_run: false`, and the command exits `0`.
3. **Given** a populated collection ready to reindex, **When** an operator runs `docpipe-maestro reindex --model openai/text-embedding-3-small --dry-run --json`, **Then** standard output is valid JSON reporting `dry_run: true`, collection, `embed_model`, `total_sources`, `total_children`, `total_parents`, `estimated_tokens`, and `estimated_cost_usd`, with exit code `0`.
4. **Given** a populated collection ready to reindex, **When** an operator runs `docpipe-maestro reindex --model <model> --json` without `--dry-run`, **Then** standard output is valid JSON containing `collection`, `embed_model`, `reindexed_children`, and `dry_run: false`, with exit code `0`.

---

### Edge Cases

- **Unchanged directory sync**: Running `sync --dry-run` when no files were added, modified, or removed reports empty `added`, `updated`, and `removed` lists, `0` children/parents to write, `0` estimated tokens, and `$0.00` estimated cost without calling the embedding provider or touching `mtime`/`size` on disk.
- **Remote vs. local model cost lookup**: Local/loopback embedding models deterministically report `0.0` USD estimated cost without loading remote pricing tables; recognized cloud models (e.g., `openai/text-embedding-3-small`) compute USD cost from offline bundled per-token pricing; unrecognized/custom remote model identifiers return unavailable (`None` / `unknown`) rather than erroring or making network calls.
- **`--local-only` enforcement in dry-run**: Selecting a remote embedding model while `--local-only` / `local_only=True` is active still fails immediately with a local-only refusal error even under `--dry-run`.
- **Documents yielding zero content after cleaning/chunking**: Unsupported or malformed files in the sync directory still raise `UnsupportedFormatError` during dry-run discovery/intake validation cleanly before any writes, consistent with live `sync`.
- **Deleted-only sync**: When tracked files are removed from disk with no additions or updates, `sync --dry-run` lists them under `removed` with `0` estimated tokens and `$0.00` cost.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a non-mutating dry-run preview mode for both `sync` and `reindex` accessible through the library API and CLI (`--dry-run`).
- **FR-002**: During `sync` dry-run mode, System MUST NOT create missing persistence directories, write or update manifest files (even when file timestamps/sizes drift on unchanged files), mutate vector store collections or SQLite FTS5 lexical indices, write PII audit log files, or invoke any embedding provider calls.
- **FR-003**: During `reindex` dry-run mode, System MUST NOT mutate or reset existing vector collections, lexical indices, or manifests, MUST NOT create missing persistence directories, MUST invoke **0** embedding provider calls, and MUST guarantee **0 bytes** modified across existing database files (including across standalone CLI subprocesses and read-only directories for default local storage, delegating to the registered `Store` only for custom store backends).
- **FR-004**: `sync` MUST classify candidate files into `added`, `updated`, `skipped`, and `removed` lists and populate `estimated_children`, `estimated_parents`, deterministic offline `estimated_tokens` (summed across staged child chunks for `added` and `updated` sources), and `estimated_cost_usd` consistently across both live execution (`dry_run=False`) and dry-run preview (`dry_run=True`).
- **FR-005**: `reindex` dry-run preview MUST count active committed sources and child chunks in the collection (excluding uncommitted staging records when active manifest versions apply) and compute deterministic offline `estimated_tokens` summed across those child chunks' texts, returning a zero-work preview (`0` sources, `0` children, `0` tokens, `0.0` cost, exit `0`) without creating directories when the collection manifest is absent or empty.
- **FR-006**: Dry-run previews MUST compute offline `estimated_cost_usd` (`0.0` for local/loopback models, token count * offline per-token rate for known models, and `None` when offline pricing for the model is unavailable) without making network requests.
- **FR-007**: Dry-run preflight MUST preserve validation errors identically to live execution — raising on missing target directory, invalid file format, collection model lock mismatch (during `sync`), unregistered stage keys, `--local-only` violations, or blocked PII rules (without persisting audit log mutations on dry-run).
- **FR-008**: CLI `sync` and `reindex` commands MUST accept `--dry-run` and `--json`, emitting clear human-readable summaries by default and clean machine-parseable JSON on `stdout` when `--json` is passed (while keeping any optional diagnostic logging on `stderr`).
- **FR-009**: Existing default invocations (`dry_run=False`, omitted CLI `--dry-run`) MUST remain 100% backward-compatible in return types, behavior, and CLI output.

### Key Entities

- **Synchronization Summary (`SyncResult`)**: Immutable result returned by both live and dry-run `sync()`, carrying `collection`, `embed_model`, `added`, `updated`, `skipped`, `removed`, `dry_run` flag, `estimated_children`, `estimated_parents`, deterministic offline `estimated_tokens`, and optional `estimated_cost_usd`.
- **Reindex Dry-Run Summary (`ReindexPreview`)**: Immutable summary returned by `reindex(..., dry_run=True)` carrying `collection`, target `embed_model`, `previous_embed_model`, active `total_sources`, `total_children`, `total_parents`, deterministic offline `estimated_tokens`, optional `estimated_cost_usd`, and `dry_run=True`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running `sync` or `reindex` in dry-run mode performs **0** embedding provider calls and results in **0 bytes** created or modified across existing manifest, SQLite, lexical, audit, or vector storage paths (verified both in-process and across fresh CLI invocations / read-only persistence directories on default local storage).
- **SC-002**: Dry-run classification counts (`added`, `updated`, `skipped`, `removed`) and chunk counts match a subsequent live execution over unchanged inputs with **100%** accuracy.
- **SC-003**: Token counts and local vs. known cloud cost estimates execute **100% offline** in single-run latency comparable to parsing/chunking without triggering any outbound network requests or credential requirements.
- **SC-004**: All existing tests, Release Gate #1 (`@pytest.mark.reverse`), Release Gate #2 (`@pytest.mark.pii`), strict type checks, and lint rules pass with `>= 80%` test coverage.

## Assumptions

- `ingest` already offers incremental manifest skipping and hash validation; backlog item `8.1` scopes `--dry-run` specifically to `sync` and `reindex`.
- Token estimation in dry-run reuses the repository's existing offline deterministic token estimator (`estimate_tokens`) rather than adding remote tokenizer downloads or external dependencies.
- Bundled offline model pricing lookup via LiteLLM's local cost map (`LITELLM_LOCAL_MODEL_COST_MAP="true"`) suffices for common cloud embedding providers, with `None` / unavailable shown cleanly for unlisted models.

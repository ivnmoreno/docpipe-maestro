<!--
# Sync Impact Report
- Version change: 1.3.0 -> 1.3.1
- Rationale: Fulfill v1.3.0 follow-up TODO by syncing finalized Stage 4 (`009-pii-protection`) public root exports (`register_pii_recognizer`, `PiiPolicy`, `PiiBlockedError`) into Quality Gates.
- Migration Note: Strictly additive root exports (`__all__` count incremented to 36); zero breaking changes for existing callers or Phase 1/2 signatures.
- List of modified principles: None
- Modified sections:
  - Additional Constraints -> Quality Gates (synced `register_pii_recognizer`, `PiiPolicy`, `PiiBlockedError` into the root public API surface list)
- Added sections: None
- Removed sections: None
- Follow-up TODOs: None
-->

# docpipe-maestro Constitution

## Core Principles

### I. Scope Discipline (NON-NEGOTIABLE)

The product is a minimal RAG pipeline library — not an application, not a framework,
not a platform. "Minimal" applies strictly to feature surface and scope promise,
never to engineering rigor, correctness guarantees, or safety discipline
(*minimal in promise, not in rigor*). Anything that assumes "a user is waiting" (UI, HTTP API,
sessions, auth, streaming, deployment) belongs to the consuming application. Anything
that cannot be reached through the public API surface does not belong in the core.
Every feature proposal must pass the one-sentence positioning test:

> "A minimal RAG pipeline: it is the engine — not the app, not the framework."

### II. Two-Phase Architecture

Every module belongs to exactly one phase: Phase 1 (ingest, offline, run once per
batch) or Phase 2 (query, online, run per question). Shared modules (types, config,
store, manifest) must serve both phases without blurring the boundary. Phase 1 work
must never degrade Phase 2 latency; Phase 2 must treat the store and manifest as
read-only. The file tree must make the phase of every module legible without opening it.

### III. Library Purity

No module in the library reads a user config or policy file. cli.py is the only file
that may; runtime configuration and PII policies MUST be passed programmatically to
library entry points. Chunking profiles are Python constants, not files. Provider
credentials come exclusively from environment variables — never from code, config, logs,
or error messages. There is no provider registry in the codebase; provider resolution is
delegated to the unified client via `provider/model` strings. Adding a provider must
require zero code changes.

### IV. Search Small, Return Big (NON-NEGOTIABLE)

Retrieval must match child chunks and return parent sections. Every child must
carry a `parent_id`. Parents must be stored with a `type` field that excludes them
from similarity search via an explicit filter. Parent sections must be deduplicated
before being returned. This principle exists because incomplete retrieval can
*invert the meaning* of a rule — not merely reduce precision. A system that returns
"20 days of leave" without "except for new hires" is not imprecise; it is wrong.

### V. Exception Preservation

Any retrieval context containing a rule with an exception marker (`except`,
`unless`, `not entitled`, `subject to`, `provided that`) must also contain that
exception. This is enforced by the reverse test against a fixture policy corpus,
which serves as mandatory **Release Gate #1** (`@pytest.mark.reverse`). PII ingestion
safeguards, outbound egress protection, and zero-raw-PII audit guarantees are enforced
by the PII safety suite as mandatory **Release Gate #2** (`@pytest.mark.pii`). A
release that fails Release Gate #1 or Release Gate #2 MUST NOT be published, regardless
of other passing tests; safety claims are only credible when verified by automated gates.

### VI. Provider Agnosticism and Local-First Default

Embeddings and generation are addressed by `provider/model` strings through a
single unified interface. The default generation model is local, so the
out-of-the-box configuration requires no third-party account and no network access.
The full pipeline must be runnable with zero external network calls when configured
with local providers. Privacy is a default, not an opt-in.

### VII. Structured Correctness Over Speed

Chunking must be structure-aware: split on headings, then sections, then clauses,
then sentences, and only as a last resort on characters. No clause may be split
across chunks in policy profiles. Overlap is scoped to a parent section and resets
at section boundaries. Crossrefs are resolved or logged — never silently dropped.
Data shapes are defined once in `types.py` and imported everywhere; schema drift
across modules is prohibited.

## Additional Constraints

### Data and Privacy

- Credentials are environment variables only. No credential may appear in source,
  config, logs, or error output.
- Local execution must require no outbound network call. When strict local-only mode is
  requested, any remote LLM provider or non-loopback `api_base` MUST be rejected with a
  typed `DocpipeError` before any network request is made.
- Every retrieved section must carry metadata sufficient to cite source document,
  section, and page.
- Ingestion must be deterministic (identical inputs → identical content-addressed
  chunk IDs) and incremental:
  - Changes are tracked via a database-collocated ingestion manifest using content
    hashes (`sha256`), with `mtime` and `size` used strictly as fast-path hints.
  - Updates use source-scoped **delete-then-reinsert** (never ID-only upsert) wrapped
    in a staging/version-flip envelope so shrinking documents never leave orphaned
    clauses and failed re-ingestions leave the prior version intact and queryable.
  - Collections lock their embedding model identifier in the manifest; model
    mismatches between ingest and query are refused unless explicitly reindexed.
- When a PII policy is configured during ingestion:
  - Detection and transformation MUST execute pre-chunking across both section titles
    and body text so redacted or tokenized values never leak into child context headers
    or stored chunks.
  - Block-mode matches MUST halt ingestion via a typed `DocpipeError` before any vector
    store write or manifest commit, leaving prior collection state intact.
  - Tokenization MUST use a keyed/salted cryptographic digest of the matched value
    (never character-offset hashing) so repeated identifiers correlate deterministically
    without exposing plaintext.
  - Errors, telemetry, and PII audit logs (`.audit.jsonl`) MUST contain zero raw PII
    values (counts, entity types, actions, source keys, and document version digests
    only), and audit log storage MUST restrict directory permissions (`0o700` on POSIX
    systems).
- When remote LLM completion is invoked outside local-only mode, outbound prompts and
  role-separated chat messages MUST pass through the configured PII egress policy prior
  to transmission. Documentation MUST NOT overclaim "100% accurate detection" or blanket
  regulatory compliance (e.g., "GDPR compliant").

### Quality Gates

- Every behavioral change ships with tests. Running **all tests** across the entire
  suite after implementation is mandatory, and **all tests must pass** (zero
  failures). CI runs linting, static type checking, and the full suite; any
  failing test or red CI blocks completion and release.
- **Release Gate #1 (mandatory)**: The exception-preservation reverse test
  (`@pytest.mark.reverse`) must pass prior to every release.
- **Release Gate #2 (mandatory)**: The PII protection safety suite (`@pytest.mark.pii`)
  must pass prior to every release, verifying ingestion block/redaction/tokenization
  invariants, outbound PII egress guarding, local-only remote-call refusal, and
  zero-raw-PII audit logs.
- The package must install from TestPyPI in a clean environment before any PyPI
  release, and publishing uses trusted publishing rather than long-lived tokens.
- The public API surface is the contract: `ingest`, `sync`, `remove`, `status`,
  `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, optional `answer`,
  `answer_detailed`, extension decorators (`register_parser`, `register_cleaner`,
  `register_enricher`, `register_chunker`, `register_embedder`, `register_store`,
  `register_searcher`, `register_reranker`, `register_pii_recognizer`), shared data/result shapes (`Chunk`,
  `EmbeddedChunk`, `RetrievedChunk`, `SourceRecord`, `IngestResult`, `SyncResult`,
  `CollectionStatus`, `GenerationResult`, `PiiPolicy`), public exceptions (`DocpipeError`,
  `MissingExtraError`, `UnsupportedFormatError`, `EmptyDocumentError`,
  `ModelMismatchError`, `MissingCredentialError`, `RegistryError`, `IngestionError`,
  `GenerationError`, `PiiBlockedError`), and `__version__`. If a feature cannot be reached through that
  surface, it does not belong in the core.

### Footprint

- The default local configuration must run comfortably on 16 GB RAM with no GPU.
- The core install stays lean; generation is **optional to invoke** at runtime (Phase 1
  ingestion and Phase 2 retrieval work offline with zero LLM completion calls), while
  the unified client library handles both embeddings and completions in the core install.
- Built-in pattern/checksum PII recognizers MUST operate offline in the core install with
  zero automatic model downloads; optional NER-based PII dependencies MUST stay isolated
  behind an optional extra and load lazily only when requested.
- A new file format or storage backend must be additive — no existing module should
  need modification beyond registration.

## Governance

- This constitution supersedes feature convenience. A feature that violates a
  principle must be rejected, or the constitution amended first — never quietly
  worked around.
- Amendments require a documented rationale, a version bump, and a migration note
  describing what existing code or consumers must change.
- Every spec, plan, and task must include a "Constitution Check" confirming
  compliance with Principles I–VII before implementation begins.
- The one-sentence positioning is the tiebreaker for any scope dispute:

> "docpipe-maestro is a minimal RAG pipeline: it ingests any document, chunks it
> correctly, embeds it, stores it, retrieves the right sections, and optionally
> generates a grounded answer. It is the engine — not the app, not the framework."

**Version**: 1.3.1 | **Ratified**: 2026-11-12 | **Last Amended**: 2026-11-15

# Research & Architectural Decisions: PII Protection & Release Gate #2

**Feature**: `009-pii-protection` (`feat/009-pii-protection`)  
**Date**: 2026-11-15  
**Spec**: [spec.md](spec.md)

## Decision 1: Phase-Neutral PII Engine + Stage Isolation

- **Decision**: Place shared PII policy validation, recognizer registry, pattern/checksum recognizers, optional Presidio adapter, overlap resolver, and HMAC tokenization inside a new phase-neutral module `src/docpipe_maestro/_pii.py` with zero imports from `docpipe_maestro.ingest` or `docpipe_maestro.query`. Wrap it in Phase 1 via `src/docpipe_maestro/ingest/enricher/pii.py` (`PiiEnricher` lazily registered under `ENRICHERS["pii"]`) and in Phase 2 via `src/docpipe_maestro/query/egress.py` (`guard_egress`).
- **Rationale**: Mirroring Stage 3's `_crossrefs.py` split directly enforces Constitution Principle II (`Two-Phase Architecture`) and satisfies the automated AST boundary gate in `tests/test_library_purity.py` (`query/` never imports `ingest/`, and `_pii.py` imports neither `ingest/` nor `query/`). Lazy registration under `ENRICHERS["pii"]` preserves zero eager startup overhead (`tests/test_library_purity.py`).
- **Alternatives Considered**:
  - Keeping recognition logic inside `ingest/enricher/pii.py` and importing it from `query/egress.py` — **Rejected** because Phase 2 → Phase 1 imports violate Constitution II and fail `test_phase2_query_does_not_import_phase1_stage_contracts`.
  - Duplicating regex/checksum/Presidio logic across Phase 1 and Phase 2 — **Rejected** because duplicated security scanners invite policy/tokenization drift.

## Decision 2: Hybrid Deterministic Recognizers + Lazy Offline-Safe Optional `[pii]` Backend

- **Decision**: Implement seven zero-download, stdlib-only deterministic/checksum recognizers (`EMAIL_ADDRESS`, `IBAN_CODE` with ISO 13616 country lengths + MOD-97 checksum, `CREDIT_CARD` with Luhn mod-10 checksum, `US_SSN` with SSA prefix/group exclusions, `IP_ADDRESS` with `ipaddress` IPv4/IPv6 validation, bounded `PHONE_NUMBER` heuristic, and `ES_DNI` with MOD-23 `"TRWAGMYFPDXBNJZSQVHLCKE"` letter verification) plus an extensible `PII_RECOGNIZERS: Registry[PiiRecognizer]` registry in `_pii.py`. Add optional `pii = ["presidio-analyzer>=2.2.0", "presidio-anonymizer>=2.2.0"]` in `pyproject.toml`, loaded lazily *only* when `ner=True` or NER-only entity classes (`PERSON`, `LOCATION`, `ORGANIZATION`) are requested in `policy["types"]`.
- **Rationale**: Aligns with Constitution Footprint and CI offline guarantees (`pytest -m pii` passes offline across Python `3.10–3.13` with zero spaCy model downloads or network I/O). When Presidio NER is invoked, `_pii.py` iterates every configured language in `policy.get("languages", ["en", "es"])` rather than hardcoding `language="en"`, ensuring non-English recognizers (including `ES_DNI` / Spanish `SpainDNIRecognizer`) execute reliably and raising clean `MissingExtraError` (or `DocpipeError` when spaCy runtime models are absent offline, never triggering `spacy.cli.download`) when `[pii]` is unavailable.
- **Alternatives Considered**:
  - Requiring `presidio-analyzer` in core dependencies — **Rejected** because `spacy`/`thinc` add heavy install footprint and risk runtime spaCy model downloads.
  - Hardcoding `language="en"` in Presidio/detection dispatch — **Rejected** because Spanish recognizers (`ES_DNI`) and multilingual documents silently get skipped.

## Decision 3: Pre-Chunking Section-by-Section Scrubbing & Auto-Enricher Scheduling Order

- **Decision**: `PiiEnricher.enrich(doc, ctx)` inspects `ctx.get("pii_policy")` (no-op when `None`) and evaluates **both** `sec.section_label` (heading) and `sec.raw_text` (body), plus `sec.clauses` if populated, using a single shared overlap-resolved transformation helper. In `ingest/pipeline.py`, supplying a non-`None` `pii_policy` (validated up front before file scanning) automatically schedules `"pii"` *ahead* of all other profile-declared enrichers (including when `DEFAULT.enrichers == ()` and ahead of `POLICY`'s `"crossrefs"`), unless `"pii"` already appears explicitly in `profile.enrichers` (in which case explicit placement governs with zero duplicate execution).
- **Rationale**: Directly implements Clarification Q1 and protects child context headers (`[Source: ... | Section: <sec.section_label>]`) built by `ingest/chunker/default.py` as well as preventing `CrossrefsEnricher` from replicating raw PII into `[Crossref ...]` excerpts across sections.
- **Alternatives Considered**:
  - Running `"pii"` after `"crossrefs"` — **Rejected** because cross-reference excerpts would already have duplicated raw body snippets across sections prior to scrubbing.
  - Requiring callers to build custom `ChunkingProfile(..., enrichers=("pii", ...))` — **Rejected** by Clarification Q1 (silent plaintext leak risk on `DEFAULT` / `POLICY`).

## Decision 4: Keyed/Salted Value-Based HMAC Tokenization with Process-Scoped Fallback

- **Decision**: Compute deterministic tokens as `[<ENTITY_TYPE>_<hex8>]` where `<hex8>` is `hmac.new(salt_bytes, raw_value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]`. Salt resolution checks explicit `policy["token_salt"]`, then `os.environ.get(policy["token_salt_env"])` when configured and non-empty; if neither exists (Clarification Q4 Option A), fall back to a process-wide cached `secrets.token_bytes(32)` generated on first fallback use and emit one warning noting cross-process repeatability requires configuring a persistent salt.
- **Rationale**: Strictly value-based (independent of character offset `start:end`), non-reversible without the secret salt, and immune to offline dictionary/rainbow attacks against predictable collection or file metadata while keeping zero-config single-process workflows ergonomic.
- **Alternatives Considered**:
  - Character-offset hashing (`start:end`) — **Rejected** because identical PII values at different positions yield inconsistent tokens and break multi-section correlation.
  - Deriving salt from `collection` name or path — **Rejected** because predictable collection strings weaken HMAC preimage resistance.
  - Failing immediately whenever salt is omitted — **Rejected** by Clarification Q4 Option A.

## Decision 5: Transactional Block-Mode Abort & Restricted `.audit.jsonl` Append Logging

- **Decision**: Add `audit_log_path(persist_dir, collection)` and `append_audit_record(persist_dir, collection, record)` in `src/docpipe_maestro/manifest.py` using `validate_collection_name` + path containment checks, `ensure_private_dir` (`0o700` on `<persist_dir>` and `<persist_dir>/manifests`), and owner-only file chmod (`0o600` suppressed cleanly on non-POSIX filesystems). During `ingest()` / `sync()`:
  - Non-blocking per-source `PiiAuditRecord` summaries (even when entity counts are all zero for scanned/changed sources) buffer in `staged_audit_records` during in-memory extraction and flush cleanly to `<collection>.audit.jsonl` alongside `save_manifest(...)` commit.
  - On any `block`-action detection (body or section heading), `PiiEnricher` raises `PiiBlockedError(DocpipeError)` carrying **only** source key and entity category names (never raw PII substrings). Pipeline catches `PiiBlockedError` during batch staging, emits a single `blocked=True` `PiiAuditRecord` (counts/actions/threshold/`doc_version`, zero raw PII) for that blocked source, omits uncommitted staged docs, and re-raises `PiiBlockedError` before vector store / lexical store / `manifest.json` writes.
- **Rationale**: Preserves docpipe-maestro's all-or-nothing transactional batch commit semantics while ensuring DPOs see every evaluated commit and every blocked violation attempt without leaking plaintext PII anywhere on disk or stderr.
- **Alternatives Considered**:
  - Flushing unblocked doc #1 audit entries before doc #2 blocks and rolls back doc #1 — **Rejected** because audit log would falsely imply doc #1 was committed into the collection.

## Decision 6: Shared Locality Classifier & Egress Guard Semantics

- **Decision**: Export `is_local_target(model: str, api_base: str | None = None) -> bool` and `enforce_local_only(model: str, api_base: str | None = None, *, operation: str) -> None` alongside existing `validate_api_base` and `_is_loopback_host` in `src/docpipe_maestro/embedder/default.py` (lazily exposed in `embedder/__init__.py`). Classification rules:
  - Validate `api_base` first via `validate_api_base`. If `api_base` is provided, return `_is_loopback_host(urlparse(validated_base).hostname)` (so loopback OpenAI-compatible servers pass even with `openai/...`, while remote `api_base` rejects even with `ollama/...`).
  - If `api_base is None`: treat `"ollama/"`, `"ollama_chat/"` (verifying `OLLAMA_API_BASE` / `OLLAMA_HOST` if set is also loopback), and `"local/"` prefixes as local; treat all other providers (`openai/`, `groq/`, `anthropic/`, remote prefixes, bare remote model IDs) as remote.
  In Phase 2, `src/docpipe_maestro/query/egress.py` calls `enforce_local_only` (before `has_context` short-circuit or HTTP calls!) and, for non-local targets with `pii_policy is not None` (Clarification Q2 Option A), validates and applies the configured policy (Clarification Q3 Option B: `allow` skips scrubbing, `block` rejects on any matched entity, default / `redact` honors each entity's configured `redact`/`tokenize`/`block` rule without downgrading `block`) across plain strings or every `"content"` in role-separated chat messages via a copied message list. `local_only=True` also guards `ingest`, `sync`, `reindex`, `retrieve`, and `evaluate` preflight before embedding calls.
- **Rationale**: Zero duplicated URL/loopback parsing across Phase 1 and Phase 2, zero Phase 2 → Phase 1 imports, exact compliance with Clarifications Q2, Q3, and Q5.
- **Alternatives Considered**:
  - Separate URL parser inside `query/egress.py` — **Rejected** (`validate_api_base` / `_is_loopback_host` already exist cleanly in `embedder`).
  - Checking `local_only` only inside `answer()` after retrieval or `has_context` check — **Rejected** because Scenario 3 & FR-011 require failing before any remote call or silent fallback.

## Decision 7: Public API Surface, CLI Flags & Gate #2 Alignment

- **Decision**: Export `PiiBlockedError`, `PiiPolicy`, and lazy `register_pii_recognizer` from `docpipe_maestro.__init__.__all__` (`33 -> 36` symbols) while exporting `PiiRecognizer`, `PiiDetection`, and `PiiAuditRecord` from `docpipe_maestro.types`; append optional keyword-only `pii_policy: PiiPolicy | None = None` / `local_only: bool = False` parameters to `ingest`, `sync`, `answer_detailed`, `answer` and `local_only: bool = False` to `reindex`, `retrieve`, `evaluate` cleanly updating `tests/test_api_stability.py`. In `cli.py`, support `--local-only` (`BooleanOptionalAction` + TOML `local_only` default on shared parser across all subcommands before/after subcommand) and `--pii-policy` (JSON/TOML policy loader strictly inside `cli.py`, accepted before/after `ingest`, `sync`, `ask`, cleanly rejecting misplaced usage on other subcommands). Add `"pii"` marker in `pyproject.toml`, `tests/test_pii_safety.py`, and CI Gate #2 step in `.github/workflows/ci.yml`.
- **Rationale**: Preserves exact positional/keyword backward compatibility for existing callers while delivering clean Python and CLI surfaces consistent with Stage 5/Stage 6 conventions.
- **Alternatives Considered**:
  - Keeping `PiiBlockedError` / `PiiPolicy` hidden only in `types.py` — **Rejected** because Constitution Principle I favors public exceptions/inputs reachable at root surface alongside `RegistryError`.

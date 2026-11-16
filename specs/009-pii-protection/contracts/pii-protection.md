# Interface Contracts: PII Protection, Outbound Egress & CLI

**Feature**: `009-pii-protection` (`feat/009-pii-protection`)  
**Date**: 2026-11-15  
**Spec**: [spec.md](spec.md)

## 1. Root & Public Python API (`docpipe_maestro.__init__` & `docpipe_maestro.types`)

### New Top-Level Exports (`docpipe_maestro.__all__`, `33 -> 36`)

- `PiiBlockedError`: Exception subclass of `DocpipeError`.
- `PiiPolicy`: `TypedDict(total=False)` configuration mapping.
- `register_pii_recognizer`: Lazy extension decorator forwarded to `docpipe_maestro._pii.register_pii_recognizer`.
- `docpipe_maestro.types` also exposes `PiiAction`, `EgressAction`, `PiiErrorMode`, `PiiDetection`, `PiiAuditRecord`, and `PiiRecognizer`.

### Extended Entry Point Signatures *(Strictly Additive Appended Keyword-Only Arguments)*

```python
ingest(
    path: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    force: bool = False,
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> IngestResult

sync(
    directory: str | Path,
    *,
    profile: str | ChunkingProfile = "DEFAULT",
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    cleaner: str = "default",
    chunker: str = "default",
    embedder: str = "default",
    store: str = "default",
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> SyncResult

reindex(
    *,
    embed_model: str,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embedder: str = "default",
    store: str = "default",
    local_only: bool = False,
) -> int

retrieve(
    question: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    top_k: int = DEFAULT_TOP_K,
    threshold: float | None = None,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
    rerank: bool = False,
    reranker: str = "cross_encoder",
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    local_only: bool = False,
) -> list[RetrievedChunk]

evaluate(
    fixture: str | Path | EvalFixture,
    *,
    collection: str | None = None,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    k_values: Sequence[int] = DEFAULT_EVAL_K_VALUES,
    expand_parent: bool = True,
    searcher: str = "default",
    rerank: bool = False,
    reranker: str = "cross_encoder",
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    local_only: bool = False,
) -> EvalReport

answer_detailed(
    prompt: str | Sequence[Mapping[str, str]],
    *,
    model: str = DEFAULT_GENERATION_MODEL,
    api_base: str | None = None,
    has_context: bool = True,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
    model_kwargs: Mapping[str, Any] | None = None,
    fail_on_truncation: bool = False,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> GenerationResult

answer(
    # identical parameters to answer_detailed(...) returning str
) -> str
```

> Backward Compatibility Guarantee: Calling any of the above functions without `pii_policy` or `local_only` executes the exact prior pipeline behavior with zero added network calls, files, or latency.

## 2. Phase-Neutral PII Engine (`src/docpipe_maestro/_pii.py`)

Must maintain zero imports from `docpipe_maestro.ingest` or `docpipe_maestro.query`.

### Extensible Recognizer Registry

`PiiRecognizer` is defined canonically in `docpipe_maestro.types` and re-exported by `_pii.py`, while `@register_pii_recognizer` is lazily exposed from top-level `docpipe_maestro`:

```python
@runtime_checkable
class PiiRecognizer(Protocol):
    name: str
    entity_type: str
    supported_languages: tuple[str, ...]  # e.g., ("*",) or ("es",)

    def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]: ...


PII_RECOGNIZERS: Registry[PiiRecognizer]
register_pii_recognizer = (
    PII_RECOGNIZERS.register
)  # re-exported lazily at docpipe_maestro.register_pii_recognizer
```

### Policy Validation & Transformation Contracts

```python
def validate_pii_policy(policy: PiiPolicy) -> ValidatedPiiPolicy:
    """Validate structure, actions, min_confidence in [0,1], languages, on_error, egress."""


def resolve_token_salt(policy: PiiPolicy) -> bytes:
    """Resolve explicit token_salt -> env[token_salt_env] -> cached random 32-byte fallback with warning."""


def tokenize_value(entity_type: str, value: str, *, salt: bytes) -> str:
    """Return '[{ENTITY}_{sha256_hmac[:8]}]' deterministically from salted value digest."""


def apply_pii_policy_to_text(
    text: str,
    policy: PiiPolicy,
    *,
    source: str = "",
    phase: str = "ingest",
) -> tuple[str, dict[str, int], dict[str, str]]:
    """Evaluate all configured recognizers across text, raising PiiBlockedError on block rules.

    Returns (transformed_text, entity_counts, actions_applied) with ZERO raw PII substrings
    carried in raised exception messages or returned summary maps.
    """
```

## 3. Phase 1 Enricher & Audit Log Contracts

### `PiiEnricher` (`src/docpipe_maestro/ingest/enricher/pii.py`)

- Registered lazily in `docpipe_maestro/ingest/enricher/__init__.py` as `ENRICHERS.register_lazy("pii", "docpipe_maestro.ingest.enricher.pii", "PiiEnricher")`.
- Implements `Enricher` protocol (`name = "pii"`, `enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument`).
- Scheduling rule (`Clarification Q1`): When `pii_policy is not None`:
  - If `"pii"` is NOT in `prof.enrichers`, resolve `"pii"` ahead of `prof.enrichers` (e.g., `["pii", *prof.enrichers]`).
  - If `"pii"` IS already in `prof.enrichers`, preserve `prof.enrichers` exact sequence (never run twice).
- Transformation scope: Evaluates `sec.section_label`, `sec.raw_text`, and each `clause.text` in `sec.clauses` sequentially in memory, accumulating section counts & actions across the document for audit logging before `CrossrefsEnricher` or `Chunker` runs.

### Audit Log (`src/docpipe_maestro/manifest.py`)

```python
def audit_log_path(persist_dir: Path, collection: str) -> Path:
    """Validate collection name and return <persist_dir>/manifests/<collection>.audit.jsonl."""


def append_audit_record(persist_dir: Path, collection: str, record: PiiAuditRecord) -> None:
    """Ensure 0o700 directories, append compact single-line JSON record with fsync, apply 0o600 file perms."""
```

## 4. Phase 1/2 Locality & Phase 2 Egress Contracts

### Shared Locality Validation (`src/docpipe_maestro/embedder/default.py` + `embedder/__init__.py`)

```python
def is_local_target(model: str, api_base: str | None = None) -> bool:
    """Return True iff target executes strictly locally or against a loopback api_base."""


def enforce_local_only(model: str, api_base: str | None = None, *, operation: str) -> None:
    """Raise DocpipeError before network I/O when local_only is enabled for a remote target."""
```

- Uses existing `validate_api_base(api_base)` and `_is_loopback_host(hostname)`.
- Explicit `api_base`: local iff `_is_loopback_host` is `True`.
- `api_base is None`: local iff `model` starts with `("ollama/", "ollama_chat/", "local/")` AND any set `OLLAMA_API_BASE`/`OLLAMA_HOST` also resolves to loopback.

### Outbound Egress Guard (`src/docpipe_maestro/query/egress.py`)

```python
@overload
def guard_egress(
    payload: str,
    *,
    model: str,
    api_base: str | None = None,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> str: ...


@overload
def guard_egress(
    payload: Sequence[Mapping[str, str]],
    *,
    model: str,
    api_base: str | None = None,
    pii_policy: PiiPolicy | None = None,
    local_only: bool = False,
) -> list[dict[str, str]]: ...
```

- Preflight always enforces `enforce_local_only(..., operation="generation")` when `local_only=True`.
- When `pii_policy is None`, target is local (`is_local_target(model, api_base)` is `True`), or `policy.get("egress") == "allow"`, `guard_egress` returns a normalized copy without mutating payloads (skipping redundant outbound scrubbing for strictly local/loopback targets while still enforcing `local_only`).
- For multi-message chat arrays: guards every message's `"content"` field while preserving exact `"role"` and message ordering.

## 5. CLI Contract (`src/docpipe_maestro/cli.py`)

- `--local-only` / `--no-local-only`: supported on `common` parent + top-level parser (works before or after `ingest`, `sync`, `reindex`, `query`, `ask`, `eval`; explicit CLI flags take precedence over `docpipe.toml` boolean key `local_only`, default `False`).
- `--pii-policy <PATH>`: supported before or after `ingest`, `sync`, and `ask` (and optionally `docpipe.toml` `pii_policy` relative/absolute path string or inline `[pii_policy]` table read solely inside `cli.py`); rejects misplaced usage before non-policy subcommands (`status`, `remove`, `reindex`, `query`, `eval`) with exit code `1`. Accepts `.json` (`json.loads`) or `.toml`/`.tml` (`tomllib`/`tomli`, either top-level keys or `[pii_policy]` wrapper table), validated via `validate_pii_policy`, and passed programmatically to library calls.

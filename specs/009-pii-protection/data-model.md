# Data Model: Configurable PII Protection & Egress Guard

**Feature**: `009-pii-protection` (`feat/009-pii-protection`)  
**Date**: 2026-11-15  
**Spec**: [spec.md](spec.md)

## 1. Domain Exceptions (`src/docpipe_maestro/types.py`)

### `PiiBlockedError(DocpipeError)`

- **Hierarchy**: Subclass of `DocpipeError` (exported from both `docpipe_maestro.types` and root `docpipe_maestro`).
- **Trigger conditions**:
  1. **Phase 1 Ingestion/Sync**: Any section heading/label or section body matches a PII entity mapped to `"block"` (aborts batch prior to vector store, lexical index, or manifest writes).
  2. **Phase 2 Outbound Egress**: When calling a non-local LLM with an active `PiiPolicy` and either `egress == "block"` (any configured match) or a matched entity is mapped to `"block"` under default / `egress == "redact"`.
- **Diagnostic Safety Constraint**: Exception text MUST carry only operation phase, source key (if ingestion), and sorted entity type identifiers (e.g., `Blocked PII entity type(s) ['US_SSN'] in source 'hr_policy.md'`), and MUST NEVER contain matched plaintext substrings.

## 2. Type Aliases & Policy Schemas (`src/docpipe_maestro/types.py`)

```python
PiiAction = Literal["redact", "tokenize", "block"]
EgressAction = Literal["redact", "block", "allow"]
PiiErrorMode = Literal["fail", "continue"]
```

### `PiiPolicy(TypedDict, total=False)`

| Field | Type | Default | Validation Rules |
|---|---|---|---|
| `types` | `dict[str, PiiAction]` | `{}` | Keys must be non-blank entity type strings (normalized uppercase); values must belong to `{"redact", "tokenize", "block"}`. Empty `types` scans zero entities cleanly. |
| `min_confidence` | `float` | `0.6` | Must be finite `float`/`int` (not `bool`) in `[0.0, 1.0]`. Matches below threshold are discarded. |
| `languages` | `list[str]` | `["en", "es"]` | Non-empty sequence of non-blank ISO language codes (normalized lowercase). Never hardcoded to `["en"]`. |
| `on_error` | `PiiErrorMode` | `"fail"` | Must belong to `{"fail", "continue"}`. Applies to recognizer/NER runtime failures only; `PiiBlockedError` ALWAYS halts execution. |
| `egress` | `EgressAction` | `"redact"` | Must belong to `{"redact", "block", "allow"}`. `"redact"` / omitted preserves per-entity `types` dispositions outbound; `"block"` blocks outbound calls on any match; `"allow"` skips outbound scrubbing without relaxing `local_only`. |
| `ner` | `bool` | `False` | Enables optional `[pii]` NER analysis. Automatically implied when `types` includes standard NER entities (`PERSON`, `LOCATION`, `ORGANIZATION`) not covered by built-in/custom recognizers. |
| `token_salt` | `str` | `""` | Explicit secret salt for HMAC tokenization (optional; overrides `token_salt_env` if non-empty). |
| `token_salt_env` | `str` | `""` | Environment variable name holding persistent salt (e.g., `"DOCPIPE_PII_SALT"`). If both salt sources are empty when `"tokenize"` runs, `_pii.py` uses a cached cryptographically random `secrets.token_bytes(32)` per process and logs one warning. |

### `PiiDetection(TypedDict)` *(Ephemeral In-Memory Span Record)*

| Field | Type | Notes |
|---|---|---|
| `entity_type` | `str` | Normalized entity category (e.g., `"US_SSN"`, `"ES_DNI"`) |
| `start` | `int` | Character start offset (`0 <= start < end <= len(text)`) |
| `end` | `int` | Character end offset |
| `score` | `float` | Confidence score in `[0.0, 1.0]` |
| `recognizer` | `str` | Recognizer identifier (`"builtin:<name>"`, `"custom:<name>"`, `"presidio"`) |

> Note: `PiiDetection` intentionally omits raw matched plaintext substrings (`matched_text`) so transient detection metadata can never accidentally serialize secrets.

### `PiiAuditRecord(TypedDict)` *(Persisted Zero-Raw-PII Entry in `<collection>.audit.jsonl`)*

| Field | Type | Notes |
|---|---|---|
| `timestamp` | `str` | UTC ISO-8601 timestamp (`datetime.now(timezone.utc).isoformat()`) |
| `collection` | `str` | Target collection identifier |
| `source` | `str` | Canonical source key (relative POSIX path) |
| `doc_version` | `str` | 12-char `sha256` hex prefix (`sha256_hex[:12]`) |
| `threshold` | `float` | Effective `min_confidence` applied |
| `entity_counts` | `dict[str, int]` | Sorted entity category → occurrence count |
| `actions` | `dict[str, str]` | Sorted entity category → effective action (`"redact"`, `"tokenize"`, `"block"`) |
| `blocked` | `bool` | `True` when ingestion aborted due to `"block"` match; `False` when committed |
| `mode` | `str` | Operation mode (`"ingest"` or `"sync"`) |

### `IngestContext` Extension (`src/docpipe_maestro/types.py`)

Add optional key under `IngestContext(_IngestContextBase, total=False)`:

```python
class IngestContext(_IngestContextBase, total=False):
    """Execution context passed to Phase 1 ``Enricher`` stage extensions."""

    extra: dict[str, Any]
    pii_policy: PiiPolicy | None
```

### `PiiRecognizer(Protocol)` *(Extensible Recognizer Strategy in `src/docpipe_maestro/types.py`)*

| Attribute / Method | Signature / Type | Notes |
|---|---|---|
| `name` | `str` | Recognizer identifier recorded in `PiiDetection["recognizer"]` |
| `entity_type` | `str` | Normalized entity label (e.g., `"EMPLOYEE_BADGE"`) |
| `supported_languages` | `tuple[str, ...]` | ISO language codes or `("*",)` wildcard |
| `detect` | `(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]` | Registered via top-level `@docpipe_maestro.register_pii_recognizer` |

## 3. Built-In Deterministic Recognizer Taxonomy & Replacement Grammar

### Built-In Entity Categories (`src/docpipe_maestro/_pii.py`)

| Entity Type | Language Scope | Confidence | Validation Logic |
|---|---|---|---|
| `EMAIL_ADDRESS` | `*` (all) | `0.95` | Practical RFC email regex with strict host/TLD boundaries |
| `IBAN_CODE` | `*` (all) | `0.95` | Uppercase canonicalization, country-code length table check, ISO 13616 MOD-97 `== 1` |
| `CREDIT_CARD` | `*` (all) | `0.95` | 13–19 digits (single space/hyphen groups allowed), Luhn mod-10 `== 0`, non-uniform digits |
| `US_SSN` | `en`, `*` | `0.90` | Delimited `AAA-GG-SSSS` / `AAA GG SSSS`; rejects area `000`/`666`/`900–999`, group `00`, serial `0000` |
| `IP_ADDRESS` | `*` (all) | `0.90` | Word/delimiter-bounded IPv4 & IPv6 candidates validated via stdlib `ipaddress.ip_address()`, skipping prefixed software versions (e.g., `v1.2.3.4`) |
| `PHONE_NUMBER` | `*` (all) | `0.75` | International/regional phone formats (`+CC ...`, `(AAA) ...`, `XXX-XXX-XXXX`) requiring `7–15` digits, guarded against dates & numeric section clauses |
| `ES_DNI` | `es` | `0.95` | Spanish 8-digit + letter DNI validated against MOD-23 `"TRWAGMYFPDXBNJZSQVHLCKE"` control letter |

### Overlap Resolution & Replacement Formats

1. Filter candidate detections by `score >= min_confidence` and membership in `policy["types"]` (or configured NER classes).
2. Sort candidates deterministically by `(-score, -(end - start), start)`.
3. Greedily retain non-overlapping intervals.
4. For `redact`: replace slice with `f"[{entity_type}]"` (e.g., `[EMAIL_ADDRESS]`).
5. For `tokenize`: compute `digest = hmac.new(salt_bytes, raw_value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]` and replace slice with `f"[{entity_type}_{digest}]"` (e.g., `[EMAIL_ADDRESS_a1b2c3d4]`).

## 4. Transactional State Transitions (Ingestion + Audit Log)

1. **Preflight**:
   - Validate `collection` name (`validate_collection_name`), `embed_model` lock (`check_model_lock`), `local_only` (`enforce_local_only` if `local_only=True`), and `pii_policy` (`validate_pii_policy` if not `None`).
   - Resolve enrichers up front (`auto_enrichers` prepends `"pii"` before `prof.enrichers` when `pii_policy is not None` and `"pii"` not already in `prof.enrichers`).
2. **In-Memory Extraction & PII Evaluation**:
   - Scan each non-unchanged document section-by-section: `sec.section_label`, `sec.raw_text`, and each clause in `sec.clauses`.
   - Aggregate per-document `entity_counts` and `actions`.
   - On any `block` match: append one `blocked=True` `PiiAuditRecord` to `<persist_dir>/manifests/<collection>.audit.jsonl` (creating directory with `0o700` on POSIX), then raise `PiiBlockedError` before vector store / lexical store / `manifest.json` writes. Prior committed chunks & manifest remain unchanged.
   - If zero blocks occur: buffer `blocked=False` `PiiAuditRecord` in `staged_audit_records`.
3. **Commit**:
   - Persist `VectorStore`, `LexicalIndex`, `manifest.json`, and then flush `staged_audit_records` to `<collection>.audit.jsonl` (`0o600` file, `0o700` parent directory on POSIX). Existing `<collection>.audit.jsonl` history is append-only and retained across `remove()` operations.

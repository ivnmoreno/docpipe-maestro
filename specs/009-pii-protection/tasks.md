---

description: "Actionable, dependency-ordered task list for Configurable PII Protection, Egress Guard & Release Gate #2"
---

# Tasks: Configurable PII Protection, Egress Guard & Release Gate #2

**Input**: Design documents from `/specs/009-pii-protection/`  
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/pii-protection.md](contracts/pii-protection.md), [quickstart.md](quickstart.md)

**Tests**: Included per explicit specification and Constitution `v1.3.0` requirements (`FR-013`, `SC-001`–`SC-006`, mandatory **Release Gate #2 `@pytest.mark.pii`** in `tests/test_pii_safety.py`, alongside Gate #1 `@pytest.mark.reverse` and full offline suite parity).

**Organization**: Tasks are grouped by user story (`US1`–`US5`) following Phase 1 (Setup) and Phase 2 (Foundational) so every P1/P2 increment is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`[US1]` through `[US5]`; omitted in Setup, Foundational, and Polish phases)
- Every task includes exact repository file paths and verbatim `data-model.md` constraints where applicable

## Path Conventions

- **Package modules**: `src/docpipe_maestro/`
- **Tests**: `tests/`
- **Repository & feature docs**: `SECURITY.md`, `PRODUCT.md`, `README.md`, `docs/`, `specs/009-pii-protection/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Packaging extras, strict typing overrides, pytest Release Gate #2 marker, and CI workflow wiring

- [X] T001 [P] Configure optional `pii = ["presidio-analyzer>=2.2.0", "presidio-anonymizer>=2.2.0"]` dependency extra (excluded from `all` alongside `rerank`), register `"pii: PII protection and egress release gate"` marker in `[tool.pytest.ini_options].markers`, and add `"presidio_analyzer.*"` and `"presidio_anonymizer.*"` to `[[tool.mypy.overrides]]` `ignore_missing_imports` in `pyproject.toml`
- [X] T002 [P] Add mandatory Release Gate #2 step running `uv run pytest -m pii -v` alongside existing Gate #1 (`uv run pytest -m reverse -v`) across Python `3.10–3.13` in `.github/workflows/ci.yml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Canonical PII types/exception contracts, phase-neutral recognizer/policy/HMAC engine, root public exports, and shared loopback locality validator that all user stories build upon

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Add `PiiBlockedError(DocpipeError)` (`Exception text MUST carry only operation phase, source key (if ingestion), and sorted entity type identifiers ... and MUST NEVER contain matched plaintext substrings`), `PiiAction = Literal["redact", "tokenize", "block"]`, `EgressAction = Literal["redact", "block", "allow"]`, `PiiErrorMode = Literal["fail", "continue"]`, `PiiPolicy(TypedDict, total=False)` (`types: dict[str, PiiAction]` default `{}`, `min_confidence: float` default `0.6`, `languages: list[str]` default `["en", "es"]`, `on_error: PiiErrorMode` default `"fail"`, `egress: EgressAction` default `"redact"`, `ner: bool` default `False`, `token_salt: str` default `""`, `token_salt_env: str` default `""`), `PiiDetection(TypedDict)` (`entity_type: str`, `start: int` with `0 <= start < end <= len(text)`, `end: int`, `score: float` in `[0.0, 1.0]`, `recognizer: str` — deliberately omitting `matched_text`), `PiiAuditRecord(TypedDict)` (`timestamp` UTC ISO-8601 `datetime.now(timezone.utc).isoformat()`, `collection: str`, `source: str`, `doc_version: str` as `sha256_hex[:12]`, `threshold: float`, `entity_counts: dict[str, int]` sorted, `actions: dict[str, str]` sorted, `blocked: bool`, `mode: str` `"ingest"` or `"sync"`), `@runtime_checkable class PiiRecognizer(Protocol)` (`name`, `entity_type`, `supported_languages`, `detect(text, *, languages)`), and optional `pii_policy: PiiPolicy | None` on `IngestContext(_IngestContextBase, total=False)` in `src/docpipe_maestro/types.py` (depends on T001)
- [X] T004 [P] Export `PiiBlockedError`, `PiiPolicy`, and lazy `register_pii_recognizer` cleanly in root `docpipe_maestro.__all__` (`33 -> 36`) preserving lazy loading behavior in `src/docpipe_maestro/__init__.py` (depends on T003, T005)
- [X] T005 [P] Create phase-neutral PII core with zero imports from `docpipe_maestro.ingest` or `docpipe_maestro.query`, re-exporting `PiiRecognizer` from `docpipe_maestro.types`, defining `PII_RECOGNIZERS: Registry[PiiRecognizer]`, `register_pii_recognizer`, and `validate_pii_policy(policy)` enforcing `"Keys must be non-blank entity type strings (normalized uppercase); values must belong to {\"redact\", \"tokenize\", \"block\"}"`, `"Must be finite float/int (not bool) in [0.0, 1.0]"`, `"Non-empty sequence of non-blank ISO language codes (normalized lowercase). Never hardcoded to [\"en\"]"`, `"Must belong to {\"fail\", \"continue\"}"`, and `"Must belong to {\"redact\", \"block\", \"allow\"}"` in `src/docpipe_maestro/_pii.py` (depends on T003)
- [X] T006 Implement and register all 7 zero-download built-in deterministic recognizers in `PII_RECOGNIZERS` in `src/docpipe_maestro/_pii.py`: `EMAIL_ADDRESS` (`*`, `0.95`, RFC email regex/TLD boundaries), `IBAN_CODE` (`*`, `0.95`, `"Uppercase canonicalization, country-code length table check, ISO 13616 MOD-97 == 1"`), `CREDIT_CARD` (`*`, `0.95`, `"13–19 digits (single space/hyphen groups allowed), Luhn mod-10 == 0, non-uniform digits"`), `US_SSN` (`("en", "*")`, `0.90`, `"Delimited AAA-GG-SSSS / AAA GG SSSS; rejects area 000/666/900–999, group 00, serial 0000"`), `IP_ADDRESS` (`*`, `0.90`, `"Word/delimiter-bounded IPv4 & IPv6 candidates validated via stdlib ipaddress.ip_address(), skipping prefixed software versions (e.g., v1.2.3.4)"`), `PHONE_NUMBER` (`*`, `0.75`, `"International/regional phone formats (+CC ..., (AAA) ..., XXX-XXX-XXXX) requiring 7–15 digits, guarded against dates & numeric section clauses"`), and `ES_DNI` (`("es",)`, `0.95`, `"Spanish 8-digit + letter DNI validated against MOD-23 \"TRWAGMYFPDXBNJZSQVHLCKE\" control letter"`) (depends on T005)
- [X] T007 Implement overlap resolution (`score >= min_confidence` filtering, deterministic sort `(-score, -(end - start), start)`, greedy non-overlapping interval retention), replacement grammar (`f"[{entity_type}]"` for `redact`; `resolve_token_salt` checking `token_salt` then `os.environ.get(token_salt_env)` then cached random `secrets.token_bytes(32)` with one warning log; `tokenize_value` returning `f"[{entity_type}_{digest}]"` with `hmac.new(salt_bytes, raw_value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]`), and `apply_pii_policy_to_text(text, policy, *, source="", phase="ingest")` raising `PiiBlockedError` with zero raw PII substrings in `src/docpipe_maestro/_pii.py` (depends on T006)
- [X] T008 [P] Implement `is_local_target(model: str, api_base: str | None = None) -> bool` and `enforce_local_only(model: str, api_base: str | None = None, *, operation: str) -> None` reusing existing `validate_api_base` and `_is_loopback_host` (`api_base` local iff `_is_loopback_host`; `api_base is None` local iff `model` starts with `("ollama/", "ollama_chat/", "local/")` and any `OLLAMA_API_BASE` / `OLLAMA_HOST` resolves to loopback; raises `DocpipeError` pre-network with zero raw PII) in `src/docpipe_maestro/embedder/default.py` (depends on T003)
- [X] T009 Re-export `is_local_target` and `enforce_local_only` lazily from `src/docpipe_maestro/embedder/__init__.py` (depends on T008)

**Checkpoint**: Foundation ready — `PiiBlockedError`, `PiiPolicy`, deterministic recognizers, HMAC tokenization, and shared locality validation exist; user stories can now proceed

---

## Phase 3: User Story 1 - Pre-Chunking PII Ingestion Protection & Blocking (Priority: P1) 🎯 MVP

**Goal**: Scrub or block sensitive PII across both section headings and section body text pre-chunking (ahead of child header generation and `CrossrefsEnricher`), with position-independent HMAC tokenization and fail-closed batch rollback on `block` rules

**Independent Test**: Run `pytest tests/test_pii_safety.py tests/test_invariants_stage1.py -k "pii or enrich"` against synthetic multi-section fixtures containing PII in headings and body paragraphs under `block`, `redact`, and `tokenize` rules

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T010 [P] [US1] Write failing `@pytest.mark.pii` pre-chunking ingestion tests covering all 7 built-in recognizers, MOD-97 IBAN & Luhn `CREDIT_CARD` false-positive rejection, custom `register_pii_recognizer`, redaction/tokenization in both `section_label` and body/clauses prior to child context header `[Source: ... | Section: ...]` construction and `CrossrefsEnricher`, position-independent HMAC tokens across sections/documents (explicit/env salt determinism + random fallback salt warning), and mid-batch `PiiBlockedError` aborting before vector/lexical/manifest writes with prior collection state intact and 0 raw PII in error text in `tests/test_pii_safety.py` (depends on T004, T007)
- [X] T011 [P] [US1] Write failing stage-ordering & backward-compatibility tests verifying `pii_policy` auto-schedules `"pii"` before all profile enrichers (including `DEFAULT` and ahead of `"crossrefs"` on `POLICY`), preserves custom explicit `"pii"` position in `ChunkingProfile.enrichers` with zero duplicate execution, and keeps `pii_policy=None` behavior identical in `tests/test_invariants_stage1.py` (depends on T004, T007)

### Implementation for User Story 1

- [X] T012 [US1] Create `PiiEnricher` (`name = "pii"`, `enrich(self, doc: ParsedDocument, ctx: IngestContext) -> ParsedDocument`) inspecting `ctx.get("pii_policy")`, sequentially scrubbing `sec.section_label`, `sec.raw_text`, and each `clause.text` in `sec.clauses` via `apply_pii_policy_to_text`, accumulating per-document `entity_counts` and `actions` without retaining raw PII substrings, and raising `PiiBlockedError` on any `block` match in `src/docpipe_maestro/ingest/enricher/pii.py` (depends on T007, T010)
- [X] T013 [US1] Register `"pii"` lazily in `ENRICHERS.register_lazy("pii", "docpipe_maestro.ingest.enricher.pii", "PiiEnricher")` keeping zero eager import cost in `src/docpipe_maestro/ingest/enricher/__init__.py` (depends on T012)
- [X] T014 [US1] Extend `ingest(...)` and `sync(...)` with keyword-only `pii_policy: PiiPolicy | None = None`, running preflight `validate_pii_policy`, auto-prepending `"pii"` ahead of profile enrichers when `pii_policy is not None` and `"pii"` not already in `profile.enrichers`, passing `pii_policy` in `IngestContext`, and guaranteeing transactional `PiiBlockedError` batch abort before vector store, lexical index, or `manifest.json` commits in `src/docpipe_maestro/ingest/pipeline.py` (depends on T011, T013)
- [X] T015 [US1] Run `pytest tests/test_pii_safety.py tests/test_invariants_stage1.py -k "pii or enrich"` and verify all US1 tests pass independently

**Checkpoint**: User Story 1 (MVP) is complete and independently testable — ingested chunks, child context headers, and batch rollbacks enforce PII policies pre-chunking

---

## Phase 4: User Story 2 - Strict Local-Only Mode & Outbound Egress Guard (Priority: P1)

**Goal**: Prevent non-local/non-loopback network requests under `local_only=True` across all embedding and generation entry points, and enforce configurable PII egress policies across outbound string prompts and role-separated chat message lists prior to remote LLM invocation

**Independent Test**: Run `pytest tests/test_pii_safety.py tests/test_prompts_answer.py -k "local_only or egress or pii"` using mocked transports and URL targets verifying remote refusal prior to transport dispatch, loopback allowance, and prompt/chat scrubbing/blocking

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T016 [P] [US2] Write failing `@pytest.mark.pii` locality and egress tests covering `is_local_target` / `enforce_local_only` (loopback `localhost`/`127.0.0.1`/`::1` OpenAI-compatible endpoints & `ollama/`/`ollama_chat/`/`local/` permitted; `openai/`/`groq/` & non-loopback `api_base` rejected pre-network across `ingest`, `sync`, `reindex`, `retrieve`, `evaluate`, `answer`, `answer_detailed`) and `guard_egress` on both `str` prompts and `list[dict[str, str]]` chat payloads preserving roles/order across omitted/`"redact"`, `"block"`, `"allow"`, `pii_policy=None` passthrough, and local-target passthrough with 0 raw PII in exceptions in `tests/test_pii_safety.py` (depends on T009, T015)
- [X] T017 [P] [US2] Write failing generation guard tests verifying `answer()` and `answer_detailed()` evaluate `guard_egress` prior to the `has_context` early return and LiteLLM completion calls, scrubbing/blocking system context and user query roles in `tests/test_prompts_answer.py` (depends on T009)

### Implementation for User Story 2

- [X] T018 [US2] Implement `guard_egress` with `@overload` typing for `str` and `Sequence[Mapping[str, str]]` in `src/docpipe_maestro/query/egress.py`: run `enforce_local_only(model, api_base, operation="generation")` when `local_only=True`; return normalized copy/payload untouched when `pii_policy is None` or `is_local_target(model, api_base)` is `True` or `policy.get("egress") == "allow"`; honor per-entity `redact`/`tokenize`/`block` rules under default/`"redact"`; escalate all configured entities to `PiiBlockedError` under `"block"`; maintain zero imports from `docpipe_maestro.ingest` (depends on T007, T009, T016)
- [X] T019 [P] [US2] Extend `answer_detailed(...)` and `answer(...)` with keyword-only `pii_policy: PiiPolicy | None = None, local_only: bool = False`, enforcing `guard_egress` across normalized prompts and chat messages prior to `has_context` early return and remote completion dispatch in `src/docpipe_maestro/query/answer.py` (depends on T017, T018)
- [X] T020 [P] [US2] Extend `retrieve(...)` with keyword-only `local_only: bool = False` calling `enforce_local_only(embed_model, operation="retrieval")` preflight before query embedding in `src/docpipe_maestro/query/retriever.py` (depends on T009, T016)
- [X] T021 [US2] Extend `evaluate(...)` with keyword-only `local_only: bool = False` calling `enforce_local_only(embed_model, operation="evaluation")` preflight and forwarding `local_only` to retrieval calls in `src/docpipe_maestro/eval/harness.py` (depends on T020)
- [X] T022 [P] [US2] Extend `ingest(...)`, `sync(...)`, and `reindex(...)` signatures with keyword-only `local_only: bool = False` calling preflight `enforce_local_only(embed_model, operation="ingest"|"sync"|"reindex")` prior to model loading or embedding transport calls in `src/docpipe_maestro/ingest/pipeline.py` (depends on T009, T014, T016)
- [X] T023 [US2] Run `pytest tests/test_pii_safety.py tests/test_prompts_answer.py -k "local_only or egress or pii"` and verify all US2 tests pass independently

**Checkpoint**: User Stories 1 AND 2 both work independently — Phase 1 ingestion and Phase 2 remote generation/retrieval respect `--local-only` and outbound egress PII rules

---

## Phase 5: User Story 3 - Zero-Raw-PII Structured Audit Trail (Priority: P1)

**Goal**: Persist machine-readable append-only `.audit.jsonl` records alongside collection manifests (`<persist_dir>/manifests/<collection>.audit.jsonl`) with owner-only (`0o700`/`0o600`) permissions, atomic commit coordination, `blocked=True` logging on abort, and zero raw PII substrings

**Independent Test**: Run `pytest tests/test_pii_safety.py tests/test_manifest.py -k "audit or pii"` inspecting generated JSONL records, filesystem POSIX modes (`0o700`/`0o600`), mid-batch abort logging, and exhaustive raw-PII substring absence

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T024 [P] [US3] Write failing `@pytest.mark.pii` audit log tests verifying `<persist_dir>/manifests/<collection>.audit.jsonl` creation, POSIX `0o700` directory / `0o600` file permissions, JSONL schema (`timestamp`, `collection`, `source`, `doc_version` `sha256_hex[:12]`, `threshold`, `entity_counts` sorted, `actions` sorted, `blocked`, `mode` `"ingest"`/`"sync"`), zero-count audit record emission for evaluated clean documents, staged flush on commit vs single `blocked=True` emission only for blocked source on mid-batch rollback, and exhaustive 0-raw-PII substring verification across the audit file in `tests/test_pii_safety.py` (depends on T023)
- [X] T025 [P] [US3] Write failing unit tests for `audit_log_path` (`validate_collection_name` path-traversal rejection and `<persist_dir>/manifests/<collection>.audit.jsonl` resolution) and `append_audit_record` POSIX chmod behavior in `tests/test_manifest.py` (depends on T003)

### Implementation for User Story 3

- [X] T026 [US3] Implement `audit_log_path(persist_dir: Path, collection: str) -> Path` and `append_audit_record(persist_dir: Path, collection: str, record: PiiAuditRecord) -> None` (calling `validate_collection_name`, containment guard, `ensure_private_dir` for `0o700` directories, appending compact single-line JSON with flush/`fsync`, applying `0o600` file perms wrapped in `contextlib.suppress(OSError)`) in `src/docpipe_maestro/manifest.py` (depends on T003, T025)
- [X] T027 [US3] Wire transactional `staged_audit_records` tracking across `ingest(...)` and `sync(...)`: gather per-document `(entity_counts, actions)` metadata from `PiiEnricher` evaluations, flush `blocked=False` `PiiAuditRecord` entries alongside `save_manifest(...)` commit (including zero-match entries when `pii_policy is not None`), and on `PiiBlockedError` append one `blocked=True` `PiiAuditRecord` with zero raw PII for the offending source while discarding uncommitted staged records prior to re-raising in `src/docpipe_maestro/ingest/pipeline.py` (depends on T012, T022, T026, T024)
- [X] T028 [US3] Run `pytest tests/test_pii_safety.py tests/test_manifest.py -k "audit or pii"` and verify all US3 tests pass independently

**Checkpoint**: User Stories 1, 2, AND 3 all work independently — DPOs have verifiable owner-only `.audit.jsonl` records containing zero raw PII across commits and blocked runs

---

## Phase 6: User Story 4 - Multi-Language Optional NER Extension & CLI Policy Supply (Priority: P2)

**Goal**: Support optional lazy `[pii]` Presidio NER across all configured policy languages with zero offline network downloads, and parse `--pii-policy` JSON/TOML policy files strictly inside the CLI boundary alongside `--local-only` flags across all 6 model/eval CLI subcommands

**Independent Test**: Run `pytest tests/test_pii_safety.py tests/test_cli.py -k "pii or local_only or ner"` verifying mocked multi-lang Presidio dispatch, missing-extra error hints, CLI flag ordering before/after subcommands, and CLI-only policy file parsing

### Tests for User Story 4 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T029 [P] [US4] Write failing `@pytest.mark.pii` optional `[pii]` NER tests using offline mocks/stubs verifying lazy import triggered only when `ner=True` or NER entity types (`PERSON`, `LOCATION`, `ORGANIZATION`) appear in `policy["types"]`, Presidio analysis loops over all configured `languages` (`["en", "es"]`, never hardcoded `"en"`), `on_error="fail"` vs `on_error="continue"` handling while `PiiBlockedError` always halts, `MissingExtraError` install hint when `[pii]` absent, and offline `DocpipeError` when spaCy runtime models are absent with zero runtime network downloads in `tests/test_pii_safety.py` (depends on T028)
- [X] T030 [P] [US4] Write failing CLI tests verifying `--local-only` / `--no-local-only` before and after all 6 subcommands (`ingest`, `sync`, `reindex`, `query`, `ask`, `eval`), `--pii-policy <PATH>` JSON & TOML loading before and after `ingest`, `sync`, and `ask`, exit code `1` on misplaced `--pii-policy` (`status`, `remove`, `reindex`, `query`, `eval`) or unreadable/invalid policy payloads, zero raw PII on stderr, and `docpipe.toml` `local_only` / `pii_policy` defaults in `tests/test_cli.py` (depends on T019, T021, T022)

### Implementation for User Story 4

- [X] T031 [P] [US4] Implement lazy optional `[pii]` Presidio NER adapter inside `src/docpipe_maestro/_pii.py` invoked only when `ner=True` or NER types (`PERSON`, `LOCATION`, `ORGANIZATION`) are requested: lazily import `presidio_analyzer`, iterate all normalized language codes in `policy["languages"]` (default `["en", "es"]`), convert results to `PiiDetection` spans omitting matched text, raise `MissingExtraError` when uninstalled or offline `DocpipeError` when spaCy models are missing locally (never triggering automatic downloads), and apply `on_error` (`"fail"` vs `"continue"`) solely to recognizer runtime failures while `PiiBlockedError` fails closed (depends on T007, T029)
- [X] T032 [P] [US4] Add `--local-only` (`BooleanOptionalAction` + `docpipe.toml` `local_only` default, supported on shared `common` parent and top-level parser before/after `ingest`, `sync`, `reindex`, `query`, `ask`, `eval`) and `--pii-policy <PATH>` (JSON via `json.loads` or TOML via `tomllib`/`tomli` parsed exclusively in `cli.py`, validated via `validate_pii_policy`, supported before/after `ingest`, `sync`, and `ask`, rejecting misplaced usage on non-policy commands with exit code `1`, forwarding `pii_policy` and `local_only` cleanly through CLI handlers including `_handle_ask` and `_handle_eval`) in `src/docpipe_maestro/cli.py` (depends on T005, T019, T020, T021, T022, T030)
- [X] T033 [US4] Run `pytest tests/test_pii_safety.py tests/test_cli.py -k "pii or local_only or ner"` and verify all US4 tests pass independently

**Checkpoint**: User Stories 1–4 are independently complete — optional multi-lang NER and CLI policy boundary respect Principles II & III offline

---

## Phase 7: User Story 5 - Release Gate #2 & Honest Scope Documentation (Priority: P2)

**Goal**: Solidify synthetic offline Release Gate #2 (`@pytest.mark.pii`), AST architectural & API stability guards (`tests/test_library_purity.py`, `tests/test_api_stability.py`), and transparent capability/limitation docs without compliance overclaims

**Independent Test**: Run `uv run pytest -m pii -v` and `uv run pytest tests/test_api_stability.py tests/test_library_purity.py -v` alongside doc overclaim verification

- [X] T034 [P] [US5] Finalize comprehensive offline synthetic `@pytest.mark.pii` Release Gate #2 suite covering end-to-end `SC-001`–`SC-006` (Markdown/HTML/structured multi-section fixtures with section-title PII, `block`/`redact`/`tokenize` across all 7 built-in recognizers + custom recognizer + mocked multi-lang Presidio, child context headers, mid-batch rollback, salted/fallback `.audit.jsonl` verification + `0o700` perms, `--local-only` refusal across all 6 entry points, and remote `str` + chat `guard_egress`) using zero real personal data in `tests/test_pii_safety.py` (depends on T033)
- [X] T035 [P] [US5] Update `EXPECTED_ALL` (`33 -> 36` exporting `PiiBlockedError`, `PiiPolicy`, `register_pii_recognizer`) and keyword-only parameter stability assertions for `ingest`, `sync`, `reindex`, `retrieve`, `evaluate`, `answer`, and `answer_detailed` in `tests/test_api_stability.py` (depends on T004, T019, T020, T021, T022)
- [X] T036 [P] [US5] Add AST isolation and eager-import checks verifying `_pii.py` imports neither `ingest` nor `query`, `query/` never imports `ingest/`, zero library modules outside `cli.py` load policy JSON/TOML files (Principle III), and importing `docpipe_maestro` loads zero `docpipe_maestro._pii`, `presidio_analyzer`, `presidio_anonymizer`, or `spacy` modules eagerly in `tests/test_library_purity.py` (depends on T004, T018, T031, T032)
- [X] T037 [P] [US5] Document PII protection capabilities, built-in vs optional `[pii]` NER scope, salt management, `.audit.jsonl` format & `0o700` permissions, `--local-only`, false-positive/false-negative limitations, and explicit non-claims (no `"GDPR compliant"` or `"100% accurate"` claims) in `SECURITY.md`
- [X] T038 [P] [US5] Document Stage 4 PII protection, `--local-only`, `--pii-policy`, Release Gate #2, and honest heuristic/NER detection limits in `PRODUCT.md`
- [X] T039 [P] [US5] Document `[pii]` extra installation, programmatic `PiiPolicy` & `PiiBlockedError` examples, CLI `--local-only` & `--pii-policy` usage, and honest scope disclosures in `README.md`
- [X] T040 [P] [US5] Update Python API reference covering `PiiBlockedError`, `PiiPolicy`, `PiiAction`, `EgressAction`, `PiiErrorMode`, `PiiDetection`, `PiiAuditRecord`, `PiiRecognizer`, `register_pii_recognizer`, `audit_log_path`, `is_local_target`, `enforce_local_only`, and `pii_policy`/`local_only` parameters in `docs/api-reference.md`
- [X] T041 [P] [US5] Update CLI reference covering `--local-only` / `--no-local-only` (`ingest`, `sync`, `reindex`, `query`, `ask`, `eval`), `--pii-policy` (`ingest`, `sync`, `ask`), `docpipe.toml` configuration defaults, and exit status `1` diagnostics in `docs/cli-reference.md`
- [X] T042 [P] [US5] Update architecture documentation illustrating phase-neutral `_pii.py`, Phase 1 `PiiEnricher` + `.audit.jsonl` commit/abort lifecycle, and Phase 2 `query/egress.py` + `enforce_local_only` dataflow in `docs/architecture.md`

**Checkpoint**: Release Gate #2, architectural AST boundaries, API surface checks, and honest repository docs are all complete

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Automated non-overclaim check, `quickstart.md` verification, static analysis/security checks, and full offline suite gate

- [X] T043 Add automated documentation disclosure & zero-overclaim check verifying `SECURITY.md`, `PRODUCT.md`, and `README.md` omit `"GDPR compliant"` and `"100% accurate"` claims while documenting heuristic/NER limitations in `tests/test_pii_safety.py` (depends on T034, T037, T038, T039)
- [X] T044 Validate `specs/009-pii-protection/quickstart.md` workflow and run formatting, lint, Bandit security rules, and strict type checks (`uv run ruff format --check .`, `uv run ruff check .`, `uv run ruff check --select S src/`, `uv run mypy src tests`) cleanly with zero errors (depends on T002, T031, T032, T035, T036, T040, T041, T042, T043)
- [X] T045 **REQUIRED**: Run both mandatory release gates (`uv run pytest -m reverse -v`, `uv run pytest -m pii -v`) across `tests/test_reverse_safety.py` and `tests/test_pii_safety.py`, and run the full `tests/` suite with branch coverage (`LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov`) after all edits finish; 100% of tests must pass offline (`>= 80%` branch coverage, zero skips or relaxed assertions) before reporting completion (depends on T044)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — starts immediately (`T001`–`T002`)
- **Foundational (Phase 2)**: Depends on Setup (`T001`) — **BLOCKS all user stories** (`T003`–`T009`)
- **User Story 1 (Phase 3 - P1 🎯 MVP)**: Depends on Foundational (`T003`–`T007`) — no dependency on US2–US5
- **User Story 2 (Phase 4 - P1)**: Depends on Foundational (`T003`, `T007`–`T009`); edits to `src/docpipe_maestro/ingest/pipeline.py` (`T022`) sequence after `T014` to avoid file conflicts
- **User Story 3 (Phase 5 - P1)**: Depends on Foundational (`T003`) + US1/US2 `pipeline.py` sequence (`T012`, `T022`) + US2 `test_pii_safety.py` sequence (`T023`) for clean non-overlapping file edits
- **User Story 4 (Phase 6 - P2)**: Depends on Foundational (`T005`, `T007`) + US2 API signatures (`T019`–`T022`) for CLI wiring (`T032`)
- **User Story 5 (Phase 7 - P2)**: Depends on `T004`, US1–US4 implementation completion (`T033`) before locking down final gate & AST/API/doc tests (`T034`–`T042`)
- **Polish (Phase 8)**: Depends on all User Stories (`T034`–`T042`) completing cleanly (`T043`–`T045`)

### Within Each User Story

- Tests are authored FIRST (`T010`–`T011`, `T016`–`T017`, `T024`–`T025`, `T029`–`T030`) and verified to fail before writing implementation code
- Phase-neutral helpers and exceptions (`types.py`, `_pii.py`, `embedder/default.py`) precede stage adapters (`ingest/enricher/pii.py`, `query/egress.py`, `manifest.py`)
- Stage adapters precede pipeline/API orchestration (`pipeline.py`, `answer.py`, `retriever.py`, `harness.py`) and CLI (`cli.py`)
- Each story closes with a focused verification checkpoint before moving forward

### Parallel Opportunities

- **Setup**: `T001` and `T002` run in parallel
- **Foundational**: After `T003`, `T004` (`__init__.py`), `T005` (`_pii.py`), and `T008` (`embedder/default.py`) run in parallel across distinct files
- **US1**: `T010` (`test_pii_safety.py`) and `T011` (`test_invariants_stage1.py`) run in parallel
- **US2**: `T016` (`tests/test_pii_safety.py`) and `T017` (`tests/test_prompts_answer.py`) run in parallel; `T019` (`answer.py`), `T020` (`retriever.py`), and `T022` (`ingest/pipeline.py`) run in parallel after `T018` / `T016`
- **US3**: `T024` (`test_pii_safety.py`) and `T025` (`test_manifest.py`) run in parallel
- **US4**: `T029` (`test_pii_safety.py`) and `T030` (`test_cli.py`) run in parallel; `T031` (`_pii.py`) and `T032` (`cli.py`) run in parallel after tests fail
- **US5**: `T035` (`test_api_stability.py`), `T036` (`test_library_purity.py`), `T037` (`SECURITY.md`), `T038` (`PRODUCT.md`), `T039` (`README.md`), `T040` (`docs/api-reference.md`), `T041` (`docs/cli-reference.md`), and `T042` (`docs/architecture.md`) all run in parallel alongside `T034` (`test_pii_safety.py`)

---

## Parallel Example: User Story 5 (Gate #2 & Honest Documentation)

```bash
# Run API stability, AST boundary purity, and all 6 documentation updates in parallel:
Task: "T035 [P] [US5] Update EXPECTED_ALL and signature checks in tests/test_api_stability.py"
Task: "T036 [P] [US5] Add AST phase-neutrality & CLI-purity checks in tests/test_library_purity.py"
Task: "T037 [P] [US5] Document PII protection & non-claims in SECURITY.md"
Task: "T038 [P] [US5] Document Stage 4 PII & Gate #2 limits in PRODUCT.md"
Task: "T039 [P] [US5] Document [pii] extra, flags & non-claims in README.md"
Task: "T040 [P] [US5] Update Python API reference in docs/api-reference.md"
Task: "T041 [P] [US5] Update CLI reference in docs/cli-reference.md"
Task: "T042 [P] [US5] Update Phase 1/2 PII architecture in docs/architecture.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (`T001`–`T002`) and Phase 2 Foundational (`T003`–`T009`)
2. Complete Phase 3 User Story 1 (`T010`–`T015`)
3. **STOP and VALIDATE**: Confirm `pytest tests/test_pii_safety.py tests/test_invariants_stage1.py -k "pii or enrich"` verifies zero plaintext PII in chunks/headers and fail-closed batch rollback on `PiiBlockedError`

### Incremental Delivery

1. **Setup + Foundational** (`T001`–`T009`) → Canonical schemas, 7 deterministic recognizers, HMAC tokenization, and shared loopback validator ready
2. **+ US1** (`T010`–`T015`) → Pre-chunking PII scrubbing & transactional ingestion block guarantee (MVP!)
3. **+ US2** (`T016`–`T023`) → `--local-only` network refusal & Phase 2 outbound `guard_egress`
4. **+ US3** (`T024`–`T028`) → DPO zero-raw-PII `.audit.jsonl` trail with `0o700`/`0o600` permissions
5. **+ US4** (`T029`–`T033`) → Multi-language optional `[pii]` Presidio NER & CLI `--local-only`/`--pii-policy`
6. **+ US5 + Polish** (`T034`–`T045`) → Release Gate #2, AST/API gates, honest docs, and full offline CI pass

---

## Notes

- `[P]` marks tasks operating on independent files with satisfied prerequisites
- Every `[USn]` task maps directly to `specs/009-pii-protection/spec.md` User Stories 1–5
- Presidio NER tests in offline suites MUST mock/stub `presidio_*` modules and never trigger runtime `spacy.cli.download`
- `.audit.jsonl`, `PiiDetection`, `PiiBlockedError`, and CLI errors MUST NEVER record or emit matched raw PII plaintext substrings

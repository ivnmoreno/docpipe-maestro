# Implementation Plan: Configurable PII Protection, Egress Guard & Release Gate #2

**Branch**: `009-pii-protection` (git `feat/009-pii-protection`) | **Date**: 2026-11-15 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/009-pii-protection/spec.md`

## Summary

Add configurable PII protection across Phase 1 ingestion (`PiiEnricher` + zero-raw-PII transactional `.audit.jsonl` audit log) and Phase 2 remote generation (`query/egress.py` + `--local-only` enforcement across all model-invoking CLI subcommands), anchored by mandatory **Release Gate #2 (`@pytest.mark.pii`)**. Shared pure policy validation, an extensible `PII_RECOGNIZERS` registry with 7 zero-download stdlib deterministic/checksum recognizers (`EMAIL_ADDRESS`, MOD-97 `IBAN_CODE`, Luhn `CREDIT_CARD`, `US_SSN`, `IP_ADDRESS`, heuristic `PHONE_NUMBER`, MOD-23 `ES_DNI`), an optional offline-safe lazy `[pii]` Presidio NER adapter iterating configured multi-language codes (`["en", "es"]`), and HMAC salted value tokenization (`[ENTITY_hex8]` with cryptographically random process fallback salt) live in phase-neutral `src/docpipe_maestro/_pii.py`. `PiiEnricher` auto-schedules ahead of profile enrichers whenever a `PiiPolicy` is provided (unless explicitly placed in `profile.enrichers`), scrubs both section headings (`section_label`) and bodies (`raw_text` / `clauses`) before chunking/crossref expansion, and aborts batches cleanly with `PiiBlockedError(DocpipeError)` before store or manifest writes while writing owner-only (`0o700`) zero-raw-PII audit logs.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)  
**Primary Dependencies**: Core stdlib only (`re`, `hmac`, `hashlib`, `secrets`, `ipaddress`, `os`, `json`, `urllib.parse`, `contextlib`, `importlib`); optional `[pii]` extra (`presidio-analyzer>=2.2.0`, `presidio-anonymizer>=2.2.0`) loaded lazily with zero automatic downloads  
**Storage**: Append-only JSON-lines audit file `<persist_dir>/manifests/<collection>.audit.jsonl` (POSIX `0o700` directory, `0o600` file permissions) colocated beside collection manifests; existing ChromaDB + SQLite FTS5 store transactions stay untouched on `PiiBlockedError`  
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `pytest -m pii` (Release Gate #2), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests` across Python `3.10–3.13`  
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`; `os.chmod` `0o700`/`0o600` guarded cleanly via `contextlib.suppress(OSError)` for non-POSIX compatibility)  
**Project Type**: Single Python library + CLI package (`src/docpipe_maestro/`, `tests/`, `docs/`)  
**Performance Goals**: Zero startup/import overhead when `pii_policy` / `[pii]` are unused (`0` `presidio_*`/`spacy` imports on CLI startup or standard ingestion/query); linear pre-chunking regex/checksum pass per document section  
**Constraints**: Preserve Principle II phase isolation (`query/` must never import `ingest/`; `_pii.py` must import neither `ingest/` nor `query/`); preserve Principle III (`cli.py` is the only module reading `--pii-policy` / TOML config files); zero raw PII values in exception strings, stdout/stderr, or `.audit.jsonl`; 100% offline test execution across CI  
**Scale/Scope**: Built-in 7 deterministic recognizers + custom `register_pii_recognizer` extensibility + optional multi-language NER; synthetic PII corpus covering ingestion block/redact/tokenize, child context headers, multi-document rollback, DPO audit logs, `--local-only` refusal across 6 CLI commands, and outbound prompt/chat egress checks

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verified against `.specify/memory/constitution.md` (`v1.3.0`, amended `2026-11-15`):

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
|---|---|---|---|
| I. Scope Discipline | Public surface stays minimal: exports `PiiBlockedError`, `PiiPolicy`, and lazy `register_pii_recognizer` cleanly in `docpipe_maestro.__all__` (`33 -> 36`), defines `PiiRecognizer` in `types.py`, appends optional `pii_policy` / `local_only` kwargs, exposes `--local-only` & `--pii-policy` CLI options | PASS | PASS |
| II. Two-Phase Architecture | Shared pure PII core sits in phase-neutral `_pii.py`; locality checks extend shared `embedder/default.py`; Phase 1 lives in `ingest/enricher/pii.py` + `manifest.py`; Phase 2 egress lives read-only in `query/egress.py` (zero `query -> ingest` imports) | PASS | PASS |
| III. Library Purity | `_pii.py`, `ingest/`, and `query/` accept programmatic `PiiPolicy` dicts only and never read JSON/TOML policy files; `--pii-policy` & TOML policy loading live exclusively inside `cli.py` (verified via AST test) | PASS | PASS |
| IV. Search Small, Return Big | `PiiEnricher` scrubs both `ParsedSection.section_label` AND `raw_text`/`clauses` *before* `"crossrefs"` and chunking, guaranteeing redacted/tokenized headings in parent sections, child context headers, and chunk metadata | PASS | PASS |
| V. Exception Preservation & Safety Gates | Preserves Release Gate #1 (`@pytest.mark.reverse`) unmodified and implements mandatory Release Gate #2 (`@pytest.mark.pii`, `tests/test_pii_safety.py`, wired in `pyproject.toml` and `.github/workflows/ci.yml`) | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Built-in recognizers execute 100% offline with zero accounts/downloads; `enforce_local_only` rejects remote providers and non-loopback `api_base` URLs prior to network I/O while permitting loopback OpenAI-compatible endpoints | PASS | PASS |
| VII. Structured Correctness & Privacy/Data | All PII shapes (`PiiBlockedError`, `PiiPolicy`, `PiiDetection`, `PiiAuditRecord`, `IngestContext.pii_policy`) defined canonically in `types.py`; salted value-based HMAC tokens independent of offset; zero-raw-PII `0o700` `.audit.jsonl`; batch block fails before store/manifest commit; optional NER lazily isolated behind `[pii]`; honest docs | PASS | PASS |

**Gate Outcome**: **PASS** (0 Constitution violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/009-pii-protection/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 architectural & security research decisions
├── data-model.md        # Phase 1 types, recognizer taxonomy, token & audit schemas
├── quickstart.md        # Phase 1 offline gates, CLI & DPO audit verification guide
├── contracts/
│   └── pii-protection.md # Phase 1 Python API, CLI, enricher, audit & egress contracts
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
pyproject.toml                                    # Add optional [pii] extra, "pii" pytest marker, mypy overrides for presidio_*
.github/workflows/ci.yml                          # Add mandatory Release Gate #2 step: uv run pytest -m pii -v
src/docpipe_maestro/
├── __init__.py                                   # Export PiiBlockedError, PiiPolicy & lazy register_pii_recognizer in __all__ (33 -> 36)
├── types.py                                      # Add PiiBlockedError, PiiRecognizer, PiiAction, EgressAction, PiiErrorMode, PiiPolicy, PiiDetection, PiiAuditRecord; extend IngestContext
├── _pii.py                                       # NEW phase-neutral PII engine: PII_RECOGNIZERS registry, 7 built-in recognizers, lazy Presidio multi-lang NER adapter, overlap resolution, HMAC tokenization
├── manifest.py                                   # Add audit_log_path() & append_audit_record() with 0o700 dir / 0o600 file perms
├── embedder/
│   ├── __init__.py                               # Re-export is_local_target & enforce_local_only lazily
│   └── default.py                                # Add is_local_target() & enforce_local_only() reusing _is_loopback_host & validate_api_base
├── ingest/
│   ├── enricher/
│   │   ├── __init__.py                           # Register lazy ENRICHERS['pii'] -> PiiEnricher
│   │   └── pii.py                                # NEW PiiEnricher scrubbing headings + body + clauses & collecting per-doc audit summaries
│   └── pipeline.py                               # Add pii_policy / local_only params, auto-schedule "pii" ahead of profile enrichers, buffer/flush .audit.jsonl, transactional block abort + blocked audit log
├── query/
│   ├── egress.py                                 # NEW guard_egress() supporting str & Sequence[Mapping[str, str]] chat payloads + enforce_local_only
│   ├── answer.py                                 # Add pii_policy / local_only kwargs to answer() & answer_detailed(); run guard_egress before has_context/remote completion calls
│   └── retriever.py                              # Add local_only kwarg & preflight enforce_local_only before embedding query
├── eval/
│   └── harness.py                                # Add local_only kwarg & enforce_local_only before fixture evaluation
└── cli.py                                        # Support --local-only / --no-local-only (common + 6 model commands), --pii-policy JSON/TOML file reader (ingest, sync, ask), and TOML defaults

tests/
├── test_pii_safety.py                            # NEW @pytest.mark.pii Release Gate #2 suite (synthetics, checksums, tokens, headers, rollback, audit JSONL, perms, egress, --local-only, multi-lang/mock Presidio)
├── test_api_stability.py                         # Sync EXPECTED_ALL (36 symbols) & updated keyword-only signatures
├── test_library_purity.py                        # Guard query/ vs ingest/ & _pii.py phase neutrality + zero eager presidio/spacy/pii imports
└── test_cli.py                                   # Add CLI tests for --local-only, --pii-policy before/after subcommands, invalid policy/command errors

SECURITY.md                                       # Document PII protection scopes, audit trail, salt config, --local-only, honest non-claims
PRODUCT.md                                        # Document Stage 4 PII & Release Gate #2 capabilities + honest limits
README.md                                         # Document [pii] optional extra, PII protection usage, --local-only, --pii-policy, non-claims
docs/
├── api-reference.md                              # Document PiiBlockedError, PiiPolicy, PiiEnricher, register_pii_recognizer, local_only & egress args
├── cli-reference.md                              # Document --local-only and --pii-policy across CLI commands + examples
└── architecture.md                               # Document Phase 1 PiiEnricher + .audit.jsonl and Phase 2 egress guard flow
```

**Structure Decision**: Isolate pure PII detection, checksum validation, optional lazy NER execution, and salted HMAC tokenization inside phase-neutral `src/docpipe_maestro/_pii.py` while reusing `embedder/default.py`'s existing `_is_loopback_host` and `validate_api_base` helpers for unified Phase 1/2 locality checks. Expose Phase 1 scrubbing through the registry-backed `PiiEnricher`, atomic `.audit.jsonl` persistence via `manifest.py`, Phase 2 outbound protection via `query/egress.py`, and `--pii-policy` file parsing strictly inside `cli.py`.

## Complexity Tracking

No Constitution violations — table intentionally empty.

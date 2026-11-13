# Implementation Plan: Online LLM Answer Customization

**Branch**: `feat/002-online-llm-gateways` (`002-online-llm-customization`) | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from [specs/002-online-llm-customization/spec.md](spec.md)

## Summary

Extend Phase 2 question answering (`answer()`, `build_chat_messages()`, and `docpipe-maestro ask`) to support customizable online LLM providers (Groq serverless, Together.ai, OpenAI, Anthropic, Google Gemini, Mistral, Azure OpenAI, and private OpenAI-compatible gateways) while keeping `ollama/llama3.2` as the zero-config local default and leaving Phase 1 ingestion completely untouched. Add first-class generation parameters (`temperature` with `None`-omission for reasoning models, `max_tokens`, `timeout`, and validated `model_kwargs`), shared role-separated prompt construction (`build_chat_messages()`), CLI `.env` loading via `python-dotenv` (scoped strictly to `cli.py` and `--config` dir / CWD without parent traversal), committed `.env.example` template, TOML/CLI flag parity, loopback-only HTTP validation, dual pattern + active runtime env secret redaction, HTTP 401/403/429 error classification with zero implicit retries (`num_retries=0`), and empty/refusal/blank completion safety.

## Technical Context

**Language/Version**: Python `>=3.10` (validated on Python 3.11)  
**Primary Dependencies**: `litellm>=1.108.0` (unified `provider/model` adapter), `python-dotenv>=1.0.0` (declared explicitly in `pyproject.toml`; `1.2.4` installed with `py.typed`), `chromadb>=1.5.9` (read-only during Phase 2), `tomli>=2.0.0` (Python `<3.11`)  
**Storage**: Read-only access to existing ChromaDB (`persist_dir`) and JSON collection manifest during Phase 2; no schema changes to Phase 1 storage  
**Testing**: `pytest>=8.0.0`, `pytest-cov` (`>=80%` branch coverage), `ruff` (lint/format/bandit `S` rules), `mypy --strict`, `pytest -m reverse` gate, `cz check`  
**Target Platform**: Cross-platform local workstations/servers (Linux/macOS/Windows)  
**Project Type**: Python library + `docpipe-maestro` CLI (`src/` layout via `hatchling` + `hatch-vcs`)  
**Performance Goals**: Pure sub-millisecond `build_chat_messages()` / `build_prompt()`; fail-fast rate limits (`num_retries=0`) and bounded network wait via configurable `timeout` (`120.0s` default); air-gapped startup safety (`LITELLM_LOCAL_MODEL_COST_MAP="true"`)  
**Constraints**: Strict Constitution compliance — no `.env` or TOML reads outside `cli.py`, zero hardcoded provider registries, no secret exposure in errors/causes, local-first offline default unchanged, reserved/duplicate `model_kwargs` keys rejected pre-flight  
**Scale/Scope**: Phase 2 single-turn RAG generation and CLI configuration only (5 existing Python modules updated, `.env.example`, `pyproject.toml`, docs, and targeted unit/CLI/security tests)

## Constitution Check

*GATE: Evaluated before Phase 0 research and re-verified after Phase 1 design.*

| Principle / Constraint | Compliance Status | How Satisfied in Design |
|---|---|---|
| **I. Scope Discipline (NON-NEGOTIABLE)** | PASS | Extends existing `answer()` and exports `build_chat_messages()` alongside `build_prompt()` on the public surface. No session memory, streaming UI, HTTP server, or end-user auth added. |
| **II. Two-Phase Architecture** | PASS | Changes affect strictly Phase 2 (`query/prompts.py`, `query/answer.py`), shared adapter/error hygiene (`embedder.py`), and `cli.py`. Phase 1 `ingest/` modules, chunking, and stored ChromaDB/manifest state remain untouched and read-only. |
| **III. Library Purity** | PASS | Only `cli.py` invokes `load_dotenv()` and `_load_toml_config()`. `answer()`, `build_chat_messages()`, and `embedder.py` accept explicit kwargs and read credentials solely from process environment variables via LiteLLM. No hardcoded provider registry. |
| **IV. Search Small, Return Big (NON-NEGOTIABLE)** | PASS | Retriever child search and parent-section expansion remain unchanged; `build_chat_messages()` consumes the exact deduplicated parent `RetrievedChunk` sequence. |
| **V. Exception Preservation** | PASS | `_SYSTEM_INSTRUCTIONS` and `_format_context_block()` preserve all citation and exception-preservation instructions cleanly across both `build_prompt()` and `build_chat_messages()`; reverse suite continues as mandatory release gate. |
| **VI. Provider Agnosticism & Local-First** | PASS | Out-of-the-box default stays `ollama/llama3.2` with zero credentials or outbound calls. Online providers (Groq, Together.ai, OpenAI, Anthropic, Gemini, Mistral, Azure, private proxies) are purely opt-in via `provider/model` strings and env vars. |
| **VII. Structured Correctness Over Speed** | PASS | Shared `_format_context_block()` helper prevents prompt drift between `build_prompt()` and `build_chat_messages()`; upfront parameter and URL validation fails fast with typed `DocpipeError`/`MissingCredentialError`. |
| **Data, Quality Gates & Footprint** | PASS | `python-dotenv` is lightweight MIT/BSD permissive (already pulled transitively, now declared explicitly); all secrets redacted by regex + active runtime env inspection; CI gates (`ruff`, `ruff --select S`, `mypy`, `pytest -m reverse`, `pytest --cov >= 80%`) remain green. |

**Post-Design Re-Check**: All Phase 0/Phase 1 artifacts ([research.md](research.md), [data-model.md](data-model.md), [contracts/python-api.md](contracts/python-api.md), [contracts/cli.md](contracts/cli.md), [contracts/credentials-env.md](contracts/credentials-env.md), [quickstart.md](quickstart.md)) adhere cleanly to Principles I–VII with zero constitutional exceptions or waivers required.

## Project Structure

### Documentation (this feature)

```text
specs/002-online-llm-customization/
├── plan.md                         # This file (/speckit-plan command output)
├── research.md                     # Phase 0 technical decisions & verified LiteLLM/dotenv facts
├── data-model.md                   # Request entities, TOML config schema, validation & response flows
├── quickstart.md                   # Offline CI validation & optional live provider smoke steps
├── contracts/
│   ├── python-api.md               # Extended answer(), new build_chat_messages(), security & error contracts
│   ├── cli.md                      # .env loading scope, extended ask flags, TOML precedence contract
│   └── credentials-env.md          # .env.example template & supported provider env mapping
├── checklists/
│   └── requirements.md             # Spec quality validation checklist
└── spec.md                         # Feature specification & clarified requirements
```

### Source Code (repository root)

```text
.env.example                        # Tracked credential template (no real secrets)
pyproject.toml                      # Declare explicit python-dotenv>=1.0.0 runtime dependency

src/docpipe_maestro/
├── __init__.py                     # Export build_chat_messages alongside build_prompt and answer
├── embedder.py                     # Broadened _SECRET_PATTERN_RE + active env scrubbing, loopback HTTPS check, HTTP 401/403/429 classification
├── cli.py                          # Startup scoped load_dotenv(), _cfg_opt_int(), ask flags (--temperature, --max-tokens, --timeout, --api-base), build_chat_messages dispatch
└── query/
    ├── prompts.py                  # Shared _format_context_block() + new build_chat_messages()
    └── answer.py                   # Extended answer() kwargs, reserved model_kwargs guard, None omission, num_retries=0, choices/refusal/blank validation

tests/
├── test_prompts_answer.py          # Structured messages, param forwarding, None omission, model_kwargs guard, empty/refusal/blank choice handling
├── test_security_hardening.py      # Loopback vs remote HTTP, gsk_/AIza/Bearer/query/opaque env secret redaction, 401/403/429 handling
└── test_cli.py                     # Scoped .env loading, --temperature/--max-tokens/--timeout flags, CLI > TOML > code precedence

docs/
├── api-reference.md                # Document extended answer() & build_chat_messages()
└── cli-reference.md                # Document .env discovery, ask options & docpipe.toml keys
README.md                           # Quickstart snippets for .env setup, Groq serverless, and Together.ai
```

**Structure Decision**: Extends the existing single-package `src/docpipe_maestro/` layout defined in Feature 001 with zero new runtime subpackages or modules. Security/transport helpers (`embedder.py`), prompt formatting (`query/prompts.py`), generation (`query/answer.py`), and CLI/TOML/dotenv loading (`cli.py`) stay strictly within their constitutional phase and purity boundaries.

## Complexity Tracking

*No Constitution Check violations or waivers required.*

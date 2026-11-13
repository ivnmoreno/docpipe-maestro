---

description: "Executable dependency-ordered task list for Online LLM Answer Customization"
---

# Tasks: Online LLM Answer Customization

**Input**: Design documents from `/specs/002-online-llm-customization/`
**Prerequisites**: `plan.md` (required), `spec.md` (required), `research.md`, `data-model.md`, `contracts/` (`python-api.md`, `cli.md`, `credentials-env.md`), `quickstart.md`

**Tests**: Required per docpipe-maestro Constitution Quality Gates ("Every behavioral change ships with tests") and `quickstart.md` verification gates. Write story tests FIRST and confirm they fail before implementing each story's production code.

**Organization**: Tasks are grouped by user story (`US1`–`US5`) from `spec.md` so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (touches different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to user story (`US1`, `US2`, `US3`, `US4`, `US5`)
- Every task cites exact repository file paths and verbatim constraints from `data-model.md` / `contracts/`

## Path Conventions

Single-package `src/` layout at repository root (`src/docpipe_maestro/`, `tests/`, `docs/`, `pyproject.toml`, `.gitignore`, `.env.example`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Packaging dependencies and Git tracking rules required across online inference features

- [X] T001 Declare explicit runtime dependency `"python-dotenv>=1.0.0"` under `[project].dependencies` in `pyproject.toml`
- [X] T002 [P] Add negation rule `!.env.example` directly below `*.env.*` ignore rules in `.gitignore` so `.env.example` is trackable while `.env`, `*.env`, `*.env.*`, `.env.local`, `.env.production`, and `.env.development` remain ignored

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Baseline green check and shared pure prompt-formatting helper shared by prompt builders

**⚠️ CRITICAL**: No user story work begins until Phase 2 is complete

- [X] T003 Verify clean baseline test and static analysis status via `uv run pytest -q`, `uv run ruff check .`, and `uv run mypy src tests` configured by `pyproject.toml`
- [X] T004 Extract shared `_format_context_block(sections: Sequence[RetrievedChunk]) -> str` helper (zero I/O, preserving `[1] Source: ... | Section: ...` plus optional `Clause`/`Page` headers and `---` separators) used by `build_prompt()` in `src/docpipe_maestro/query/prompts.py`

**Checkpoint**: Foundation ready — user story implementation can proceed

---

## Phase 3: User Story 1 - Selecting and Tuning Online LLM Providers (Priority: P1) 🎯 MVP

**Goal**: Allow callers to target cloud or private LLM providers with first-class generation controls (`temperature`, `max_tokens`, `timeout`, `model_kwargs`), omitting unset optional parameters (reasoning model safety), forwarding `0.0`, failing fast on rate limits (`num_retries=0`), and rejecting reserved/duplicate `model_kwargs` keys while preserving local defaults (`ollama/llama3.2`) and empty-context short-circuiting.

**Independent Test**: Run `uv run pytest tests/test_prompts_answer.py -v` verifying mocked `litellm.completion` calls honor `temperature=0.0`, `max_tokens`, `timeout`, `model_kwargs`, `num_retries=0`, omit `temperature`/`max_tokens` when `None`, reject reserved/invalid values, and leave default local execution intact.

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T005 [US1] Add unit tests in `tests/test_prompts_answer.py` verifying `answer()` forwards explicit `temperature=0.0`, `max_tokens` (`int >= 1`), `timeout` (`float > 0.0`, default `120.0`), valid `model_kwargs` (`top_p`, `frequency_penalty`), and `num_retries=0`, while omitting `"temperature"` and `"max_tokens"` completely when `None`
- [X] T006 [US1] Add upfront validation tests in `tests/test_prompts_answer.py` asserting `answer()` raises `DocpipeError` for boolean/non-finite/negative `temperature` (`< 0.0`), boolean/non-`int`/`< 1` `max_tokens`, boolean/non-finite/`<= 0.0` `timeout`, and any reserved or conflicting key (`model`, `messages`, `prompt`, `api_base`, `base_url`, `api_key`, `temperature`, `max_tokens`, `timeout`, `num_retries`) in `model_kwargs`

### Implementation for User Story 1

- [X] T007 [US1] Implement `_RESERVED_MODEL_KWARGS` (`frozenset` of `model`, `messages`, `prompt`, `api_base`, `base_url`, `api_key`, `temperature`, `max_tokens`, `timeout`, `num_retries`) and `_validate_generation_params()` enforcing finite `timeout > 0.0` (not `bool`), `temperature is None` or finite `>= 0.0` (not `bool`), and `max_tokens is None` or `int >= 1` (not `bool`) in `src/docpipe_maestro/query/answer.py`
- [X] T008 [US1] Extend `answer()` signature with `temperature: float | None = None`, `max_tokens: int | None = None`, `timeout: float = DEFAULT_REQUEST_TIMEOUT`, and `model_kwargs: Mapping[str, Any] | None = None`, conditionally add `"temperature"` and `"max_tokens"` only when `is not None` (preserving `0.0`), unpack validated `model_kwargs`, and pass `num_retries=0` to `litellm.completion()` in `src/docpipe_maestro/query/answer.py`

**Checkpoint**: User Story 1 is fully implemented and independently testable via `tests/test_prompts_answer.py` (MVP!)

---

## Phase 4: User Story 2 - Local Credential Management via Environment File (Priority: P1)

**Goal**: Provide a tracked `.env.example` template and scoped `.env` loading at CLI startup (`Path(config).parent / ".env"` if `--config` is passed, or `Path.cwd() / ".env"` otherwise, no upward traversal, `override=False`), keeping core library modules strictly decoupled from config and `.env` files.

**Independent Test**: Run `uv run pytest tests/test_cli.py -v` verifying isolated CWD and `--config` directory `.env` resolution, zero parent traversal, shell env precedence, missing `.env` tolerance, `.gitignore` status for `.env` vs `.env.example`, and pure env-only behavior in `answer()`.

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T009 [P] [US2] Add CLI credential discovery tests in `tests/test_cli.py` verifying `.env` loads from `Path(config).parent / ".env"` when `--config` is set or `Path.cwd() / ".env"` otherwise, never walks upward into ancestor directories, ignores missing `.env` files silently, preserves pre-set shell environment variables (`override=False`), and confirms `.env.example` parses with non-live placeholder values only
- [X] T010 [P] [US2] Verify `.gitignore` excludes `.env` and permits `.env.example` creation without live secrets by adding repository template check in `tests/test_cli.py` or alongside T009 before implementation

### Implementation for User Story 2

- [X] T011 [P] [US2] Create tracked `.env.example` at repository root containing placeholder keys (zero live secrets) for `GROQ_API_KEY`, `TOGETHERAI_API_KEY` (with note on `TOGETHER_API_KEY` alias), `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, `LITELLM_LOCAL_MODEL_COST_MAP="true"`, and `chmod 600 .env` security guidance in `.env.example`
- [X] T012 [US2] Implement `_load_cli_dotenv(config_path: str | None) -> None` resolving `(Path(config_path).parent if config_path else Path.cwd()) / ".env"` and calling `load_dotenv(dotenv_path=env_path, override=False)` only when `env_path.is_file()` at the top of `main()` before `_load_toml_config()` in `src/docpipe_maestro/cli.py`

**Checkpoint**: User Stories 1 AND 2 work independently and securely without leaking credentials to Git

---

## Phase 5: User Story 3 - Transport Security, Secret Redaction, and Provider Resilience (Priority: P1)

**Goal**: Require HTTPS for remote custom endpoints while permitting local loopback HTTP (`localhost`, `127.0.0.0/8`, `::1`), scrub both regex secret patterns and exact loaded environment secret values (covering opaque Together.ai / Azure keys), classify HTTP 401/403 vs fail-fast HTTP 429 errors, and handle empty `choices`, populated `message.refusal`, or `None`/whitespace-only completion content safely.

**Independent Test**: Run `uv run pytest tests/test_security_hardening.py tests/test_prompts_answer.py -v` verifying pre-flight rejection of remote HTTP, acceptance of loopback HTTP, redaction across all key patterns and loaded env keys, 401/403 vs 429 classification, and guarded `DocpipeError` on moderated/refused/blank responses.

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T013 [P] [US3] Add transport security, secret redaction, and HTTP 401/403/429 tests in `tests/test_security_hardening.py` verifying `http://localhost`, `http://127.0.0.1`, and `http://[::1]:8000` are permitted while `http://api.example.com/v1` raises `DocpipeError("Insecure remote api_base URL: must use https:// for external endpoints")`, redaction covers `gsk_...`, `AIza...`, `Bearer ...`, `?key=`/`?api_key=`/`?token=`, and opaque bare env secrets (`TOGETHERAI_API_KEY`, `AZURE_API_KEY`), `401`/`403`/`PermissionDeniedError` raises `MissingCredentialError`, and `429`/`RateLimitError` raises sanitized `DocpipeError` matching `"Rate limit or quota exceeded (HTTP 429)"`
- [X] T014 [P] [US3] Add completion moderation and empty-content safety tests in `tests/test_prompts_answer.py` asserting `answer()` raises descriptive `DocpipeError` (instead of `IndexError` or `""`) when mocked `litellm.completion` returns `choices=[]`, non-empty `message.refusal`, or `message.content` that is `None` or whitespace-only (while still handling `SimpleNamespace` responses omitting `refusal`)

### Implementation for User Story 3

- [X] T015 [P] [US3] Update `validate_api_base()` using stdlib `ipaddress.ip_address(host).is_loopback` and `"localhost"` check to permit loopback `http://` and raise `DocpipeError("Insecure remote api_base URL: must use https:// for external endpoints")` on remote `http://` URLs in `src/docpipe_maestro/embedder.py`
- [X] T016 [US3] Broaden `_SECRET_PATTERN_RE` (`://user:pass@`, `sk-`, `gsk_`, `AIza`, `Bearer`, `[?&](?:api[_-]?key|key|token)=[^&\s]+`), add `_active_env_secrets()` helper checking loaded `*_API_KEY`/`*_TOKEN`/`*_SECRET` (`len >= 8`) values, extend `_is_auth_error()` for `401`/`403`/`PermissionDeniedError`, and emit sanitized `"Rate limit or quota exceeded (HTTP 429)"` errors in `raise_litellm_error()` in `src/docpipe_maestro/embedder.py`
- [X] T017 [P] [US3] Add `_extract_completion_text(response, model)` helper verifying non-empty `choices`, checking dict/object `refusal` safely via `_item_field` / `getattr(msg, "refusal", None)`, raising `DocpipeError` when empty/`refusal`/null/blank, and returning stripped answer text in `src/docpipe_maestro/query/answer.py`

**Checkpoint**: User Stories 1, 2, AND 3 pass all P1 security, credential, and generation safety criteria

---

## Phase 6: User Story 4 - Role-Separated Prompt Structuring (Priority: P2)

**Goal**: Provide `build_chat_messages(question, sections)` separating `_SYSTEM_INSTRUCTIONS` (`system` role) from retrieved context + user question (`user` role) using the shared `_format_context_block()` helper, export it cleanly on `docpipe_maestro`, and extend `answer()` to accept either `str` or validated role/content message sequences.

**Independent Test**: Run `uv run pytest tests/test_prompts_answer.py -v` confirming `docpipe_maestro.build_chat_messages()` returns a 2-message list isolating instructions from untrusted context, works with empty sections, and integrates smoothly with `answer()` while preserving legacy `build_prompt()` and `answer(str)` behavior.

### Tests for User Story 4 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T018 [US4] Add ChatML prompt structure and message-input tests in `tests/test_prompts_answer.py` verifying top-level `build_chat_messages()` returns `[{"role": "system", ...}, {"role": "user", ...}]` separating `_SYSTEM_INSTRUCTIONS` from context/question (including empty sections), `answer()` forwards message sequences directly to `litellm.completion(messages=...)`, retains `str` compatibility, and raises `DocpipeError` on empty or malformed message sequences

### Implementation for User Story 4

- [X] T019 [P] [US4] Implement `build_chat_messages(question: str, sections: Sequence[RetrievedChunk]) -> list[dict[str, str]]` sharing `_SYSTEM_INSTRUCTIONS` and `_format_context_block(sections)` (zero I/O, zero side effects) in `src/docpipe_maestro/query/prompts.py`
- [X] T020 [US4] Re-export `build_chat_messages` alongside `build_prompt` and add `"build_chat_messages"` alphabetically to `__all__` in `src/docpipe_maestro/__init__.py`
- [X] T021 [US4] Update `answer()` parameter annotation to `prompt: str | Sequence[Mapping[str, str]]` and add `_normalize_messages()` validating non-empty sequences with non-empty `str` `"role"` and `str` `"content"` entries in `src/docpipe_maestro/query/answer.py`

**Checkpoint**: User Story 4 works independently across both plain-string callers and structured role-separated callers

---

## Phase 7: User Story 5 - CLI and Project Configuration Parity with Strict Precedence (Priority: P2)

**Goal**: Expose full CLI (`--api-base`, `--temperature`, `--max-tokens`, `--timeout`) and `docpipe.toml` configuration parity on `docpipe-maestro ask` enforcing `CLI flags > TOML defaults > built-in defaults` precedence, validating malformed TOML types cleanly, and dispatching `ask` prompts via `build_chat_messages()`.

**Independent Test**: Run `uv run pytest tests/test_cli.py -v` verifying TOML defaults (`api_base`, `temperature`, `max_tokens`, `timeout`), CLI overrides (`--temperature 0.0` overriding TOML `0.5`), invalid TOML type errors (exit code `1`), and `ask` forwarding structured `build_chat_messages()` output to `answer()`.

### Tests for User Story 5 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T022 [US5] Add CLI flag & TOML parity precedence tests in `tests/test_cli.py` verifying `docpipe.toml` keys (`api_base`, `temperature`, `max_tokens`, `timeout`) apply as defaults, CLI `--temperature`, `--max-tokens`, `--timeout`, and `--api-base` flags override TOML values, invalid TOML types (such as `bool` for `max_tokens`/`temperature`/`timeout` or non-string `api_base`) fail cleanly with exit code `1`, and `ask` constructs role-separated messages via `build_chat_messages()`

### Implementation for User Story 5

- [X] T023 [US5] Add `_cfg_opt_str()` and `_cfg_opt_int()` helpers (rejecting `bool` and unexpected TOML types with `DocpipeError("Invalid TOML config value for ...")`) in `src/docpipe_maestro/cli.py`
- [X] T024 [US5] Extend `build_parser()` to load `api_base`, `temperature`, `max_tokens`, and `timeout` (defaulting to `DEFAULT_REQUEST_TIMEOUT` = `120.0`) from `cfg_defaults` and register `--temperature` (`float`), `--max-tokens` (`int`), and `--timeout` (`float`) options on `p_ask` in `src/docpipe_maestro/cli.py`
- [X] T025 [US5] Import `build_chat_messages` and update `args.command == "ask"` handler to pass `build_chat_messages(args.question, sections)`, `temperature=args.temperature`, `max_tokens=args.max_tokens`, `timeout=args.timeout`, and `api_base=args.api_base` to `answer()` in `src/docpipe_maestro/cli.py`

**Checkpoint**: All 5 user stories (P1 and P2) are independently complete and verified end-to-end

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Align user documentation with new contracts and pass all CI & quickstart gates

- [X] T026 [P] Update `docs/api-reference.md` with `build_chat_messages()`, extended `answer()` parameters (`temperature`, `max_tokens`, `timeout`, `model_kwargs`), reserved `model_kwargs` rules, Groq/Together.ai Python examples, and HTTP 429/moderation error documentation
- [X] T027 [P] Update `docs/cli-reference.md` with `.env` scoped startup discovery rules, extended `docpipe-maestro ask` flags (`--temperature`, `--max-tokens`, `--timeout`), `docpipe.toml` generation keys, and strict precedence order
- [X] T028 [P] Update `README.md` with `.env` + `chmod 600 .env` setup quickstart, Groq serverless and Together.ai examples, and air-gapped safety guidance
- [X] T029 Run full offline verification suite per `specs/002-online-llm-customization/quickstart.md`: `uv run ruff format --check .`, `uv run ruff check .`, `uv run ruff check --select S src/`, `uv run mypy src tests`, `uv run pytest -m reverse -v`, `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov` (`>=80%` branch coverage), and verify `git check-ignore .env` passes while `.env.example` stays untracked-ready (`!ignored`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** (`T001`–`T002`): No dependencies; start immediately.
- **Phase 2 (Foundational)** (`T003`–`T004`): Depends on Phase 1; `T004` (`_format_context_block` helper) prepares clean shared prompt formatting.
- **Phase 3 (US1, P1)** (`T005`–`T008`): Depends on Phase 2 completion; delivers core MVP online provider tuning & parameter omission safety.
- **Phase 4 (US2, P1)** (`T009`–`T012`): Depends on Phase 1 (`python-dotenv` + `!.env.example`) & Phase 2 (`T003`). Independent of US1.
- **Phase 5 (US3, P1)** (`T013`–`T017`): `embedder.py` tasks (`T015`–`T016`) depend on Phase 2; `answer.py` completion-response guardrail (`T017`) follows `T008` in US1 so both compose cleanly without `answer.py` merge conflicts.
- **Phase 6 (US4, P2)** (`T018`–`T021`): `prompts.py` + `__init__.py` (`T019`–`T020`) depend on `T004`; `answer.py` message normalization (`T021`) follows `T017`.
- **Phase 7 (US5, P2)** (`T022`–`T025`): Depends on US1 (`answer()` params `T008`), US2 (`cli.py` startup `.env` `T012`), and US4 (`build_chat_messages` `T019`–`T020`) to wire CLI flags, TOML defaults, and ChatML dispatch together cleanly.
- **Phase 8 (Polish)** (`T026`–`T029`): Depends on completion of all implementation stories (`T001`–`T025`).

### Parallel Opportunities

- Phase 1: `T001` (`pyproject.toml`) and `T002` (`.gitignore`) run in parallel.
- Phase 4 (US2): `T009` (`tests/test_cli.py`) and `T011` (`.env.example`) touch distinct files and run in parallel.
- Phase 5 (US3): `T013` (`tests/test_security_hardening.py`), `T014` (`tests/test_prompts_answer.py`), `T015` (`embedder.py`), and `T017` (`answer.py`, after `T008`) touch distinct files across test/source boundaries.
- Across Stories after Phase 2: US2 (`T009`–`T012`), US3 `embedder.py` (`T013`, `T015`–`T016`), and US4 `prompts.py`/`__init__.py` (`T019`–`T020`) can proceed in parallel with zero file overlap.
- Phase 8 (Polish): `T026`, `T027`, and `T028` modify separate Markdown docs (`docs/api-reference.md`, `docs/cli-reference.md`, `README.md`) in parallel before final gate check `T029`.

---

## Parallel Example: User Story 1 vs User Story 2 & 3

```bash
# After Phase 2 (T003-T004) completes, run across non-overlapping files:
Task T005: "Add US1 parameter forwarding & None omission tests in tests/test_prompts_answer.py"
Task T009: "Add US2 scoped .env & template checks in tests/test_cli.py"
Task T011: "Create .env.example template at repository root"
Task T013: "Add US3 loopback HTTPS, secret redaction & 401/403/429 tests in tests/test_security_hardening.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (`T001`–`T002`) and Phase 2 (`T003`–`T004`).
2. Complete Phase 3 / US1 (`T005`–`T008`) for programmatic `answer()` customization (`temperature`, `max_tokens`, `timeout`, `model_kwargs`, `num_retries=0`, `None`-omission for reasoning models).
3. Validate `tests/test_prompts_answer.py` before adding `.env` loading, security hardening, ChatML prompts, and CLI parity.

### Incremental Delivery

1. Setup + Foundation (`T001`–`T004`) → clean baseline + shared context formatter.
2. Add US1 (`T005`–`T008`) → customizable online inference (MVP).
3. Add US2 (`T009`–`T012`) → `.env.example` + safe scoped `.env` loading at CLI startup.
4. Add US3 (`T013`–`T017`) → loopback-only HTTP validation, broad + runtime secret scrubbing, HTTP 429 fail-fast, and moderation/refusal safety.
5. Add US4 (`T018`–`T021`) → role-separated `build_chat_messages()` + backward-compatible `answer()` input handling.
6. Add US5 (`T022`–`T025`) → full CLI `--temperature`/`--max-tokens`/`--timeout` & `docpipe.toml` parity.
7. Complete Polish & CI verification (`T026`–`T029`) before opening PR from `feat/002-online-llm-gateways`.

---

## Notes

- Zero Phase 1 files (`src/docpipe_maestro/ingest/`, `store.py`, `manifest.py`) or retrieval (`query/retriever.py`) are modified.
- Note on `.gitignore`: line 69 (`*.env.*`) currently matches `.env.example`; `T002` explicitly fixes this with `!.env.example` before `.env.example` is staged.
- All automated verification uses `mock_litellm_offline` / monkeypatched doubles (`LITELLM_LOCAL_MODEL_COST_MAP=true`) with zero live network calls in CI.

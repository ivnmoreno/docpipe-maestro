---

description: "Actionable, dependency-ordered task list for Stage 0 Baseline Housekeeping and Alignment"
---

# Tasks: Baseline Housekeeping and Alignment

**Input**: Design documents from `/specs/003-baseline-housekeeping/`

**Prerequisites**: [plan.md](plan.md) (required), [spec.md](spec.md) (required for user stories), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Constitution Check**: Verified compliant with Principles I–VII and Governance rules in [plan.md](plan.md#L28-L43) prior to implementation.

**Tests**: Included for the new `docpipe-maestro query --json` CLI contract (`User Story 2` and constitution Quality Gates requirement) and the broken `Product.md` path in `tests/test_extended_complex.py` (`User Story 1`), plus baseline packaging and CI/Release Gate #1 verification (`User Story 3`).

**Organization**: Tasks are grouped by user story (`[US1]`, `[US2]`, `[US3]`) so each slice can be implemented and validated cleanly and incrementally.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story mapping (`[US1]`, `[US2]`, `[US3]`) — omitted on Setup, Foundational, and Polish phases
- Exact file paths included in every task description

---

## Phase 1: Setup (Shared Prerequisites)

**Purpose**: Ensure branch, toolchain, and the canonical `PRODUCT.md` git rename are cleanly staged before parallel documentation and code edits begin.

- [X] T001 Verify active git branch (`chore/003-baseline-housekeeping`) and synced dev environment (`.venv/bin/pytest`, `ruff`, `mypy`, `build`, `twine`) in `/home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro`
- [X] T002 Stage the working-tree rename `Product.md` → `PRODUCT.md` cleanly in the git index (`PRODUCT.md`) so all subsequent edits operate on the canonical tracked uppercase file

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Capture verified ground-truth package exports and baseline tool health before modifying docs, constitution, packaging, or CLI code.

**⚠️ CRITICAL**: Complete before User Story work begins so documentation reconciliation and packaging verification reference exact verified symbols and module paths.

- [X] T003 Confirm PEP 561 marker presence (`src/docpipe_maestro/py.typed`) and verify baseline static checks (`uv run ruff check .` and `uv run mypy src tests`) pass before edits
- [X] T004 [P] Inspect and confirm the 24 exported symbols in `__all__` from `src/docpipe_maestro/__init__.py` and active module layout under `src/docpipe_maestro/` (`ingest/`, `query/`, root modules)

**Checkpoint**: Canonical `PRODUCT.md` rename staged and ground-truth export/module inventory verified. User Stories 1, 2, and 3 can now execute.

---

## Phase 3: User Story 1 — Consistent Governance, Product Documentation, and Filename Baseline (Priority: P1) 🎯 MVP

**Goal**: Eliminate stale `Product.md` links/references, reconcile `PRODUCT.md` (§7.3, §7.5, §14.3, §16, §18, §20.1), amend `.specify/memory/constitution.md` to `v1.2.0`, disclose heuristic PDF clause detection in `README.md`, and fix `tests/test_extended_complex.py`.

**Independent Test**: Zero `Product.md` matches across active repository files; all internal markdown links resolve cleanly; `PRODUCT.md` §7.5 lists all 24 exports in `__all__` and §20.1 maps `ingest/` + `query/`; `.specify/memory/constitution.md` reflects `v1.2.0`; `uv run pytest tests/test_extended_complex.py -v` passes.

### Implementation for User Story 1

- [X] T005 [P] [US1] Amend `.specify/memory/constitution.md` from `1.1.0` to `Version: 1.2.0` (`Last Amended: 2026-11-13`): update the top Sync Impact Report Amendment Log (`Version change: 1.1.0 -> 1.2.0`, `Rationale:`, `Migration Note:` confirming zero breaking runtime changes, modified principles/sections, and `Follow-up TODOs:` noting Stage 4 `@pytest.mark.pii` implementation); clarify Principle I (`Scope Discipline`) that "minimal" constrains feature surface and scope promise, not engineering rigor; designate `@pytest.mark.reverse` as mandatory **Release Gate #1** and reserve **Release Gate #2** for future PII safety in Principle V and `Quality Gates`; sync the `Quality Gates` public API contract sentence to cover all shipped callables (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, optional `answer`, `answer_detailed`), shared/result shapes, and `DocpipeError` hierarchy; and replace the obsolete `"generation is an optional extra, not a core dependency"` line in `Footprint` while retaining the `16 GB RAM with no GPU` local target and additive extensibility rules
- [X] T006 [P] [US1] Reconcile `PRODUCT.md`: update §7.3 (`Phase 2 — Optional Generation`) to remove *"not part of the core install"* and state generation is optional to invoke while provider client support ships in core dependencies; update §7.5 (`Public Library API`) to remove `(optional extra)` from `answer` and catalog all 24 symbols from `src/docpipe_maestro/__init__.py` `__all__` (`ingest`, `sync`, `remove`, `status`, `reindex`, `retrieve`, `build_prompt`, `build_chat_messages`, `answer`, `answer_detailed`, `Chunk`, `EmbeddedChunk`, `RetrievedChunk`, `SourceRecord`, `IngestResult`, `SyncResult`, `CollectionStatus`, `GenerationResult`, `DocpipeError`, `UnsupportedFormatError`, `MissingExtraError`, `ModelMismatchError`, `MissingCredentialError`, `__version__`); align §14.3, §16 row `10`, and §18 item `19` to remove contradictory `"optional generation extra"` wording; and update §20.1 (`Module Responsibilities`) to list `__init__.py`, `__main__.py`, `types.py`, `config.py`, `manifest.py`, `embedder.py`, `store.py`, `cli.py`, `ingest/{intake,clean,crossrefs,chunker,pipeline}.py`, and `query/{retriever,prompts,answer}.py`
- [X] T007 [P] [US1] Update `README.md`: explicitly note in `### 5. Chunking Profiles` (`POLICY` profile row for **Clause Preservation** plus a concise note beneath the table) that PDF clause boundary detection relies on extracted-text heuristics rather than guaranteed structural PDF parsing, and update `Product.md` → `PRODUCT.md` in `## Repository Structure`
- [X] T008 [P] [US1] Update `[Product Description](../Product.md)` → `[Product Description](../PRODUCT.md)` in `docs/README.md`
- [X] T009 [P] [US1] Update `` `Product.md` `` → `` `PRODUCT.md` `` in `docs/future-features.md`
- [X] T010 [P] [US1] Update the docstring and file path in `tests/test_extended_complex.py` (`REPO_ROOT / "Product.md"` → `REPO_ROOT / "PRODUCT.md"` and `corpus / "PRODUCT.md"`)
- [X] T011 [US1] Validate User Story 1 deliverables independently by running `uv run pytest tests/test_extended_complex.py -v`, checking zero `Product.md` occurrences across US1 doc/test files (`README.md`, `PRODUCT.md`, `docs/`, `tests/`), verifying relative markdown links, and running `specs/003-baseline-housekeeping/quickstart.md` §2 (`24`-symbol parity and `.specify/memory/constitution.md` `v1.2.0` checks; full-repo grep including `pyproject.toml` runs at `T021` after `T018`) (depends on T005–T010)

**Checkpoint**: User Story 1 (MVP) is complete and independently verified — docs, constitution `v1.2.0`, filenames, and integration corpus fixtures align with reality.

---

## Phase 4: User Story 2 — Machine-Readable Retrieval Output from CLI `query` (Priority: P1)

**Goal**: Support `docpipe-maestro query "<question>" --json` emitting the structured JSON wrapper object `{"query", "collection", "expand_parent", "results"}` with `id`, `parent_id`, `score`, `text`, and `metadata` per item, document it in `docs/cli-reference.md` and `README.md`, and keep default text mode and error behavior intact.

**Independent Test**: Run `uv run pytest tests/test_cli.py -v -k "query"` proving parent-expanded JSON, `--no-expand-parent` raw child JSON, zero-match `results: []`, global option placement parity, `stderr` error exit `1` behavior, and unchanged non-JSON text formatting.

### Tests for User Story 2 (TDD First ⚠️)

> **NOTE**: Add these assertions first and confirm they fail before updating `src/docpipe_maestro/cli.py`.

- [X] T012 [US2] Add failing CLI tests in `tests/test_cli.py` exercising `docpipe-maestro query` per `specs/003-baseline-housekeeping/contracts/cli-query-json.md`: (1) populated `--json` returns valid JSON with top-level `"query"` (`string`), `"collection"` (`string`), `"expand_parent"` (`true`), and `"results"` (`array` of objects containing 16-char hex `"id"`, `"parent_id": null`, numeric `"score"` in `[0.0, 1.0]`, `"text"`, and `"metadata"` with `type="parent"`, `clause: null | str`, `page: null | int`); (2) `--no-expand-parent --json` sets `"expand_parent": false` and returns non-empty string `"parent_id"` with `metadata.type == "child"`; (3) zero matches via empty collection or high `--threshold` with `--json` emit `"results": []` with exit code `0` and zero plain-text prose on `stdout`; (4) global flags (`--config`, `--no-config`, `--collection`, `--persist-dir`) before or after `query` (including `--config` TOML overrides) produce matching JSON output; (5) invalid `--threshold` or `ModelMismatchError` with `--json` emits single-line `Error: ...` on `stderr`, leaves `stdout` empty, and returns `1`; and (6) omitting `--json` preserves existing console formatting

### Implementation for User Story 2

- [X] T013 [US2] Add `--json` (`action="store_true"`, `dest="as_json"`, `default=False`) argument to `p_query` subparser in `src/docpipe_maestro/cli.py` (depends on T012)
- [X] T014 [US2] Update the `args.command == "query"` handler in `main()` in `src/docpipe_maestro/cli.py` so when `args.as_json` is `True` it prints `json.dumps({"query": args.question, "collection": args.collection, "expand_parent": args.expand_parent, "results": [{"id": item.id, "parent_id": item.parent_id, "score": float(item.score), "text": item.text, "metadata": dict(item.metadata)} for item in results]}, indent=2)` and returns `0` (emitting `"results": []` when `results` is empty, preserving full float `score` fidelity and `null` nullable `parent_id`/`clause`/`page`, keeping validation/runtime exceptions routed through existing `stderr` + exit `1` handler, and leaving non-`--json` output unchanged) (depends on T013)
- [X] T015 [P] [US2] Document `[--json]` in `### docpipe-maestro query "<question>"` in `docs/cli-reference.md`: add `--json` to synopsis and option descriptions, provide annotated JSON output example covering `"query"`, `"collection"`, `"expand_parent"`, and `"results"` (`id`, `parent_id`, `score`, `text`, `metadata`), and note `--no-expand-parent`, empty `"results": []` (`exit 0`), and `Error: ...` on `stderr` (`exit 1`) behavior
- [X] T016 [US2] Add `--json` usage example to `### 6. Semantic Search Without an LLM` in `README.md` (sequenced after T007 so both `README.md` edits compose cleanly)
- [X] T017 [US2] Run `uv run pytest tests/test_cli.py -v` and confirm all new `query --json` tests and existing `ask`/`status`/CLI regression tests pass cleanly (depends on T014)

**Checkpoint**: User Story 2 is complete and independently verified — `docpipe-maestro query --json` matches `contracts/cli-query-json.md` cleanly.

---

## Phase 5: User Story 3 — Reliable Packaging Baseline and Zero-Regression Quality Gates (Priority: P2)

**Goal**: Update source-distribution inclusion in `pyproject.toml` without disturbing dependencies, URLs, or tool configs, build and verify `sdist` + `wheel` archives, and confirm all CI and Release Gate #1 checks pass cleanly.

**Independent Test**: `python -m build` and `twine check dist/*` succeed with zero warnings; `sdist` includes `PRODUCT.md`, `.specify/memory/constitution.md`, and `docs/` (zero `Product.md`); `wheel` includes `docpipe_maestro/py.typed`; all lint, security, strict typing, reverse gate, and coverage checks exit `0`.

### Implementation & Verification for User Story 3

- [X] T018 [US3] Update `[tool.hatch.build.targets.sdist].include` line in `pyproject.toml` from `"Product.md"` to `"PRODUCT.md"`, leaving core `dependencies`, `optional-dependencies`, `[project.urls]`, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, and `[tool.coverage.*]` untouched
- [X] T019 [US3] Build distributions (`rm -rf dist/ && uv run python -m build`) and validate package metadata & contents (`uv run twine check dist/*`, `tar -tzf dist/docpipe_maestro-*.tar.gz`, `unzip -l dist/docpipe_maestro-*.whl`) confirming presence of `PRODUCT.md`, `.specify/memory/constitution.md`, `docs/`, and `docpipe_maestro/py.typed` with zero `Product.md` entries (depends on T005, T006, T018)
- [X] T020 [US3] Run the complete quality and safety verification suite after all edits (`uv run ruff format --check .`, `uv run ruff check .`, `uv run ruff check --select S src/`, `uv run mypy src tests`, `uv run pytest -m reverse -v`, `uv run pytest -v --cov` confirming `>= 80%` branch coverage) (depends on T011, T017, T018)

**Checkpoint**: Packaging builds cleanly and all quality/safety gates pass with zero regressions.

---

## Phase 6: Polish & Cross-Cutting Validation

**Purpose**: Final cross-repository consistency audit, cleanup of temporary build output, and readiness check before commit.

- [X] T021 Execute the full end-to-end verification script from `specs/003-baseline-housekeeping/quickstart.md` confirming 0 `Product.md` stale occurrences across active files, 0 broken relative markdown links across `README.md`, `PRODUCT.md`, `.specify/memory/constitution.md`, and `docs/`, `24/24` public exports parity, and constitution `v1.2.0` compliance
- [X] T022 Remove transient build artifacts (`rm -rf dist/ build/`) if untracked cleanly and inspect `git status` and `git diff` across the workspace to verify only Stage 0 baseline alignment files are modified

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1: T001–T002)**: Immediate start; stages the `Product.md` → `PRODUCT.md` rename so edits operate on the canonical tracked file.
- **Foundational (Phase 2: T003–T004)**: Depends on Setup; verifies baseline tooling health, `py.typed`, and canonical 24-symbol `__all__` inventory.
- **User Story 1 (Phase 3: T005–T011)**: Depends on Phase 2; establishes consistent docs, constitution `v1.2.0`, filename links, and test fixture path.
- **User Story 2 (Phase 4: T012–T017)**: Depends on Phase 2 (`T012`–`T015` can run completely in parallel with US1; `T016` sequences cleanly after `T007` since both touch `README.md`).
- **User Story 3 (Phase 5: T018–T020)**: `T018` (`pyproject.toml`) can run immediately after Phase 2; `T019` (`build` + archive inspection) and `T020` (full quality/safety suite) run once US1 and US2 edits are complete.
- **Polish (Phase 6: T021–T022)**: Final check after all User Stories pass.

### User Story Independence

- **User Story 1 (P1)**: Independent docs/constitution/fixture consistency slice — forms the standalone MVP documentation & governance baseline.
- **User Story 2 (P1)**: Independent CLI JSON output slice — touches only `src/docpipe_maestro/cli.py`, `tests/test_cli.py`, `docs/cli-reference.md`, and §6 of `README.md`.
- **User Story 3 (P2)**: Packaging manifest + release-gate verification slice — validates `pyproject.toml`, built archives, and CI gates across the finished baseline.

### Parallel Opportunities

- After Phase 2 completes:
  - Within **US1**: `T005` (`.specify/memory/constitution.md`), `T006` (`PRODUCT.md`), `T007` (`README.md`), `T008` (`docs/README.md`), `T009` (`docs/future-features.md`), and `T010` (`tests/test_extended_complex.py`) touch 6 separate files and can run concurrently!
  - Across **US1 / US2 / US3**: `T012` (`tests/test_cli.py`), `T015` (`docs/cli-reference.md`), and `T018` (`pyproject.toml`) touch distinct files from all `US1` tasks and can run concurrently while `US1` tasks run!

---

## Parallel Example: Maximum Concurrency After Foundational

```bash
# Launch parallel User Story 1, User Story 2 (docs/tests), and User Story 3 (pyproject) edits simultaneously:
Task: "T005 [P] [US1] Amend .specify/memory/constitution.md to v1.2.0"
Task: "T006 [P] [US1] Reconcile PRODUCT.md (§7.3, §7.5, §14.3, §16, §18, §20.1)"
Task: "T007 [P] [US1] Update README.md POLICY heuristic note & Repository Structure"
Task: "T008 [P] [US1] Fix PRODUCT.md link in docs/README.md"
Task: "T009 [P] [US1] Fix PRODUCT.md reference in docs/future-features.md"
Task: "T010 [P] [US1] Fix PRODUCT.md path in tests/test_extended_complex.py"
Task: "T012 [US2] Add failing query --json tests in tests/test_cli.py"
Task: "T015 [P] [US2] Document query --json in docs/cli-reference.md"
Task: "T018 [US3] Update sdist include PRODUCT.md in pyproject.toml"
```

---

## Implementation Strategy

### MVP First (User Story 1 First, Then User Story 2 & 3)

1. Complete **Phase 1 (Setup)** + **Phase 2 (Foundational)** (`T001`–`T004`).
2. Complete **Phase 3 (User Story 1)** (`T005`–`T011`) and validate doc links, `PRODUCT.md` exports, `constitution.md` `v1.2.0`, and `tests/test_extended_complex.py`.
3. Complete **Phase 4 (User Story 2)** (`T012`–`T017`) using strict test-first order for `docpipe-maestro query --json` and verify `tests/test_cli.py`.
4. Complete **Phase 5 (User Story 3)** (`T018`–`T020`) to verify `sdist`/`wheel` archives, `twine check`, `ruff`, `mypy`, `pytest -m reverse`, and `pytest --cov >= 80%`.
5. Run **Phase 6 (Polish)** (`T021`–`T022`) prior to committing on `chore/003-baseline-housekeeping`.

### Incremental Checkpoints

- After `T011`: Documentation, constitution, and casing rename baseline is independently verified.
- After `T017`: `docpipe-maestro query --json` feature and documentation are independently verified.
- After `T022`: Full release-ready Stage 0 baseline verified across all 6 success criteria (`SC-001`–`SC-006`).

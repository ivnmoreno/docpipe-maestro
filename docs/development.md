# Development & Testing Guide

This guide covers setting up a local development environment, running quality and safety gates, running live local model tests with Ollama, and extending **`docpipe-maestro`** cleanly.

---

## 1. Local Development Setup

`docpipe-maestro` uses a `src/` layout managed by `hatchling` + `hatch-vcs` and PEP 735 `[dependency-groups]`.

```bash
git clone https://github.com/ivnmoreno/docpipe-maestro.git
cd docpipe-maestro

# Recommended: uv
uv sync --all-extras --group dev

# Alternative: pip >= 24.1
python -m venv .venv && source .venv/bin/activate
pip install --group dev -e ".[all]"

# Enable Conventional Commit & Ruff pre-commit checks
pre-commit install --hook-type commit-msg
pre-commit install
```

---

## 2. Mandatory Quality & Safety Gates

All checks treat warnings strictly (`filterwarnings = ["error"]` in `pyproject.toml`), enforce `mypy --strict`, and require branch coverage $\ge 80\%$.

```bash
# 1. Lint and formatting check (Ruff target py310, line-length 100)
uv run ruff check .
uv run ruff format --check .

# 2. Strict static type checking across library and tests
uv run mypy src tests

# 3. Full test suite with branch coverage (must stay >= 80%)
uv run pytest -v --cov

# 4. Mandatory Reverse Safety Release Gate (exception preservation)
uv run pytest -m reverse -v

# 5. Extended large-corpus, complex multi-format & stress suite
uv run pytest -m integration -v
```

### Understanding Test Markers

Configured in `pyproject.toml`:

- `reverse` (`tests/test_reverse_safety.py`): Release-gating property tests verifying that queries targeting any policy clause with exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) retrieve parent context preserving both rule and exception.
- `integration` (`tests/test_extended_complex.py`): Large-corpus (`> 64` chunks testing multi-batch embedding), multi-page PDF boilerplate detection, complex DOCX/HTML table extraction, nested directory sync/rename/truncation, and atomic abort guarantees.
- `slow`: Reserved for long-running benchmarks or large stress runs.

### Offline Test Doubles (`tests/conftest.py`)

Unit and integration tests stay deterministic and zero-network via two fixtures in `tests/conftest.py`:

- `mock_litellm_offline`: Monkeypatches `litellm.embedding` with a deterministic L2-normalized signed bag-of-words hash embedder (`dim=64`, or `dim=32` when `"small"` appears in the model string so `reindex` dimension changes are tested) and monkeypatches `litellm.completion`.
- `tmp_persist_dir`: Provides an isolated `.docpipe` temporary directory per test.

### Running Live End-to-End Tests with Local Ollama

When Ollama is running locally (zero cloud credentials or outbound internet required):

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5:1.5b-instruct   # or default: ollama pull llama3.2

uv run docpipe-maestro ingest ./tests/fixtures/policy_corpus --profile POLICY --collection live_demo
uv run docpipe-maestro status --collection live_demo
uv run docpipe-maestro query "annual leave probationary period" --collection live_demo
uv run docpipe-maestro ask "How many days of annual leave do employees get, and what is the exception?" \
  --model ollama/qwen2.5:1.5b-instruct --collection live_demo
```

---

## 3. Architectural Guardrails for Contributors

Before adding features, verify compliance with [`.specify/memory/constitution.md`](../.specify/memory/constitution.md):

1. **Scope Discipline**: Every core feature must be reachable via the minimal public API or `docpipe-maestro` CLI — no HTTP server, auth middleware, session memory, or UI code inside `docpipe_maestro`.
2. **Two-Phase Separation**: Keep Phase 1 write logic inside `src/docpipe_maestro/ingest/` and read-only Phase 2 logic inside `src/docpipe_maestro/query/`.
3. **Library Purity**: Never read config files inside library modules (TOML loading belongs solely in `cli.py`). Never add a hardcoded provider registry; delegate `provider/model` resolution directly to `litellm`.
4. **Schema Single Source**: Add or modify shared dataclasses/types only in `src/docpipe_maestro/types.py`.
5. **Additive Format Extensions**: To add a new parser (e.g., `.rst` or `.xlsx`):
   - Add an optional dependency under `[project.optional-dependencies]` in `pyproject.toml`.
   - Implement a `_parse_<fmt>(path, source_key) -> ParsedDocument` helper in `ingest/intake.py` raising `MissingExtraError` on import failure and `UnsupportedFormatError` on corrupted files.
   - Register its extension and/or magic-byte branch in `detect_format()` and `parse_file()`.
   - Add format tests in `tests/` including failure handling when corrupted.

---

## 4. Commits, Versioning & Releases

`docpipe-maestro` uses **Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`) and derives package versions automatically from annotated Git tags via `hatch-vcs`.

```bash
# Validate commit messages against Commitizen rules
uv run cz check --rev-range HEAD~5..HEAD

# Update CHANGELOG.md from conventional commits (use cz changelog, NOT cz bump)
uv run cz changelog

# Verify wheel and sdist artifacts cleanly
uv run python -m build
uv run twine check dist/*
```

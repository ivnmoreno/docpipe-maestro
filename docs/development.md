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

# Alternative: pip >= 24.1 (add rerank,pii extras if testing optional dependencies)
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
# 1. Lint, formatting, and Bandit security checks (Ruff target py310, line-length 100)
uv run ruff check .
uv run ruff check --select S src/
uv run ruff format --check .

# 2. Strict static type checking across library and tests
uv run mypy src tests

# 3. Full offline test suite with branch coverage (must stay >= 80%)
LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov

# 4. Mandatory Safety Release Gates (exception preservation + PII safety)
uv run pytest -m reverse -v
uv run pytest -m pii -v

# 5. Extended large-corpus, complex multi-format & stress suite
uv run pytest -m integration -v
```

### Understanding Test Markers

Configured in `pyproject.toml`:

- `reverse` (`tests/test_reverse_safety.py`): Release Gate #1 property tests verifying that queries targeting any policy clause with exception markers (`except`, `unless`, `not entitled`, `subject to`, `provided that`) retrieve parent context preserving both rule and exception.
- `pii` (`tests/test_pii_safety.py`): Release Gate #2 synthetic tests verifying pre-chunking blocking/redaction/tokenization in headings and bodies, transactional `PiiBlockedError` rollback, owner-only zero-raw-PII `.audit.jsonl` logs, `--local-only` refusal, and outbound `guard_egress` enforcement offline.
- `integration` (`tests/test_extended_complex.py`): Large-corpus (`> 64` chunks testing multi-batch embedding), multi-page PDF boilerplate detection, complex DOCX/HTML table extraction, nested directory sync/rename/truncation, and atomic abort guarantees.
- `slow`: Reserved for long-running benchmarks or large stress runs.
- Baseline replay (`tests/test_eval.py`): Replays `tests/fixtures/eval_policy_corpus.json` strictly offline under `mock_litellm_offline` and verifies exact equivalence with `docs/eval-baseline.json` (`default` and `fts5_hybrid`).

### Offline Test Doubles (`tests/conftest.py`)

Unit and integration tests stay deterministic and zero-network via two fixtures in `tests/conftest.py`:

- `mock_litellm_offline`: Monkeypatches `litellm.embedding` with a deterministic L2-normalized signed bag-of-words hash embedder (`dim=64`, or `dim=32` when `"small"` appears in the model string so `reindex` dimension changes are tested) and monkeypatches `litellm.completion` (handling both non-streaming completions and `stream=True` delta chunks in offline tests).
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
  --model ollama/qwen2.5:1.5b-instruct --collection live_demo --stream
uv run docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json --collection live_demo --searcher fts5_hybrid
```

---

## 3. Architectural Guardrails for Contributors

Before adding features, verify compliance with [`.specify/memory/constitution.md`](../.specify/memory/constitution.md):

1. **Scope Discipline**: Every core feature must be reachable via the minimal public API or `docpipe-maestro` CLI — no HTTP server, auth middleware, session memory, or UI code inside `docpipe_maestro`.
2. **Two-Phase Separation**: Keep Phase 1 write logic inside `src/docpipe_maestro/ingest/` and read-only Phase 2 logic inside `src/docpipe_maestro/query/` (and `src/docpipe_maestro/eval/`).
3. **Library Purity**: Never read config or PII policy files inside library modules (TOML `--config` and JSON/TOML `--pii-policy` parsing belong solely in `cli.py`). Never add a hardcoded provider registry; delegate `provider/model` resolution directly to `litellm`.
4. **Schema Single Source**: Add or modify shared dataclasses/types only in `src/docpipe_maestro/types.py`.
5. **Additive Format Extensions**: To add a new parser (e.g., `.rst` or `.xlsx`):
   - Add an optional dependency under `[project.optional-dependencies]` in `pyproject.toml`.
   - Implement a `_parse_<fmt>(path, source_key) -> ParsedDocument` helper in `ingest/intake.py` raising `MissingExtraError` on import failure and `UnsupportedFormatError` on corrupted files.
   - Register its extension and/or magic-byte branch in `detect_format()` and `parse_file()`.
   - Add format tests in `tests/` including failure handling when corrupted.

---

## 4. Commits, Versioning & Releases

`docpipe-maestro` uses **Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`) and derives package versions automatically from annotated Git tags via `hatch-vcs`.

```bash
# Validate commit messages against Commitizen rules
uv run cz check --rev-range origin/main..HEAD

# Update CHANGELOG.md from conventional commits (use cz changelog, NOT cz bump)
uv run cz changelog

# Verify lockfile, build artifacts, and package metadata cleanly
uv lock --check
uv build
uv run twine check --strict dist/*
```

### Automated CI & Trusted Publishing Workflows

- **Continuous Integration ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)):** Runs on pushes and pull requests to `main`:
  - `quality`: Ubuntu matrix across Python `3.10`–`3.13` (`uv lock --check`, Ruff format/lint/security `S`, strict `mypy`, `@pytest.mark.reverse`, `@pytest.mark.pii`, and full `pytest --cov` branch coverage >= 80%).
  - `commits`: Pull-request Commitizen check across PR commits.
  - `minimal-core`: Python `3.10` core-only install without optional extras (`--group dev`), verifying core tests, CLI entrypoint, and fail-loud `MissingExtraError` guards.
  - `packaging`: `uv build`, `twine check --strict`, and isolated clean-venv wheel + sdist installation smoke tests.
  - `dependency-audit`: `pip-audit` against exported locked dependencies.
  - `os-smoke`: Cross-OS offline test matrix on `macos-latest` and `windows-latest`.
- **Trusted Release Pipeline ([`.github/workflows/release.yml`](../.github/workflows/release.yml)):** Triggered by version tags matching `v[0-9]*` (e.g., `v0.2.0`):
  1. Verifies quality/safety gates, builds sdist + wheel with `hatch-vcs`, asserts the built wheel version matches the pushed tag (no `.dev`/local versions), and runs `twine check --strict`.
  2. Publishes artifacts to TestPyPI (`testpypi` environment) via OIDC Trusted Publishing (`id-token: write`).
  3. Smoke-tests `pip install --no-deps` from TestPyPI into a fresh environment (`docpipe-maestro --version`).
  4. Publishes artifacts to PyPI (`pypi` environment) via OIDC Trusted Publishing and creates a GitHub Release with attached distributions and generated notes.

# Contributing to `docpipe-maestro`

Thank you for your interest in contributing to **`docpipe-maestro`**!

For complete environment details, offline test doubles, and live Ollama smoke-test instructions, see the [Development & Testing Guide](docs/development.md).

---

## Quick Setup

```bash
git clone https://github.com/ivnmoreno/docpipe-maestro.git
cd docpipe-maestro

# Install runtime, optional extras, and dev dependencies
uv sync --all-extras --group dev

# Enable Conventional Commits and Ruff pre-commit hooks
uv run pre-commit install --hook-type commit-msg
uv run pre-commit install
```

---

## Core Design Principles

All contributions must uphold the guardrails in [`.specify/memory/constitution.md`](.specify/memory/constitution.md):

1. **Scope Discipline:** `docpipe-maestro` is a minimal RAG pipeline library and CLI engine — do not add HTTP servers, auth middleware, session management, or UI layers to `src/docpipe_maestro/`.
2. **Two-Phase Separation:** Phase 1 ingestion (`ingest/`) writes offline; Phase 2 query (`query/`) treats the vector store as read-only.
3. **Library Purity:** Only `src/docpipe_maestro/cli.py` may read TOML configuration files. Never introduce a hardcoded provider registry or store credentials outside environment variables.
4. **Search Small, Return Big & Exception Preservation:** Match child chunks (`type="child"`) and return deduplicated parent sections (`type="parent"`). Policy rules with exception markers must never lose their exception clauses.
5. **Single Schema Source:** Define shared dataclasses and TypedDicts once in `src/docpipe_maestro/types.py`.

---

## Pull Request Checklist

Before opening a pull request, ensure every CI gate passes locally:

```bash
# Formatting, lint, and Bandit security rules
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/

# Strict type checking
uv run mypy src tests

# Mandatory Reverse Safety Gate & full suite with branch coverage (>= 80%)
uv run pytest -m reverse -v
LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov

# Conventional Commits validation
uv run cz check --rev-range origin/main..HEAD
```

### Commit Message Format

Commits must follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`), enforced by Commitizen (`cz check`).

---

## Reporting Security Issues

Please do **not** report security vulnerabilities in public GitHub issues. Follow the instructions in [SECURITY.md](SECURITY.md).

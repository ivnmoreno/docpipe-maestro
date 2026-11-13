# Quickstart Validation Guide: Baseline Housekeeping and Alignment

**Feature**: `003-baseline-housekeeping` | **Branch**: `chore/003-baseline-housekeeping` | **Date**: 2026-11-13

Use these deterministic checks after implementing Stage 0 edits to validate all success criteria (`SC-001`–`SC-006`) defined in [spec.md](spec.md), [data-model.md](data-model.md), [contracts/cli-query-json.md](contracts/cli-query-json.md), and [contracts/baseline-alignment.md](contracts/baseline-alignment.md).

---

## Prerequisites

- Working tree on branch `chore/003-baseline-housekeeping`
- Development environment synced (`uv sync --extra all --group dev`)

---

## 1. Filename Casing & Internal Markdown Link Verification (`SC-001`, `SC-002`)

Verify zero stale `Product.md` references remain across source, tests, packaging, and active documentation, and confirm all relative file links in `README.md`, `PRODUCT.md`, `docs/`, and `.specify/memory/constitution.md` resolve on disk:

```bash
# Confirm git tracks PRODUCT.md (not Product.md)
git ls-files Product.md PRODUCT.md

# Confirm zero remaining stale references outside historical 001/002 specs and logs
grep -rn "Product\.md" README.md PRODUCT.md CHANGELOG.md CONTRIBUTING.md SECURITY.md pyproject.toml .github/ docs/ .specify/memory/ src/ tests/ || echo "Clean"

# Validate every relative file link across root docs, docs/, and constitution.md
uv run python -c '
import pathlib, re
roots = [pathlib.Path("README.md"), pathlib.Path("PRODUCT.md"), pathlib.Path(".specify/memory/constitution.md"), *sorted(pathlib.Path("docs").glob("*.md"))]
missing = []
for f in roots:
    text = re.sub(r"```.*?```|`[^`]*`", "", f.read_text(encoding="utf-8"), flags=re.S)
    for m in re.finditer(r"\[[^\]]+\]\(([^)#:\s]+)(?:#[^)]*)?\)", text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (f.parent / target).resolve()
        if not resolved.exists() or resolved.name != pathlib.Path(target).name:
            missing.append((str(f), target))
assert not missing, f"Broken links: {missing}"
print(f"Verified relative links across {len(roots)} docs cleanly.")
'
```

---

## 2. Public API & Constitution Alignment Check (`SC-002`, `SC-003`)

Verify `PRODUCT.md` §7.5 lists all 24 symbols from `docpipe_maestro.__all__`, §20.1 covers every active Python module under `src/docpipe_maestro/`, and `.specify/memory/constitution.md` is at version `1.2.0` with Release Gate #1 / reserved Gate #2 and updated Footprint wording:

```bash
uv run python -c '
import pathlib, docpipe_maestro
product = pathlib.Path("PRODUCT.md").read_text(encoding="utf-8")
missing = [sym for sym in docpipe_maestro.__all__ if sym not in product]
assert not missing, f"Missing from PRODUCT.md: {missing}"
const = pathlib.Path(".specify/memory/constitution.md").read_text(encoding="utf-8")
assert "**Version**: 1.2.0" in const and "Last Amended**: 2026-11-13" in const
assert "Release Gate #1" in const and "Release Gate #2" in const
assert "minimal in promise, not in rigor" in const.lower()
assert "generation is an optional extra" not in const.lower()
print("Public API (24 exports) and Constitution v1.2.0 checks passed.")
'
```

---

## 3. CLI `query --json` Contract Validation (`SC-004`)

Validate parent-expanded output, raw child output (`--no-expand-parent`), empty threshold results (`"results": []`), unchanged non-JSON output, and `Error: ...` failure output (`exit 1`, empty `stdout`):

```bash
# Automated unit/CLI contract tests covering query --json scenarios
uv run pytest tests/test_cli.py -v -k "query"
```

Expected assertions verified by `tests/test_cli.py` and [contracts/cli-query-json.md](contracts/cli-query-json.md):
- Valid JSON parsed by `json.loads(...)` / `jq .` with top-level keys `query`, `collection`, `expand_parent`, `results`.
- Each item exposes `id`, `parent_id` (`null` when `expand_parent=true`; parent ID string when `expand_parent=false`), `score` (float `[0.0, 1.0]`), `text`, and `metadata`.
- Zero matches with `--json` prints `"results": []` and exits `0` without plain-text prose.
- Validation/runtime errors with `--json` write `Error: ...` to `stderr`, keep `stdout` empty, and exit `1`.

---

## 4. Packaging Build & Distribution Verification (`SC-005`)

Build fresh `sdist` and `wheel` artifacts, run `twine check`, and inspect bundle contents:

```bash
rm -rf dist/
uv run python -m build
uv run twine check dist/*
tar -tzf dist/docpipe_maestro-*.tar.gz | grep -E "PRODUCT\.md|constitution\.md|docs/"
unzip -l dist/docpipe_maestro-*.whl | grep "py.typed"
```

Expected:
- Zero warnings from `hatchling` or `twine check`.
- Source tarball contains `PRODUCT.md`, `.specify/memory/constitution.md`, and `docs/`, and contains zero `Product.md`.
- Wheel archive contains `docpipe_maestro/py.typed`.

---

## 5. Quality & Mandatory Release Gate Suite (`SC-006`)

```bash
uv run ruff format --check .
uv run ruff check .
uv run ruff check --select S src/
uv run mypy src tests
uv run pytest -m reverse -v
uv run pytest -v --cov
```

Expected: All formatting, lint, Bandit (`S`) security checks, strict `mypy` type checks across `src` and `tests`, mandatory Release Gate #1 (`-m reverse`), and full test suite (`>= 80%` branch coverage) exit `0`.

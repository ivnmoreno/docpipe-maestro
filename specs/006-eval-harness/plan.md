# Implementation Plan: Retrieval Evaluation Harness

**Branch**: `006-eval-harness` (git `feat/006-eval-harness`) | **Date**: 2026-11-14 | **Spec**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/spec.md)

**Input**: Feature specification from `/specs/006-eval-harness/spec.md`

## Summary

Build a deterministic, strictly read-only retrieval evaluation harness in `src/docpipe_maestro/eval/` (`metrics.py`, `harness.py`, `__init__.py`) backed by canonical `TypedDict` schemas in `src/docpipe_maestro/types.py`, expose a lazy-loaded `eval` CLI subcommand in `src/docpipe_maestro/cli.py`, curate a self-contained `20+`-query policy benchmark (`tests/fixtures/eval_policy_corpus.json` grounded across untouched `tests/fixtures/policy_corpus/` plus complementary synthetic Markdown files in `tests/fixtures/eval_corpus/`), and commit offline reproducible side-by-side baseline snapshots (`default` dense search vs `fts5_hybrid` hybrid search) in `docs/eval-baseline.json` and `docs/eval-baseline.md`. All metric math uses standard IR definitions (`Recall@K` over total unique relevant IDs), rejects malformed/empty fixture queries while keeping low-level metric primitives safe, honors `explicit --collection > fixture collection > config > default` precedence, and passes 100% of repository tests and quality gates after completion.

## Technical Context

**Language/Version**: Python `>= 3.10` (`mypy --strict`, `python_version = "3.10"`, `ruff`)
**Primary Dependencies**: Zero new third-party dependencies; reuses stdlib `json`/`pathlib`/`argparse`/`math` alongside existing Phase 2 retrieval (`retrieve`, `SEARCHERS`, `EMBEDDERS`, `STORES`, `manifest`)
**Storage**: Strictly read-only reads against existing `<persist_dir>/manifests/<collection>.json`, `<persist_dir>/chroma.sqlite3`, and `<persist_dir>/lexical/<collection>.db`; zero directory/file creation or byte writes during evaluation (verified via manifest existence pre-flight before `ChromaStore`)
**Testing**: `pytest` (`-Werror`), `pytest-cov` (`branch = true`, `fail_under = 80`), `pytest -m reverse` (Release Gate #1), `ruff format --check .`, `ruff check .`, `ruff check --select S src/`, `mypy src tests`
**Target Platform**: Cross-platform Python `3.10+` (`Linux`/`macOS`/`Windows`) local CLI and library workflows with zero network required in CI
**Project Type**: Single Python package + CLI (`src/docpipe_maestro/`, `tests/`, `docs/`)
**Performance Goals**: Instant (`O(|K| + |retrieved|)`) pure metric math; single `retrieve(..., top_k=max(K))` call per query regardless of cutoff list length; CLI parser & startup remain lightweight without importing `chromadb`/`litellm`
**Constraints**: Preserve 33-symbol top-level `docpipe_maestro.__all__`; keep library config discovery confined strictly to `cli.py`; preserve `tests/fixtures/policy_corpus/` completely unmodified; exit `0` on valid runs (no threshold failure gate flags); deterministic bit-for-bit repeatable scores offline
**Scale/Scope**: Curated `20+` queries (`>= 3` rule-and-exception parent-section queries) across ~20+ parent sections in 5 packaged Markdown policy files, extensible cleanly to arbitrary user fixtures

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / Gate | Compliance Design | Pre-Design | Post-Design |
| --- | --- | --- | --- |
| I. Scope Discipline | Minimal, library-first evaluation subpackage (`docpipe_maestro.eval`) + `eval` CLI workflow cleanly scoped to Phase 2 retrieval ranking only (no LLM judge, no UI/HTTP server, no score gate bloat); 33-symbol top-level `__all__` preserved | PASS | PASS |
| II. Two-Phase Architecture | Evaluation invokes read-only Phase 2 `retrieve()` only; `evaluate()` validates manifest existence & committed sources before touching `ChromaStore` so missing collections create zero storage artifacts | PASS | PASS |
| III. Library Purity | Zero config/dotenv imports inside `src/docpipe_maestro/eval/`; only `cli.py` resolves `docpipe.toml` / `.env` defaults and forwards resolved args explicitly into `evaluate()`; CLI parser keeps heavy backends unloaded | PASS | PASS |
| IV. Search Small, Return Big | Harness propagates `expand_parent` (default `True`) straight to `retrieve()`, measuring returned parent IDs strictly against fixture parent `relevant_ids` cleanly | PASS | PASS |
| V. Exception Preservation | Untouched `tests/fixtures/policy_corpus/` keeps `@pytest.mark.reverse` Release Gate #1 100% invariant; curated benchmark includes `>= 3` `rule_and_exception` queries verified to target complete parent sections | PASS | PASS |
| VI. Provider Agnosticism & Local-First | Delegates to `provider/model` + `SEARCHERS`; committed baselines run 100% offline with `mock_litellm_offline` (`deterministic_embed`) and require zero external downloads in CI | PASS | PASS |
| VII. Structured Correctness Over Speed | All 6 evaluation `TypedDict`s (`EvalQuery`, `EvalFixture`, `EvalConfig`, `PerQueryResult`, `EvalMetricsSummary`, `EvalReport`) defined canonically in `src/docpipe_maestro/types.py` and re-exported in `eval.harness` / `eval`; full test suite pass mandatory (`v1.2.2`) | PASS | PASS |

**Gate Outcome**: **PASS** (0 Constitution violations pre-design; 0 violations post-design).

## Project Structure

### Documentation (this feature)

```text
specs/006-eval-harness/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 architectural, empirical read-only, and formula decisions
├── data-model.md        # Phase 1 canonical TypedDict schemas and validation rules
├── quickstart.md        # Phase 1 offline/online validation scenarios and gate commands
├── contracts/
│   └── eval-harness.md  # Phase 1 metrics, runner, CLI, fixture, and baseline contracts
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/docpipe_maestro/
├── types.py                         # Add canonical EvalQuery, EvalFixture, EvalConfig, PerQueryResult, EvalMetricsSummary, EvalReport TypedDicts
├── cli.py                           # Add _StoreExplicitCollection action, p_eval subcommand, _handle_eval (lazy eval import), config fallback
└── eval/                            # NEW subpackage (Phase 2 offline evaluation tooling)
    ├── __init__.py                  # Clean re-exports for metrics, TypedDicts, load_eval_fixture, evaluate, DEFAULT_EVAL_K_VALUES
    ├── metrics.py                   # Pure zero-I/O precision_at_k, recall_at_k, reciprocal_rank, normalize_k_values
    └── harness.py                   # Strict read-only load_eval_fixture & evaluate runner

tests/
├── fixtures/
│   ├── policy_corpus/               # UNTOUCHED (hr_leave_policy.md, travel_expenses_policy.md)
│   ├── eval_corpus/                 # NEW complementary synthetic Markdown policy files (POLICY profile)
│   │   ├── information_security_policy.md
│   │   ├── incident_response_runbook.md
│   │   └── procurement_vendor_policy.md
│   └── eval_policy_corpus.json      # NEW curated 20+ query fixture (>=3 rule+exception full-parent queries)
├── test_eval.py                     # NEW comprehensive metrics, runner read-only/errors, CLI, fixture coverage & baseline replay tests
├── test_cli.py                      # Add CLI eval flag/precedence/startup/error regression tests as needed
└── test_reverse_safety.py           # Untouched Release Gate #1 baseline tests

docs/
├── eval-baseline.json               # NEW reproducible offline side-by-side BaselineSnapshot (default + fts5_hybrid)
├── eval-baseline.md                 # NEW human-readable baseline comparison summary & reproduction guide
├── cli-reference.md                 # Document docpipe-maestro eval flags, precedence, and examples
├── api-reference.md                 # Document docpipe_maestro.eval API and TypedDicts
└── architecture.md                  # Update package map / evaluation layer notes
```

**Structure Decision**: Place the evaluation engine in `src/docpipe_maestro/eval/` following the `REFACTOR_PROGRAM.md` package blueprint while housing canonical `TypedDict` definitions in `src/docpipe_maestro/types.py` (re-exported by `eval.harness`) so Constitution Principle VII, top-level `__all__` stability (`tests/test_api_stability.py`), and CLI startup purity (`tests/test_library_purity.py`) all hold cleanly without adding heavy runtime dependencies.

## Complexity Tracking

No Constitution violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| — | — | — |

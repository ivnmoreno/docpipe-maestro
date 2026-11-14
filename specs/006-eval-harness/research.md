# Phase 0 Research: Retrieval Evaluation Harness

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/spec.md) | **Date**: 2026-11-14 | **Branch**: `feat/006-eval-harness`

## 1. Module Placement & Public API Surface Stability

- **Decision**: Implement the evaluation engine under a dedicated subpackage `src/docpipe_maestro/eval/` (`__init__.py`, `metrics.py`, `harness.py`) while defining its canonical `TypedDict` data shapes (`EvalQuery`, `EvalFixture`, `PerQueryResult`, `EvalConfig`, `EvalReport`) once in `src/docpipe_maestro/types.py` and re-exporting them from `docpipe_maestro.eval.harness` and `docpipe_maestro.eval`. Leave top-level `docpipe_maestro.__all__` (`33` symbols guarded by `tests/test_api_stability.py` and Constitution Additional Constraints) unchanged.
- **Rationale**: Keeps top-level contract tests (`test_top_level_all_exports_and_exception_hierarchy`) intact without forcing a Constitution amendment for `docpipe_maestro.__all__`, preserves Constitution VII (*single canonical schema definitions in `types.py`*), and delivers the exact module surface (`docpipe_maestro.eval.metrics`, `docpipe_maestro.eval.harness`) expected by downstream ranking stages.
- **Alternatives Considered**:
  - *Adding `evaluate` / metrics to top-level `docpipe_maestro.__all__`*: Rejected because Constitution Additional Constraints and `tests/test_api_stability.py` strictly lock `len(root.__all__) == 33`, and offline evaluation is developer/benchmark tooling rather than an online core pipeline verb (`ingest`/`retrieve`/`answer`).
  - *Defining `TypedDict` shapes only inside `eval/harness.py`*: Rejected because Constitution Principle VII mandates defining cross-module data shapes once in `types.py`; defining in `types.py` and re-exporting in `eval/harness.py` satisfies both rules cleanly.

## 2. Pure Ranking Metric Semantics (`metrics.py`)

- **Decision**: Implement pure, zero-I/O metric functions (`precision_at_k`, `recall_at_k`, `reciprocal_rank`) plus cutoff helper `normalize_k_values` in `src/docpipe_maestro/eval/metrics.py` with strict boundary guards:
  - `k` validation: Reject `bool` (via `isinstance(k, bool)`) and `k <= 0` with `ValueError`.
  - Relevant set normalization: Convert `relevant_ids` into a `frozenset[str]` once per call, eliminating duplicates cleanly.
  - `precision_at_k(retrieved_ids, relevant_ids, k)`: Return `0.0` if `not relevant_set or not retrieved_ids`. Otherwise deduplicate `retrieved_ids[:k]` when intersecting `relevant_set` (`hits = len(set(retrieved_ids[:k]) & relevant_set)`) and divide by `k`. Always bounded within `[0.0, 1.0]`.
  - `recall_at_k(retrieved_ids, relevant_ids, k)`: Return `0.0` if `not relevant_set or not retrieved_ids`. Otherwise compute `len(set(retrieved_ids[:k]) & relevant_set) / len(relevant_set)` (standard IR `Recall@K`, Q1 decision). Monotonically non-decreasing across ascending `K` and bounded within `[0.0, 1.0]`.
  - `reciprocal_rank(retrieved_ids, relevant_ids)`: Return `0.0` if `not relevant_set or not retrieved_ids`. Scan `retrieved_ids` in order with 1-based rank; return `1.0 / rank` at the first ID present in `relevant_set`, else `0.0`.
  - `normalize_k_values(k_values)`: Reject empty sequence, `bool` entries, or `k <= 0` with `ValueError`; return `tuple(sorted({int(k) for k in k_values}))` (Q4 decision).
- **Rationale**: Zero third-party or package imports keep `metrics.py` fast, pure, and independently testable; deduplicating `retrieved_ids[:k]` protects `Precision@K` and `Recall@K` against synthetic duplicate inputs exceeding `1.0`.
- **Alternatives Considered**:
  - *Counting un-deduplicated hits in `Precision@K`*: Rejected because duplicate retrieved IDs in synthetic unit tests could push `Precision@K` above `1.0` or make `Recall@K` > `1.0`.
  - *Capped `Recall@K` (`min(K, |relevant|)`) denominator*: Rejected via Q1 clarification in favor of standard IR `|relevant|`.

## 3. Strictly Read-Only Persistence Verification & Pre-Flight Validation

- **Decision**: In `evaluate(...)`, execute all validation and persistence pre-flight checks **before** calling `retrieve()` or instantiating any `VectorStore` / `ChromaStore`:
  1. Validate numeric options (`normalize_k_values(k_values)`, finite `threshold` in `[0.0, 1.0]` if provided).
  2. Load and validate the evaluation fixture (`load_eval_fixture`) — rejecting missing files, invalid JSON, missing required fields, zero queries, blank questions, or any query with empty `relevant_ids` (Q2 decision) with `DocpipeError` / `ValueError`.
  3. Resolve target collection (`explicit collection arg or non-empty fixture["collection"] or DEFAULT_COLLECTION`) and validate collection name (`validate_collection_name`).
  4. Resolve registry selectors (`EMBEDDERS`, `STORES`, `SEARCHERS`) early if non-default so unknown keys fail immediately before store/provider lookups.
  5. Check `manifest_path(persist_path, resolved_collection).exists()` first without calling `ensure_private_dir` or `ChromaStore`; if absent, raise `DocpipeError` explaining that the collection does not exist.
  6. Load manifest read-only (`load_manifest`), run `check_model_lock(manifest, embed_model)` (raising `ModelMismatchError` on lock mismatch), and verify `bool(manifest.sources)` (raising `DocpipeError` if zero committed documents exist).
  7. Run `retrieve(query["question"], ..., top_k=max(normalized_k), ...)` once per query (not once per `K`), extracting `retrieved_ids = [chunk.id for chunk in chunks]` and scores `[float(chunk.score) for chunk in chunks]`.
- **Empirical Verification**: Tested in an isolated temporary `.docpipe` directory ingested under `POLICY` profile with both `searcher="default"` and `searcher="fts5_hybrid"`. Comparing SHA-256 hashes of every file inside `.docpipe/` before and after `retrieve()` showed zero added files, zero removed files, and zero modified bytes across both vector and SQLite FTS5 stores.
- **Rationale**: Calling `ChromaStore.__init__` directly on a non-existent `.docpipe` directory calls `ensure_private_dir` + `chromadb.PersistentClient(...).get_or_create_collection(...)`, which would create empty directories and `chroma.sqlite3` files on disk. Checking `manifest_path.exists()` first ensures missing or empty collections fail cleanly with zero filesystem side effects, satisfying `FR-003` and `SC-002`.
- **Alternatives Considered**:
  - *Letting `retrieve()` return `[]` on missing/empty collections*: Rejected because `spec.md` (`Edge Cases`, `FR-005`) explicitly requires failing fast on missing or zero-document collections rather than reporting misleading `0.0` scores.

## 4. CLI Collection Resolution Precedence (`Q3`) & Option Handling

- **Decision**: Track explicit `--collection` flag presence in `cli.py` using a lightweight `argparse.Action` subclass (`_StoreExplicitCollection`) on both top-level `parser` and shared `common` parent parser, setting `namespace._collection_explicit = True` whenever `--collection` is supplied either before or after the subcommand name (`parser.set_defaults(_collection_explicit=False)`). In `_handle_eval`:
  - Lazy-import `DEFAULT_EVAL_K_VALUES`, `evaluate`, and `load_eval_fixture` inside `_handle_eval` so `tests/test_library_purity.py` passes startup import checks (`chromadb`, `litellm`, `pypdf`, `docx`, `bs4` stay unloaded on `cli.build_parser()` and `--help`).
  - Call `loaded_fixture = load_eval_fixture(args.fixture)` once inside `_handle_eval`, capture `cfg_collection = _cfg_opt_str(cfg, "collection")` from `_load_toml_config`, resolve target collection cleanly in `cli.py`, and pass both `loaded_fixture` and resolved `collection` into `evaluate(...)` (keeping TOML fallback resolution strictly inside `cli.py` with zero `fallback_collection` parameter leakage in `evaluate()`):
    1. `args.collection` if `args._collection_explicit` is `True`;
    2. Else `loaded_fixture["collection"].strip()` if present and non-empty;
    3. Else `cfg_collection` (from TOML `docpipe.toml` / `--config`) if present and non-empty;
    4. Else `DEFAULT_COLLECTION` (`"default"`).
  - Add `p_eval` subcommand (`--fixture` required, `--k` with `action="extend", nargs="+", type=int` accepting both `--k 1 3 5 10` and `--k 1 --k 3`, `--embed-model`, `--searcher`, `--expand-parent` boolean optional defaulting to `True`, `--json`).
- **Rationale**: Standard `argparse` default resolution merges CLI flags and TOML defaults eagerly into `args.collection`, hiding whether `--collection` was typed by the operator or synthesized from config/`"default"`. Recording `_collection_explicit` cleanly enables `Q3` precedence (`explicit > fixture > config > default`) for `eval` without changing behavior for any existing subcommand (`ingest`, `sync`, `status`, `remove`, `reindex`, `query`, `ask`).
- **Alternatives Considered**:
  - *Removing global `--collection` default for all subcommands*: Rejected because existing commands and `tests/test_cli.py` depend on `args.collection` resolving TOML/default seamlessly.
  - *Only supporting repeated `--k 1 --k 3` (`action="append"`)*: Rejected in favor of `action="extend", nargs="+"` so both `--k 1 3 5` and `--k 1 --k 3 --k 5` parse naturally.

## 5. Curated Benchmark Corpus (`Q2`) & Offline Side-by-Side Baselines (`Q1`)

- **Decision**:
  - Keep `tests/fixtures/policy_corpus/` (`hr_leave_policy.md`, `travel_expenses_policy.md` — 6 parent sections) 100% untouched so `@pytest.mark.reverse` (`tests/test_reverse_safety.py`, Release Gate #1) remains invariant.
  - Add `tests/fixtures/eval_corpus/` containing complementary synthetic Markdown policy documents (`information_security_policy.md`, `incident_response_runbook.md`, `procurement_vendor_policy.md`) structured with clear headings, exact clause/control codes (`AES-256`, `KMS-401`, `SEV-1`, `IR-RB-012`, `DPO-24H`, `PROC-204`, `PO-5000`), cross-document citations, and rule-plus-exception sections using Markdown (`POLICY` profile, requiring zero optional `[pdf]/[docx]/[html]` extras).
  - Ingest both `tests/fixtures/policy_corpus` and `tests/fixtures/eval_corpus` sequentially into a single `"eval_policy"` collection (`profile="POLICY"`) during offline benchmark seeding, producing ~20+ distinct parent sections.
  - Author `tests/fixtures/eval_policy_corpus.json` with 22–24 curated queries tagged in `notes` across all 4 required categories:
    1. `direct_lookup` (factual policy questions);
    2. `paraphrased` (semantic wording without shared exact terms);
    3. `exact_identifier` (queries citing clause/code identifiers such as `IR-RB-012`, `AES-256`, `SEV-1`, `PROC-204`, `Section 2.2` where lexical/hybrid retrieval measurably boosts precision/MRR);
    4. `rule_and_exception` (`>= 5` queries exceeding `>= 3` requirement, where `relevant_ids` targets complete enclosing parent section IDs containing both general rule and exception clauses).
  - Generate `docs/eval-baseline.json` (recording reproducible offline runs via `deterministic_embed` / `mock_litellm_offline` for **both** `modes.default` and `modes.fts5_hybrid` side-by-side at `k_values=(1, 3, 5, 10)`) and accompanying `docs/eval-baseline.md` summarizing the metrics table, delta between dense and hybrid search, corpus inventory, and offline reproduction commands.
- **Rationale**: Using Markdown files keeps CI 100% dependency-free (`docpipe-maestro` core install), packages cleanly inside `tests/` (`pyproject.toml` `sdist` already includes `tests/` and `docs/`, unlike root `documents/`), gives `test_reverse_safety.py` zero churn, and delivers objective, deterministic side-by-side comparison baselines for upcoming Reranking (`Stage 3+`) regressions.
- **Alternatives Considered**:
  - *Adding files inside `tests/fixtures/policy_corpus/`*: Rejected so Release Gate #1 fixture files remain completely untouched.
  - *Referencing root `documents/`*: Rejected because root `documents/` is excluded from `sdist` packaging and contains a 19 MB PDF requiring `[pdf]` extra.

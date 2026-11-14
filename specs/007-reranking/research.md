# Phase 0 Research: Cross-Encoder Reranking

**Feature**: [spec.md](spec.md) | **Date**: 2026-11-14 | **Branch**: `feat/007-reranking`

## 1. Optional Packaging (`[rerank]`) & Lazy Import Isolation

- **Decision**:
  - Add an optional dependency group `rerank = ["sentence-transformers>=3.0.0"]` under `[project.optional-dependencies]` in `pyproject.toml`, keeping core `[project.dependencies]` untouched and leaving `[project.optional-dependencies].all` scoped to document format parsers (`pdf`, `docx`, `html`) so parser-only installs do not pull ~1–2 GB PyTorch wheels unexpectedly. Update `uv.lock` accordingly (CI's `uv sync --all-extras --group dev` installs `rerank` across Python `3.10-3.13`, and users can opt in via `pip install "docpipe-maestro[rerank]"`).
  - Add `"sentence_transformers.*"` to `[[tool.mypy.overrides]]` (`ignore_missing_imports = true`) in `pyproject.toml`.
  - Keep `src/docpipe_maestro/query/reranker/__init__.py` completely free of eager `sentence_transformers` imports using `RERANKERS.register_lazy("cross_encoder", "docpipe_maestro.query.reranker.cross_encoder", "CrossEncoderReranker")` and module-level `__getattr__` for `CrossEncoderReranker` (mirroring `query/searcher/__init__.py`).
  - Extend `tests/test_library_purity.py` (`test_top_level_register_exports_and_cli_avoid_heavy_deps`) to assert neither `'sentence_transformers'` nor `'torch'` enters `sys.modules` on package import, `register_reranker` access, or `cli.build_parser()`.
- **Rationale**: Enforces Constitution Principles I & VI (lean local core install, zero import-time heavyweight ML dependencies) and `FR-002` / `SC-004` cleanly while matching existing `SEARCHERS` / `EMBEDDERS` / parser patterns.
- **Alternatives Considered**:
  - *Including `docpipe-maestro[rerank]` inside `[all]`*: Rejected because `README.md` currently documents `[all]` as "all document format parsers", and forcing PyTorch downloads on users wanting PDF+DOCX+HTML parsers violates lean footprint expectations. Users opting into reranking run `pip install "docpipe-maestro[rerank]"`.
  - *Using `llama-cpp` or HTTP reranker APIs*: Rejected because `spec.md` restricts scope to local cross-encoder weights (`BAAI/bge-reranker-base`) and excludes cloud reranker APIs.

## 2. Fail-Fast Dependency Preflight, Model Caching & Score Normalization

- **Decision**:
  - Inside `src/docpipe_maestro/query/reranker/cross_encoder.py`, implement `CrossEncoderReranker` (`name = "cross_encoder"`) registered via `@RERANKERS.register("cross_encoder")`, with `DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"` defined in `config.py`.
  - Provide a lightweight dependency check (`validate_available()` / `has_rerank_extra()`) using `sys.modules` + `importlib.util.find_spec("sentence_transformers")` **without importing `sentence_transformers` or `torch`**. Raise `MissingExtraError("Cross-encoder reranking requires the 'rerank' extra: pip install 'docpipe-maestro[rerank]'")` when `sentence_transformers` is absent or explicitly masked (`sys.modules["sentence_transformers"] = None`).
  - Extract a shared validation helper (`validate_rerank_options(rerank=..., reranker=..., rerank_top_n=...)`) exported from `docpipe_maestro.query.reranker` so both `query/retriever.py` and `eval/harness.py` validate `rerank_top_n` (rejecting booleans and integers `<= 0` with `ValueError`!), resolve `RERANKERS.resolve(reranker)` when `rerank=True`, and run optional `validate_available()` upfront before touching stores or returning early on empty collections / `top_k <= 0`.
  - Cache loaded `CrossEncoder(model_name)` instances in a thread-safe module dictionary `_MODEL_CACHE: dict[str, Any]` guarded by `threading.Lock()` inside `_load_cross_encoder(model_name: str)`, delegating cold creation to `_instantiate_cross_encoder(model_name: str)` which invokes `CrossEncoderReranker.validate_available()`, lazily imports `from sentence_transformers import CrossEncoder`, and constructs `CrossEncoder(model_name)` only when scoring executes on non-empty candidates.
  - Normalize raw cross-encoder scores monotonically onto `[0.0, 1.0]` using an overflow-safe sigmoid transformation:
    - For finite `x >= 0.0`: `1.0 / (1.0 + math.exp(-x))`
    - For finite `x < 0.0`: `z / (1.0 + z)` where `z = math.exp(x)`
    - Clamp into `[0.0, 1.0]` and reject non-finite (`NaN`/`Inf`) raw scores with `DocpipeError`.
  - Build updated chunks via `dataclasses.replace(chunk, score=norm_score)` (`RetrievedChunk` uses `@dataclass(slots=True)`, so `chunk.__dict__` does not exist) and sort descending (`key=lambda c: c.score, reverse=True`) leveraging Python's stable Timsort before truncating `[:top_k]`.
- **Rationale**: Separating `find_spec` preflight from `_load_cross_encoder()` guarantees missing `[rerank]` fails immediately with `MissingExtraError` (even when `top_k <= 0` or a collection has 0 hits), while installed environments incur zero PyTorch weight-load cost when candidate lists are empty. Overflow-safe sigmoid avoids `OverflowError` on large negative/positive logits and preserves monotonic ranking parity across dense/hybrid search pipelines.
- **Alternatives Considered**:
  - *Eagerly importing `sentence_transformers.CrossEncoder` during preflight*: Rejected because importing `sentence_transformers` pulls PyTorch (~seconds of startup latency and potential third-party deprecation warnings) even when `0` candidates survive threshold filtering.
  - *Min-max scaling within batch*: Rejected because batch-relative min-max destroys comparability across queries (`max=1.0`, `min=0.0` regardless of absolute relevance) and breaks single-candidate batches (`max == min`).

## 3. Child-First Retrieval Ordering & Parent Expansion Sizing (Clarifications Q3 & Q4)

- **Decision**:
  - Append three keyword-only parameters with defaults to `retrieve()` in `src/docpipe_maestro/query/retriever.py` (after `searcher`, preserving positional/keyword stability in `tests/test_api_stability.py` and Constitution Rule #6):
    - `rerank: bool = False`
    - `reranker: str = "cross_encoder"`
    - `rerank_top_n: int = DEFAULT_RERANK_TOP_N` (`20` in `config.py`)
  - When `rerank=True`:
    1. Run `validate_rerank_options(rerank=rerank, reranker=reranker, rerank_top_n=rerank_top_n)` first (alongside `EMBEDDERS`/`STORES`/`SEARCHERS` resolution) -> raises `ValueError` / `RegistryError` / `MissingExtraError` immediately.
    2. Compute expansion-aware candidate fetch depth per **Q4 clarification**:
       - `base_child_k = top_k * 3 if expand_parent else top_k`
       - `child_top_k = max(rerank_top_n, base_child_k)` (so `default top_k=5` fetches `20` candidates regardless of `expand_parent`, while `eval K=10` with `expand_parent=True` fetches `max(20, 30) = 30` candidates preserving full `3x` parent recall headroom).
    3. Fetch `child_matches = searcher_inst.search(question, top_k=child_top_k, ...)` (applies committed `doc_version` filtering on both `default` and `fts5_hybrid`).
    4. Apply optional pre-rerank `threshold` (`[c for c in child_matches if c.score >= threshold]`); if empty, return `[]` without loading reranker weights.
    5. Run `reranker_inst = reranker_cls()` and invoke `child_matches = reranker_inst.rerank(question, child_matches, top_k=len(child_matches) if expand_parent else top_k)`.
       - Note why `top_k=len(child_matches)` when `expand_parent=True`: truncating child chunks to `top_k` *before* parent deduplication could collapse multiple children from 1–2 parent sections and starve parent expansion below `top_k` distinct parents! Passing `len(child_matches)` rescores all surviving candidate children before deduplicating into top `top_k` unique parents ranked by `max(child.score)`.
    6. Continue existing parent expansion (`parent_scores[pid] = max(...)`, fetch parents, sort descending, slice `[:top_k]`) and `_enrich_crossdoc_references(...)` (or return `child_matches` directly when `expand_parent=False`).
- **Rationale**: Strictly enforces Constitution Principle IV ("Search Small, Return Big"), Principle V (`@pytest.mark.reverse`), and Q4 without regressing `Recall@10` or parent section completeness.
- **Alternatives Considered**:
  - *Truncating reranked children to `top_k` before parent expansion*: Rejected because multiple top-scoring chunks from the same section would reduce unique parent count below `top_k`.
  - *Reranking expanded parent sections instead of child chunks*: Rejected because parent sections exceed typical cross-encoder token windows (512 tokens) and violate child-first `007-reranking` design.

## 4. CLI, TOML Configuration & Read-Only Evaluation Schema (`Q2` & `Q3`)

- **Decision**:
  - Expose `--rerank` (`action=argparse.BooleanOptionalAction`, allowing `--no-rerank` to override TOML `rerank = true`), `--reranker`, and `--rerank-top-n` on subparsers `query`, `ask`, and `eval` in `src/docpipe_maestro/cli.py`, reading TOML defaults (`rerank`, `reranker`, `rerank_top_n`) in `build_parser(defaults)` via `_cfg_bool`, `_cfg_str`, and `_cfg_int` (validating `rerank_top_n >= 1` cleanly when parsed/executed).
  - Add explicit keyword-only parameters (`rerank: bool = False`, `reranker: str = "cross_encoder"`, `rerank_top_n: int = DEFAULT_RERANK_TOP_N`) to `evaluate()` in `src/docpipe_maestro/eval/harness.py`, validating them in `_preflight_check` before directory creation, forwarding them to `retrieve(...)`, and applying **Q2 conditional schema rule**:
    - Update `EvalConfig` in `src/docpipe_maestro/types.py` so base fields remain required (`total=True` base class) and `rerank: bool`, `reranker: str`, `rerank_top_n: int` live in an `total=False` subclass (`EvalConfig`).
    - Populate `"rerank"`, `"reranker"`, and `"rerank_top_n"` inside `report["config"]` **only when `rerank=True`**. When `rerank=False`, omit those keys so `docs/eval-baseline.json` and non-reranked `evaluate()` / `eval --json` outputs remain 100% schema- and value-identical (`test_curated_policy_suite_and_baseline_replay` stays green untouched).
    - In `_format_eval_text(report)`, append ` | Reranker: {cfg['reranker']} (top_n={cfg['rerank_top_n']})` to the header line only when `cfg.get("rerank")` is `True`.
- **Rationale**: Honors Constitution Principle III (`cli.py`-only TOML reading), Q2 baseline preservation, and Q3 minimal surface parity.
- **Alternatives Considered**:
  - *Unconditionally adding `rerank`/`reranker`/`rerank_top_n` to `EvalConfig`*: Rejected in Q2 because it breaks strict dict equality with committed `docs/eval-baseline.json` and forces unrelated churn across pre-existing baselines.

## 5. Offline CI Test Strategy & Live Benchmark Ship-or-Revert Protocol (`Q1`)

- **Decision**:
  - **Offline CI Tests (`tests/test_reranker.py`, `tests/test_eval.py`, `tests/test_cli.py`, `tests/test_api_stability.py`, `tests/test_library_purity.py`)**:
    - Never download Hugging Face weights in `pytest`. Mock `_instantiate_cross_encoder` to test real `CrossEncoderReranker` batch formatting `(query, chunk.text)`, thread-safe `_MODEL_CACHE` hits and per-`model_name` isolation on repeat calls, overflow-safe sigmoid normalization, non-finite score rejection, and child-first parent max-score aggregation.
    - Test `MissingExtraError` cleanly using `monkeypatch` on `sys.modules` / `importlib.util.find_spec` so both `[rerank]`-installed CI runs and base installs verify the fail-fast diagnostic before vector lookup or store initialization.
    - Verify `@pytest.mark.reverse` (Release Gate #1) with an offline registered test reranker across all 8 `EXCEPTION_CASES`, and verify `evaluate(..., rerank=True)` leaves `.docpipe/` files byte-identical (0 SHA-256 drift) and only adds rerank config fields when `rerank=True`.
  - **Live Acceptance / Revert Gate (Q1 Local Benchmark Run)**:
    - Prior to shipping/finalizing `007-reranking`, run `docpipe-maestro eval --fixture tests/fixtures/eval_policy_corpus.json` locally against live `ollama/nomic-embed-text` across all 4 cells (`default` without `--rerank`, `default --rerank`, `fts5_hybrid` without `--rerank`, `fts5_hybrid --rerank`) using real `BAAI/bge-reranker-base`.
    - Apply Q1 criterion: retain reranking only if **both** `default` and `fts5_hybrid` individually achieve strictly positive (`> 0.0`) improvement on `Precision@5` **or** strictly positive (`> 0.0`) improvement on both `MRR` and `Precision@1` with zero `Precision@5` regression (`Precision@5 >= baseline`); otherwise execute a clean revert of reranking code while documenting the empirical benchmark results in `docs/eval-baseline.md`.
- **Rationale**: Satisfies both offline deterministic CI (`100%` pass rate, zero network calls) and empirical Constitution Principle I discipline against shipping unhelpful complexity.

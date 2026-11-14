# Phase 1 Data Model: Retrieval Evaluation Harness

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/spec.md) | **Plan**: [plan.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/plan.md) | **Date**: 2026-11-14

All canonical evaluation data shapes are defined once in `src/docpipe_maestro/types.py` (Constitution Principle VII) and re-exported by `src/docpipe_maestro/eval/harness.py` and `src/docpipe_maestro/eval/__init__.py` so consumer modules never drift across Phase 2 evaluation or downstream ranking stages.

## 1. Canonical Data Shapes (`TypedDict`s in `types.py`)

### 1.1 `EvalQuery`
Represents one labeled benchmark test case inside an evaluation fixture (implemented via `_EvalQueryRequired(TypedDict)` + `class EvalQuery(_EvalQueryRequired, total=False)` so callers may omit `notes` under `mypy --strict`, while `load_eval_fixture()` normalizes `notes` to `""`).

| Field | Type | Required | Constraints & Normalization |
| --- | --- | --- | --- |
| `question` | `str` | Yes | Must be a `str` with non-empty content after `.strip()`; stored trimmed or preserved non-blank string. |
| `relevant_ids` | `list[str]` | Yes | Non-empty `list[str]`; every element must be a non-blank `str`; deduplicated preserving first-seen order at load/eval time. |
| `notes` | `str` | Optional in input JSON / caller dicts (`""` default) | Omitted or `None` normalizes to `""`; if present and non-null, must be a `str`. Commonly labels query category (`direct_lookup`, `paraphrased`, `exact_identifier`, `rule_and_exception`). |

### 1.2 `EvalFixture`
Represents a complete validated evaluation test suite loaded from JSON or supplied programmatically (implemented via `_EvalFixtureRequired(TypedDict)` + `class EvalFixture(_EvalFixtureRequired, total=False)` so `collection` and `profile` are optional for programmatic callers under `mypy --strict`, while `load_eval_fixture()` normalizes them to `str`).

| Field | Type | Required | Constraints & Normalization |
| --- | --- | --- | --- |
| `collection` | `str` | Optional in input JSON / caller dicts (`""` default) | Omitted or `None` normalizes to `""`; if non-empty, passes `validate_collection_name` when selected as target collection. |
| `profile` | `str` | Optional in input JSON / caller dicts (`""` default) | Optional informational chunking profile provenance (`""` if omitted); not enforced against collection sources at runtime (`Q3` decision). |
| `queries` | `list[EvalQuery]` | Yes | Must be a non-empty `list` containing at least one valid `EvalQuery`. |

### 1.3 `EvalConfig`
Captures the exact resolved configuration used for an evaluation run so reports are self-describing and reproducible.

| Field | Type | Constraints |
| --- | --- | --- |
| `collection` | `str` | Effective resolved collection name (`explicit > fixture > config > default`). |
| `persist_dir` | `str` | Stringified persistence root path used for read-only store lookup. |
| `embed_model` | `str` | `provider/model` string checked against collection lock. |
| `k_values` | `list[int]` | Normalized strictly ascending list of unique positive cutoff integers (e.g., `[1, 3, 5, 10]`). |
| `expand_parent` | `bool` | Whether child hits expanded to deduplicated parent sections. |
| `follow_crossrefs` | `bool` | Whether cross-document annotations were resolved on retrieved parents. |
| `searcher` | `str` | Registered `SEARCHERS` key (`"default"`, `"fts5_hybrid"`, or custom). |
| `embedder` | `str` | Registered `EMBEDDERS` key (`"default"` or custom). |
| `store` | `str` | Registered `STORES` key (`"default"` or custom). |
| `threshold` | `float \| None` | Optional finite score cutoff in `[0.0, 1.0]`, or `None`. |

### 1.4 `PerQueryResult`
Detailed diagnostic record produced for a single `EvalQuery`.

| Field | Type | Constraints |
| --- | --- | --- |
| `question` | `str` | Evaluated question string from the `EvalQuery`. |
| `notes` | `str` | Query notes/category string carried from the `EvalQuery`. |
| `relevant_ids` | `list[str]` | Deduplicated ground-truth relevant item IDs from the `EvalQuery`. |
| `retrieved_ids` | `list[str]` | Ordered item IDs returned by `retrieve(..., top_k=max(k_values))` (`max(k_values)` upper bound). |
| `retrieved_scores` | `list[float]` | Parallel normalized similarity/RRF scores matching `retrieved_ids` in descending order. |
| `precision_at_k` | `dict[str, float]` | Mapping `str(k) -> Precision@K` in `[0.0, 1.0]` for each cutoff `k` in normalized `k_values`. |
| `recall_at_k` | `dict[str, float]` | Mapping `str(k) -> Recall@K` in `[0.0, 1.0]` (`hits_in_top_k / len(relevant_set)`). |
| `reciprocal_rank` | `float` | `1.0 / rank` of first relevant retrieved ID (1-based), or `0.0` if none retrieved. |

> **String-Key Rationale (`dict[str, float]`)**: JSON objects only permit string keys. Using stringified integer cutoffs (`"1"`, `"3"`, `"5"`, `"10"`) in `precision_at_k` and `recall_at_k` guarantees exact Python equality (`live_report == json.loads(json.dumps(live_report))`) when comparing live runs against `docs/eval-baseline.json`.

### 1.5 `EvalMetricsSummary` & `EvalReport`
Aggregate summary and top-level typed report returned by `evaluate(...)` and emitted by `docpipe-maestro eval --json`.

**`EvalMetricsSummary`**:
| Field | Type | Constraints |
| --- | --- | --- |
| `num_queries` | `int` | Positive count matching `len(per_query)`. |
| `mrr` | `float` | Arithmetic mean of `reciprocal_rank` across all queries (`[0.0, 1.0]`). |
| `precision_at_k` | `dict[str, float]` | Per-`str(k)` arithmetic mean of `Precision@K` across all queries. |
| `recall_at_k` | `dict[str, float]` | Per-`str(k)` arithmetic mean of `Recall@K` across all queries. |

**`EvalReport`**:
| Field | Type | Constraints |
| --- | --- | --- |
| `config` | `EvalConfig` | Effective configuration metadata for the evaluation run. |
| `aggregate` | `EvalMetricsSummary` | Aggregate benchmark metrics across all queries in the fixture. |
| `per_query` | `list[PerQueryResult]` | Ordered per-query diagnostics aligned 1:1 with fixture `queries`. |

### 1.6 `BaselineSnapshot` (`docs/eval-baseline.json`)
Committed side-by-side reference baseline artifact consumed programmatically by subsequent stages.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | `int` | Fixed `1` for baseline artifact format versioning. |
| `fixture` | `str` | Project-relative path (`"tests/fixtures/eval_policy_corpus.json"`). |
| `corpora` | `list[str]` | Packaged corpus directories (`["tests/fixtures/policy_corpus", "tests/fixtures/eval_corpus"]`). |
| `embed_mode` | `str` | `"offline_deterministic"` indicating offline deterministic embeddings (`mock_litellm_offline`). |
| `collection` | `str` | Target evaluation collection (`"eval_policy"`). |
| `profile` | `str` | Chunking profile (`"POLICY"`). |
| `k_values` | `list[int]` | `[1, 3, 5, 10]`. |
| `modes` | `dict[str, EvalReport]` | Side-by-side full `EvalReport` snapshots keyed by `"default"` and `"fts5_hybrid"`. Committed snapshots normalize each mode's `config["persist_dir"]` to canonical `".docpipe"` (avoiding machine-specific temporary paths); offline replay assertions verify exact equality on `aggregate`, `per_query`, and `config` excluding `persist_dir`. |

## 2. Boundary & Validation Rules

| Validation Point | Invalid Input | Error Type & Behavior |
| --- | --- | --- |
| Direct metric calls (`metrics.py`) | `retrieved_ids=[]` or `relevant_ids=[]` | Returns `0.0` cleanly with zero I/O or `ZeroDivisionError`. |
| Direct metric calls & `normalize_k_values` | `k <= 0`, `isinstance(k, bool)`, empty `k_values` | Raises `ValueError` with explicit cutoff message. |
| Cutoff normalization (`Q4`) | Unsorted or duplicate positive cutoffs (e.g., `(10, 3, 3)`) | Normalized automatically to `(3, 10)`. |
| Threshold parameter | `NaN`, `inf`, `< 0.0`, or `> 1.0` | Raises `ValueError`. |
| Fixture file load (`Q2`) | Missing file, invalid JSON, non-object root, empty `queries`, blank `question`, non-list/empty `relevant_ids`, blank ID entry, invalid `notes`/`collection`/`profile` type | Raises `DocpipeError` (wrapping `OSError`/`JSONDecodeError`/`ValueError` as descriptive `DocpipeError` or `ValueError` caught by CLI `main` -> exit `1`). |
| Registry lookup | Unregistered `searcher`, `embedder`, or `store` key | Raises `RegistryError` (`DocpipeError` subclass). |
| Pre-flight collection check | Missing manifest file or zero committed sources in manifest | Raises `DocpipeError` before touching ChromaDB/FTS5 (`0` filesystem mutations). |
| Model lock check | `embed_model` differs from collection `manifest.embed_model` | Raises `ModelMismatchError` (`DocpipeError` subclass). |

## 3. Relationships & Data Flow

```text
EvalFixture JSON ──▶ load_eval_fixture() ──▶ EvalFixture (1..*) EvalQuery
                                                  │
Manifest (read-only) + Searcher + Store           │ evaluate() runs retrieve(..., top_k=max(K))
      │                                           ▼
      └──────────────────────────────▶ PerQueryResult [*] ──▶ EvalMetricsSummary ──▶ EvalReport
                                                                                         │
                                                                 modes["default"|"fts5_hybrid"]
                                                                                         ▼
                                                                              BaselineSnapshot (JSON)
```

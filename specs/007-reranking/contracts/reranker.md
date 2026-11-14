# Interface Contracts: Cross-Encoder Reranking

**Feature**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md) | **Date**: 2026-11-14

---

## 1. Extension Registry & `CrossEncoderReranker` (`docpipe_maestro.query.reranker`)

### Module Exports (`src/docpipe_maestro/query/reranker/__init__.py`)

```python
RERANKERS: Registry[Reranker]
register_reranker = RERANKERS.register
# Lazy built-in declaration (no eager sentence_transformers import):
# RERANKERS.register_lazy("cross_encoder", "docpipe_maestro.query.reranker.cross_encoder", "CrossEncoderReranker")

__all__ = [
    "RERANKERS",
    "CrossEncoderReranker",
    "register_reranker",
    "validate_rerank_options",
]
```

- Accessing `docpipe_maestro.register_reranker` or importing `docpipe_maestro.query.reranker` MUST NOT import `sentence_transformers` or `torch`.
- `CrossEncoderReranker` is lazily resolved via `__getattr__` and registered under `"cross_encoder"`.

### Concrete Strategy (`src/docpipe_maestro/query/reranker/cross_encoder.py`)

```python
@RERANKERS.register("cross_encoder")
class CrossEncoderReranker:
    name: str = "cross_encoder"

    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL) -> None: ...

    @classmethod
    def validate_available(cls) -> None: ...

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]: ...
```

Behavioral guarantees:
- Implements `docpipe_maestro.query.stages.Reranker` Protocol cleanly (`isinstance(CrossEncoderReranker(), Reranker) is True`).
- `validate_available()` inspects `sys.modules` and `importlib.util.find_spec("sentence_transformers")` without importing `sentence_transformers`/`torch`. Raises `MissingExtraError("Cross-encoder reranking requires the 'rerank' extra: pip install 'docpipe-maestro[rerank]'")` when unavailable.
- `_instantiate_cross_encoder(model_name)` calls `CrossEncoderReranker.validate_available()`, lazily imports `CrossEncoder` from `sentence_transformers`, and constructs `CrossEncoder(model_name)`.
- `_load_cross_encoder(model_name)` checks and populates module-level `_MODEL_CACHE: dict[str, Any]` per `model_name` under a `threading.Lock()`, delegating cold initialization to `_instantiate_cross_encoder(model_name)`.
- `rerank(query, chunks, *, top_k)`:
  - If `not chunks or top_k <= 0`: returns `[]` immediately without calling `_load_cross_encoder` or `CrossEncoder.predict`.
  - When non-empty (`chunks` and `top_k > 0`), calls `_load_cross_encoder(self._model_name)`, which enforces `validate_available()` so direct `CrossEncoderReranker().rerank(...)` calls outside `retrieve()` still raise `MissingExtraError` when `[rerank]` is missing.
  - Evaluates `[(query, chunk.text) for chunk in chunks]` in a single batch call.
  - Normalizes each finite raw logit monotonically onto `[0.0, 1.0]` using overflow-safe sigmoid; raises `DocpipeError` on non-finite logits or length mismatch.
  - Copies chunks via `dataclasses.replace(chunk, score=norm_score)` without mutating input chunk objects.
  - Returns top `top_k` chunks sorted in descending order of normalized score (preserving original relative order on ties).

### Shared Preflight Validator

```python
def validate_rerank_options(
    *,
    rerank: bool,
    reranker: str,
    rerank_top_n: int,
) -> type[Reranker] | None:
```

- Always rejects `isinstance(rerank_top_n, bool)` or `not isinstance(rerank_top_n, int)` or `rerank_top_n <= 0` with `ValueError("rerank_top_n must be a positive integer >= 1")`.
- When `rerank` is `False`, returns `None` without resolving `RERANKERS` or checking optional extras.
- When `rerank` is `True`, resolves `reranker_cls = RERANKERS.resolve(reranker)` (raising `RegistryError` if unregistered), invokes `validate_available()` if present on `reranker_cls` (raising `MissingExtraError` if `[rerank]` absent), and returns `reranker_cls`.

---

## 2. Phase 2 Retrieval Contract (`docpipe_maestro.query.retriever.retrieve`)

Signature extension (appending keyword-only parameters with defaults per Constitution Quality Gates):

```python
def retrieve(
    question: str,
    *,
    collection: str = DEFAULT_COLLECTION,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    top_k: int = DEFAULT_TOP_K,
    threshold: float | None = None,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
    rerank: bool = False,
    reranker: str = "cross_encoder",
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
) -> list[RetrievedChunk]:
```

Contract guarantees:
- Top-level `docpipe_maestro.__all__` retains its exact `33` symbols (`tests/test_api_stability.py` updated strictly for the 3 appended `retrieve()` keyword-only parameters).
- When `rerank=False` (default): execution path, returned chunks, and scores are 100% identical to pre-007 behavior (`reranker` is never resolved or checked unless `rerank_top_n <= 0`).
- When `rerank=True`:
  1. `validate_rerank_options(rerank=True, reranker=reranker, rerank_top_n=rerank_top_n)` runs upfront alongside `EMBEDDERS`/`STORES`/`SEARCHERS` resolution.
  2. Candidate fetch depth is `max(rerank_top_n, top_k * 3)` if `expand_parent` else `max(rerank_top_n, top_k)`.
  3. Searcher fetches committed child chunks up to that candidate depth; pre-rerank `threshold` filter applies immediately before reranking.
  4. If zero children survive, returns `[]` without invoking `rerank()`.
  5. Otherwise calls `reranker_inst.rerank(question, child_matches, top_k=len(child_matches) if expand_parent else top_k)`.
  6. If `expand_parent=True`, groups all reranked children by `parent_id` using `max(child.score)`, fetches unique top `top_k` parents sorted descending by score, and runs `_enrich_crossdoc_references` when `follow_crossrefs=True`.

---

## 3. Evaluation Harness Contract (`docpipe_maestro.eval.harness.evaluate`)

Signature extension:

```python
def evaluate(
    fixture: str | Path | EvalFixture,
    *,
    collection: str | None = None,
    persist_dir: str | Path = DEFAULT_PERSIST_DIR,
    embed_model: str = DEFAULT_EMBED_MODEL,
    k_values: Sequence[int] = DEFAULT_EVAL_K_VALUES,
    expand_parent: bool = True,
    follow_crossrefs: bool = True,
    threshold: float | None = None,
    embedder: str = "default",
    store: str = "default",
    searcher: str = "default",
    rerank: bool = False,
    reranker: str = "cross_encoder",
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    **retrieve_kwargs: Any,
) -> EvalReport:
```

Contract guarantees:
- `_preflight_check` calls `validate_rerank_options(rerank=rerank, reranker=reranker, rerank_top_n=rerank_top_n)` BEFORE manifest loading or store access.
- Calls `retrieve(..., rerank=rerank, reranker=reranker, rerank_top_n=rerank_top_n, **retrieve_kwargs)` read-only with `top_k=max(norm_k)`.
- Conditional `EvalConfig` keys (Clarification **Q2**):
  - `rerank=False`: `config` dict contains ONLY the 10 pre-007 baseline keys (`docs/eval-baseline.json` remains byte-identical).
  - `rerank=True`: `config` dict additionally sets `"rerank": True`, `"reranker": reranker`, and `"rerank_top_n": rerank_top_n`.

---

## 4. CLI & TOML Config Contract (`docpipe_maestro.cli`)

Subcommands updated: `query`, `ask`, and `eval` (`p_query`, `p_ask`, `p_eval`).

| CLI Flag | Action / Type | Default Precedence | Description |
| --- | --- | --- | --- |
| `--rerank` / `--no-rerank` | `BooleanOptionalAction` | CLI > TOML `rerank` > `False` | Opt into or explicitly disable post-retrieval reranking. |
| `--reranker` | `str` | CLI > TOML `reranker` > `"cross_encoder"` | Registered `RERANKERS` strategy key. |
| `--rerank-top-n` | `int` | CLI > TOML `rerank_top_n` > `20` | Pre-rerank candidate child pool floor (`>= 1`). |

Output & Exit Behavior:
- Parser initialization and `--help` MUST NOT import `sentence_transformers` or `torch`.
- Missing `[rerank]` extra (`MissingExtraError`), unregistered `reranker` (`RegistryError`), or `rerank_top_n <= 0` (`ValueError`) exit with status `1` and single-line `Error: ...` on `stderr`.
- `_format_eval_text(report)` includes `| Reranker: <name> (top_n=<n>)` on line 1 only when `report["config"].get("rerank")` is `True`.

---

## 5. Ship-or-Revert Governance Gate (`FR-009` / Clarification `Q1`)

Prior to finalizing the feature for merge, execute live local benchmarking with Ollama (`nomic-embed-text`) and local `CrossEncoderReranker` (`BAAI/bge-reranker-base`) on `tests/fixtures/eval_policy_corpus.json`:
1. Measure `default` (dense) with `--no-rerank` vs `--rerank`.
2. Measure `fts5_hybrid` with `--no-rerank` vs `--rerank`.
3. **Retain criterion**: **Both** `default` and `fts5_hybrid` must individually achieve strictly positive (`> 0.0`) improvement on `Precision@5` **or** strictly positive (`> 0.0`) improvement on both `MRR` and `Precision@1` with zero `Precision@5` regression (`Precision@5 >= baseline`) against their respective live non-reranked runs.
4. **Revert action**: If either mode fails this criterion, revert implementation and feature docs cleanly and document empirical metrics and rationale in `docs/eval-baseline.md`.

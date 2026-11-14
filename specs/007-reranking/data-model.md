# Data Model: Cross-Encoder Reranking

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-14

All public shared types and configuration structures live canonically in `src/docpipe_maestro/types.py` (with static constants in `src/docpipe_maestro/config.py`) per Constitution Principle VII.

---

## 1. Static Configuration Constants (`src/docpipe_maestro/config.py`)

| Constant | Type | Default | Description |
| --- | --- | --- | --- |
| `DEFAULT_RERANK_TOP_N` | `int` | `20` | Default pre-rerank candidate child pool limit (`>= 1`). |
| `DEFAULT_RERANK_MODEL` | `str` | `"BAAI/bge-reranker-base"` | Default Hugging Face cross-encoder model identifier instantiated by `CrossEncoderReranker`. |

---

## 2. Rerank Retrieval Parameters & Validation Rules

Used by `retrieve(...)` (`query/retriever.py`), `evaluate(...)` (`eval/harness.py`), and parsed/validated via `docpipe_maestro.query.reranker.validate_rerank_options`.

| Field | Type | Default | Validation / Constraints |
| --- | --- | --- | --- |
| `rerank` | `bool` | `False` | Strict boolean flag (`bool(rerank)`). When `False`, `reranker` and dependency availability are not loaded or executed (unless `rerank_top_n` is explicitly invalid). |
| `reranker` | `str` | `"cross_encoder"` | Must resolve via `RERANKERS.resolve(reranker)` when `rerank=True`; raises `RegistryError` if unregistered. |
| `rerank_top_n` | `int` | `20` (`DEFAULT_RERANK_TOP_N`) | Must be an integer (`not isinstance(val, bool)`) strictly `>= 1`; raises `ValueError` otherwise. Expansion-aware candidate fetch depth computes `max(rerank_top_n, top_k * 3)` when `expand_parent=True` or `max(rerank_top_n, top_k)` when `expand_parent=False`. |

Preflight dependency rule:
- When `rerank=True` and the resolved reranker class defines a dependency availability hook (such as `CrossEncoderReranker.validate_available()`), it executes upfront before manifest/collection short-circuits and raises `MissingExtraError` if `sentence_transformers` is absent.

---

## 3. Scored Chunk Transition (`RetrievedChunk`)

Existing `RetrievedChunk` (`src/docpipe_maestro/types.py`) uses `@dataclass(slots=True)`:

| Attribute | Pre-Rerank Value (Child) | Post-Rerank Value (Child) | Post-Expansion Value (Parent) |
| --- | --- | --- | --- |
| `id` | Content-addressed child ID (`<source>::c::<idx>`) | Same child ID (never duplicated) | Unique parent ID (`<source>::p::<idx>`) |
| `parent_id` | Non-empty parent ID | Same non-empty parent ID | `None` |
| `text` | Child passage text (with `[Source \| Section]` header) | Unchanged child passage text | Enclosing parent section text (`+ [Crossref ...]` notes if enabled) |
| `score` | Searcher cosine or normalized RRF score in `[0.0, 1.0]` | Overflow-safe sigmoid `1 / (1 + exp(-logit))` clamped to `[0.0, 1.0]` | `max(child.score)` across all reranked child matches mapped to that parent |

Mutation safety rule:
- Rerankers MUST produce updated `RetrievedChunk` instances via `dataclasses.replace(chunk, score=normalized_score)` rather than mutating inputs in place or reading `__dict__` (which fails on `slots=True`).
- Raw non-finite logits (`math.isnan` / `math.isinf`) MUST raise `DocpipeError` rather than silently emitting invalid scores.

---

## 4. Conditional Evaluation Config Schema (`EvalConfig` in `src/docpipe_maestro/types.py`)

Split into required baseline fields plus optional (`total=False`) rerank metadata (Clarification **Q2**) so non-reranked `EvalReport["config"]` dictionaries remain byte-identical to committed baselines:

```python
class _EvalConfigRequired(TypedDict):
    collection: str
    persist_dir: str
    embed_model: str
    k_values: list[int]
    expand_parent: bool
    follow_crossrefs: bool
    searcher: str
    embedder: str
    store: str
    threshold: float | None


class EvalConfig(_EvalConfigRequired, total=False):
    rerank: bool
    reranker: str
    rerank_top_n: int
```

Emission rule in `evaluate(...)`:
- When `rerank=False`: omit `"rerank"`, `"reranker"`, and `"rerank_top_n"` keys completely.
- When `rerank=True`: set `"rerank": True`, `"reranker": reranker`, and `"rerank_top_n": rerank_top_n`.

---

## 5. Child-First Retrieval State Flow (When `rerank=True`)

```text
retrieve(question, ..., rerank=True, reranker, rerank_top_n)
  │
  ├─► Preflight validate:
  │     validate_rerank_options(rerank=True, reranker=reranker, rerank_top_n=rerank_top_n)
  │     (validates rerank_top_n >= 1, resolves RERANKERS, checks MissingExtraError)
  │
  ├─► Load manifest & check model lock (returns [] if empty sources or top_k <= 0)
  │
  ├─► Compute candidate pool limit:
  │     child_top_k = max(rerank_top_n, top_k * 3) if expand_parent else max(rerank_top_n, top_k)
  │
  ├─► Execute active searcher (default or fts5_hybrid) -> committed child_matches[:child_top_k]
  │
  ├─► Apply pre-rerank threshold filter (score >= threshold); return [] if none survive
  │
  ├─► Instantiate reranker_cls() & call:
  │     rerank_limit = len(child_matches) if expand_parent else top_k
  │     child_matches = reranker_inst.rerank(question, child_matches, top_k=rerank_limit)
  │
  ├─► If not expand_parent:
  │     return child_matches[:top_k]
  │
  └─► Else (expand_parent=True):
        aggregate parent_scores[pid] = max(child.score) -> fetch parents -> sort[:top_k]
        -> _enrich_crossdoc_references() if follow_crossrefs
```

# Contract: Evaluation Metrics, Harness API, CLI & Baseline Artifacts

**Feature**: [spec.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/spec.md) | **Plan**: [plan.md](file:///home/maestro/LifeFolder/10_PUBLIC/projects/docpipe-maestro/specs/006-eval-harness/plan.md) | **Date**: 2026-11-14

## 1. Pure Metrics Module (`src/docpipe_maestro/eval/metrics.py`)

Zero third-party imports, zero filesystem I/O, zero network calls, zero mutation of caller inputs.

```python
def precision_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: AbstractSet[str] | Sequence[str],
    k: int,
) -> float: ...


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: AbstractSet[str] | Sequence[str],
    k: int,
) -> float: ...


def reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevant_ids: AbstractSet[str] | Sequence[str],
) -> float: ...


def normalize_k_values(k_values: Sequence[int]) -> tuple[int, ...]: ...
```

### Metric Guarantees

- `k` in `precision_at_k` / `recall_at_k`: raises `ValueError` if `isinstance(k, bool)` or `k <= 0`.
- `precision_at_k`: returns `0.0` when `retrieved_ids` or `relevant_ids` is empty; otherwise computes `len(set(retrieved_ids[:k]) & relevant_set) / k`. Fixed-cutoff denominator `k` applies even when `len(retrieved_ids) < k`.
- `recall_at_k`: returns `0.0` when `retrieved_ids` or `relevant_ids` is empty; otherwise computes `len(set(retrieved_ids[:k]) & relevant_set) / len(relevant_set)` (`Q1` standard IR definition).
- `reciprocal_rank`: returns `0.0` when `retrieved_ids` or `relevant_ids` is empty or has zero hits; otherwise returns `1.0 / rank` for the 1-based position `rank` of the first element of `retrieved_ids` in `relevant_set`.
- `normalize_k_values`: raises `ValueError` if `k_values` is empty or contains any `bool` or integer `<= 0`; returns deduplicated positive integers sorted ascending (e.g., `[10, 3, 3]` -> `(3, 10)`, `Q4` decision).

---

## 2. Evaluation Harness API (`src/docpipe_maestro/eval/harness.py` & `docpipe_maestro.eval`)

Top-level `docpipe_maestro.__all__` (`33` symbols) remains unchanged. Consumers import from `docpipe_maestro.eval` or `docpipe_maestro.eval.harness`:

```python
DEFAULT_EVAL_K_VALUES: tuple[int, ...] = (1, 3, 5, 10)


def load_eval_fixture(fixture: str | Path | EvalFixture) -> EvalFixture: ...


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
    **retrieve_kwargs: Any,
) -> EvalReport: ...
```

### Runner Execution & Precedence Contract

1. **Numeric & Option Validation**: Validate `k_values` via `normalize_k_values(k_values)` and `threshold` (`None` or finite `float` in `[0.0, 1.0]`).
2. **Fixture Loading & Validation (`Q2`)**: Parse and validate JSON file or in-memory `EvalFixture` before touching storage:
   - Missing/unreadable/invalid JSON -> raises `DocpipeError`.
   - Empty `queries`, blank `question`, or query with empty/blank `relevant_ids` -> raises `DocpipeError`.
3. **Collection Precedence (`Q3`)**: Resolve `effective_collection` strictly in order:
   1. Explicit non-`None` `collection` argument (`validate_collection_name` applied even if empty string);
   2. Else non-empty trimmed `fixture["collection"]` (if non-empty);
   3. Else `DEFAULT_COLLECTION` (`"default"`).
   - `cli.py` handles TOML fallback (`explicit --collection > fixture collection > TOML config > DEFAULT_COLLECTION`) via `load_eval_fixture()` before calling `evaluate(..., collection=resolved_collection)`, keeping configuration discovery strictly out of `docpipe_maestro.eval`.
   - `fixture["profile"]` is retained strictly as provenance and never rejects collections with differing source profiles.
4. **Early Stage Selector Validation**: If `embedder != "default"`, `store != "default"`, or `searcher != "default"` (`"fts5_hybrid"` also resolves cleanly), validate registered keys via `EMBEDDERS.resolve` / `STORES.resolve` / `SEARCHERS.resolve` (`RegistryError` on unknown key).
5. **Read-Only Store Pre-Flight (`FR-003`)**:
   - Check `manifest_path(persist_path, effective_collection).exists()` without instantiating `ChromaStore` or creating directories. Missing manifest raises `DocpipeError`.
   - Call `load_manifest(persist_path, effective_collection)` and `check_model_lock(manifest, embed_model)` (`ModelMismatchError` if collection is locked to a different embedding model).
   - If `not manifest.sources` (zero committed documents), raise `DocpipeError`.
6. **Single-Pass Query Evaluation (`SC-001`, `SC-002`)**:
   - For each normalized `EvalQuery`, call `retrieve(query["question"], collection=effective_collection, persist_dir=persist_path, embed_model=embed_model, top_k=max(norm_k), threshold=threshold, expand_parent=expand_parent, follow_crossrefs=follow_crossrefs, embedder=embedder, store=store, searcher=searcher, **retrieve_kwargs)` **once**.
   - Extract `retrieved_ids = [chunk.id for chunk in chunks]` and `retrieved_scores = [float(chunk.score) for chunk in chunks]`.
   - Compute `precision_at_k` (`{str(k): ...}`), `recall_at_k` (`{str(k): ...}`), and `reciprocal_rank` strictly on `retrieved_ids` vs `query["relevant_ids"]` with no hidden `parent_id` rewriting.
7. **Aggregate Report**: Return typed `EvalReport` (`config`, `aggregate`, `per_query`) containing exact float averages over all queries. Persistence directory bytes must match pre-run hashes 100%.

---

## 3. CLI `eval` Subcommand (`src/docpipe_maestro/cli.py`)

```text
docpipe-maestro [--config PATH] [--no-config] [--collection NAME] [--persist-dir DIR]
  eval --fixture PATH
       [--collection NAME]
       [--persist-dir DIR]
       [--config PATH]
       [--no-config]
       [--k INT [INT ...]]
       [--embed-model PROVIDER/MODEL]
       [--searcher KEY]
       [--expand-parent | --no-expand-parent]
       [--json]
```

### CLI Contract Guarantees

- **Startup Purity (`FR-006`)**: `build_parser()` and `--help` MUST NOT import `docpipe_maestro.eval.harness`, `chromadb`, `litellm`, `pypdf`, `docx`, or `bs4`.
- **Global Flags**: Uses `parents=[common]` so `--collection`, `--persist-dir`, `--config`, `--no-config` work cleanly before or after `eval`.
- **Explicit Collection Tracking (`Q3`)**: Inside `_handle_eval`, lazy-import and call `load_eval_fixture(args.fixture)`, resolve target collection strictly as `args.collection` (if `--collection` was passed explicitly) `>` non-empty `loaded_fixture["collection"]` `>` TOML `collection` `>` `"default"`, and forward `loaded_fixture` and resolved `collection` into `evaluate(...)`.
- **TOML Defaults**: `persist_dir`, `embed_model`, `searcher` inherit TOML defaults identically to `query` when omitted on CLI.
- **Cutoff Flag `--k`**: Accepts single values (`--k 5`), space-separated values (`--k 1 3 5 10`), and repeated flags (`--k 1 --k 3 --k 5`) via `action="extend", nargs="+", type=int`; defaults to `(1, 3, 5, 10)` when omitted.
- **JSON Output (`--json`)**: Prints `json.dumps(report, indent=2)` directly to `stdout` (`EvalReport` shape) and exits `0`.
- **Human-Readable Output (default)**: Prints concise run header (`Collection`, `Model`, `Searcher`, `Expand Parent`, `Queries`, `MRR`), an aligned `K | Precision@K | Recall@K` table, and brief per-query diagnostic lines (`[rank/hit] MRR=... | P@max=... | question`), and exits `0`.
- **Error Handling & Exit Status (`FR-005`)**: Catches `(DocpipeError, ValueError, TypeError)` in `cli.main`, prints a single-line `"Error: <message>"` to `stderr`, and returns `1`. Regression-threshold failure exit flags are excluded in this stage.

---

## 4. Curated Benchmark & Baseline Artifacts

- **Fixture Corpus**:
  - `tests/fixtures/policy_corpus/` (`hr_leave_policy.md`, `travel_expenses_policy.md`): **preserved unmodified** (`Release Gate #1`).
  - `tests/fixtures/eval_corpus/`: complementary self-contained synthetic Markdown policy documents (`information_security_policy.md`, `incident_response_runbook.md`, `procurement_vendor_policy.md`) parsed under `"POLICY"` profile.
- **Curated Query Fixture (`tests/fixtures/eval_policy_corpus.json`)**:
  - Conforms to `EvalFixture` schema (`collection: "eval_policy"`, `profile: "POLICY"`, `queries: [...]`).
  - Contains `>= 20` verified queries distributed across `direct_lookup`, `paraphrased`, `exact_identifier`, and `rule_and_exception` (`>= 3` rule+exception queries whose `relevant_ids` contain exact content-addressed parent section IDs verified against deterministic `POLICY` ingestion).
- **Baseline Reports (`docs/eval-baseline.json`, `docs/eval-baseline.md`)**:
  - `docs/eval-baseline.json` conforms to `BaselineSnapshot` (`schema_version=1`, `modes={"default": EvalReport, "fts5_hybrid": EvalReport}`) generated strictly offline via `mock_litellm_offline` / `deterministic_embed`, with each mode's `config["persist_dir"]` normalized to canonical `".docpipe"` so offline replay compares `aggregate`, `per_query`, and `config` (excluding runtime `persist_dir`) bit-for-bit across environments.
  - `docs/eval-baseline.md` presents the side-by-side comparison table (`default` dense vs `fts5_hybrid`), query-category highlights, corpus manifest, and exact offline reproduction command.

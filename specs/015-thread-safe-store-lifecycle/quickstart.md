# Quickstart Validation Guide: Thread-Safe Persistent Vector Store Lifecycle

**Feature Branch**: `fix/015-store-lifecycle-thread-safety`  
**Plan**: [plan.md](./plan.md) | **Contracts**: [store-lifecycle.md](./contracts/store-lifecycle.md)

All validation scenarios run **100% offline** in a `minimal-core` or full dev environment with zero network access or API keys.

---

## 1. Prerequisites

```bash
uv sync --locked --all-extras --group dev
# Or minimal-core parity check:
# uv sync --locked --group dev
```

---

## 2. Targeted Concurrency, Lifecycle & Rollback Verification

### Scenario A — True Fresh-Subprocess Cold-Start Retrieval (`SC-001`, `FR-009`)
1. Run `pytest tests/test_retriever.py -k cold_start -v`.
2. **What it verifies**:
   - Parent fixture ingests policy chunks into a temporary persisted collection using `mock_litellm_offline`.
   - Across multiple fresh `subprocess.run([sys.executable, ...])` executions, each subprocess patches `litellm.embedding` cleanly without importing `chromadb`, asserts `"chromadb" not in sys.modules`, spawns 4 `threading.Barrier(4)` worker threads calling `retrieve(..., top_k=1, local_only=True)` concurrently, and asserts **100%** success with zero exceptions and identical retrieved results.

### Scenario B — Concurrent Lifecycle, Partial-Init Rollback & Non-Blocking Reads (`SC-002`, `SC-003`, `FR-003`, `FR-010`)
1. Run `pytest tests/test_store.py -v`.
2. **What it verifies**:
   - Barrier-synchronized concurrent `VectorStore(persist_dir, collection)` initialization (same collection, multiple collections, multiple directories) + overlapping `close()` / `reset_collection()` cycles leave `_active_systems_for(persist_dir)` cleanly managed down to `[]` after final close.
   - Fault-injected `chromadb.PersistentClient` failure wraps in `DocpipeError("Invalid or unusable collection ...")` preserving `__cause__`, skips client teardown (`_client is None`), and leaves zero orphaned systems.
   - Fault-injected `get_or_create_collection` failure (including concurrent secondary `client.close()` failure) triggers serialized rollback leaving `_active_systems_for` empty and surfacing the primary `DocpipeError`.
   - Steady-state concurrent `query_children()` calls on already-open store handles execute concurrently without waiting on `_CHROMA_CLIENT_LOCK`.

---

## 3. Contract & Full Release Gate Verification (`FR-006`, `FR-008`, `SC-004`, `SC-005`)

Run the project's full quality, purity, API stability, and safety checks after implementation:

```bash
# 1. API exports (36 locked), Store plugin compatibility & lazy-import startup purity
uv run --no-sync pytest tests/test_api_stability.py tests/test_library_purity.py -v

# 2. Formatting, lint, security lint & strict typing
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync ruff check --select S src/
uv run --no-sync mypy src tests

# 3. Mandatory Release Gates (#1 Exception Preservation & #2 PII Protection)
uv run --no-sync pytest -m reverse -v
uv run --no-sync pytest -m pii -v

# 4. Full offline test suite + coverage (>= 80%)
LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov

# 5. Minimal-core CI subset verification
LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -q \
  --ignore=tests/test_extended_complex.py \
  --ignore=tests/test_intake_clean.py \
  --ignore=tests/test_intake_formats_optional.py \
  --ignore=tests/test_security_hardening.py \
  --ignore=tests/test_pii_safety.py
```

**Expected Result**: All checks pass with exit code `0`, zero failures, zero skipped/relaxed assertions, and unchanged lazy-startup & public API contracts.

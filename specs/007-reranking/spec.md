# Feature Specification: Cross-Encoder Reranking

**Feature Branch**: `feat/007-reranking`  
**Created**: 2026-11-14  
**Status**: Draft  
**Input**: User description: "Add an optional local cross-encoder reranking stage to the Phase 2 retrieval pipeline, validated quantitatively against the committed evaluation baselines (`docs/eval-baseline.json`)."

## Clarifications

### Session 2026-11-14

- Q: Which benchmark comparison mode and ranking metrics must improve to retain cross-encoder reranking instead of reverting it? → A: Retain reranking only if live local-embedding evaluation shows **both** default semantic search (`default`) and hybrid search (`fts5_hybrid`) individually achieve strictly positive (`> 0.0`) improvement on `Precision@5` **or** strictly positive (`> 0.0`) improvement on both `MRR` and `Precision@1` with zero `Precision@5` regression (`Precision@5 >= baseline`) against their respective live non-reranked runs on the curated suite; if either mode regresses or fails this criterion, cleanly revert reranking and record the benchmark findings in the baseline report.
- Q: How should evaluation reports record reranking settings while preserving compatibility with existing committed baselines? → A: Include reranking configuration fields (`rerank`, reranker strategy, and candidate pool depth) in evaluation reports only when reranking is enabled, leaving non-reranked report structures and committed baseline artifacts completely unchanged.
- Q: Which reranking controls should be exposed through CLI flags and TOML configuration beyond the core `--rerank` opt-in toggle? → A: Expose rerank enable/disable toggle (`rerank`), reranker strategy selection (`reranker`), and candidate pool depth (`rerank_top_n`) as CLI options and TOML configuration defaults across query, question-answering, and evaluation workflows, keeping underlying model-weight selection programmatic on the reranker strategy itself.
- Q: How many candidate child chunks should be fetched before reranking when parent expansion is active and the requested `top_k` interacts with `rerank_top_n`? → A: Fetch an expansion-aware minimum candidate pool: `max(rerank_top_n, requested top_k * 3)` when parent expansion is enabled, or `max(rerank_top_n, requested top_k)` when parent expansion is disabled, preserving full `3x` parent recall headroom during high-cutoff evaluation (`K=10`) while still reranking `20` candidates at the default top `5`.

## Constitution Check

All requirements comply with `.specify/memory/constitution.md` (`v1.2.2`, Principles I–VII and Quality Gates): opt-in `rerank=False` scope isolation, lazy Phase 2 boundaries, CLI-only TOML configuration, child-first parent expansion, Release Gate #1 (`@pytest.mark.reverse`), local-first execution, canonical schema definitions in `types.py`, and mandatory full test suite pass. Full gate matrix verified in [plan.md](plan.md#constitution-check).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Opt-In Local Child-First Reranking in Retrieval (Priority: P1)

A user or caller enables optional post-retrieval reranking when searching a collection (using either standard semantic search or hybrid lexical+vector search), receiving top-ranked parent sections (or child chunks when parent expansion is disabled) reordered by deeper query-passage relevance scoring without sacrificing exception preservation.

**Why this priority**: Initial bi-encoder vector similarity and lexical fusion capture broad topical relevance and exact identifiers effectively, yet struggle to distinguish fine-grained multi-term interactions and negation among top candidates—especially on paraphrased policy questions. Rescoring candidate child chunks before parent expansion delivers the core ranking precision improvement while preserving complete policy rules.

**Independent Test**: Can be fully tested offline against a populated test collection using a deterministic test reranker double, confirming candidate pool sizing, pre-rerank threshold filtering, normalized `[0.0, 1.0]` score bounds, parent deduplication scored by highest matching child score, cross-document reference enrichment, and exception-preservation safety compliance.

**Acceptance Scenarios**:

1. **Given** a populated collection with committed documents and a caller opting into reranking (with either standard semantic search or hybrid search), **When** retrieval executes, **Then** the system retrieves a candidate pool of committed child chunks, applies committed document version filtering and any caller-supplied score threshold before reranking, rescores those surviving candidates via the selected local reranker strategy with normalized `[0.0, 1.0]` relevance scores, and returns deduplicated parent sections ordered by each parent's highest reranked child score with cross-document citations preserved.
2. **Given** a policy collection containing rules paired with exception clauses (`except`, `unless`, `not entitled`, `subject to`, `provided that`), **When** retrieval runs with reranking enabled and parent expansion active, **Then** every retrieved rule section retains its complete exception clause context and passes the mandatory exception-preservation safety gate.
3. **Given** a caller who disables parent expansion while enabling reranking, **When** retrieval executes, **Then** the system returns the top reranked child chunks directly in descending normalized relevance order without parent expansion.
4. **Given** repeated queries issued consecutively using the same local reranking model configuration, **When** reranking runs back-to-back within a session or evaluation batch, **Then** loaded model state is reused across calls rather than reloaded per query.

---

### User Story 2 - Lean Default Install & Fail-Fast Missing Dependency Diagnostics (Priority: P2)

A user runs the core tool without optional reranking packages installed; default retrieval, question answering, evaluation, and startup commands behave identically with zero extra install footprint or model-loading delay, while explicitly requesting reranking when optional components are absent fails immediately with a clear installation guidance message.

**Why this priority**: Keeping default installs lean ensures out-of-the-box local workflows stay fast and lightweight on standard CPU hardware, while clear opt-in diagnostics prevent cryptic import failures for users trying the optional capability.

**Independent Test**: Can be tested in isolation by executing normal retrieval and command-line startup commands with optional reranking packages absent—confirming identical behavior and lightweight startup—followed by invoking opt-in reranking (or requesting an unknown reranker strategy) to verify immediate, actionable single-line error reporting.

**Acceptance Scenarios**:

1. **Given** an installation without optional reranking dependencies, **When** a user runs default querying, question answering, evaluation, or CLI help commands without requesting reranking, **Then** every operation completes identically to baseline behavior without loading heavy reranking packages or failing.
2. **Given** an installation missing the optional reranking dependency extra, **When** a user explicitly enables reranking via command-line options or library retrieval calls, **Then** execution halts immediately before model execution with an actionable missing-dependency error explaining how to install the optional extra (and the command line exits with status `1` and a concise single-line message without stack traces).
3. **Given** a caller specifying an unknown reranker strategy name or an invalid candidate pool limit (`<= 0`), **When** retrieval or evaluation starts, **Then** the system rejects the invalid configuration immediately with a clear error before scoring runs.

---

### User Story 3 - Evaluation Integration & Baseline-Gated Acceptance (Priority: P3)

A maintainer evaluates opt-in reranking through the read-only evaluation workflow on the curated policy corpus baselines for both default semantic search and hybrid search, retaining the reranking stage only when **both** search modes individually demonstrate strictly positive (`> 0.0`) quality improvement (`Precision@5 > baseline`, or both `MRR > baseline` and `Precision@1 > baseline` with zero `Precision@5` regression) on live local embeddings, or cleanly reverting it with findings documented if quality fails to improve.

**Why this priority**: Adding retrieval complexity without verified ranking gain violates project scope discipline. Integrating reranking cleanly into the read-only evaluation workflow creates an objective ship-or-revert gate grounded in reproducible benchmarks.

**Independent Test**: Can be tested offline by invoking both programmatic and command-line evaluation workflows with a deterministic test reranker double, verifying exact forwarding of rerank options, zero persisted storage mutations, and accurate baseline comparison reporting.

**Acceptance Scenarios**:

1. **Given** a valid evaluation fixture and populated collection, **When** a maintainer executes programmatic or command-line evaluation with reranking enabled (across default semantic or hybrid search), **Then** evaluation forwards reranking options consistently, leaves all persisted index and manifest directories completely unmodified (`0` byte changes), and records reranking configuration parameters alongside the run configuration and ranking metrics (`Precision@K`, `Recall@K`, and `MRR`); when reranking is disabled, evaluation report structure remains unchanged.
2. **Given** the curated policy benchmark corpus evaluated with live local embeddings across both default semantic search and hybrid search, **When** maintainers compare live non-reranked runs against the local default cross-encoder reranker, **Then** reranking is retained only if **both** `default` and `fts5_hybrid` individually satisfy `Precision@5 > baseline` **or** (`MRR > baseline` and `Precision@1 > baseline` and `Precision@5 >= baseline`); otherwise reranking is cleanly reverted and the benchmark findings are recorded in the baseline documentation.

---

### Edge Cases

- What happens when initial candidate search returns zero chunks or fewer chunks than the configured candidate pool depth, or when a pre-rerank score threshold eliminates all candidates? If no candidates survive pre-rerank filtering, retrieval returns an empty list immediately without invoking the reranker; if fewer candidates survive than the pool limit, only the surviving candidates are rescored and truncated cleanly.
- What happens when multiple candidate child chunks belong to the same parent section? Candidate children are rescored independently, grouped by parent section identifier, assigned the highest reranked child score per parent, deduplicated so each parent appears at most once, and truncated to the requested top result count.
- What happens when a caller requests final results whose expanded child fetch count (`top_k * 3` with parent expansion, or `top_k` without it) exceeds the configured candidate pool depth (default `20`), or specifies a non-positive candidate pool size (`<= 0`)? Non-positive candidate pool sizes fail immediately with a validation error; positive candidate pools use `max(rerank_top_n, top_k * 3)` when parent expansion is enabled (or `max(rerank_top_n, top_k)` when disabled) so higher cutoffs retain full parent recall headroom without silently under-fetching.
- What happens when the caller requests `0` or fewer top results, or when the target collection has zero committed documents? Invalid configuration or missing optional dependencies requested by the caller still validate up front; otherwise retrieval returns an empty list cleanly without model initialization or store writes.
- What happens when raw cross-encoder scores span arbitrary negative or positive values? All scores emitted by the reranking stage are monotonically normalized onto `[0.0, 1.0]` so downstream threshold handling, parent ranking weight comparisons, and evaluation reporting remain consistent.
- What happens during automated CI or restricted offline environments without pre-downloaded cross-encoder weights? Non-reranked usage and automated mocked test suites perform zero network requests; live local cross-encoder benchmarking relies on user-initiated local weight download/cache when opted in.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide opt-in post-retrieval reranking across user query, question-answering, evaluation, and programmatic retrieval entry points—supporting configuration of enablement (disabled by default), reranker strategy name, and candidate pool depth across both CLI options and TOML defaults (`CLI > TOML > built-in defaults`)—so non-reranked behavior is completely unchanged.
- **FR-002**: System MUST package heavy reranking model dependencies as an optional installation extra excluded from core dependencies, and command-line startup plus non-reranked execution MUST avoid importing or initializing reranking backends.
- **FR-003**: System MUST provide a registered local cross-encoder strategy as the default reranker when opted in, supporting extensible registration of alternative reranking strategies by name without modifying core orchestration code.
- **FR-004**: The local cross-encoder reranker MUST normalize raw relevance scores monotonically onto `[0.0, 1.0]` and reuse loaded model instances safely across consecutive calls using the same model configuration.
- **FR-005**: When reranking is requested without the required optional dependency installed—or with an unregistered reranker strategy name or invalid candidate pool size (`<= 0`)—the system MUST fail fast before scoring with an actionable error message (exiting with status `1` and a concise single-line message on standard error in CLI workflows).
- **FR-006**: When reranking is enabled, retrieval MUST execute child-first ordering: retrieve committed candidate child chunks up to the expansion-aware candidate pool depth (`max(candidate pool depth, requested top result count * 3)` when parent expansion is enabled, or `max(candidate pool depth, requested top result count)` when disabled, with candidate pool depth defaulting to `20`) using committed document versions and the active searcher strategy, apply any pre-rerank score threshold before reranking, pass non-empty surviving child candidates to the reranker, deduplicate unique parent sections ranked by each parent's highest reranked child score (or return top reranked children directly when parent expansion is disabled), and preserve cross-document reference enrichment.
- **FR-007**: Reranked retrieval MUST preserve full exception clauses on policy rules and satisfy the mandatory exception-preservation safety gate.
- **FR-008**: Evaluation workflows with reranking enabled MUST remain strictly read-only against all persisted index, lexical, and manifest files (`0` byte modifications) and include reranking configuration parameters in evaluation report configuration metadata only when reranking is enabled (leaving non-reranked report structure and committed baseline artifacts unchanged).
- **FR-009**: Maintainers MUST benchmark the opt-in local cross-encoder reranker using live local embeddings across both `default` semantic search and `fts5_hybrid` search on the curated policy corpus against live non-reranked runs, and enforce the explicit revert rule: retain reranking only if **both** `default` and `fts5_hybrid` individually satisfy strictly positive (`> 0.0`) improvement on `Precision@5` **or** strictly positive (`> 0.0`) improvement on both `MRR` and `Precision@1` with zero `Precision@5` regression (`Precision@5 >= baseline`); otherwise cleanly revert reranking and record the empirical findings in the baseline report.
- **FR-010**: Automated tests covering core reranking logic, mocked offline local cross-encoder behavior, missing-dependency errors, parent/child scoring invariants, CLI integration, read-only evaluation, and exception preservation MUST run offline with zero network downloads and achieve `100%` pass rate across all supported runtime environments and repository quality checks.

### Key Entities

- **Reranker Strategy**: An interchangeable post-retrieval scoring component identified by registration name that scores a query against candidate retrieved chunks and returns them ordered by descending normalized relevance (`[0.0, 1.0]`).
- **Rerank Configuration**: Opt-in retrieval parameters controlling whether reranking is enabled (disabled by default), the selected reranker strategy name, and the pre-rerank candidate child pool limit (default `20`).
- **Candidate Child Pool**: The bounded set of committed child chunks surviving active-version matching and optional pre-rerank score filtering immediately prior to reranking and parent section expansion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Live local-embedding evaluation of opt-in cross-encoder reranking across **both** `default` semantic and `fts5_hybrid` search individually achieves strictly positive (`> 0.0`) improvement on curated benchmark `Precision@5` — or strictly positive (`> 0.0`) improvement on both `MRR` and `Precision@1` with zero `Precision@5` regression (`Precision@5 >= baseline`) — over their respective live non-reranked runs (or, per the governance revert rule, failing this criterion on either mode triggers a clean revert with empirical findings documented in the baseline report).
- **SC-002**: When reranking is disabled, retrieval outputs, evaluation scores, and evaluation report config structure remain 100% identical to committed baselines (`0` schema or score drift and `0` additional mandatory core package dependencies).
- **SC-003**: `100%` of rule-and-exception queries in the mandatory exception-preservation safety gate retain complete exception clauses when reranking is active.
- **SC-004**: CLI startup and non-reranked execution incur `0` optional reranker imports or failures when the optional extra is absent; explicitly requesting reranking without the optional extra fails cleanly on first attempt with exit status `1` and installation instructions.
- **SC-005**: Evaluation runs with reranking enabled produce `0` byte changes across persisted storage, and `100%` of automated tests and quality checks pass offline across all supported runtime environments with zero network calls.

## Assumptions

- Prerequisite capabilities—extensible reranker registration, hybrid lexical+dense retrieval, and the read-only evaluation harness with committed benchmark baselines—are already present on `main`.
- Default local cross-encoder reranking targets a compact locally runnable model appropriate for standard 16 GB RAM CPU environments when users opt in and install the optional extra; custom model-weight selection stays programmatic on the reranker strategy rather than adding CLI or TOML model override flags.
- Automated CI validation uses deterministic offline test doubles and mocks so no model weights are downloaded during automated test runs; real local cross-encoder benchmarking against live local embeddings is executed locally with the optional extra installed across default semantic and hybrid search prior to acceptance.
- Cloud-hosted reranker APIs, LLM-based rerankers, and making reranking enabled by default are explicitly out of scope.
- Existing configuration precedence (`explicit option > config file > default`) and two-phase storage read-only guarantees remain preserved in accordance with project governance.

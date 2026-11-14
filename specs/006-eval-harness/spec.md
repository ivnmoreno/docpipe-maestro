# Feature Specification: Retrieval Evaluation Harness

**Feature Branch**: `feat/006-eval-harness`

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Create a deterministic, strictly read-only retrieval evaluation harness and baseline benchmark suite so ranking changes (like Hybrid Search and upcoming Reranking) can be measured objectively across realistic queries (direct lookups, paraphrased questions, exact clause IDs, and rule+exception queries) and safely reverted if quality drops."

## Clarifications

### Session 2026-11-14

- Q: When a query has multiple ground-truth relevant items and the cutoff K is smaller than that total, how should Recall@K calculate its denominator? → A: Divide unique relevant hits in the top K results by the total number of unique ground-truth relevant items for that query (standard information-retrieval Recall@K).
- Q: When loading a structured evaluation fixture file, how should the system handle a query whose list of expected relevant identifiers is empty? → A: Reject loaded fixtures containing empty query lists, blank questions, or any query with an empty expected-identifier list before running retrieval, while keeping pure metric functions returning 0.0 safely when called directly with an empty relevant set.
- Q: When a benchmark fixture declares a collection name and chunking profile, how should those fields interact with command-line or caller-provided target collection options? → A: Explicit caller/command-line collection overrides fixture `collection`; if omitted on the command line (or omitted by caller), fall back to non-empty fixture `collection` before configuration or global default, while treating fixture `profile` as informational metadata.
- Q: How should the evaluation runner and command-line command handle duplicate or out-of-order positive cutoff K values (such as passing K=10, 3, 3)? → A: Deduplicate and sort positive cutoff K values in ascending order automatically (e.g., `[10, 3, 3]` becomes `(3, 10)`), while rejecting empty sequences or any cutoff `<= 0` with a clear validation error.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reproducible Offline Retrieval Measurement (Priority: P1)

A developer or maintainer invokes the retrieval evaluation workflow against an already-indexed collection and a structured query fixture containing ground-truth relevant item identifiers, obtaining deterministic aggregate and per-query ranking quality metrics without altering any stored index state.

**Why this priority**: Quantitative, repeatable ranking metrics (`Precision@K`, `Recall@K`, and `Mean Reciprocal Rank`) are the core engine capability that all command-line workflows and future ranking improvements (such as reranking) depend on.

**Independent Test**: Can be fully tested in isolation by computing ranking metrics over synthetic result lists and running evaluation against a seeded, read-only test collection and verifying repeatable aggregate and per-query metric values with zero store mutations.

**Acceptance Scenarios**:

1. **Given** an ingested read-only collection and a valid evaluation fixture containing queries paired with known relevant item identifiers, **When** a user runs evaluation across one or more cutoff values `K`, **Then** the runner returns deterministic aggregate `Precision@K`, `Recall@K`, and `MRR` metrics plus matching per-query diagnostics.
2. **Given** identical collection contents, evaluation fixture inputs, and retrieval settings, **When** evaluation is executed repeatedly, **Then** every run produces identical scores and leaves all persisted index and manifest files unmodified.
3. **Given** a retrieval call returning zero items or an evaluation query with no relevant ground-truth identifiers, **When** metrics are computed directly, **Then** the system safely returns defined zero/boundary scores rather than failing with division errors.

---

### User Story 2 - Read-Only Command-Line Benchmark Workflow (Priority: P2)

An engineer or operator runs the evaluation command against a target collection and fixture file to print a human-readable summary or structured machine-readable report comparing retrieval configurations without writing to persisted storage.

**Why this priority**: Exposing evaluation from the command line enables rapid local benchmarking, easy diffing between retrieval strategies, and automation-friendly structured reporting alongside existing querying and status inspection workflows.

**Independent Test**: Can be fully tested by invoking the evaluation command against an offline populated collection in both human-readable and machine-readable output modes, verifying exit codes, global option precedence, and clean single-line error reporting on invalid inputs.

**Acceptance Scenarios**:

1. **Given** a populated collection and valid structured evaluation fixture file, **When** a user runs the evaluation command with structured output enabled, **Then** the command writes a machine-readable report containing configuration metadata, aggregate metrics per `K`, and per-query results to standard output and exits with status `0`.
2. **Given** invalid parameters such as an unknown retrieval strategy, missing fixture file, malformed fixture payload, non-positive `K` cutoff, or embedding model mismatch against the target collection, **When** the user runs the evaluation command, **Then** it writes a concise single-line error message to standard error without stack traces and exits with status `1`.
3. **Given** a project configuration file supplying default collection, persistence location, embedding model, or retrieval options alongside a fixture declaring a collection name, **When** the evaluation command runs with and without explicit collection or option overrides, **Then** target collection resolves in order `explicit collection option > fixture collection (if non-empty) > configuration default > global default`, fixture profile remains informational provenance, and other explicit command options take precedence over configuration defaults cleanly.

---

### User Story 3 - Curated Policy Evaluation Suite & Recorded Baselines (Priority: P3)

A maintainer evaluates ranking quality across a curated multi-category policy benchmark (covering direct factual lookups, paraphrased questions, exact clause/code identifiers, and rule-plus-exception scenarios) and consults saved reproducible baseline artifacts to assess future ranking changes objectively.

**Why this priority**: Establishing an agreed human-verified query set and recorded numerical baseline gives the project concrete regression targets before introducing new ranking stages such as reranking.

**Independent Test**: Can be verified independently by loading the curated benchmark fixture, running evaluation offline against the benchmark policy corpus, confirming rule-plus-exception queries target complete parent sections, and comparing results against the saved machine-readable and human-readable baseline reports.

**Acceptance Scenarios**:

1. **Given** the curated policy benchmark fixture in the repository, **When** inspected for coverage, **Then** it contains at least 20 distinct verified queries spanning direct lookups, paraphrased questions, exact identifiers/clause references, and at least 3 rule-plus-exception queries whose ground-truth identifiers match complete enclosing parent sections.
2. **Given** the repository's saved machine-readable and human-readable baseline artifacts, **When** an automated check replays the benchmark offline against the seeded self-contained benchmark corpus for both default semantic search and hybrid lexical search, **Then** the computed baseline metrics match the documented baseline numbers reproducibly.

---

### Edge Cases

- What happens when a retrieval returns fewer items than cutoff `K` (e.g., 2 items returned when evaluating `K=10`), or when `K` is smaller than the relevant set? `Precision@K` divides unique relevant hits within top `K` by `K` (standard fixed-cutoff definition), while `Recall@K` divides unique relevant hits within top `K` by the total number of unique ground-truth relevant items (`0.0`–`1.0`) without exceeding `1.0` or crashing.
- What happens when ground-truth relevant identifiers are duplicated or empty? When metric calculations are called directly, duplicate relevant IDs are deduplicated as a set and an empty ground-truth set yields `0.0` safely without division errors; when loading a structured evaluation fixture file, empty query sets, blank questions, or queries with empty expected-identifier lists fail schema validation cleanly before retrieval executes.
- What happens when the cutoff list contains duplicates, unsorted numbers, an empty sequence, or values `<= 0`? Duplicate or unsorted positive cutoffs are deduplicated and sorted in ascending order automatically (for example `[10, 3, 3]` becomes `(3, 10)`), while empty sequences or any cutoff `<= 0` fail cleanly with a clear validation error.
- What happens when the target collection has zero committed documents or does not exist? Fails fast cleanly with an actionable error without mutating any persisted storage.
- What happens when evaluating a fixture built with a different retrieval granularity (expanded parent sections vs. child passages)? The requested parent-expansion setting (supplied via command-line option or caller parameter) flows cleanly into retrieval without altering fixture loading or metric calculation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide deterministic, side-effect-free ranking metric calculations for `Precision@K`, `Recall@K` (dividing unique relevant hits in top `K` by total unique relevant items), and `Mean Reciprocal Rank (MRR)`, safely handling empty retrieved lists, empty ground-truth sets, cutoffs `K` larger than the retrieved count, and duplicate identifiers.
- **FR-002**: System MUST provide an evaluation runner capable of loading and validating a structured query fixture (specifying collection/profile context and non-empty labeled query cases with non-blank question text, non-empty relevant ground-truth identifiers, and optional notes) and executing evaluation over positive `K` cutoffs (defaulting to `1, 3, 5, 10` when omitted, and automatically deduplicating and sorting supplied positive cutoffs in ascending order while rejecting empty or non-positive cutoffs), embedding model selection, parent expansion behavior, and extensible retrieval options.
- **FR-003**: System MUST treat the persistence store, vector index, lexical index, and collection manifest as strictly read-only during every evaluation run, producing zero file additions, deletions, or content modifications in persisted storage.
- **FR-004**: System MUST produce structured aggregate metrics (average `Precision@K`, `Recall@K`, and `MRR` across all queries) alongside per-query diagnostics (question text, expected identifiers, retrieved identifiers and scores, and per-query metric values).
- **FR-005**: System MUST expose a command-line evaluation workflow accepting fixture path, target collection, cutoff `K` value(s), embedding model, search strategy selection, parent-expansion mode toggle, and structured output toggle, resolving target collection as `explicit collection option > fixture collection (if non-empty) > configuration default > global default` (with fixture `profile` treated as informational metadata), respecting existing global persistence and configuration conventions, formatting errors consistently with existing user workflows, and exiting cleanly (`0`) on valid measurement runs or exiting with failure (`1`) on invalid arguments, missing/empty collections, or embedding model mismatches (without regression-threshold exit-gate options).
- **FR-006**: Command-line startup and argument validation MUST remain lightweight and avoid eagerly loading heavy retrieval or language-model backends until execution requires them.
- **FR-007**: System MUST include a curated benchmark fixture containing at least 20 human-verified queries covering direct lookups, paraphrased questions, exact clause/code identifiers, and at least 3 exception-sensitive policy rules targeting complete parent sections, grounded against a self-contained packaged benchmark corpus that preserves existing repository policy test fixtures unmodified while adding complementary policy material with distinct section structures and exact clause/code identifiers.
- **FR-008**: Repository MUST include reproducible machine-readable and human-readable baseline benchmark reports recording offline metric snapshots for both default semantic search and hybrid lexical search side-by-side on the curated benchmark corpus.
- **FR-009**: All evaluation metrics, runner error paths, command-line behavior, fixture validation, and baseline reproducibility MUST be covered by automated tests passing with zero failures across the entire repository test suite after implementation completes.

### Key Entities

- **Evaluation Query**: A single benchmark test case pairing a user question with a set of ground-truth relevant section or chunk identifiers and optional explanatory notes categorizing query intent.
- **Evaluation Fixture**: A versioned structured test suite containing collection and profile metadata and an ordered list of Evaluation Queries.
- **Per-Query Evaluation Result**: Detailed diagnostic record linking one Evaluation Query to the ordered retrieved identifiers returned by the engine and its computed `Precision@K`, `Recall@K`, and reciprocal rank values.
- **Evaluation Report**: Structured summary combining run configuration parameters (target collection, embedding model, cutoff list, parent-expansion mode, and search strategy), aggregate scores across all queries, and all Per-Query Evaluation Results.
- **Baseline Snapshot**: Committed machine-readable and human-readable reference report capturing reproducible metric values on the repository's curated benchmark suite for longitudinal comparison by subsequent retrieval stages.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running evaluation twice consecutively on identical collection data and fixture inputs yields 100% identical aggregate and per-query scores (`0.0` numeric drift).
- **SC-002**: Executing full command-line and programmatic evaluation runs causes `0` byte changes across all files inside the persistence directory (verified via file hashes and modification checks).
- **SC-003**: The curated benchmark fixture includes at least `20` verified queries spanning all 4 target query categories, with at least `3` rule-and-exception queries referencing full parent sections.
- **SC-004**: Machine-readable and human-readable baseline artifacts are present, validated offline for both default semantic search and hybrid lexical search modes, and directly consumable by subsequent ranking evaluation checks without requiring network downloads or live external model APIs.
- **SC-005**: All automated tests across the repository pass with zero failures after implementation completes and satisfy the project's quality and coverage standards.

## Assumptions

- Evaluation measures Phase 2 retrieval ranking only; answer synthesis, faithfulness/groundedness scoring, and LLM-as-a-judge evaluation remain explicitly out of scope.
- Minimum-score regression failure exit-gate flags are out of scope for this stage; the evaluation command reports measurements and exits `0` on valid runs (with failure exit reserved for invalid arguments, missing/empty collections, or model mismatches).
- Ground-truth identifiers in fixtures rely on deterministic content-addressed chunk/parent IDs already guaranteed by the pipeline for fixed input files and chunking profiles.
- Automated test suites validate the harness offline without downloading live embedding models during CI execution, and committed baselines record deterministic offline comparisons across both default semantic search and hybrid lexical search; local live-model runs against an already-running local provider remain optional manual workflows.
- The curated benchmark corpus lives self-contained within packaged test fixtures, reusing existing policy fixtures unmodified alongside complementary synthetic policy documents so existing safety tests are undisturbed.
- Configuration discovery remains restricted to user-facing command-line entrypoints; core evaluation operations accept all inputs and persistence paths explicitly.

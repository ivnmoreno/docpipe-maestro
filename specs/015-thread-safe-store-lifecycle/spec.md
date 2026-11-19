# Feature Specification: Thread-Safe Persistent Vector Store Lifecycle

**Feature Branch**: `fix/015-store-lifecycle-thread-safety`  
**Created**: 2026-11-19  
**Status**: Draft  
**Input**: User description: "Make persistent vector store initialization, teardown, and collection lifecycle thread-safe under cold-start multithreaded concurrency (next sequential spec after 014). Problem: concurrent cold-start retrieval calls from host applications or multi-threaded workers against the same persisted store directory and collection crash intermittently during startup with mismatched backend/key errors while warm/sequential calls succeed. Require lifecycle-only serialization across initialization, collection validation/reset, and explicit teardown, clean partial-initialization rollback raising DocpipeError, preserved steady-state read/write concurrency, no per-query close() auto-teardown in retrieval/search paths, preserved Store plugin compatibility (no required close()), preserved reference-counted close/context-manager semantics, preserved public API/CLI/lazy-import purity, and offline fresh-subprocess cold-start + lifecycle + fault-injection verification."

## Clarifications

### Session 2026-11-19

- Q: When opening a persistent vector store fails during initial backend client startup (before a collection is acquired), should initialization wrap that startup failure in `DocpipeError` or let the raw backend exception propagate? → A: Wrap both backend client startup failures and collection acquisition/validation failures uniformly in `DocpipeError` (preserving the original exception as cause and skipping client teardown when no client handle was acquired).
- Q: If a caller invokes store operations on an instance whose `.close()` has already been called, should this change add new closed-handle `DocpipeError` guards or leave post-close operation behavior out of scope? → A: Keep new post-close error guards out of scope; preserve idempotent repeated `.close()` and leave existing behavior untouched when other methods are called after close.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cold-Start Concurrent Retrieval Without Initialization Races (Priority: P1)

As a host application or evaluation runner invoking concurrent retrieval queries (for example with 4 or more parallel worker threads) in a freshly started process against an existing persisted vector store directory and collection, I want every concurrent retrieval call to initialize and resolve the shared store cleanly without startup race crashes so multi-threaded workloads succeed reliably on first use just as they do under sequential execution.

**Why this priority**: Cold-start concurrent retrieval currently fails intermittently in production callers during worker fan-out, blocking default multi-threaded evaluation and retrieval workflows against newly launched processes.

**Independent Test**: Pre-populate a persistent collection offline, then launch an isolated fresh process with multiple barrier-synchronized worker threads executing concurrent `retrieve()` calls against the shared store directory and collection, confirming all workers succeed across repeated cold runs with zero errors.

**Acceptance Scenarios**:

1. **Given** a pre-populated persistent collection on disk and a freshly started process with no pre-warmed store state in memory, **When** 4 or more worker threads invoke `retrieve()` concurrently against the same store directory and collection, **Then** every worker initializes/opens the collection safely and returns valid results without backend initialization errors or missing store-identifier key errors.
2. **Given** an already initialized persistent store in a running process, **When** subsequent concurrent or sequential retrieval workers target the same store directory and collection (warm reuse), **Then** all requests complete with identical accuracy and no regression relative to single-threaded execution.
3. **Given** multiple concurrent threads targeting distinct persisted store directories in the same cold process, **When** retrieval workers run simultaneously across different store directories, **Then** initialization against each directory completes independently without cross-directory corruption or startup deadlock.

---

### User Story 2 - Concurrent Store Lifecycle Coordination & Clean Failure Rollback (Priority: P1)

As a library consumer using concurrent persistent vector store instances—including explicit opening, collection reset, shared ownership across handles, explicit `.close()` or context-manager exit, and error recovery—I want every lifecycle transition and failure rollback to stay coordinated across threads so partial initialization failures never corrupt shared state or trigger secondary teardown errors.

**Why this priority**: Uncoordinated concurrent teardown during a failed initialization can strip active state out from under sibling initializing threads, turning recoverable/single failures into cascading concurrent crashes and leaving shared client registries broken.

**Independent Test**: Exercise concurrent in-process open, shared-handle close, re-open, and reset cycles across threads, plus fault-injection tests simulating mid-initialization and collection-validation failures, confirming clean shared-state recovery and typed `DocpipeError` reporting.

**Acceptance Scenarios**:

1. **Given** two or more concurrent callers holding handles to the same persistent store directory, **When** one caller closes its handle explicitly or exits a context manager while another caller still holds an active handle, **Then** the shared underlying store remains active for remaining holders and releases resources only when the final active holder closes.
2. **Given** a persistent store whose initialization fails during backend client startup or mid-way during collection acquisition/validation while another thread concurrently opens or closes the same store directory, **When** failure rollback runs, **Then** rollback skips client teardown if no client handle was acquired, keeps any acquired cleanup coordinated with concurrent lifecycle operations, leaves shared store registry state clean without secondary teardown errors, and surfaces `DocpipeError` cleanly (preserving the original cause).
3. **Given** a concurrent caller triggering a collection reset while another thread opens, closes, or initializes the same store directory, **When** lifecycle operations overlap, **Then** all collection lifecycle transitions execute consistently without leaving dangling collection references or unhandled internal errors.

---

### User Story 3 - Non-Serialized Concurrent Reads, Preserved Plugin/Caller Contracts & Lazy Startup (Priority: P1)

As a maintainer or custom stage author integrating `docpipe-maestro` in constrained environments and custom extensions, I want concurrency coordination limited strictly to store/collection lifecycle transitions while preserving store reuse across retrieval calls, existing plugin contracts, CLI behavior, public exports, and deferred dependency loading so concurrency safety causes zero throughput, resource-handle, compatibility, or startup regressions.

**Why this priority**: Overly coarse fixes—such as locking steady-state reads/queries or closing stores after every query—introduce severe latency regressions, break custom store plugins that do not expose `.close()`, and risk exhausting file descriptors or triggering cache eviction churn on low-handle platforms.

**Independent Test**: Verify concurrently executing read/query/write calls do not block behind a global read lock once open, retrieval orchestration never issues per-query teardown across child/parent lookups, custom `Store` plugins without `.close()` keep working cleanly, and fresh-process package-root imports and CLI help startup load zero vector-store runtimes eagerly.

**Acceptance Scenarios**:

1. **Given** an already opened persistent vector store shared across concurrent workers, **When** multiple threads issue read, lookup, or write operations concurrently, **Then** steady-state reads, queries, and writes proceed without being serialized behind a store lifecycle lock.
2. **Given** `retrieve()` and search workflows executing child searches followed by parent lookups concurrently across worker threads, **When** queries complete, **Then** retrieval paths reuse active persistent store lifetimes rather than closing/reopening the store per query, avoiding repeated restart overhead and handle churn.
3. **Given** a custom `Store` stage plugin that implements only the documented `Store` stage contract without defining a `.close()` method, **When** ingestion, maintenance, or retrieval runs through that custom store, **Then** all operations succeed with full backward compatibility.
4. **Given** a consumer importing top-level public package symbols or invoking CLI `--help` / argument parsing, **When** startup runs without invoking store-backed commands, **Then** heavy vector-store runtime dependencies remain unloaded in memory and all existing public exports and error types remain unchanged.

---

### Edge Cases

- **Same-thread reentrant lifecycle calls**: What happens if an initialization, collection validation, reset, or cleanup routine triggers another lifecycle action (such as rollback cleanup on error) on the same thread? Lifecycle coordination MUST allow safe same-thread reentrancy without self-deadlocking.
- **Failure before vs. after acquiring a client handle**: What happens if initialization fails during client creation before a client handle is obtained versus after acquiring a client handle during collection acquisition? Rollback MUST close only an actually acquired client handle (skipping client teardown when no handle was created), leave shared store state clean, never decrement or remove an active sibling thread's live reference, and wrap either failure uniformly in `DocpipeError`.
- **Concurrent reopen immediately after final close**: What happens when Thread A executes the final `.close()` dropping the last active handle while Thread B simultaneously opens the same store directory? The open/close boundary MUST serialize cleanly so Thread B either joins a still-valid client or cleanly initializes a fresh one without observing half-torn-down state.
- **Repeated close on a single handle & post-close usage**: What happens if `.close()` or context-manager exit is called multiple times on the same store instance, or if another method is invoked after `.close()`? Duplicate close calls MUST remain idempotent and never decrement shared ownership more than once; adding new `DocpipeError` guards on post-close read, write, reset, or context-manager calls is out of scope and existing post-close behavior remains unchanged.
- **Low file-handle environments**: On OS environments with tighter default descriptor limits (such as Windows or macOS), keeping active persistent store sessions reused rather than per-query closed/reopened avoids repeated storage-engine startup and cache eviction thrashing during bursts of retrieval calls.
- **In-process test suite contamination**: If an earlier test in the same test session already initialized a persistent client, an in-process concurrency test alone can falsely pass by observing warmed singleton state. Cold-start verification MUST isolate the test inside a freshly spawned subprocess.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST serialize all persistent vector store lifecycle transitions—store client initialization, collection acquisition/validation, collection reset, and explicit handle teardown (`.close()` and context-manager exit)—across threads so concurrent callers against the same or different store directories never race on shared client initialization or teardown state.
- **FR-002**: Store lifecycle coordination MUST support safe same-thread reentrancy so error recovery or cleanup triggered inside an ongoing initialization step on the owning thread executes cleanly without deadlock.
- **FR-003**: If store initialization fails at either backend client creation or collection acquisition/validation, initialization MUST raise `DocpipeError` cleanly (re-raising any existing `DocpipeError` directly and wrapping non-`DocpipeError` failures while preserving the original cause), skip client teardown when no client handle was acquired, keep any post-client rollback cleanup serialized with concurrent lifecycle operations, and leave shared backend state uncorrupted without secondary teardown errors (such as missing-identifier lookup errors).
- **FR-004**: Concurrency serialization MUST be scoped strictly to store/collection lifecycle transitions and MUST NOT serialize steady-state vector store reads, queries, lookups, or writes once a store instance and collection are initialized.
- **FR-005**: Retrieval (`retrieve()`) and search workflows MUST NOT inject per-query store teardown (auto-closing the vector store after every query, child search, or parent expansion); shared persistent store instances MUST preserve existing reuse lifetimes across queries and concurrent workers.
- **FR-006**: System MUST preserve existing `Store` stage contract compatibility: custom `Store` plugins MUST NOT be required to implement `.close()`.
- **FR-007**: System MUST preserve existing explicit `.close()`, context-manager cleanup, idempotent repeated-close safety, and shared reference-counting semantics so closing one store handle never disrupts an active shared store still held by another concurrent consumer until the final holder closes; adding new post-close `DocpipeError` guards on other store methods after close is explicitly out of scope.
- **FR-008**: System MUST preserve all existing public package exports, CLI interfaces/flags, `DocpipeError` exception semantics, and lazy-import startup purity (importing the top-level package or running CLI help/argument parsing MUST NOT eagerly import heavy vector-store backend runtimes).
- **FR-009**: Verification MUST include an isolated fresh-subprocess multi-thread cold-start `retrieve()` concurrency check running concurrently across barrier-synchronized threads against a pre-populated persistent collection with zero failures.
- **FR-010**: Verification MUST include in-process concurrent store open/close/re-open lifecycle checks and fault-injection partial-initialization rollback checks confirming shared state remains clean and `DocpipeError` is preserved, with all checks running completely offline using local/deterministic test doubles where embeddings are needed and staying compatible with `minimal-core` and project quality gates.

### Key Entities *(include if feature involves data)*

- **Persistent Store Handle**: A logical consumer handle bound to a persisted store directory and collection name that tracks its own open/closed state, supports explicit close and context-manager exit, and participates safely in shared client reference ownership.
- **Shared Store Client Registry State**: Process-wide backend client state keyed by persisted store directory identifier, mutated only through coordinated lifecycle transitions (acquire on initialize/validate, release on final close or rollback).
- **Lifecycle Transition Guard**: Mutual-exclusion boundary covering only initialization, collection acquisition/validation, reset, and teardown (with same-thread reentrancy), leaving steady-state query and write paths unblocked.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In isolated fresh-process cold-start runs launching 4 or more concurrent retrieval threads simultaneously against a pre-populated persistent collection, **100%** of concurrent retrieval requests succeed across repeated cold executions (**0** initialization, missing-identifier, or teardown errors).
- **SC-002**: Under simulated initialization failure occurring concurrently with sibling store opens or closes, **100%** of failed calls report a clean typed store error (`DocpipeError`) without masking secondary errors, and shared store state retains **0** orphaned or corrupted entries afterward.
- **SC-003**: Once store handles are open, steady-state concurrent read/query operations incur **0** cross-thread serialization wait from lifecycle coordination and perform **0** per-query store teardown/restart cycles per retrieval invocation.
- **SC-004**: **100%** of existing custom stage/store contract checks, explicit close/reference-counting lifecycle checks, public export checks, and lazy startup checks (zero heavy vector-store runtime loaded on top-level import or CLI help parsing) continue to pass without breaking changes or relaxed assertions.
- **SC-005**: The complete offline verification suite—including fresh-subprocess cold-start concurrency, lifecycle coordination, and partial-initialization rollback checks—passes **100%** deterministically without network access or external API credentials.

## Assumptions

- Persistent vector storage operates in-process on local disk directories and is accessed both by direct Python library consumers (including multi-threaded orchestrators invoking `retrieve()`) and CLI workflows.
- Multi-threaded callers share a single worker process per host invocation; cold-start concurrency failures manifest when multiple threads race before the process has initialized the shared store directory state.
- Core persistent vector-store support remains part of the minimal core dependency set, allowing all cold-start and lifecycle tests to execute cleanly in `minimal-core` offline environments using deterministic local embeddings/doubles.
- Specific synchronization primitives, lock placement, and code structure details are intentionally deferred to the implementation planning phase (`/speckit-plan`).

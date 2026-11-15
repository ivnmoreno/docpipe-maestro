# Feature Specification: Configurable PII Protection, Egress Guard & Release Gate #2

**Feature Branch**: `feat/009-pii-protection`  
**Created**: 2026-11-15  
**Status**: Implemented  
**Input**: User description: "Add configurable PII detection, redaction/tokenization/blocking on ingestion, an outbound PII egress guard for remote LLMs, a `--local-only` privacy mode, structured zero-value audit logs, and Release Gate #2 (`@pytest.mark.pii`)."

## Clarifications

### Session 2026-11-15

- Q: When a caller provides a PII policy during ingestion, should PII protection run automatically before other document enrichers (even on the default profile), or require explicit profile configuration? → A: Automatically schedule `"pii"` enrichment ahead of all other profile-declared enrichers (including on the `DEFAULT` profile) whenever a PII policy is provided, unless `"pii"` is already explicitly ordered in the profile's enricher sequence.
- Q: When invoking a remote cloud LLM without `--local-only` and without an explicit PII policy, should outbound prompts and messages pass through unmodified or undergo automatic default PII redaction? → A: Apply outbound PII egress protection only when a PII policy is provided; leave unconfigured remote calls unmodified (while `--local-only` remains enforceable independently).
- Q: When a PII policy specifies both per-entity actions (such as blocking SSNs while redacting emails) and an outbound `egress` mode (`redact`, `block`, or `allow`), how should they interact for remote LLM calls? → A: Follow each entity's per-type rule (`redact`, `tokenize`, `block`) by default and under `egress: "redact"`, escalate all configured entities to halt transmission under `egress: "block"`, and bypass outbound PII checks only under `egress: "allow"`.
- Q: When `tokenize` mode is configured without an explicit salt or populated salt environment variable, should tokenization use a process-scoped fallback salt or fail fast requiring an explicit salt? → A: Use a cryptographically random process-scoped fallback salt (never predictable collection/file metadata) with a warning log when no explicit or environment salt is provided, while guaranteeing deterministic cross-run correlation whenever a persistent salt is supplied.
- Q: Which CLI subcommands should accept `--local-only` and `--pii-policy`? → A: Accept `--local-only` across all embedding and generation subcommands (`ingest`, `sync`, `reindex`, `query`, `ask`, `eval`) to block both remote embedding and remote LLM egress, and accept `--pii-policy` across `ingest`, `sync`, and `ask` (both before and after the subcommand name).

## Constitution Check

All requirements comply with `.specify/memory/constitution.md` (`v1.3.0`, ratified `2026-11-12`, amended `2026-11-15`), which already formalizes **Release Gate #2 (`@pytest.mark.pii`)**, strict local-only network refusal, pre-chunking PII scrubbing across headings and bodies, zero-raw-PII error/audit guarantees, outbound egress enforcement, and offline core footprint isolation:

- **Scope Discipline (I)**: Exposes PII safeguards directly through existing Phase 1 ingestion enrichment, Phase 2 retrieval/generation parameters, shared result/error shapes, and CLI flags without introducing application state or UI/server scope.
- **Two-Phase Architecture (II)**: Phase 1 PII ingestion enrichment and audit writing stay strictly inside Phase 1; Phase 2 outbound egress protection inspects prompts and chat payloads read-only with zero Phase 2 dependencies on Phase 1 ingestion modules.
- **Library Purity (III)**: Core library modules accept structured PII policies programmatically and never read PII policy files directly; policy file loading (`--pii-policy`) lives solely in the CLI boundary.
- **Search Small, Return Big & Exception Preservation (IV, V)**: Pre-chunking scrubbing protects section titles before child context header generation while preserving policy clauses and mandatory Release Gate #1 (Exception Preservation), alongside newly activated mandatory Release Gate #2 (PII Safety).
- **Provider Agnosticism & Local-First Default (VI, Data & Privacy)**: Built-in deterministic recognizers work 100% offline with zero automatic downloads; `--local-only` prevents non-local or non-loopback network calls prior to transmission.
- **Footprint (Quality Gates & Footprint)**: Core pattern/checksum recognizers add zero heavy runtime dependencies; optional NER support stays isolated behind an optional extra and loads lazily only when requested.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pre-Chunking PII Ingestion Protection & Blocking (Priority: P1)

A compliance engineer configures a structured PII policy mapping sensitive personal data categories (email addresses, IBANs with checksum validation, Luhn-validated credit card numbers, US Social Security Numbers, IP addresses, phone numbers, Spanish DNIs, and custom registered recognizers) to `block`, `redact`, or `tokenize` actions. When documents are ingested or synchronized, PII protection executes section-by-section across both section headings and section body text *before* chunk splitting and child context header construction. Any `block` match aborts the batch cleanly before storing chunks or updating manifests, naming only the offending source and entity category with zero raw PII values exposed; `redact` replaces matches with non-identifying masks; `tokenize` replaces matches with salted/keyed non-reversible deterministic tokens (for example `[EMAIL_ADDRESS_a1b2c3d4]`) that remain identical for repeated sensitive values across sections and documents regardless of position.

**Why this priority**: Preventing unredacted sensitive personal data from entering persisted vector indexes, lexical stores, or child context headers—while enforcing transactional fail-closed blocking—is the core safety guarantee required before indexing sensitive HR, legal, or policy corpora.

**Independent Test**: Can be fully tested by ingesting and synchronizing synthetic multi-section documents containing PII in both section titles and section bodies under policies using `block`, `redact`, and `tokenize`, and verifying transaction abort on blocks plus absence of plaintext PII across stored parent chunks, child chunks, and child context headers.

**Acceptance Scenarios**:

1. **Given** a PII policy configured to `block` US SSNs and credit card numbers and `redact` emails and IBANs, **When** an ingested batch includes a document containing a synthetic US SSN, **Then** ingestion halts before any vector storage, lexical index, or manifest write occurs (preserving prior collection state intact) and reports the affected source identifier and entity type without outputting any raw SSN digits.
2. **Given** a PII policy configured to `tokenize` email addresses, Spanish DNIs (`ES_DNI`), phone numbers, and IP addresses, **When** a multi-section document containing identical synthetic values across multiple sections—including within section headings—is ingested, **Then** every matching occurrence across headings, child context headers, and stored chunks is replaced with the exact same position-independent deterministic digest token.
3. **Given** invalid or malformed checksum-guarded inputs (such as strings matching IBAN or credit card digit lengths that fail MOD-97 IBAN or Luhn credit card checksums), **When** ingestion runs under strict deterministic pattern/checksum recognizers, **Then** non-valid false positives are not mistakenly blocked or mangled.

---

### User Story 2 - Strict Local-Only Mode & Outbound Egress Guard (Priority: P1)

A security-conscious user invokes CLI operations or pipeline workflows with `--local-only` (or enables local-only mode programmatically), causing any attempt to invoke a non-local cloud embedding or generation provider or a remote non-loopback endpoint to fail immediately *before* any network request is dispatched, while allowing local models and local loopback OpenAI-compatible servers (`localhost` / `127.0.0.1` / loopback IPv6). When remote cloud generation is permitted (without `--local-only`) and an outbound PII egress policy is configured, the egress guard evaluates and applies the PII policy across both plain prompt strings and role-separated multi-turn chat message sequences prior to remote transmission.

**Why this priority**: Even carefully scrubbed indexes or runtime user queries can otherwise transmit sensitive context or user questions to third-party APIs unintentionally; outbound egress control and strict `--local-only` network refusal protect Phase 2 query workflows before data leaves the host.

**Independent Test**: Can be fully tested using mocked/instrumented LLM transports and URL endpoints by asserting remote provider strings and non-loopback endpoints raise cleanly before transport invocation under `--local-only`, loopback endpoints are accepted as local, and both plain prompts and multi-role chat message lists are scrubbed or blocked according to configured egress rules prior to remote calls.

**Acceptance Scenarios**:

1. **Given** a user runs a question-answering workflow with `--local-only` targeting a cloud LLM provider (such as `openai/...` or `groq/...`) or a non-loopback remote API endpoint, **When** generation is invoked, **Then** the request is rejected cleanly prior to network transmission with a clear privacy/configuration error containing zero raw prompt PII.
2. **Given** a user runs with `--local-only` targeting a local model or a loopback API base (`127.0.0.1` / `localhost`), **When** generation is invoked, **Then** the locality check permits execution without network-refusal error.
3. **Given** remote cloud generation is permitted and an egress PII policy is active (for example default per-entity rules, `egress: "redact"`, or `egress: "block"`), **When** generation constructs either a single prompt string or role-separated system/user chat messages containing sensitive context or query PII, **Then** all outbound message contents undergo per-entity `redact`/`tokenize`/`block` enforcement (or block all PII under `egress: "block"`) before dispatch, bypassing checks only when `egress: "allow"` is explicitly set.

---

### User Story 3 - Zero-Raw-PII Structured Audit Trail (Priority: P1)

A Data Protection Officer (DPO) or security auditor inspects the collection's append-only audit log located alongside its ingestion manifests and confirms that every PII-evaluated ingestion operation records structured metadata—collection name, source key, truncated document version digest (`sha256` prefix), timestamp, configured confidence threshold, detected entity categories, per-category counts, actions applied, and whether ingestion was blocked—with **zero raw PII values or matched substrings** stored anywhere in the log or parent directory, and with restricted owner-only directory permissions (`0o700` on POSIX systems).

**Why this priority**: Compliance auditing requires verifiable evidence of what PII policies ran and what entity classes were redacted or blocked without creating a secondary plaintext leak inside audit artifacts.

**Independent Test**: Can be fully tested by ingesting clean, redacted, tokenized, and blocked synthetic documents under an active PII policy, inspecting filesystem directory permissions on POSIX, parsing every JSON-lines audit entry, and asserting schema completeness alongside exhaustive substring checks guaranteeing zero raw PII values appear anywhere in the log file.

**Acceptance Scenarios**:

1. **Given** a collection ingested under an active PII policy using mixed `redact`, `tokenize`, and `block` rules, **When** an auditor parses the append-only `.audit.jsonl` file in the collection manifest directory, **Then** every line parses as valid structured JSON recording source key, document version digest, entity counts, actions, and threshold metadata.
2. **Given** synthetic PII secrets present in ingested documents (including values that triggered `block`), **When** the entire audit file and surfaced error output are scanned for those literal synthetic values and partial secrets, **Then** zero raw PII characters appear anywhere in the audit trail or diagnostics, and on POSIX hosts the audit log directory restricts access to owner-only permissions (`0o700`).

---

### User Story 4 - Multi-Language Optional NER Extension & CLI Policy Supply (Priority: P2)

A user supplies a structured policy file path via `--pii-policy` on the CLI, which loads the configuration exclusively in the CLI layer and passes programmatic policy dictionaries to library entry points so library components remain file-independent. When users install the optional `[pii]` NER extra to detect unstructured entity types (`PERSON`, `LOCATION`, `ORGANIZATION`), detection honors multi-language policy settings (supporting non-English configured languages such as `["en", "es"]` rather than hardcoding English alone) and never attempts automatic network downloads when running offline.

**Why this priority**: Preserving library purity while enabling extensible multi-language recognition ensures both lightweight offline defaults and deeper optional entity coverage when explicitly installed.

**Independent Test**: Can be fully tested via automated architectural boundary verification confirming core library modules read no policy files, CLI tests verifying `--pii-policy` and `--local-only` flag propagation, and multi-language recognizer and mocked-NER tests confirming non-English recognizers (such as Spanish DNI) execute across configured language lists without triggering automatic network downloads.

**Acceptance Scenarios**:

1. **Given** a structured policy configuration file supplied via CLI `--pii-policy` alongside ingest or ask commands, **When** invoked via the CLI, **Then** only the CLI entrypoint layer reads the policy file from disk and forwards the parsed policy settings programmatically into library execution.
2. **Given** a policy specifying multi-language detection (such as `["en", "es"]`) containing jurisdiction identifiers like Spanish DNI (`ES_DNI`), **When** PII detection runs offline with built-in recognizers (or with optional NER enabled), **Then** both English-scoped patterns and non-English recognizers evaluate all configured languages rather than defaulting solely to English.
3. **Given** the optional NER capability is requested when the `[pii]` extra is not installed, **When** analysis runs, **Then** the system raises a clear missing-optional-extra diagnostic instructing how to install the optional dependency without attempting automatic runtime downloads.

---

### User Story 5 - Release Gate #2 & Honest Scope Documentation (Priority: P2)

Engineering maintainers and prospective adopters rely on an automated Release Gate #2 safety suite driven exclusively by synthetic non-production PII fixtures to verify blocking, redaction/tokenization, child context header scrubbing, outbound egress protection, `--local-only` enforcement, and zero-raw-PII audit guarantees offline across all supported environments. Alongside automated tests, repository security, product, and README documentation transparently describes built-in vs optional NER capabilities, audit log format, confidence threshold tuning, known limitations, and explicit non-claims (avoiding overclaims such as "GDPR compliant" or "100% accurate detection").

**Why this priority**: Constitution v1.3.0 elevates Release Gate #2 to mandatory alongside Release Gate #1 and forbids misleading compliance overclaims so adopters understand exact technical guarantees and boundaries.

**Independent Test**: Can be fully tested by executing the Release Gate #2 safety suite offline, verifying Release Gate #1 continues passing concurrently, and running automated documentation checks verifying honest limitation disclosures and absence of prohibited compliance overclaims.

**Acceptance Scenarios**:

1. **Given** the complete synthetic PII test corpus in the Release Gate #2 suite, **When** maintainers run both Release Gate #2 and Release Gate #1 offline without optional network downloads, **Then** both safety gates pass across every supported target environment.
2. **Given** updated security, product, and README documentation, **When** reviewed for PII safety claims, **Then** documentation clearly documents recognizer types, audit logs, limitations (such as false positives/negatives in regex/NER detection), and avoids any claim of "GDPR compliance" or "100% accuracy".

---

### Edge Cases

- **Multi-document batch failure mid-batch**: If the first document in a batch has `redact` matches and the second document triggers a `block` match, transactional ingestion staging aborts the whole batch so neither partial vector chunks nor lexical index updates nor manifest entries persist from the aborted batch.
- **PII inside document headings/section titles**: Section labels/headings containing PII (such as a heading naming an employee email or SSN) are evaluated and scrubbed or blocked *prior* to chunking so child context headers never retain raw PII omitted from body text.
- **Position-independent repeated tokens**: Identical sensitive strings occurring at different character offsets within one section, across multiple sections, or across separate documents produce the exact same token identifier when configured with the same token salt.
- **Role-separated chat message egress**: Outbound PII egress guards applied to multi-message chat arrays preserve message roles (`system`, `user`, `assistant`) and message ordering while redacting, tokenizing, or blocking content inside every role-bearing text payload.
- **Outbound error diagnostics**: When either ingestion blocking or egress blocking triggers, surfaced exception text names source/policy context and entity types while containing zero substrings of the matched raw PII.
- **Unsupported or misspelled entity/action policy keys**: Invalid policy actions (outside `redact`, `tokenize`, `block`), out-of-range confidence thresholds (`< 0.0` or `> 1.0`), unreadable/invalid `--pii-policy` JSON/TOML CLI files, misplaced `--pii-policy` usage on unsupported subcommands (`status`, `remove`, `reindex`, `query`, `eval`), or invalid egress modes fail fast with explicit validation errors (exit code `1` on CLI) rather than silently ignoring rules.
- **Documents with zero PII matches under an active policy**: Ingestion proceeds smoothly without altering text and records a clean zero-count audit log entry (or completes cleanly with zero false-positive mutations).
- **Disabled or omitted PII configuration**: See `FR-015` — omitting both `pii_policy` and `local_only` preserves prior ingestion, sync, retrieval, and generation behavior without alteration.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The pipeline MUST support deterministic, zero-download built-in PII detection covering email addresses (`EMAIL_ADDRESS`), IBAN codes with MOD-97 checksum validation (`IBAN_CODE`), credit card numbers with Luhn validation (`CREDIT_CARD`), US Social Security Numbers (`US_SSN`), IP addresses (`IP_ADDRESS`), phone number heuristics (`PHONE_NUMBER`), Spanish national identity numbers (`ES_DNI`), and an extensible recognizer registration mechanism for custom entity patterns.
- **FR-002**: The system MUST support an optional NER backend isolated behind an optional extra (`[pii]`) that loads lazily only when explicitly requested (`ner=True`) or implicitly triggered by configuring standard NER entity categories (`PERSON`, `LOCATION`, `ORGANIZATION`) not already handled by deterministic/custom recognizers, and never attempts automatic runtime network downloads in offline mode.
- **FR-003**: PII detection and recognizer dispatch MUST support multi-language evaluation driven by configured policy languages rather than hardcoding English (`"en"`) alone, so language-specific recognizers such as Spanish DNI execute cleanly alongside other configured languages.
- **FR-004**: Phase 1 document ingestion and synchronization MUST include a built-in `"pii"` enrichment stage operating section-by-section across **both** section headings/labels and section body text plus extracted structural clauses (`clauses`) pre-chunking—prior to child context header construction and ahead of other enrichers. Whenever an active PII policy is provided, the pipeline MUST automatically execute `"pii"` enrichment before all profile-declared enrichers (including on `DEFAULT`), unless `"pii"` is already explicitly positioned in the profile's enricher sequence (preserving custom explicit ordering without running twice).
- **FR-005**: The pipeline MUST accept structured PII policy configuration programmatically via ingestion context and query/generation entry points, forbidding any core library module from reading PII policy files from disk (Principle III), while exposing custom recognizer registration (`register_pii_recognizer` and `PiiRecognizer`) cleanly through the public library surface.
- **FR-006**: PII policies MUST support configurable per-entity actions (`redact`, `tokenize`, `block`), configurable confidence score thresholds, error-handling modes (`fail`, `continue`), supported language lists, optional NER enablement (`ner`), configurable outbound `egress` disposition (`redact` [default], `block`, `allow`), and token salt configuration. Under default / `egress: "redact"`, outbound enforcement MUST honor each entity's configured per-type rule without downgrading `block` entities; under `egress: "block"`, any matched configured entity MUST halt transmission; under `egress: "allow"`, outbound PII scrubbing is bypassed (without relaxing `--local-only`).
- **FR-007**: When any entity configured with the `block` action is matched during ingestion, the pipeline MUST halt ingestion via a typed domain error before writing any chunks, lexical entries, or manifest updates, preserving prior collection state intact while omitting all raw PII characters from surfaced error messages.
- **FR-008**: When PII is configured with `tokenize`, sensitive matches MUST be transformed into deterministic non-reversible tokens derived from a keyed/salted cryptographic digest of the matched sensitive value (independent of character offset), producing identical tokens across sections, documents, and separate runs whenever an explicit or environment-configured salt is supplied; when omitted, the system MUST fall back to a cryptographically random process-scoped secret (never predictable metadata such as collection names or filenames) and log a warning that cross-process correlation requires a persistent salt.
- **FR-009**: When an active PII policy executes during ingestion or sync, the pipeline MUST append structured audit records to a collection-scoped `.audit.jsonl` log alongside collection manifests recording collection, source key, truncated cryptographic document version digest (`doc_version`), confidence threshold, entity type counts, actions, and outcome metadata while containing **zero raw PII values**, inside a directory created and maintained with owner-only access permissions (`0o700` where supported). Audit logs are append-only compliance history and remain intact across subsequent `remove()` calls.
- **FR-010**: Phase 2 generation workflows MUST apply an outbound PII egress guard whenever a PII policy is configured on a remote target prior to dispatching remote LLM requests (leaving remote calls without a PII policy—and local/loopback targets—unmodified for backward compatibility, while enforcing `--local-only` unconditionally), supporting both single-string prompts and role-separated chat message sequences while preserving message structure and applying the configured egress PII policy.
- **FR-011**: The system MUST support a `--local-only` privacy mode rejecting any non-local cloud embedding or LLM provider or non-loopback API endpoint *before* any network connection is attempted (raising a clean domain error), while continuing to recognize local providers and loopback API endpoints (`localhost`, `127.0.0.1`, loopback IPv6) as local execution.
- **FR-012**: The CLI MUST accept `--local-only` / `--no-local-only` across all embedding and generation subcommands (`ingest`, `sync`, `reindex`, `query`, `ask`, `eval`, taking precedence over `docpipe.toml` `local_only` defaults) and `--pii-policy <PATH>` across `ingest`, `sync`, and `ask` (supported both before and after the subcommand name, consistent with shared CLI options, parsing `.json` or `.toml`/`.tml` files plus optional `docpipe.toml` `pii_policy` path strings or `[pii_policy]` tables solely inside the CLI entrypoint layer and passing parsed structured policies programmatically into library operations; invoking `--pii-policy` on unsupported subcommands MUST exit with status `1`).
- **FR-013**: All automated safety invariants—ingestion blocking, pre-chunking redaction/tokenization in bodies and headers, position-independent tokenization, zero-raw-PII audit logging with restricted directory permissions, outbound prompt/chat egress guarding, and `--local-only` remote refusal—MUST be verified using synthetic fixtures as mandatory **Release Gate #2** (PII Safety Gate), running completely offline without external network access.
- **FR-014**: Repository security, product, and README documentation MUST transparently explain PII recognition scope, optional `[pii]` installation, audit log semantics, configuration options, and detection limitations while explicitly avoiding "GDPR compliant" or "100% accurate detection" overclaims.
- **FR-015**: Existing Phase 1 ingestion, Phase 2 retrieval (including mandatory **Release Gate #1** Exception Preservation), and optional generation workflows MUST remain 100% backward-compatible when no PII policy or `--local-only` mode is configured.

### Key Entities

- **PII Policy**: Structured policy configuration defining per-entity disposition (`redact`, `tokenize`, `block`), minimum confidence threshold, active language list, failure policy (`fail` vs `continue`), outbound egress behavior, NER enablement, and token salt configuration.
- **PII Detection**: Ephemeral detection record capturing recognized entity category, match boundaries, recognizer source, and confidence score used exclusively in memory during scrubbing and never logged or persisted in raw form.
- **PII Audit Record**: Append-only structured audit entry capturing collection, source identifier, document content digest version (`doc_version`), applied threshold, per-entity-type counts, actions taken, and block status without any raw PII substrings.
- **PII Recognizer Registry**: Extensible registry holding built-in deterministic pattern/checksum recognizers and optional NER-backed detectors selectable per active language list.
- **Outbound Egress Guard**: Phase 2 outbound verification layer enforcing strict local-only endpoint rules and applying egress PII policies over plain prompts and multi-role chat messages before remote LLM invocation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of synthetic ingestion batches containing `block`-configured PII halt cleanly before persisting chunks or updating collection manifests (leaving pre-run collection contents 100% unchanged) and emit 0 raw PII characters in surfaced exception messages.
- **SC-002**: 100% of synthetic test cases covering emails, IBANs, Luhn-validated credit cards, US SSNs, IP addresses, phones, and Spanish DNIs across section titles and bodies produce 0 occurrences of unredacted raw PII in stored chunks or generated child context headers under `redact` and `tokenize` policies, while 100% of identical repeated sensitive values share identical non-reversible tokens across sections and documents.
- **SC-003**: 100% of strict local-only (`--local-only`) invocations configured with cloud embedding/generation providers or remote non-loopback API URLs fail cleanly before attempting any outbound network call, while 100% of loopback local endpoint configurations remain permitted.
- **SC-004**: 100% of remote LLM calls configured with an active egress PII policy apply redaction, tokenization, or blocking across all outbound single-prompt strings and role-separated chat message payloads prior to transport invocation, leaking 0 blocked or redacted raw PII strings in instrumented transport checks.
- **SC-005**: 100% of structured audit log records in collection `.audit.jsonl` files parse cleanly as machine-readable structured records containing required metadata and count fields, contain 0 raw PII substrings across the entire file, and enforce owner-only directory access controls where supported.
- **SC-006**: Mandatory Release Gate #2 (PII Safety Gate) and Release Gate #1 (Exception Preservation) suites pass offline with zero external network downloads across every supported runtime environment, and 100% of updated documentation adheres to truthful capability disclosures with 0 claims of "GDPR compliant" or "100% accurate detection".

## Assumptions

- **Deterministic Tokenization Salt Strategy**: When callers supply an explicit salt or populate the policy's configured salt environment variable, identical sensitive values yield identical non-reversible tokens across sections, documents, and runs; when omitted, a cryptographically random process-scoped fallback secret ensures within-process consistency and non-reversibility while logging a warning for cross-process repeatability.
- **Audit Recording Scope**: When an active PII policy evaluates a source during ingestion or sync (whether findings are `0`, redacted, tokenized, or blocked), appending an audit record confirms policy evaluation took place for compliance verification without recording sensitive plaintext. Subsequent `remove()` calls purge vector/lexical/manifest entries while retaining append-only `.audit.jsonl` compliance history.
- **Boundary Between Local and Remote Endpoints**: Explicit `api_base` URLs satisfy `--local-only` when resolving to a loopback address (`localhost`, `127.0.0.1`, `::1`, or equivalent loopback bindings), allowing loopback OpenAI-compatible servers regardless of provider prefix; when `api_base` is omitted, `--local-only` requires a local provider prefix (`ollama/`, `ollama_chat/`, `local/`) with any configured `OLLAMA_API_BASE` / `OLLAMA_HOST` resolving to loopback, whereas cloud providers (`openai/`, `anthropic/`, `groq/`, etc.) or non-loopback endpoints constitute remote egress. (`--local-only` governs embedding and LLM provider targets; optional `--rerank` uses local HuggingFace weights and relies on pre-cached local models offline.)
- **Out of Scope**: LLM-based PII classification/detection (deferred Tier 2), automatic spaCy/NER model downloads in offline execution or tests, and reading PII policy files inside core library modules.

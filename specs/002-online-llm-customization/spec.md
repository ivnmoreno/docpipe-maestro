# Feature Specification: Online LLM Answer Customization

**Feature Branch**: `feat/002-online-llm-gateways`

**Created**: 2026-11-13

**Status**: Draft

**Input**: User description: "Specification & Implementation Blueprint: Online LLM Answer Customization"

## Clarifications

### Session 2026-11-13

- Q: How should the system handle reserved or conflicting fields if a programmatic caller supplies them inside provider-specific pass-through options? (FR-003) → A: Reject reserved/security-sensitive fields (model identifier, endpoint URL, credentials, message payload) and duplicates of first-class settings (temperature, max output tokens, timeout) immediately with a validation error
- Q: Beyond known key prefixes and authorization headers, should error redaction also mask exact secret values loaded into the runtime environment? (FR-012) → A: Redact both recognized secret patterns and exact active credential values present in the runtime environment
- Q: How should question answering behave when an online provider returns a rate-limit or quota-exceeded error? (FR-013) → A: Fail fast immediately with a clean, sanitized rate-limit diagnostic error so the caller decides whether to retry
- Q: What should happen when an online provider returns a completion choice whose message text is empty or whitespace-only without an explicit refusal field? (FR-014) → A: Treat empty, whitespace-only, or null completion text as a failed/filtered generation and raise a clear diagnostic error
- Q: Where should the CLI search when discovering the local `.env` credential file at startup? (FR-007) → A: Load `.env` from the project configuration directory when an explicit configuration file path is provided, or strictly from the current working directory otherwise (no upward parent traversal)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Selecting and Tuning Online LLM Providers (Priority: P1)

Users and programmatic callers running Phase 2 question answering can opt in from the local default model to hosted online inference providers (including Groq serverless, Together.ai, OpenAI, Anthropic, Google Gemini, Mistral) or private/enterprise compatible gateways, while customizing sampling temperature, maximum response length, request timeout, and provider-specific options.

**Why this priority**: Enabling flexible selection and tuning of fast serverless, frontier cloud, and private model gateways unlocks real-world production deployments without modifying the core retrieval pipeline or breaking local-first defaults.

**Independent Test**: Submit grounded questions against mocked or configured online provider targets with explicit deterministic temperature (`0.0`), omitted temperature, maximum output token limits, custom timeouts, and extra provider-specific options; verify generation requests honor each parameter while leaving out-of-the-box local execution and Phase 1 ingested collections untouched.

**Acceptance Scenarios**:

1. **Given** an ingested document collection and valid online credentials in the runtime environment, **When** a user requests an answer specifying an online provider model (such as a Groq serverless or Together.ai model) with deterministic temperature `0.0` and a maximum token cap, **Then** the request transmits those exact generation settings to the chosen provider and returns the grounded answer.
2. **Given** a reasoning model that rejects explicit sampling temperature parameters, **When** a user requests an answer without specifying a temperature value, **Then** the system omits the temperature field completely from the provider request so generation succeeds without parameter validation errors.
3. **Given** no custom online model or endpoint is configured, **When** a user asks a question out of the box, **Then** the system defaults to local inference and operates without requiring cloud API keys or outbound network access.
4. **Given** a programmatic caller supplies additional provider-specific generation options alongside standard controls, **When** answer generation runs, **Then** those options are forwarded to the target provider cleanly without affecting Phase 1 indexed document stores.

---

### User Story 2 - Local Credential Management via Environment File (Priority: P1)

Users configuring cloud model providers store API keys locally in an untracked `.env` file guided by a committed `.env.example` template, allowing seamless command-line execution while keeping secrets out of version control and keeping core library modules decoupled from configuration files.

**Why this priority**: Safe, frictionless secret storage is essential before using cloud API keys in everyday workflows, preventing accidental credential leaks to public repositories while keeping the core engine embeddable.

**Independent Test**: Copy `.env.example` to `.env` with sample provider keys, verify version control excludes `.env`, execute a CLI question-answering query without manually exporting shell variables, and verify core library calls resolve credentials solely from the active process environment.

**Acceptance Scenarios**:

1. **Given** a fresh repository checkout, **When** a user opens `.env.example`, **Then** they find documented placeholder entries (with zero real secrets) covering Groq, Together.ai, OpenAI, Anthropic, Google Gemini, Azure deployments, and an optional offline startup mode toggle.
2. **Given** valid provider API keys saved in a `.env` file located in the explicit configuration file's directory (when provided) or the current working directory, **When** a user runs the CLI `ask` command, **Then** that `.env` file is loaded at CLI startup (without traversing parent directories) so the chosen online provider authenticates automatically.
3. **Given** a populated `.env` file (or environment-specific variants) in the workspace, **When** inspecting repository tracking status, **Then** real environment files remain ignored by version control.
4. **Given** a programmatic caller running inside an application that injects secrets directly into the process environment, **When** question answering runs, **Then** core library components read credentials exclusively from the runtime environment and never access `.env` or project configuration files on disk.

---

### User Story 3 - Transport Security, Secret Redaction, and Provider Resilience (Priority: P1)

Users routing requests to external providers or private proxies are protected against insecure remote URLs, accidental secret leaks in failure messages, uninformative rate-limit errors, and crashes on filtered or refused provider responses.

**Why this priority**: Sending proprietary documents and commercial API keys over external networks requires fail-safe transport validation, airtight error redaction, and predictable handling of provider guardrails and serverless rate limits.

**Independent Test**: Exercise unencrypted remote custom URLs vs. loopback URLs, simulate failures embedding OpenAI/Groq/Google/Bearer/query-string credentials, trigger simulated HTTP 401/403 auth failures and HTTP 429 rate limits, and return empty choice lists or explicit refusal payloads; verify every failure is cleanly classified, pre-flight blocked when insecure, and 100% free of secret exposure.

**Acceptance Scenarios**:

1. **Given** a custom endpoint URL pointing to a non-loopback remote host over unencrypted HTTP, **When** a user or caller triggers answer generation, **Then** the request is rejected immediately before any outbound connection or credential transmission occurs.
2. **Given** a custom endpoint URL targeting a local loopback host (`localhost`, IPv4 loopback, or IPv6 loopback) over HTTP for local development or proxy testing, **When** answer generation runs, **Then** the local endpoint is permitted without transport error.
3. **Given** a failure originating from a provider, network transport, or endpoint URL containing sensitive credentials (OpenAI keys, Groq keys, Google API keys, Bearer tokens, URL basic-auth credentials, or secret query parameters), **When** the error is surfaced, **Then** every credential token and secret query value is masked while preserving actionable context.
4. **Given** an online provider returns invalid-credential errors (HTTP 401/403), rate-limit or quota errors (HTTP 429), empty response choices due to content moderation, or an explicit refusal message, **When** handling the response, **Then** the system reports a clear, categorized diagnostic failure without dumping headers, credentials, or crashing with unguarded indexing errors.

---

### User Story 4 - Role-Separated Prompt Structuring (Priority: P2)

Question answering supports structured role-separated conversations that isolate trusted grounding instructions in a system role from retrieved document excerpts and the user question in a user role, strengthening cloud model instruction adherence and prompt-injection resistance while preserving full compatibility with plain single-string prompts.

**Why this priority**: Separating system rules from untrusted document text significantly improves grounding reliability on frontier and serverless chat models while keeping existing single-string callers working unchanged.

**Independent Test**: Build a structured prompt from a question and retrieved sections, confirm trusted instructions reside in a dedicated system message separate from context and question in the user message, verify CLI execution sends structured messages, and confirm plain single-string prompts continue producing valid answers.

**Acceptance Scenarios**:

1. **Given** a user question and retrieved document sections (including text that attempts to override instructions), **When** the CLI builds a prompt for answer generation, **Then** trusted grounding instructions are isolated in a system role message separate from the user role message containing context and question.
2. **Given** an existing caller passing a pre-formatted plain text prompt, **When** answer generation runs, **Then** the system accepts the plain prompt cleanly and returns a grounded answer with full backward compatibility.
3. **Given** document retrieval returns zero relevant sections meeting the relevance threshold, **When** answer generation is requested, **Then** the system short-circuits immediately with the standard insufficient-context refusal without calling any online provider.

---

### User Story 5 - CLI and Project Configuration Parity with Strict Precedence (Priority: P2)

Users can store recurring online model defaults (model identifier, custom endpoint URL, sampling temperature, maximum output tokens, and request timeout) in a project configuration file and override any setting per query via CLI options using strict, predictable override precedence.

**Why this priority**: Teams and frequent users need repeatable project defaults alongside quick command-line overrides without editing files between runs.

**Independent Test**: Define online generation defaults in a project configuration file, execute `ask` queries with no flags, partial flags, and full overriding flags, and confirm resolved parameters follow CLI options > project configuration > built-in defaults.

**Acceptance Scenarios**:

1. **Given** a project configuration file specifying an online model, sampling temperature, maximum output tokens, and request timeout, **When** a user executes a CLI `ask` query without overriding options, **Then** all configured defaults govern generation.
2. **Given** a project configuration file sets sampling temperature to `0.5` and the user passes a CLI override of `0.0`, **When** the query runs, **Then** the CLI value (`0.0`) overrides the project configuration value (`0.5`), while un-overridden settings continue coming from configuration or built-in defaults.

---

### Edge Cases

- What happens when sampling temperature is explicitly configured as `0.0` versus left unset? Zero (`0.0`) MUST be treated as an explicit numeric value and forwarded for deterministic generation, whereas an unset temperature MUST be omitted entirely from the provider payload.
- What happens when `.env` is absent from the workspace or when the same key is already set in the invoking shell environment? CLI startup MUST proceed silently when `.env` is missing, and pre-existing shell environment variables MUST take precedence over `.env` defaults.
- What happens when an IPv6 loopback URL (such as `http://[::1]:8000`) is supplied as a custom endpoint vs. a remote plaintext host? IPv6 and IPv4 loopback hosts and `localhost` are permitted over HTTP; all non-loopback hosts over plaintext HTTP fail validation before network requests occur.
- What happens when an operator runs in an air-gapped or restricted corporate network? Setting the documented offline cost-map toggle prevents startup remote metadata fetches.
- What happens when a provider returns empty response choices, an explicit refusal message, or null/whitespace-only message text? All three cases raise clear, categorized generation errors identifying a moderation filter, refusal, or empty completion rather than returning blank output or crashing; surrounding whitespace on non-empty valid answers is trimmed cleanly.
- What happens when a user runs generation with invalid non-numeric or malformed configuration entries? Invalid values fail fast with clear validation errors rather than silently falling back to unintended settings.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST retain local offline execution as the out-of-the-box default requiring no cloud credentials or network access, while allowing opt-in selection of online providers (including Groq serverless, Together.ai, OpenAI, Anthropic, Google Gemini, Mistral) and custom/private compatible gateways via standard provider/model identifiers without hardcoding provider registries.
- **FR-002**: Online customization MUST remain restricted to Phase 2 single-turn question answering; Phase 1 ingestion, chunking, indexing, and persisted vector stores MUST remain unaffected, and session memory, streaming UI, server modes, and end-user login remain out of scope.
- **FR-003**: Users and callers MUST be able to customize sampling temperature, maximum output tokens, request timeout (defaulting to 120 seconds), custom gateway endpoint URL, and (for programmatic callers) additional provider-specific generation options; provider-specific pass-through options MUST reject reserved fields (model identifier, endpoint URL, credentials, message payload) and duplicates of first-class settings (temperature, maximum output tokens, request timeout) immediately with a validation error.
- **FR-004**: System MUST forward explicit temperature values including `0.0` and MUST completely omit the temperature parameter from requests when unset so reasoning models rejecting temperature settings operate without validation errors; unset maximum-token limits MUST likewise be omitted.
- **FR-005**: System MUST support structured role-separated chat messages splitting trusted system grounding instructions from retrieved context and user question, MUST use structured messages for CLI `ask` execution, and MUST preserve full backward compatibility for plain string prompts.
- **FR-006**: Question answering MUST short-circuit immediately with the standard insufficient-context refusal without making outbound model requests whenever retrieval yields zero context sections.
- **FR-007**: CLI startup MUST automatically load environment variables from a `.env` file located in the explicit configuration file's directory when a configuration file path is supplied, or strictly in the current working directory otherwise (without upward parent-directory traversal, silently skipping if absent, and preserving pre-set shell variables); version control ignore rules MUST exclude `.env` and environment-variant files, and the repository MUST include a tracked `.env.example` template with placeholder entries (no real secrets) for Groq, Together.ai, OpenAI, Anthropic, Google Gemini, Azure deployments, and offline metadata mode.
- **FR-008**: Programmatic answering and embedding components MUST read provider credentials strictly from the active runtime process environment and MUST NOT read `.env` files or project configuration files directly.
- **FR-009**: Project configuration files and CLI `ask` options MUST provide full parity for online model selection, custom endpoint URL, sampling temperature, maximum output tokens, and request timeout.
- **FR-010**: Parameter resolution MUST follow strict precedence: command-line options override project configuration file settings, which override built-in system defaults.
- **FR-011**: Custom endpoint URL validation MUST allow unencrypted HTTP strictly for local loopback hosts (`localhost`, IPv4 loopback, IPv6 loopback) and MUST fail immediately before network requests or credential transmission when given a non-loopback plaintext HTTP URL.
- **FR-012**: Error sanitization MUST redact both recognized secret patterns (OpenAI-style secret keys, Groq keys, Google API keys, Bearer authorization tokens, URL basic-auth credentials, and secret URL query parameters) and exact active credential values loaded from provider environment variables (covering prefixless keys such as Together.ai and Azure tokens) from all surfaced error messages.
- **FR-013**: System MUST classify HTTP 401/403 authentication/permission failures as credential errors and MUST fail fast on HTTP 429 rate-limit or quota failures (performing no implicit automatic retries) with clean, actionable diagnostic messages free of raw credentials or full provider response dumps.
- **FR-014**: Response handling MUST inspect provider choice availability, refusal indicators, and trimmed answer text, raising clear categorized generation errors whenever choices are empty, a refusal is indicated, or the returned text is null or blank.
- **FR-015**: Project documentation MUST cover `.env` setup and owner-only file-permission hardening, project configuration defaults, CLI usage, and programmatic examples for Groq serverless and Together.ai alongside major cloud providers.

### Key Entities *(include if feature involves data)*

- **Generation Settings**: Configurable parameters governing an online or local Phase 2 answer call — provider/model identifier, optional custom endpoint URL, optional sampling temperature, optional maximum output tokens, request timeout, and optional provider pass-through parameters.
- **Structured Chat Prompt**: An ordered pair of role-scoped messages placing immutable grounding instructions in the system role and retrieved context plus the user question in the user role.
- **Local Credential Profile**: Untracked workspace key-value configuration (`.env`) paired with a tracked `.env.example` template holding API keys and gateway environment settings for selected cloud providers.
- **Custom Gateway Endpoint**: An optional target URL validated to permit unencrypted HTTP exclusively on local loopback hosts while requiring encrypted HTTPS for all remote hosts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can populate credentials from the repository template into a local `.env` file and execute a customized online model query in under 2 minutes with zero source code modifications.
- **SC-002**: 100% of default queries run without online overrides continue executing offline using the local default model with zero outbound network requests or cloud credentials.
- **SC-003**: 100% of simulated authentication, rate-limit, endpoint, and transport errors hide all recognized secret patterns and active runtime credential values from surfaced messages.
- **SC-004**: 100% of unencrypted remote custom endpoint URLs are blocked prior to any outbound request, while 100% of local loopback HTTP endpoints remain permitted.
- **SC-005**: Queries against reasoning-style models with unset temperature omit temperature across 100% of requests, while explicit deterministic temperature settings (`0.0`) are preserved across 100% of requests.
- **SC-006**: 100% of simulated rate-limit errors, empty moderated responses, and explicit provider refusals produce clear categorized diagnostic failures without unhandled crashes.
- **SC-007**: Configuration precedence resolves deterministically across 100% of overlapping combinations of command-line options, project configuration defaults, and built-in defaults.

## Assumptions

- Users opting into online cloud providers possess valid provider credentials and outbound encrypted network access from their runtime environment (except local-first offline runs or local loopback proxies).
- Built-in defaults keep temperature unset (deferring to the model provider) and request timeout at 120 seconds unless overridden by project configuration or command-line options.
- Restrictive file permissions on `.env` files (owner read/write only) are applied by the user or deployment environment according to repository security instructions rather than altered silently at runtime.
- Pre-set shell environment variables intentionally take precedence over `.env` entries so CI/CD runners, containers, and one-off shell overrides work without mutating local files.
- Interactive multi-turn chat history, streaming UI output, server deployment modes, and end-user authentication remain out of scope per the library's single-shot engine boundary.
- Automated verification runs deterministically offline using simulated provider responses rather than live external API calls in CI.

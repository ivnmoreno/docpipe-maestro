# Security Policy

## Supported Versions

Security fixes are currently applied to the `main` branch (`0.1.x` pre-release).

| Version | Supported |
|---|---|
| `main` (`0.1.x`) | Yes |

---

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for suspected security vulnerabilities.

Instead, report vulnerabilities privately via one of the following channels:

1. **GitHub Security Advisories:** Use the repository's **Security -> Advisories -> Report a vulnerability** workflow on GitHub (`https://github.com/ivnmoreno/docpipe-maestro/security/advisories`).
2. **Direct Contact:** Email the maintainer at `ivnmoreno@gmail.com` with `[SECURITY] docpipe-maestro` in the subject line.

Please include:
- A description of the vulnerability and potential impact
- Steps or a minimal script to reproduce the issue
- Affected version/commit SHA and Python/OS environment

You can expect an initial acknowledgment within 72 hours and updates as the issue is investigated and patched.

---

## Security & Privacy Model

`docpipe-maestro` is designed to operate local-first with zero external network calls by default:

- **Credentials:** Provider API keys must be supplied exclusively through environment variables (never in `docpipe.toml`, source code, or CLI flags). `MissingCredentialError` scrubs exception chains to prevent accidental key leakage in error output, and `--api-base` validates `http://` / `https://` schemes.
- **Air-Gapped Execution & `--local-only`:** Set `LITELLM_LOCAL_MODEL_COST_MAP=true` alongside local Ollama models (`ollama/nomic-embed-text`, `ollama/llama3.2`) to prevent LiteLLM's startup model-cost lookup. Passing `--local-only` (or `local_only=True`) rejects any non-local model or non-loopback `--api-base` (and non-loopback `OLLAMA_API_BASE` / `OLLAMA_HOST`) before network requests leave the process.
- **Configurable PII Protection:** Pass a programmatic `PiiPolicy` (or `--pii-policy <PATH>` JSON/TOML file on CLI `ingest`, `sync`, `ask`) to redact, HMAC-tokenize (`[ENTITY_hex8]`), or block (`PiiBlockedError`, aborting before vector/manifest commit) sensitive spans across headings, body text, and clauses pre-chunking, plus outbound egress payloads sent to remote LLM providers (`guard_egress`). Built-in deterministic recognizers cover `EMAIL_ADDRESS`, `IBAN_CODE` (MOD-97), `CREDIT_CARD` (Luhn), `US_SSN`, `IP_ADDRESS`, `PHONE_NUMBER`, and `ES_DNI`, extensible via root `@register_pii_recognizer` (`docpipe_maestro.types.PiiRecognizer`), alongside optional `[pii]` multi-language Presidio NER (`languages`, defaulting to `["en", "es"]`, offline without automatic model downloads).
- **Salt & Audit Log Handling:** For deterministic cross-run `tokenize` hashes, supply an explicit `token_salt` or `token_salt_env` secret outside the document repository; without one, `docpipe-maestro` uses an ephemeral process-random 32-byte key and emits a warning. When a `PiiPolicy` is active during `ingest`/`sync`, `<persist_dir>/manifests/<collection>.audit.jsonl` records counts, actions, thresholds, `doc_version`, and block status under `0o700`/`0o600` POSIX permissions with **zero raw PII values** (retained append-only across `remove()` calls).
- **Structured Telemetry & Error Hygiene:** Library calls remain silent by default (`NullHandler` only via `docpipe_maestro.log`, never modifying host root loggers or `stdout`). CLI flags `--log-json` and `--log-level {DEBUG,INFO,WARNING,ERROR}` emit `stderr`-only telemetry (`docpipe.toml` ignores log keys); both `JsonFormatter` and `TextFormatter` strip raw `exc_info`/`exc_text` tracebacks, stage failures emit only the `error_type` exception class name (`status="error"`), and `INFO`/`DEBUG` logs exclude raw document text, questions, prompts, completions, PII, and API keys.
- **Scope Limitations & Non-Claims:** Heuristic recognizers and optional NER produce both false positives and false negatives (especially for regional phone formats, domain-specific IDs, unstructured free text, or noisy PDF extractions). `docpipe-maestro` provides configurable technical safeguards rather than legal certification—we make no claim of automatic legal compliance, regulatory certification, or exhaustive detection accuracy. Operators remain responsible for evaluating their own policies, salt lifecycle, and corpora.
- **Trusted Corpus Assumption:** `ingest` and `sync` parse files inside user-specified directories. Only ingest trusted files, avoid directories containing untrusted symlinks or crafted HTML/PDF inputs, and protect `.docpipe/` on shared hosts (`chmod 700`, excluded from version control).

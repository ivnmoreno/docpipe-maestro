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
- **Air-Gapped Execution:** Set `LITELLM_LOCAL_MODEL_COST_MAP=true` alongside local Ollama models (`ollama/nomic-embed-text`, `ollama/llama3.2`) to prevent LiteLLM's startup model-cost lookup.
- **Trusted Corpus Assumption:** `ingest` and `sync` parse files inside user-specified directories. Only ingest trusted files, avoid directories containing untrusted symlinks or crafted HTML/PDF inputs, and protect `.docpipe/` on shared hosts (`chmod 700`, excluded from version control).

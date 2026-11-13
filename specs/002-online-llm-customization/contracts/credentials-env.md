# Local Credentials & `.env.example` Contract

**Feature**: `002-online-llm-customization` | **Option**: Option 1 (`.env` File + Tracked Template)

---

## 1. Repository Template (`.env.example`)

Committed at repository root with placeholder values only (zero live credentials):

```dotenv
# .env.example - Copy to .env (chmod 600 .env) and fill in your API keys
# Serverless Fast Inference
GROQ_API_KEY="gsk_..."
# Together.ai accepts TOGETHER_API_KEY (or TOGETHERAI_API_KEY)
TOGETHERAI_API_KEY="..."

# Major Cloud Providers
OPENAI_API_KEY="sk-..."
ANTHROPIC_API_KEY="sk-ant-..."
GEMINI_API_KEY="AIza..."

# Azure OpenAI (if applicable)
AZURE_API_KEY="..."
AZURE_API_BASE="https://your-resource.openai.azure.com/"
AZURE_API_VERSION="2024-08-01-preview"

# Optional Air-Gapped Setting (enabled by default in docpipe-maestro)
LITELLM_LOCAL_MODEL_COST_MAP="true"
```

---

## 2. Supported Provider Identifiers & Credential Mapping

| Provider | Model Identifier Example | Environment Variable(s) |
|---|---|---|
| Ollama (Local Default) | `ollama/llama3.2` | None required (no cloud key or network) |
| Groq Serverless | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Together.ai | `together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo` | `TOGETHER_API_KEY` / `TOGETHERAI_API_KEY` / `TOGETHER_AI_API_KEY` / `TOGETHER_AI_TOKEN` |
| OpenAI / o-series | `openai/gpt-4o`, `openai/o3-mini` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` |
| Mistral | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` |
| Azure OpenAI | `azure/<deployment>` | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` |
| OpenAI-compatible Gateway | `openai/<model>` + `--api-base` | `OPENAI_API_KEY` (or custom key env) |

---

## 3. Git Protection & File Permissions

- `.gitignore` excludes `.env`, `*.env`, `*.env.*`, `*.env.local`, `.env.production`, and `.env.development` (already enforced; `.env.example` remains tracked).
- User guidance in `README.md` / `.env.example` instructs restricting permissions with `chmod 600 .env` so only the OS owner can read the local file.
- `uv run --env-file .env docpipe-maestro ask ...` also works natively alongside `cli.py` startup loading.

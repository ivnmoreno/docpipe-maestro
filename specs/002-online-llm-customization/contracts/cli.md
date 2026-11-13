# CLI & TOML Configuration Contract Extensions

**Feature**: `002-online-llm-customization` | **Entry Point**: `docpipe-maestro` (`docpipe_maestro.cli:main`)

Per Constitution Principle III, `src/docpipe_maestro/cli.py` remains the sole module permitted to read `.env` files and `--config` TOML files. All resolved generation parameters are passed explicitly to `answer()`.

---

## 1. Startup `.env` Discovery (`main()`)

Before parsing subcommand options or reading configuration defaults, `cli.py` loads optional workspace credentials:

- When `--config <path>` is specified: looks strictly for `<Path(config).parent>/.env`.
- When `--config` is omitted: looks strictly for `<Path.cwd()>/.env`.
- Never traverses upward into parent directories (`find_dotenv` parent walk is not used).
- Calls `load_dotenv(dotenv_path=env_path, override=False)` only if the target `.env` file exists. Pre-set shell environment variables take precedence over `.env` entries, and missing `.env` files are silently ignored.

---

## 2. Extended `docpipe-maestro ask` Subcommand

```text
docpipe-maestro ask [--config CONFIG] [--collection COLLECTION]
                    [--persist-dir PERSIST_DIR] [--top-k TOP_K]
                    [--threshold THRESHOLD] [--model MODEL]
                    [--embed-model EMBED_MODEL] [--api-base API_BASE]
                    [--temperature TEMPERATURE] [--max-tokens MAX_TOKENS]
                    [--timeout TIMEOUT] question
```

| Flag | Type | Built-in Default | TOML Key | Behavior |
|---|---|---|---|---|
| `--model` | `str` | `"ollama/llama3.2"` | `model` | LiteLLM `provider/model` string |
| `--api-base` | `str` | `None` | `api_base` | Custom gateway URL (loopback `http://` or remote `https://`) |
| `--temperature` | `float` | `None` | `temperature` | Sampling temperature (`>= 0.0`); omitted from request when `None` |
| `--max-tokens` | `int` | `None` | `max_tokens` | Max completion tokens (`>= 1`); omitted when `None` |
| `--timeout` | `float` | `120.0` | `timeout` | Completion timeout in seconds (`> 0.0`) |

- **Prompt Dispatch**: Uses `build_chat_messages(args.question, sections)` before invoking `answer(...)` with resolved generation options.
- **Short-Circuit**: Still returns `"Not found in the provided context."` cleanly when retrieval yields zero sections (`has_context=False`).

---

## 3. TOML Configuration Schema & Strict Precedence

Supported optional generation keys in `docpipe.toml`:

```toml
# Optional Phase 2 online generation settings
model = "groq/llama-3.3-70b-versatile"
api_base = "https://api.example.com/v1"
temperature = 0.0
max_tokens = 512
timeout = 30.0
```

- **Strict Precedence**: Explicit CLI flag > `--config` TOML value > Built-in default (`config.py` / `DEFAULT_REQUEST_TIMEOUT`).
- **Type Validation**: Invalid TOML types (e.g., `bool` for `int`/`float`, strings for numbers, wrong scalar type for `api_base`) fail fast with `DocpipeError("Invalid TOML config value for ...")` rendered cleanly as single-line `Error: ...` on `stderr` with exit code `1`.
- **Security Prohibition**: Never store API keys inside `docpipe.toml`; store provider credentials strictly in environment variables or untracked `.env`.

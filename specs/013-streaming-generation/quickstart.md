# Quickstart Validation Guide: Streaming Generation Support (`013-streaming-generation`)

**Feature**: `013-streaming-generation` | **Date**: 2026-11-17 | **Spec**: [spec.md](spec.md)

## Scenario 1: Synchronous Library Streaming & Eager Safety Checks

```python
from docpipe_maestro import answer, build_chat_messages, retrieve

sections = retrieve("How many leave days?", collection="policies")
messages = build_chat_messages("How many leave days?", sections)

# Stream chunks synchronously as the model generates them
for delta in answer(messages, model="ollama/llama3.2", has_context=bool(sections), stream=True):
    print(delta, end="", flush=True)
print()
```

Expected:
- Yields non-empty string deltas progressively without stripping internal/boundary whitespace.
- Uniterated calls perform zero LLM calls; invalid parameters, `local_only=True` remote models, and blocked outbound `PiiPolicy` inputs raise typed exceptions immediately at call time.

## Scenario 2: CLI Real-Time `ask --stream` & Mode Guards

```bash
# Stream grounded answer chunks to stdout while keeping context and telemetry on stderr
docpipe-maestro ask "What is the leave exception?" \
  --collection policies \
  --show-context \
  --log-json \
  --stream

# Verify --stream and --json are rejected together upfront before retrieval
docpipe-maestro ask "What is the leave exception?" --stream --json
```

Expected:
- `--stream` prints answer text progressively to `stdout` with immediate flush and trailing newline; `--show-context` and JSON stage logs stay cleanly on `stderr` under one CLI `correlation_id`.
- `--stream --json` exits non-zero (`2`) cleanly without executing retrieval or generation.

## Scenario 3: Quality, Safety & Coverage Gates

```bash
uv run --no-sync pytest tests/test_prompts_answer.py tests/test_cli.py tests/test_logging.py tests/test_api_stability.py tests/test_pii_safety.py -v
uv run --no-sync pytest -m reverse -v
uv run --no-sync pytest -m pii -v
LITELLM_LOCAL_MODEL_COST_MAP=true uv run --no-sync pytest -v --cov
```

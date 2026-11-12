"""Unit tests for pure prompt construction and optional grounded generation."""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from docpipe_maestro import answer, build_prompt
from docpipe_maestro.query.answer import EMPTY_CONTEXT_REFUSAL
from docpipe_maestro.types import MissingCredentialError, RetrievedChunk


def _sample_section() -> RetrievedChunk:
    return RetrievedChunk(
        id="p1",
        text="Employees get 20 days leave except probationary hires.",
        parent_id=None,
        metadata={
            "type": "parent",
            "source": "handbook.pdf",
            "doc_version": "abc123",
            "section": "Section 1: Leave",
            "clause": None,
            "page": 4,
            "chunk_index": 0,
            "embed_model": "ollama/nomic-embed-text",
        },
        vector=[0.0] * 4,
        score=0.92,
    )


def test_build_prompt_is_pure_fast_and_preserves_citations() -> None:
    sec = _sample_section()
    t0 = time.perf_counter()
    prompt = build_prompt("How many days of leave?", [sec])
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 5.0
    assert "handbook.pdf" in prompt
    assert "Section 1: Leave" in prompt
    assert "Page: 4" in prompt
    assert "except probationary hires" in prompt
    assert "ONLY the provided context" in prompt


def test_answer_short_circuits_on_empty_context(
    mock_litellm_offline: dict[str, Any],
) -> None:
    prompt = build_prompt("What is the secret code?", [])
    res = answer(prompt, has_context=False)
    assert res == EMPTY_CONTEXT_REFUSAL
    assert mock_litellm_offline["completion"] == []


def test_answer_uses_local_default_and_never_leaks_credentials(
    monkeypatch: pytest.MonkeyPatch,
    mock_litellm_offline: dict[str, Any],
) -> None:
    prompt = build_prompt("How many days of leave?", [_sample_section()])
    res = answer(prompt)
    assert "ollama/llama3.2" in res
    assert mock_litellm_offline["completion"][0]["model"] == "ollama/llama3.2"

    secret_val = "sk-super-secret-value-999"
    monkeypatch.setenv("OPENAI_API_KEY", secret_val)

    import litellm

    def fail_auth(**kwargs: Any) -> Any:
        raise RuntimeError(f"AuthenticationError: invalid api_key {os.environ['OPENAI_API_KEY']}")

    monkeypatch.setattr(litellm, "completion", fail_auth)
    with pytest.raises(MissingCredentialError) as exc_info:
        answer(prompt, model="openai/gpt-4o-mini")
    assert secret_val not in str(exc_info.value)

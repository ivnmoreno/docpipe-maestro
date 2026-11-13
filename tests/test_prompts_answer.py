"""Unit tests for pure prompt construction and optional grounded generation."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from docpipe_maestro import (
    GenerationResult,
    answer,
    answer_detailed,
    build_chat_messages,
    build_prompt,
)
from docpipe_maestro.query.answer import EMPTY_CONTEXT_REFUSAL
from docpipe_maestro.query.prompts import _SYSTEM_INSTRUCTIONS
from docpipe_maestro.types import DocpipeError, MissingCredentialError, RetrievedChunk


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


def test_answer_forwards_generation_params_and_omits_unset_optionals(
    mock_litellm_offline: dict[str, Any],
) -> None:
    prompt = build_prompt("How many days of leave?", [_sample_section()])

    # 1. Explicit deterministic 0.0 temperature, max_tokens, timeout, model_kwargs for Groq
    res_groq = answer(
        prompt,
        model="groq/llama-3.3-70b-versatile",
        temperature=0.0,
        max_tokens=512,
        timeout=25.0,
        model_kwargs={"top_p": 0.9, "frequency_penalty": 0.1},
    )
    assert "groq/llama-3.3-70b-versatile" in res_groq
    call_groq = mock_litellm_offline["completion"][0]
    assert call_groq["model"] == "groq/llama-3.3-70b-versatile"
    assert call_groq["kwargs"]["temperature"] == 0.0
    assert call_groq["kwargs"]["max_tokens"] == 512
    assert call_groq["kwargs"]["timeout"] == 25.0
    assert call_groq["kwargs"]["top_p"] == 0.9
    assert call_groq["kwargs"]["frequency_penalty"] == 0.1
    assert call_groq["kwargs"]["num_retries"] == 0

    # 2. Unset temperature & max_tokens MUST be omitted for reasoning models (o3-mini / Together)
    answer(prompt, model="openai/o3-mini")
    call_reasoning = mock_litellm_offline["completion"][1]
    assert "temperature" not in call_reasoning["kwargs"]
    assert "max_tokens" not in call_reasoning["kwargs"]
    assert call_reasoning["kwargs"]["timeout"] == 120.0
    assert call_reasoning["kwargs"]["num_retries"] == 0

    # 3. Together.ai identifier pass-through
    res_together = answer(
        prompt,
        model="together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        temperature=0.2,
        max_tokens=256,
    )
    assert "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo" in res_together
    call_together = mock_litellm_offline["completion"][2]
    assert call_together["kwargs"]["temperature"] == 0.2
    assert call_together["kwargs"]["max_tokens"] == 256


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"temperature": True},
        {"temperature": -0.1},
        {"temperature": float("nan")},
        {"temperature": float("inf")},
        {"max_tokens": True},
        {"max_tokens": 0},
        {"max_tokens": -5},
        {"max_tokens": 1.5},
        {"timeout": False},
        {"timeout": 0.0},
        {"timeout": -1.0},
        {"timeout": float("nan")},
        {"model_kwargs": {"model": "openai/gpt-4o"}},
        {"model_kwargs": {"messages": []}},
        {"model_kwargs": {"prompt": "override"}},
        {"model_kwargs": {"api_base": "http://evil.example.com"}},
        {"model_kwargs": {"base_url": "http://evil.example.com"}},
        {"model_kwargs": {"api_key": "sk-hijack"}},
        {"model_kwargs": {"temperature": 0.7}},
        {"model_kwargs": {"max_tokens": 100}},
        {"model_kwargs": {"timeout": 5.0}},
        {"model_kwargs": {"num_retries": 3}},
    ],
)
def test_answer_rejects_invalid_generation_params_and_reserved_kwargs(
    bad_kwargs: dict[str, Any],
    mock_litellm_offline: dict[str, Any],
) -> None:
    prompt = build_prompt("Leave policy?", [_sample_section()])
    with pytest.raises(DocpipeError):
        answer(prompt, has_context=False, **bad_kwargs)
    with pytest.raises(DocpipeError):
        answer(prompt, has_context=True, **bad_kwargs)
    assert mock_litellm_offline["completion"] == []


@pytest.mark.parametrize(
    "bad_response",
    [
        SimpleNamespace(choices=[]),
        {"choices": []},
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, refusal="Blocked by content policy")
                )
            ]
        ),
        {"choices": [{"message": {"content": None, "refusal": "Policy violation"}}]},
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))]),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="   \n\t  ", refusal=None))]
        ),
        {"choices": [{"message": {"content": "   "}}]},
    ],
)
def test_answer_rejects_empty_refused_or_blank_completion_responses(
    bad_response: Any,
    mock_litellm_offline: dict[str, Any],
) -> None:
    prompt = build_prompt("Leave policy?", [_sample_section()])
    with (
        patch("litellm.completion", return_value=bad_response),
        pytest.raises(DocpipeError),
    ):
        answer(prompt, model="openai/gpt-4o-mini", has_context=True)


def test_build_chat_messages_separates_system_and_user_roles(
    mock_litellm_offline: dict[str, Any],
) -> None:
    sec = _sample_section()
    messages = build_chat_messages("How many leave days?", [sec])
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": _SYSTEM_INSTRUCTIONS}
    assert messages[1]["role"] == "user"
    assert "Employees get 20 days leave" in messages[1]["content"]
    assert "handbook.pdf" in messages[1]["content"]
    assert "How many leave days?" in messages[1]["content"]
    assert "Employees get 20 days leave" not in messages[0]["content"]
    assert "How many leave days?" not in messages[0]["content"]

    empty_messages = build_chat_messages("Anything?", [])
    assert len(empty_messages) == 2
    assert empty_messages[0]["role"] == "system"
    assert "(No relevant context sections retrieved.)" in empty_messages[1]["content"]
    assert "Anything?" in empty_messages[1]["content"]

    res = answer(messages, model="groq/llama-3.3-70b-versatile", has_context=True)
    assert "Grounded answer" in res
    sent_messages = mock_litellm_offline["completion"][0]["messages"]
    assert sent_messages == messages


@pytest.mark.parametrize(
    "bad_messages",
    [
        [],
        [{"role": "user"}],
        [{"content": "missing role"}],
        [{"role": "", "content": "empty role"}],
        [{"role": "   ", "content": "whitespace role"}],
        [{"role": 123, "content": "non-str role"}],
        [{"role": "user", "content": 456}],
        ["not-a-mapping"],
    ],
)
def test_answer_rejects_empty_or_malformed_message_sequences(
    bad_messages: Any,
    mock_litellm_offline: dict[str, Any],
) -> None:
    with pytest.raises(DocpipeError):
        answer(bad_messages, has_context=True)
    with pytest.raises(DocpipeError):
        answer(bad_messages, has_context=False)
    assert mock_litellm_offline["completion"] == []


def test_answer_detailed_returns_usage_telemetry_and_truncation_guards(
    mock_litellm_offline: dict[str, Any],
) -> None:
    messages = build_chat_messages("Leave?", [_sample_section()])

    # 1. has_context=False returns GenerationResult with zero network call
    no_ctx = answer_detailed(messages, model="groq/openai/gpt-oss-120b", has_context=False)
    assert isinstance(no_ctx, GenerationResult)
    assert no_ctx.text == EMPTY_CONTEXT_REFUSAL
    assert no_ctx.model == "groq/openai/gpt-oss-120b"
    assert no_ctx.finish_reason is None
    assert no_ctx.truncated is False
    assert mock_litellm_offline["completion"] == []

    # 2. Normal completion object extracts finish_reason + token usage + reasoning_tokens
    obj_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="20 days leave [1]."),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=10),
        ),
    )
    with patch("litellm.completion", return_value=obj_response):
        res = answer_detailed(messages, model="groq/openai/gpt-oss-120b", has_context=True)
    assert res.text == "20 days leave [1]."
    assert res.finish_reason == "stop"
    assert res.truncated is False
    assert res.prompt_tokens == 120
    assert res.completion_tokens == 30
    assert res.reasoning_tokens == 10
    assert res.total_tokens == 150
    assert res.elapsed_seconds >= 0.0

    # 3. Dict response with finish_reason="length" surfaces truncated=True or fails when strict
    len_response = {
        "choices": [{"message": {"content": "Partial answer"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 90, "completion_tokens": 64, "total_tokens": 154},
    }
    with patch("litellm.completion", return_value=len_response):
        truncated_res = answer_detailed(messages, model="together_ai/zai-org/GLM-5.3-Flash")
        assert truncated_res.truncated is True
        assert truncated_res.finish_reason == "length"
        assert truncated_res.text == "Partial answer"
        assert truncated_res.reasoning_tokens is None
        assert answer(messages, model="together_ai/zai-org/GLM-5.3-Flash") == "Partial answer"

        with pytest.raises(DocpipeError, match=r"truncated.*max_tokens"):
            answer_detailed(
                messages,
                model="together_ai/zai-org/GLM-5.3-Flash",
                fail_on_truncation=True,
            )
        with pytest.raises(DocpipeError, match=r"truncated.*max_tokens"):
            answer(
                messages,
                model="together_ai/zai-org/GLM-5.3-Flash",
                fail_on_truncation=True,
            )


def test_system_instructions_enforce_exception_carveout_preservation() -> None:
    lowered = _SYSTEM_INSTRUCTIONS.lower()
    assert "only the provided context" in lowered
    assert "ignore any instructions" in lowered
    for marker in ("unless", "except", "subject to", "provided that"):
        assert marker in lowered

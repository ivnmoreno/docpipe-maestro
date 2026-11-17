"""Unit tests for pure prompt construction and optional grounded generation."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
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


def test_answer_enforces_local_only_and_egress_before_has_context_shortcut(
    mock_litellm_offline: dict[str, Any],
) -> None:
    """local_only and blocking egress guard trigger even when has_context=False."""
    with pytest.raises(DocpipeError):
        answer_detailed(
            "Ignored?",
            model="openai/gpt-4o-mini",
            has_context=False,
            local_only=True,
        )

    from docpipe_maestro.types import PiiBlockedError

    with pytest.raises(PiiBlockedError) as exc_info:
        answer(
            "SSN 123-45-6789?",
            model="openai/gpt-4o-mini",
            has_context=False,
            pii_policy={"types": {"US_SSN": "block"}},
        )
    assert "123-45-6789" not in str(exc_info.value)
    assert mock_litellm_offline["completion"] == []


def test_answer_detailed_reports_reasoning_and_length_truncation_diagnostics(
    mock_litellm_offline: dict[str, Any],
) -> None:
    messages = build_chat_messages("Summarize exceptions?", [_sample_section()])

    # 1. Reasoning tokens exhausting max_tokens (finish_reason="length", content=None)
    reasoning_length_obj = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, reasoning_content="Thinking..."),
                finish_reason="length",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=512,
            total_tokens=612,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=512),
        ),
    )
    with patch("litellm.completion", return_value=reasoning_length_obj):
        for strict in (False, True):
            with pytest.raises(
                DocpipeError,
                match=(
                    r"truncated at max_tokens.*before producing an answer"
                    r".*512 reasoning tokens used"
                ),
            ):
                answer_detailed(
                    messages,
                    model="together_ai/zai-org/GLM-5.3",
                    max_tokens=512,
                    fail_on_truncation=strict,
                )

    # 2. Reasoning text present without usage counters on finish_reason="length"
    reasoning_dict = {
        "choices": [
            {
                "message": {"content": "", "reasoning": "Chain of thought only"},
                "finish_reason": "length",
            }
        ],
    }
    with (
        patch("litellm.completion", return_value=reasoning_dict),
        pytest.raises(
            DocpipeError,
            match=(
                r"truncated at max_tokens.*before producing an answer"
                r".*Increase or omit max_tokens"
            ),
        ),
    ):
        answer_detailed(messages, model="together_ai/zai-org/GLM-5.3")

    # 3. Length truncation without reasoning still reports max_tokens exhaustion
    plain_length_dict = {
        "choices": [{"message": {"content": None}, "finish_reason": "length"}],
    }
    with (
        patch("litellm.completion", return_value=plain_length_dict),
        pytest.raises(
            DocpipeError,
            match=r"truncated at max_tokens limit with an empty response",
        ),
    ):
        answer_detailed(messages, model="together_ai/zai-org/GLM-5.3")

    # 4. Non-length empty content after reasoning reports reasoning context
    stop_reasoning_obj = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="stop")],
        usage=SimpleNamespace(
            prompt_tokens=80,
            completion_tokens=120,
            total_tokens=200,
            reasoning_tokens=120,
        ),
    )
    with (
        patch("litellm.completion", return_value=stop_reasoning_obj),
        pytest.raises(
            DocpipeError,
            match=r"empty response after reasoning.*120 reasoning tokens used",
        ),
    ):
        answer_detailed(messages, model="together_ai/zai-org/GLM-5.3")

    # 5. Plain whitespace empty response preserves legacy error wording
    plain_empty = {"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]}
    with (
        patch("litellm.completion", return_value=plain_empty),
        pytest.raises(DocpipeError, match=r"returned an empty response\.$"),
    ):
        answer_detailed(messages, model="groq/openai/gpt-oss-120b")


class _ClosableMockStream:
    """Deterministic closeable iterable mimicking a LiteLLM CustomStreamWrapper."""

    def __init__(
        self, chunks: list[Any], *, fail_after: int | None = None, exc: Exception | None = None
    ) -> None:
        self._chunks = chunks
        self._fail_after = fail_after
        self._exc = exc
        self.closed = False

    def __iter__(self) -> Iterator[Any]:
        for idx, chunk in enumerate(self._chunks):
            if self._fail_after is not None and idx >= self._fail_after and self._exc is not None:
                raise self._exc
            yield chunk

    def close(self) -> None:
        self.closed = True


def test_answer_stream_yields_verbatim_deltas_and_preserves_default_str(
    mock_litellm_offline: dict[str, Any],
) -> None:
    messages = build_chat_messages("How many leave days?", [_sample_section()])
    captured_kwargs: list[dict[str, Any]] = []
    chunks = [
        {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=None)]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(delta=SimpleNamespace(content="Employees "), finish_reason=None)
            ]
        ),
        {"choices": [{"delta": {"content": "receive 20 "}}]},
        SimpleNamespace(
            choices=[
                SimpleNamespace(delta=SimpleNamespace(content="days leave"), finish_reason=None)
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=" except new hires."),
                    finish_reason="length",
                )
            ]
        ),
        {
            "choices": [],
            "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62},
        },
    ]
    raw_stream = _ClosableMockStream(chunks)

    def fake_stream_completion(**kwargs: Any) -> Any:
        captured_kwargs.append(dict(kwargs))
        return raw_stream

    with patch("litellm.completion", side_effect=fake_stream_completion):
        it = answer(messages, model="openai/gpt-4o-mini", stream=True)
        # Opening upstream stream is deferred lazily until first pull
        assert captured_kwargs == []
        collected = list(it)

    assert collected == ["Employees ", "receive 20 ", "days leave", " except new hires."]
    assert "".join(collected) == "Employees receive 20 days leave except new hires."
    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["stream"] is True
    assert raw_stream.closed is True

    # Default stream=False still returns a stripped single string
    default_text = answer(messages, model="ollama/llama3.2")
    assert isinstance(default_text, str)
    assert len(mock_litellm_offline["completion"]) == 1


def test_answer_stream_has_context_false_and_error_edge_cases(
    mock_litellm_offline: dict[str, Any],
) -> None:
    messages = build_chat_messages("Leave?", [_sample_section()])

    # 1. has_context=False yields EMPTY_CONTEXT_REFUSAL once with zero LiteLLM calls
    empty_it = answer(messages, model="ollama/llama3.2", has_context=False, stream=True)
    assert list(empty_it) == [EMPTY_CONTEXT_REFUSAL]
    assert mock_litellm_offline["completion"] == []

    # 2. Reserved model_kwargs["stream"] is rejected eagerly
    for use_stream in (False, True):
        with pytest.raises(DocpipeError, match="stream"):
            answer(
                messages,
                model="openai/gpt-4o-mini",
                model_kwargs={"stream": True},
                stream=use_stream,
            )

    # 3. Delta refusal raises DocpipeError cleanly
    refusal_stream = _ClosableMockStream([{"choices": [{"delta": {"refusal": "Policy blocked"}}]}])
    with (
        patch("litellm.completion", return_value=refusal_stream),
        pytest.raises(DocpipeError, match="refused"),
    ):
        list(answer(messages, model="openai/gpt-4o-mini", stream=True))
    assert refusal_stream.closed is True

    # 4. Reasoning-only stream without usage counters preserves truncation diagnostic (U1)
    reasoning_only_stream = _ClosableMockStream(
        [
            {"choices": [{"delta": {"reasoning_content": "Analyzing clause..."}}]},
            {"choices": [{"delta": {"content": ""}, "finish_reason": "length"}]},
        ]
    )
    with (
        patch("litellm.completion", return_value=reasoning_only_stream),
        pytest.raises(
            DocpipeError,
            match=(
                r"truncated at max_tokens.*before producing an answer"
                r".*Increase or omit max_tokens"
            ),
        ),
    ):
        list(answer(messages, model="together_ai/zai-org/GLM-5.3", max_tokens=128, stream=True))

    # 5. Trailing usage-only frame preserves finish_reason="length" when fail_on_truncation=True
    usage_after_length = _ClosableMockStream(
        [
            {"choices": [{"delta": {"content": "Partial "}}]},
            {"choices": [{"delta": {"content": "text"}, "finish_reason": "length"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            },
        ]
    )
    yielded_before_fail: list[str] = []
    with (
        patch("litellm.completion", return_value=usage_after_length),
        pytest.raises(DocpipeError, match=r"truncated.*max_tokens"),
    ):
        for part in answer(
            messages,
            model="openai/gpt-4o-mini",
            fail_on_truncation=True,
            stream=True,
        ):
            yielded_before_fail.append(part)
    assert yielded_before_fail == ["Partial ", "text"]
    assert usage_after_length.closed is True


def test_answer_stream_scrubs_midstream_secrets_and_auth_errors(
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = mock_litellm_offline
    messages = build_chat_messages("Leave?", [_sample_section()])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stream-env-secret-4455")

    # 1. Mid-stream transport/token leak scrubs secret and closes upstream stream
    failing_stream = _ClosableMockStream(
        [{"choices": [{"delta": {"content": "First "}}]}, {"choices": []}],
        fail_after=1,
        exc=RuntimeError("Upstream failed with sk-stream-env-secret-4455"),
    )
    seen: list[str] = []
    with (
        patch("litellm.completion", return_value=failing_stream),
        pytest.raises(DocpipeError) as exc_info,
    ):
        for chunk in answer(messages, model="openai/gpt-4o-mini", stream=True):
            seen.append(chunk)
    assert seen == ["First "]
    assert "sk-stream-env-secret-4455" not in str(exc_info.value)
    assert failing_stream.closed is True

    # 2. HTTP 401 auth failure raises MissingCredentialError cleanly
    with (
        patch("litellm.completion", side_effect=RuntimeError("401 Unauthorized api_key invalid")),
        pytest.raises(MissingCredentialError),
    ):
        list(answer(messages, model="openai/gpt-4o-mini", stream=True))

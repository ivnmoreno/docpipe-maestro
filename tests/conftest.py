"""Shared pytest fixtures and offline deterministic test doubles."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

EMBED_DIM = 64
_WORD_RE = re.compile(r"[a-z0-9]+")


def deterministic_embed(texts: list[str], dim: int = EMBED_DIM) -> list[list[float]]:
    """Compute a deterministic, L2-normalized bag-of-words hash embedding."""
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dim
        tokens = _WORD_RE.findall(text.lower())
        if not tokens:
            vec[0] = 1.0
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            vec = [v / norm for v in vec]
        else:
            vec[0] = 1.0
        vectors.append(vec)
    return vectors


@pytest.fixture
def tmp_persist_dir(tmp_path: Path) -> Path:
    """Return a clean temporary persistence directory for ChromaDB and manifests."""
    persist_dir = tmp_path / ".docpipe"
    persist_dir.mkdir(parents=True, exist_ok=True)
    return persist_dir


@pytest.fixture
def mock_litellm_offline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch litellm.embedding and litellm.completion for deterministic offline tests."""
    calls: dict[str, Any] = {"embedding": [], "completion": []}

    def fake_embedding(*, model: str, input: list[str], **kwargs: Any) -> dict[str, Any]:
        calls["embedding"].append({"model": model, "input": list(input), "kwargs": kwargs})
        dim = 32 if "small" in model else EMBED_DIM
        vecs = deterministic_embed(input, dim=dim)
        return {
            "data": [{"index": idx, "embedding": vec} for idx, vec in enumerate(vecs)],
            "model": model,
        }

    def fake_completion(
        *, model: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> SimpleNamespace:
        calls["completion"].append({"model": model, "messages": list(messages), "kwargs": kwargs})
        user_msg = messages[-1]["content"] if messages else ""
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            f"[mock:{model}] Grounded answer based on provided context. "
                            f"({len(user_msg)} chars)"
                        )
                    )
                )
            ]
        )

    import litellm

    monkeypatch.setattr(litellm, "embedding", fake_embedding)
    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls

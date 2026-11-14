"""Offline unit and integration tests for Phase 2 child-first reranking."""

from __future__ import annotations

import concurrent.futures
import contextlib
import importlib.util
import math
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, retrieve
from docpipe_maestro.query.reranker import (
    RERANKERS,
    CrossEncoderReranker,
    register_reranker,
)
from docpipe_maestro.query.reranker import (
    cross_encoder as ce_mod,
)
from docpipe_maestro.query.searcher import SEARCHERS, register_searcher
from docpipe_maestro.query.stages import Reranker
from docpipe_maestro.types import DocpipeError, MissingExtraError, RegistryError, RetrievedChunk


def _chunk(
    cid: str,
    text: str,
    *,
    parent_id: str | None = "p1",
    score: float = 0.5,
    source: str = "doc.md",
    section: str = "Sec 1",
) -> RetrievedChunk:
    return RetrievedChunk(
        id=cid,
        text=text,
        parent_id=parent_id,
        metadata={
            "type": "child" if parent_id else "parent",
            "source": source,
            "doc_version": "abc123def456",
            "section": section,
            "clause": cid,
            "page": 1,
            "chunk_index": 0,
            "embed_model": "ollama/nomic-embed-text",
        },
        score=score,
    )


@contextlib.contextmanager
def _clean_registry(reg: Any) -> Iterator[None]:
    entries = dict(reg._entries)
    lazy = dict(reg._lazy_builtins)
    try:
        yield
    finally:
        reg._entries = entries
        reg._lazy_builtins = lazy


@contextlib.contextmanager
def _clean_model_cache() -> Iterator[None]:
    ce_mod._MODEL_CACHE.clear()
    try:
        yield
    finally:
        ce_mod._MODEL_CACHE.clear()


class _FakeModel:
    """Deterministic fake CrossEncoder returning preset raw logits per predict call."""

    def __init__(self, scorer: Any) -> None:
        self._scorer = scorer
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, pairs: list[tuple[str, str]]) -> Any:
        self.calls.append(list(pairs))
        return self._scorer(pairs)


# ---------------------------------------------------------------------------
# T008: CrossEncoderReranker Unit, Sigmoid Normalization & Cache Tests
# ---------------------------------------------------------------------------


def test_cross_encoder_protocol_and_validation() -> None:
    inst = CrossEncoderReranker()
    assert isinstance(inst, Reranker)
    assert inst.name == "cross_encoder"
    assert RERANKERS.resolve("cross_encoder") is CrossEncoderReranker

    with pytest.raises(ValueError, match="model_name"):
        CrossEncoderReranker("")
    with pytest.raises(ValueError, match="model_name"):
        CrossEncoderReranker("   ")


def test_cross_encoder_sigmoid_sorting_ties_and_immutability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeModel(lambda pairs: [-1000.0, 2.0, 2.0, 1000.0, 0.0][: len(pairs)])
    with _clean_model_cache():
        monkeypatch.setattr(ce_mod, "_instantiate_cross_encoder", lambda _m: fake)
        c0 = _chunk("c0", "neg extreme", score=0.91)
        c1 = _chunk("c1", "tie first", score=0.10)
        c2 = _chunk("c2", "tie second", score=0.20)
        c3 = _chunk("c3", "pos extreme", score=0.05)
        c4 = _chunk("c4", "zero logit", score=0.33)
        inputs = [c0, c1, c2, c3, c4]

        out = CrossEncoderReranker().rerank("policy leave", inputs, top_k=4)

    assert len(fake.calls) == 1
    assert fake.calls[0] == [
        ("policy leave", "neg extreme"),
        ("policy leave", "tie first"),
        ("policy leave", "tie second"),
        ("policy leave", "pos extreme"),
        ("policy leave", "zero logit"),
    ]
    assert [c.id for c in out] == ["c3", "c1", "c2", "c4"]
    assert out[0].score == 1.0
    assert out[3].score == pytest.approx(0.5)
    assert all(0.0 <= c.score <= 1.0 for c in out)
    # Input RetrievedChunk (slots=True) objects remain untouched.
    assert [c.score for c in inputs] == [0.91, 0.10, 0.20, 0.05, 0.33]
    assert out[0] is not c3


def test_cross_encoder_scalar_extreme_neg_and_empty_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class _ScalarZeroDim:
        ndim = 0

        def __float__(self) -> float:
            return -1000.0

    def _create(_m: str) -> _FakeModel:
        nonlocal calls
        calls += 1
        return _FakeModel(lambda _pairs: _ScalarZeroDim())

    reranker = CrossEncoderReranker()
    with _clean_model_cache():
        monkeypatch.setattr(ce_mod, "_instantiate_cross_encoder", _create)
        assert reranker.rerank("q", [], top_k=5) == []
        assert reranker.rerank("q", [_chunk("c0", "hi")], top_k=0) == []
        assert calls == 0

        single = reranker.rerank("q", [_chunk("c0", "hi", score=0.8)], top_k=3)
        assert calls == 1
        assert len(single) == 1
        assert 0.0 <= single[0].score < 1e-12


@pytest.mark.parametrize(
    "bad_preds",
    [
        [float("nan")],
        [float("inf")],
        [float("-inf")],
        [0.1, 0.2],
        [],
    ],
)
def test_cross_encoder_rejects_non_finite_or_length_mismatch(
    bad_preds: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _clean_model_cache():
        monkeypatch.setattr(
            ce_mod,
            "_instantiate_cross_encoder",
            lambda _m: _FakeModel(lambda _pairs: bad_preds),
        )
        with pytest.raises(DocpipeError):
            CrossEncoderReranker().rerank("q", [_chunk("c0", "only one")], top_k=5)


def test_cross_encoder_model_cache_reuse_isolation_and_thread_safety(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str] = []
    create_lock = threading.Lock()
    barrier = threading.Barrier(4)

    def _create(model_name: str) -> _FakeModel:
        with create_lock:
            created.append(model_name)
        time.sleep(0.02)
        return _FakeModel(lambda pairs: [1.0 if model_name == "model-a" else -1.0 for _ in pairs])

    with _clean_model_cache():
        monkeypatch.setattr(ce_mod, "_instantiate_cross_encoder", _create)

        # Sequential repeat calls reuse model-a; distinct model-b isolates cleanly.
        ra = CrossEncoderReranker("model-a")
        rb = CrossEncoderReranker("model-b")
        out_a1 = ra.rerank("q", [_chunk("c1", "alpha")], top_k=1)
        out_a2 = ra.rerank("q", [_chunk("c2", "beta")], top_k=1)
        out_b1 = rb.rerank("q", [_chunk("c1", "alpha")], top_k=1)

        assert created == ["model-a", "model-b"]
        assert math.isclose(out_a1[0].score, out_a2[0].score)
        assert out_a1[0].score > 0.7
        assert out_b1[0].score < 0.3

        # Concurrent cold loads for the same model_name instantiate once under lock.
        def _worker() -> float:
            barrier.wait(timeout=5.0)
            res = CrossEncoderReranker("concurrent-model").rerank(
                "q", [_chunk("c9", "thread test")], top_k=1
            )
            return res[0].score

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            scores = list(pool.map(lambda _: _worker(), range(4)))

        assert len(scores) == 4
        assert created.count("concurrent-model") == 1


# ---------------------------------------------------------------------------
# T009: Child-First Retrieval Integration Tests
# ---------------------------------------------------------------------------


def _seed_multidoc_policy(tmp_path: Path, persist_dir: Path, collection: str) -> Path:
    corpus = tmp_path / f"corpus_{collection}"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "leave_policy.md").write_text(
        (
            "## Section 1: Annual Leave Entitlement\n\n"
            "1.1 Employees receive 25 days of paid annual leave each year.\n\n"
            "1.2 Seasonal contractors are excluded except when explicitly specified in writing.\n\n"
            "1.3 Unused days require compliance sign-off (see Section 2 in travel_policy.md).\n\n"
            "## Section 2: Parking Benefits\n\n"
            "2.1 Bicycle storage passes are issued upon badge activation.\n"
        ),
        encoding="utf-8",
    )
    (corpus / "travel_policy.md").write_text(
        (
            "## Section 1: Flight Class\n\n"
            "1.1 Economy class airfare is standard for all domestic trips.\n\n"
            "## Section 2: Leave Sign-Off Authority\n\n"
            "2.1 Department heads approve carried leave days above the annual statutory cap.\n"
        ),
        encoding="utf-8",
    )
    ingest(corpus, profile="POLICY", collection=collection, persist_dir=persist_dir)
    return corpus


def test_child_first_parent_dedup_max_score_and_crossrefs(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_multidoc_policy(tmp_path, tmp_persist_dir, "rerank_p1")

    observed_rerank_limits: list[tuple[int, int]] = []

    def _score_pairs(pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        for _q, text in pairs:
            lower = text.lower()
            if "flight class" in lower or "economy class" in lower:
                scores.append(6.0)  # Boost Travel Section 1 highest
            elif "bicycle" in lower:
                scores.append(2.0)  # Moderate boost for Leave Section 2
            elif "department heads approve" in lower:
                scores.append(1.5)
            else:
                scores.append(-3.0)
        return scores

    orig_rerank = CrossEncoderReranker.rerank

    def _spy_rerank(
        self: CrossEncoderReranker,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        observed_rerank_limits.append((len(chunks), top_k))
        return orig_rerank(self, query, chunks, top_k=top_k)

    with _clean_model_cache():
        monkeypatch.setattr(
            ce_mod,
            "_instantiate_cross_encoder",
            lambda _m: _FakeModel(_score_pairs),
        )
        monkeypatch.setattr(CrossEncoderReranker, "rerank", _spy_rerank)

        expanded = retrieve(
            "annual leave sign-off",
            collection="rerank_p1",
            persist_dir=tmp_persist_dir,
            top_k=2,
            expand_parent=True,
            follow_crossrefs=True,
            rerank=True,
        )
        children_only = retrieve(
            "annual leave sign-off",
            collection="rerank_p1",
            persist_dir=tmp_persist_dir,
            top_k=2,
            expand_parent=False,
            rerank=True,
        )

    # expand_parent=True must pass top_k=len(child_matches) to avoid pre-dedup starvation.
    assert observed_rerank_limits[0][0] == observed_rerank_limits[0][1]
    assert observed_rerank_limits[1][1] == 2

    assert len(expanded) == 2
    assert len({r.id for r in expanded}) == 2
    assert "Flight Class" in expanded[0].metadata["section"]
    assert "1.1 Economy class airfare" in expanded[0].text
    assert expanded[0].score == pytest.approx(1.0 / (1.0 + math.exp(-6.0)))
    assert expanded[0].score > expanded[1].score

    assert len(children_only) == 2
    assert all(c.metadata["type"] == "child" for c in children_only)
    assert "Economy class airfare" in children_only[0].text

    # Confirm cross-document reference enrichment stays active when target absent from top_k=1.
    with _clean_model_cache():
        monkeypatch.setattr(
            ce_mod,
            "_instantiate_cross_encoder",
            lambda _m: _FakeModel(
                lambda pairs: [
                    8.0 if "section 2 in travel_policy.md" in txt.lower() else -5.0
                    for _q, txt in pairs
                ]
            ),
        )
        crossref_hit = retrieve(
            "unused days leave compliance",
            collection="rerank_p1",
            persist_dir=tmp_persist_dir,
            top_k=1,
            expand_parent=True,
            follow_crossrefs=True,
            rerank=True,
        )
    assert len(crossref_hit) == 1
    assert "[Crossref" in crossref_hit[0].text


def test_rerank_pool_depth_threshold_doc_version_and_hybrid(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = tmp_path / "ver_corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    doc = corpus / "bonus.md"
    doc.write_text(
        "## Section 1: Bonus Policy\n\n1.1 LEGACY_BONUS_500 paid automatically.\n",
        encoding="utf-8",
    )
    ingest(corpus, profile="POLICY", collection="ver_col", persist_dir=tmp_persist_dir)
    # Overwrite with updated rule to mint a new doc_version cleanly.
    doc.write_text(
        "## Section 1: Bonus Policy\n\n1.1 CURRENT_BONUS_100 requires manager review.\n",
        encoding="utf-8",
    )
    ingest(corpus, profile="POLICY", collection="ver_col", persist_dir=tmp_persist_dir)

    seen_preds: list[list[tuple[str, str]]] = []

    def _score_pairs(pairs: list[tuple[str, str]]) -> list[float]:
        seen_preds.append(pairs)
        return [3.0 if "CURRENT_BONUS" in t else 99.0 for _, t in pairs]

    with _clean_model_cache():
        monkeypatch.setattr(
            ce_mod,
            "_instantiate_cross_encoder",
            lambda _m: _FakeModel(_score_pairs),
        )
        for mode in ("default", "fts5_hybrid"):
            hits = retrieve(
                "bonus review",
                collection="ver_col",
                persist_dir=tmp_persist_dir,
                searcher=mode,
                top_k=2,
                rerank=True,
            )
            assert hits
            assert all("LEGACY_BONUS_500" not in h.text for h in hits)
            assert "CURRENT_BONUS_100" in hits[0].text

        # Pre-rerank threshold eliminating all candidates skips reranker entirely.
        before_calls = len(seen_preds)
        no_hits = retrieve(
            "unrelated quantum toaster",
            collection="ver_col",
            persist_dir=tmp_persist_dir,
            threshold=0.99,
            rerank=True,
        )
        assert no_hits == []
        assert len(seen_preds) == before_calls

        # Negative reranker logits on pre-threshold survivors are NOT dropped post-rerank.
        negative_rerank = CrossEncoderReranker()
        with _clean_model_cache():
            monkeypatch.setattr(
                ce_mod,
                "_instantiate_cross_encoder",
                lambda _m: _FakeModel(lambda pairs: [-6.0 for _ in pairs]),
            )
            _ = negative_rerank
            kept = retrieve(
                "CURRENT_BONUS_100 manager review",
                collection="ver_col",
                persist_dir=tmp_persist_dir,
                threshold=0.0,
                rerank=True,
            )
            assert len(kept) >= 1
            assert kept[0].score < 0.01

        # Valid-env top_k=0 short-circuits without calling _load_cross_encoder.
        ce_mod._MODEL_CACHE.clear()
        calls_on_zero: list[str] = []
        monkeypatch.setattr(
            ce_mod,
            "_load_cross_encoder",
            lambda name: calls_on_zero.append(name),
        )
        assert (
            retrieve(
                "bonus review",
                collection="ver_col",
                persist_dir=tmp_persist_dir,
                top_k=0,
                rerank=True,
            )
            == []
        )
        assert calls_on_zero == []


def test_expansion_aware_pool_custom_protocol_and_baseline_identity(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    _seed_multidoc_policy(tmp_path, tmp_persist_dir, "pool_col")
    recorded_fetch_depths: list[int] = []

    with _clean_registry(SEARCHERS), _clean_registry(RERANKERS):
        base_searcher_cls = SEARCHERS.resolve("default")

        @register_searcher("spy_dense")
        class SpyDenseSearcher:
            name = "spy_dense"

            def search(
                self,
                question: str,
                *,
                top_k: int,
                collection: str,
                persist_dir: str,
                embed_model: str,
                where: dict[str, object] | None = None,
            ) -> list[RetrievedChunk]:
                recorded_fetch_depths.append(top_k)
                return base_searcher_cls().search(
                    question,
                    top_k=top_k,
                    collection=collection,
                    persist_dir=persist_dir,
                    embed_model=embed_model,
                    where=where,
                )

        # Custom minimal Reranker Protocol without validate_available() hook (FR-003).
        @register_reranker("proto_only")
        class ProtoOnlyReranker:
            name = "proto_only"

            def rerank(
                self,
                query: str,
                chunks: list[RetrievedChunk],
                *,
                top_k: int,
            ) -> list[RetrievedChunk]:
                _ = query
                return chunks[:top_k]

        retrieve(
            "annual leave",
            collection="pool_col",
            persist_dir=tmp_persist_dir,
            searcher="spy_dense",
            reranker="proto_only",
            top_k=5,
            expand_parent=True,
            rerank=True,
            rerank_top_n=20,
        )
        retrieve(
            "annual leave",
            collection="pool_col",
            persist_dir=tmp_persist_dir,
            searcher="spy_dense",
            reranker="proto_only",
            top_k=10,
            expand_parent=True,
            rerank=True,
            rerank_top_n=20,
        )
        retrieve(
            "annual leave",
            collection="pool_col",
            persist_dir=tmp_persist_dir,
            searcher="spy_dense",
            reranker="proto_only",
            top_k=10,
            expand_parent=False,
            rerank=True,
            rerank_top_n=20,
        )
        retrieve(
            "annual leave",
            collection="pool_col",
            persist_dir=tmp_persist_dir,
            searcher="spy_dense",
            reranker="proto_only",
            top_k=25,
            expand_parent=False,
            rerank=True,
            rerank_top_n=20,
        )

    assert recorded_fetch_depths == [20, 30, 20, 25]

    # rerank=False must produce bit-identical results and never invoke any reranker.
    for mode in ("default", "fts5_hybrid"):
        base_out = retrieve(
            "annual leave",
            collection="pool_col",
            persist_dir=tmp_persist_dir,
            searcher=mode,
        )
        opt_out = retrieve(
            "annual leave",
            collection="pool_col",
            persist_dir=tmp_persist_dir,
            searcher=mode,
            rerank=False,
            reranker="nonexistent_ignored_when_disabled",
        )
        assert [(c.id, c.score) for c in opt_out] == [(c.id, c.score) for c in base_out]


# ---------------------------------------------------------------------------
# T015: Fail-Fast Preflight Validation & Missing Dependency Tests (US2)
# ---------------------------------------------------------------------------


def test_preflight_missing_extra_registry_and_top_n_errors(
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Missing [rerank] fails before collection/manifest checks and even when top_k <= 0.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(MissingExtraError, match=r"docpipe-maestro\[rerank\]"):
        retrieve(
            "anything",
            collection="nonexistent_collection",
            persist_dir=tmp_persist_dir,
            top_k=0,
            rerank=True,
        )

    # 2. Direct non-empty CrossEncoderReranker.rerank() also raises MissingExtraError via find_spec.
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    orig_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, package=None: (
            None if name == "sentence_transformers" else orig_find_spec(name, package)
        ),
    )
    with _clean_model_cache(), pytest.raises(MissingExtraError, match=r"docpipe-maestro\[rerank\]"):
        CrossEncoderReranker().rerank("q", [_chunk("c0", "candidate text")], top_k=3)

    # 3. Unregistered reranker strategy fails upfront before store/manifest access.
    with pytest.raises(RegistryError, match="ghost_reranker"):
        retrieve(
            "anything",
            collection="nonexistent_collection",
            persist_dir=tmp_persist_dir,
            rerank=True,
            reranker="ghost_reranker",
        )

    # 4. Invalid rerank_top_n (<= 0, bool, non-int) fails upfront even when rerank=False or top_k=0.
    for bad_top_n in (0, -5, True, False, "20", 1.5):
        with pytest.raises(ValueError, match="rerank_top_n must be a positive integer >= 1"):
            retrieve(
                "anything",
                collection="nonexistent_collection",
                persist_dir=tmp_persist_dir,
                top_k=0,
                rerank=False,
                rerank_top_n=bad_top_n,  # type: ignore[arg-type]
            )

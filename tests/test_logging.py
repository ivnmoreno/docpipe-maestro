"""Unit, concurrency, lifecycle, and privacy-hygiene tests for Stage 8 logging."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from docpipe_maestro import (
    answer_detailed,
    build_chat_messages,
    ingest,
    reindex,
    remove,
    retrieve,
    status,
    sync,
)
from docpipe_maestro.eval import EvalFixture, evaluate
from docpipe_maestro.log import (
    LOGGER_NAME,
    RESERVED_ENVELOPE_KEYS,
    JsonFormatter,
    TextFormatter,
    correlation_id,
    get_correlation_id,
    get_logger,
    stage_event,
)
from docpipe_maestro.query.stages import Reranker
from docpipe_maestro.types import RetrievedChunk


@contextmanager
def _capture_json_records(
    level: int = logging.INFO,
) -> Iterator[tuple[io.StringIO, list[dict[str, Any]]]]:
    """Attach a temporary JsonFormatter handler onto ``docpipe_maestro`` safely."""
    pkg_logger = get_logger()
    prev_level = pkg_logger.level
    buf = io.StringIO()
    records: list[dict[str, Any]] = []
    handler = logging.StreamHandler(buf)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    pkg_logger.setLevel(level)
    pkg_logger.addHandler(handler)
    try:
        yield buf, records
    finally:
        pkg_logger.removeHandler(handler)
        handler.close()
        pkg_logger.setLevel(prev_level)
        raw = buf.getvalue().strip()
        if raw:
            records.extend(json.loads(line) for line in raw.splitlines())


def test_silent_default_library_logging_and_root_isolation(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Library defaults must attach NullHandler only, untouched root, zero stdio noise."""
    pkg_logger = get_logger()
    assert pkg_logger.name == LOGGER_NAME
    assert any(isinstance(h, logging.NullHandler) for h in pkg_logger.handlers)

    corpus = tmp_path / "docs"
    corpus.mkdir()
    doc = corpus / "policy.md"
    doc.write_text("# Policy\n\nAll hires get 20 days leave.\n", encoding="utf-8")

    root_logger = logging.getLogger()
    root_handlers_before = list(root_logger.handlers)
    root_level_before = root_logger.level

    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        ingest(corpus, collection="silent_col", persist_dir=tmp_persist_dir)
        hits = retrieve("leave", collection="silent_col", persist_dir=tmp_persist_dir)
        assert hits

    assert stdout_buf.getvalue() == ""
    assert stderr_buf.getvalue() == ""
    assert list(root_logger.handlers) == root_handlers_before
    assert root_logger.level == root_level_before
    assert [type(h) for h in pkg_logger.handlers] == [logging.NullHandler]

    # Subprocess sanity check: unconfigured Python process leaves root untouched cleanly.
    code = (
        "import logging, docpipe_maestro.log as dlog; "
        "root = logging.getLogger(); "
        "assert root.handlers == []; "
        "pkg = dlog.get_logger(); "
        "assert [type(h) for h in pkg.handlers] == [logging.NullHandler]; "
        "assert pkg.level == logging.NOTSET"
    )
    proc = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_json_and_text_formatters_envelope_collision_paths_and_no_tracebacks() -> None:
    """Formatters preserve envelope keys, coerce PathLike, and omit exc_info tracebacks."""
    assert get_correlation_id() is None
    json_fmt = JsonFormatter()
    text_fmt = TextFormatter()

    try:
        raise RuntimeError("SECRET_CREDENTIAL=sk-raw-leak-999")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="docpipe_maestro.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="stage.end",
        args=(),
        exc_info=exc_info,
    )
    record.docpipe_fields = {
        "ts": "evil-override",
        "level": "DEBUG",
        "logger": "evil",
        "msg": "evil",
        "correlation_id": "evil-cid",
        "path": Path("docs/a.md"),
        "tags": ("a", "b"),
        "status": "error",
        "error_type": "RuntimeError",
        "duration_ms": 1.25,
    }

    rendered_json = json_fmt.format(record)
    assert "\n" not in rendered_json
    parsed = json.loads(rendered_json)
    assert set(parsed.keys()) == RESERVED_ENVELOPE_KEYS | {"fields"}
    assert parsed["level"] == "ERROR"
    assert parsed["logger"] == "docpipe_maestro.test"
    assert parsed["msg"] == "stage.end"
    assert parsed["correlation_id"] is None
    assert parsed["fields"]["ts"] == "evil-override"
    assert parsed["fields"]["path"] == os.fspath(Path("docs/a.md"))
    assert parsed["fields"]["tags"] == ["a", "b"]
    assert "SECRET_CREDENTIAL" not in rendered_json
    assert "Traceback" not in rendered_json

    rendered_text = text_fmt.format(record)
    assert "\n" not in rendered_text
    assert "ERROR [-] docpipe_maestro.test: stage.end" in rendered_text
    assert "error_type=RuntimeError" in rendered_text
    assert "SECRET_CREDENTIAL" not in rendered_text
    assert "Traceback" not in rendered_text


def test_correlation_id_validation_nesting_and_concurrency_isolation() -> None:
    """ContextVar correlation_id inherits outer IDs, resets on error, and isolates workers."""
    with pytest.raises(ValueError, match="empty"), correlation_id("   "):
        pass

    assert get_correlation_id() is None
    with correlation_id() as outer:
        assert uuid.UUID(outer)
        with correlation_id() as inner:
            assert inner == outer
        with correlation_id("override-id") as custom:
            assert custom == "override-id"
            assert get_correlation_id() == "override-id"
        assert get_correlation_id() == outer
    assert get_correlation_id() is None

    with pytest.raises(RuntimeError), correlation_id() as err_cid:
        assert get_correlation_id() == err_cid
        raise RuntimeError("boom")
    assert get_correlation_id() is None

    # Async task isolation across interleaved yields.
    async def _worker(tag: str) -> tuple[str, str, str]:
        with correlation_id(f"async-{tag}") as cid:
            await asyncio.sleep(0.01)
            mid = get_correlation_id()
            await asyncio.sleep(0.01)
            end = get_correlation_id()
            return cid, mid or "", end or ""

    async def _run_all() -> list[tuple[str, str, str]]:
        return await asyncio.gather(*[_worker(str(i)) for i in range(6)])

    async_results = asyncio.run(_run_all())
    for idx, (start, mid, end) in enumerate(async_results):
        expected = f"async-{idx}"
        assert (start, mid, end) == (expected, expected, expected)

    # ThreadPool isolation.
    barrier = threading.Barrier(4)

    def _thread_worker(idx: int) -> tuple[str, str]:
        with correlation_id() as cid:
            barrier.wait(timeout=2.0)
            time.sleep(0.01)
            return cid, get_correlation_id() or ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        thread_results = list(pool.map(_thread_worker, range(4)))
    assert len({cid for cid, _ in thread_results}) == 4
    assert all(start == end for start, end in thread_results)
    assert get_correlation_id() is None


def test_phase1_info_batch_vs_debug_per_doc_and_lifecycle_stages(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Phase 1 emits batch INFO summaries, DEBUG per-doc stages, and lifecycle store events."""
    corpus = tmp_path / "p1_docs"
    corpus.mkdir()
    (corpus / "a.md").write_text("# Sec 1\n\nAlpha rule body.\n", encoding="utf-8")
    (corpus / "b.md").write_text("# Sec 1\n\nBeta rule body.\n", encoding="utf-8")

    # 1. INFO batch ingest emits exactly one summary per Phase 1 stage, all sharing 1 UUID.
    with _capture_json_records(logging.INFO) as (_, info_events):
        ingest(corpus, profile="POLICY", collection="p1_col", persist_dir=tmp_persist_dir)

    info_stages = [r["fields"]["stage"] for r in info_events]
    assert info_stages == ["intake", "clean", "enrich", "chunk", "embed", "store"]
    assert all(r["level"] == "INFO" and r["msg"] == "stage.end" for r in info_events)
    assert all(r["fields"]["status"] == "ok" for r in info_events)
    assert all(isinstance(r["fields"]["duration_ms"], float) for r in info_events)
    cids = {r["correlation_id"] for r in info_events}
    assert len(cids) == 1
    assert uuid.UUID(next(iter(cids)))
    assert info_events[0]["fields"]["docs"] == 2
    assert info_events[-1]["fields"]["ingested"] == 2

    # 2. All-skipped incremental run still emits batch INFO summaries (docs=0, skipped=2).
    with _capture_json_records(logging.INFO) as (_, noop_events):
        ingest(corpus, profile="POLICY", collection="p1_col", persist_dir=tmp_persist_dir)
    assert [r["fields"]["stage"] for r in noop_events] == [
        "intake",
        "clean",
        "enrich",
        "chunk",
        "embed",
        "store",
    ]
    assert all(r["fields"]["docs"] == 0 for r in noop_events[:-1])
    assert noop_events[-1]["fields"]["skipped"] == 2
    assert noop_events[-1]["fields"]["ingested"] == 0

    # 3. Sync at DEBUG emits per-doc stages + INFO summaries sharing 1 correlation_id.
    (corpus / "b.md").write_text("# Sec 1\n\nBeta rule updated.\n", encoding="utf-8")
    (corpus / "c.md").write_text("# Sec 1\n\nGamma new file.\n", encoding="utf-8")
    (corpus / "a.md").unlink()

    with _capture_json_records(logging.DEBUG) as (_, debug_events):
        sync(corpus, profile="POLICY", collection="p1_col", persist_dir=tmp_persist_dir)

    debug_stage_recs = [r for r in debug_events if r["level"] == "DEBUG"]
    info_stage_recs = [r for r in debug_events if r["level"] == "INFO"]
    assert len({r["correlation_id"] for r in debug_events}) == 1
    assert [r["fields"]["stage"] for r in info_stage_recs] == [
        "intake",
        "clean",
        "enrich",
        "chunk",
        "embed",
        "store",
    ]
    assert info_stage_recs[-1]["fields"]["added"] == 1
    assert info_stage_recs[-1]["fields"]["updated"] == 1
    assert info_stage_recs[-1]["fields"]["skipped"] == 0
    assert info_stage_recs[-1]["fields"]["removed"] == 1
    per_doc_stages = {r["fields"]["stage"] for r in debug_stage_recs}
    assert {"intake", "clean", "enrich", "chunk"}.issubset(per_doc_stages)
    assert any(r["fields"].get("source") == "c.md" for r in debug_stage_recs)

    # 4. status, reindex, remove each emit correlated INFO store / embed stage events.
    with _capture_json_records(logging.INFO) as (_, st_events):
        status(collection="p1_col", persist_dir=tmp_persist_dir)
    assert [r["fields"]["operation"] for r in st_events] == ["status"]

    with _capture_json_records(logging.INFO) as (_, rx_events):
        reindex(
            embed_model="openai/text-embedding-3-small",
            collection="p1_col",
            persist_dir=tmp_persist_dir,
        )
    assert [r["fields"]["stage"] for r in rx_events] == ["embed", "store"]
    assert len({r["correlation_id"] for r in rx_events}) == 1

    with _capture_json_records(logging.INFO) as (_, rm_events):
        assert remove("c.md", collection="p1_col", persist_dir=tmp_persist_dir) is True
    assert rm_events[0]["fields"]["operation"] == "remove"
    assert rm_events[0]["fields"]["removed"] is True


def test_phase2_stages_rerank_eval_short_circuit_and_answer(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Phase 2 emits embed, search, optional rerank, answer, and shared eval correlation."""
    corpus = tmp_path / "p2_docs"
    corpus.mkdir()
    (corpus / "handbook.md").write_text(
        "# Travel Rules\n\n## Section 1\n\n1.1 Economy rail is covered under 200 EUR.\n",
        encoding="utf-8",
    )
    ingest(corpus, profile="POLICY", collection="p2_col", persist_dir=tmp_persist_dir)

    class _FakeReranker(Reranker):
        def rerank(
            self,
            query: str,
            chunks: list[RetrievedChunk],
            *,
            top_k: int,
        ) -> list[RetrievedChunk]:
            _ = query
            return chunks[:top_k]

    with (
        _capture_json_records(logging.INFO) as (_, ret_events),
        patch(
            "docpipe_maestro.query.retriever.validate_rerank_options", return_value=_FakeReranker
        ),
    ):
        secs = retrieve(
            "rail covered",
            collection="p2_col",
            persist_dir=tmp_persist_dir,
            searcher="fts5_hybrid",
            rerank=True,
        )
    assert secs
    assert [r["fields"]["stage"] for r in ret_events] == ["embed", "search", "rerank"]
    assert len({r["correlation_id"] for r in ret_events}) == 1
    assert ret_events[0]["fields"]["operation"] == "query"
    assert ret_events[1]["fields"]["searcher"] == "fts5_hybrid"

    # Impossible manifest filter short-circuits cleanly before embed & search.
    with _capture_json_records(logging.INFO) as (_, sc_events):
        empty = retrieve(
            "rail covered",
            collection="p2_col",
            persist_dir=tmp_persist_dir,
            where={"ingested_after": "2099-01-01"},
        )
    assert empty == []
    assert sc_events == []

    # Answer stage emits when has_context=True and omits completion when has_context=False.
    msgs = build_chat_messages("What is covered?", secs)
    with _capture_json_records(logging.INFO) as (_, ans_events):
        answer_detailed(msgs, model="ollama/llama3.2", has_context=True)
    assert [r["fields"]["stage"] for r in ans_events] == ["answer"]
    assert ans_events[0]["fields"]["model"] == "ollama/llama3.2"

    with _capture_json_records(logging.INFO) as (_, empty_ans_events):
        res_empty = answer_detailed(msgs, model="ollama/llama3.2", has_context=False)
    assert res_empty.text == "Not found in the provided context."
    assert empty_ans_events == []

    # evaluate() correlates all inner retrieve() calls under one outer correlation_id.
    fixture: EvalFixture = {
        "collection": "p2_col",
        "queries": [
            {"question": "rail covered", "relevant_ids": [secs[0].id]},
            {"question": "economy rail 200 EUR", "relevant_ids": [secs[0].id]},
        ],
    }
    with _capture_json_records(logging.INFO) as (_, eval_events):
        report = evaluate(fixture, persist_dir=tmp_persist_dir)
    assert report["aggregate"]["mrr"] == pytest.approx(1.0)
    assert len(eval_events) == 4  # 2 queries * (embed + search)
    assert len({r["correlation_id"] for r in eval_events}) == 1


def test_stage_failure_hygiene_disabled_short_circuit_and_secret_exclusion(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures log error_type only, inactive logger short-circuits, DEBUG leaks zero secrets."""
    stage_logger = get_logger("docpipe_maestro.test_failure")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    prev_level = stage_logger.level
    stage_logger.setLevel(logging.CRITICAL)
    stage_logger.addHandler(handler)
    try:
        # Inactive level short-circuits cleanly without emitting LogRecord.
        with stage_event(stage_logger, "search", log_level=logging.INFO):
            pass
        assert buf.getvalue() == ""

        # Active ERROR emits stage.end with error_type only — zero secret message strings.
        stage_logger.setLevel(logging.INFO)
        with (
            pytest.raises(RuntimeError),
            correlation_id("fail-cid"),
            stage_event(stage_logger, "answer", model="openai/gpt-4o-mini"),
        ):
            raise RuntimeError("Authorization Bearer sk-live-secret-abc987")
    finally:
        stage_logger.removeHandler(handler)
        handler.close()
        stage_logger.setLevel(prev_level)

    err_line = buf.getvalue().strip()
    err_rec = json.loads(err_line)
    assert err_rec["level"] == "ERROR"
    assert err_rec["correlation_id"] == "fail-cid"
    assert err_rec["fields"]["stage"] == "answer"
    assert err_rec["fields"]["status"] == "error"
    assert err_rec["fields"]["error_type"] == "RuntimeError"
    assert "sk-live-secret-abc987" not in err_line
    assert "Authorization" not in err_line

    # Full pipeline DEBUG log scan excludes raw content, questions, prompts, answers, credentials.
    corpus = tmp_path / "secret_docs"
    corpus.mkdir()
    doc_secret = "CONFIDENTIAL_DOC_BODY_TOKEN_5544"
    (corpus / "rules.md").write_text(
        f"# Internal Policy\n\nRule: {doc_secret} except emergency waiver.\n",
        encoding="utf-8",
    )
    query_secret = "UNIQUE_USER_QUESTION_TOKEN_6677"
    api_secret = "sk-provider-secret-998877"
    monkeypatch.setenv("OPENAI_API_KEY", api_secret)

    with _capture_json_records(logging.DEBUG) as (raw_buf, _):
        ingest(corpus, profile="POLICY", collection="sec_col", persist_dir=tmp_persist_dir)
        secs = retrieve(
            f"{query_secret} {doc_secret}",
            collection="sec_col",
            persist_dir=tmp_persist_dir,
            searcher="fts5_hybrid",
        )
        msgs = build_chat_messages(query_secret, secs)
        ans = answer_detailed(msgs, model="ollama/llama3.2", has_context=bool(secs))

    dumped = raw_buf.getvalue()
    assert dumped.strip()
    for forbidden in (doc_secret, query_secret, api_secret, ans.text):
        assert forbidden not in dumped

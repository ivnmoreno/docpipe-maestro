"""Release Gate #2 (@pytest.mark.pii): Offline synthetic PII safety invariants."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from docpipe_maestro import (
    PiiBlockedError,
    PiiPolicy,
    answer,
    answer_detailed,
    build_chat_messages,
    ingest,
    reindex,
    retrieve,
    sync,
)
from docpipe_maestro import (
    register_pii_recognizer as root_register_pii_recognizer,
)
from docpipe_maestro._pii import (
    PII_RECOGNIZERS,
    apply_pii_policy_to_text,
    register_pii_recognizer,
)
from docpipe_maestro.embedder import enforce_local_only, is_local_target
from docpipe_maestro.eval import evaluate
from docpipe_maestro.manifest import audit_log_path, compute_file_hash
from docpipe_maestro.store import LexicalIndex, VectorStore
from docpipe_maestro.types import DocpipeError, MissingExtraError, PiiDetection, PiiRecognizer

pytestmark = pytest.mark.pii

# Strictly synthetic non-production test values.
_SYNTH_EMAIL = "alex.rivera@example.test"
_SYNTH_IBAN_DE = "DE89370400440532013000"
_SYNTH_IBAN_ES = "ES9121000418450200051332"
_SYNTH_IBAN_INVALID = "ES0021000418450200051332"
_SYNTH_CARD_VALID = "4111-1111-1111-1111"
_SYNTH_CARD_INVALID = "4111-1111-1111-1112"
_SYNTH_SSN_VALID = "123-45-6789"
_SYNTH_SSN_INVALID_666 = "666-45-6789"
_SYNTH_SSN_INVALID_900 = "905-12-3456"
_SYNTH_IPV4 = "203.0.113.42"
_SYNTH_IPV6 = "2001:db8::42"
_SYNTH_PHONE_ES = "+34 600 112 233"
_SYNTH_PHONE_US = "(415) 555-0199"
_SYNTH_DNI_VALID = "12345678Z"
_SYNTH_DNI_INVALID = "12345678A"


@contextmanager
def _restore_pii_recognizers() -> Iterator[None]:
    """Isolate custom PiiRecognizer registrations cleanly per test."""
    saved_entries = dict(PII_RECOGNIZERS._entries)
    saved_lazy = dict(PII_RECOGNIZERS._lazy_builtins)
    saved_mat = set(PII_RECOGNIZERS._materializing)
    try:
        yield
    finally:
        PII_RECOGNIZERS._entries.clear()
        PII_RECOGNIZERS._entries.update(saved_entries)
        PII_RECOGNIZERS._lazy_builtins.clear()
        PII_RECOGNIZERS._lazy_builtins.update(saved_lazy)
        PII_RECOGNIZERS._materializing.clear()
        PII_RECOGNIZERS._materializing.update(saved_mat)


def test_builtin_recognizers_checksums_and_custom_registry() -> None:
    """All 7 deterministic recognizers detect valid synthetics and reject checksum decoys."""
    sample = (
        f"Contact {_SYNTH_EMAIL} or {_SYNTH_PHONE_ES} / {_SYNTH_PHONE_US}. "
        f"Accounts: {_SYNTH_IBAN_DE}, {_SYNTH_IBAN_ES}, fake {_SYNTH_IBAN_INVALID}. "
        f"Card {_SYNTH_CARD_VALID} (bad {_SYNTH_CARD_INVALID} and 0000-0000-0000-0000). "
        f"SSN {_SYNTH_SSN_VALID} (bad {_SYNTH_SSN_INVALID_666}, "
        f"{_SYNTH_SSN_INVALID_900}, 000-12-3456). "
        f"Hosts {_SYNTH_IPV4}, {_SYNTH_IPV6}, release v1.2.3.4, date 2026-11-15, clause 1.2.3. "
        f"Spanish DNI {_SYNTH_DNI_VALID} (bad {_SYNTH_DNI_INVALID})."
    )
    policy: PiiPolicy = {
        "types": {
            "EMAIL_ADDRESS": "redact",
            "IBAN_CODE": "redact",
            "CREDIT_CARD": "redact",
            "US_SSN": "redact",
            "IP_ADDRESS": "redact",
            "PHONE_NUMBER": "redact",
            "ES_DNI": "redact",
        },
        "languages": ["en", "es"],
        "min_confidence": 0.6,
    }
    redacted, counts, _ = apply_pii_policy_to_text(sample, policy)

    for secret in (
        _SYNTH_EMAIL,
        _SYNTH_IBAN_DE,
        _SYNTH_IBAN_ES,
        _SYNTH_CARD_VALID,
        _SYNTH_SSN_VALID,
        _SYNTH_IPV4,
        _SYNTH_IPV6,
        _SYNTH_PHONE_ES,
        _SYNTH_PHONE_US,
        _SYNTH_DNI_VALID,
    ):
        assert secret not in redacted

    # Checksum decoys, dates, version tags, and section numbers remain untouched.
    for decoy in (
        _SYNTH_IBAN_INVALID,
        _SYNTH_CARD_INVALID,
        "0000-0000-0000-0000",
        _SYNTH_SSN_INVALID_666,
        _SYNTH_SSN_INVALID_900,
        "000-12-3456",
        "v1.2.3.4",
        "2026-11-15",
        "clause 1.2.3",
        _SYNTH_DNI_INVALID,
    ):
        assert decoy in redacted

    assert counts == {
        "CREDIT_CARD": 1,
        "EMAIL_ADDRESS": 1,
        "ES_DNI": 1,
        "IBAN_CODE": 2,
        "IP_ADDRESS": 2,
        "PHONE_NUMBER": 2,
        "US_SSN": 1,
    }

    with _restore_pii_recognizers():
        assert root_register_pii_recognizer is register_pii_recognizer

        @root_register_pii_recognizer("employee_badge")
        class _BadgeRecognizer:
            name: str = "custom:employee_badge"
            entity_type: str = "EMPLOYEE_BADGE"
            supported_languages: tuple[str, ...] = ("*",)

            def detect(self, text: str, *, languages: tuple[str, ...]) -> list[PiiDetection]:
                _ = languages
                return [
                    {
                        "entity_type": self.entity_type,
                        "start": m.start(),
                        "end": m.end(),
                        "score": 0.99,
                        "recognizer": self.name,
                    }
                    for m in re.finditer(r"\bEMP-\d{5}\b", text)
                ]

        assert isinstance(_BadgeRecognizer(), PiiRecognizer)
        badge_out, badge_counts, _ = apply_pii_policy_to_text(
            "Badge EMP-90210 granted access.",
            {"types": {"EMPLOYEE_BADGE": "redact"}},
        )
        assert badge_out == "Badge [EMPLOYEE_BADGE] granted access."
        assert badge_counts == {"EMPLOYEE_BADGE": 1}


def test_prechunking_title_and_body_tokenization_with_salt_and_fallback(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section titles, bodies, and child headers tokenize deterministically pre-chunking."""
    _ = mock_litellm_offline
    corpus = tmp_path / "pii_corpus"
    corpus.mkdir()
    doc1 = corpus / "hr_notice.md"
    doc2 = corpus / "finance_memo.md"
    doc1.write_text(
        f"# 1. Employee Contact {_SYNTH_EMAIL} ({_SYNTH_DNI_VALID})\n\n"
        f"Reach {_SYNTH_EMAIL} via {_SYNTH_PHONE_ES} or host {_SYNTH_IPV4}. "
        "Notice: 20 days of leave apply except for probationary staff.\n",
        encoding="utf-8",
    )
    doc2.write_text(
        f"# 2. Reimbursement {_SYNTH_IBAN_ES}\n\n"
        f"Secondary confirmation for {_SYNTH_EMAIL} and DNI {_SYNTH_DNI_VALID} "
        f"uses IBAN {_SYNTH_IBAN_ES}.\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("DOCPIPE_PII_TEST_SALT", "unit-test-hmac-secret-key")
    policy: PiiPolicy = {
        "types": {
            "EMAIL_ADDRESS": "tokenize",
            "ES_DNI": "tokenize",
            "IBAN_CODE": "redact",
            "PHONE_NUMBER": "redact",
            "IP_ADDRESS": "redact",
        },
        "languages": ["en", "es"],
        "token_salt_env": "DOCPIPE_PII_TEST_SALT",
    }

    ingest(
        corpus,
        profile="POLICY",
        collection="pii_tok_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/embed",
        pii_policy=policy,
    )

    store = VectorStore(tmp_persist_dir, "pii_tok_col")
    lexical = LexicalIndex(tmp_persist_dir, "pii_tok_col")
    all_records = store.get_all_children() + store.get_all_parents()
    assert all_records
    for rec in all_records:
        for secret in (
            _SYNTH_EMAIL,
            _SYNTH_DNI_VALID,
            _SYNTH_IBAN_ES,
            _SYNTH_PHONE_ES,
            _SYNTH_IPV4,
        ):
            assert secret not in rec.text
            assert secret not in rec.metadata["section"]

    email_tokens: set[str] = set()
    dni_tokens: set[str] = set()
    for rec in all_records:
        email_tokens.update(re.findall(r"\[EMAIL_ADDRESS_[0-9a-f]{8}\]", rec.text))
        dni_tokens.update(re.findall(r"\[ES_DNI_[0-9a-f]{8}\]", rec.text))
    # Identical value hashes to the exact same token across headings, bodies, and docs.
    assert len(email_tokens) == 1
    assert len(dni_tokens) == 1

    retrieved = retrieve(
        "leave probationary contact",
        collection="pii_tok_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/embed",
    )
    assert retrieved
    for hit in retrieved:
        assert _SYNTH_EMAIL not in hit.text
        assert "[EMAIL_ADDRESS_" in hit.text
    assert lexical.exists()

    # Fallback process-random salt emits warning when no explicit/env salt is provided.
    import docpipe_maestro._pii as pii_mod

    monkeypatch.setattr(pii_mod, "_PROCESS_FALLBACK_SALT", None)
    monkeypatch.setattr(pii_mod, "_FALLBACK_SALT_WARNED", False)
    with caplog.at_level(logging.WARNING, logger="docpipe_maestro._pii"):
        t1, _, _ = apply_pii_policy_to_text(
            f"Contact {_SYNTH_EMAIL}", {"types": {"EMAIL_ADDRESS": "tokenize"}}
        )
        t2, _, _ = apply_pii_policy_to_text(
            f"Later offset email: {_SYNTH_EMAIL}", {"types": {"EMAIL_ADDRESS": "tokenize"}}
        )
    assert "random salt" in caplog.text.lower()
    tok1 = re.findall(r"\[EMAIL_ADDRESS_[0-9a-f]{8}\]", t1)
    tok2 = re.findall(r"\[EMAIL_ADDRESS_[0-9a-f]{8}\]", t2)
    assert len(tok1) == 1 and tok1 == tok2


def test_block_mode_aborts_batch_transactionally_without_leaking_raw_pii(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Block-mode matches halt multi-doc ingest & sync cleanly before store or manifest commit."""
    _ = mock_litellm_offline
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    (baseline_dir / "clean.md").write_text("# Clean\n\nSafe baseline document.\n", encoding="utf-8")

    ingest(
        baseline_dir,
        collection="pii_block_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/embed",
    )
    store = VectorStore(tmp_persist_dir, "pii_block_col")
    before_ids = sorted(c.id for c in store.get_all_children() + store.get_all_parents())

    bad_dir = tmp_path / "bad_batch"
    bad_dir.mkdir()
    (bad_dir / "a_redacted.md").write_text(
        f"# Redacted\n\nContact {_SYNTH_EMAIL}.\n", encoding="utf-8"
    )
    (bad_dir / "b_blocked.md").write_text(
        f"# Violation\n\nSSN {_SYNTH_SSN_VALID} and card {_SYNTH_CARD_VALID}.\n",
        encoding="utf-8",
    )

    block_policy: PiiPolicy = {
        "types": {
            "EMAIL_ADDRESS": "redact",
            "US_SSN": "block",
            "CREDIT_CARD": "block",
        }
    }

    with pytest.raises(PiiBlockedError) as exc_info:
        ingest(
            bad_dir,
            collection="pii_block_col",
            persist_dir=tmp_persist_dir,
            embed_model="mock/embed",
            pii_policy=block_policy,
        )

    assert isinstance(exc_info.value, DocpipeError)
    err_msg = str(exc_info.value)
    assert "b_blocked.md" in err_msg
    assert "CREDIT_CARD" in err_msg and "US_SSN" in err_msg
    assert _SYNTH_SSN_VALID not in err_msg
    assert _SYNTH_CARD_VALID not in err_msg
    assert "123-45" not in err_msg
    assert "4111" not in err_msg

    # First doc in aborted batch and bad doc MUST NOT leak into store.
    store_after = VectorStore(tmp_persist_dir, "pii_block_col")
    after_ids = sorted(c.id for c in store_after.get_all_children() + store_after.get_all_parents())
    assert after_ids == before_ids

    # Same guarantee under sync().
    with pytest.raises(PiiBlockedError) as sync_exc:
        sync(
            bad_dir,
            collection="pii_block_col",
            persist_dir=tmp_persist_dir,
            embed_model="mock/embed",
            pii_policy=block_policy,
        )
    assert _SYNTH_SSN_VALID not in str(sync_exc.value)
    assert (
        sorted(
            c.id
            for c in VectorStore(tmp_persist_dir, "pii_block_col").get_all_children()
            + VectorStore(tmp_persist_dir, "pii_block_col").get_all_parents()
        )
        == before_ids
    )


def test_local_only_permits_loopback_and_blocks_remote_before_network(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """local_only rejects remote models and non-loopback endpoints prior to transport I/O."""
    assert is_local_target("ollama/llama3.2") is True
    assert is_local_target("ollama_chat/llama3.2") is True
    assert is_local_target("local/embed") is True
    assert is_local_target("openai/local-vllm", api_base="http://127.0.0.1:8000/v1") is True
    assert is_local_target("openai/local-vllm", api_base="http://localhost:8000/v1") is True
    assert is_local_target("openai/local-vllm", api_base="http://[::1]:8000/v1") is True

    assert is_local_target("openai/gpt-4o-mini") is False
    assert is_local_target("groq/openai/gpt-oss-120b") is False
    assert is_local_target("ollama/llama3.2", api_base="https://remote.example.test/v1") is False

    monkeypatch.setenv("OLLAMA_API_BASE", "https://remote-ollama.example.test")
    assert is_local_target("ollama/llama3.2") is False
    monkeypatch.delenv("OLLAMA_API_BASE")

    doc_dir = tmp_path / "local_only_docs"
    doc_dir.mkdir()
    (doc_dir / "note.md").write_text("# Note\n\nSafe local text.\n", encoding="utf-8")

    # Loopback OpenAI-compatible server is allowed by answer_detailed when mocked.
    answer_detailed(
        "Summarize safe text.",
        model="openai/local-vllm",
        api_base="http://127.0.0.1:8000/v1",
        local_only=True,
    )
    assert len(mock_litellm_offline["completion"]) == 1

    # Remote cloud targets and non-loopback endpoints fail BEFORE any network/embedder call.
    for op_call in (
        lambda: ingest(
            doc_dir,
            persist_dir=tmp_persist_dir,
            collection="lo_col",
            embed_model="openai/text-embedding-3-small",
            local_only=True,
        ),
        lambda: sync(
            doc_dir,
            persist_dir=tmp_persist_dir,
            collection="lo_col",
            embed_model="openai/text-embedding-3-small",
            local_only=True,
        ),
        lambda: reindex(
            persist_dir=tmp_persist_dir,
            collection="lo_col",
            embed_model="openai/text-embedding-3-small",
            local_only=True,
        ),
        lambda: retrieve(
            "question",
            persist_dir=tmp_persist_dir,
            collection="lo_col",
            embed_model="openai/text-embedding-3-small",
            local_only=True,
        ),
        lambda: evaluate(
            {"collection": "lo_col", "queries": [{"question": "q", "relevant_ids": ["1"]}]},
            persist_dir=tmp_persist_dir,
            embed_model="openai/text-embedding-3-small",
            local_only=True,
        ),
        lambda: answer(
            f"Check {_SYNTH_SSN_VALID}",
            model="openai/gpt-4o-mini",
            local_only=True,
        ),
        lambda: answer_detailed(
            f"Check {_SYNTH_SSN_VALID}",
            model="openai/local-vllm",
            api_base="https://remote.example.test/v1",
            local_only=True,
        ),
    ):
        with pytest.raises(DocpipeError) as exc_info:
            op_call()
        assert _SYNTH_SSN_VALID not in str(exc_info.value)

    assert mock_litellm_offline["embedding"] == []
    assert len(mock_litellm_offline["completion"]) == 1
    with pytest.raises(DocpipeError, match="local_only"):
        enforce_local_only("groq/llama3-70b", operation="generation")


def test_outbound_egress_guard_for_prompts_chat_messages_and_modes(
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Remote LLM egress honors omitted/redact, block, allow, and unconfigured passthrough."""
    from docpipe_maestro.query.egress import guard_egress

    chat_msgs = [
        {"role": "system", "content": f"Context owner: {_SYNTH_EMAIL}, IBAN {_SYNTH_IBAN_ES}."},
        {"role": "user", "content": f"Verify card for {_SYNTH_PHONE_US}."},
        {"role": "assistant", "content": f"Checking {_SYNTH_IPV4}."},
    ]

    # Unconfigured pii_policy passes through remote call unmodified.
    answer_detailed(chat_msgs, model="openai/gpt-4o-mini")
    sent_unconfigured = mock_litellm_offline["completion"][-1]["messages"]
    assert sent_unconfigured == chat_msgs

    # Default egress ("redact" omitted) applies per-entity redact/tokenize/block without downgrade.
    policy_mixed: PiiPolicy = {
        "types": {
            "EMAIL_ADDRESS": "tokenize",
            "IBAN_CODE": "redact",
            "PHONE_NUMBER": "redact",
            "IP_ADDRESS": "redact",
            "US_SSN": "block",
        },
        "token_salt": "egress-test-salt",
    }
    answer_detailed(chat_msgs, model="openai/gpt-4o-mini", pii_policy=policy_mixed)
    sent_guarded = mock_litellm_offline["completion"][-1]["messages"]
    assert [m["role"] for m in sent_guarded] == ["system", "user", "assistant"]
    assert sent_guarded[0]["content"] != chat_msgs[0]["content"]
    for raw_secret in (_SYNTH_EMAIL, _SYNTH_IBAN_ES, _SYNTH_PHONE_US, _SYNTH_IPV4):
        assert all(raw_secret not in m["content"] for m in sent_guarded)
    assert "[IBAN_CODE]" in sent_guarded[0]["content"]
    assert "[EMAIL_ADDRESS_" in sent_guarded[0]["content"]
    assert "[PHONE_NUMBER]" in sent_guarded[1]["content"]
    assert "[IP_ADDRESS]" in sent_guarded[2]["content"]

    # Per-entity block rule is preserved even when egress defaults or equals "redact".
    with pytest.raises(PiiBlockedError) as blk_exc:
        answer(
            f"Plain string with SSN {_SYNTH_SSN_VALID}.",
            model="groq/llama3-70b",
            pii_policy={**policy_mixed, "egress": "redact"},
        )
    assert "US_SSN" in str(blk_exc.value)
    assert _SYNTH_SSN_VALID not in str(blk_exc.value)

    # egress="block" escalates ALL matched configured entities to PiiBlockedError.
    calls_before_blk = len(mock_litellm_offline["completion"])
    with pytest.raises(PiiBlockedError) as esc_exc:
        guard_egress(
            f"Contact {_SYNTH_EMAIL}",
            model="openai/gpt-4o-mini",
            pii_policy={"types": {"EMAIL_ADDRESS": "redact"}, "egress": "block"},
        )
    assert "EMAIL_ADDRESS" in str(esc_exc.value)
    assert _SYNTH_EMAIL not in str(esc_exc.value)
    assert len(mock_litellm_offline["completion"]) == calls_before_blk

    # egress="allow" skips outbound PII scrubbing without relaxing local_only.
    answer_detailed(
        f"Allow {_SYNTH_EMAIL}",
        model="openai/gpt-4o-mini",
        pii_policy={"types": {"EMAIL_ADDRESS": "block"}, "egress": "allow"},
    )
    assert _SYNTH_EMAIL in mock_litellm_offline["completion"][-1]["messages"][0]["content"]
    with pytest.raises(DocpipeError):
        guard_egress(
            "Allow",
            model="openai/gpt-4o-mini",
            pii_policy={"types": {"EMAIL_ADDRESS": "redact"}, "egress": "allow"},
            local_only=True,
        )

    # Plain string build_chat_messages compatibility check + local model passthrough.
    local_msgs = build_chat_messages("Question?", [])
    local_out = guard_egress(
        local_msgs,
        model="ollama/llama3.2",
        pii_policy={"types": {"EMAIL_ADDRESS": "redact"}},
    )
    assert local_out == local_msgs


def test_audit_jsonl_lifecycle_permissions_and_zero_raw_pii(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    """Audit JSONL records counts/actions/versions cleanly with zero raw PII and 0o700/0o600."""
    corpus = tmp_path / "audit_corpus"
    corpus.mkdir()
    clean_file = corpus / "01_clean.md"
    clean_file.write_text("# Overview\n\nGeneral leave policy with no personal data.\n", "utf-8")
    pii_file = corpus / "02_contact.md"
    pii_file.write_text(
        (
            f"# Directory {_SYNTH_DNI_VALID}\n\n"
            f"Reach {_SYNTH_EMAIL} or {_SYNTH_IBAN_DE} at {_SYNTH_IPV4}.\n"
        ),
        encoding="utf-8",
    )

    policy_ingest: PiiPolicy = {
        "types": {
            "EMAIL_ADDRESS": "tokenize",
            "IBAN_CODE": "redact",
            "IP_ADDRESS": "redact",
            "ES_DNI": "redact",
            "US_SSN": "block",
        },
        "min_confidence": 0.65,
        "token_salt": "audit-salt",
    }

    ingest(
        corpus,
        collection="audit_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/embed",
        pii_policy=policy_ingest,
    )

    audit_path = audit_log_path(tmp_persist_dir, "audit_col")
    assert audit_path == tmp_persist_dir / "manifests" / "audit_col.audit.jsonl"
    assert audit_path.exists()
    if os.name == "posix":
        assert stat.S_IMODE(tmp_persist_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(audit_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(audit_path.stat().st_mode) == 0o600

    records = [json.loads(line) for line in audit_path.read_text("utf-8").splitlines()]
    assert len(records) == 2

    rec_clean, rec_pii = sorted(records, key=lambda r: r["source"])
    assert set(rec_clean.keys()) == {
        "timestamp",
        "collection",
        "source",
        "doc_version",
        "threshold",
        "entity_counts",
        "actions",
        "blocked",
        "mode",
    }
    assert rec_clean["source"] == "01_clean.md"
    assert rec_clean["doc_version"] == compute_file_hash(clean_file).split(":", 1)[1][:12]
    assert rec_clean["threshold"] == 0.65
    assert rec_clean["entity_counts"] == {}
    assert rec_clean["actions"] == {}
    assert rec_clean["blocked"] is False
    assert rec_clean["mode"] == "ingest"

    assert rec_pii["source"] == "02_contact.md"
    assert rec_pii["doc_version"] == compute_file_hash(pii_file).split(":", 1)[1][:12]
    assert list(rec_pii["entity_counts"].keys()) == sorted(rec_pii["entity_counts"].keys())
    assert list(rec_pii["actions"].keys()) == sorted(rec_pii["actions"].keys())
    assert rec_pii["entity_counts"] == {
        "EMAIL_ADDRESS": 1,
        "ES_DNI": 1,
        "IBAN_CODE": 1,
        "IP_ADDRESS": 1,
    }
    assert rec_pii["actions"] == {
        "EMAIL_ADDRESS": "tokenize",
        "ES_DNI": "redact",
        "IBAN_CODE": "redact",
        "IP_ADDRESS": "redact",
    }
    assert rec_pii["blocked"] is False
    assert rec_pii["mode"] == "ingest"

    # Mid-batch sync abort: prior staged doc must not commit, blocked doc logs blocked=True.
    batch = tmp_path / "sync_batch"
    batch.mkdir()
    shutil_clean = batch / "01_clean.md"
    shutil_clean.write_text("# Overview\n\nGeneral leave policy with no personal data.\n", "utf-8")
    shutil_pii = batch / "02_contact.md"
    shutil_pii.write_text(
        f"# Directory {_SYNTH_DNI_VALID}\n\nReach {_SYNTH_EMAIL}.\n",
        encoding="utf-8",
    )
    (batch / "03_uncommitted_ok.md").write_text(
        f"# Temp\n\nCall {_SYNTH_PHONE_US}.\n",
        encoding="utf-8",
    )
    blocked_doc = batch / "04_blocked.md"
    blocked_doc.write_text(
        f"# Secret\n\nSSN {_SYNTH_SSN_VALID} and card {_SYNTH_CARD_VALID}.\n",
        encoding="utf-8",
    )

    with pytest.raises(PiiBlockedError):
        sync(
            batch,
            collection="audit_col",
            persist_dir=tmp_persist_dir,
            embed_model="mock/embed",
            pii_policy={
                **policy_ingest,
                "types": {
                    **policy_ingest["types"],
                    "CREDIT_CARD": "block",
                    "PHONE_NUMBER": "redact",
                },
            },
        )

    post_records = [json.loads(line) for line in audit_path.read_text("utf-8").splitlines()]
    assert len(post_records) == 3
    blocked_rec = post_records[-1]
    assert blocked_rec["source"] == "04_blocked.md"
    assert blocked_rec["doc_version"] == compute_file_hash(blocked_doc).split(":", 1)[1][:12]
    assert blocked_rec["blocked"] is True
    assert blocked_rec["mode"] == "sync"
    assert blocked_rec["entity_counts"] == {"CREDIT_CARD": 1, "US_SSN": 1}
    assert blocked_rec["actions"] == {"CREDIT_CARD": "block", "US_SSN": "block"}
    assert all(r["source"] != "03_uncommitted_ok.md" for r in post_records)

    raw_audit_blob = audit_path.read_text("utf-8")
    for secret in (
        _SYNTH_EMAIL,
        "alex.rivera",
        _SYNTH_IBAN_DE,
        _SYNTH_IPV4,
        _SYNTH_DNI_VALID,
        _SYNTH_PHONE_US,
        _SYNTH_SSN_VALID,
        _SYNTH_CARD_VALID,
    ):
        assert secret not in raw_audit_blob


def test_optional_multilang_presidio_ner_and_error_modes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Optional [pii] NER is lazy, multi-language, offline-safe, and honors on_error modes."""
    # 1. Deterministic policies never require or import presidio_analyzer.
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)
    clean_text, counts, actions = apply_pii_policy_to_text(
        f"Reach {_SYNTH_EMAIL}.",
        {"types": {"EMAIL_ADDRESS": "redact"}},
    )
    assert clean_text == "Reach [EMAIL_ADDRESS]."
    assert counts == {"EMAIL_ADDRESS": 1}
    assert actions == {"EMAIL_ADDRESS": "redact"}

    # 2. Requesting NER entity (or ner=True) raises MissingExtraError with install hint.
    with pytest.raises(MissingExtraError, match=r"docpipe-maestro\[pii\]"):
        apply_pii_policy_to_text(
            "Jordan Lee lives in Madrid.",
            {"types": {"PERSON": "redact"}},
        )
    with pytest.raises(MissingExtraError, match=r"docpipe-maestro\[pii\]"):
        apply_pii_policy_to_text(
            "Hello world",
            {"types": {"EMAIL_ADDRESS": "redact"}, "ner": True, "on_error": "continue"},
        )

    # 3. Mocked offline multi-language Presidio backend loops across ALL configured languages.
    seen_languages: list[str] = []

    class _FakeAnalyzerEngine:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def analyze(
            self,
            *,
            text: str,
            entities: list[str],
            language: str,
        ) -> list[Any]:
            seen_languages.append(language)
            hits: list[Any] = []
            if language == "en" and "PERSON" in entities and "Jordan Lee" in text:
                idx = text.index("Jordan Lee")
                hits.append(
                    SimpleNamespace(
                        entity_type="PERSON",
                        start=idx,
                        end=idx + len("Jordan Lee"),
                        score=0.88,
                    )
                )
            if language == "es" and "LOCATION" in entities and "Madrid" in text:
                idx = text.index("Madrid")
                hits.append(
                    SimpleNamespace(
                        entity_type="LOCATION",
                        start=idx,
                        end=idx + len("Madrid"),
                        score=0.86,
                    )
                )
            return hits

    fake_presidio = ModuleType("presidio_analyzer")
    fake_presidio.AnalyzerEngine = _FakeAnalyzerEngine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "presidio_analyzer", fake_presidio)

    sample = f"Jordan Lee relocated to Madrid ({_SYNTH_EMAIL})."
    out_ner, ner_counts, ner_actions = apply_pii_policy_to_text(
        sample,
        {
            "types": {"PERSON": "redact", "LOCATION": "redact", "EMAIL_ADDRESS": "redact"},
            "languages": ["en", "es"],
        },
    )
    assert seen_languages == ["en", "es"]
    assert out_ner == "[PERSON] relocated to [LOCATION] ([EMAIL_ADDRESS])."
    assert ner_counts == {"EMAIL_ADDRESS": 1, "LOCATION": 1, "PERSON": 1}
    assert ner_actions == {"EMAIL_ADDRESS": "redact", "LOCATION": "redact", "PERSON": "redact"}

    # 4. Missing spaCy language model offline -> DocpipeError (never triggers download).
    class _MissingModelEngine:
        def __init__(self, **kwargs: Any) -> None:
            _ = kwargs
            raise OSError("[E050] Can't find model 'es_core_news_lg'")

    fake_presidio_missing = ModuleType("presidio_analyzer")
    fake_presidio_missing.AnalyzerEngine = _MissingModelEngine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "presidio_analyzer", fake_presidio_missing)

    with pytest.raises(DocpipeError, match="offline") as err_fail:
        apply_pii_policy_to_text(
            f"Jordan Lee SSN {_SYNTH_SSN_VALID}",
            {"types": {"PERSON": "redact", "US_SSN": "block"}, "on_error": "fail"},
        )
    assert _SYNTH_SSN_VALID not in str(err_fail.value)

    # 5. on_error="continue" logs NER runtime failure cleanly while still blocking US_SSN.
    with (
        caplog.at_level(logging.WARNING, logger="docpipe_maestro._pii"),
        pytest.raises(PiiBlockedError) as blk_continue,
    ):
        apply_pii_policy_to_text(
            f"Jordan Lee SSN {_SYNTH_SSN_VALID}",
            {"types": {"PERSON": "redact", "US_SSN": "block"}, "on_error": "continue"},
        )
    assert "US_SSN" in str(blk_continue.value)
    assert _SYNTH_SSN_VALID not in str(blk_continue.value)
    assert any("on_error='continue'" in r.message for r in caplog.records)

    cont_text, cont_counts, _ = apply_pii_policy_to_text(
        f"Contact {_SYNTH_EMAIL} in Madrid",
        {"types": {"EMAIL_ADDRESS": "redact", "LOCATION": "redact"}, "on_error": "continue"},
    )
    assert cont_text == "Contact [EMAIL_ADDRESS] in Madrid"
    assert cont_counts == {"EMAIL_ADDRESS": 1}


def test_release_gate_pii_end_to_end_synthetic_corpus(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release Gate #2 E2E: HTML+Markdown corpus ingest, retrieval, remote egress, and audit."""
    corpus = tmp_path / "gate2_corpus"
    corpus.mkdir()
    html_doc = corpus / "handbook.html"
    html_doc.write_text(
        (
            "<html><body>"
            f"<h1>Employee Record {_SYNTH_DNI_VALID}</h1>"
            f"<p>Email {_SYNTH_EMAIL} or call {_SYNTH_PHONE_ES}. "
            f"Billing IBAN {_SYNTH_IBAN_ES} from host {_SYNTH_IPV6}.</p>"
            "</body></html>"
        ),
        encoding="utf-8",
    )
    md_doc = corpus / "payroll.md"
    md_doc.write_text(
        (
            f"# Payroll Desk {_SYNTH_EMAIL}\n\n"
            f"Use host {_SYNTH_IPV4} and contact JORDAN LEE for approvals.\n"
        ),
        encoding="utf-8",
    )

    class _FakeGateAnalyzer:
        def __init__(self, **kwargs: Any) -> None:
            _ = kwargs

        def analyze(self, *, text: str, entities: list[str], language: str) -> list[Any]:
            if language == "en" and "PERSON" in entities and "JORDAN LEE" in text:
                idx = text.index("JORDAN LEE")
                return [
                    SimpleNamespace(
                        entity_type="PERSON",
                        start=idx,
                        end=idx + len("JORDAN LEE"),
                        score=0.91,
                    )
                ]
            return []

    fake_presidio = ModuleType("presidio_analyzer")
    fake_presidio.AnalyzerEngine = _FakeGateAnalyzer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "presidio_analyzer", fake_presidio)

    gate_policy: PiiPolicy = {
        "types": {
            "EMAIL_ADDRESS": "tokenize",
            "PHONE_NUMBER": "redact",
            "IBAN_CODE": "redact",
            "IP_ADDRESS": "redact",
            "ES_DNI": "redact",
            "PERSON": "redact",
        },
        "languages": ["en", "es"],
        "min_confidence": 0.6,
        "token_salt": "gate2-fixed-salt",
        "egress": "redact",
    }

    ingest_res = ingest(
        corpus,
        collection="gate2_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/embed",
        pii_policy=gate_policy,
    )
    assert sorted(ingest_res.ingested) == ["handbook.html", "payroll.md"]

    store = VectorStore(tmp_persist_dir, "gate2_col")
    all_stored_text = "\n".join(c.text for c in store.get_all_children() + store.get_all_parents())
    for raw_secret in (
        _SYNTH_DNI_VALID,
        _SYNTH_EMAIL,
        _SYNTH_PHONE_ES,
        _SYNTH_IBAN_ES,
        _SYNTH_IPV6,
        _SYNTH_IPV4,
        "JORDAN LEE",
    ):
        assert raw_secret not in all_stored_text

    # Same tokenized email across handbook.html body and payroll.md title matches deterministically.
    email_tokens = re.findall(r"\[EMAIL_ADDRESS_[0-9a-f]{8}\]", all_stored_text)
    assert len(email_tokens) >= 2
    assert len(set(email_tokens)) == 1

    hits = retrieve(
        "Billing approvals",
        collection="gate2_col",
        persist_dir=tmp_persist_dir,
        embed_model="mock/embed",
        top_k=4,
    )
    assert hits

    # Outbound remote completion scrubs both prompt user PII and any synthetic PII in messages.
    messages = build_chat_messages(f"Send summary to {_SYNTH_EMAIL} via {_SYNTH_IPV4}", hits)
    answer_detailed(
        messages,
        model="openai/gpt-4o-mini",
        pii_policy=gate_policy,
    )
    sent_payload = "\n".join(
        m["content"] for m in mock_litellm_offline["completion"][-1]["messages"]
    )
    for raw_secret in (_SYNTH_EMAIL, _SYNTH_IPV4, _SYNTH_IBAN_ES, _SYNTH_DNI_VALID, "JORDAN LEE"):
        assert raw_secret not in sent_payload
    assert email_tokens[0] in sent_payload

    audit_file = audit_log_path(tmp_persist_dir, "gate2_col")
    audit_lines = [json.loads(line) for line in audit_file.read_text("utf-8").splitlines()]
    assert len(audit_lines) == 2
    assert {r["source"] for r in audit_lines} == {"handbook.html", "payroll.md"}
    assert all(r["blocked"] is False for r in audit_lines)
    raw_audit = audit_file.read_text("utf-8")
    for raw_secret in (_SYNTH_EMAIL, _SYNTH_IBAN_ES, _SYNTH_DNI_VALID, _SYNTH_IPV4, "JORDAN LEE"):
        assert raw_secret not in raw_audit


def test_documentation_honest_disclosures_and_zero_overclaims() -> None:
    """Release Gate #2 / SC-006: docs must state honest limits with zero compliance overclaims."""
    repo_root = Path(__file__).resolve().parents[1]
    required_docs = ("SECURITY.md", "PRODUCT.md", "README.md")
    forbidden_overclaims = ("gdpr compliant", "100% accurate")
    for rel_path in required_docs:
        doc_path = repo_root / rel_path
        assert doc_path.is_file(), f"Missing required doc: {rel_path}"
        content = doc_path.read_text("utf-8").lower()
        for phrase in forbidden_overclaims:
            assert phrase not in content, f"Overclaim {phrase!r} found in {rel_path}"
        assert "false positive" in content or "false-positive" in content, (
            f"Expected false-positive disclosure in {rel_path}"
        )
        assert "false negative" in content or "false-negative" in content, (
            f"Expected false-negative disclosure in {rel_path}"
        )


def test_pii_and_egress_debug_telemetry_zero_raw_leaks(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release Gate #2 + Stage 8: DEBUG telemetry logs emit safe stats and zero raw PII."""
    import io

    from docpipe_maestro.log import JsonFormatter, get_logger

    pkg_logger = get_logger()
    prev_level = pkg_logger.level
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonFormatter())
    pkg_logger.setLevel(logging.DEBUG)
    pkg_logger.addHandler(handler)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-gate2-telemetry-secret-42")

    try:
        corpus = tmp_path / "pii_tel_docs"
        corpus.mkdir()
        (corpus / "clean_ok.md").write_text(
            f"# Contacts\n\nSend receipts to {_SYNTH_EMAIL}.\n",
            encoding="utf-8",
        )
        tokenize_policy: PiiPolicy = {
            "types": {"EMAIL_ADDRESS": "tokenize", "US_SSN": "block"},
            "token_salt": "tel-salt-99",
            "egress": "redact",
        }
        ingest(
            corpus,
            collection="pii_tel",
            persist_dir=tmp_persist_dir,
            embed_model="mock/embed",
            pii_policy=tokenize_policy,
        )

        # Blocked SSN triggers ERROR stage.end for enrich without raw SSN leakage.
        blocked_doc = tmp_path / "blocked_ssn.txt"
        blocked_doc.write_text(f"Confidential SSN: {_SYNTH_SSN_VALID}\n", encoding="utf-8")
        with pytest.raises(PiiBlockedError):
            ingest(
                blocked_doc,
                collection="pii_tel",
                persist_dir=tmp_persist_dir,
                embed_model="mock/embed",
                pii_policy=tokenize_policy,
            )

        # Remote answer egress redact and block flows.
        hits = retrieve(
            "contacts receipts",
            collection="pii_tel",
            persist_dir=tmp_persist_dir,
            embed_model="mock/embed",
        )
        scrub_msgs = build_chat_messages(f"Reply to {_SYNTH_EMAIL}", hits)
        answer_detailed(scrub_msgs, model="openai/gpt-4o-mini", pii_policy=tokenize_policy)

        block_msgs = build_chat_messages(f"SSN {_SYNTH_SSN_VALID}", hits)
        with pytest.raises(PiiBlockedError):
            answer_detailed(block_msgs, model="openai/gpt-4o-mini", pii_policy=tokenize_policy)
    finally:
        pkg_logger.removeHandler(handler)
        handler.close()
        pkg_logger.setLevel(prev_level)

    raw_logs = buf.getvalue()
    parsed = [json.loads(line) for line in raw_logs.strip().splitlines()]
    stages_seen = {rec["fields"].get("stage") for rec in parsed}
    assert {"enrich", "egress", "answer"}.issubset(stages_seen)
    assert any(
        rec["level"] == "ERROR"
        and rec["fields"].get("stage") == "enrich"
        and rec["fields"].get("error_type") == "PiiBlockedError"
        for rec in parsed
    )
    assert any(
        rec["level"] == "ERROR"
        and rec["fields"].get("stage") == "egress"
        and rec["fields"].get("error_type") == "PiiBlockedError"
        for rec in parsed
    )
    for secret in (_SYNTH_EMAIL, _SYNTH_SSN_VALID, "tel-salt-99", "sk-gate2-telemetry-secret-42"):
        assert secret not in raw_logs

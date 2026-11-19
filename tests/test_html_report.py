"""Unit and CLI integration tests for static HTML Document Integrity & Chunk Audit Reports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro.cli import main
from docpipe_maestro.report import COMPLIANCE_TAGS, build_audit_report, export_html_report
from docpipe_maestro.types import Chunk, ChunkMetadata

_REPORT_JSON_RE = re.compile(
    r'<script\s+id="report-data"\s+type="application/json">\s*(.*?)\s*</script>',
    re.DOTALL,
)


def _extract_embedded_json(html_text: str) -> dict[str, Any]:
    match = _REPORT_JSON_RE.search(html_text)
    assert match is not None, "Expected <script id='report-data' type='application/json'> element"
    decoded = json.loads(match.group(1))
    assert isinstance(decoded, dict)
    return decoded


def test_html_report_created_offline_with_bound_exceptions_and_cli_integration(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = tmp_path / "leave_policy.md"
    policy.write_text(
        "# HR Leave Policy\n\n"
        "## Section 1: Annual Leave\n\n"
        "1.1 Full-time staff accrue 20 days of annual leave per year, except for employees "
        "in their initial 90-day probationary period.\n\n"
        "1.2 Accrued days carry over up to 5 days, unless the role is fixed-term.\n\n"
        "## Section 2: Sabbatical Rules\n\n"
        "2.1 Employees with five years tenure may apply for sabbatical, "
        "subject to Section 4 approval.\n\n"
        "2.2 Contractors are not entitled to paid sabbatical leave, "
        "provided that exceptions require HR review and §1.1 eligibility.\n\n"
        "## Section 4: Approval Process\n\n"
        "4.1 Applications require department head approval 60 days ahead, "
        "except in documented medical emergencies.\n",
        encoding="utf-8",
    )

    ingest_report = tmp_path / "reports" / "ingest_audit.html"
    rc = main(
        [
            "ingest",
            str(policy),
            "--profile",
            "POLICY",
            "--collection",
            "audit_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "--html-report",
            str(ingest_report),
        ]
    )
    assert rc == 0
    ingest_out = capsys.readouterr().out
    assert "HTML audit report saved to:" in ingest_out
    assert ingest_report.is_file()

    # Export offline read-only via `status --html-report` without calling embedder again
    embed_calls_before = len(mock_litellm_offline["embedding"])
    status_report = tmp_path / "reports" / "status_audit.html"
    rc = main(
        [
            "status",
            "--collection",
            "audit_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "--json",
            "--html-report",
            str(status_report),
        ]
    )
    assert rc == 0
    assert len(mock_litellm_offline["embedding"]) == embed_calls_before
    status_stdout = capsys.readouterr().out
    status_payload = json.loads(status_stdout)
    assert status_payload["collection"] == "audit_col"
    assert status_payload["total_sources"] == 1
    assert status_report.is_file()

    html_content = status_report.read_text(encoding="utf-8")
    lowered = html_content.lower()
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "<style>" in html_content
    assert "<script>" in html_content
    assert "@media print" in html_content
    assert "size: A4 portrait" in html_content
    for tag in COMPLIANCE_TAGS:
        assert tag in html_content
    for pill_label in ("ALL", "HAS_EXCEPTION", "HAS_CROSS_REF", "WARNING / SPLIT"):
        assert pill_label in html_content

    payload = _extract_embedded_json(html_content)
    assert payload["collection"] == "audit_col"
    assert payload["document_summary"] == "leave_policy.md"
    assert payload["document_hash_summary"].startswith("sha256:")

    kpis = payload["kpis"]
    assert kpis["total_chunks"] >= 3
    assert kpis["clause_integrity_rate_pct"] == 100.0
    assert kpis["crossrefs_resolved"] >= 2
    assert kpis["crossref_resolution_rate_pct"] == 100.0
    assert kpis["rule_exception_links_total"] >= 4
    assert kpis["rule_exception_links_preserved"] == kpis["rule_exception_links_total"]
    assert kpis["rule_exception_preservation_rate_pct"] == 100.0

    chunks = payload["chunks"]
    assert chunks
    exception_markers = {
        exc["marker"]
        for chunk in chunks
        for exc in chunk["bound_exceptions"]
        if exc["preserved_in_parent"]
    }
    assert {"except", "unless", "subject to", "not entitled", "provided that"}.issubset(
        exception_markers
    )
    assert any(chunk["resolved_crossrefs"] for chunk in chunks)
    assert all(" > " in chunk["breadcrumb"] for chunk in chunks)
    assert all(chunk["token_count"] > 0 and chunk["char_count"] > 0 for chunk in chunks)


def test_cli_sync_html_report_and_validation_guards(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "travel.md").write_text(
        "## Section 1: Travel Caps\n\n"
        "1.1 Flights are economy class, except when medically approved.\n",
        encoding="utf-8",
    )

    # Dry-run combined with --html-report must fail upfront with zero store writes
    dry_report = tmp_path / "should_not_exist.html"
    rc = main(
        [
            "sync",
            str(corpus),
            "--profile",
            "POLICY",
            "--collection",
            "sync_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "--dry-run",
            "--html-report",
            str(dry_report),
        ]
    )
    assert rc == 1
    assert "cannot be combined with --dry-run" in capsys.readouterr().err
    assert not dry_report.exists()

    # Empty path and directory path rejected cleanly
    assert (
        main(
            [
                "status",
                "--collection",
                "sync_col",
                "--persist-dir",
                str(tmp_persist_dir),
                "--html-report",
                "   ",
            ]
        )
        == 1
    )
    assert "must not be empty" in capsys.readouterr().err

    assert (
        main(
            [
                "status",
                "--collection",
                "sync_col",
                "--persist-dir",
                str(tmp_persist_dir),
                "--html-report",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert "not a directory" in capsys.readouterr().err

    # Live sync writes report cleanly
    sync_report = tmp_path / "sync_audit.html"
    rc = main(
        [
            "sync",
            str(corpus),
            "--profile",
            "POLICY",
            "--collection",
            "sync_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "--html-report",
            str(sync_report),
        ]
    )
    assert rc == 0
    assert "HTML audit report saved to:" in capsys.readouterr().out
    payload = _extract_embedded_json(sync_report.read_text(encoding="utf-8"))
    assert payload["kpis"]["total_chunks"] == 1
    assert payload["chunks"][0]["bound_exceptions"][0]["marker"] == "except"


def test_html_report_neutralizes_script_breakout_and_html_injection(
    tmp_path: Path,
    tmp_persist_dir: Path,
) -> None:
    hostile_text = "Rule 1.1 allows leave, except </script><img src=x onerror=alert(1)> & <tag>."
    parent_meta: ChunkMetadata = {
        "type": "parent",
        "source": "bad</script>doc.md",
        "doc_version": "abc123def456",
        "section": "Section <1>",
        "clause": None,
        "page": None,
        "chunk_index": 0,
        "embed_model": "ollama/nomic-embed-text",
    }
    child_meta: ChunkMetadata = {
        "type": "child",
        "source": "bad</script>doc.md",
        "doc_version": "abc123def456",
        "section": "Section <1>",
        "clause": "1.1",
        "page": None,
        "chunk_index": 0,
        "embed_model": "ollama/nomic-embed-text",
    }
    child_header = "[Source: bad</script>doc.md | Section: Section <1> | Clause: 1.1]\n"
    chunks = [
        Chunk(id="parent001", text=hostile_text, parent_id=None, metadata=parent_meta),
        Chunk(
            id="child001",
            text=f"{child_header}{hostile_text}",
            parent_id="parent001",
            metadata=child_meta,
        ),
    ]
    out_file = export_html_report(
        tmp_path / "xss_safe.html",
        collection="sec_test",
        persist_dir=tmp_persist_dir,
        chunks=chunks,
        embed_model="ollama/nomic-embed-text",
    )
    html_text = out_file.read_text(encoding="utf-8")
    # Only the two legitimate closing tags (<script id="report-data"> and client <script>) exist.
    assert html_text.count("</script>") == 2
    assert "<img src=x onerror=alert(1)>" not in html_text
    payload = _extract_embedded_json(html_text)
    assert payload["chunks"][0]["text"] == hostile_text


def test_report_detects_splits_unresolved_crossrefs_and_unbound_exceptions() -> None:
    split_chunks = [
        Chunk(
            id="c1",
            text=(
                "[Source: draft.md | Section: Section 1 | Clause: 1.1]\n"
                "1.1 Leave applies subject to Section 99"
            ),
            parent_id="missing_parent_id",
            metadata={
                "type": "child",
                "source": "draft.md",
                "doc_version": "000000000001",
                "section": "Section 1",
                "clause": "1.1",
                "page": 2,
                "chunk_index": 0,
                "embed_model": "ollama/nomic-embed-text",
            },
        ),
        Chunk(
            id="c2",
            text=(
                "[Source: draft.md | Section: Section 1 | Clause: 1.1]\n"
                "unless temporary contractor status."
            ),
            parent_id="missing_parent_id",
            metadata={
                "type": "child",
                "source": "draft.md",
                "doc_version": "000000000001",
                "section": "Section 1",
                "clause": "1.1",
                "page": 2,
                "chunk_index": 1,
                "embed_model": "ollama/nomic-embed-text",
            },
        ),
    ]
    report = build_audit_report(split_chunks, collection="broken_col")
    kpis = report["kpis"]
    assert kpis["total_chunks"] == 2
    assert kpis["split_or_broken_chunks"] == 2
    assert kpis["clause_integrity_rate_pct"] == 0.0
    assert kpis["crossrefs_total"] == 1
    assert kpis["crossrefs_resolved"] == 0
    assert kpis["crossref_resolution_rate_pct"] == 0.0
    assert kpis["rule_exception_links_total"] == 2
    assert kpis["rule_exception_links_preserved"] == 0
    assert kpis["rule_exception_preservation_rate_pct"] == 0.0

    c1, c2 = report["chunks"]
    assert c1["breadcrumb"] == "draft.md > Page 2 > Section 1 > Clause 1.1"
    assert c1["has_warning"] and c2["has_warning"]
    assert "Section 99" in c1["unresolved_crossrefs"]
    assert all(not exc["preserved_in_parent"] for exc in c1["bound_exceptions"])
    assert any("lowercase continuation" in w for w in c2["warnings"])


def test_status_html_report_on_empty_collection_makes_no_chroma_files(
    tmp_path: Path,
    tmp_persist_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_report = tmp_path / "empty.html"
    rc = main(
        [
            "status",
            "--collection",
            "uninitialized_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "--html-report",
            str(empty_report),
        ]
    )
    assert rc == 0
    _ = capsys.readouterr()
    assert empty_report.is_file()
    assert not (tmp_persist_dir / "chroma.sqlite3").exists()
    payload = _extract_embedded_json(empty_report.read_text(encoding="utf-8"))
    assert payload["kpis"]["total_chunks"] == 0
    assert payload["kpis"]["clause_integrity_rate_pct"] is None
    assert payload["kpis"]["rule_exception_preservation_rate_pct"] is None

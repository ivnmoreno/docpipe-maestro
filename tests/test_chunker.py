"""Unit tests for structure-aware hierarchical chunking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docpipe_maestro import ingest, retrieve
from docpipe_maestro.config import DEFAULT, POLICY
from docpipe_maestro.ingest.chunker import chunk_document
from docpipe_maestro.ingest.clean import clean_document
from docpipe_maestro.ingest.intake import parse_file


def test_parent_child_linking_and_context_headers(tmp_path: Path) -> None:
    md = tmp_path / "handbook.md"
    md.write_text(
        "# Handbook\n\n"
        "## Section 1: Annual Leave\n\n"
        "1.1 Full-time employees receive 20 days of annual leave.\n\n"
        "1.2 Employees with less than one year of service are not entitled to full leave.\n\n"
        "## Section 2: Sick Leave\n\n"
        "2.1 Sick leave is granted up to 10 days per year.\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(md, source_key="handbook.md"))
    chunks = chunk_document(
        doc, profile=POLICY, doc_version="v1", embed_model="ollama/nomic-embed-text"
    )

    parents = [c for c in chunks if c.metadata["type"] == "parent"]
    children = [c for c in chunks if c.metadata["type"] == "child"]

    assert len(parents) >= 2
    assert len(children) >= 2
    parent_ids = {p.id for p in parents}

    for parent in parents:
        assert parent.parent_id is None

    for child in children:
        assert child.parent_id in parent_ids
        assert child.text.startswith("[Source: handbook.md | Section:")


def test_policy_profile_never_splits_long_clause(tmp_path: Path) -> None:
    long_clause = "1.1 " + " ".join(["entitlement"] * 1200) + " except new hires."
    md = tmp_path / "long_policy.md"
    md.write_text(f"## Section 1: Rules\n\n{long_clause}\n", encoding="utf-8")

    doc = clean_document(parse_file(md, source_key="long_policy.md"))
    chunks = chunk_document(
        doc, profile=POLICY, doc_version="v1", embed_model="ollama/nomic-embed-text"
    )
    children = [c for c in chunks if c.metadata["type"] == "child"]

    # Indivisible clause exceeding 1000 tokens must stay intact in a single child chunk
    assert len(children) == 1
    assert "except new hires." in children[0].text


def test_overlap_resets_at_section_boundaries(tmp_path: Path) -> None:
    md = tmp_path / "sections.md"
    md.write_text(
        "## Section A: Alpha\n\n"
        "UniqueAlphaToken " + " ".join(["alpha"] * 300) + "\n\n"
        "## Section B: Beta\n\n"
        "UniqueBetaToken " + " ".join(["beta"] * 300) + "\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(md, source_key="sections.md"))
    chunks = chunk_document(
        doc, profile=DEFAULT, doc_version="v1", embed_model="ollama/nomic-embed-text"
    )
    sec_b_children = [
        c for c in chunks if c.metadata["type"] == "child" and "Beta" in c.metadata["section"]
    ]
    assert sec_b_children
    for child in sec_b_children:
        assert "UniqueAlphaToken" not in child.text


def test_duplicate_sections_unique_ids_and_default_coalescing(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    dup = tmp_path / "dup.md"
    dup.write_text(
        "## Notes\n\nIntentionally left blank.\n\n## Notes\n\nIntentionally left blank.\n",
        encoding="utf-8",
    )
    doc = clean_document(parse_file(dup, source_key="dup.md"))
    chunks = chunk_document(doc, profile=POLICY, doc_version="v1", embed_model="m")
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)) == 4

    # Must ingest into ChromaDB cleanly without DuplicateIDError
    res = ingest(dup, profile="POLICY", collection="dup_col", persist_dir=tmp_persist_dir)
    assert res.chunks_written == 2
    assert (
        len(retrieve("Intentionally left blank", collection="dup_col", persist_dir=tmp_persist_dir))
        >= 1
    )

    # DEFAULT profile coalesces short consecutive paragraphs under chunk_size budget
    prose = tmp_path / "prose.md"
    prose.write_text(
        "# Article\n\n"
        + "\n\n".join(f"Paragraph {i} explains engineering guidelines clearly." for i in range(10)),
        encoding="utf-8",
    )
    prose_doc = clean_document(parse_file(prose, source_key="prose.md"))
    prose_chunks = chunk_document(prose_doc, profile=DEFAULT, doc_version="v1", embed_model="m")
    prose_children = [c for c in prose_chunks if c.metadata["type"] == "child"]
    assert len(prose_children) == 1

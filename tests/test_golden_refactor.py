"""Offline deterministic golden query equivalence test against Stage 0 snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docpipe_maestro import ingest, retrieve

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "golden_query_stage1.json"


def test_golden_query_equivalence_against_stage0_baseline(
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    corpus_path = Path(__file__).parent.parent / golden["corpus"]
    collection = golden["collection"]

    ingest(
        corpus_path,
        profile=golden["profile"],
        collection=collection,
        persist_dir=tmp_persist_dir,
    )

    for case in golden["queries"]:
        results = retrieve(
            case["question"],
            collection=collection,
            persist_dir=tmp_persist_dir,
            top_k=case["top_k"],
            threshold=case["threshold"],
            expand_parent=case["expand_parent"],
            follow_crossrefs=case["follow_crossrefs"],
        )
        observed = [
            {
                "id": chunk.id,
                "parent_id": chunk.parent_id,
                "score": chunk.score,
                "text": chunk.text,
                "metadata": dict(chunk.metadata),
            }
            for chunk in results
        ]
        assert observed == case["results"], f"Golden mismatch for query case {case['name']!r}"

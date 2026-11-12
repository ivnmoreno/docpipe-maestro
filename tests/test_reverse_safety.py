"""Mandatory Release Gate: Reverse Safety Test for exception preservation.

Constitution Principle V: Any retrieval context containing a rule with an exception
marker ('except', 'unless', 'not entitled', 'subject to', 'provided that') MUST
also contain that exception.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, retrieve

POLICY_CORPUS = Path(__file__).parent / "fixtures" / "policy_corpus"

EXCEPTION_CASES = [
    ("annual leave paid days full-time employees", "except", "initial 90-day probationary period"),
    ("accrued annual leave carried over calendar year", "unless", "fixed-term seasonal contract"),
    (
        "part-time contractors paid sabbatical leave holiday stipends",
        "not entitled",
        "not entitled to paid sabbatical",
    ),
    ("continuous tenure paid sabbatical four weeks", "subject to", "Section 4"),
    ("home-office equipment stipend $500 annually", "provided that", "within 30 days of purchase"),
    ("economy class airfare domestic flights reimbursed", "except", "medical accommodation"),
    ("hotel stays above $250 per night reimbursed", "unless", "Clause 2.1"),
    (
        "written pre-approval Vice President lodging airfare caps",
        "provided that",
        "two comparable quotes",
    ),
]


@pytest.mark.reverse
@pytest.mark.parametrize(("query", "marker", "expected_exception"), EXCEPTION_CASES)
def test_reverse_safety_exception_preservation(
    query: str,
    marker: str,
    expected_exception: str,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    ingest(
        POLICY_CORPUS,
        profile="POLICY",
        collection="reverse_gate",
        persist_dir=tmp_persist_dir,
    )
    results = retrieve(
        query,
        collection="reverse_gate",
        persist_dir=tmp_persist_dir,
        top_k=3,
        expand_parent=True,
    )
    assert results, f"Expected retrieval results for query {query!r}"
    combined_context = "\n".join(r.text for r in results)
    assert marker in combined_context.lower(), (
        f"Expected exception marker {marker!r} in retrieved context for {query!r}"
    )
    assert expected_exception.lower() in combined_context.lower(), (
        f"Expected exception text {expected_exception!r} in retrieved context for {query!r}"
    )

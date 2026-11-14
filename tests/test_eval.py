"""Unit and offline integration tests for docpipe_maestro.eval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro import ingest, retrieve, status
from docpipe_maestro.config import DEFAULT_COLLECTION, DEFAULT_EMBED_MODEL
from docpipe_maestro.eval import (
    DEFAULT_EVAL_K_VALUES,
    EvalConfig,
    EvalFixture,
    EvalMetricsSummary,
    EvalQuery,
    EvalReport,
    PerQueryResult,
    evaluate,
    load_eval_fixture,
    normalize_k_values,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from docpipe_maestro.manifest import save_manifest
from docpipe_maestro.types import DocpipeError, Manifest, ModelMismatchError, RegistryError


def _snapshot_tree_hashes(root: Path) -> dict[str, str]:
    """Capture relative-path SHA-256 digests of every file under ``root``."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _seed_two_doc_policy_collection(
    tmp_path: Path,
    persist_dir: Path,
    *,
    collection: str = "eval_test",
) -> tuple[str, str, str]:
    """Seed two distinct Markdown policy documents and return (parent1, parent2, child1)."""
    corpus_dir = tmp_path / f"corpus_{collection}"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "security.md").write_text(
        (
            "# Encryption Policy\n\n"
            "All database backups MUST use AES-256 encryption at rest under KMS-401.\n"
            "Development snapshots are excluded except when storing customer identifiers.\n"
        ),
        encoding="utf-8",
    )
    (corpus_dir / "leave.md").write_text(
        (
            "# Parental Leave\n\n"
            "Eligible employees receive 16 weeks of paid parental leave after birth or adoption.\n"
            "Contractors are not entitled unless approved by People Operations.\n"
        ),
        encoding="utf-8",
    )
    ingest(
        corpus_dir,
        profile="POLICY",
        collection=collection,
        persist_dir=persist_dir,
    )
    st = status(collection=collection, persist_dir=persist_dir)
    sec_rec = next(rec for rec in st.sources if rec.source.endswith("security.md"))
    leave_rec = next(rec for rec in st.sources if rec.source.endswith("leave.md"))
    p1 = sec_rec.parent_ids[0]
    p2 = leave_rec.parent_ids[0]
    c1 = sec_rec.chunk_ids[0]
    return p1, p2, c1


# ---------------------------------------------------------------------------
# Pure Metric Unit Tests (FR-001)
# ---------------------------------------------------------------------------


def test_precision_and_recall_at_k_standard_ir_and_clamping() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["a", "c", "e", "f"]

    # K=2: hits={a}, fixed denominator 2 -> 0.5; Recall denominator |relevant|=4 -> 0.25
    assert precision_at_k(retrieved, relevant, 2) == pytest.approx(0.5)
    assert recall_at_k(retrieved, relevant, 2) == pytest.approx(0.25)

    # K=10 > len(retrieved): Precision divides by K=10 (0.2), Recall divides by 4 (0.5)
    assert precision_at_k(retrieved, relevant, 10) == pytest.approx(0.2)
    assert recall_at_k(retrieved, relevant, 10) == pytest.approx(0.5)

    # Duplicate retrieved / relevant IDs must be deduplicated cleanly and stay in [0.0, 1.0]
    assert precision_at_k(["a", "a", "a"], ["a", "a"], 2) == pytest.approx(0.5)
    assert recall_at_k(["a", "a", "b"], ["a", "a"], 3) == pytest.approx(1.0)


def test_reciprocal_rank_and_empty_boundaries() -> None:
    assert reciprocal_rank(["a", "b", "c"], ["a"]) == pytest.approx(1.0)
    assert reciprocal_rank(["x", "y", "b", "c"], ["b", "c"]) == pytest.approx(1.0 / 3.0)
    assert reciprocal_rank(["x", "y"], ["b"]) == pytest.approx(0.0)

    # Pure metrics safely return 0.0 on empty retrieved or empty relevant IDs
    assert precision_at_k([], ["a"], 3) == 0.0
    assert precision_at_k(["a"], [], 3) == 0.0
    assert recall_at_k([], ["a"], 3) == 0.0
    assert recall_at_k(["a"], [], 3) == 0.0
    assert reciprocal_rank([], ["a"]) == 0.0
    assert reciprocal_rank(["a"], []) == 0.0


@pytest.mark.parametrize("bad_k", [0, -1, -100, True, False])
def test_metric_cutoffs_reject_bool_and_non_positive(bad_k: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        precision_at_k(["a"], ["a"], bad_k)
    with pytest.raises(ValueError, match="positive integer"):
        recall_at_k(["a"], ["a"], bad_k)


def test_normalize_k_values_sorts_deduplicates_and_validates() -> None:
    assert DEFAULT_EVAL_K_VALUES == (1, 3, 5, 10)
    assert normalize_k_values([10, 3, 3]) == (3, 10)
    assert normalize_k_values((5,)) == (5,)

    for bad_seq in ([], (), [0], [1, -3], [True, 3]):
        with pytest.raises(ValueError):
            normalize_k_values(bad_seq)


# ---------------------------------------------------------------------------
# Fixture Loading & Validation Tests (FR-002)
# ---------------------------------------------------------------------------


def test_load_eval_fixture_normalizes_json_and_in_memory_dict(tmp_path: Path) -> None:
    raw_in_memory: EvalFixture = {
        "queries": [
            {"question": "What encryption standard applies?", "relevant_ids": ["p1", "p1", "p2"]}
        ]
    }
    loaded_mem = load_eval_fixture(raw_in_memory)
    assert loaded_mem["collection"] == ""
    assert loaded_mem["profile"] == ""
    assert loaded_mem["queries"] == [
        {
            "question": "What encryption standard applies?",
            "relevant_ids": ["p1", "p2"],
            "notes": "",
        }
    ]
    # Caller dictionary must remain unmodified
    assert "collection" not in raw_in_memory
    assert raw_in_memory["queries"][0]["relevant_ids"] == ["p1", "p1", "p2"]

    fixture_path = _write_json(
        tmp_path / "valid.json",
        {
            "collection": "my_col",
            "profile": "POLICY",
            "queries": [
                {
                    "question": "Who approves parental leave?",
                    "relevant_ids": ["p2"],
                    "notes": "direct_lookup",
                }
            ],
        },
    )
    loaded_file = load_eval_fixture(fixture_path)
    assert loaded_file["collection"] == "my_col"
    assert loaded_file["profile"] == "POLICY"
    assert loaded_file["queries"][0]["notes"] == "direct_lookup"


def test_load_eval_fixture_rejects_invalid_inputs(tmp_path: Path) -> None:
    with pytest.raises(DocpipeError):
        load_eval_fixture(tmp_path / "does_not_exist.json")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DocpipeError):
        load_eval_fixture(bad_json)

    non_obj = _write_json(tmp_path / "list_root.json", ["a"])
    with pytest.raises(DocpipeError):
        load_eval_fixture(non_obj)

    invalid_payloads: list[Any] = [
        {"queries": []},
        {"queries": "not-a-list"},
        {"queries": ["not-an-object"]},
        {"queries": [{"question": "   ", "relevant_ids": ["id1"]}]},
        {"queries": [{"question": "valid?", "relevant_ids": []}]},
        {"queries": [{"question": "valid?", "relevant_ids": ["  "]}]},
        {"queries": [{"question": "valid?", "relevant_ids": [123]}]},
        {"collection": 123, "queries": [{"question": "q?", "relevant_ids": ["id1"]}]},
        {"profile": 456, "queries": [{"question": "q?", "relevant_ids": ["id1"]}]},
        {
            "queries": [
                {"question": "q?", "relevant_ids": ["id1"], "notes": ["wrong"]},
            ]
        },
    ]
    for idx, payload in enumerate(invalid_payloads):
        path = _write_json(tmp_path / f"invalid_{idx}.json", payload)
        with pytest.raises(DocpipeError):
            load_eval_fixture(path)


# ---------------------------------------------------------------------------
# Offline Evaluation Runner & Read-Only Guarantees (FR-002, FR-003, SC-001/002)
# ---------------------------------------------------------------------------


def test_evaluate_preflight_errors_leave_persist_dir_untouched(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    # 1. Non-existent persist_dir must NOT be created by missing-collection check
    uncreated_dir = tmp_path / "uncreated_docpipe"
    valid_fixture: EvalFixture = {
        "collection": "missing_collection",
        "queries": [{"question": "AES-256?", "relevant_ids": ["p1"]}],
    }
    with pytest.raises(DocpipeError, match="missing_collection"):
        evaluate(valid_fixture, persist_dir=uncreated_dir)
    assert not uncreated_dir.exists()

    # 2. Empty manifest (no sources) fails without mutating persist_dir
    save_manifest(tmp_persist_dir, Manifest(collection="empty_col"))
    before_empty = _snapshot_tree_hashes(tmp_persist_dir)
    with pytest.raises(DocpipeError, match="no committed documents"):
        evaluate(valid_fixture, collection="empty_col", persist_dir=tmp_persist_dir)
    assert _snapshot_tree_hashes(tmp_persist_dir) == before_empty

    # 3. Seeded collection checks: model lock, registry selectors, threshold, cutoffs
    p1, _p2, _c1 = _seed_two_doc_policy_collection(tmp_path, tmp_persist_dir, collection="seeded")
    seeded_fixture: EvalFixture = {
        "collection": "seeded",
        "queries": [{"question": "What uses AES-256?", "relevant_ids": [p1]}],
    }
    snap = _snapshot_tree_hashes(tmp_persist_dir)

    with pytest.raises(ModelMismatchError):
        evaluate(seeded_fixture, persist_dir=tmp_persist_dir, embed_model="openai/other-model")
    assert _snapshot_tree_hashes(tmp_persist_dir) == snap

    for kwargs in (
        {"searcher": "ghost_searcher"},
        {"embedder": "ghost_embedder"},
        {"store": "ghost_store"},
    ):
        with pytest.raises(RegistryError):
            evaluate(seeded_fixture, persist_dir=tmp_persist_dir, **kwargs)  # type: ignore[arg-type]
        assert _snapshot_tree_hashes(tmp_persist_dir) == snap

    for bad_threshold in (-0.1, 1.1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            evaluate(seeded_fixture, persist_dir=tmp_persist_dir, threshold=bad_threshold)
        assert _snapshot_tree_hashes(tmp_persist_dir) == snap

    with pytest.raises(ValueError):
        evaluate(seeded_fixture, persist_dir=tmp_persist_dir, k_values=[0, 5])
    assert _snapshot_tree_hashes(tmp_persist_dir) == snap


def test_evaluate_precedence_expand_parent_and_k_normalization(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
) -> None:
    p1, p2, c1 = _seed_two_doc_policy_collection(
        tmp_path, tmp_persist_dir, collection="col_primary"
    )
    _seed_two_doc_policy_collection(tmp_path, tmp_persist_dir, collection=DEFAULT_COLLECTION)

    # Explicit collection overrides fixture["collection"]; profile is informational only
    override_fixture: EvalFixture = {
        "collection": "missing_from_fixture",
        "profile": "DEFAULT",
        "queries": [
            {
                "question": "AES-256 KMS-401 encryption backups",
                "relevant_ids": [p1],
                "notes": "exact_identifier",
            },
            {
                "question": "paid parental leave after birth or adoption",
                "relevant_ids": [p2],
                "notes": "direct_lookup",
            },
        ],
    }
    report_explicit = evaluate(
        override_fixture,
        collection="col_primary",
        persist_dir=tmp_persist_dir,
        k_values=[10, 3, 3],
    )
    assert report_explicit["config"]["collection"] == "col_primary"
    assert report_explicit["config"]["k_values"] == [3, 10]
    assert list(report_explicit["aggregate"]["precision_at_k"]) == ["3", "10"]
    assert list(report_explicit["aggregate"]["recall_at_k"]) == ["3", "10"]
    assert report_explicit["aggregate"]["num_queries"] == 2
    assert report_explicit["aggregate"]["mrr"] == pytest.approx(1.0)
    assert report_explicit["per_query"][0]["retrieved_ids"][0] == p1

    # Omitted collection uses fixture collection when non-empty, else DEFAULT_COLLECTION
    default_st = status(collection=DEFAULT_COLLECTION, persist_dir=tmp_persist_dir)
    default_sec = next(rec for rec in default_st.sources if rec.source.endswith("security.md"))
    default_p1 = default_sec.parent_ids[0]
    omitted_col_fixture: EvalFixture = {
        "queries": [{"question": "AES-256 KMS-401", "relevant_ids": [default_p1]}]
    }
    report_default = evaluate(omitted_col_fixture, persist_dir=tmp_persist_dir)
    assert report_default["config"]["collection"] == DEFAULT_COLLECTION

    # expand_parent=False returns child IDs instead of parent IDs
    child_report = evaluate(
        {
            "collection": "col_primary",
            "queries": [{"question": "AES-256 KMS-401", "relevant_ids": [c1]}],
        },
        persist_dir=tmp_persist_dir,
        expand_parent=False,
        k_values=[1, 3],
    )
    assert child_report["config"]["expand_parent"] is False
    assert child_report["per_query"][0]["retrieved_ids"][0] == c1
    assert child_report["aggregate"]["mrr"] == pytest.approx(1.0)
    # Sanity check direct retrieve parity
    direct = retrieve(
        "AES-256 KMS-401",
        collection="col_primary",
        persist_dir=tmp_persist_dir,
        top_k=3,
        expand_parent=False,
    )
    assert child_report["per_query"][0]["retrieved_ids"] == [r.id for r in direct]


@pytest.mark.parametrize("searcher", ["default", "fts5_hybrid"])
def test_evaluate_repeatable_and_zero_persist_byte_drift(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    searcher: str,
) -> None:
    p1, p2, _c1 = _seed_two_doc_policy_collection(
        tmp_path, tmp_persist_dir, collection="drift_check"
    )
    fixture_path = _write_json(
        tmp_path / "fixture.json",
        {
            "collection": "drift_check",
            "profile": "POLICY",
            "queries": [
                {"question": "KMS-401 AES-256 database backups", "relevant_ids": [p1]},
                {"question": "parental leave weeks paid", "relevant_ids": [p2]},
            ],
        },
    )

    before_hashes = _snapshot_tree_hashes(tmp_persist_dir)
    first: EvalReport = evaluate(fixture_path, persist_dir=tmp_persist_dir, searcher=searcher)
    second: EvalReport = evaluate(fixture_path, persist_dir=tmp_persist_dir, searcher=searcher)
    after_hashes = _snapshot_tree_hashes(tmp_persist_dir)

    assert before_hashes == after_hashes
    assert first == second
    # Report must serialize and deserialize cleanly with string cutoff keys
    assert first == json.loads(json.dumps(first))

    # Validate runtime shape compatibility with TypedDict symbols exported by docpipe_maestro.eval
    cfg: EvalConfig = first["config"]
    agg: EvalMetricsSummary = first["aggregate"]
    pq: PerQueryResult = first["per_query"][0]
    q_sample: EvalQuery = {"question": "q", "relevant_ids": ["r"]}
    assert cfg["embed_model"] == DEFAULT_EMBED_MODEL
    assert agg["num_queries"] == 2
    assert len(pq["retrieved_ids"]) == len(pq["retrieved_scores"])
    assert q_sample["question"] == "q"


def _strip_persist_dir(report: dict[str, Any]) -> dict[str, Any]:
    """Return report copy excluding ephemeral runtime ``persist_dir`` path."""
    copied = json.loads(json.dumps(report))
    copied["config"].pop("persist_dir", None)
    return dict(copied)


def test_curated_policy_suite_and_baseline_replay(
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from docpipe_maestro.cli import main as cli_main

    repo_root = Path(__file__).resolve().parent.parent
    fixture_path = repo_root / "tests" / "fixtures" / "eval_policy_corpus.json"
    policy_dir = repo_root / "tests" / "fixtures" / "policy_corpus"
    eval_dir = repo_root / "tests" / "fixtures" / "eval_corpus"
    baseline_path = repo_root / "docs" / "eval-baseline.json"

    loaded = load_eval_fixture(fixture_path)
    queries = loaded["queries"]
    assert len(queries) >= 20
    questions = [q["question"] for q in queries]
    assert len(questions) == len(set(questions))

    categories = [q["notes"] for q in queries]
    assert set(categories) >= {
        "direct_lookup",
        "paraphrased",
        "exact_identifier",
        "rule_and_exception",
    }
    assert categories.count("rule_and_exception") >= 3

    ingest(policy_dir, profile="POLICY", collection="eval_policy", persist_dir=tmp_persist_dir)
    ingest(eval_dir, profile="POLICY", collection="eval_policy", persist_dir=tmp_persist_dir)

    st = status(collection="eval_policy", persist_dir=tmp_persist_dir)
    committed_parent_ids = {pid for rec in st.sources for pid in rec.parent_ids}
    for query in queries:
        for rel_id in query["relevant_ids"]:
            assert rel_id in committed_parent_ids, f"Missing parent section ID {rel_id!r}"

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert baseline["schema_version"] == 1
    assert baseline["collection"] == "eval_policy"
    assert baseline["profile"] == "POLICY"
    assert baseline["k_values"] == [1, 3, 5, 10]

    for mode in ("default", "fts5_hybrid"):
        recorded = baseline["modes"][mode]
        assert recorded["config"]["persist_dir"] == ".docpipe"
        replayed = evaluate(fixture_path, persist_dir=tmp_persist_dir, searcher=mode)
        assert _strip_persist_dir(dict(replayed)) == _strip_persist_dir(recorded)

    # CLI end-to-end replay matches committed default baseline with zero storage drift
    before_hashes = _snapshot_tree_hashes(tmp_persist_dir)
    rc = cli_main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(fixture_path),
            "--json",
        ]
    )
    assert rc == 0
    assert _snapshot_tree_hashes(tmp_persist_dir) == before_hashes
    cli_report = json.loads(capsys.readouterr().out)
    assert _strip_persist_dir(cli_report) == _strip_persist_dir(baseline["modes"]["default"])

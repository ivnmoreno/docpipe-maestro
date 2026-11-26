"""Verification tests for the EvalForge Maestro CI/release integration assets."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.conftest import deterministic_embed as conftest_deterministic_embed

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALFORGE_DIR = REPO_ROOT / "evalforge"
OFFLINE_CONFIG = EVALFORGE_DIR / "evalforge-offline.toml"
LIVE_CONFIG = EVALFORGE_DIR / "evalforge-live.toml"
CALIBRATION_SAMPLES = EVALFORGE_DIR / "calibration-samples.jsonl"
RUN_GATE_SCRIPT = EVALFORGE_DIR / "run_gate.py"
POLICY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "eval_policy_corpus.json"
EVALFORGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "evalforge.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _load_run_gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docpipe_evalforge_run_gate", RUN_GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_forbidden_secret_keys(mapping: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key, value in mapping.items():
        if "api_key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
            found.append(key)
        if isinstance(value, dict):
            found.extend(f"{key}.{nested}" for nested in _has_forbidden_secret_keys(value))
    return found


def test_evalforge_configs_parse_cleanly_without_hardcoded_secrets() -> None:
    offline = tomllib.loads(OFFLINE_CONFIG.read_text(encoding="utf-8"))
    live = tomllib.loads(LIVE_CONFIG.read_text(encoding="utf-8"))

    for cfg in (offline, live):
        assert _has_forbidden_secret_keys(cfg) == []
        assert cfg["target"]["type"] == "docpipe"
        assert cfg["target"]["docpipe_collection"] == "eval_policy"
        assert cfg["target"]["docpipe_searcher"] == "fts5_hybrid"
        assert cfg["security"]["local_only"] is True
        assert cfg["run"]["strict"] is True

    assert offline["target"]["docpipe_mode"] == "retrieve"
    assert offline["metrics"]["enabled"] == [
        "precision_at_k",
        "recall_at_k",
        "mrr",
        "ndcg_at_k",
    ]
    assert offline["gate"]["max_inconclusive_rate"] == 0.0
    assert set(offline["gate"]["min_metric_scores"]) == {
        "precision_at_k",
        "recall_at_k",
        "mrr",
        "ndcg_at_k",
    }

    assert live["target"]["docpipe_mode"] == "answer_detailed"
    assert live["security"]["block_pii"] is True
    assert set(live["gate"]["min_metric_scores"]) == {
        "precision_at_k",
        "recall_at_k",
        "mrr",
        "ndcg_at_k",
    }


def test_evalforge_calibration_samples_grounded_in_policy_corpus() -> None:
    fixture = json.loads(POLICY_FIXTURE.read_text(encoding="utf-8"))
    known_parent_ids = {rel_id for query in fixture["queries"] for rel_id in query["relevant_ids"]}

    raw_lines = [
        line.strip()
        for line in CALIBRATION_SAMPLES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(raw_lines) >= 6

    seen_ids: set[str] = set()
    passed_flags: list[bool] = []
    for raw_line in raw_lines:
        record = json.loads(raw_line)
        case_id = record["case_id"]
        assert isinstance(case_id, str) and case_id
        assert case_id not in seen_ids
        seen_ids.add(case_id)

        human_score = record["human_score"]
        assert isinstance(human_score, (int, float))
        assert 0.0 <= float(human_score) <= 1.0
        assert isinstance(record["human_passed"], bool)
        passed_flags.append(record["human_passed"])

        chunks = record["retrieved_chunks"]
        assert isinstance(chunks, list) and chunks
        for chunk in chunks:
            assert chunk["id"] in known_parent_ids
            assert isinstance(chunk["text"], str) and chunk["text"].strip()

    assert any(passed_flags)
    assert any(not flag for flag in passed_flags)


def test_evalforge_runner_helpers_match_conftest_and_detect_drift(tmp_path: Path) -> None:
    run_gate = _load_run_gate_module()

    sample_texts = [
        "Control SEC-101 AES-256 KMS-401 encryption requirements",
        "Full-time employees are entitled to 20 days of paid annual leave",
        "",
    ]
    assert run_gate.deterministic_embed(sample_texts) == conftest_deterministic_embed(sample_texts)

    probe_dir = tmp_path / "persist"
    probe_dir.mkdir()
    target_file = probe_dir / "manifest.json"
    target_file.write_text('{"version": 1}', encoding="utf-8")

    before = run_gate.snapshot_tree_hashes(probe_dir)
    assert before == run_gate.snapshot_tree_hashes(probe_dir)

    target_file.write_text('{"version": 2}', encoding="utf-8")
    after = run_gate.snapshot_tree_hashes(probe_dir)
    assert before != after


def test_evalforge_workflows_pin_version_and_gate_releases() -> None:
    evalforge_wf = EVALFORGE_WORKFLOW.read_text(encoding="utf-8")
    release_wf = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert '"evalforge-maestro==0.4.0"' in evalforge_wf
    assert "evalforge/run_gate.py offline" in evalforge_wf
    assert "evalforge/run_gate.py live" in evalforge_wf
    assert "GITHUB_STEP_SUMMARY" in evalforge_wf
    # Ensure workflow_dispatch inputs bind via env:, never interpolated directly.
    for line in evalforge_wf.splitlines():
        stripped = line.strip()
        if stripped.startswith("args") or stripped.startswith("/tmp/evalforge"):
            assert "${{ inputs." not in stripped

    assert '"evalforge-maestro==0.4.0"' in release_wf
    assert "evalforge-gate:" in release_wf
    assert "evalforge/run_gate.py offline" in release_wf
    assert "needs: [verify-and-build, evalforge-gate]" in release_wf
    assert "needs: [verify-and-build, evalforge-gate, verify-testpypi]" in release_wf
    assert "needs: [verify-and-build, evalforge-gate, publish-pypi]" in release_wf


def test_evalforge_offline_gate_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("evalforge_maestro")
    run_gate = _load_run_gate_module()

    output_dir = tmp_path / "artifacts"
    rc = run_gate.main(["offline", "--output-dir", str(output_dir)])
    assert rc == 0

    retrieval_report = json.loads(
        (output_dir / "retrieval-report.json").read_text(encoding="utf-8")
    )
    calibration_report = json.loads(
        (output_dir / "calibration-report.json").read_text(encoding="utf-8")
    )

    assert (output_dir / "retrieval-report.md").is_file()
    assert (output_dir / "calibration-report.md").is_file()

    assert retrieval_report["gate"]["decision"] == "PASS"
    assert retrieval_report["evaluation"]["evaluated_case_count"] == 24
    agg = retrieval_report["evaluation"]["aggregates"]
    assert agg["precision_at_k"]["mean_score"] >= 0.83
    assert agg["recall_at_k"]["mean_score"] >= 0.95
    assert agg["mrr"]["mean_score"] >= 0.90
    assert agg["ndcg_at_k"]["mean_score"] >= 0.90

    assert calibration_report["calibration"]["exact_agreement_rate"] >= 80.0
    assert calibration_report["calibration_gate"]["passed"] is True

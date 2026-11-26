"""EvalForge Maestro quality and judge-calibration gate runner for docpipe-maestro.

Runs either:
- ``offline``: deterministic zero-network CI/release gate indexing the 5 policy
  documents with docpipe-maestro's 64-D deterministic bag-of-words embedder
  (matching ``docs/eval-baseline.md``), executing real ``DocpipeAdapter`` hybrid
  retrieval over all 24 curated queries, asserting zero Phase-2 persistence
  drift, and running offline mock judge calibration.
- ``live``: optional manual live-model gate using real embeddings, optional
  cross-encoder reranking, and live LLM generation/judging configured solely via
  CLI flags and environment variables (zero hardcoded credentials).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OFFLINE_CONFIG = REPO_ROOT / "evalforge" / "evalforge-offline.toml"
DEFAULT_LIVE_CONFIG = REPO_ROOT / "evalforge" / "evalforge-live.toml"
DEFAULT_CALIBRATION_SAMPLES = REPO_ROOT / "evalforge" / "calibration-samples.jsonl"
DEFAULT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "eval_policy_corpus.json"
DEFAULT_POLICY_CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "policy_corpus"
DEFAULT_EVAL_CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "eval_corpus"

EMBED_DIM = 64
_WORD_RE = re.compile(r"[a-z0-9]+")


def deterministic_embed(texts: Sequence[str], dim: int = EMBED_DIM) -> list[list[float]]:
    """Compute deterministic L2-normalized bag-of-words embeddings matching tests/conftest.py."""
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


def snapshot_tree_hashes(root: Path) -> dict[str, str]:
    """Return sorted relative-path SHA-256 digests for every file under ``root``."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@contextlib.contextmanager
def offline_deterministic_embeddings() -> Iterator[None]:
    """Temporarily patch ``litellm.embedding`` with the deterministic offline embedder."""
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    import litellm

    original_embedding = litellm.embedding

    def _fake_embedding(*, model: str, input: list[str], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        dim = 32 if "small" in model else EMBED_DIM
        vecs = deterministic_embed(input, dim=dim)
        return {
            "data": [{"index": idx, "embedding": vec} for idx, vec in enumerate(vecs)],
            "model": model,
        }

    litellm.embedding = _fake_embedding
    try:
        yield
    finally:
        litellm.embedding = original_embedding


def export_docpipe_fixture_to_jsonl(
    fixture_path: Path,
    output_jsonl: Path,
    *,
    dataset_id: str,
    dataset_version: str = "1.0.0",
) -> int:
    """Convert ``eval_policy_corpus.json`` into an EvalForge JSONL dataset via native importer."""
    from evalforge_maestro import load_docpipe_fixture

    engine = load_docpipe_fixture(
        fixture_path,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
    )
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for case in engine.iter_cases():
            payload = case.model_dump(mode="json", exclude_none=True)
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            count += 1
    return count


def _ingest_policy_corpus(
    persist_dir: Path,
    *,
    collection: str = "eval_policy",
    embed_model: str | None = None,
    local_only: bool = True,
) -> None:
    """Ingest the 5 curated policy Markdown documents into ``persist_dir``."""
    from docpipe_maestro import ingest

    kwargs: dict[str, Any] = {
        "profile": "POLICY",
        "collection": collection,
        "persist_dir": persist_dir,
        "local_only": local_only,
    }
    if embed_model is not None:
        kwargs["embed_model"] = embed_model

    ingest(DEFAULT_POLICY_CORPUS_DIR, **kwargs)
    ingest(DEFAULT_EVAL_CORPUS_DIR, **kwargs)


def _invoke_evalforge(
    argv: Sequence[str],
    *,
    env_overrides: dict[str, str] | None = None,
) -> int:
    """Invoke the installed EvalForge Maestro CLI entrypoint and return its POSIX exit code."""
    from evalforge_maestro.cli import main as evalforge_main

    if not env_overrides:
        return int(evalforge_main(list(argv)))

    saved: dict[str, str | None] = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)
    try:
        return int(evalforge_main(list(argv)))
    finally:
        for key, prev in saved.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


def _run_offline_gate(args: argparse.Namespace) -> int:
    """Execute deterministic offline config, retrieval, drift, and calibration gates."""
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    offline_config = Path(args.config).resolve()
    live_config = Path(args.live_config).resolve()
    calibration_samples = Path(args.calibration_samples).resolve()
    fixture_path = Path(args.fixture).resolve()

    for cfg in (offline_config, live_config):
        rc = _invoke_evalforge(["config", "validate", "--config", str(cfg), "--quiet"])
        if rc != 0:
            print(f"[evalforge-gate] config validate failed for {cfg} (exit={rc})", file=sys.stderr)
            return rc

    with tempfile.TemporaryDirectory(prefix="docpipe-evalforge-") as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        persist_dir = tmp_root / ".docpipe"
        storage_dir = tmp_root / ".evalforge"
        dataset_jsonl = tmp_root / "eval_policy_corpus.jsonl"

        case_count = export_docpipe_fixture_to_jsonl(
            fixture_path,
            dataset_jsonl,
            dataset_id="docpipe-eval-policy",
            dataset_version="1.0.0",
        )
        print(f"[evalforge-gate] Exported {case_count} cases from {fixture_path.name}")

        retrieval_json = output_dir / "retrieval-report.json"
        retrieval_md = output_dir / "retrieval-report.md"

        with offline_deterministic_embeddings():
            _ingest_policy_corpus(persist_dir, collection="eval_policy", local_only=True)
            before_hashes = snapshot_tree_hashes(persist_dir)

            rc = _invoke_evalforge(
                [
                    "run",
                    "--config",
                    str(offline_config),
                    "--dataset",
                    str(dataset_jsonl),
                    "--docpipe-persist-dir",
                    str(persist_dir),
                    "--storage-dir",
                    str(storage_dir),
                    "--local-only",
                    "--strict",
                    "--quiet",
                    "--json-out",
                    str(retrieval_json),
                    "--markdown-out",
                    str(retrieval_md),
                ]
            )

            after_hashes = snapshot_tree_hashes(persist_dir)

        if rc != 0:
            print(f"[evalforge-gate] Retrieval quality gate failed (exit={rc})", file=sys.stderr)
            return rc

        if before_hashes != after_hashes:
            print(
                "[evalforge-gate] Phase 2 persistence drift detected in .docpipe during retrieval!",
                file=sys.stderr,
            )
            return 1

        calibration_json = output_dir / "calibration-report.json"
        calibration_md = output_dir / "calibration-report.md"

        cal_rc = _invoke_evalforge(
            [
                "calibrate",
                "--samples",
                str(calibration_samples),
                "--metric",
                "groundedness",
                "--min-agreement",
                str(args.min_agreement),
                "--mock",
                "--local-only",
                "--strict",
                "--quiet",
                "--storage-dir",
                str(storage_dir),
                "--json-out",
                str(calibration_json),
                "--markdown-out",
                str(calibration_md),
            ]
        )
        if cal_rc != 0:
            print(
                f"[evalforge-gate] Judge calibration gate failed (exit={cal_rc})",
                file=sys.stderr,
            )
            return cal_rc

    report_data = json.loads(retrieval_json.read_text(encoding="utf-8"))
    cal_data = json.loads(calibration_json.read_text(encoding="utf-8"))
    evaluation = report_data.get("evaluation", {})
    agg = evaluation.get("aggregates", {})
    cal_summary = cal_data.get("calibration", {})
    print(
        "[evalforge-gate] PASS | "
        f"cases={evaluation.get('evaluated_case_count')} | "
        f"P@1={agg.get('precision_at_k', {}).get('mean_score')} | "
        f"R@3={agg.get('recall_at_k', {}).get('mean_score')} | "
        f"MRR={agg.get('mrr', {}).get('mean_score')} | "
        f"NDCG@3={agg.get('ndcg_at_k', {}).get('mean_score')} | "
        f"cal_agreement={cal_summary.get('exact_agreement_rate')}% | "
        "phase2_drift=0B"
    )
    return 0


def _run_live_gate(args: argparse.Namespace) -> int:
    """Execute manual/local live-model ingestion, EvalForge run, and optional calibration."""
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    live_config = Path(args.config).resolve()
    fixture_path = Path(args.fixture).resolve()
    calibration_samples = Path(args.calibration_samples).resolve()

    rc = _invoke_evalforge(["config", "validate", "--config", str(live_config), "--quiet"])
    if rc != 0:
        print(
            f"[evalforge-live] config validate failed for {live_config} (exit={rc})",
            file=sys.stderr,
        )
        return rc

    with tempfile.TemporaryDirectory(prefix="docpipe-evalforge-live-") as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        persist_dir = tmp_root / ".docpipe"
        storage_dir = tmp_root / ".evalforge"
        dataset_jsonl = tmp_root / "eval_policy_corpus.jsonl"

        case_count = export_docpipe_fixture_to_jsonl(
            fixture_path,
            dataset_jsonl,
            dataset_id="docpipe-eval-policy-live",
            dataset_version="1.0.0",
        )
        print(f"[evalforge-live] Exported {case_count} cases from {fixture_path.name}")

        _ingest_policy_corpus(
            persist_dir,
            collection="eval_policy",
            embed_model=args.docpipe_embed_model,
            local_only=args.local_only,
        )

        run_argv: list[str] = [
            "run",
            "--config",
            str(live_config),
            "--dataset",
            str(dataset_jsonl),
            "--docpipe-persist-dir",
            str(persist_dir),
            "--docpipe-mode",
            args.docpipe_mode,
            "--docpipe-searcher",
            args.docpipe_searcher,
            "--storage-dir",
            str(storage_dir),
            "--strict",
            "--quiet",
            "--json-out",
            str(output_dir / "live-report.json"),
            "--markdown-out",
            str(output_dir / "live-report.md"),
        ]
        if args.docpipe_embed_model:
            run_argv.extend(["--docpipe-embed-model", args.docpipe_embed_model])
        if args.docpipe_rerank:
            run_argv.append("--docpipe-rerank")
        if args.docpipe_mode == "retrieve":
            run_argv.extend(
                [
                    "--metric",
                    "precision_at_k:k=1",
                    "--metric",
                    "recall_at_k:k=3",
                    "--metric",
                    "mrr",
                    "--metric",
                    "ndcg_at_k:k=3",
                ]
            )
        else:
            if args.docpipe_answer_model:
                run_argv.extend(["--docpipe-answer-model", args.docpipe_answer_model])
            if args.docpipe_api_base:
                run_argv.extend(["--docpipe-api-base", args.docpipe_api_base])
            if args.judge_model:
                run_argv.extend(["--judge-model", args.judge_model])
            if args.judge_api_base:
                run_argv.extend(["--judge-api-base", args.judge_api_base])

        env_overrides = {"EVALFORGE_LOCAL_ONLY": "true" if args.local_only else "false"}
        if args.local_only:
            run_argv.append("--local-only")

        rc = _invoke_evalforge(run_argv, env_overrides=env_overrides)
        if rc != 0:
            print(f"[evalforge-live] Live evaluation gate failed (exit={rc})", file=sys.stderr)
            return rc

        if args.run_calibration:
            cal_argv: list[str] = [
                "calibrate",
                "--samples",
                str(calibration_samples),
                "--metric",
                "groundedness",
                "--min-agreement",
                str(args.min_agreement),
                "--strict",
                "--quiet",
                "--storage-dir",
                str(storage_dir),
                "--json-out",
                str(output_dir / "live-calibration-report.json"),
                "--markdown-out",
                str(output_dir / "live-calibration-report.md"),
            ]
            if args.judge_model:
                cal_argv.extend(["--judge-model", args.judge_model])
            if args.judge_api_base:
                cal_argv.extend(["--judge-api-base", args.judge_api_base])
            if args.local_only:
                cal_argv.append("--local-only")

            cal_rc = _invoke_evalforge(cal_argv, env_overrides=env_overrides)
            if cal_rc != 0:
                print(
                    f"[evalforge-live] Live calibration gate failed (exit={cal_rc})",
                    file=sys.stderr,
                )
                return cal_rc

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for ``evalforge/run_gate.py``."""
    parser = argparse.ArgumentParser(
        description="Run EvalForge Maestro quality & judge-calibration gates for docpipe-maestro."
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_off = sub.add_parser("offline", help="Run deterministic zero-network CI/release gate.")
    p_off.add_argument("--config", default=str(DEFAULT_OFFLINE_CONFIG))
    p_off.add_argument("--live-config", default=str(DEFAULT_LIVE_CONFIG))
    p_off.add_argument("--fixture", default=str(DEFAULT_FIXTURE_PATH))
    p_off.add_argument("--calibration-samples", default=str(DEFAULT_CALIBRATION_SAMPLES))
    p_off.add_argument("--min-agreement", type=float, default=80.0)
    p_off.add_argument("--output-dir", default="evalforge-artifacts")

    p_live = sub.add_parser("live", help="Run live-model evaluation gate via explicit inputs.")
    p_live.add_argument("--config", default=str(DEFAULT_LIVE_CONFIG))
    p_live.add_argument("--fixture", default=str(DEFAULT_FIXTURE_PATH))
    p_live.add_argument("--calibration-samples", default=str(DEFAULT_CALIBRATION_SAMPLES))
    p_live.add_argument(
        "--docpipe-mode",
        choices=("retrieve", "answer_detailed"),
        default="answer_detailed",
    )
    p_live.add_argument(
        "--docpipe-searcher",
        choices=("fts5_hybrid", "default"),
        default="fts5_hybrid",
    )
    p_live.add_argument("--docpipe-rerank", action="store_true")
    p_live.add_argument("--docpipe-embed-model", default="ollama/nomic-embed-text")
    p_live.add_argument("--docpipe-answer-model", default="ollama/llama3.2")
    p_live.add_argument("--docpipe-api-base", default=None)
    p_live.add_argument("--judge-model", default="ollama/llama3.2")
    p_live.add_argument("--judge-api-base", default=None)
    p_live.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p_live.add_argument("--run-calibration", action="store_true")
    p_live.add_argument("--min-agreement", type=float, default=80.0)
    p_live.add_argument("--output-dir", default="evalforge-artifacts")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.mode == "offline":
        return _run_offline_gate(args)
    return _run_live_gate(args)


if __name__ == "__main__":
    raise SystemExit(main())

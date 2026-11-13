"""Command-line interface for docpipe-maestro (sole module permitted to read user config files)."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from docpipe_maestro import __version__, build_chat_messages
from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_PERSIST_DIR,
    DEFAULT_TOP_K,
)
from docpipe_maestro.embedder import DEFAULT_REQUEST_TIMEOUT
from docpipe_maestro.types import DocpipeError


def _load_cli_dotenv(config_path: str | None) -> None:
    """Load an optional ``.env`` strictly from the config directory or CWD (CLI only).

    Never walks upward into ancestor directories and never overwrites variables
    that are already present in the caller's environment.
    """
    base_dir = Path(config_path).parent if config_path else Path.cwd()
    env_path = base_dir / ".env"
    if env_path.is_file():
        load_dotenv(dotenv_path=env_path, override=False)


def _load_toml_config(config_path: str | None, *, no_config: bool = False) -> dict[str, Any]:
    """Load an optional TOML user configuration file (permitted in CLI only).

    When ``config_path`` is omitted and ``no_config`` is ``False``, checks strictly
    for ``docpipe.toml`` in the current working directory (never walking upward
    into parent directories). Supported keys include ``collection``, ``persist_dir``,
    ``embed_model``, ``model``, ``profile``, ``top_k``, ``threshold``, ``api_base``,
    ``temperature``, ``max_tokens``, ``timeout``, and ``fail_on_truncation``.
    Credentials must never be stored here; use environment variables or ``.env``.
    """
    if no_config:
        return {}
    if config_path is None:
        cwd_cfg = Path.cwd() / "docpipe.toml"
        if not cwd_cfg.is_file():
            return {}
        path = cwd_cfg
    else:
        path = Path(config_path)
        if not path.is_file():
            raise DocpipeError(f"Config file not found: {config_path}")
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return dict(data)


def _cfg_bool(cfg: dict[str, Any], key: str, fallback: bool) -> bool:
    """Validate and return a boolean configuration value from TOML defaults."""
    val = cfg.get(key)
    if val is None:
        return fallback
    if not isinstance(val, bool):
        raise DocpipeError(f"Invalid TOML config value for {key!r}: expected boolean")
    return val


def _cfg_opt_str(cfg: dict[str, Any], key: str) -> str | None:
    """Validate and return an optional string configuration value from TOML defaults."""
    val = cfg.get(key)
    if val is None:
        return None
    if not isinstance(val, str):
        raise DocpipeError(f"Invalid TOML config value for {key!r}: expected string")
    return val


def _cfg_str(cfg: dict[str, Any], key: str, fallback: str) -> str:
    """Validate and return a string configuration value from parsed TOML defaults."""
    val = _cfg_opt_str(cfg, key)
    return fallback if val is None else val


def _cfg_opt_int(cfg: dict[str, Any], key: str) -> int | None:
    """Validate and return an optional integer configuration value (rejecting booleans)."""
    val = cfg.get(key)
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise DocpipeError(f"Invalid TOML config value for {key!r}: expected integer")
    return val


def _cfg_int(cfg: dict[str, Any], key: str, fallback: int) -> int:
    """Validate and return an integer configuration value (rejecting booleans/lists)."""
    val = _cfg_opt_int(cfg, key)
    return fallback if val is None else val


def _cfg_opt_float(cfg: dict[str, Any], key: str) -> float | None:
    """Validate and return an optional finite float configuration value from TOML defaults."""
    val = cfg.get(key)
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
        raise DocpipeError(f"Invalid TOML config value for {key!r}: expected number")
    return float(val)


def build_parser(defaults: dict[str, Any] | None = None) -> argparse.ArgumentParser:
    """Construct the ``docpipe-maestro`` CLI parser with shared global options.

    Uses a hidden ``common`` parent parser on every subcommand so ``--config``,
    ``--collection``, and ``--persist-dir`` are accepted either before or after
    the subcommand name, with explicit CLI flags overriding TOML defaults.
    """
    cfg = defaults or {}
    default_collection = _cfg_str(cfg, "collection", DEFAULT_COLLECTION)
    default_persist_dir = _cfg_str(cfg, "persist_dir", DEFAULT_PERSIST_DIR)
    default_embed_model = _cfg_str(cfg, "embed_model", DEFAULT_EMBED_MODEL)
    default_gen_model = _cfg_str(cfg, "model", DEFAULT_GENERATION_MODEL)
    default_profile = _cfg_str(cfg, "profile", "DEFAULT")
    default_top_k = _cfg_int(cfg, "top_k", DEFAULT_TOP_K)
    default_threshold = _cfg_opt_float(cfg, "threshold")
    default_api_base = _cfg_opt_str(cfg, "api_base")
    default_temperature = _cfg_opt_float(cfg, "temperature")
    default_max_tokens = _cfg_opt_int(cfg, "max_tokens")
    toml_timeout = _cfg_opt_float(cfg, "timeout")
    default_timeout = DEFAULT_REQUEST_TIMEOUT if toml_timeout is None else toml_timeout
    default_fail_on_truncation = _cfg_bool(cfg, "fail_on_truncation", False)

    parser = argparse.ArgumentParser(
        prog="docpipe-maestro",
        description="Minimal, structure-aware RAG pipeline CLI.",
    )
    parser.add_argument("--version", action="version", version=f"docpipe-maestro {__version__}")
    parser.add_argument("--config", default=None, help="Optional TOML config file path")
    parser.add_argument(
        "--no-config",
        action="store_true",
        default=False,
        help="Ignore CWD docpipe.toml and --config TOML defaults",
    )
    parser.add_argument("--collection", default=default_collection, help="Target collection name")
    parser.add_argument("--persist-dir", default=default_persist_dir, help="Local store directory")

    # Shared parent parser so global flags work both before and after any subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=argparse.SUPPRESS, help="Optional TOML config file path"
    )
    common.add_argument(
        "--no-config",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Ignore CWD docpipe.toml and --config TOML defaults",
    )
    common.add_argument("--collection", default=argparse.SUPPRESS, help="Target collection name")
    common.add_argument("--persist-dir", default=argparse.SUPPRESS, help="Local store directory")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Phase 1: ingest
    p_ingest = subparsers.add_parser("ingest", parents=[common], help="Ingest a file or directory")
    p_ingest.add_argument("path", help="File or directory path to ingest")
    p_ingest.add_argument("--profile", default=default_profile, help="Chunking profile")
    p_ingest.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_ingest.add_argument("--force", action="store_true", help="Re-ingest even if hash unchanged")

    # Phase 1: sync
    p_sync = subparsers.add_parser(
        "sync", parents=[common], help="Reconcile a directory against the manifest"
    )
    p_sync.add_argument("directory", help="Directory path to synchronize")
    p_sync.add_argument("--profile", default=default_profile, help="Chunking profile")
    p_sync.add_argument("--embed-model", default=default_embed_model, help="Embedding model")

    # Phase 1/2: status
    p_status = subparsers.add_parser(
        "status", parents=[common], help="Inspect collection manifest status"
    )
    p_status.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    # Phase 1: remove
    p_remove = subparsers.add_parser(
        "remove", parents=[common], help="Remove a source document from the collection"
    )
    p_remove.add_argument("source", help="Source key to remove")

    # Phase 1: reindex
    p_reindex = subparsers.add_parser(
        "reindex", parents=[common], help="Re-embed collection under a new model"
    )
    p_reindex.add_argument("--model", required=True, help="New embedding provider/model string")

    # Phase 2: query
    p_query = subparsers.add_parser(
        "query", parents=[common], help="Retrieve relevant sections without generation"
    )
    p_query.add_argument("question", help="Question to search for")
    p_query.add_argument("--top-k", type=int, default=default_top_k, help="Max child matches")
    p_query.add_argument(
        "--threshold", type=float, default=default_threshold, help="Min similarity [0.0, 1.0]"
    )
    p_query.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_query.add_argument(
        "--expand-parent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Expand matched children to parent sections",
    )
    p_query.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=False,
        help="Emit structured JSON output with query context and retrieved records",
    )

    # Phase 2: ask
    p_ask = subparsers.add_parser(
        "ask", parents=[common], help="Generate a grounded answer for a question"
    )
    p_ask.add_argument("question", help="Question to answer")
    p_ask.add_argument("--top-k", type=int, default=default_top_k, help="Max child matches")
    p_ask.add_argument(
        "--threshold", type=float, default=default_threshold, help="Min similarity [0.0, 1.0]"
    )
    p_ask.add_argument("--model", default=default_gen_model, help="LLM provider/model")
    p_ask.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_ask.add_argument(
        "--api-base", default=default_api_base, help="Optional OpenAI-compatible base URL"
    )
    p_ask.add_argument(
        "--temperature",
        type=float,
        default=default_temperature,
        help="Sampling temperature (>= 0.0); omitted when unset",
    )
    p_ask.add_argument(
        "--max-tokens",
        type=int,
        default=default_max_tokens,
        help="Maximum completion tokens (>= 1); omitted when unset",
    )
    p_ask.add_argument(
        "--timeout",
        type=float,
        default=default_timeout,
        help=f"Completion timeout in seconds (default: {DEFAULT_REQUEST_TIMEOUT})",
    )
    p_ask.add_argument(
        "--fail-on-truncation",
        action="store_true",
        default=default_fail_on_truncation,
        help="Exit non-zero if completion stops due to token limit (finish_reason='length')",
    )
    p_ask.add_argument(
        "--show-context",
        action="store_true",
        default=False,
        help="Print retrieved context sections and similarity scores to stderr",
    )
    p_ask.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=False,
        help="Emit structured JSON with answer, truncation flag, token usage, and sources",
    )

    return parser


def _handle_ask(args: argparse.Namespace) -> int:
    """Execute the ``ask`` subcommand with timing, context inspection, and truncation warnings."""
    from docpipe_maestro.query.answer import answer_detailed
    from docpipe_maestro.query.retriever import retrieve

    t_ret = time.perf_counter()
    sections = retrieve(
        args.question,
        collection=args.collection,
        persist_dir=args.persist_dir,
        embed_model=args.embed_model,
        top_k=args.top_k,
        threshold=args.threshold,
        expand_parent=True,
    )
    retrieval_elapsed = time.perf_counter() - t_ret

    if args.show_context:
        if not sections:
            print("[Context] No matching sections retrieved.", file=sys.stderr)
        else:
            for idx, item in enumerate(sections, start=1):
                meta = item.metadata
                clause_info = f" | Clause: {meta['clause']}" if meta["clause"] else ""
                page_info = f" | Page: {meta['page']}" if meta["page"] is not None else ""
                print(
                    f"[Context {idx}] score={item.score:.4f} | Source: {meta['source']} | "
                    f"Section: {meta['section']}{clause_info}{page_info}",
                    file=sys.stderr,
                )

    messages = build_chat_messages(args.question, sections)
    gen = answer_detailed(
        messages,
        model=args.model,
        api_base=args.api_base,
        has_context=bool(sections),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        fail_on_truncation=args.fail_on_truncation,
    )

    if gen.truncated:
        print(
            f"Warning: Response for model {args.model!r} was truncated at token limit "
            "(finish_reason='length'). Increase or omit --max-tokens to get the full answer.",
            file=sys.stderr,
        )

    if args.as_json:
        print(
            json.dumps(
                {
                    "answer": gen.text,
                    "model": gen.model,
                    "truncated": gen.truncated,
                    "finish_reason": gen.finish_reason,
                    "usage": {
                        "prompt_tokens": gen.prompt_tokens,
                        "completion_tokens": gen.completion_tokens,
                        "reasoning_tokens": gen.reasoning_tokens,
                        "total_tokens": gen.total_tokens,
                    },
                    "elapsed_seconds": round(gen.elapsed_seconds, 4),
                    "retrieval_elapsed_seconds": round(retrieval_elapsed, 4),
                    "sources": [
                        {
                            "source": sec.metadata["source"],
                            "section": sec.metadata["section"],
                            "clause": sec.metadata["clause"],
                            "page": sec.metadata["page"],
                            "score": round(sec.score, 4),
                        }
                        for sec in sections
                    ],
                },
                indent=2,
            )
        )
    else:
        print(gen.text)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``docpipe-maestro`` CLI entry point and return a process exit code.

    Catches ``DocpipeError`` and ``ValueError`` exceptions, prints a clean
    single-line message to ``stderr``, and exits with status ``1`` instead of
    emitting an unhandled traceback.
    """
    arg_list = list(argv) if argv is not None else sys.argv[1:]
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    pre.add_argument("--no-config", action="store_true", default=False)
    known, _ = pre.parse_known_args(arg_list)

    try:
        effective_cfg = None if known.no_config else known.config
        _load_cli_dotenv(effective_cfg)
        cfg_defaults = _load_toml_config(known.config, no_config=known.no_config)
        parser = build_parser(cfg_defaults)
        args = parser.parse_args(arg_list)

        if args.command == "ingest":
            from docpipe_maestro.ingest.pipeline import ingest

            res = ingest(
                args.path,
                profile=args.profile,
                collection=args.collection,
                persist_dir=args.persist_dir,
                embed_model=args.embed_model,
                force=args.force,
            )
            print(
                f"Ingested {len(res.ingested)} file(s), skipped {len(res.skipped)} unchanged "
                f"({res.chunks_written} children, {res.parents_written} parents) "
                f"into collection '{res.collection}'."
            )
            return 0

        if args.command == "sync":
            from docpipe_maestro.ingest.pipeline import sync

            sres = sync(
                args.directory,
                profile=args.profile,
                collection=args.collection,
                persist_dir=args.persist_dir,
                embed_model=args.embed_model,
            )
            print(
                f"Synced '{sres.collection}': added={len(sres.added)}, "
                f"updated={len(sres.updated)}, skipped={len(sres.skipped)}, "
                f"removed={len(sres.removed)}."
            )
            return 0

        if args.command == "status":
            from docpipe_maestro.ingest.pipeline import status

            st = status(collection=args.collection, persist_dir=args.persist_dir)
            if args.as_json:
                print(
                    json.dumps(
                        {
                            "collection": st.collection,
                            "embed_model": st.embed_model,
                            "embed_dim": st.embed_dim,
                            "total_sources": st.total_sources,
                            "total_children": st.total_children,
                            "total_parents": st.total_parents,
                            "sources": [s.to_dict() for s in st.sources],
                        },
                        indent=2,
                    )
                )
            else:
                print(
                    f"Collection: {st.collection} | Model: {st.embed_model} "
                    f"(dim={st.embed_dim}) | Sources: {st.total_sources} | "
                    f"Children: {st.total_children} | Parents: {st.total_parents}"
                )
                for rec in st.sources:
                    print(
                        f"  - {rec.source} [{rec.doc_version}] "
                        f"({len(rec.chunk_ids)} children, {len(rec.parent_ids)} parents)"
                    )
            return 0

        if args.command == "remove":
            from docpipe_maestro.ingest.pipeline import remove

            removed = remove(
                args.source,
                collection=args.collection,
                persist_dir=args.persist_dir,
            )
            if not removed:
                print(f"Source not found in collection '{args.collection}': {args.source}")
                return 1
            print(f"Removed '{args.source}' from collection '{args.collection}'.")
            return 0

        if args.command == "reindex":
            from docpipe_maestro.ingest.pipeline import reindex

            count = reindex(
                embed_model=args.model,
                collection=args.collection,
                persist_dir=args.persist_dir,
            )
            print(
                f"Reindexed {count} child chunk(s) in collection '{args.collection}' "
                f"with model '{args.model}'."
            )
            return 0

        if args.command == "query":
            from docpipe_maestro.query.retriever import retrieve

            if args.threshold is not None and (
                not math.isfinite(args.threshold) or not 0.0 <= args.threshold <= 1.0
            ):
                raise ValueError("--threshold must be finite and between 0.0 and 1.0")

            results = retrieve(
                args.question,
                collection=args.collection,
                persist_dir=args.persist_dir,
                embed_model=args.embed_model,
                top_k=args.top_k,
                threshold=args.threshold,
                expand_parent=args.expand_parent,
            )
            if args.as_json:
                print(
                    json.dumps(
                        {
                            "query": args.question,
                            "collection": args.collection,
                            "expand_parent": args.expand_parent,
                            "results": [
                                {
                                    "id": item.id,
                                    "parent_id": item.parent_id,
                                    "score": float(item.score),
                                    "text": item.text,
                                    "metadata": dict(item.metadata),
                                }
                                for item in results
                            ],
                        },
                        indent=2,
                    )
                )
                return 0
            if not results:
                print("No matching sections found.")
                return 0
            for idx, item in enumerate(results, start=1):
                meta = item.metadata
                page_info = f" | Page: {meta['page']}" if meta["page"] is not None else ""
                print(
                    f"[{idx}] score={item.score:.4f} | Source: {meta['source']} | "
                    f"Section: {meta['section']}{page_info}"
                )
                print(item.text)
                print("-" * 60)
            return 0

        if args.command == "ask":
            return _handle_ask(args)
    except (DocpipeError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

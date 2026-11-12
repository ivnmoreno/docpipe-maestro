"""Command-line interface for docpipe-maestro (sole module permitted to read user config files)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from docpipe_maestro import (
    __version__,
    answer,
    build_prompt,
    ingest,
    reindex,
    remove,
    retrieve,
    status,
    sync,
)
from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_PERSIST_DIR,
    DEFAULT_TOP_K,
)
from docpipe_maestro.types import DocpipeError


def _load_toml_config(config_path: str | None) -> dict[str, Any]:
    """Load an optional TOML user configuration file (CLI-only)."""
    if config_path is None:
        return {}
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


def build_parser(defaults: dict[str, Any] | None = None) -> argparse.ArgumentParser:
    """Construct the docpipe CLI argument parser."""
    cfg = defaults or {}
    default_collection = str(cfg.get("collection", DEFAULT_COLLECTION))
    default_persist_dir = str(cfg.get("persist_dir", DEFAULT_PERSIST_DIR))
    default_embed_model = str(cfg.get("embed_model", DEFAULT_EMBED_MODEL))
    default_gen_model = str(cfg.get("model", DEFAULT_GENERATION_MODEL))
    default_profile = str(cfg.get("profile", "DEFAULT"))
    default_top_k = int(cfg.get("top_k", DEFAULT_TOP_K))
    raw_threshold = cfg.get("threshold")
    default_threshold: float | None = float(raw_threshold) if raw_threshold is not None else None

    parser = argparse.ArgumentParser(
        prog="docpipe",
        description="Minimal, structure-aware RAG pipeline CLI.",
    )
    parser.add_argument("--version", action="version", version=f"docpipe-maestro {__version__}")
    parser.add_argument("--config", default=None, help="Optional TOML config file path")
    parser.add_argument("--collection", default=default_collection, help="Target collection name")
    parser.add_argument("--persist-dir", default=default_persist_dir, help="Local store directory")

    # Shared parent parser so global flags work both before and after any subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=argparse.SUPPRESS, help="Optional TOML config file path"
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
    p_ask.add_argument("--api-base", default=None, help="Optional OpenAI-compatible base URL")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    arg_list = list(argv) if argv is not None else sys.argv[1:]
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    known, _ = pre.parse_known_args(arg_list)

    try:
        cfg_defaults = _load_toml_config(known.config)
        parser = build_parser(cfg_defaults)
        args = parser.parse_args(arg_list)

        if args.command == "ingest":
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
            results = retrieve(
                args.question,
                collection=args.collection,
                persist_dir=args.persist_dir,
                embed_model=args.embed_model,
                top_k=args.top_k,
                threshold=args.threshold,
                expand_parent=args.expand_parent,
            )
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
            sections = retrieve(
                args.question,
                collection=args.collection,
                persist_dir=args.persist_dir,
                embed_model=args.embed_model,
                top_k=args.top_k,
                threshold=args.threshold,
                expand_parent=True,
            )
            prompt = build_prompt(args.question, sections)
            reply = answer(
                prompt,
                model=args.model,
                api_base=args.api_base,
                has_context=bool(sections),
            )
            print(reply)
            return 0
    except (DocpipeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

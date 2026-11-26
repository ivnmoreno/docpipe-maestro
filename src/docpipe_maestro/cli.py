"""Command-line interface for docpipe-maestro (sole module permitted to read user config files)."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from dotenv import load_dotenv

from docpipe_maestro import __version__, build_chat_messages
from docpipe_maestro.config import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBED_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_PERSIST_DIR,
    DEFAULT_RERANK_TOP_N,
    DEFAULT_TOP_K,
)
from docpipe_maestro.embedder import DEFAULT_REQUEST_TIMEOUT
from docpipe_maestro.log import JsonFormatter, TextFormatter, correlation_id, get_logger
from docpipe_maestro.types import DocpipeError

if TYPE_CHECKING:
    from docpipe_maestro.types import EvalReport, PiiPolicy


def _load_cli_dotenv(config_path: str | None) -> None:
    """Load an optional ``.env`` strictly from the config directory or CWD (CLI only).

    Never walks upward into ancestor directories and never overwrites variables
    that are already present in the caller's environment.
    """
    base_dir = Path(config_path).parent if config_path else Path.cwd()
    env_path = base_dir / ".env"
    if env_path.is_file():
        load_dotenv(dotenv_path=env_path, override=False)


def _parse_toml_file(path: Path) -> dict[str, Any]:
    """Parse a TOML file into a top-level dictionary (CLI boundary only)."""
    import tomllib

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return dict(data)


def _load_toml_config(config_path: str | None, *, no_config: bool = False) -> dict[str, Any]:
    """Load an optional TOML user configuration file (permitted in CLI only).

    When ``config_path`` is omitted and ``no_config`` is ``False``, checks strictly
    for ``docpipe.toml`` in the current working directory (never walking upward
    into parent directories). Supported keys include ``collection``, ``persist_dir``,
    ``embed_model``, ``model``, ``profile``, ``top_k``, ``threshold``, ``searcher``,
    ``rerank``, ``reranker``, ``rerank_top_n``, ``api_base``, ``temperature``,
    ``max_tokens``, ``timeout``, ``fail_on_truncation``, ``local_only``, and
    ``pii_policy``. Credentials must never be stored here; use environment
    variables or ``.env``.
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
    return _parse_toml_file(path)


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


class _StoreExplicitPiiPolicy(argparse.Action):
    """Store ``--pii-policy`` path while recording explicit CLI flag presence."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        namespace._pii_policy_explicit = True


def _load_pii_policy_file(path: Path) -> PiiPolicy:
    """Parse and validate a JSON or TOML PII policy file (permitted in CLI only)."""
    if not path.is_file():
        raise DocpipeError(f"PII policy file not found: {path}")

    raw: Any
    try:
        if path.suffix.lower() in {".toml", ".tml"}:
            raw = _parse_toml_file(path)
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DocpipeError(f"Invalid or unreadable PII policy file {path.name}: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ValueError("PII policy file must decode to a JSON or TOML object")

    payload_dict = dict(raw)
    if list(payload_dict.keys()) == ["pii_policy"] and isinstance(
        payload_dict["pii_policy"], Mapping
    ):
        payload_dict = dict(payload_dict["pii_policy"])

    from docpipe_maestro._pii import validate_pii_policy

    validate_pii_policy(cast("PiiPolicy", payload_dict))
    return cast("PiiPolicy", payload_dict)


def _resolve_cli_pii_policy(
    args: argparse.Namespace,
    cfg_defaults: Mapping[str, Any],
    *,
    config_dir: Path,
) -> PiiPolicy | None:
    """Enforce CLI subcommand policy rules and resolve JSON/TOML/config policies."""
    allowed_commands = {"ingest", "sync", "ask"}
    if getattr(args, "_pii_policy_explicit", False) and args.command not in allowed_commands:
        raise ValueError(
            f"--pii-policy is only supported for ingest, sync, and ask (got {args.command!r})"
        )
    if args.command not in allowed_commands:
        return None

    if args.pii_policy is not None:
        return _load_pii_policy_file(Path(args.pii_policy))

    cfg_val = cfg_defaults.get("pii_policy")
    if cfg_val is None:
        return None
    if isinstance(cfg_val, str):
        candidate = Path(cfg_val)
        if not candidate.is_absolute() and not candidate.is_file():
            rel_cfg = config_dir / candidate
            if rel_cfg.is_file():
                candidate = rel_cfg
        return _load_pii_policy_file(candidate)
    if isinstance(cfg_val, Mapping):
        from docpipe_maestro._pii import validate_pii_policy

        cfg_policy = dict(cfg_val)
        validate_pii_policy(cast("PiiPolicy", cfg_policy))
        return cast("PiiPolicy", cfg_policy)
    raise DocpipeError("Invalid TOML config value for 'pii_policy': expected path string or table")


class _StoreExplicitCollection(argparse.Action):
    """Store ``--collection`` value while recording explicit CLI flag presence."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        namespace._collection_explicit = True


def _add_where_arg(subparser: argparse.ArgumentParser) -> None:
    """Register repeatable ``--where KEY=VALUE`` metadata filter argument."""
    subparser.add_argument(
        "--where",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help=(
            "Filter retrieval by metadata attribute (repeatable; e.g., "
            "--where source=policy.md, --where page=2, --where profile=POLICY)"
        ),
    )


def _add_html_report_arg(subparser: argparse.ArgumentParser) -> None:
    """Register optional ``--html-report PATH`` static HTML audit report export flag."""
    subparser.add_argument(
        "--html-report",
        default=None,
        metavar="PATH",
        help="Write a self-contained static HTML Document Integrity & Chunk Audit Report",
    )


def _add_rerank_args(
    subparser: argparse.ArgumentParser,
    *,
    default_rerank: bool,
    default_reranker: str,
    default_rerank_top_n: int,
) -> None:
    """Attach shared cross-encoder reranking CLI flags to a retrieval subparser."""
    subparser.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        default=default_rerank,
        help="Apply second-stage reranking before returning top_k results",
    )
    subparser.add_argument(
        "--reranker",
        default=default_reranker,
        help="Registered reranker strategy (default: cross_encoder)",
    )
    subparser.add_argument(
        "--rerank-top-n",
        type=int,
        default=default_rerank_top_n,
        help=(
            "Minimum candidate pool size fetched before reranking "
            f"(default: {DEFAULT_RERANK_TOP_N})"
        ),
    )


_LOG_LEVEL_CHOICES: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR")


def _add_logging_args(target: argparse.ArgumentParser, *, suppress_default: bool) -> None:
    """Register CLI-only telemetry flags on root and shared parent parsers."""
    target.add_argument(
        "--log-json",
        action="store_true",
        default=argparse.SUPPRESS if suppress_default else False,
        help="Emit single-line JSON stage telemetry to stderr (defaults to INFO severity)",
    )
    target.add_argument(
        "--log-level",
        type=str.upper,
        choices=_LOG_LEVEL_CHOICES,
        default=argparse.SUPPRESS if suppress_default else None,
        help="Enable telemetry on stderr at DEBUG, INFO, WARNING, or ERROR severity",
    )


@contextmanager
def _cli_logging_scope(*, log_json: bool, log_level: str | None) -> Iterator[None]:
    """Attach a transient stderr handler to ``docpipe_maestro`` during CLI dispatch."""
    if not log_json and log_level is None:
        yield
        return

    pkg_logger = get_logger()
    prev_level = pkg_logger.level
    effective_name = log_level if log_level is not None else "INFO"
    numeric_level = int(getattr(logging, effective_name))

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(numeric_level)
    handler.setFormatter(JsonFormatter() if log_json else TextFormatter())

    pkg_logger.setLevel(numeric_level)
    pkg_logger.addHandler(handler)
    try:
        yield
    finally:
        pkg_logger.removeHandler(handler)
        handler.close()
        pkg_logger.setLevel(prev_level)


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
    default_searcher = _cfg_str(cfg, "searcher", "default")
    default_rerank = _cfg_bool(cfg, "rerank", False)
    default_reranker = _cfg_str(cfg, "reranker", "cross_encoder")
    default_rerank_top_n = _cfg_int(cfg, "rerank_top_n", DEFAULT_RERANK_TOP_N)
    default_api_base = _cfg_opt_str(cfg, "api_base")
    default_temperature = _cfg_opt_float(cfg, "temperature")
    default_max_tokens = _cfg_opt_int(cfg, "max_tokens")
    toml_timeout = _cfg_opt_float(cfg, "timeout")
    default_timeout = DEFAULT_REQUEST_TIMEOUT if toml_timeout is None else toml_timeout
    default_fail_on_truncation = _cfg_bool(cfg, "fail_on_truncation", False)
    default_local_only = _cfg_bool(cfg, "local_only", False)

    parser = argparse.ArgumentParser(
        prog="docpipe-maestro",
        description="Minimal, structure-aware RAG pipeline CLI.",
    )
    parser.set_defaults(_collection_explicit=False, _pii_policy_explicit=False)
    parser.add_argument("--version", action="version", version=f"docpipe-maestro {__version__}")
    parser.add_argument("--config", default=None, help="Optional TOML config file path")
    parser.add_argument(
        "--no-config",
        action="store_true",
        default=False,
        help="Ignore CWD docpipe.toml and --config TOML defaults",
    )
    parser.add_argument(
        "--collection",
        action=_StoreExplicitCollection,
        default=default_collection,
        help="Target collection name",
    )
    parser.add_argument("--persist-dir", default=default_persist_dir, help="Local store directory")
    parser.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=default_local_only,
        help="Disallow non-local/non-loopback models and endpoints before network I/O",
    )
    parser.add_argument(
        "--pii-policy",
        action=_StoreExplicitPiiPolicy,
        default=None,
        help="Path to JSON or TOML PII policy config (supported by ingest, sync, ask)",
    )
    _add_logging_args(parser, suppress_default=False)

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
    common.add_argument(
        "--collection",
        action=_StoreExplicitCollection,
        default=argparse.SUPPRESS,
        help="Target collection name",
    )
    common.add_argument("--persist-dir", default=argparse.SUPPRESS, help="Local store directory")
    common.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Disallow non-local/non-loopback models and endpoints before network I/O",
    )
    _add_logging_args(common, suppress_default=True)

    # Parent parsers for --pii-policy: advertised on policy commands, cleanly rejected on others.
    pii_supported = argparse.ArgumentParser(add_help=False)
    pii_supported.add_argument(
        "--pii-policy",
        action=_StoreExplicitPiiPolicy,
        default=argparse.SUPPRESS,
        help="Path to JSON or TOML PII policy config",
    )
    pii_unsupported = argparse.ArgumentParser(add_help=False)
    pii_unsupported.add_argument(
        "--pii-policy",
        action=_StoreExplicitPiiPolicy,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Phase 1: ingest
    p_ingest = subparsers.add_parser(
        "ingest", parents=[common, pii_supported], help="Ingest a file or directory"
    )
    p_ingest.add_argument("path", help="File or directory path to ingest")
    p_ingest.add_argument("--profile", default=default_profile, help="Chunking profile")
    p_ingest.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_ingest.add_argument("--force", action="store_true", help="Re-ingest even if hash unchanged")
    _add_html_report_arg(p_ingest)

    # Phase 1: sync
    p_sync = subparsers.add_parser(
        "sync",
        parents=[common, pii_supported],
        help="Reconcile a directory against the manifest",
    )
    p_sync.add_argument("directory", help="Directory path to synchronize")
    p_sync.add_argument("--profile", default=default_profile, help="Chunking profile")
    p_sync.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes, tokens, and estimated cost without writing or embedding",
    )
    p_sync.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")
    _add_html_report_arg(p_sync)

    # Phase 1/2: status
    p_status = subparsers.add_parser(
        "status",
        parents=[common, pii_unsupported],
        help="Inspect collection manifest status",
    )
    p_status.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")
    _add_html_report_arg(p_status)

    # Phase 1: remove
    p_remove = subparsers.add_parser(
        "remove",
        parents=[common, pii_unsupported],
        help="Remove a source document from the collection",
    )
    p_remove.add_argument("source", help="Source key to remove")

    # Phase 1: reindex
    p_reindex = subparsers.add_parser(
        "reindex",
        parents=[common, pii_unsupported],
        help="Re-embed collection under a new model",
    )
    p_reindex.add_argument("--model", required=True, help="New embedding provider/model string")
    p_reindex.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview active chunks, tokens, and estimated cost without re-embedding",
    )
    p_reindex.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    # Phase 2: query
    p_query = subparsers.add_parser(
        "query",
        parents=[common, pii_unsupported],
        help="Retrieve relevant sections without generation",
    )
    p_query.add_argument("question", help="Question to search for")
    p_query.add_argument("--top-k", type=int, default=default_top_k, help="Max child matches")
    p_query.add_argument(
        "--threshold", type=float, default=default_threshold, help="Min similarity [0.0, 1.0]"
    )
    p_query.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_query.add_argument(
        "--searcher",
        default=default_searcher,
        help="Registered retrieval searcher strategy (e.g., default, fts5_hybrid)",
    )
    p_query.add_argument(
        "--expand-parent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Expand matched children to parent sections",
    )
    _add_rerank_args(
        p_query,
        default_rerank=default_rerank,
        default_reranker=default_reranker,
        default_rerank_top_n=default_rerank_top_n,
    )
    _add_where_arg(p_query)
    p_query.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=False,
        help="Emit structured JSON output with query context and retrieved records",
    )

    # Phase 2: ask
    p_ask = subparsers.add_parser(
        "ask",
        parents=[common, pii_supported],
        help="Generate a grounded answer for a question",
    )
    p_ask.add_argument("question", help="Question to answer")
    p_ask.add_argument("--top-k", type=int, default=default_top_k, help="Max child matches")
    p_ask.add_argument(
        "--threshold", type=float, default=default_threshold, help="Min similarity [0.0, 1.0]"
    )
    p_ask.add_argument("--model", default=default_gen_model, help="LLM provider/model")
    p_ask.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_ask.add_argument(
        "--searcher",
        default=default_searcher,
        help="Registered retrieval searcher strategy (e.g., default, fts5_hybrid)",
    )
    _add_rerank_args(
        p_ask,
        default_rerank=default_rerank,
        default_reranker=default_reranker,
        default_rerank_top_n=default_rerank_top_n,
    )
    _add_where_arg(p_ask)
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
    ask_output_group = p_ask.add_mutually_exclusive_group()
    ask_output_group.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=False,
        help="Emit structured JSON with answer, truncation flag, token usage, and sources",
    )
    ask_output_group.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="Stream answer text deltas progressively to stdout (conflicts with --json)",
    )

    # Phase 2: eval
    p_eval = subparsers.add_parser(
        "eval",
        parents=[common, pii_unsupported],
        help="Evaluate retrieval quality read-only against a ground-truth fixture",
    )
    p_eval.add_argument("--fixture", required=True, help="Path to evaluation JSON fixture")
    p_eval.add_argument(
        "--k",
        action="extend",
        nargs="+",
        type=int,
        default=None,
        dest="k_values",
        help="Positive ranking cutoff(s) K (default: 1 3 5 10)",
    )
    p_eval.add_argument("--embed-model", default=default_embed_model, help="Embedding model")
    p_eval.add_argument(
        "--searcher",
        default=default_searcher,
        help="Registered retrieval searcher strategy (e.g., default, fts5_hybrid)",
    )
    p_eval.add_argument(
        "--expand-parent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Expand matched children to parent sections",
    )
    _add_rerank_args(
        p_eval,
        default_rerank=default_rerank,
        default_reranker=default_reranker,
        default_rerank_top_n=default_rerank_top_n,
    )
    _add_where_arg(p_eval)
    p_eval.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        default=False,
        help="Emit structured EvalReport JSON output",
    )

    return parser


def _warn_if_truncated(truncated: bool, *, model: str) -> None:
    """Emit a consistent truncation warning to stderr when output hit max_tokens."""
    if truncated:
        print(
            f"Warning: Response for model {model!r} was truncated at token limit "
            "(finish_reason='length'). Increase or omit --max-tokens to get the full answer.",
            file=sys.stderr,
        )


def _handle_ask(
    args: argparse.Namespace,
    *,
    pii_policy: PiiPolicy | None = None,
) -> int:
    """Execute the ``ask`` subcommand with timing, context inspection, and truncation warnings."""
    from docpipe_maestro._filters import parse_cli_where
    from docpipe_maestro.query.answer import (
        _GenerationStreamState,
        _stream_answer_with_state,
        answer_detailed,
    )
    from docpipe_maestro.query.retriever import retrieve

    if args.local_only:
        from docpipe_maestro.embedder import enforce_local_only

        enforce_local_only(args.embed_model, operation="retrieval")
        enforce_local_only(args.model, args.api_base, operation="generation")

    parsed_where = parse_cli_where(args.where)

    t_ret = time.perf_counter()
    sections = retrieve(
        args.question,
        collection=args.collection,
        persist_dir=args.persist_dir,
        embed_model=args.embed_model,
        top_k=args.top_k,
        threshold=args.threshold,
        expand_parent=True,
        searcher=args.searcher,
        rerank=args.rerank,
        reranker=args.reranker,
        rerank_top_n=args.rerank_top_n,
        local_only=args.local_only,
        where=parsed_where,
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
    if args.stream:
        stream_state = _GenerationStreamState(model=args.model)
        wrote_any = False
        try:
            for chunk in _stream_answer_with_state(
                messages,
                model=args.model,
                api_base=args.api_base,
                has_context=bool(sections),
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                fail_on_truncation=args.fail_on_truncation,
                pii_policy=pii_policy,
                local_only=args.local_only,
                state=stream_state,
            ):
                if chunk:
                    wrote_any = True
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
        finally:
            if wrote_any:
                sys.stdout.write("\n")
                sys.stdout.flush()
        _warn_if_truncated(stream_state.truncated, model=args.model)
        return 0

    gen = answer_detailed(
        messages,
        model=args.model,
        api_base=args.api_base,
        has_context=bool(sections),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        fail_on_truncation=args.fail_on_truncation,
        pii_policy=pii_policy,
        local_only=args.local_only,
    )

    _warn_if_truncated(gen.truncated, model=args.model)

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


def _resolve_eval_collection(
    args: argparse.Namespace,
    loaded_fixture: Mapping[str, Any],
    cfg_collection: str | None,
) -> str:
    """Resolve target collection strictly: explicit CLI > fixture > TOML > global default."""
    if getattr(args, "_collection_explicit", False):
        return str(args.collection)
    fixture_collection = str(loaded_fixture.get("collection", "")).strip()
    if fixture_collection:
        return fixture_collection
    if cfg_collection is not None and cfg_collection.strip():
        return cfg_collection.strip()
    return DEFAULT_COLLECTION


def _format_cost_usd(cost: float | None) -> str:
    """Format an optional USD embedding cost estimate for human CLI output."""
    return f"${cost:.6f}" if cost is not None else "unavailable"


def _format_eval_text(report: EvalReport) -> str:
    """Render an aligned terminal summary of an ``EvalReport``."""
    cfg = report["config"]
    agg = report["aggregate"]
    header = (
        f"Collection: {cfg['collection']} | Model: {cfg['embed_model']} | "
        f"Searcher: {cfg['searcher']} | Expand Parent: {cfg['expand_parent']}"
    )
    if cfg.get("rerank"):
        header += (
            f" | Reranker: {cfg.get('reranker', 'cross_encoder')} "
            f"(top_n={cfg.get('rerank_top_n', DEFAULT_RERANK_TOP_N)})"
        )
    lines = [
        header,
        f"Queries: {agg['num_queries']} | MRR: {agg['mrr']:.4f}",
        "",
        "K   | Precision@K | Recall@K",
        "----+-------------+---------",
    ]
    for k in cfg["k_values"]:
        ks = str(k)
        lines.append(f"{k:<3d} | {agg['precision_at_k'][ks]:<11.4f} | {agg['recall_at_k'][ks]:.4f}")
    max_k_key = str(cfg["k_values"][-1])
    lines.append("")
    lines.append("Per-Query Diagnostics:")
    for item in report["per_query"]:
        rr = item["reciprocal_rank"]
        rank_str = f"rank={round(1.0 / rr)}" if rr > 0.0 else "miss"
        p_max = item["precision_at_k"][max_k_key]
        lines.append(
            f"  [{rank_str}] MRR={rr:.4f} | P@{max_k_key}={p_max:.4f} | {item['question']}"
        )
    return "\n".join(lines)


def _handle_eval(args: argparse.Namespace, *, cfg_collection: str | None) -> int:
    """Execute the ``eval`` subcommand read-only with lazy harness imports."""
    from docpipe_maestro._filters import parse_cli_where
    from docpipe_maestro.eval.harness import (
        DEFAULT_EVAL_K_VALUES,
        evaluate,
        load_eval_fixture,
    )

    parsed_where = parse_cli_where(args.where)
    loaded_fixture = load_eval_fixture(args.fixture)
    resolved_collection = _resolve_eval_collection(args, loaded_fixture, cfg_collection)
    k_values = DEFAULT_EVAL_K_VALUES if args.k_values is None else args.k_values

    report = evaluate(
        loaded_fixture,
        collection=resolved_collection,
        persist_dir=args.persist_dir,
        embed_model=args.embed_model,
        k_values=k_values,
        expand_parent=args.expand_parent,
        searcher=args.searcher,
        rerank=args.rerank,
        reranker=args.reranker,
        rerank_top_n=args.rerank_top_n,
        local_only=args.local_only,
        where=parsed_where,
    )
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_eval_text(report))
    return 0


def _validate_html_report_path(args: argparse.Namespace) -> Path | None:
    """Validate optional ``--html-report`` flag eagerly prior to running mutations."""
    raw = getattr(args, "html_report", None)
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        raise ValueError("--html-report output path must not be empty")
    if getattr(args, "dry_run", False):
        raise ValueError("--html-report cannot be combined with --dry-run")
    target = Path(cleaned)
    if target.exists() and target.is_dir():
        raise ValueError(f"--html-report target must be a file path, not a directory: {target}")
    return target


def _maybe_export_html_report(args: argparse.Namespace, report_target: Path | None) -> None:
    """Lazily export a static HTML audit report when ``--html-report`` was supplied."""
    if report_target is None:
        return
    from docpipe_maestro.report import export_html_report

    written = export_html_report(
        report_target,
        collection=args.collection,
        persist_dir=args.persist_dir,
    )
    if not getattr(args, "as_json", False):
        print(f"HTML audit report saved to: {written}")


def _dispatch_command(
    args: argparse.Namespace,
    *,
    cfg_defaults: dict[str, Any],
    cfg_collection: str | None,
    effective_cfg: str | None,
) -> int:
    """Dispatch parsed CLI subcommand after telemetry and correlation scopes open."""
    cfg_dir = Path(effective_cfg).parent if effective_cfg else Path.cwd()
    resolved_pii_policy = _resolve_cli_pii_policy(args, cfg_defaults, config_dir=cfg_dir)

    if args.command == "ingest":
        from docpipe_maestro.ingest.pipeline import ingest

        report_target = _validate_html_report_path(args)
        res = ingest(
            args.path,
            profile=args.profile,
            collection=args.collection,
            persist_dir=args.persist_dir,
            embed_model=args.embed_model,
            force=args.force,
            pii_policy=resolved_pii_policy,
            local_only=args.local_only,
        )
        print(
            f"Ingested {len(res.ingested)} file(s), skipped {len(res.skipped)} unchanged "
            f"({res.chunks_written} children, {res.parents_written} parents) "
            f"into collection '{res.collection}'."
        )
        _maybe_export_html_report(args, report_target)
        return 0

    if args.command == "sync":
        from docpipe_maestro.ingest.pipeline import sync

        report_target = _validate_html_report_path(args)
        sres = sync(
            args.directory,
            profile=args.profile,
            collection=args.collection,
            persist_dir=args.persist_dir,
            embed_model=args.embed_model,
            pii_policy=resolved_pii_policy,
            local_only=args.local_only,
            dry_run=args.dry_run,
        )
        _maybe_export_html_report(args, report_target)
        if args.as_json:
            print(json.dumps(sres.to_dict(), indent=2))
            return 0
        if sres.dry_run:
            print(
                f"[Dry Run] Sync preview for '{sres.collection}' (model={sres.embed_model}): "
                f"added={len(sres.added)}, updated={len(sres.updated)}, "
                f"skipped={len(sres.skipped)}, removed={len(sres.removed)}, "
                f"children={sres.estimated_children}, parents={sres.estimated_parents}, "
                f"estimated_tokens={sres.estimated_tokens}, "
                f"estimated_cost_usd={_format_cost_usd(sres.estimated_cost_usd)}."
            )
            for label, keys in (
                ("added", sres.added),
                ("updated", sres.updated),
                ("removed", sres.removed),
            ):
                if keys:
                    print(f"  {label}: {', '.join(keys)}")
            return 0
        print(
            f"Synced '{sres.collection}': added={len(sres.added)}, "
            f"updated={len(sres.updated)}, skipped={len(sres.skipped)}, "
            f"removed={len(sres.removed)}."
        )
        return 0

    if args.command == "status":
        from docpipe_maestro.ingest.pipeline import status

        report_target = _validate_html_report_path(args)
        st = status(collection=args.collection, persist_dir=args.persist_dir)
        _maybe_export_html_report(args, report_target)
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

        if args.dry_run:
            preview = reindex(
                embed_model=args.model,
                collection=args.collection,
                persist_dir=args.persist_dir,
                local_only=args.local_only,
                dry_run=True,
            )
            if args.as_json:
                print(json.dumps(preview.to_dict(), indent=2))
                return 0
            print(
                f"[Dry Run] Reindex preview for '{preview.collection}' "
                f"(target_model={preview.embed_model}, "
                f"previous_model={preview.previous_embed_model}): "
                f"sources={preview.total_sources}, children={preview.total_children}, "
                f"parents={preview.total_parents}, estimated_tokens={preview.estimated_tokens}, "
                f"estimated_cost_usd={_format_cost_usd(preview.estimated_cost_usd)}."
            )
            return 0

        count = reindex(
            embed_model=args.model,
            collection=args.collection,
            persist_dir=args.persist_dir,
            local_only=args.local_only,
        )
        if args.as_json:
            print(
                json.dumps(
                    {
                        "collection": args.collection,
                        "embed_model": args.model,
                        "reindexed_children": count,
                        "dry_run": False,
                    },
                    indent=2,
                )
            )
            return 0
        print(
            f"Reindexed {count} child chunk(s) in collection '{args.collection}' "
            f"with model '{args.model}'."
        )
        return 0

    if args.command == "query":
        from docpipe_maestro._filters import parse_cli_where
        from docpipe_maestro.query.retriever import retrieve

        if args.threshold is not None and (
            not math.isfinite(args.threshold) or not 0.0 <= args.threshold <= 1.0
        ):
            raise ValueError("--threshold must be finite and between 0.0 and 1.0")

        parsed_where = parse_cli_where(args.where)

        results = retrieve(
            args.question,
            collection=args.collection,
            persist_dir=args.persist_dir,
            embed_model=args.embed_model,
            top_k=args.top_k,
            threshold=args.threshold,
            expand_parent=args.expand_parent,
            searcher=args.searcher,
            rerank=args.rerank,
            reranker=args.reranker,
            rerank_top_n=args.rerank_top_n,
            local_only=args.local_only,
            where=parsed_where,
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
        return _handle_ask(args, pii_policy=resolved_pii_policy)

    if args.command == "eval":
        return _handle_eval(args, cfg_collection=cfg_collection)

    return 1


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
        cfg_collection = _cfg_opt_str(cfg_defaults, "collection")
        parser = build_parser(cfg_defaults)
        args = parser.parse_args(arg_list)
        with (
            _cli_logging_scope(
                log_json=bool(args.log_json),
                log_level=args.log_level,
            ),
            correlation_id(),
        ):
            return _dispatch_command(
                args,
                cfg_defaults=cfg_defaults,
                cfg_collection=cfg_collection,
                effective_cfg=effective_cfg,
            )
    except (DocpipeError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

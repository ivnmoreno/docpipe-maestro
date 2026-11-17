"""Parser format router with custom-over-builtin precedence and magic-byte fallback."""

from __future__ import annotations

from pathlib import Path

from docpipe_maestro.ingest.intake import PARSERS
from docpipe_maestro.ingest.intake._common import _LEGACY_BINARY_EXTENSIONS, detect_format
from docpipe_maestro.ingest.stages import Parser
from docpipe_maestro.types import UnsupportedFormatError

_BUILTIN_PARSER_KEYS = frozenset(
    {"csv", "docx", "epub", "html", "md", "pdf", "pptx", "rst", "tsv", "txt", "xlsx"}
)


def resolve_parser(path: Path, preferred: str | None = None) -> Parser:
    """Resolve and instantiate the matching ``Parser`` strategy for ``path``.

    Precedence:
    1. Explicit ``preferred`` key resolved via ``PARSERS.resolve(preferred)``.
    2. Readable-file guard (raising ``UnsupportedFormatError`` otherwise).
    3. Lowercased file extension match across registered parsers, checking custom
       non-built-in sorted keys before built-in default keys so custom
       registrations override built-in extensions deterministically.
    4. Extensionless content/magic-byte detection via ``detect_format(path)``.
    """
    if preferred is not None:
        return PARSERS.resolve(preferred)()

    if not path.is_file():
        raise UnsupportedFormatError(f"Path is not a readable file: {path}")

    ext = path.suffix.lower()
    if ext:
        keys = PARSERS.keys()
        custom_keys = sorted(k for k in keys if k not in _BUILTIN_PARSER_KEYS)
        builtin_keys = sorted(k for k in keys if k in _BUILTIN_PARSER_KEYS)
        for key in (*custom_keys, *builtin_keys):
            parser_cls = PARSERS.resolve(key)
            if ext in {e.lower() for e in parser_cls.extensions}:
                return parser_cls()
        if ext in _LEGACY_BINARY_EXTENSIONS:
            raise UnsupportedFormatError(
                f"Unsupported legacy binary format {ext!r} for {path.name}; "
                "convert to '.xlsx', '.pptx', '.docx', or '.csv'"
            )
        raise UnsupportedFormatError(f"Unsupported file extension {ext!r} for {path.name}")

    fmt = detect_format(path)
    return PARSERS.resolve(fmt)()

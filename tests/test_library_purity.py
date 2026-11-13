"""AST library purity, Phase 1/2 separation, and lazy import startup guards."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "docpipe_maestro"
FORBIDDEN_MODULES = frozenset({"tomllib", "tomli", "toml", "configparser", "dotenv"})


def _iter_library_python_files() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py") if p.name != "cli.py")


def test_non_cli_modules_forbid_config_and_dotenv_imports() -> None:
    files = _iter_library_python_files()
    assert files, "Expected library source files under src/docpipe_maestro"

    violations: list[str] = []
    file_io_seen = False

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(SRC_ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_mod = alias.name.split(".", 1)[0]
                    if top_mod in FORBIDDEN_MODULES:
                        violations.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_mod = node.module.split(".", 1)[0]
                    if top_mod in FORBIDDEN_MODULES:
                        violations.append(f"{rel}:{node.lineno} from {node.module} import ...")
                if any(alias.name == "load_dotenv" for alias in node.names):
                    violations.append(f"{rel}:{node.lineno} import load_dotenv")
            elif isinstance(node, ast.Call):
                # Catch dynamic importlib.import_module("dotenv" / "tomli" / ...)
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "import_module"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    target = node.args[0].value.split(".", 1)[0]
                    if target in FORBIDDEN_MODULES:
                        violations.append(
                            f"{rel}:{node.lineno} import_module({node.args[0].value!r})"
                        )
                if (
                    isinstance(func, ast.Attribute) and func.attr in {"read_text", "read_bytes"}
                ) or (isinstance(func, ast.Name) and func.id == "open"):
                    file_io_seen = True

    assert violations == []
    # Confirm document/manifest Path.read_* and open() remain permitted cleanly
    assert file_io_seen


def test_phase2_query_does_not_import_phase1_stage_contracts() -> None:
    query_files = sorted((SRC_ROOT / "query").rglob("*.py"))
    forbidden_phase1 = (
        "docpipe_maestro.ingest.stages",
        "docpipe_maestro.ingest.intake",
        "docpipe_maestro.ingest.clean",
        "docpipe_maestro.ingest.chunker",
        "docpipe_maestro.ingest.enricher",
        "docpipe_maestro.ingest.pipeline",
    )
    violations: list[str] = []
    for path in query_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(SRC_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if any(node.module.startswith(prefix) for prefix in forbidden_phase1):
                    violations.append(f"{rel}:{node.lineno} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(prefix) for prefix in forbidden_phase1):
                        violations.append(f"{rel}:{node.lineno} imports {alias.name}")
    assert violations == []


def test_top_level_register_exports_and_cli_avoid_heavy_deps() -> None:
    code = (
        "import sys; "
        "import docpipe_maestro as dp; "
        "regs = [dp.register_parser, dp.register_cleaner, dp.register_enricher, "
        "dp.register_chunker, dp.register_embedder, dp.register_store, "
        "dp.register_searcher, dp.register_reranker]; "
        "assert all(callable(r) for r in regs); "
        "assert callable(dp.ingest); "
        "import docpipe_maestro.cli as cli; "
        "cli.build_parser(); "
        "assert 'chromadb' not in sys.modules, 'chromadb loaded eagerly'; "
        "assert 'litellm' not in sys.modules, 'litellm loaded eagerly'; "
        "assert 'pypdf' not in sys.modules, 'pypdf loaded eagerly'; "
        "assert 'docx' not in sys.modules, 'docx loaded eagerly'; "
        "assert 'bs4' not in sys.modules, 'bs4 loaded eagerly'"
    )
    proc = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

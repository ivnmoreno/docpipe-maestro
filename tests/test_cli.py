"""Integration tests for all 7 docpipe-maestro CLI commands and --config isolation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from docpipe_maestro.cli import build_parser, main


def test_cli_full_workflow_and_toml_config(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = tmp_path / "docs"
    corpus.mkdir()
    doc = corpus / "leave.md"
    doc.write_text(
        "## Section 1: Annual Leave\n\n"
        "1.1 Employees receive 20 days annual leave except probationary hires.\n",
        encoding="utf-8",
    )

    cfg_file = tmp_path / "docpipe.toml"
    cfg_file.write_text(
        f'collection = "cli_col"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        f'profile = "POLICY"\n',
        encoding="utf-8",
    )

    # 1. ingest with --config and --force
    rc = main(["--config", str(cfg_file), "ingest", str(corpus), "--force"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ingested 1 file(s)" in out

    # 2. status --json
    rc = main(["--config", str(cfg_file), "status", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["collection"] == "cli_col"
    assert payload["total_sources"] == 1

    # 3. query (--expand-parent and --no-expand-parent)
    rc = main(["--config", str(cfg_file), "query", "annual leave days"])
    assert rc == 0
    q_out = capsys.readouterr().out
    assert "except probationary hires" in q_out

    rc = main(["--config", str(cfg_file), "query", "annual leave", "--no-expand-parent"])
    assert rc == 0
    q_child_out = capsys.readouterr().out
    assert "[Source: leave.md" in q_child_out

    # 4. ask
    rc = main(["--config", str(cfg_file), "ask", "How many days of leave?"])
    assert rc == 0
    ask_out = capsys.readouterr().out
    assert "Grounded answer" in ask_out

    # 5. sync
    rc = main(["--config", str(cfg_file), "sync", str(corpus)])
    assert rc == 0
    assert "skipped=1" in capsys.readouterr().out

    # 6. reindex
    rc = main(["--config", str(cfg_file), "reindex", "--model", "openai/text-embedding-3-small"])
    assert rc == 0
    assert "Reindexed 1 child chunk(s)" in capsys.readouterr().out

    # 7. remove (existing and missing)
    rc = main(["--config", str(cfg_file), "remove", "leave.md"])
    assert rc == 0
    assert "Removed 'leave.md'" in capsys.readouterr().out

    rc = main(["--config", str(cfg_file), "remove", "leave.md"])
    assert rc == 1
    assert "Source not found" in capsys.readouterr().out


def test_cli_global_flags_after_subcommand(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "note.md"
    doc.write_text("# Policy\n\nAll staff get 10 holidays.\n", encoding="utf-8")

    rc = main(
        [
            "ingest",
            str(doc),
            "--collection",
            "post_col",
            "--persist-dir",
            str(tmp_persist_dir),
        ]
    )
    assert rc == 0
    assert "collection 'post_col'" in capsys.readouterr().out

    rc = main(
        [
            "status",
            "--json",
            "--collection",
            "post_col",
            "--persist-dir",
            str(tmp_persist_dir),
        ]
    )
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["collection"] == "post_col"

    # Invalid profile and invalid collection name fail cleanly with exit code 1 (no traceback)
    rc_bad_prof = main(
        ["ingest", str(doc), "--profile", "NO_SUCH_PROFILE", "--persist-dir", str(tmp_persist_dir)]
    )
    assert rc_bad_prof == 1
    assert "Unknown chunking profile" in capsys.readouterr().err

    rc_bad_col = main(
        ["ingest", str(doc), "--collection", "x", "--persist-dir", str(tmp_persist_dir)]
    )
    assert rc_bad_col == 1
    assert "Invalid or unusable collection" in capsys.readouterr().err


def test_cli_prog_name_and_module_entrypoint() -> None:
    parser = build_parser()
    assert parser.prog == "docpipe-maestro"

    proc = subprocess.run(
        [sys.executable, "-m", "docpipe_maestro", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip().startswith("docpipe-maestro ")

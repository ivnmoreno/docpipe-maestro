"""Integration tests for all 7 docpipe-maestro CLI commands and --config isolation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from dotenv import dotenv_values

from docpipe_maestro import answer
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


def test_cli_dotenv_scoped_discovery_precedence_and_no_ancestor_walk(
    tmp_path: Path,
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_litellm_offline: dict[str, Any],
) -> None:
    ancestor_env = tmp_path / ".env"
    ancestor_env.write_text('DOCPIPE_TEST_ANCESTOR="leaked-from-parent"\n', encoding="utf-8")

    cfg_dir = tmp_path / "project_cfg"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "docpipe.toml"
    cfg_file.write_text(
        f'collection = "env_col"\npersist_dir = "{tmp_persist_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    (cfg_dir / ".env").write_text(
        'DOCPIPE_TEST_CFG_KEY="from-config-dotenv"\nDOCPIPE_TEST_SHELL_WINS="from-dotenv"\n',
        encoding="utf-8",
    )

    work_dir = tmp_path / "nested" / "workdir"
    work_dir.mkdir(parents=True)
    (work_dir / ".env").write_text('DOCPIPE_TEST_CWD_KEY="from-cwd-dotenv"\n', encoding="utf-8")

    for var in (
        "DOCPIPE_TEST_ANCESTOR",
        "DOCPIPE_TEST_CFG_KEY",
        "DOCPIPE_TEST_SHELL_WINS",
        "DOCPIPE_TEST_CWD_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DOCPIPE_TEST_SHELL_WINS", "from-shell")
    monkeypatch.chdir(work_dir)

    # 1. Direct library call must NOT read CWD .env
    answer("What is the policy?", has_context=True)
    assert "DOCPIPE_TEST_CWD_KEY" not in os.environ

    # 2. --config scopes .env discovery strictly to config file directory (ignores CWD and parent)
    rc_cfg = main(["--config", str(cfg_file), "status", "--json"])
    assert rc_cfg == 0
    assert os.environ.get("DOCPIPE_TEST_CFG_KEY") == "from-config-dotenv"
    assert os.environ.get("DOCPIPE_TEST_SHELL_WINS") == "from-shell"
    assert "DOCPIPE_TEST_CWD_KEY" not in os.environ
    assert "DOCPIPE_TEST_ANCESTOR" not in os.environ

    # 3. No --config scopes .env discovery strictly to CWD (never walks up to ancestor)
    monkeypatch.delenv("DOCPIPE_TEST_CWD_KEY", raising=False)
    rc_cwd = main(["--persist-dir", str(tmp_persist_dir), "status", "--json"])
    assert rc_cwd == 0
    assert os.environ.get("DOCPIPE_TEST_CWD_KEY") == "from-cwd-dotenv"
    assert "DOCPIPE_TEST_ANCESTOR" not in os.environ

    # 4. Missing .env in an empty directory is tolerated silently
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    rc_missing = main(["--persist-dir", str(tmp_persist_dir), "status", "--json"])
    assert rc_missing == 0


def test_env_example_template_and_gitignore_rules() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    template_path = repo_root / ".env.example"
    assert template_path.is_file()

    text = template_path.read_text(encoding="utf-8")
    assert "chmod 600 .env" in text
    assert "TOGETHER_API_KEY" in text

    parsed = dotenv_values(template_path)
    expected_keys = {
        "GROQ_API_KEY",
        "TOGETHERAI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_API_KEY",
        "AZURE_API_BASE",
        "AZURE_API_VERSION",
        "LITELLM_LOCAL_MODEL_COST_MAP",
    }
    assert expected_keys.issubset(parsed.keys())
    assert parsed["LITELLM_LOCAL_MODEL_COST_MAP"] == "true"

    live_prefixes = ("sk-", "gsk_", "AIza")
    for key, val in parsed.items():
        if key != "LITELLM_LOCAL_MODEL_COST_MAP" and val is not None:
            assert not val.startswith(live_prefixes), f"{key} looks like a live key"

    if (repo_root / ".git").exists():
        ignored = subprocess.run(
            ["git", "check-ignore", ".env"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ignored.returncode == 0
        tracked_ready = subprocess.run(
            ["git", "check-ignore", ".env.example"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert tracked_ready.returncode == 1


def test_cli_ask_generation_flags_toml_parity_and_chat_messages(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "policy.md"
    doc.write_text("## Section 1: Travel\n\nAll travel requires pre-approval.\n", encoding="utf-8")

    cfg_file = tmp_path / "docpipe.toml"
    cfg_file.write_text(
        f'collection = "parity_col"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        f'model = "groq/llama-3.3-70b-versatile"\n'
        f'api_base = "https://api.groq.com/openai/v1"\n'
        f"temperature = 0.5\n"
        f"max_tokens = 256\n"
        f"timeout = 45.0\n",
        encoding="utf-8",
    )

    assert main(["--config", str(cfg_file), "ingest", str(doc), "--force"]) == 0
    capsys.readouterr()

    # 1. TOML defaults apply cleanly and ask dispatches role-separated build_chat_messages
    assert main(["--config", str(cfg_file), "ask", "Who approves travel?"]) == 0
    assert "Grounded answer" in capsys.readouterr().out
    call_toml = mock_litellm_offline["completion"][-1]
    assert call_toml["model"] == "groq/llama-3.3-70b-versatile"
    assert call_toml["kwargs"]["api_base"] == "https://api.groq.com/openai/v1"
    assert call_toml["kwargs"]["temperature"] == 0.5
    assert call_toml["kwargs"]["max_tokens"] == 256
    assert call_toml["kwargs"]["timeout"] == 45.0
    assert call_toml["kwargs"]["num_retries"] == 0

    msgs = call_toml["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "All travel requires pre-approval." in msgs[1]["content"]
    assert "Who approves travel?" in msgs[1]["content"]
    assert "All travel requires pre-approval." not in msgs[0]["content"]

    # 2. Explicit CLI flags override TOML defaults (including temperature=0.0)
    rc_override = main(
        [
            "--config",
            str(cfg_file),
            "ask",
            "Who approves travel?",
            "--temperature",
            "0.0",
            "--max-tokens",
            "512",
            "--timeout",
            "15.5",
            "--api-base",
            "http://localhost:11434/v1",
        ]
    )
    assert rc_override == 0
    call_cli = mock_litellm_offline["completion"][-1]
    assert call_cli["kwargs"]["temperature"] == 0.0
    assert call_cli["kwargs"]["max_tokens"] == 512
    assert call_cli["kwargs"]["timeout"] == 15.5
    assert call_cli["kwargs"]["api_base"] == "http://localhost:11434/v1"

    # 3. With --no-config (ignoring any CWD docpipe.toml), built-in defaults apply
    rc_builtin = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "parity_col",
            "ask",
            "Who approves travel?",
        ]
    )
    assert rc_builtin == 0
    call_builtin = mock_litellm_offline["completion"][-1]
    assert "temperature" not in call_builtin["kwargs"]
    assert "max_tokens" not in call_builtin["kwargs"]
    assert call_builtin["kwargs"]["timeout"] == 120.0


@pytest.mark.parametrize(
    "bad_toml",
    [
        "max_tokens = true\n",
        "max_tokens = 1.5\n",
        "temperature = true\n",
        "timeout = false\n",
        "api_base = 123\n",
    ],
)
def test_cli_rejects_invalid_toml_generation_types(
    bad_toml: str,
    tmp_path: Path,
    tmp_persist_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "bad_gen.toml"
    cfg.write_text(f'persist_dir = "{tmp_persist_dir.as_posix()}"\n{bad_toml}', encoding="utf-8")
    rc = main(["--config", str(cfg), "status"])
    assert rc == 1
    assert "Invalid TOML config value" in capsys.readouterr().err


def test_cli_cwd_docpipe_toml_autodiscovery_precedence_and_no_config(
    tmp_path: Path,
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "rules.md"
    doc.write_text("## Section 1: Laptops\n\nAll laptops require encryption.\n", encoding="utf-8")

    # Ancestor docpipe.toml must NEVER be loaded via upward traversal
    (tmp_path / "docpipe.toml").write_text('model = "ancestor/should-not-load"\n', encoding="utf-8")

    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    (work_dir / "docpipe.toml").write_text(
        f'collection = "cwd_col"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        f'model = "groq/openai/gpt-oss-120b"\n',
        encoding="utf-8",
    )

    override_cfg = tmp_path / "override.toml"
    override_cfg.write_text(
        f'collection = "cwd_col"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        f'model = "mistral/mistral-small-2603"\n',
        encoding="utf-8",
    )

    monkeypatch.chdir(work_dir)
    assert main(["ingest", str(doc), "--force"]) == 0
    capsys.readouterr()

    # 1. CWD docpipe.toml auto-loads when --config is omitted
    assert main(["ask", "Do laptops require encryption?"]) == 0
    capsys.readouterr()
    assert mock_litellm_offline["completion"][-1]["model"] == "groq/openai/gpt-oss-120b"

    # 2. Explicit --config overrides CWD docpipe.toml
    assert main(["--config", str(override_cfg), "ask", "Do laptops require encryption?"]) == 0
    capsys.readouterr()
    assert mock_litellm_offline["completion"][-1]["model"] == "mistral/mistral-small-2603"

    # 3. --no-config bypasses CWD docpipe.toml completely and restores built-in defaults
    assert (
        main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "--collection",
                "cwd_col",
                "ask",
                "Do laptops require encryption?",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert mock_litellm_offline["completion"][-1]["model"] == "ollama/llama3.2"

    # 4. Empty directory without docpipe.toml never walks upward to parent
    empty_dir = work_dir / "sub_empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    assert (
        main(
            [
                "--persist-dir",
                str(tmp_persist_dir),
                "--collection",
                "cwd_col",
                "ask",
                "Do laptops require encryption?",
            ]
        )
        == 0
    )
    assert mock_litellm_offline["completion"][-1]["model"] == "ollama/llama3.2"


def test_cli_ask_truncation_warning_strict_mode_show_context_and_json(
    tmp_path: Path,
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "policy.md"
    doc.write_text("## Section 1: Access\n\nMFA is required for all logins.\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    assert main(["--no-config", "--persist-dir", str(tmp_persist_dir), "ingest", str(doc)]) == 0
    capsys.readouterr()

    truncated_reply = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Partial MFA answer"),
                finish_reason="length",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=60,
            completion_tokens=20,
            total_tokens=80,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )

    with patch("litellm.completion", return_value=truncated_reply):
        # 1. Default mode: exits 0, outputs partial answer, warns cleanly on stderr
        rc_warn = main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "ask",
                "Is MFA required?",
                "--show-context",
            ]
        )
        assert rc_warn == 0
        captured = capsys.readouterr()
        assert "Partial MFA answer" in captured.out
        assert "Warning:" in captured.err
        assert "truncated" in captured.err.lower()
        assert "Section 1: Access" in captured.err

        # 2. --json includes answer, truncation state, usage counters, and sources
        rc_json = main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "ask",
                "Is MFA required?",
                "--json",
            ]
        )
        assert rc_json == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["answer"] == "Partial MFA answer"
        assert payload["truncated"] is True
        assert payload["finish_reason"] == "length"
        assert payload["usage"]["reasoning_tokens"] == 5
        assert payload["sources"][0]["section"] == "Section 1: Access"

        # 3. --fail-on-truncation converts finish_reason="length" into exit code 1 error
        rc_fail = main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "ask",
                "Is MFA required?",
                "--fail-on-truncation",
            ]
        )
        assert rc_fail == 1
        err_out = capsys.readouterr().err
        assert "Error:" in err_out
        assert "truncated" in err_out.lower()


def test_cli_lazy_imports_avoid_heavy_deps_on_parser_init() -> None:
    code = (
        "import sys; "
        "import docpipe_maestro.cli as c; "
        "c.build_parser(); "
        "assert 'chromadb' not in sys.modules, 'chromadb loaded eagerly'; "
        "assert 'litellm' not in sys.modules, 'litellm loaded eagerly'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

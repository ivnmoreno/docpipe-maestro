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

    reasoning_exhausted = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, reasoning="Analyzing context..."),
                finish_reason="length",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=60,
            completion_tokens=512,
            total_tokens=572,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=512),
        ),
    )
    with patch("litellm.completion", return_value=reasoning_exhausted):
        rc_reasoning = main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "ask",
                "Is MFA required?",
                "--max-tokens",
                "512",
            ]
        )
        assert rc_reasoning == 1
        err_reasoning = capsys.readouterr().err
        assert "Error:" in err_reasoning
        assert "max_tokens" in err_reasoning
        assert "512 reasoning tokens used" in err_reasoning


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


def test_cli_query_json_envelope_child_empty_flags_and_errors(
    tmp_path: Path,
    tmp_persist_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = tmp_path / "docs"
    corpus.mkdir()
    doc = corpus / "leave.md"
    doc.write_text(
        "## Section 1: Annual Leave\n\n"
        "1.1 Full-time employees accrue 20 days annual leave except probationary hires.\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "docpipe.toml"
    cfg.write_text(
        f'collection = "q_json_col"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        f'profile = "POLICY"\n'
        f"top_k = 3\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert main(["--config", str(cfg), "ingest", str(doc)]) == 0
    capsys.readouterr()

    # 1. Parent-expanded --json (--config before subcommand)
    rc_parent = main(["--config", str(cfg), "query", "annual leave", "--json"])
    assert rc_parent == 0
    cap_parent = capsys.readouterr()
    assert cap_parent.err == ""
    payload = json.loads(cap_parent.out)
    assert payload["query"] == "annual leave"
    assert payload["collection"] == "q_json_col"
    assert payload["expand_parent"] is True
    assert len(payload["results"]) >= 1
    first = payload["results"][0]
    assert set(first) == {"id", "parent_id", "score", "text", "metadata"}
    assert len(first["id"]) == 16
    assert first["parent_id"] is None
    assert isinstance(first["score"], float)
    assert 0.0 <= first["score"] <= 1.0
    assert "probationary hires" in first["text"]
    assert first["metadata"]["type"] == "parent"
    assert first["metadata"]["source"] == "leave.md"
    assert first["metadata"]["page"] is None

    # 2. Global flags (--config) placed AFTER query produce identical JSON structure
    rc_after = main(["query", "annual leave", "--json", "--config", str(cfg)])
    assert rc_after == 0
    assert json.loads(capsys.readouterr().out) == payload

    # 3. Raw child mode (--no-expand-parent --json)
    rc_child = main(
        [
            "--no-config",
            "--collection",
            "q_json_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "query",
            "annual leave",
            "--no-expand-parent",
            "--json",
        ]
    )
    assert rc_child == 0
    child_payload = json.loads(capsys.readouterr().out)
    assert child_payload["expand_parent"] is False
    child_item = child_payload["results"][0]
    assert isinstance(child_item["parent_id"], str) and len(child_item["parent_id"]) == 16
    assert child_item["metadata"]["type"] == "child"

    # 4. Zero matches (empty collection and impossible threshold) -> valid JSON with results=[]
    rc_empty_thresh = main(
        ["--config", str(cfg), "query", "annual leave", "--threshold", "0.99999", "--json"]
    )
    assert rc_empty_thresh == 0
    cap_empty = capsys.readouterr()
    assert cap_empty.err == ""
    assert "No matching sections found." not in cap_empty.out
    assert json.loads(cap_empty.out) == {
        "query": "annual leave",
        "collection": "q_json_col",
        "expand_parent": True,
        "results": [],
    }

    rc_empty_col = main(
        [
            "--no-config",
            "--collection",
            "empty_col",
            "--persist-dir",
            str(tmp_persist_dir),
            "query",
            "anything",
            "--json",
        ]
    )
    assert rc_empty_col == 0
    assert json.loads(capsys.readouterr().out)["results"] == []

    # 5. Default non-JSON text mode preserved
    assert main(["--config", str(cfg), "query", "annual leave"]) == 0
    assert "[1] score=" in capsys.readouterr().out
    assert main(["--config", str(cfg), "query", "annual leave", "--threshold", "0.99999"]) == 0
    assert "No matching sections found." in capsys.readouterr().out

    # 6. Validation / runtime failures emit Error: on stderr, empty stdout, and exit 1
    rc_bad_thresh = main(
        ["--config", str(cfg), "query", "annual leave", "--threshold", "1.5", "--json"]
    )
    assert rc_bad_thresh == 1
    cap_bad = capsys.readouterr()
    assert cap_bad.out == ""
    assert "Error:" in cap_bad.err

    rc_mismatch = main(
        [
            "--config",
            str(cfg),
            "query",
            "annual leave",
            "--embed-model",
            "openai/wrong-model",
            "--json",
        ]
    )
    assert rc_mismatch == 1
    cap_mis = capsys.readouterr()
    assert cap_mis.out == ""
    assert "Error:" in cap_mis.err


def _seed_cli_eval_collections(
    tmp_path: Path,
    persist_dir: Path,
) -> dict[str, dict[str, str]]:
    """Seed two isolated collections and return parent IDs per collection."""
    from docpipe_maestro import ingest, status

    docs_dir = tmp_path / "cli_eval_docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "policy.md").write_text(
        (
            "# Backup Policy\n\n"
            "Production backups MUST use KMS-401 keys and AES-256 encryption.\n"
            "Legacy tapes are excluded except under CFO sign-off.\n"
        ),
        encoding="utf-8",
    )

    seeded: dict[str, dict[str, str]] = {}
    for col_name in ("fixture_col", "toml_col", "explicit_col", "default"):
        ingest(docs_dir, profile="POLICY", collection=col_name, persist_dir=persist_dir)
        st = status(collection=col_name, persist_dir=persist_dir)
        rec = next(item for item in st.sources if item.source.endswith("policy.md"))
        seeded[col_name] = {"parent": rec.parent_ids[0], "child": rec.chunk_ids[0]}
    return seeded


def test_cli_eval_startup_purity_and_help() -> None:
    code = (
        "import sys; "
        "import docpipe_maestro.cli as cli; "
        "p = cli.build_parser(); "
        "assert 'docpipe_maestro.eval.harness' not in sys.modules; "
        "assert 'chromadb' not in sys.modules; "
        "assert 'litellm' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    help_proc = subprocess.run(
        [sys.executable, "-m", "docpipe_maestro.cli", "eval", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_proc.returncode == 0
    assert "--fixture" in help_proc.stdout
    assert "--k" in help_proc.stdout
    assert "--searcher" in help_proc.stdout
    assert "--expand-parent" in help_proc.stdout


def test_cli_eval_json_and_human_output_and_precedence(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeded = _seed_cli_eval_collections(tmp_path, tmp_persist_dir)
    pid = seeded["fixture_col"]["parent"]
    cid = seeded["explicit_col"]["child"]

    fixture_with_col = tmp_path / "fixture_with_col.json"
    fixture_with_col.write_text(
        json.dumps(
            {
                "collection": "fixture_col",
                "profile": "POLICY",
                "queries": [
                    {
                        "question": "What encryption applies to KMS-401 production backups?",
                        "relevant_ids": [pid],
                        "notes": "exact_identifier",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fixture_empty_col = tmp_path / "fixture_empty_col.json"
    fixture_empty_col.write_text(
        json.dumps(
            {
                "collection": "",
                "queries": [
                    {
                        "question": "What encryption applies to KMS-401 production backups?",
                        "relevant_ids": [seeded["toml_col"]["parent"]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cfg = tmp_path / "docpipe.toml"
    cfg.write_text(
        f'collection = "toml_col"\npersist_dir = "{tmp_persist_dir.as_posix()}"\n',
        encoding="utf-8",
    )

    # 1. Explicit --collection BEFORE eval overrides fixture and TOML
    rc = main(
        [
            "--config",
            str(cfg),
            "--collection",
            "explicit_col",
            "eval",
            "--fixture",
            str(fixture_with_col),
            "--json",
        ]
    )
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["config"]["collection"] == "explicit_col"
    assert report["aggregate"]["num_queries"] == 1

    # 2. Explicit --collection AFTER eval overrides fixture and TOML
    rc_after = main(
        [
            "eval",
            "--config",
            str(cfg),
            "--collection",
            "explicit_col",
            "--fixture",
            str(fixture_with_col),
            "--k",
            "10",
            "3",
            "--k",
            "3",
            "--searcher",
            "fts5_hybrid",
            "--no-expand-parent",
            "--json",
        ]
    )
    assert rc_after == 0
    rep_after = json.loads(capsys.readouterr().out)
    assert rep_after["config"]["collection"] == "explicit_col"
    assert rep_after["config"]["k_values"] == [3, 10]
    assert rep_after["config"]["searcher"] == "fts5_hybrid"
    assert rep_after["config"]["expand_parent"] is False
    assert cid in rep_after["per_query"][0]["retrieved_ids"]

    # 3. Omitted --collection selects fixture["collection"] ahead of docpipe.toml
    rc_fixture = main(["--config", str(cfg), "eval", "--fixture", str(fixture_with_col), "--json"])
    assert rc_fixture == 0
    rep_fix = json.loads(capsys.readouterr().out)
    assert rep_fix["config"]["collection"] == "fixture_col"
    assert rep_fix["aggregate"]["mrr"] == pytest.approx(1.0)

    # 4. Empty fixture["collection"] falls back to docpipe.toml, else "default" with --no-config
    rc_toml = main(["--config", str(cfg), "eval", "--fixture", str(fixture_empty_col), "--json"])
    assert rc_toml == 0
    rep_toml = json.loads(capsys.readouterr().out)
    assert rep_toml["config"]["collection"] == "toml_col"
    assert rep_toml["aggregate"]["mrr"] == pytest.approx(1.0)

    rc_global_default = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(fixture_empty_col),
            "--json",
        ]
    )
    assert rc_global_default == 0
    assert json.loads(capsys.readouterr().out)["config"]["collection"] == "default"

    # 5. Human-readable summary output mode exits 0 and includes expected sections
    rc_text = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(fixture_with_col),
            "--k",
            "1",
            "3",
            "5",
        ]
    )
    assert rc_text == 0
    cap_text = capsys.readouterr()
    assert cap_text.err == ""
    for required in (
        "Collection:",
        "Model:",
        "Searcher:",
        "Expand Parent:",
        "Queries:",
        "MRR:",
        "K",
        "Precision@K",
        "Recall@K",
    ):
        assert required in cap_text.out


def test_cli_eval_errors_emit_single_line_stderr_and_exit_one(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeded = _seed_cli_eval_collections(tmp_path, tmp_persist_dir)
    valid_fix = tmp_path / "ok.json"
    valid_fix.write_text(
        json.dumps(
            {
                "collection": "fixture_col",
                "queries": [
                    {"question": "KMS-401?", "relevant_ids": [seeded["fixture_col"]["parent"]]}
                ],
            }
        ),
        encoding="utf-8",
    )
    bad_json_fix = tmp_path / "bad.json"
    bad_json_fix.write_text("{bad", encoding="utf-8")

    error_invocations: list[list[str]] = [
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(tmp_path / "missing.json"),
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(bad_json_fix),
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(valid_fix),
            "--k",
            "0",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "does_not_exist",
            "eval",
            "--fixture",
            str(valid_fix),
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(valid_fix),
            "--embed-model",
            "openai/mismatched",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(valid_fix),
            "--searcher",
            "ghost",
        ],
    ]
    for argv in error_invocations:
        rc = main(argv)
        assert rc == 1
        cap = capsys.readouterr()
        assert cap.out == ""
        assert cap.err.startswith("Error:")
        assert len(cap.err.strip().splitlines()) == 1


def test_cli_query_ask_rerank_flags_toml_precedence_and_errors(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from docpipe_maestro import ingest
    from docpipe_maestro.query.reranker import RERANKERS, register_reranker

    docs_dir = tmp_path / "cli_rr_docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "leave.md").write_text(
        "# Annual Leave\n\nEmployees receive 20 paid leave days except probationary staff.\n",
        encoding="utf-8",
    )
    ingest(docs_dir, profile="POLICY", collection="cli_rr", persist_dir=tmp_persist_dir)

    default_parsed_q = build_parser().parse_args(["query", "leave"])
    assert default_parsed_q.rerank is False
    assert default_parsed_q.reranker == "cross_encoder"
    assert default_parsed_q.rerank_top_n == 20

    default_parsed_a = build_parser().parse_args(["ask", "leave"])
    assert default_parsed_a.rerank is False
    assert default_parsed_a.reranker == "cross_encoder"
    assert default_parsed_a.rerank_top_n == 20

    cfg_override = tmp_path / "rerank.toml"
    cfg_override.write_text(
        f'collection = "cli_rr"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        f"rerank = true\n"
        f'reranker = "cli_spy_reranker"\n'
        f"rerank_top_n = 7\n",
        encoding="utf-8",
    )

    entries_snap = dict(RERANKERS._entries)
    lazy_snap = dict(RERANKERS._lazy_builtins)
    rerank_calls: list[int] = []
    try:

        @register_reranker("cli_spy_reranker")
        class CliSpyReranker:
            name = "cli_spy_reranker"

            def rerank(self, query: str, chunks: list[Any], *, top_k: int) -> list[Any]:
                _ = query
                rerank_calls.append(top_k)
                return chunks[:top_k]

        # TOML defaults apply cleanly across query & ask.
        assert main(["--config", str(cfg_override), "query", "leave", "--json"]) == 0
        _ = capsys.readouterr()
        assert len(rerank_calls) == 1

        assert main(["--config", str(cfg_override), "ask", "leave", "--json"]) == 0
        _ = capsys.readouterr()
        assert len(rerank_calls) == 2

        # Explicit --no-rerank overrides TOML rerank = true without invoking reranker.
        assert main(["--config", str(cfg_override), "query", "leave", "--no-rerank", "--json"]) == 0
        _ = capsys.readouterr()
        assert main(["--config", str(cfg_override), "ask", "leave", "--no-rerank", "--json"]) == 0
        _ = capsys.readouterr()
        assert len(rerank_calls) == 2
    finally:
        RERANKERS._entries = entries_snap
        RERANKERS._lazy_builtins = lazy_snap

    # TOML rerank_top_n = 0 must NOT block unrelated commands like status --json,
    # while query and ask fail with single-line Error: and exit 1.
    bad_topn_cfg = tmp_path / "bad_topn.toml"
    bad_topn_cfg.write_text(
        f'collection = "cli_rr"\npersist_dir = "{tmp_persist_dir.as_posix()}"\nrerank_top_n = 0\n',
        encoding="utf-8",
    )
    assert main(["--config", str(bad_topn_cfg), "status", "--json"]) == 0
    _ = capsys.readouterr()

    for sub_args in (
        ["--config", str(bad_topn_cfg), "query", "leave"],
        ["--config", str(bad_topn_cfg), "ask", "leave"],
        ["--config", str(cfg_override), "query", "leave", "--rerank-top-n", "0"],
        ["--config", str(cfg_override), "ask", "leave", "--reranker", "ghost_reranker"],
    ):
        rc = main(sub_args)
        assert rc == 1
        cap = capsys.readouterr()
        assert cap.out == ""
        assert cap.err.startswith("Error:")
        assert len(cap.err.strip().splitlines()) == 1

    # Invalid TOML types (boolean where int expected / string where bool expected) fail cleanly.
    bad_type_cfg = tmp_path / "bad_type.toml"
    bad_type_cfg.write_text('rerank = "yes"\n', encoding="utf-8")
    assert main(["--config", str(bad_type_cfg), "query", "leave"]) == 1
    cap_type = capsys.readouterr()
    assert cap_type.out == ""
    assert cap_type.err.startswith("Error:")

    # Missing [rerank] emits single-line installation Error: on stderr and exit 1.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    for subcmd in ("query", "ask"):
        rc_miss = main(
            [
                "--no-config",
                "--collection",
                "cli_rr",
                "--persist-dir",
                str(tmp_persist_dir),
                subcmd,
                "leave",
                "--rerank",
            ]
        )
        assert rc_miss == 1
        cap_miss = capsys.readouterr()
        assert cap_miss.out == ""
        assert cap_miss.err.startswith("Error:")
        assert "docpipe-maestro[rerank]" in cap_miss.err
        assert len(cap_miss.err.strip().splitlines()) == 1


def test_cli_eval_rerank_flags_toml_header_and_errors(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from dataclasses import replace

    from docpipe_maestro.query.reranker import RERANKERS, register_reranker
    from docpipe_maestro.types import RetrievedChunk

    seeded = _seed_cli_eval_collections(tmp_path, tmp_persist_dir)
    pid = seeded["fixture_col"]["parent"]

    fixture_path = tmp_path / "eval_rerank_fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "collection": "fixture_col",
                "profile": "POLICY",
                "queries": [
                    {
                        "question": "What encryption applies to KMS-401 production backups?",
                        "relevant_ids": [pid],
                        "notes": "exact_identifier",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    saved_entries = dict(RERANKERS._entries)
    saved_lazy = dict(RERANKERS._lazy_builtins)
    try:

        @register_reranker("_test_cli_eval_rr")
        class _CliEvalReranker:
            name = "_test_cli_eval_rr"

            def rerank(
                self,
                query: str,
                chunks: list[RetrievedChunk],
                *,
                top_k: int,
            ) -> list[RetrievedChunk]:
                rescored = [
                    replace(chunk, score=0.91 if "KMS-401" in chunk.text else 0.21)
                    for chunk in chunks
                ]
                rescored.sort(key=lambda c: c.score, reverse=True)
                return rescored[:top_k]

        cfg = tmp_path / "eval_rerank.toml"
        cfg.write_text(
            f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
            "rerank = true\n"
            'reranker = "_test_cli_eval_rr"\n'
            "rerank_top_n = 9\n",
            encoding="utf-8",
        )

        # 1. TOML defaults apply to eval --json
        rc_toml = main(["--config", str(cfg), "eval", "--fixture", str(fixture_path), "--json"])
        assert rc_toml == 0
        rep_toml = json.loads(capsys.readouterr().out)
        assert rep_toml["config"]["rerank"] is True
        assert rep_toml["config"]["reranker"] == "_test_cli_eval_rr"
        assert rep_toml["config"]["rerank_top_n"] == 9

        # 2. --no-rerank overrides TOML and omits all rerank keys from EvalConfig JSON
        rc_no = main(
            [
                "--config",
                str(cfg),
                "eval",
                "--fixture",
                str(fixture_path),
                "--no-rerank",
                "--json",
            ]
        )
        assert rc_no == 0
        rep_no = json.loads(capsys.readouterr().out)
        assert "rerank" not in rep_no["config"]
        assert "reranker" not in rep_no["config"]
        assert "rerank_top_n" not in rep_no["config"]

        # 3. Text header includes Reranker ONLY when rerank=True
        rc_text_off = main(
            ["--config", str(cfg), "eval", "--fixture", str(fixture_path), "--no-rerank"]
        )
        assert rc_text_off == 0
        out_off = capsys.readouterr().out
        assert "Reranker:" not in out_off

        rc_text_on = main(
            [
                "--config",
                str(cfg),
                "eval",
                "--fixture",
                str(fixture_path),
                "--rerank",
                "--reranker",
                "_test_cli_eval_rr",
                "--rerank-top-n",
                "6",
            ]
        )
        assert rc_text_on == 0
        out_on = capsys.readouterr().out
        first_line = out_on.splitlines()[0]
        assert "| Reranker: _test_cli_eval_rr (top_n=6)" in first_line

        # 4. Exit-1 single-line stderr diagnostics for eval error cases
        bad_cfg = tmp_path / "eval_bad_topn.toml"
        bad_cfg.write_text(
            f'persist_dir = "{tmp_persist_dir.as_posix()}"\nrerank = true\nrerank_top_n = 0\n',
            encoding="utf-8",
        )
        for bad_args in (
            ["--config", str(bad_cfg), "eval", "--fixture", str(fixture_path)],
            [
                "--config",
                str(cfg),
                "eval",
                "--fixture",
                str(fixture_path),
                "--rerank-top-n",
                "0",
            ],
            [
                "--config",
                str(cfg),
                "eval",
                "--fixture",
                str(fixture_path),
                "--reranker",
                "ghost_reranker",
            ],
        ):
            assert main(bad_args) == 1
            cap_bad = capsys.readouterr()
            assert cap_bad.out == ""
            assert cap_bad.err.startswith("Error:")
            assert len(cap_bad.err.strip().splitlines()) == 1

        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        assert (
            main(
                [
                    "--no-config",
                    "--persist-dir",
                    str(tmp_persist_dir),
                    "eval",
                    "--fixture",
                    str(fixture_path),
                    "--rerank",
                ]
            )
            == 1
        )
        cap_miss = capsys.readouterr()
        assert cap_miss.out == ""
        assert "docpipe-maestro[rerank]" in cap_miss.err
        assert len(cap_miss.err.strip().splitlines()) == 1
    finally:
        RERANKERS._entries = saved_entries
        RERANKERS._lazy_builtins = saved_lazy


def test_cli_policy_profile_runs_crossrefs_and_enricher_error_exits_1(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI ingest --profile POLICY runs CrossrefsEnricher and enricher errors exit 1."""
    from docpipe_maestro.config import PROFILES
    from docpipe_maestro.ingest.enricher import ENRICHERS, register_enricher
    from docpipe_maestro.store import VectorStore
    from docpipe_maestro.types import ChunkingProfile, DocpipeError, IngestContext, ParsedDocument

    _ = mock_litellm_offline
    doc = tmp_path / "cli_policy.md"
    doc.write_text(
        "## Section 1: Retention\n\n"
        "1.1 Isolate logs and follow Section 2.\n\n"
        "## Section 2: Exceptions\n\n"
        "2.1 Executive backups remain offline unless audited.\n",
        encoding="utf-8",
    )

    rc_ingest = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_policy_col",
            "ingest",
            str(doc),
            "--profile",
            "POLICY",
        ]
    )
    assert rc_ingest == 0
    _ = capsys.readouterr()

    stored_text = "\n".join(
        c.text for c in VectorStore(tmp_persist_dir, "cli_policy_col").get_all_children()
    )
    assert "[Crossref Section 2:" in stored_text
    assert "Executive backups remain offline" in stored_text

    saved_entries = dict(ENRICHERS._entries)
    saved_lazy = dict(ENRICHERS._lazy_builtins)
    saved_mat = set(ENRICHERS._materializing)
    try:

        @register_enricher("boom_cli")
        class _CliBoomEnricher:
            name = "boom_cli"

            def enrich(self, doc_in: ParsedDocument, ctx: IngestContext) -> ParsedDocument:
                _ = (doc_in, ctx)
                raise DocpipeError("Enricher validation halted CLI run")

        boom_profile = ChunkingProfile(
            name="BOOM_CLI",
            chunk_size=1000,
            overlap=80,
            clause_preserving=False,
            parent_child=False,
            resolve_crossrefs=False,
            enrichers=("boom_cli",),
        )
        cfg = tmp_path / "cli_boom.toml"
        cfg.write_text(
            f'persist_dir = "{tmp_persist_dir.as_posix()}"\ncollection = "cli_boom_col"\n',
            encoding="utf-8",
        )
        with patch.dict(PROFILES, {"BOOM_CLI": boom_profile}):
            rc_err = main(
                [
                    "--config",
                    str(cfg),
                    "ingest",
                    str(doc),
                    "--profile",
                    "BOOM_CLI",
                ]
            )
        captured = capsys.readouterr()
        assert rc_err == 1
        assert captured.out == ""
        assert "Error: Enricher validation halted CLI run" in captured.err
        assert len(captured.err.strip().splitlines()) == 1
    finally:
        ENRICHERS._entries = saved_entries
        ENRICHERS._lazy_builtins = saved_lazy
        ENRICHERS._materializing = saved_mat


def test_cli_local_only_and_pii_policy_flags_and_toml_defaults(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI supports --local-only/--pii-policy positioning, TOML defaults, and safe errors."""
    corpus = tmp_path / "pii_cli_docs"
    corpus.mkdir()
    doc = corpus / "directory.md"
    doc.write_text(
        "# Contacts\n\nReach alex.rivera@example.test for badge activation.\n",
        encoding="utf-8",
    )
    blocked_doc = corpus / "blocked.md"
    blocked_doc.write_text(
        "# Restricted\n\nSSN 123-45-6789 is confidential.\n",
        encoding="utf-8",
    )
    fixture_path = tmp_path / "eval_fix.json"
    fixture_path.write_text(
        json.dumps(
            {"collection": "cli_pii_col", "queries": [{"question": "badge", "relevant_ids": ["x"]}]}
        ),
        encoding="utf-8",
    )

    json_policy = tmp_path / "pii_policy.json"
    json_policy.write_text(
        json.dumps(
            {
                "types": {
                    "EMAIL_ADDRESS": "tokenize",
                    "US_SSN": "block",
                },
                "token_salt": "cli-test-salt",
                "egress": "redact",
            }
        ),
        encoding="utf-8",
    )
    toml_policy = tmp_path / "pii_policy.toml"
    toml_policy.write_text(
        'token_salt = "cli-toml-salt"\negress = "block"\n[types]\nEMAIL_ADDRESS = "redact"\n',
        encoding="utf-8",
    )

    # 1. Parser accepts --local-only / --no-local-only before & after all 6 commands.
    for cmd_tail in (
        ["ingest", str(doc)],
        ["sync", str(corpus)],
        ["reindex", "--model", "local/m"],
        ["query", "badge"],
        ["ask", "badge"],
        ["eval", "--fixture", str(fixture_path)],
    ):
        ns_before = build_parser().parse_args(["--local-only", *cmd_tail])
        ns_after = build_parser().parse_args([*cmd_tail, "--local-only"])
        ns_no_after = build_parser().parse_args([*cmd_tail, "--no-local-only"])
        assert ns_before.local_only is True
        assert ns_after.local_only is True
        assert ns_no_after.local_only is False

    # 2. --local-only execution refuses remote models prior to LiteLLM transport.
    for remote_argv in (
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--local-only",
            "ingest",
            str(doc),
            "--embed-model",
            "openai/text-embedding-3-small",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "sync",
            str(corpus),
            "--embed-model",
            "openai/text-embedding-3-small",
            "--local-only",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "reindex",
            "--model",
            "openai/text-embedding-3-small",
            "--local-only",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--local-only",
            "query",
            "badge",
            "--embed-model",
            "openai/text-embedding-3-small",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "eval",
            "--fixture",
            str(fixture_path),
            "--embed-model",
            "openai/text-embedding-3-small",
            "--local-only",
        ],
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "ask",
            "badge",
            "--model",
            "openai/gpt-4o-mini",
            "--local-only",
        ],
    ):
        rc_remote = main(remote_argv)
        assert rc_remote == 1
        cap_rem = capsys.readouterr()
        assert cap_rem.out == ""
        assert cap_rem.err.startswith("Error:")
        assert len(cap_rem.err.strip().splitlines()) == 1
    assert mock_litellm_offline["embedding"] == []
    assert mock_litellm_offline["completion"] == []

    # 3. --pii-policy JSON works before/after ingest and writes scrubbed output + audit log.
    rc_ing = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_pii_col",
            "--pii-policy",
            str(json_policy),
            "ingest",
            str(doc),
        ]
    )
    assert rc_ing == 0
    _ = capsys.readouterr()
    assert (tmp_persist_dir / "manifests" / "cli_pii_col.audit.jsonl").exists()

    # 4. --pii-policy TOML after sync fails closed cleanly on blocked SSN without stderr leak.
    rc_sync_blk = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_pii_col",
            "sync",
            str(corpus),
            "--pii-policy",
            str(json_policy),
        ]
    )
    assert rc_sync_blk == 1
    cap_blk = capsys.readouterr()
    assert "US_SSN" in cap_blk.err
    assert "123-45-6789" not in cap_blk.err

    # 5. --pii-policy TOML on ask (before & after) scrubs/blocks remote completion safely.
    rc_ask_toml = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_pii_col",
            "ask",
            "Contact alex.rivera@example.test",
            "--model",
            "openai/gpt-4o-mini",
            "--pii-policy",
            str(toml_policy),
        ]
    )
    assert rc_ask_toml == 1
    cap_ask_blk = capsys.readouterr()
    assert "EMAIL_ADDRESS" in cap_ask_blk.err
    assert "alex.rivera@example.test" not in cap_ask_blk.err

    rc_ask_ok = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_pii_col",
            "--pii-policy",
            str(json_policy),
            "ask",
            "Mail alex.rivera@example.test please",
            "--model",
            "openai/gpt-4o-mini",
        ]
    )
    assert rc_ask_ok == 0
    _ = capsys.readouterr()
    last_sent = mock_litellm_offline["completion"][-1]["messages"]
    assert all("alex.rivera@example.test" not in m["content"] for m in last_sent)

    # 6. Misplaced --pii-policy on unsupported subcommands exits 1.
    for unsupported in ("status", "remove", "reindex", "query", "eval"):
        tail = (
            [unsupported]
            if unsupported == "status"
            else [unsupported, "x"]
            if unsupported in ("remove", "query")
            else [unsupported, "--model", "local/m"]
            if unsupported == "reindex"
            else [unsupported, "--fixture", str(fixture_path)]
        )
        for bad_cmd in (
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "--pii-policy",
                str(json_policy),
                *tail,
            ],
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                *tail,
                "--pii-policy",
                str(json_policy),
            ],
        ):
            assert main(bad_cmd) == 1
            cap_mis = capsys.readouterr()
            assert cap_mis.err.startswith("Error:")

    # 7. Unreadable / invalid policy files exit 1 cleanly.
    bad_json = tmp_path / "broken_policy.json"
    bad_json.write_text("{not json", encoding="utf-8")
    bad_schema = tmp_path / "bad_schema.json"
    bad_schema.write_text('{"unknown": true}', encoding="utf-8")
    for err_policy in (tmp_path / "missing.json", bad_json, bad_schema):
        assert (
            main(
                [
                    "--no-config",
                    "--persist-dir",
                    str(tmp_persist_dir),
                    "ingest",
                    str(doc),
                    "--pii-policy",
                    str(err_policy),
                ]
            )
            == 1
        )
        assert capsys.readouterr().err.startswith("Error:")

    # 8. docpipe.toml local_only + pii_policy (path or inline table) & --no-local-only override.
    toml_cfg = tmp_path / "docpipe_pii.toml"
    toml_cfg.write_text(
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        'collection = "cli_pii_col"\n'
        "local_only = true\n"
        f'pii_policy = "{json_policy.as_posix()}"\n',
        encoding="utf-8",
    )
    assert main(["--config", str(toml_cfg), "query", "badge", "--embed-model", "openai/embed"]) == 1
    assert "local_only" in capsys.readouterr().err
    assert main(["--config", str(toml_cfg), "query", "badge", "--no-local-only"]) == 0
    _ = capsys.readouterr()
    assert (
        main(
            [
                "--config",
                str(toml_cfg),
                "--no-local-only",
                "ask",
                "Mail alex.rivera@example.test",
                "--model",
                "openai/gpt-4o-mini",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()
    last_toml_sent = mock_litellm_offline["completion"][-1]["messages"]
    assert all("alex.rivera@example.test" not in m["content"] for m in last_toml_sent)

    toml_inline_cfg = tmp_path / "docpipe_inline_pii.toml"
    toml_inline_cfg.write_text(
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        'collection = "cli_pii_col"\n'
        "[pii_policy]\n"
        'token_salt = "inline-salt"\n'
        "[pii_policy.types]\n"
        'EMAIL_ADDRESS = "redact"\n',
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--config",
                str(toml_inline_cfg),
                "ask",
                "Mail alex.rivera@example.test",
                "--model",
                "openai/gpt-4o-mini",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()
    last_inline = mock_litellm_offline["completion"][-1]["messages"]
    assert any("[EMAIL_ADDRESS]" in m["content"] for m in last_inline)


def test_cli_where_filtering_and_validation_across_subcommands(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI --where works across query, ask, and eval and fails fast on invalid inputs."""
    from docpipe_maestro import ingest

    doc_a = tmp_path / "a_policy.md"
    doc_a.write_text(
        "## Section 1: Tier A=B\n\n1.1 Annual stipend limit is 500 euros.\n",
        encoding="utf-8",
    )
    doc_b = tmp_path / "b_guide.md"
    doc_b.write_text(
        "## Section 1: Travel Guide\n\nUse public rail passes when traveling domestically.\n",
        encoding="utf-8",
    )
    ingest(doc_a, profile="POLICY", collection="cli_where", persist_dir=tmp_persist_dir)
    ingest(doc_b, profile="DEFAULT", collection="cli_where", persist_dir=tmp_persist_dir)

    # 1. query with chunk filter, '=' preserved in value, int chunk_index, and profile filter
    for args in (
        [
            "--no-config",
            "--collection",
            "cli_where",
            "--persist-dir",
            str(tmp_persist_dir),
            "query",
            "stipend",
            "--where",
            "source=a_policy.md",
            "--where",
            "section=Section 1: Tier A=B",
            "--where",
            "chunk_index=0",
            "--expand-parent",
            "--searcher",
            "fts5_hybrid",
            "--json",
        ],
        [
            "--no-config",
            "--collection",
            "cli_where",
            "--persist-dir",
            str(tmp_persist_dir),
            "query",
            "stipend",
            "--where",
            "profile=policy",
            "--json",
        ],
    ):
        assert main(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["results"]
        assert all(item["metadata"]["source"] == "a_policy.md" for item in payload["results"])

    # 2. Repeating the same equality key performs $in set membership across multiple sources
    assert (
        main(
            [
                "--no-config",
                "--collection",
                "cli_where",
                "--persist-dir",
                str(tmp_persist_dir),
                "query",
                "rail passes stipend",
                "--where",
                "source=a_policy.md",
                "--where",
                "source=b_guide.md",
                "--json",
            ]
        )
        == 0
    )
    multi_sources = {
        r["metadata"]["source"] for r in json.loads(capsys.readouterr().out)["results"]
    }
    assert multi_sources <= {"a_policy.md", "b_guide.md"} and len(multi_sources) >= 1

    # 3. ask with non-matching source yields clean EMPTY_CONTEXT_REFUSAL and 0 LLM calls
    comp_before = len(mock_litellm_offline["completion"])
    assert (
        main(
            [
                "--no-config",
                "--collection",
                "cli_where",
                "--persist-dir",
                str(tmp_persist_dir),
                "ask",
                "What is the stipend?",
                "--where",
                "ingested_after=2099-01-01",
                "--json",
            ]
        )
        == 0
    )
    ask_empty = json.loads(capsys.readouterr().out)
    assert ask_empty["answer"] == "Not found in the provided context."
    assert len(mock_litellm_offline["completion"]) == comp_before

    # 4. eval --where filters evaluation cleanly
    from docpipe_maestro import status as _status

    st = _status(collection="cli_where", persist_dir=tmp_persist_dir)
    a_pids = next(r.parent_ids for r in st.sources if r.source == "a_policy.md")
    fix_path = tmp_path / "cli_where_fixture.json"
    fix_path.write_text(
        json.dumps(
            {
                "collection": "cli_where",
                "queries": [{"question": "annual stipend limit", "relevant_ids": list(a_pids)}],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "eval",
                "--fixture",
                str(fix_path),
                "--where",
                "source=a_policy.md",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["aggregate"]["mrr"] == pytest.approx(1.0)

    # 5. All invalid CLI --where arguments exit with code 1 and 0 embed/LLM calls
    emb_before = len(mock_litellm_offline["embedding"])
    bad_flag_lists = [
        ["--where", "broken_no_equals"],
        ["--where", "=val"],
        ["--where", "source="],
        ["--where", "source=   "],
        ["--where", "page=abc"],
        ["--where", "chunk_index=1.5"],
        ["--where", "page=true"],
        ["--where", "typo=val"],
        ["--where", "type=parent"],
        ["--where", "ingested_after=not-a-date"],
        ["--where", "ingested_after=2026-01-01", "--where", "ingested_after=2026-02-01"],
        ["--where", "ingested_before=2026-01-01", "--where", "ingested_before=2026-02-01"],
    ]
    for subcmd in ("query", "ask"):
        for flags in bad_flag_lists:
            rc = main(
                [
                    "--no-config",
                    "--collection",
                    "cli_where",
                    "--persist-dir",
                    str(tmp_persist_dir),
                    subcmd,
                    "stipend",
                    *flags,
                ]
            )
            assert rc == 1
            assert "Error:" in capsys.readouterr().err

    assert (
        main(
            [
                "--no-config",
                "--persist-dir",
                str(tmp_persist_dir),
                "eval",
                "--fixture",
                str(fix_path),
                "--where",
                "type=parent",
            ]
        )
        == 1
    )
    assert "Error:" in capsys.readouterr().err
    assert len(mock_litellm_offline["embedding"]) == emb_before
    assert len(mock_litellm_offline["completion"]) == comp_before


def test_cli_structured_logging_flags_isolation_and_handler_cleanup(
    tmp_path: Path,
    tmp_persist_dir: Path,
    mock_litellm_offline: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify --log-json/--log-level before/after subcommands, stderr-only logs, and cleanup."""
    import logging

    from docpipe_maestro.log import get_logger

    corpus = tmp_path / "cli_log_docs"
    corpus.mkdir()
    (corpus / "leave.md").write_text(
        "# Leave Rules\n\n## Section 1\n\n1.1 Full-time staff receive 22 days leave.\n",
        encoding="utf-8",
    )

    root_logger = logging.getLogger()
    root_handlers_before = list(root_logger.handlers)
    pkg_logger = get_logger()
    assert pkg_logger.level == logging.NOTSET

    # 1. Invalid --log-level exits cleanly with argparse error.
    with pytest.raises(SystemExit) as bad_lvl:
        main(["--no-config", "--log-level", "TRACE", "status"])
    assert bad_lvl.value.code == 2
    capsys.readouterr()

    # 2. --log-json before subcommand defaults to INFO (excludes DEBUG per-doc events).
    rc = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_log",
            "--log-json",
            "ingest",
            str(corpus),
        ]
    )
    assert rc == 0
    cap = capsys.readouterr()
    assert "Ingested 1 file(s)" in cap.out
    assert "stage.end" not in cap.out
    err_lines = [json.loads(line) for line in cap.err.strip().splitlines()]
    assert [r["fields"]["stage"] for r in err_lines] == [
        "intake",
        "clean",
        "enrich",
        "chunk",
        "embed",
        "store",
    ]
    assert all(r["level"] == "INFO" for r in err_lines)
    assert len({r["correlation_id"] for r in err_lines}) == 1

    # 3. Flags placed AFTER subcommand keep query/ask --json stdout 100% pure JSON.
    rc_q = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_log",
            "query",
            "annual leave days",
            "--json",
            "--log-json",
            "--log-level",
            "debug",
        ]
    )
    assert rc_q == 0
    cap_q = capsys.readouterr()
    q_payload = json.loads(cap_q.out)
    assert q_payload["collection"] == "cli_log"
    assert len(q_payload["results"]) >= 1
    q_err = [json.loads(line) for line in cap_q.err.strip().splitlines()]
    assert [r["fields"]["stage"] for r in q_err] == ["embed", "search"]
    assert len({r["correlation_id"] for r in q_err}) == 1

    # 4. Multi-step `ask --json` correlates retrieve + answer under one CLI correlation_id.
    rc_a = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_log",
            "ask",
            "How many leave days?",
            "--json",
            "--log-json",
        ]
    )
    assert rc_a == 0
    cap_a = capsys.readouterr()
    a_payload = json.loads(cap_a.out)
    assert "answer" in a_payload
    a_err = [json.loads(line) for line in cap_a.err.strip().splitlines()]
    assert [r["fields"]["stage"] for r in a_err] == ["embed", "search", "answer"]
    assert len({r["correlation_id"] for r in a_err}) == 1

    # 5. Standalone --log-level (without --log-json) emits human-readable stderr text only.
    rc_txt = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--collection",
            "cli_log",
            "--log-level",
            "INFO",
            "status",
            "--json",
        ]
    )
    assert rc_txt == 0
    cap_txt = capsys.readouterr()
    assert json.loads(cap_txt.out)["collection"] == "cli_log"
    assert "INFO [" in cap_txt.err
    assert "stage.end" in cap_txt.err
    with pytest.raises(json.JSONDecodeError):
        json.loads(cap_txt.err.strip().splitlines()[0])

    # 6. docpipe.toml log keys (log_json / log_level) are ignored when CLI flags are omitted.
    cfg_file = tmp_path / "log_ignore.toml"
    cfg_file.write_text(
        f'collection = "cli_log"\n'
        f'persist_dir = "{tmp_persist_dir.as_posix()}"\n'
        'log_json = true\nlog_level = "DEBUG"\n',
        encoding="utf-8",
    )
    rc_cfg = main(["--config", str(cfg_file), "status", "--json"])
    assert rc_cfg == 0
    cap_cfg = capsys.readouterr()
    assert json.loads(cap_cfg.out)["collection"] == "cli_log"
    assert cap_cfg.err == ""

    # 7. Repeated calls (and failed exit-1 calls) never leak handlers or mutate root logger.
    rc_fail = main(
        [
            "--no-config",
            "--persist-dir",
            str(tmp_persist_dir),
            "--log-json",
            "query",
            "x",
            "--where",
            "type=parent",
        ]
    )
    assert rc_fail == 1
    assert "Error:" in capsys.readouterr().err
    assert [type(h) for h in pkg_logger.handlers] == [logging.NullHandler]
    assert pkg_logger.level == logging.NOTSET
    assert list(root_logger.handlers) == root_handlers_before

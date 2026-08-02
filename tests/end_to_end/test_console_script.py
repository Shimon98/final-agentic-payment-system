"""Installed ``agentic-payments`` console-script smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _console_script() -> Path:
    executable = Path(sys.executable).with_name(
        "agentic-payments.exe" if os.name == "nt" else "agentic-payments"
    )
    assert executable.is_file()
    return executable


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("LLM_API_KEY", None)
    return subprocess.run(
        [str(_console_script()), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )


def test_console_script_help() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert "agentic-payments" in result.stdout
    assert result.stderr == ""


def test_console_script_demo() -> None:
    result = _run("demo")

    assert result.returncode == 0
    assert "Demo completed successfully." in result.stdout
    assert "0501234567" not in result.stdout
    assert "0509876543" not in result.stdout
    assert "Traceback" not in result.stdout + result.stderr

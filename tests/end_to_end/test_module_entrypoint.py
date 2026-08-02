"""Subprocess coverage for ``python -m agentic_payments``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("LLM_API_KEY", None)
    return subprocess.run(
        [sys.executable, "-m", "agentic_payments", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )


def test_module_help_is_safe_utf8() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert "agentic-payments" in result.stdout
    assert "interactive" in result.stdout
    assert result.stderr == ""


def test_module_demo_is_successful_without_phone_or_traceback() -> None:
    result = _run("demo")

    assert result.returncode == 0
    assert "Demo completed successfully." in result.stdout
    assert "0501234567" not in result.stdout
    assert "0509876543" not in result.stdout
    assert "Traceback" not in result.stdout + result.stderr


def test_module_unsafe_reset_is_refused_before_bootstrap() -> None:
    result = _run("reset")

    assert result.returncode == 2
    assert "Reset refused: pass --yes to confirm." in result.stdout
    assert "Traceback" not in result.stdout + result.stderr

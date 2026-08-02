"""Interactive CLI through a production-built application."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from agentic_payments.bootstrap import build_application
from agentic_payments.infrastructure import Settings
from agentic_payments.presentation.cli import run_interactive


class _Console:
    def __init__(self, lines: list[str | None]) -> None:
        self.lines = deque(lines)
        self.output: list[str] = []

    async def read_line(self, prompt: str) -> str | None:
        return self.lines.popleft()

    def write_line(self, text: str) -> None:
        self.output.append(text)


@pytest.mark.asyncio
async def test_interactive_ordinary_request_status_and_clean_exit(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )
    container = await build_application(settings)
    console = _Console(
        [
            'createUser name="Alice" phone=0501111111 initial_balance=100.00',
            "/status",
            "/exit",
        ]
    )

    result = await run_interactive(container, console=console)

    rendered = "\n".join(console.output)
    assert result == 0
    assert len(container.snapshot().users) == 1
    assert '"agent_name": "OrchestratorAgent"' in rendered
    assert '"user_count": 1' in rendered
    assert "0501111111" not in rendered
    assert "Traceback" not in rendered

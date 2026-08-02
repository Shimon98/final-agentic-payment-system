"""Unit tests for exact interactive command behavior."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, cast

import pytest

from agentic_payments.application import AgentResult, ApplicationState, MemoryService
from agentic_payments.bootstrap import ApplicationContainer
from agentic_payments.infrastructure import OutboxFlushResult, Settings
from agentic_payments.presentation.cli import ConsolePort, run_interactive


class _Console:
    def __init__(self, lines: list[str | None]) -> None:
        self.lines = deque(lines)
        self.prompts: list[str] = []
        self.output: list[str] = []

    async def read_line(self, prompt: str) -> str | None:
        self.prompts.append(prompt)
        return self.lines.popleft()

    def write_line(self, text: str) -> None:
        self.output.append(text)


class _TransactionManager:
    @property
    def current_state(self) -> ApplicationState:
        return ApplicationState()


class _Orchestrator:
    def __init__(self, *, fail: bool = False) -> None:
        self.inputs: list[str] = []
        self.fail = fail

    async def handle(self, user_input: str) -> AgentResult:
        self.inputs.append(user_input)
        if self.fail:
            raise RuntimeError("API_KEY=do-not-leak")
        return AgentResult("OrchestratorAgent", {"message": "ok"})


class _Outbox:
    def __init__(self) -> None:
        self.calls = 0

    async def flush_pending(self) -> OutboxFlushResult:
        self.calls += 1
        return OutboxFlushResult(0, 0, 0, 0, (), 0)


def _container(
    tmp_path: Path, *, fail: bool = False
) -> tuple[ApplicationContainer, _Orchestrator, _Outbox]:
    orchestrator = _Orchestrator(fail=fail)
    outbox = _Outbox()
    settings = Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )
    container = ApplicationContainer(
        settings=settings,
        state_repository=cast(Any, object()),
        audit_repository=cast(Any, object()),
        lock_manager=cast(Any, object()),
        transaction_manager=cast(Any, _TransactionManager()),
        memory_service=MemoryService(),
        outbox_dispatcher=cast(Any, outbox),
        orchestrator=cast(Any, orchestrator),
        llm_runtime=None,
        startup_outbox_result=None,
        startup_warnings=(),
    )
    return container, orchestrator, outbox


@pytest.mark.asyncio
async def test_ordinary_request_is_formatted(tmp_path: Path) -> None:
    container, orchestrator, outbox = _container(tmp_path)
    console = _Console(["checkBalance user_id=USR-1", "/exit"])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    assert orchestrator.inputs == ["checkBalance user_id=USR-1"]
    assert any('"agent_name": "OrchestratorAgent"' in line for line in console.output)
    assert outbox.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/exit", "exit", "quit", None])
async def test_clean_exit_aliases_and_eof_flush_once(tmp_path: Path, command: str | None) -> None:
    container, orchestrator, outbox = _container(tmp_path)
    console = _Console([command])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    assert orchestrator.inputs == []
    assert outbox.calls == 1
    assert console.output[-1] == "Goodbye. / להתראות."


@pytest.mark.asyncio
async def test_help_status_and_flush_do_not_call_orchestrator(tmp_path: Path) -> None:
    container, orchestrator, outbox = _container(tmp_path)
    console = _Console(["/help", "/status", "/flush", "/exit"])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    assert orchestrator.inputs == []
    assert "createUser" in console.output[1]
    assert '"user_count": 0' in console.output[2]
    assert '"pending_after": 0' in console.output[3]
    assert outbox.calls == 2


@pytest.mark.asyncio
async def test_reset_requires_exact_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, orchestrator, _ = _container(tmp_path)
    calls = 0

    async def reset_state(self: ApplicationContainer) -> OutboxFlushResult:
        nonlocal calls
        calls += 1
        return OutboxFlushResult(0, 0, 0, 0, (), 0)

    monkeypatch.setattr(ApplicationContainer, "reset_state", reset_state)
    console = _Console(["/reset", "RESET", "/exit"])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    assert calls == 1
    assert "Type RESET to confirm: " in console.prompts
    assert "State reset completed safely." in console.output
    assert orchestrator.inputs == []


@pytest.mark.asyncio
async def test_reset_refusal_does_not_call_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, _, _ = _container(tmp_path)
    reset = pytest.fail
    monkeypatch.setattr(ApplicationContainer, "reset_state", reset)
    console = _Console(["/reset", "reset", "/exit"])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    assert "Reset refused." in console.output
    assert "reset" not in console.output


@pytest.mark.asyncio
async def test_empty_input_is_ignored(tmp_path: Path) -> None:
    container, orchestrator, _ = _container(tmp_path)
    console = _Console(["", "   ", "/exit"])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    assert orchestrator.inputs == []


@pytest.mark.asyncio
async def test_unexpected_request_error_is_generic_and_loop_remains_usable(tmp_path: Path) -> None:
    container, _, _ = _container(tmp_path, fail=True)
    console = _Console(["unsafe request", "/exit"])

    assert await run_interactive(container, console=cast(ConsolePort, console)) == 0
    rendered = "\n".join(console.output)
    assert "Request could not be completed safely." in rendered
    assert "API_KEY" not in rendered
    assert "Traceback" not in rendered

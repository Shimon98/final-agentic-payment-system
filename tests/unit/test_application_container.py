"""Unit coverage for the Phase 9 application container."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import agentic_payments.bootstrap as bootstrap
from agentic_payments.agents import HybridRouterAgent, RouterAgent
from agentic_payments.bootstrap import ApplicationContainer, build_application
from agentic_payments.infrastructure import OutboxFlushResult, Settings


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "llm_provider": "rule_based",
        "enable_llm_router": False,
        "state_file": tmp_path / "state.json",
        "audit_file": tmp_path / "audit.jsonl",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_build_returns_exact_container_and_rule_router(tmp_path: Path) -> None:
    container = await build_application(_settings(tmp_path))

    assert isinstance(container, ApplicationContainer)
    assert isinstance(container.orchestrator._router_agent, RouterAgent)
    assert container.llm_runtime is None
    assert container.startup_outbox_result is not None
    assert container.startup_outbox_result.pending_after == 0


@pytest.mark.asyncio
async def test_snapshot_is_an_independent_clone(tmp_path: Path) -> None:
    container = await build_application(_settings(tmp_path))

    first = container.snapshot()
    second = container.snapshot()
    first.users.clear()

    assert first is not second
    assert second == container.snapshot()


@pytest.mark.asyncio
async def test_flush_delegates_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = await build_application(_settings(tmp_path))
    expected = OutboxFlushResult(0, 0, 0, 0, (), 0)
    flush = AsyncMock(return_value=expected)
    monkeypatch.setattr(container.outbox_dispatcher, "flush_pending", flush)

    assert await container.flush_outbox() is expected
    flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_llm_mode_wires_hybrid_without_constructing_provider_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_model = AsyncMock(side_effect=AssertionError("provider model must stay lazy"))
    monkeypatch.setattr(bootstrap.AgentsModelFactory, "create_model", create_model)
    settings = _settings(
        tmp_path,
        llm_provider="openai_compatible",
        enable_llm_router=True,
        llm_model="test-model",
        llm_base_url="https://example.invalid/v1",
    )

    container = await build_application(settings)

    assert isinstance(container.orchestrator._router_agent, HybridRouterAgent)
    assert container.llm_runtime is not None
    create_model.assert_not_awaited()


def test_hybrid_compatibility_limitation_is_documented() -> None:
    source = Path(bootstrap.__file__).read_text(encoding="utf-8")

    assert "no real correlation or memory parameters" in source
    assert "compatibility marker and empty memory" in source

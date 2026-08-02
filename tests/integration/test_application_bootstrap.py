"""Integration coverage for the exact Phase 9 bootstrap sequence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import agentic_payments.bootstrap as bootstrap
from agentic_payments.application import ApplicationState, BusinessMemory
from agentic_payments.bootstrap import build_application
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import (
    JsonLinesAuditRepository,
    JsonStateRepository,
    Settings,
    StatePersistenceError,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        llm_provider="rule_based",
        enable_llm_router=False,
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )


def _event() -> AuditEvent:
    return AuditEvent(
        event_id="AUD-BOOT",
        correlation_id="COR-BOOT",
        action="BOOTSTRAP_TEST",
        status="SUCCESS",
        occurred_at=datetime(2026, 8, 2, 8, 0, tzinfo=UTC),
        actor="system",
        details={"source": "test"},
    )


@pytest.mark.asyncio
async def test_build_loads_state_memory_and_flushes_startup_outbox(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    event = _event()
    persisted = ApplicationState(
        memory=BusinessMemory(last_action="persisted_action"),
        pending_audit_events={event.event_id: event},
    )
    await JsonStateRepository(settings.state_file).save_atomic(persisted)

    container = await build_application(settings)

    assert container.settings is settings
    assert container.snapshot().memory.last_action == "persisted_action"
    assert container.memory_service.snapshot().last_action == "persisted_action"
    assert container.startup_outbox_result is not None
    assert container.startup_outbox_result.delivered == 1
    assert container.startup_outbox_result.pending_after == 0
    assert await JsonLinesAuditRepository(settings.audit_file).list_all() == [event]


class _UnavailableAuditRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def append(self, event: AuditEvent) -> None:
        raise OSError("sensitive append detail")

    async def list_all(self) -> list[AuditEvent]:
        raise OSError("sensitive init detail")

    async def find_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        return []

    def contains_event_id(self, event_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_audit_startup_failure_becomes_one_safe_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "JsonLinesAuditRepository", _UnavailableAuditRepository)

    container = await build_application(_settings(tmp_path))

    assert container.startup_outbox_result is None
    assert len(container.startup_warnings) == 1
    warning = container.startup_warnings[0]
    assert "OSError" in warning
    assert "sensitive" not in warning
    assert str(tmp_path) not in warning
    assert "Traceback" not in warning


@pytest.mark.asyncio
async def test_invalid_existing_state_fails_construction(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.state_file.write_text("{malformed", encoding="utf-8")

    with pytest.raises(StatePersistenceError):
        await build_application(settings)

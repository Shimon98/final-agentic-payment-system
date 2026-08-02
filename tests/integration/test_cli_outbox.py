"""Pending audit retry across a production application restart."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.bootstrap import build_application
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import JsonStateRepository, Settings


@pytest.mark.asyncio
async def test_pending_audit_is_retried_and_removed_after_restart(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    settings = Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=audit_path,
    )
    event = AuditEvent(
        event_id="AUD-RETRY",
        correlation_id="COR-RETRY",
        action="RETRY",
        status="SUCCESS",
        occurred_at=datetime(2026, 8, 2, 8, 30, tzinfo=UTC),
        actor="system",
        details={"safe": True},
    )
    await JsonStateRepository(settings.state_file).save_atomic(
        ApplicationState(pending_audit_events={event.event_id: event})
    )
    audit_path.mkdir()

    first = await build_application(settings)

    assert first.startup_outbox_result is None
    assert len(first.snapshot().pending_audit_events) == 1
    audit_path.rmdir()

    second = await build_application(settings)

    assert second.startup_outbox_result is not None
    assert second.startup_outbox_result.delivered == 1
    assert second.startup_outbox_result.pending_after == 0
    assert second.snapshot().pending_audit_events == {}
    assert "AUD-RETRY" in audit_path.read_text(encoding="utf-8")

"""Orchestrator audit-outbox success and ordinary-failure behavior."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
)


class _FailingOutbox:
    async def flush_pending(self) -> object:
        raise OSError("private path must not escape")


@pytest.mark.asyncio
async def test_real_outbox_flushes_committed_audit_events(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-O",
        correlation_id="COR-O",
        requested_at=NOW,
    )

    assert result.metadata["outbox"]["outbox_flush_succeeded"] is True
    assert result.metadata["outbox"]["delivered"] == 1
    assert system.payment.manager.current_state.pending_audit_events == {}
    assert len(system.audit.events) == 1


@pytest.mark.asyncio
async def test_outbox_exception_preserves_primary_result_and_is_safe(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory, outbox=_FailingOutbox())
    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-OF",
        requested_at=NOW,
    )

    assert result.agent_name == "OrchestratorAgent"
    assert result.metadata["outbox"] == {
        "outbox_flush_succeeded": False,
        "error_type": "OSError",
        "message": "Audit outbox flush failed",
    }
    assert "private path" not in str(result.metadata)

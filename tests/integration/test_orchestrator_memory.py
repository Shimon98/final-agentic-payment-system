"""Business-memory update and transactional persistence tests."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import InMemoryStateRepository

from agentic_payments.application import AgentResult
from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
    create_users,
)


class _FailOnConfiguredSaveRepository(InMemoryStateRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_on_call: int | None = None

    async def save_atomic(self, state: Any) -> None:
        next_call = self.save_calls + 1
        if self.fail_on_call == next_call:
            self.save_calls = next_call
            raise OSError("configured memory persistence failure")
        await super().save_atomic(state)


class _FailingFraudAgent:
    async def assess_transaction(self, snapshot: Any) -> AgentResult:
        raise RuntimeError("configured post-processing failure")


@pytest.mark.asyncio
async def test_entities_results_and_one_timestamp_are_persisted(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    result = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=20.00",
        idempotency_key="IDEMP-MEM",
        correlation_id="COR-MEM",
        requested_at=NOW,
    )

    memory = system.payment.manager.current_state.memory
    assert memory.last_transaction_id == result.output["transaction_id"]
    assert memory.last_result["agent_name"] == "PaymentFacade"
    assert {entry.occurred_at for entry in memory.recent_actions[-3:]} == {NOW}
    assert result.metadata["memory_persisted"] is True


@pytest.mark.asyncio
async def test_memory_persistence_failure_after_commit_remains_success(
    payment_harness_factory: Any,
) -> None:
    repository = _FailOnConfiguredSaveRepository()
    system = build_system(
        payment_harness_factory,
        repository=repository,
        fraud_agent=_FailingFraudAgent(),
    )
    first, second = await create_users(system)
    repository.fail_on_call = repository.save_calls + 2

    result = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=20.00",
        idempotency_key="IDEMP-MEM-FAIL",
        requested_at=NOW,
    )

    assert result.agent_name == "OrchestratorAgent"
    assert result.metadata["memory_persisted"] is False
    assert result.metadata["memory_error_type"] == "OSError"
    assert system.payment.manager.current_state.wallets[first].balance == 980
    assert len(system.payment.manager.current_state.transactions) == 1
    assert result.output["post_processing_status"] == "degraded"
    assert "configured memory" not in str(result.metadata)

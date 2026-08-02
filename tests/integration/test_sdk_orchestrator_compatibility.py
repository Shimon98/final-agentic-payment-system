"""The existing Phase 7 orchestrator accepts HybridRouterAgent structurally."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import DeterministicIdGenerator, FixedClock

from agentic_payments.agents import (
    CriticAgent,
    FallbackAgent,
    HybridRouterAgent,
    ReflectionAgent,
    RouterAgent,
)
from agentic_payments.application import AgentResult, BusinessMemory, MemoryService
from agentic_payments.application.orchestrator import OrchestratorAgent
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.infrastructure import OutboxFlushResult
from agentic_payments.tools import PaymentToolRegistry, ToolGuardrails

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class NeverCalledGateway:
    async def route(self, **_kwargs: Any) -> object:
        raise AssertionError("disabled LLM gateway must not be called")


class EmptyOutbox:
    async def flush_pending(self) -> OutboxFlushResult:
        return OutboxFlushResult(0, 0, 0, 0, (), 0)


@pytest.mark.asyncio
async def test_existing_orchestrator_accepts_hybrid_router_without_api_change(
    payment_harness_factory: Any,
) -> None:
    facade = PaymentFacade.__new__(PaymentFacade)
    facade.check_balance = AsyncMock(
        return_value=AgentResult(
            "PaymentFacade",
            {
                "operation": "checkBalance",
                "user_id": "USR-1",
                "balance": "10.00",
                "currency": "ILS",
            },
        )
    )
    payment = payment_harness_factory()
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=NeverCalledGateway(),  # type: ignore[arg-type]
        llm_enabled=False,
    )
    orchestrator = OrchestratorAgent(
        router_agent=hybrid,
        tool_registry=PaymentToolRegistry(payment_facade=facade),
        tool_guardrails=ToolGuardrails(),
        critic_agent=CriticAgent(),
        reflection_agent=ReflectionAgent(),
        fallback_agent=FallbackAgent(),
        memory_service=MemoryService(BusinessMemory()),
        transaction_manager=payment.manager,
        audit_outbox_dispatcher=EmptyOutbox(),
        clock=FixedClock(NOW),
        id_generator=DeterministicIdGenerator(),
    )
    result = await orchestrator.handle(
        "checkBalance user_id=USR-1",
        correlation_id="CORR-1",
        requested_at=NOW,
    )
    assert result.agent_name == "OrchestratorAgent"
    assert result.output["balance"] == "10.00"
    assert facade.check_balance.await_count == 1

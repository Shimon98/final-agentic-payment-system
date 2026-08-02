"""Orchestrator routing, wrapping, context, and cancellation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import DeterministicIdGenerator, FixedClock

from agentic_payments.agents import CriticAgent, FallbackAgent, ReflectionAgent
from agentic_payments.application import (
    AgentResult,
    BusinessMemory,
    MemoryService,
    RouterDecision,
)
from agentic_payments.application.orchestrator import OrchestratorAgent
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import Intent
from agentic_payments.infrastructure import OutboxFlushResult
from agentic_payments.tools import PaymentToolRegistry, ToolGuardrails

NOW = datetime(2026, 8, 2, 14, 0, tzinfo=UTC)


class _Router:
    def __init__(self, output: object) -> None:
        self.output = output

    async def route(self, user_input: str) -> AgentResult:
        if isinstance(self.output, BaseException):
            raise self.output
        return AgentResult("Router", self.output)


class _Outbox:
    def __init__(self) -> None:
        self.calls = 0

    async def flush_pending(self) -> OutboxFlushResult:
        self.calls += 1
        return OutboxFlushResult(0, 0, 0, 0, (), 0)


def _build(
    payment_harness_factory: Any,
    decision: object,
) -> tuple[OrchestratorAgent, PaymentFacade, _Outbox]:
    facade = PaymentFacade.__new__(PaymentFacade)
    facade.check_balance = AsyncMock(
        return_value=AgentResult(
            "PaymentFacade",
            {
                "operation": "checkBalance",
                "user_id": "U1",
                "balance": "10.00",
                "currency": "ILS",
            },
        )
    )
    outbox = _Outbox()
    orchestrator = OrchestratorAgent(
        router_agent=_Router(decision),
        tool_registry=PaymentToolRegistry(payment_facade=facade),
        tool_guardrails=ToolGuardrails(),
        critic_agent=CriticAgent(),
        reflection_agent=ReflectionAgent(),
        fallback_agent=FallbackAgent(),
        memory_service=MemoryService(BusinessMemory()),
        transaction_manager=payment_harness_factory().manager,
        audit_outbox_dispatcher=outbox,
        clock=FixedClock(NOW),
        id_generator=DeterministicIdGenerator(),
    )
    return orchestrator, facade, outbox


@pytest.mark.asyncio
async def test_generated_and_supplied_context_values(
    payment_harness_factory: Any,
) -> None:
    decision = RouterDecision(
        intent=Intent.CHECK_BALANCE,
        parameters={"user_id": "U1"},
        confidence=1.0,
    )
    orchestrator, facade, outbox = _build(payment_harness_factory, decision)

    generated = await orchestrator.handle("check")
    supplied = await orchestrator.handle(
        "check",
        correlation_id="COR-SUPPLIED",
        idempotency_key="IDEMP-SUPPLIED",
        requested_at=NOW,
    )

    first_command = facade.check_balance.await_args_list[0].args[0]
    second_command = facade.check_balance.await_args_list[1].args[0]
    assert first_command.context.correlation_id == "CORR-GENERATED"
    assert first_command.context.idempotency_key == "IDEMP-CORR-GENERATED"
    assert second_command.context.correlation_id == "COR-SUPPLIED"
    assert second_command.context.idempotency_key == "IDEMP-SUPPLIED"
    assert generated.agent_name == supplied.agent_name == "OrchestratorAgent"
    assert outbox.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision",
    [
        RouterDecision(
            intent=Intent.UNKNOWN,
            parameters={},
            confidence=0.0,
            requires_clarification=True,
            clarification_question="Supported action?",
        ),
        RouterDecision(
            intent=Intent.CHECK_BALANCE,
            parameters={},
            confidence=0.6,
            requires_clarification=True,
            clarification_question="Which user?",
        ),
        RouterDecision(
            intent=Intent.CHECK_BALANCE,
            parameters={"user_id": "U1"},
            confidence=0.7,
        ),
    ],
)
async def test_unknown_clarification_and_low_confidence_use_fallback(
    payment_harness_factory: Any,
    decision: RouterDecision,
) -> None:
    orchestrator, facade, outbox = _build(payment_harness_factory, decision)

    result = await orchestrator.handle("unclear", requested_at=NOW)

    assert result.agent_name == "FallbackAgent"
    assert facade.check_balance.await_count == 0
    assert outbox.calls == 1
    assert result.metadata["correlation_id"] == "CORR-GENERATED"


@pytest.mark.asyncio
async def test_invalid_router_output_is_reflected(
    payment_harness_factory: Any,
) -> None:
    orchestrator, facade, _ = _build(payment_harness_factory, {"bad": True})

    result = await orchestrator.handle("bad route", requested_at=NOW)

    assert result.agent_name == "ReflectionAgent"
    assert result.metadata["error_handled"] is True
    assert facade.check_balance.await_count == 0


@pytest.mark.asyncio
async def test_cancellation_is_never_suppressed(payment_harness_factory: Any) -> None:
    orchestrator, _, _ = _build(
        payment_harness_factory,
        asyncio.CancelledError(),
    )
    with pytest.raises(asyncio.CancelledError):
        await orchestrator.handle("cancel", requested_at=NOW)

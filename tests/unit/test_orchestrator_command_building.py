"""Typed Orchestrator command construction tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from conftest import DeterministicIdGenerator, FixedClock

from agentic_payments.agents import CriticAgent, FallbackAgent, ReflectionAgent
from agentic_payments.application import (
    BusinessMemory,
    MemoryService,
    RequestContext,
    RouterDecision,
)
from agentic_payments.application.orchestrator import OrchestratorAgent
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import Intent
from agentic_payments.infrastructure import OutboxFlushResult
from agentic_payments.tools import PaymentToolRegistry, ToolGuardrails

NOW = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
CONTEXT = RequestContext("COR", "IDEMP", NOW)


class _UnusedRouter:
    async def route(self, user_input: str) -> Any:
        raise AssertionError("route must not be called")


class _Outbox:
    async def flush_pending(self) -> OutboxFlushResult:
        return OutboxFlushResult(0, 0, 0, 0, (), 0)


def _orchestrator(payment_harness_factory: Any) -> OrchestratorAgent:
    facade = PaymentFacade.__new__(PaymentFacade)
    return OrchestratorAgent(
        router_agent=_UnusedRouter(),
        tool_registry=PaymentToolRegistry(payment_facade=facade),
        tool_guardrails=ToolGuardrails(),
        critic_agent=CriticAgent(),
        reflection_agent=ReflectionAgent(),
        fallback_agent=FallbackAgent(),
        memory_service=MemoryService(BusinessMemory()),
        transaction_manager=payment_harness_factory().manager,
        audit_outbox_dispatcher=_Outbox(),
        clock=FixedClock(NOW),
        id_generator=DeterministicIdGenerator(),
    )


@pytest.mark.parametrize(
    ("intent", "parameters", "class_name"),
    [
        (
            Intent.CREATE_USER,
            {"name": "Name", "phone_number": "0501234567", "initial_balance": "1.00"},
            "CreateUserCommand",
        ),
        (Intent.CHECK_BALANCE, {"user_id": "U1"}, "CheckBalanceCommand"),
        (
            Intent.TRANSFER_MONEY,
            {"sender_id": "U1", "receiver_id": "U2", "amount": "1.00"},
            "TransferMoneyCommand",
        ),
        (
            Intent.REQUEST_PAYMENT,
            {"requester_id": "U1", "payer_id": "U2", "amount": Decimal("1.00")},
            "RequestPaymentCommand",
        ),
        (Intent.APPROVE_PAYMENT, {"request_id": "R1"}, "ApprovePaymentCommand"),
        (Intent.REJECT_PAYMENT, {"request_id": "R1"}, "RejectPaymentCommand"),
        (Intent.SHOW_TRANSACTIONS, {"user_id": "U1"}, "ShowTransactionsCommand"),
        (Intent.FRAUD_CHECK, {"transaction_id": "T1"}, "FraudCheckCommand"),
        (Intent.SECURITY_REVIEW, {"transaction_id": None}, "SecurityReviewCommand"),
        (Intent.EXPLAIN_LAST_ACTION, {}, "ExplainLastActionCommand"),
    ],
)
def test_all_ten_typed_commands_have_exact_context(
    payment_harness_factory: Any,
    intent: Intent,
    parameters: dict[str, object],
    class_name: str,
) -> None:
    orchestrator = _orchestrator(payment_harness_factory)
    decision = RouterDecision(intent=intent, parameters=parameters, confidence=1.0)

    command = orchestrator._build_command(decision, CONTEXT)

    assert type(command).__name__ == class_name
    assert command.context == CONTEXT  # type: ignore[attr-defined]
    assert command.context.actor == "user"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "parameters",
    [
        {"sender_id": "U1", "receiver_id": "U2"},
        {"sender_id": "U1", "receiver_id": "U2", "amount": "1e2"},
        {"sender_id": "U1", "receiver_id": "U2", "amount": 1.0},
        {"sender_id": "U1", "receiver_id": "U2", "amount": "1.00", "extra": "x"},
    ],
)
def test_command_construction_rejects_missing_extra_or_non_strict_money(
    payment_harness_factory: Any,
    parameters: dict[str, object],
) -> None:
    decision = RouterDecision(
        intent=Intent.TRANSFER_MONEY,
        parameters=parameters,
        confidence=1.0,
    )
    with pytest.raises(ValueError):
        _orchestrator(payment_harness_factory)._build_command(decision, CONTEXT)

"""Real deterministic Phase 7 application graph and business-flow tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from conftest import DeterministicIdGenerator, FixedClock

from agentic_payments.agents import (
    CriticAgent,
    ExplanationAgent,
    FallbackAgent,
    FraudDetectionAgent,
    PolicyAgent,
    ReflectionAgent,
    RouterAgent,
    SecurityAgent,
)
from agentic_payments.application import ApplicationState, MemoryService
from agentic_payments.application.orchestrator import OrchestratorAgent
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import AuditEvent, TransferPolicy
from agentic_payments.infrastructure import AuditOutboxDispatcher
from agentic_payments.tools import PaymentToolRegistry, ToolGuardrails

NOW = datetime(2026, 8, 2, 15, 0, tzinfo=UTC)


class MemoryAuditRepository:
    """Minimal idempotent audit repository for application integration tests."""

    def __init__(self) -> None:
        self.events: dict[str, AuditEvent] = {}

    async def append(self, event: AuditEvent) -> None:
        existing = self.events.get(event.event_id)
        if existing is not None and existing != event:
            raise ValueError("event ID conflict")
        self.events[event.event_id] = event

    async def list_all(self) -> list[AuditEvent]:
        return sorted(
            self.events.values(),
            key=lambda event: (event.occurred_at, event.event_id),
        )

    async def find_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        return [event for event in await self.list_all() if event.correlation_id == correlation_id]

    def contains_event_id(self, event_id: str) -> bool:
        return event_id in self.events


@dataclass(slots=True)
class SystemHarness:
    orchestrator: OrchestratorAgent
    payment: Any
    audit: MemoryAuditRepository
    memory: MemoryService


def transfer_policy() -> TransferPolicy:
    return TransferPolicy(
        maximum_single_transfer=Decimal("10000.00"),
        maximum_daily_transfer=Decimal("20000.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )


def build_system(
    payment_harness_factory: Any,
    *,
    initial_state: ApplicationState | None = None,
    repository: Any = None,
    ids: Any = None,
    clock: Any = None,
    fraud_agent: Any = None,
    critic_agent: Any = None,
    outbox: Any = None,
    tool_guardrails: Any = None,
) -> SystemHarness:
    policy = transfer_policy()
    payment = payment_harness_factory(
        initial_state=initial_state,
        repository=repository,
        ids=ids or DeterministicIdGenerator(),
        clock=clock or FixedClock(NOW),
        transfer_policy=policy,
    )
    facade = PaymentFacade(
        payment_service=payment.service,
        transaction_manager=payment.manager,
        fraud_agent=fraud_agent or FraudDetectionAgent(transfer_policy=policy),
        security_agent=SecurityAgent(),
        explanation_agent=ExplanationAgent(),
        policy_agent=PolicyAgent(transfer_policy=policy),
    )
    audit = MemoryAuditRepository()
    dispatcher = outbox or AuditOutboxDispatcher(
        transaction_manager=payment.manager,
        audit_repository=audit,
    )
    memory = MemoryService(payment.manager.current_state.memory)
    orchestrator = OrchestratorAgent(
        router_agent=RouterAgent(),
        tool_registry=PaymentToolRegistry(payment_facade=facade),
        tool_guardrails=tool_guardrails or ToolGuardrails(),
        critic_agent=critic_agent or CriticAgent(),
        reflection_agent=ReflectionAgent(),
        fallback_agent=FallbackAgent(),
        memory_service=memory,
        transaction_manager=payment.manager,
        audit_outbox_dispatcher=dispatcher,
        clock=clock or payment.clock,
        id_generator=ids or payment.ids,
    )
    return SystemHarness(orchestrator, payment, audit, memory)


async def create_users(system: SystemHarness) -> tuple[str, str]:
    first = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=1000.00',
        idempotency_key="IDEMP-CREATE-A",
        correlation_id="COR-CREATE-A",
        requested_at=NOW,
    )
    second = await system.orchestrator.handle(
        'createUser name="Bob" phone_number=0502222222 initial_balance=100.00',
        idempotency_key="IDEMP-CREATE-B",
        correlation_id="COR-CREATE-B",
        requested_at=NOW,
    )
    return first.output["user_id"], second.output["user_id"]


@pytest.mark.asyncio
async def test_all_ten_intents_execute_without_api_or_network(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    balance = await system.orchestrator.handle(f"checkBalance user_id={first}", requested_at=NOW)
    transfer = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=25.00",
        idempotency_key="IDEMP-T",
        requested_at=NOW,
    )
    pending = await system.orchestrator.handle(
        f"requestPayment requester_id={second} payer_id={first} amount=10.00",
        idempotency_key="IDEMP-R",
        requested_at=NOW,
    )
    approved = await system.orchestrator.handle(
        f"approvePayment request_id={pending.output['payment_request_id']}",
        idempotency_key="IDEMP-A",
        requested_at=NOW,
    )
    another = await system.orchestrator.handle(
        f"requestPayment requester_id={second} payer_id={first} amount=5.00",
        idempotency_key="IDEMP-R2",
        requested_at=NOW,
    )
    rejected = await system.orchestrator.handle(
        f"rejectPayment request_id={another.output['payment_request_id']}",
        idempotency_key="IDEMP-RJ",
        requested_at=NOW,
    )
    shown = await system.orchestrator.handle(f"showTransactions user_id={first}", requested_at=NOW)
    fraud = await system.orchestrator.handle(
        f"fraudCheck transaction_id={transfer.output['transaction_id']}",
        requested_at=NOW,
    )
    security = await system.orchestrator.handle("securityReview", requested_at=NOW)
    explained = await system.orchestrator.handle("explainLastAction", requested_at=NOW)

    assert balance.output["balance"] == "1000.00"
    assert transfer.output["operation"] == "transferMoney"
    assert approved.output["operation"] == "approvePayment"
    assert rejected.output["operation"] == "rejectPayment"
    assert shown.output["transactions"]
    assert fraud.output.transaction_id == transfer.output["transaction_id"]
    assert security.output.approved
    assert explained.output["facts"]
    assert all(
        result.agent_name == "OrchestratorAgent"
        for result in (
            balance,
            transfer,
            pending,
            approved,
            rejected,
            shown,
            fraud,
            security,
            explained,
        )
    )

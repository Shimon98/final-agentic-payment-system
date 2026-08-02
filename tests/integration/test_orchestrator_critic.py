"""Commit-aware guardrail and critic behavior after primary tool execution."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.application import AgentResult, CriticReview
from agentic_payments.tools import ToolGuardrails
from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
    create_users,
)
from tests.integration.test_orchestrator_memory import (
    _FailOnConfiguredSaveRepository,
)
from tests.integration.test_orchestrator_outbox import _FailingOutbox


class _RejectingCritic:
    def __init__(self) -> None:
        self.calls = 0

    async def review(self, result: AgentResult, expected_intent: Any) -> AgentResult:
        self.calls += 1
        return AgentResult(
            "Critic",
            CriticReview(
                approved=False,
                quality_score=2,
                problems=["forced_rejection"],
                requires_fallback=True,
            ),
        )


class _CancellingCritic:
    async def review(self, result: AgentResult, expected_intent: Any) -> AgentResult:
        raise asyncio.CancelledError


class _FailingCritic:
    async def review(self, result: AgentResult, expected_intent: Any) -> AgentResult:
        raise RuntimeError("private critic detail")


class _InvalidCritic:
    async def review(self, result: AgentResult, expected_intent: Any) -> AgentResult:
        return AgentResult("Critic", {"invalid": True})


class _FailingOutputGuardrails(ToolGuardrails):
    def validate_after_execution(self, *, intent: Any, result: AgentResult) -> None:
        raise RuntimeError("private guardrail detail")


def _assert_quality_warning(result: AgentResult, operation: str) -> None:
    assert result.agent_name == "OrchestratorAgent"
    assert result.output["operation"] == operation
    assert result.confidence <= 0.85
    assert result.metadata["primary_mutation_committed"] is True
    assert result.metadata["delivery_status"] == "committed_with_quality_warning"
    assert result.metadata["fallback_suppressed_reason"] == "primary_mutation_already_committed"
    assert "private" not in str(result.metadata)
    assert "Alice" not in str(result.metadata)
    assert "0501111111" not in str(result.metadata)


@pytest.mark.asyncio
async def test_create_user_critic_rejection_preserves_one_created_user(
    payment_harness_factory: Any,
) -> None:
    critic = _RejectingCritic()
    system = build_system(payment_harness_factory, critic_agent=critic)

    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-CRITIC-CREATE",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "createUser")
    state = system.payment.manager.current_state
    assert len(state.users) == len(state.wallets) == 1
    assert state.memory.last_user_id == result.output["user_id"]
    assert state.memory.last_result["agent_name"] == "PaymentFacade"
    assert critic.calls == 1


@pytest.mark.asyncio
async def test_transfer_critic_rejection_preserves_exactly_one_transfer(
    payment_harness_factory: Any,
) -> None:
    critic = _RejectingCritic()
    system = build_system(payment_harness_factory, critic_agent=critic)
    first, second = await create_users(system)

    result = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=25.00",
        idempotency_key="IDEMP-CRITIC-TRANSFER",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "transferMoney")
    state = system.payment.manager.current_state
    assert state.wallets[first].balance == Decimal("975.00")
    assert state.wallets[second].balance == Decimal("125.00")
    assert len(state.transactions) == 1
    assert state.memory.last_transaction_id == result.output["transaction_id"]


@pytest.mark.asyncio
async def test_request_payment_critic_rejection_preserves_request(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory, critic_agent=_RejectingCritic())
    first, second = await create_users(system)

    result = await system.orchestrator.handle(
        f"requestPayment requester_id={second} payer_id={first} amount=10.00",
        idempotency_key="IDEMP-CRITIC-REQUEST",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "requestPayment")
    assert result.output["payment_request_id"] in (
        system.payment.manager.current_state.payment_requests
    )


@pytest.mark.asyncio
async def test_approve_payment_critic_rejection_preserves_approval_and_transfer(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory, critic_agent=_RejectingCritic())
    first, second = await create_users(system)
    pending = await system.orchestrator.handle(
        f"requestPayment requester_id={second} payer_id={first} amount=15.00",
        idempotency_key="IDEMP-CRITIC-APPROVE-REQUEST",
        requested_at=NOW,
    )

    result = await system.orchestrator.handle(
        f"approvePayment request_id={pending.output['payment_request_id']}",
        idempotency_key="IDEMP-CRITIC-APPROVE",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "approvePayment")
    state = system.payment.manager.current_state
    assert state.payment_requests[result.output["payment_request_id"]].status.value == "APPROVED"
    assert len(state.transactions) == 1
    assert state.wallets[first].balance == Decimal("985.00")
    assert state.wallets[second].balance == Decimal("115.00")


@pytest.mark.asyncio
async def test_reject_payment_critic_rejection_preserves_rejection(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory, critic_agent=_RejectingCritic())
    first, second = await create_users(system)
    pending = await system.orchestrator.handle(
        f"requestPayment requester_id={second} payer_id={first} amount=15.00",
        idempotency_key="IDEMP-CRITIC-REJECT-REQUEST",
        requested_at=NOW,
    )

    result = await system.orchestrator.handle(
        f"rejectPayment request_id={pending.output['payment_request_id']}",
        idempotency_key="IDEMP-CRITIC-REJECT",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "rejectPayment")
    request = system.payment.manager.current_state.payment_requests[
        result.output["payment_request_id"]
    ]
    assert request.status.value == "REJECTED"


@pytest.mark.asyncio
async def test_mutating_output_guardrail_failure_preserves_committed_output(
    payment_harness_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        tool_guardrails=_FailingOutputGuardrails(),
    )

    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-GUARDRAIL-CREATE",
        requested_at=NOW,
    )

    assert result.agent_name == "OrchestratorAgent"
    assert result.output["operation"] == "createUser"
    assert result.confidence == 0.85
    assert result.metadata["delivery_status"] == "committed_with_validation_warning"
    assert result.metadata["post_commit_warning_stage"] == "output_guardrail"
    assert result.metadata["post_commit_warning_type"] == "RuntimeError"
    assert result.metadata["post_commit_warning_message"] == ("Committed result validation failed")
    assert len(system.payment.manager.current_state.users) == 1
    assert "private guardrail" not in str(result.metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("critic", "stage", "warning_type"),
    [
        (_FailingCritic(), "critic", "RuntimeError"),
        (_InvalidCritic(), "critic_output_validation", "TypeError"),
    ],
)
async def test_post_commit_critic_failures_become_safe_warnings(
    payment_harness_factory: Any,
    critic: Any,
    stage: str,
    warning_type: str,
) -> None:
    system = build_system(payment_harness_factory, critic_agent=critic)

    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key=f"IDEMP-{stage}",
        requested_at=NOW,
    )

    assert result.agent_name == "OrchestratorAgent"
    assert result.output["operation"] == "createUser"
    assert result.metadata["delivery_status"] == "committed_with_post_commit_warning"
    assert result.metadata["post_commit_warning_stage"] == stage
    assert result.metadata["post_commit_warning_type"] == warning_type
    assert "private critic" not in str(result.metadata)
    assert len(system.payment.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_committed_entity_memory_failure_is_metadata_only(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    facade = system.orchestrator._tool_registry._payment_facade
    original_create_user = facade.create_user

    async def malformed_create_result(command: Any) -> AgentResult:
        await original_create_user(command)
        return AgentResult("PaymentFacade", {"operation": "createUser"})

    facade.create_user = malformed_create_result
    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-MEMORY-ENTITY",
        requested_at=NOW,
    )

    assert result.agent_name == "OrchestratorAgent"
    assert result.output == {"operation": "createUser"}
    assert result.metadata["memory_persisted"] is False
    assert result.metadata["memory_error_type"] == "StateInvariantError"
    assert result.metadata["post_commit_warning_stage"] == "memory_entity_update"
    assert len(system.payment.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_read_only_critic_rejection_still_returns_fallback(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory({"U1": Decimal("10.00")}),
        critic_agent=_RejectingCritic(),
    )

    result = await system.orchestrator.handle(
        "checkBalance user_id=U1",
        requested_at=NOW,
    )

    assert result.agent_name == "FallbackAgent"
    assert result.metadata["fallback_trigger"] == "critic_rejection"
    assert system.payment.manager.current_state.wallets["U1"].balance == Decimal("10.00")


@pytest.mark.asyncio
async def test_read_only_output_guardrail_failure_still_returns_reflection(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory({"U1": Decimal("10.00")}),
        tool_guardrails=_FailingOutputGuardrails(),
    )

    result = await system.orchestrator.handle(
        "checkBalance user_id=U1",
        requested_at=NOW,
    )

    assert result.agent_name == "ReflectionAgent"
    assert result.metadata["error_handled"] is True


@pytest.mark.asyncio
async def test_memory_persistence_failure_after_quality_warning_preserves_output(
    payment_harness_factory: Any,
) -> None:
    repository = _FailOnConfiguredSaveRepository()
    repository.fail_on_call = 2
    system = build_system(
        payment_harness_factory,
        repository=repository,
        critic_agent=_RejectingCritic(),
    )

    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-CRITIC-MEMORY",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "createUser")
    assert result.metadata["memory_persisted"] is False
    assert result.metadata["memory_error_type"] == "OSError"
    assert len(system.payment.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_outbox_failure_after_quality_warning_preserves_output(
    payment_harness_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        critic_agent=_RejectingCritic(),
        outbox=_FailingOutbox(),
    )

    result = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
        idempotency_key="IDEMP-CRITIC-OUTBOX",
        requested_at=NOW,
    )

    _assert_quality_warning(result, "createUser")
    assert result.metadata["outbox"]["outbox_flush_succeeded"] is False
    assert len(system.payment.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_post_commit_critic_cancellation_propagates_without_rollback(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory, critic_agent=_CancellingCritic())

    with pytest.raises(asyncio.CancelledError):
        await system.orchestrator.handle(
            'createUser name="Alice" phone_number=0501111111 initial_balance=100.00',
            idempotency_key="IDEMP-CRITIC-CANCEL",
            requested_at=NOW,
        )

    assert len(system.payment.manager.current_state.users) == 1

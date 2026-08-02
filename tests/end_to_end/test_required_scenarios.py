"""Lecturer-required deterministic scenarios through OrchestratorAgent.handle."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.application import AgentResult, CriticReview
from agentic_payments.domain import RiskLevel
from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
    create_users,
)
from tests.integration.test_orchestrator_memory import (
    _FailOnConfiguredSaveRepository,
)


class _FailingFraud:
    async def assess_transaction(self, snapshot: Any) -> AgentResult:
        raise RuntimeError("configured post-processing failure")


class _RejectingCritic:
    async def review(self, result: AgentResult, expected_intent: Any) -> AgentResult:
        return AgentResult(
            "Critic",
            CriticReview(
                approved=False,
                quality_score=2,
                problems=["forced"],
                requires_fallback=True,
            ),
        )


@pytest.mark.asyncio
async def test_create_two_users_balances_transfer_and_memory_explanation(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    first_balance = await system.orchestrator.handle(
        f"checkBalance user_id={first}", requested_at=NOW
    )
    second_balance = await system.orchestrator.handle(
        f"checkBalance user_id={second}", requested_at=NOW
    )
    transferred = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=50.00",
        idempotency_key="IDEMP-E2E-T",
        requested_at=NOW,
    )
    explained = await system.orchestrator.handle(
        "explainLastAction",
        requested_at=NOW,
    )

    assert first_balance.output["balance"] == "1000.00"
    assert second_balance.output["balance"] == "100.00"
    assert transferred.output["operation"] == "transferMoney"
    assert explained.agent_name == "OrchestratorAgent"
    assert (
        explained.output["facts"]["output"]["transaction_id"]
        == transferred.output["transaction_id"]
    )


@pytest.mark.asyncio
async def test_four_invalid_transfer_scenarios_are_reflected_without_mutation(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    before = system.payment.manager.current_state.wallets[first].balance
    commands = (
        f"transferMoney sender_id={first} receiver_id={second} amount=-1.00",
        f"transferMoney sender_id={first} receiver_id={second} amount=2000.00",
        f"transferMoney sender_id={first} receiver_id=MISSING amount=1.00",
        f"transferMoney sender_id={first} receiver_id={first} amount=1.00",
    )

    results = [
        await system.orchestrator.handle(
            command,
            idempotency_key=f"IDEMP-E2E-ERR-{index}",
            requested_at=NOW,
        )
        for index, command in enumerate(commands)
    ]

    assert all(result.agent_name == "ReflectionAgent" for result in results)
    assert system.payment.manager.current_state.wallets[first].balance == before


@pytest.mark.asyncio
async def test_payment_request_approval_and_different_key_second_approval(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    pending = await system.orchestrator.handle(
        f"requestPayment requester_id={second} payer_id={first} amount=30.00",
        idempotency_key="IDEMP-E2E-REQ",
        requested_at=NOW,
    )
    request_id = pending.output["payment_request_id"]
    approved = await system.orchestrator.handle(
        f"approvePayment request_id={request_id}",
        idempotency_key="IDEMP-E2E-APPROVE-1",
        requested_at=NOW,
    )
    second_approval = await system.orchestrator.handle(
        f"approvePayment request_id={request_id}",
        idempotency_key="IDEMP-E2E-APPROVE-2",
        requested_at=NOW,
    )

    assert approved.output["operation"] == "approvePayment"
    assert second_approval.agent_name == "ReflectionAgent"
    assert second_approval.output.error_code == "payment_request_already_resolved"
    assert len(system.payment.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_suspicious_transfer_and_both_security_review_modes(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"SENDER": Decimal("10000.00"), "RECEIVER": Decimal("0.00")})
    system = build_system(payment_harness_factory, initial_state=state)
    transfer = await system.orchestrator.handle(
        "transferMoney sender_id=SENDER receiver_id=RECEIVER amount=8000.00",
        idempotency_key="IDEMP-E2E-RISK",
        requested_at=NOW,
    )
    transaction_review = await system.orchestrator.handle(
        f"securityReview transaction_id={transfer.output['transaction_id']}",
        requested_at=NOW,
    )
    system_review = await system.orchestrator.handle(
        "securityReview",
        requested_at=NOW,
    )

    assert transfer.output["fraud_assessment"]["risk_level"] == RiskLevel.HIGH.value
    assert transfer.output["snapshot"]["transaction"]["status"] == "FLAGGED"
    assert transfer.output["security_review"]["approved"] is True
    assert transaction_review.output.approved is True
    assert system_review.output.approved is True


@pytest.mark.asyncio
async def test_fallback_clarification_and_critic_rejection_do_not_double_execute(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    before = system.payment.manager.current_state.to_dict()
    unknown = await system.orchestrator.handle("unsupported request", requested_at=NOW)
    missing = await system.orchestrator.handle(
        "transferMoney sender_id=U1",
        requested_at=NOW,
    )
    after = system.payment.manager.current_state.to_dict()
    critic_system = build_system(
        payment_harness_factory,
        critic_agent=_RejectingCritic(),
    )
    rejected = await critic_system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=10.00',
        idempotency_key="IDEMP-E2E-CRITIC",
        requested_at=NOW,
    )

    assert unknown.output["reason"] == "unknown_intent"
    assert missing.output["reason"] == "missing_parameters"
    assert before["users"] == after["users"]
    assert before["wallets"] == after["wallets"]
    assert rejected.agent_name == "OrchestratorAgent"
    assert rejected.output["operation"] == "createUser"
    assert rejected.metadata["delivery_status"] == "committed_with_quality_warning"
    assert len(critic_system.payment.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_idempotency_replay_and_changed_parameters_conflict(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    command = f"transferMoney sender_id={first} receiver_id={second} amount=10.00"
    one = await system.orchestrator.handle(
        command,
        idempotency_key="IDEMP-E2E-SAME",
        requested_at=NOW,
    )
    two = await system.orchestrator.handle(
        command,
        idempotency_key="IDEMP-E2E-SAME",
        requested_at=NOW,
    )
    conflict = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=11.00",
        idempotency_key="IDEMP-E2E-SAME",
        requested_at=NOW,
    )

    assert one.output["transaction_id"] == two.output["transaction_id"]
    assert conflict.output.error_code == "idempotency_conflict"
    assert len(system.payment.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_audit_flush_removal_failure_retries_without_duplicate_event(
    payment_harness_factory: Any,
) -> None:
    repository = _FailOnConfiguredSaveRepository()
    repository.fail_on_call = 3
    system = build_system(payment_harness_factory, repository=repository)
    first = await system.orchestrator.handle(
        'createUser name="Alice" phone_number=0501111111 initial_balance=10.00',
        idempotency_key="IDEMP-E2E-OUTBOX",
        requested_at=NOW,
    )
    initial_event_ids = set(system.audit.events)

    retry = await system.orchestrator.handle(
        "unsupported request",
        requested_at=NOW,
    )

    assert first.metadata["outbox"]["outbox_flush_succeeded"] is False
    assert first.metadata["outbox"]["pending_after"] == 1
    assert retry.metadata["outbox"]["outbox_flush_succeeded"] is True
    assert system.payment.manager.current_state.pending_audit_events == {}
    assert set(system.audit.events) == initial_event_ids


@pytest.mark.asyncio
async def test_degraded_post_processing_reports_committed_transfer(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory, fraud_agent=_FailingFraud())
    first, second = await create_users(system)
    result = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=25.00",
        idempotency_key="IDEMP-E2E-DEGRADED",
        requested_at=NOW,
    )

    assert result.agent_name == "OrchestratorAgent"
    assert result.output["post_processing_status"] == "degraded"
    assert result.output["transaction_id"] in system.payment.manager.current_state.transactions
    assert system.payment.manager.current_state.wallets[first].balance == Decimal("975.00")

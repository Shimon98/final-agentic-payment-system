"""Payment-request lifecycle tests for PaymentDomainService."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from conftest import FIXED_TIME, DeterministicIdGenerator

from agentic_payments.domain import (
    InsufficientFundsError,
    PaymentRequest,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestNotFoundError,
    PaymentRequestStatus,
    PolicyViolationError,
    RiskLevel,
    SelfTransferError,
    StateInvariantError,
    Transaction,
    TransactionStatus,
    TransferPolicy,
    UserNotFoundError,
)


def _pending_state(application_state_factory: Any, *, amount: Decimal = Decimal("25.00")) -> Any:
    state = application_state_factory({"REQUESTER": Decimal("20.00"), "PAYER": Decimal("100.00")})
    state.payment_requests["REQ-1"] = PaymentRequest(
        request_id="REQ-1",
        requester_id="REQUESTER",
        payer_id="PAYER",
        amount=amount,
        status=PaymentRequestStatus.PENDING,
        created_at=FIXED_TIME,
        resolved_at=None,
        related_transaction_id=None,
        correlation_id="CORR-REQUEST",
    )
    return state


@pytest.mark.asyncio
async def test_create_pending_request_without_balance_change(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"REQUESTER": Decimal("20.00"), "PAYER": Decimal("100.00")}
        )
    )

    request = await harness.service.request_payment(
        requester_id="REQUESTER",
        payer_id="PAYER",
        amount=Decimal("25.00"),
        idempotency_key="IDEMP-REQUEST",
        correlation_id="CORR-REQUEST",
    )
    state = harness.manager.current_state

    assert request.status is PaymentRequestStatus.PENDING
    assert request.related_transaction_id is None
    assert state.payment_requests[request.request_id] == request
    assert state.wallets["REQUESTER"].balance == Decimal("20.00")
    assert state.wallets["PAYER"].balance == Decimal("100.00")
    event = next(iter(state.pending_audit_events.values()))
    assert event.action == "requestPayment"
    assert event.details["request_id"] == request.request_id


@pytest.mark.asyncio
async def test_self_payment_request_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory({"U1": Decimal("10.00")})
    )

    with pytest.raises(SelfTransferError):
        await harness.service.request_payment(
            requester_id="U1",
            payer_id="U1",
            amount=Decimal("1.00"),
            idempotency_key="IDEMP-SELF",
            correlation_id="CORR-SELF",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requester_id", "payer_id"),
    [("MISSING", "PAYER"), ("REQUESTER", "MISSING")],
)
async def test_missing_request_participant_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
    requester_id: str,
    payer_id: str,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"REQUESTER": Decimal("20.00"), "PAYER": Decimal("100.00")}
        )
    )

    with pytest.raises(UserNotFoundError):
        await harness.service.request_payment(
            requester_id=requester_id,
            payer_id=payer_id,
            amount=Decimal("1.00"),
            idempotency_key="IDEMP-MISSING",
            correlation_id="CORR-MISSING",
        )


@pytest.mark.asyncio
async def test_generated_request_id_collision_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = _pending_state(application_state_factory)
    ids = DeterministicIdGenerator(payment_request_ids=["REQ-1"])
    harness = payment_harness_factory(initial_state=state, ids=ids)

    with pytest.raises(StateInvariantError, match="request ID already exists"):
        await harness.service.request_payment(
            requester_id="REQUESTER",
            payer_id="PAYER",
            amount=Decimal("10.00"),
            idempotency_key="IDEMP-COLLISION",
            correlation_id="CORR-COLLISION",
        )


@pytest.mark.asyncio
async def test_approval_preliminary_read_rejects_missing_request(
    payment_harness_factory: Any,
) -> None:
    harness = payment_harness_factory()

    with pytest.raises(PaymentRequestNotFoundError):
        await harness.service.approve_payment_request(
            request_id="MISSING",
            idempotency_key="IDEMP-MISSING",
            correlation_id="CORR-MISSING",
        )


@pytest.mark.asyncio
async def test_request_retry_returns_original_without_second_save(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"REQUESTER": Decimal("20.00"), "PAYER": Decimal("100.00")}
        )
    )
    arguments = {
        "requester_id": "REQUESTER",
        "payer_id": "PAYER",
        "amount": Decimal("25.00"),
        "idempotency_key": "IDEMP-REQUEST",
        "correlation_id": "CORR-REQUEST",
    }

    first = await harness.service.request_payment(**arguments)
    second = await harness.service.request_payment(**arguments)

    assert second == first
    assert harness.repository.save_calls == 1
    assert harness.ids.payment_request_calls == 1
    assert len(harness.manager.current_state.payment_requests) == 1


@pytest.mark.asyncio
async def test_approve_request_transfers_and_updates_atomically(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))

    approved, snapshot = await harness.service.approve_payment_request(
        request_id="REQ-1",
        idempotency_key="IDEMP-APPROVE",
        correlation_id="CORR-APPROVE",
    )
    state = harness.manager.current_state

    assert approved.status is PaymentRequestStatus.APPROVED
    assert approved.related_transaction_id == snapshot.transaction.transaction_id
    assert state.payment_requests["REQ-1"] == approved
    assert state.transactions[snapshot.transaction.transaction_id] == snapshot.transaction
    assert state.wallets["PAYER"].balance == Decimal("75.00")
    assert state.wallets["REQUESTER"].balance == Decimal("45.00")


@pytest.mark.asyncio
async def test_approval_creates_two_correlated_audit_events(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))

    await harness.service.approve_payment_request(
        request_id="REQ-1",
        idempotency_key="IDEMP-APPROVE",
        correlation_id="CORR-APPROVE",
    )
    events = list(harness.manager.current_state.pending_audit_events.values())

    assert [event.action for event in events] == ["transferMoney", "approvePayment"]
    assert len({event.event_id for event in events}) == 2
    assert {event.correlation_id for event in events} == {"CORR-APPROVE"}
    assert events[0].details["source"] == "paymentRequest"


@pytest.mark.asyncio
async def test_approval_insufficient_funds_changes_nothing(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = _pending_state(application_state_factory, amount=Decimal("125.00"))
    harness = payment_harness_factory(initial_state=state)

    with pytest.raises(InsufficientFundsError):
        await harness.service.approve_payment_request(
            request_id="REQ-1",
            idempotency_key="IDEMP-APPROVE",
            correlation_id="CORR-APPROVE",
        )

    current = harness.manager.current_state
    assert current.payment_requests["REQ-1"].status is PaymentRequestStatus.PENDING
    assert current.transactions == {}


@pytest.mark.asyncio
async def test_approval_applies_single_transfer_limit(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    policy = TransferPolicy(
        maximum_single_transfer=Decimal("20.00"),
        maximum_daily_transfer=Decimal("100.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )
    harness = payment_harness_factory(
        initial_state=_pending_state(application_state_factory),
        transfer_policy=policy,
    )

    with pytest.raises(PolicyViolationError):
        await harness.service.approve_payment_request(
            request_id="REQ-1",
            idempotency_key="IDEMP-APPROVE",
            correlation_id="CORR-APPROVE",
        )


@pytest.mark.asyncio
async def test_approval_applies_payer_daily_limit(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = _pending_state(application_state_factory, amount=Decimal("50.00"))
    state.transactions["PRIOR"] = Transaction(
        transaction_id="PRIOR",
        sender_id="PAYER",
        receiver_id="REQUESTER",
        amount=Decimal("60.00"),
        created_at=FIXED_TIME - timedelta(hours=1),
        status=TransactionStatus.COMPLETED,
        risk_score=0,
        risk_level=RiskLevel.LOW,
        risk_reasons=(),
        failure_reason=None,
        correlation_id="CORR-PRIOR",
        idempotency_key="IDEMP-PRIOR",
    )
    policy = TransferPolicy(
        maximum_single_transfer=Decimal("100.00"),
        maximum_daily_transfer=Decimal("100.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )
    harness = payment_harness_factory(initial_state=state, transfer_policy=policy)

    with pytest.raises(PolicyViolationError):
        await harness.service.approve_payment_request(
            request_id="REQ-1",
            idempotency_key="IDEMP-APPROVE",
            correlation_id="CORR-APPROVE",
        )


@pytest.mark.asyncio
async def test_duplicate_approval_with_different_key_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))
    await harness.service.approve_payment_request(
        request_id="REQ-1",
        idempotency_key="IDEMP-FIRST",
        correlation_id="CORR-FIRST",
    )

    with pytest.raises(PaymentRequestAlreadyResolvedError):
        await harness.service.approve_payment_request(
            request_id="REQ-1",
            idempotency_key="IDEMP-SECOND",
            correlation_id="CORR-SECOND",
        )

    assert len(harness.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_duplicate_approval_same_key_returns_exact_original_result(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))
    arguments = {
        "request_id": "REQ-1",
        "idempotency_key": "IDEMP-APPROVE",
        "correlation_id": "CORR-APPROVE",
    }

    first = await harness.service.approve_payment_request(**arguments)
    second = await harness.service.approve_payment_request(**arguments)

    assert second == first
    assert harness.repository.save_calls == 1
    assert len(harness.manager.current_state.transactions) == 1
    assert len(harness.manager.current_state.pending_audit_events) == 2


@pytest.mark.asyncio
async def test_reject_request_changes_no_wallet(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))

    rejected = await harness.service.reject_payment_request(
        request_id="REQ-1",
        idempotency_key="IDEMP-REJECT",
        correlation_id="CORR-REJECT",
    )
    state = harness.manager.current_state

    assert rejected.status is PaymentRequestStatus.REJECTED
    assert state.wallets["PAYER"].balance == Decimal("100.00")
    assert state.wallets["REQUESTER"].balance == Decimal("20.00")
    assert state.transactions == {}
    event = next(iter(state.pending_audit_events.values()))
    assert event.action == "rejectPayment"
    assert event.details["request_id"] == "REQ-1"


@pytest.mark.asyncio
async def test_reject_already_resolved_request_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))
    await harness.service.reject_payment_request(
        request_id="REQ-1",
        idempotency_key="IDEMP-FIRST",
        correlation_id="CORR-FIRST",
    )

    with pytest.raises(PaymentRequestAlreadyResolvedError):
        await harness.service.reject_payment_request(
            request_id="REQ-1",
            idempotency_key="IDEMP-SECOND",
            correlation_id="CORR-SECOND",
        )


@pytest.mark.asyncio
async def test_reject_retry_returns_exact_original_without_second_save(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))
    arguments = {
        "request_id": "REQ-1",
        "idempotency_key": "IDEMP-REJECT",
        "correlation_id": "CORR-REJECT",
    }

    first = await harness.service.reject_payment_request(**arguments)
    second = await harness.service.reject_payment_request(**arguments)

    assert second == first
    assert harness.repository.save_calls == 1
    assert len(harness.manager.current_state.pending_audit_events) == 1

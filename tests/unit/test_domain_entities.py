"""Unit tests for immutable domain entities and enums."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from agentic_payments.domain import (
    AuditEvent,
    InsufficientFundsError,
    Intent,
    InvalidAmountError,
    NegativeBalanceInvariantError,
    PaymentRequest,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestStatus,
    RiskLevel,
    SelfTransferError,
    Transaction,
    TransactionStatus,
    User,
    Wallet,
)

NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)


def make_transaction(**overrides: object) -> Transaction:
    values: dict[str, object] = {
        "transaction_id": "TXN-001",
        "sender_id": "USR-001",
        "receiver_id": "USR-002",
        "amount": Decimal("25.00"),
        "created_at": NOW,
        "status": TransactionStatus.COMPLETED,
        "risk_score": 10,
        "risk_level": RiskLevel.LOW,
        "risk_reasons": ("routine transfer",),
        "failure_reason": None,
        "correlation_id": "COR-001",
        "idempotency_key": "IDEM-001",
    }
    values.update(overrides)
    return Transaction(**values)  # type: ignore[arg-type]


def make_request(**overrides: object) -> PaymentRequest:
    values: dict[str, object] = {
        "request_id": "REQ-001",
        "requester_id": "USR-002",
        "payer_id": "USR-001",
        "amount": Decimal("15.00"),
        "status": PaymentRequestStatus.PENDING,
        "created_at": NOW,
        "resolved_at": None,
        "related_transaction_id": None,
        "correlation_id": "COR-001",
    }
    values.update(overrides)
    return PaymentRequest(**values)  # type: ignore[arg-type]


def test_domain_enum_values_are_exact() -> None:
    assert [item.value for item in TransactionStatus] == [
        "PENDING",
        "COMPLETED",
        "FLAGGED",
        "REJECTED",
        "FAILED",
    ]
    assert [item.value for item in PaymentRequestStatus] == [
        "PENDING",
        "APPROVED",
        "REJECTED",
    ]
    assert [item.value for item in RiskLevel] == ["LOW", "MEDIUM", "HIGH"]
    assert [item.value for item in Intent] == [
        "createUser",
        "checkBalance",
        "transferMoney",
        "requestPayment",
        "approvePayment",
        "rejectPayment",
        "showTransactions",
        "fraudCheck",
        "securityReview",
        "explainLastAction",
        "unknown",
    ]


def test_domain_user_accepts_valid_normalized_values() -> None:
    user = User("USR-001", "Diana", "0520000000", NOW)
    user.validate()
    assert user.phone_number == "0520000000"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", ""),
        ("user_id", " USR-001"),
        ("name", ""),
        ("name", "Diana "),
        ("created_at", datetime(2026, 1, 2, 12)),
    ],
)
def test_domain_user_rejects_invalid_identity_fields(field: str, value: object) -> None:
    values: dict[str, object] = {
        "user_id": "USR-001",
        "name": "Diana",
        "phone_number": "0520000000",
        "created_at": NOW,
    }
    values[field] = value
    with pytest.raises(ValueError):
        User(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("phone", ["1234567", "123456789012345"])
def test_domain_user_phone_contract_accepts_boundary_lengths(phone: str) -> None:
    assert User("USR-001", "Diana", phone, NOW).phone_number == phone


@pytest.mark.parametrize(
    "phone",
    [
        "123456",
        "1234567890123456",
        "+972500000000",
        "050-000-0000",
        "050 000 0000",
        "(050)0000000",
        "٠٥٢٠٠٠٠٠٠٠",
    ],
)
def test_domain_user_rejects_unnormalized_phone(phone: str) -> None:
    with pytest.raises(ValueError):
        User("USR-001", "Diana", phone, NOW)


def test_domain_wallet_is_valid_frozen_and_versioned() -> None:
    wallet = Wallet("USR-001", Decimal("100.00"), "ILS", 0, NOW)
    assert wallet.balance == Decimal("100.00")
    with pytest.raises(FrozenInstanceError):
        wallet.balance = Decimal("0")  # type: ignore[misc]


def test_domain_wallet_credit_debit_and_with_balance_increment_once() -> None:
    wallet = Wallet("USR-001", Decimal("100.00"), "ILS", 3, NOW)
    later = NOW + timedelta(minutes=1)
    credited = wallet.credit(Decimal("20.00"), later)
    debited = wallet.debit(Decimal("40.00"), later)
    replaced = wallet.with_balance(Decimal("5.00"), later)
    assert (credited.balance, credited.version) == (Decimal("120.00"), 4)
    assert (debited.balance, debited.version) == (Decimal("60.00"), 4)
    assert (replaced.balance, replaced.version) == (Decimal("5.00"), 4)
    assert (wallet.balance, wallet.version) == (Decimal("100.00"), 3)


def test_domain_wallet_can_debit_valid_amount() -> None:
    wallet = Wallet("USR-001", Decimal("100.00"), "ILS", 0, NOW)
    assert wallet.can_debit(Decimal("100.00"))
    assert not wallet.can_debit(Decimal("100.01"))


def test_domain_wallet_rejects_insufficient_debit() -> None:
    wallet = Wallet("USR-001", Decimal("20.00"), "ILS", 0, NOW)
    with pytest.raises(InsufficientFundsError) as raised:
        wallet.debit(Decimal("20.01"), NOW)
    assert raised.value.available == Decimal("20.00")
    assert raised.value.required == Decimal("20.01")


def test_domain_wallet_rejects_negative_balance() -> None:
    with pytest.raises(NegativeBalanceInvariantError):
        Wallet("USR-001", Decimal("-0.01"), "ILS", 0, NOW)


@pytest.mark.parametrize(
    "amount",
    [1.0, Decimal("NaN"), Decimal("Infinity"), Decimal("1.001"), Decimal("0"), Decimal("-1")],
)
def test_domain_wallet_rejects_invalid_operation_money(amount: object) -> None:
    wallet = Wallet("USR-001", Decimal("10.00"), "ILS", 0, NOW)
    with pytest.raises(InvalidAmountError):
        wallet.credit(amount, NOW)  # type: ignore[arg-type]


def test_domain_transaction_accepts_valid_values() -> None:
    transaction = make_transaction()
    assert transaction.amount == Decimal("25.00")
    assert transaction.status is TransactionStatus.COMPLETED


def test_domain_transaction_rejects_self_transfer() -> None:
    with pytest.raises(SelfTransferError):
        make_transaction(receiver_id="USR-001")


@pytest.mark.parametrize("score", [-1, 101, True, 1.5])
def test_domain_transaction_rejects_invalid_risk_score(score: object) -> None:
    with pytest.raises(ValueError):
        make_transaction(risk_score=score)


def test_domain_transaction_failed_status_requires_failure_reason() -> None:
    with pytest.raises(ValueError):
        make_transaction(status=TransactionStatus.FAILED)
    failed = make_transaction(
        status=TransactionStatus.FAILED,
        failure_reason="processor simulation failed",
    )
    assert failed.failure_reason == "processor simulation failed"
    with pytest.raises(ValueError):
        make_transaction(failure_reason="unexpected")


def test_domain_transaction_risk_annotation_is_immutable_and_flagged() -> None:
    transaction = make_transaction(status=TransactionStatus.PENDING, risk_score=0, risk_reasons=())
    annotated = transaction.with_risk_assessment(
        score=75,
        level=RiskLevel.HIGH,
        reasons=["large amount", "high balance ratio"],
        flagged=True,
    )
    assert annotated.status is TransactionStatus.FLAGGED
    assert annotated.risk_score == 75
    assert annotated.risk_reasons == ("large amount", "high balance ratio")
    assert annotated.correlation_id == transaction.correlation_id
    assert annotated.idempotency_key == transaction.idempotency_key
    assert transaction.status is TransactionStatus.PENDING


def test_domain_transaction_non_flagged_risk_outcome_is_completed() -> None:
    transaction = make_transaction(status=TransactionStatus.PENDING)
    annotated = transaction.with_risk_assessment(
        score=20,
        level=RiskLevel.LOW,
        reasons=[],
        flagged=False,
    )
    assert annotated.status is TransactionStatus.COMPLETED


def test_domain_pending_payment_request_is_valid() -> None:
    request = make_request()
    assert request.is_pending()


def test_domain_payment_request_approval_transition_is_immutable() -> None:
    request = make_request()
    resolved_at = NOW + timedelta(minutes=1)
    approved = request.approve(transaction_id="TXN-001", resolved_at=resolved_at)
    assert approved.status is PaymentRequestStatus.APPROVED
    assert approved.related_transaction_id == "TXN-001"
    assert approved.resolved_at == resolved_at
    assert request.status is PaymentRequestStatus.PENDING


def test_domain_payment_request_rejection_transition_is_immutable() -> None:
    request = make_request()
    resolved_at = NOW + timedelta(minutes=1)
    rejected = request.reject(resolved_at=resolved_at)
    assert rejected.status is PaymentRequestStatus.REJECTED
    assert rejected.related_transaction_id is None
    assert request.status is PaymentRequestStatus.PENDING


@pytest.mark.parametrize("transition", ["approve", "reject"])
def test_domain_payment_request_duplicate_resolution_is_rejected(transition: str) -> None:
    resolved = make_request().reject(resolved_at=NOW + timedelta(minutes=1))
    with pytest.raises(PaymentRequestAlreadyResolvedError):
        if transition == "approve":
            resolved.approve(transaction_id="TXN-001", resolved_at=NOW + timedelta(minutes=2))
        else:
            resolved.reject(resolved_at=NOW + timedelta(minutes=2))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": PaymentRequestStatus.PENDING, "resolved_at": NOW},
        {"status": PaymentRequestStatus.PENDING, "related_transaction_id": "TXN-001"},
        {
            "status": PaymentRequestStatus.APPROVED,
            "resolved_at": NOW,
            "related_transaction_id": None,
        },
        {
            "status": PaymentRequestStatus.APPROVED,
            "resolved_at": None,
            "related_transaction_id": "TXN-001",
        },
        {"status": PaymentRequestStatus.REJECTED, "resolved_at": None},
        {
            "status": PaymentRequestStatus.REJECTED,
            "resolved_at": NOW,
            "related_transaction_id": "TXN-001",
        },
        {"status": PaymentRequestStatus.REJECTED, "resolved_at": NOW - timedelta(seconds=1)},
    ],
)
def test_domain_payment_request_status_invariants(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        make_request(**overrides)


def test_domain_audit_event_defensively_copies_details() -> None:
    source = {"transaction_id": "TXN-001"}
    event = AuditEvent("EVT-001", "COR-001", "TRANSFER_COMPLETED", "SUCCESS", NOW, "system", source)
    source["transaction_id"] = "TXN-MUTATED"
    assert event.details["transaction_id"] == "TXN-001"
    with pytest.raises(TypeError):
        event.details["new"] = "value"  # type: ignore[index]


def test_domain_audit_event_recursively_serializes_details() -> None:
    event = AuditEvent(
        "EVT-001",
        "COR-001",
        "TRANSFER_COMPLETED",
        "SUCCESS",
        NOW,
        "system",
        {
            "amount": Decimal("10.50"),
            "occurred": NOW,
            "risk": RiskLevel.MEDIUM,
            "nested": {"items": (Decimal("1.00"), True, None)},
        },
    )
    assert event.to_dict()["details"] == {
        "amount": "10.50",
        "occurred": NOW.isoformat(),
        "risk": "MEDIUM",
        "nested": {"items": ["1.00", True, None]},
    }


def test_domain_audit_event_rejects_unsupported_detail_value() -> None:
    event = AuditEvent("EVT-001", "COR-001", "ACTION", "SUCCESS", NOW, "system", {"bad": object()})
    with pytest.raises(TypeError):
        event.to_dict()

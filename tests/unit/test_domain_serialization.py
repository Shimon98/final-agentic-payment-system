"""Round-trip and malformed-input tests for domain serialization."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentic_payments.domain import (
    AuditEvent,
    PaymentRequest,
    PaymentRequestStatus,
    RiskLevel,
    Transaction,
    TransactionStatus,
    User,
    Wallet,
)

NOW = datetime(2026, 2, 3, 9, 30, tzinfo=UTC)


def transaction() -> Transaction:
    return Transaction(
        "TXN-001",
        "USR-001",
        "USR-002",
        Decimal("12.34"),
        NOW,
        TransactionStatus.FLAGGED,
        80,
        RiskLevel.HIGH,
        ("high balance ratio",),
        None,
        "COR-001",
        "IDEM-001",
    )


@pytest.mark.parametrize(
    "entity",
    [
        User("USR-001", "Diana", "0520000000", NOW),
        Wallet("USR-001", Decimal("100.50"), "ILS", 2, NOW),
        transaction(),
        PaymentRequest(
            "REQ-001",
            "USR-002",
            "USR-001",
            Decimal("12.34"),
            PaymentRequestStatus.APPROVED,
            NOW,
            NOW,
            "TXN-001",
            "COR-001",
        ),
        AuditEvent(
            "EVT-001",
            "COR-001",
            "TRANSFER_COMPLETED",
            "SUCCESS",
            NOW,
            "system",
            {"amount": Decimal("12.34"), "labels": ["one", "two"]},
        ),
    ],
)
def test_domain_serialization_round_trip_for_every_entity(entity: object) -> None:
    restored = type(entity).from_dict(entity.to_dict())  # type: ignore[attr-defined]
    assert restored.to_dict() == entity.to_dict()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("factory", "data"),
    [
        (
            User.from_dict,
            {
                "user_id": "USR-001",
                "name": "Diana",
                "phone_number": "0520000000",
                "created_at": "not-a-datetime",
            },
        ),
        (
            Wallet.from_dict,
            {
                "user_id": "USR-001",
                "balance": "not-a-decimal",
                "currency": "ILS",
                "version": 0,
                "updated_at": NOW.isoformat(),
            },
        ),
        (
            Transaction.from_dict,
            {
                **transaction().to_dict(),
                "amount": "NaN",
            },
        ),
    ],
)
def test_domain_serialization_rejects_malformed_values(
    factory: object, data: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        factory(data)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "data"),
    [
        (User.from_dict, {"user_id": "USR-001"}),
        (Wallet.from_dict, {"user_id": "USR-001"}),
        (Transaction.from_dict, {"transaction_id": "TXN-001"}),
        (PaymentRequest.from_dict, {"request_id": "REQ-001"}),
        (AuditEvent.from_dict, {"event_id": "EVT-001"}),
    ],
)
def test_domain_serialization_rejects_missing_required_fields(
    factory: object,
    data: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        factory(data)  # type: ignore[operator]


def test_domain_serialization_rejects_float_money() -> None:
    data = Wallet("USR-001", Decimal("10.00"), "ILS", 0, NOW).to_dict()
    data["balance"] = 10.0
    with pytest.raises(ValueError):
        Wallet.from_dict(data)


def test_domain_serialization_rejects_invalid_enum_value() -> None:
    data = transaction().to_dict()
    data["status"] = "NOT_A_STATUS"
    with pytest.raises(ValueError):
        Transaction.from_dict(data)


def test_domain_serialization_rejects_unsupported_audit_detail_value() -> None:
    data = AuditEvent(
        "EVT-001",
        "COR-001",
        "ACTION",
        "SUCCESS",
        NOW,
        "system",
        {},
    ).to_dict()
    data["details"] = {"unsupported": 1.5}
    with pytest.raises(ValueError):
        AuditEvent.from_dict(data)


def test_domain_serialization_uses_plain_decimal_enum_datetime_and_list_values() -> None:
    data = transaction().to_dict()
    assert data["amount"] == "12.34"
    assert data["created_at"] == NOW.isoformat()
    assert data["status"] == "FLAGGED"
    assert data["risk_level"] == "HIGH"
    assert data["risk_reasons"] == ["high balance ratio"]

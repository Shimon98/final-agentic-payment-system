"""Tests for immutable business memory and MemoryService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from agentic_payments.application import (
    AgentResult,
    BusinessMemory,
    MemoryEntry,
    MemoryService,
    RouterDecision,
)
from agentic_payments.domain import (
    Intent,
    PaymentRequest,
    PaymentRequestStatus,
    RiskLevel,
    Transaction,
    TransactionStatus,
    User,
)

NOW = datetime(2026, 7, 1, 10, tzinfo=UTC)


def transaction() -> Transaction:
    return Transaction(
        "TXN-001",
        "USR-001",
        "USR-002",
        Decimal("10.00"),
        NOW,
        TransactionStatus.FLAGGED,
        80,
        RiskLevel.HIGH,
        ("large",),
        None,
        "COR",
        "IDEM",
    )


def request(status: PaymentRequestStatus) -> PaymentRequest:
    resolved = None if status is PaymentRequestStatus.PENDING else NOW
    related = "TXN-001" if status is PaymentRequestStatus.APPROVED else None
    return PaymentRequest(
        "REQ-001", "USR-002", "USR-001", Decimal("10"), status, NOW, resolved, related, "COR"
    )


def test_memory_empty_and_entry_defensive_recursive_serialization() -> None:
    assert BusinessMemory() == MemoryService().snapshot()
    details = {"amount": Decimal("1.00"), "nested": (RiskLevel.LOW, NOW)}
    entry = MemoryEntry("action", NOW, details)
    details["amount"] = Decimal("2")
    assert entry.to_dict()["details"] == {
        "amount": "1.00",
        "nested": ["LOW", NOW.isoformat()],
    }
    assert MemoryEntry.from_dict(entry.to_dict()).to_dict() == entry.to_dict()


def test_memory_entry_rejects_unsupported_details() -> None:
    with pytest.raises(TypeError):
        MemoryEntry("action", NOW, {"bad": object()})


def test_memory_route_uses_explicit_timestamp_and_preserves_previous_snapshot() -> None:
    service = MemoryService()
    previous = service.snapshot()
    decision = RouterDecision(intent=Intent.CHECK_BALANCE, parameters={}, confidence=0.9)
    service.remember_route(decision, "Check balance", occurred_at=NOW)
    current = service.snapshot()
    assert previous == BusinessMemory()
    assert current.last_intent is Intent.CHECK_BALANCE
    assert current.last_user_message == "Check balance"
    assert current.recent_actions[-1].occurred_at == NOW


def test_memory_user_transaction_and_request_updates() -> None:
    service = MemoryService()
    service.remember_user(User("USR-001", "Diana", "0520000000", NOW), occurred_at=NOW)
    assert service.snapshot().last_user_id == "USR-001"
    service.remember_transaction(transaction(), occurred_at=NOW)
    memory = service.snapshot()
    assert memory.last_transaction_id == "TXN-001"
    assert memory.recent_actions[-1].details["amount"] == "10.00"
    expected = {
        PaymentRequestStatus.PENDING: "requestPayment",
        PaymentRequestStatus.APPROVED: "approvePayment",
        PaymentRequestStatus.REJECTED: "rejectPayment",
    }
    for status, action in expected.items():
        service.remember_payment_request(request(status), occurred_at=NOW)
        assert service.snapshot().last_action == action


@dataclass(frozen=True)
class ExampleData:
    amount: Decimal


class Unsupported:
    def __str__(self) -> str:
        return "unsupported"


@pytest.mark.parametrize(
    "output",
    [
        {"value": Decimal("1.00")},
        RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=1),
        ExampleData(Decimal("1.00")),
        "scalar",
        Unsupported(),
    ],
)
def test_memory_result_converts_supported_output_shapes(output: object) -> None:
    service = MemoryService()
    service.remember_result(AgentResult("agent", output), occurred_at=NOW)
    remembered = service.snapshot().last_result
    assert remembered is not None
    assert remembered["agent_name"] == "agent"


def test_memory_keeps_newest_twenty_actions_and_resets() -> None:
    service = MemoryService()
    decision = RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=1)
    for offset in range(21):
        service.remember_route(
            decision,
            f"message {offset}",
            occurred_at=NOW + timedelta(seconds=offset),
        )
    snapshot = service.snapshot()
    assert len(snapshot.recent_actions) == 20
    assert snapshot.recent_actions[0].occurred_at == NOW + timedelta(seconds=1)
    assert service.snapshot() is snapshot
    service.reset()
    assert service.snapshot() == BusinessMemory()


def test_memory_business_serialization_round_trip_and_read_only_result() -> None:
    memory = BusinessMemory(
        last_intent=Intent.TRANSFER_MONEY,
        last_result={"amount": Decimal("1.00")},
        recent_actions=(MemoryEntry("action", NOW, {"ok": True}),),
    )
    restored = BusinessMemory.from_dict(memory.to_dict())
    assert restored.to_dict() == memory.to_dict()
    with pytest.raises(TypeError):
        restored.last_result["changed"] = True  # type: ignore[index]


def test_memory_rejects_naive_route_timestamp_without_using_system_time() -> None:
    service = MemoryService()
    decision = RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=1)
    with pytest.raises(ValueError):
        service.remember_route(decision, "unknown", occurred_at=datetime(2026, 7, 1))

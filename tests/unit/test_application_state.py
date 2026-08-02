"""Tests for ApplicationState invariants and clone behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.application import ApplicationState, BusinessMemory, IdempotencyRecord
from agentic_payments.domain import (
    AuditEvent,
    PaymentRequest,
    PaymentRequestStatus,
    RiskLevel,
    StateInvariantError,
    Transaction,
    TransactionStatus,
    User,
    Wallet,
)

NOW = datetime(2026, 6, 1, 10, tzinfo=UTC)


def user(user_id: str, phone: str) -> User:
    return User(user_id, user_id, phone, NOW)


def wallet(user_id: str) -> Wallet:
    return Wallet(user_id, Decimal("100.00"), "ILS", 0, NOW)


def transaction() -> Transaction:
    return Transaction(
        "TXN-001",
        "USR-001",
        "USR-002",
        Decimal("10.00"),
        NOW,
        TransactionStatus.COMPLETED,
        0,
        RiskLevel.LOW,
        (),
        None,
        "COR-001",
        "IDEM-TXN",
    )


def request() -> PaymentRequest:
    return PaymentRequest(
        "REQ-001",
        "USR-002",
        "USR-001",
        Decimal("10.00"),
        PaymentRequestStatus.APPROVED,
        NOW,
        NOW,
        "TXN-001",
        "COR-001",
    )


def complete_state() -> ApplicationState:
    users = {
        "USR-001": user("USR-001", "0520000001"),
        "USR-002": user("USR-002", "0520000002"),
    }
    wallets = {key: wallet(key) for key in users}
    record = IdempotencyRecord("IDEM-001", "transfer", "a" * 64, "TXN-001", NOW)
    event = AuditEvent("EVT-001", "COR-001", "TRANSFER", "SUCCESS", NOW, "system", {})
    return ApplicationState(
        users=users,
        wallets=wallets,
        transactions={"TXN-001": transaction()},
        payment_requests={"REQ-001": request()},
        idempotency_records={"IDEM-001": record},
        pending_audit_events={"EVT-001": event},
        memory=BusinessMemory(
            last_user_id="USR-001",
            last_transaction_id="TXN-001",
            last_payment_request_id="REQ-001",
        ),
    )


def test_application_state_empty_is_valid() -> None:
    ApplicationState().validate_invariants()


def test_application_state_clone_is_independent() -> None:
    original = complete_state()
    clone = original.clone()
    clone.users.clear()
    clone.pending_audit_events["EVT-002"] = AuditEvent(
        "EVT-002", "COR-002", "ACTION", "SUCCESS", NOW, "system", {}
    )
    assert len(original.users) == 2
    assert set(original.pending_audit_events) == {"EVT-001"}


def test_application_state_valid_user_wallet_and_complete_state() -> None:
    state = ApplicationState(
        users={"USR-001": user("USR-001", "0520000001")},
        wallets={"USR-001": wallet("USR-001")},
    )
    state.validate_invariants()
    complete_state().validate_invariants()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda state: setattr(state, "users", {"WRONG": state.users["USR-001"]}),
        lambda state: setattr(state, "wallets", {"WRONG": state.wallets["USR-001"]}),
        lambda state: setattr(state, "transactions", {"WRONG": state.transactions["TXN-001"]}),
        lambda state: setattr(
            state, "payment_requests", {"WRONG": state.payment_requests["REQ-001"]}
        ),
        lambda state: setattr(
            state, "idempotency_records", {"WRONG": state.idempotency_records["IDEM-001"]}
        ),
        lambda state: setattr(
            state, "pending_audit_events", {"WRONG": state.pending_audit_events["EVT-001"]}
        ),
    ],
)
def test_application_state_rejects_collection_key_mismatch(mutator: Any) -> None:
    state = complete_state()
    mutator(state)
    with pytest.raises(StateInvariantError) as raised:
        state.validate_invariants()
    assert raised.value.context


def test_application_state_rejects_user_without_wallet_and_wallet_without_user() -> None:
    with pytest.raises(StateInvariantError):
        ApplicationState(users={"USR-001": user("USR-001", "0520000001")}).validate_invariants()
    with pytest.raises(StateInvariantError):
        ApplicationState(wallets={"USR-001": wallet("USR-001")}).validate_invariants()


def test_application_state_rejects_duplicate_phone() -> None:
    state = complete_state()
    state.users["USR-002"] = user("USR-002", "0520000001")
    with pytest.raises(StateInvariantError, match="duplicate phone"):
        state.validate_invariants()


def test_application_state_rejects_transaction_missing_participant_or_wallet() -> None:
    state = complete_state()
    del state.users["USR-002"]
    del state.wallets["USR-002"]
    with pytest.raises(StateInvariantError, match="participant"):
        state.validate_invariants()
    state = complete_state()
    del state.wallets["USR-002"]
    with pytest.raises(StateInvariantError):
        state.validate_invariants()


def test_application_state_rejects_request_and_approved_transaction_mismatches() -> None:
    state = complete_state()
    del state.transactions["TXN-001"]
    with pytest.raises(StateInvariantError, match="transaction does not exist"):
        state.validate_invariants()
    state = complete_state()
    wrong = Transaction(
        "TXN-001",
        "USR-002",
        "USR-001",
        Decimal("11.00"),
        NOW,
        TransactionStatus.COMPLETED,
        0,
        RiskLevel.LOW,
        (),
        None,
        "COR",
        "IDEM",
    )
    state.transactions["TXN-001"] = wrong
    with pytest.raises(StateInvariantError, match="direction"):
        state.validate_invariants()
    state.transactions["TXN-001"] = Transaction(
        "TXN-001",
        "USR-001",
        "USR-002",
        Decimal("11.00"),
        NOW,
        TransactionStatus.COMPLETED,
        0,
        RiskLevel.LOW,
        (),
        None,
        "COR",
        "IDEM",
    )
    with pytest.raises(StateInvariantError, match="amount"):
        state.validate_invariants()


@pytest.mark.parametrize(
    "memory",
    [
        BusinessMemory(last_user_id="USR-404"),
        BusinessMemory(last_transaction_id="TXN-404"),
        BusinessMemory(last_payment_request_id="REQ-404"),
    ],
)
def test_application_state_rejects_invalid_memory_references(memory: BusinessMemory) -> None:
    state = complete_state()
    state.memory = memory
    with pytest.raises(StateInvariantError, match="memory"):
        state.validate_invariants()


def test_application_state_validation_does_not_mutate_state() -> None:
    state = complete_state()
    before = state.to_dict()
    state.validate_invariants()
    assert state.to_dict() == before

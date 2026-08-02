"""Unit tests for typed domain exception contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentic_payments.domain import (
    DuplicatePhoneNumberError,
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidAmountError,
    InvalidInitialBalanceError,
    NegativeBalanceInvariantError,
    PaymentDomainError,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestNotFoundError,
    PaymentRequestStatus,
    PolicyViolationError,
    SelfTransferError,
    StateInvariantError,
    UserAlreadyExistsError,
    UserNotFoundError,
    WalletNotFoundError,
)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (PaymentDomainError("base"), "payment_domain_error"),
        (UserNotFoundError("USR-001"), "user_not_found"),
        (UserAlreadyExistsError("USR-001"), "user_already_exists"),
        (DuplicatePhoneNumberError("0520000000"), "duplicate_phone_number"),
        (InvalidInitialBalanceError(Decimal("-1")), "invalid_initial_balance"),
        (InvalidAmountError(Decimal("0"), "must be positive"), "invalid_amount"),
        (
            InsufficientFundsError("USR-001", Decimal("10"), Decimal("20")),
            "insufficient_funds",
        ),
        (SelfTransferError("USR-001"), "self_transfer"),
        (WalletNotFoundError("USR-001"), "wallet_not_found"),
        (PaymentRequestNotFoundError("REQ-001"), "payment_request_not_found"),
        (
            PaymentRequestAlreadyResolvedError("REQ-001", PaymentRequestStatus.APPROVED),
            "payment_request_already_resolved",
        ),
        (
            PolicyViolationError("maximum", Decimal("10"), Decimal("11")),
            "policy_violation",
        ),
        (
            NegativeBalanceInvariantError("USR-001", Decimal("-1")),
            "negative_balance_invariant",
        ),
        (StateInvariantError("invalid state"), "state_invariant"),
        (IdempotencyConflictError("IDEM-001"), "idempotency_conflict"),
    ],
)
def test_domain_exception_codes_are_stable(error: PaymentDomainError, code: str) -> None:
    assert error.code == code
    assert str(error) == error.message


def test_domain_exception_context_is_defensively_copied_and_read_only() -> None:
    source = {"resource": "wallet"}
    error = PaymentDomainError("failure", context=source)
    source["resource"] = "transaction"
    assert error.context == {"resource": "wallet"}
    with pytest.raises(TypeError):
        error.context["resource"] = "changed"  # type: ignore[index]
    with pytest.raises(AttributeError):
        error.message = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("error", "attributes"),
    [
        (UserNotFoundError("USR-001"), {"user_id": "USR-001"}),
        (UserAlreadyExistsError("USR-001"), {"user_id": "USR-001"}),
        (DuplicatePhoneNumberError("0520000000"), {"phone_number": "0520000000"}),
        (InvalidInitialBalanceError(Decimal("-1")), {"balance": Decimal("-1")}),
        (
            InvalidAmountError(Decimal("0"), "must be positive"),
            {"amount": Decimal("0"), "reason": "must be positive"},
        ),
        (
            InsufficientFundsError("USR-001", Decimal("10"), Decimal("20")),
            {
                "user_id": "USR-001",
                "available": Decimal("10"),
                "required": Decimal("20"),
            },
        ),
        (SelfTransferError("USR-001"), {"user_id": "USR-001"}),
        (WalletNotFoundError("USR-001"), {"user_id": "USR-001"}),
        (PaymentRequestNotFoundError("REQ-001"), {"request_id": "REQ-001"}),
        (
            PaymentRequestAlreadyResolvedError("REQ-001", PaymentRequestStatus.REJECTED),
            {"request_id": "REQ-001", "status": PaymentRequestStatus.REJECTED},
        ),
        (
            PolicyViolationError("daily", Decimal("10"), Decimal("11")),
            {"policy_name": "daily", "limit": Decimal("10"), "attempted": Decimal("11")},
        ),
        (
            NegativeBalanceInvariantError("USR-001", Decimal("-1")),
            {"user_id": "USR-001", "balance": Decimal("-1")},
        ),
        (IdempotencyConflictError("IDEM-001"), {"idempotency_key": "IDEM-001"}),
    ],
)
def test_domain_exception_attributes_match_context_and_are_read_only(
    error: PaymentDomainError,
    attributes: dict[str, object],
) -> None:
    for name, expected in attributes.items():
        assert getattr(error, name) == expected
        assert error.context[name] == expected
        with pytest.raises(AttributeError):
            setattr(error, name, object())


def test_domain_state_invariant_preserves_custom_context() -> None:
    error = StateInvariantError("dangling wallet", context={"user_id": "USR-404"})
    assert error.context == {"user_id": "USR-404"}

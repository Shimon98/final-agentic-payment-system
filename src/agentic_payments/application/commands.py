"""Immutable application request contexts and commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty stripped string")
    return value


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _money(value: object, field: str, *, positive: bool) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise ValueError(f"{field} must have at most two fractional digits")
    if positive and value <= 0:
        raise ValueError(f"{field} must be greater than zero")
    if not positive and value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Trace context supplied by the application boundary."""

    correlation_id: str
    idempotency_key: str
    requested_at: datetime
    actor: str = "user"

    def __post_init__(self) -> None:
        _text(self.correlation_id, "correlation_id")
        _text(self.idempotency_key, "idempotency_key")
        _aware(self.requested_at, "requested_at")
        _text(self.actor, "actor")


@dataclass(frozen=True, slots=True)
class CreateUserCommand:
    """Request to create a user and initial wallet."""

    name: str
    phone_number: str
    initial_balance: Decimal
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.name, "name")
        if (
            not isinstance(self.phone_number, str)
            or not self.phone_number.isascii()
            or not self.phone_number.isdigit()
            or not 7 <= len(self.phone_number) <= 15
        ):
            raise ValueError("phone_number must contain 7 to 15 ASCII digits")
        _money(self.initial_balance, "initial_balance", positive=False)
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class CheckBalanceCommand:
    """Request to read one wallet balance."""

    user_id: str
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.user_id, "user_id")
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class TransferMoneyCommand:
    """Request to transfer a positive amount between distinct users."""

    sender_id: str
    receiver_id: str
    amount: Decimal
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.sender_id, "sender_id")
        _text(self.receiver_id, "receiver_id")
        if self.sender_id == self.receiver_id:
            raise ValueError("sender_id and receiver_id must differ")
        _money(self.amount, "amount", positive=True)
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class RequestPaymentCommand:
    """Request that a payer send a positive amount to a requester."""

    requester_id: str
    payer_id: str
    amount: Decimal
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.requester_id, "requester_id")
        _text(self.payer_id, "payer_id")
        if self.requester_id == self.payer_id:
            raise ValueError("requester_id and payer_id must differ")
        _money(self.amount, "amount", positive=True)
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class ApprovePaymentCommand:
    """Request to approve a pending payment request."""

    request_id: str
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class RejectPaymentCommand:
    """Request to reject a pending payment request."""

    request_id: str
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class ShowTransactionsCommand:
    """Request to list one user's transactions."""

    user_id: str
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.user_id, "user_id")
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class FraudCheckCommand:
    """Request a read-only fraud check for one transaction."""

    transaction_id: str
    context: RequestContext

    def __post_init__(self) -> None:
        _text(self.transaction_id, "transaction_id")
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class SecurityReviewCommand:
    """Request a transaction-specific or whole-system security review."""

    transaction_id: str | None
    context: RequestContext

    def __post_init__(self) -> None:
        if self.transaction_id is not None:
            _text(self.transaction_id, "transaction_id")
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")


@dataclass(frozen=True, slots=True)
class ExplainLastActionCommand:
    """Request an explanation of the latest remembered action."""

    context: RequestContext

    def __post_init__(self) -> None:
        if not isinstance(self.context, RequestContext):
            raise TypeError("context must be RequestContext")

"""Immutable entities for the deterministic payment domain."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, cast

from agentic_payments.domain.enums import PaymentRequestStatus, RiskLevel, TransactionStatus
from agentic_payments.domain.exceptions import (
    InsufficientFundsError,
    InvalidAmountError,
    NegativeBalanceInvariantError,
    PaymentDomainError,
    PaymentRequestAlreadyResolvedError,
    SelfTransferError,
)


def _validate_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty stripped string")
    return value


def _validate_aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value


def _validate_money(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidAmountError(cast(Decimal, value), f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise InvalidAmountError(value, f"{field_name} must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise InvalidAmountError(value, f"{field_name} must have at most two fractional digits")
    if positive and value <= 0:
        raise InvalidAmountError(value, f"{field_name} must be greater than zero")
    return value


def _validate_score(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValueError("risk_score must be an integer between 0 and 100")
    return value


def _validate_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError("risk_reasons must be a tuple")
    for reason in value:
        _validate_text(reason, "risk reason")
    return value


def _require_fields(data: Mapping[str, Any], fields: Sequence[str]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError("serialized entity must be a mapping")
    missing = [field for field in fields if field not in data]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def _parse_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a decimal string")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} is not a valid decimal") from error


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} is not a valid ISO-8601 datetime") from error
    return _validate_aware_datetime(parsed, field_name)


def _decimal_string(value: Decimal) -> str:
    return format(value, "f")


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, nested_value in value.items():
            if not isinstance(key, str) or not key:
                raise TypeError("audit detail keys must be non-empty strings")
            converted[key] = _json_compatible(nested_value)
        return converted
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, datetime):
        _validate_aware_datetime(value, "audit detail datetime")
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported audit detail value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class User:
    """Registered user identity with an already-normalized phone number."""

    user_id: str
    name: str
    phone_number: str
    created_at: datetime

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate all user invariants."""

        _validate_text(self.user_id, "user_id")
        _validate_text(self.name, "name")
        if (
            not isinstance(self.phone_number, str)
            or not self.phone_number.isascii()
            or not self.phone_number.isdigit()
            or not 7 <= len(self.phone_number) <= 15
        ):
            raise ValueError("phone_number must contain 7 to 15 digits only")
        _validate_aware_datetime(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the user to JSON-compatible values."""

        return {
            "user_id": self.user_id,
            "name": self.name,
            "phone_number": self.phone_number,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> User:
        """Reconstruct and validate a user from serialized values."""

        _require_fields(data, ("user_id", "name", "phone_number", "created_at"))
        return cls(
            user_id=data["user_id"],
            name=data["name"],
            phone_number=data["phone_number"],
            created_at=_parse_datetime(data["created_at"], "created_at"),
        )


@dataclass(frozen=True, slots=True)
class Wallet:
    """Immutable and versioned ILS wallet."""

    user_id: str
    balance: Decimal
    currency: str
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        _validate_text(self.user_id, "user_id")
        balance = _validate_money(self.balance, "balance")
        if balance < 0:
            raise NegativeBalanceInvariantError(self.user_id, balance)
        if self.currency != "ILS":
            raise ValueError("currency must be ILS")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise ValueError("version must be an integer greater than or equal to zero")
        _validate_aware_datetime(self.updated_at, "updated_at")

    def can_debit(self, amount: Decimal) -> bool:
        """Return whether a valid positive debit is covered by the balance."""

        validated = _validate_money(amount, "amount", positive=True)
        return self.balance >= validated

    def with_balance(self, new_balance: Decimal, updated_at: datetime) -> Wallet:
        """Return a new wallet with a replacement balance and incremented version."""

        _validate_money(new_balance, "new_balance")
        _validate_aware_datetime(updated_at, "updated_at")
        return replace(
            self,
            balance=new_balance,
            version=self.version + 1,
            updated_at=updated_at,
        )

    def credit(self, amount: Decimal, updated_at: datetime) -> Wallet:
        """Return a new wallet credited by a positive amount."""

        validated = _validate_money(amount, "amount", positive=True)
        return self.with_balance(self.balance + validated, updated_at)

    def debit(self, amount: Decimal, updated_at: datetime) -> Wallet:
        """Return a new wallet debited by a positive covered amount."""

        validated = _validate_money(amount, "amount", positive=True)
        if validated > self.balance:
            raise InsufficientFundsError(self.user_id, self.balance, validated)
        return self.with_balance(self.balance - validated, updated_at)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the wallet to JSON-compatible values."""

        return {
            "user_id": self.user_id,
            "balance": _decimal_string(self.balance),
            "currency": self.currency,
            "version": self.version,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Wallet:
        """Reconstruct and validate a wallet from serialized values."""

        _require_fields(data, ("user_id", "balance", "currency", "version", "updated_at"))
        try:
            return cls(
                user_id=data["user_id"],
                balance=_parse_decimal(data["balance"], "balance"),
                currency=data["currency"],
                version=data["version"],
                updated_at=_parse_datetime(data["updated_at"], "updated_at"),
            )
        except PaymentDomainError as error:
            raise ValueError(str(error)) from error


@dataclass(frozen=True, slots=True)
class Transaction:
    """Immutable record of a transfer and its risk annotation."""

    transaction_id: str
    sender_id: str
    receiver_id: str
    amount: Decimal
    created_at: datetime
    status: TransactionStatus
    risk_score: int
    risk_level: RiskLevel
    risk_reasons: tuple[str, ...]
    failure_reason: str | None
    correlation_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for field_name in (
            "transaction_id",
            "sender_id",
            "receiver_id",
            "correlation_id",
            "idempotency_key",
        ):
            _validate_text(getattr(self, field_name), field_name)
        if self.sender_id == self.receiver_id:
            raise SelfTransferError(self.sender_id)
        _validate_money(self.amount, "amount", positive=True)
        _validate_aware_datetime(self.created_at, "created_at")
        if not isinstance(self.status, TransactionStatus):
            raise ValueError("status must be a TransactionStatus")
        _validate_score(self.risk_score)
        if not isinstance(self.risk_level, RiskLevel):
            raise ValueError("risk_level must be a RiskLevel")
        _validate_reasons(self.risk_reasons)
        if self.status is TransactionStatus.FAILED:
            _validate_text(self.failure_reason, "failure_reason")
        elif self.failure_reason is not None:
            raise ValueError("failure_reason must be None unless status is FAILED")

    def with_risk_assessment(
        self,
        *,
        score: int,
        level: RiskLevel,
        reasons: Sequence[str],
        flagged: bool,
    ) -> Transaction:
        """Return a new completed or flagged transaction with validated risk facts."""

        _validate_score(score)
        if not isinstance(level, RiskLevel):
            raise ValueError("level must be a RiskLevel")
        if isinstance(reasons, (str, bytes)):
            raise ValueError("reasons must be a sequence of strings")
        normalized_reasons = tuple(reasons)
        _validate_reasons(normalized_reasons)
        if not isinstance(flagged, bool):
            raise ValueError("flagged must be a bool")
        return replace(
            self,
            status=TransactionStatus.FLAGGED if flagged else TransactionStatus.COMPLETED,
            risk_score=score,
            risk_level=level,
            risk_reasons=normalized_reasons,
            failure_reason=None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the transaction to JSON-compatible values."""

        return {
            "transaction_id": self.transaction_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "amount": _decimal_string(self.amount),
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "risk_reasons": list(self.risk_reasons),
            "failure_reason": self.failure_reason,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Transaction:
        """Reconstruct and validate a transaction from serialized values."""

        fields = (
            "transaction_id",
            "sender_id",
            "receiver_id",
            "amount",
            "created_at",
            "status",
            "risk_score",
            "risk_level",
            "risk_reasons",
            "failure_reason",
            "correlation_id",
            "idempotency_key",
        )
        _require_fields(data, fields)
        reasons = data["risk_reasons"]
        if not isinstance(reasons, list):
            raise ValueError("risk_reasons must be a list")
        try:
            return cls(
                transaction_id=data["transaction_id"],
                sender_id=data["sender_id"],
                receiver_id=data["receiver_id"],
                amount=_parse_decimal(data["amount"], "amount"),
                created_at=_parse_datetime(data["created_at"], "created_at"),
                status=TransactionStatus(data["status"]),
                risk_score=data["risk_score"],
                risk_level=RiskLevel(data["risk_level"]),
                risk_reasons=tuple(reasons),
                failure_reason=data["failure_reason"],
                correlation_id=data["correlation_id"],
                idempotency_key=data["idempotency_key"],
            )
        except (PaymentDomainError, TypeError) as error:
            raise ValueError(str(error)) from error


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    """Immutable request for a payer to transfer money to a requester."""

    request_id: str
    requester_id: str
    payer_id: str
    amount: Decimal
    status: PaymentRequestStatus
    created_at: datetime
    resolved_at: datetime | None
    related_transaction_id: str | None
    correlation_id: str

    def __post_init__(self) -> None:
        for field_name in ("request_id", "requester_id", "payer_id", "correlation_id"):
            _validate_text(getattr(self, field_name), field_name)
        if self.requester_id == self.payer_id:
            raise SelfTransferError(self.requester_id)
        _validate_money(self.amount, "amount", positive=True)
        created_at = _validate_aware_datetime(self.created_at, "created_at")
        if not isinstance(self.status, PaymentRequestStatus):
            raise ValueError("status must be a PaymentRequestStatus")
        if self.resolved_at is not None:
            resolved_at = _validate_aware_datetime(self.resolved_at, "resolved_at")
            if resolved_at < created_at:
                raise ValueError("resolved_at cannot be earlier than created_at")
        if self.related_transaction_id is not None:
            _validate_text(self.related_transaction_id, "related_transaction_id")
        if self.status is PaymentRequestStatus.PENDING:
            if self.resolved_at is not None or self.related_transaction_id is not None:
                raise ValueError("pending request cannot have resolution data")
        elif self.status is PaymentRequestStatus.APPROVED:
            if self.resolved_at is None or self.related_transaction_id is None:
                raise ValueError("approved request requires resolution and transaction")
        elif self.resolved_at is None or self.related_transaction_id is not None:
            raise ValueError("rejected request requires resolution without a transaction")

    def is_pending(self) -> bool:
        """Return whether the request can still be resolved."""

        return self.status is PaymentRequestStatus.PENDING

    def approve(self, *, transaction_id: str, resolved_at: datetime) -> PaymentRequest:
        """Return an approved request linked to a transaction."""

        if not self.is_pending():
            raise PaymentRequestAlreadyResolvedError(self.request_id, self.status)
        _validate_text(transaction_id, "transaction_id")
        _validate_aware_datetime(resolved_at, "resolved_at")
        return replace(
            self,
            status=PaymentRequestStatus.APPROVED,
            resolved_at=resolved_at,
            related_transaction_id=transaction_id,
        )

    def reject(self, *, resolved_at: datetime) -> PaymentRequest:
        """Return a rejected request."""

        if not self.is_pending():
            raise PaymentRequestAlreadyResolvedError(self.request_id, self.status)
        _validate_aware_datetime(resolved_at, "resolved_at")
        return replace(
            self,
            status=PaymentRequestStatus.REJECTED,
            resolved_at=resolved_at,
            related_transaction_id=None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the payment request to JSON-compatible values."""

        return {
            "request_id": self.request_id,
            "requester_id": self.requester_id,
            "payer_id": self.payer_id,
            "amount": _decimal_string(self.amount),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "related_transaction_id": self.related_transaction_id,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PaymentRequest:
        """Reconstruct and validate a payment request from serialized values."""

        fields = (
            "request_id",
            "requester_id",
            "payer_id",
            "amount",
            "status",
            "created_at",
            "resolved_at",
            "related_transaction_id",
            "correlation_id",
        )
        _require_fields(data, fields)
        resolved_value = data["resolved_at"]
        try:
            return cls(
                request_id=data["request_id"],
                requester_id=data["requester_id"],
                payer_id=data["payer_id"],
                amount=_parse_decimal(data["amount"], "amount"),
                status=PaymentRequestStatus(data["status"]),
                created_at=_parse_datetime(data["created_at"], "created_at"),
                resolved_at=(
                    None
                    if resolved_value is None
                    else _parse_datetime(resolved_value, "resolved_at")
                ),
                related_transaction_id=data["related_transaction_id"],
                correlation_id=data["correlation_id"],
            )
        except (PaymentDomainError, TypeError) as error:
            raise ValueError(str(error)) from error


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable audit fact collected by the domain."""

    event_id: str
    correlation_id: str
    action: str
    status: str
    occurred_at: datetime
    actor: str
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("event_id", "correlation_id", "action", "status", "actor"):
            _validate_text(getattr(self, field_name), field_name)
        _validate_aware_datetime(self.occurred_at, "occurred_at")
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        copied_details = dict(self.details)
        for key in copied_details:
            if not isinstance(key, str) or not key:
                raise ValueError("details keys must be non-empty strings")
        object.__setattr__(self, "details", MappingProxyType(copied_details))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the audit event and nested details to JSON-compatible values."""

        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "action": self.action,
            "status": self.status,
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor,
            "details": _json_compatible(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AuditEvent:
        """Reconstruct and validate an audit event from serialized values."""

        fields = (
            "event_id",
            "correlation_id",
            "action",
            "status",
            "occurred_at",
            "actor",
            "details",
        )
        _require_fields(data, fields)
        details = data["details"]
        if not isinstance(details, Mapping):
            raise ValueError("details must be a mapping")
        try:
            _json_compatible(details)
        except TypeError as error:
            raise ValueError("details contain unsupported serialized values") from error
        return cls(
            event_id=data["event_id"],
            correlation_id=data["correlation_id"],
            action=data["action"],
            status=data["status"],
            occurred_at=_parse_datetime(data["occurred_at"], "occurred_at"),
            actor=data["actor"],
            details=details,
        )

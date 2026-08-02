"""Application state, idempotency records, and cross-entity invariants."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, NoReturn, TypeVar

from agentic_payments.application.memory_service import BusinessMemory
from agentic_payments.domain import (
    AuditEvent,
    PaymentRequest,
    PaymentRequestStatus,
    StateInvariantError,
    Transaction,
    User,
    Wallet,
)

T = TypeVar("T")
_STATE_KEYS = {
    "users",
    "wallets",
    "transactions",
    "payment_requests",
    "idempotency_records",
    "pending_audit_events",
    "memory",
}


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty stripped string")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _json_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise TypeError("result_payload keys must be non-empty strings")
            converted[key] = _json_payload(nested)
        return converted
    if isinstance(value, (list, tuple)):
        return [_json_payload(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("result_payload Decimal values must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        return _aware(value, "result_payload datetime").isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported result_payload value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Stored reference for one canonical idempotent request."""

    idempotency_key: str
    operation_type: str
    request_fingerprint: str
    result_reference: str
    created_at: datetime
    result_payload: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _text(self.idempotency_key, "idempotency_key")
        _text(self.operation_type, "operation_type")
        _text(self.result_reference, "result_reference")
        if re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint) is None:
            raise ValueError("request_fingerprint must be 64 lowercase hexadecimal characters")
        _aware(self.created_at, "created_at")
        if self.result_payload is not None:
            if not isinstance(self.result_payload, Mapping):
                raise TypeError("result_payload must be a mapping or None")
            object.__setattr__(
                self,
                "result_payload",
                MappingProxyType(_json_payload(self.result_payload)),
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the idempotency record."""

        return {
            "idempotency_key": self.idempotency_key,
            "operation_type": self.operation_type,
            "request_fingerprint": self.request_fingerprint,
            "result_reference": self.result_reference,
            "created_at": self.created_at.isoformat(),
            "result_payload": (
                _json_payload(self.result_payload) if self.result_payload is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IdempotencyRecord:
        """Reconstruct an idempotency record from serialized data."""

        required = {
            "idempotency_key",
            "operation_type",
            "request_fingerprint",
            "result_reference",
            "created_at",
        }
        allowed = required | {"result_payload"}
        if not isinstance(data, Mapping) or not required.issubset(data) or not set(data) <= allowed:
            raise ValueError("idempotency record fields are missing or unknown")
        raw_time = data["created_at"]
        if not isinstance(raw_time, str):
            raise ValueError("created_at must be an ISO-8601 string")
        try:
            created_at = datetime.fromisoformat(raw_time)
        except ValueError as error:
            raise ValueError("created_at is malformed") from error
        return cls(
            idempotency_key=data["idempotency_key"],
            operation_type=data["operation_type"],
            request_fingerprint=data["request_fingerprint"],
            result_reference=data["result_reference"],
            created_at=created_at,
            result_payload=data.get("result_payload"),
        )


@dataclass(slots=True)
class ApplicationState:
    """Mutable working state used only by future Units of Work."""

    users: dict[str, User] = field(default_factory=dict)
    wallets: dict[str, Wallet] = field(default_factory=dict)
    transactions: dict[str, Transaction] = field(default_factory=dict)
    payment_requests: dict[str, PaymentRequest] = field(default_factory=dict)
    idempotency_records: dict[str, IdempotencyRecord] = field(default_factory=dict)
    pending_audit_events: dict[str, AuditEvent] = field(default_factory=dict)
    memory: BusinessMemory = field(default_factory=BusinessMemory)

    def clone(self) -> ApplicationState:
        """Return a deeply independent validated state copy."""

        return ApplicationState.from_dict(self.to_dict())

    def _fail(self, message: str, **context: Any) -> NoReturn:
        raise StateInvariantError(message, context=context)

    def validate_invariants(self) -> None:
        """Validate all cross-entity application-state invariants."""

        phones: dict[str, str] = {}
        for key, user in self.users.items():
            if key != user.user_id:
                self._fail("user dictionary key mismatch", key=key, user_id=user.user_id)
            if user.phone_number in phones:
                self._fail(
                    "duplicate phone number",
                    phone_number=user.phone_number,
                    user_ids=[phones[user.phone_number], user.user_id],
                )
            phones[user.phone_number] = user.user_id
            if user.user_id not in self.wallets:
                self._fail("user is missing wallet", user_id=user.user_id)
        for key, wallet in self.wallets.items():
            if key != wallet.user_id:
                self._fail("wallet dictionary key mismatch", key=key, user_id=wallet.user_id)
            if wallet.user_id not in self.users:
                self._fail("wallet owner does not exist", user_id=wallet.user_id)
        for key, transaction in self.transactions.items():
            if key != transaction.transaction_id:
                self._fail(
                    "transaction dictionary key mismatch",
                    key=key,
                    transaction_id=transaction.transaction_id,
                )
            for role, user_id in (
                ("sender", transaction.sender_id),
                ("receiver", transaction.receiver_id),
            ):
                if user_id not in self.users:
                    self._fail("transaction participant does not exist", role=role, user_id=user_id)
                if user_id not in self.wallets:
                    self._fail("transaction participant has no wallet", role=role, user_id=user_id)
        for key, request in self.payment_requests.items():
            if key != request.request_id:
                self._fail(
                    "payment request dictionary key mismatch",
                    key=key,
                    request_id=request.request_id,
                )
            for role, user_id in (
                ("requester", request.requester_id),
                ("payer", request.payer_id),
            ):
                if user_id not in self.users:
                    self._fail(
                        "payment request participant does not exist", role=role, user_id=user_id
                    )
                if user_id not in self.wallets:
                    self._fail(
                        "payment request participant has no wallet", role=role, user_id=user_id
                    )
            if request.status is PaymentRequestStatus.APPROVED:
                transaction_id = request.related_transaction_id
                if transaction_id is None or transaction_id not in self.transactions:
                    self._fail(
                        "approved request transaction does not exist",
                        request_id=request.request_id,
                        transaction_id=transaction_id,
                    )
                transaction = self.transactions[transaction_id]
                if (
                    transaction.sender_id != request.payer_id
                    or transaction.receiver_id != request.requester_id
                ):
                    self._fail(
                        "approved request transaction direction mismatch",
                        request_id=request.request_id,
                        transaction_id=transaction_id,
                    )
                if transaction.amount != request.amount:
                    self._fail(
                        "approved request transaction amount mismatch",
                        request_id=request.request_id,
                        transaction_id=transaction_id,
                    )
        for key, record in self.idempotency_records.items():
            if key != record.idempotency_key:
                self._fail(
                    "idempotency dictionary key mismatch",
                    key=key,
                    idempotency_key=record.idempotency_key,
                )
            if not record.result_reference:
                self._fail("idempotency result reference is empty", idempotency_key=key)
        for key, event in self.pending_audit_events.items():
            if key != event.event_id:
                self._fail(
                    "pending audit dictionary key mismatch", key=key, event_id=event.event_id
                )
        if self.memory.last_user_id is not None and self.memory.last_user_id not in self.users:
            self._fail("memory user reference does not exist", user_id=self.memory.last_user_id)
        if (
            self.memory.last_transaction_id is not None
            and self.memory.last_transaction_id not in self.transactions
        ):
            self._fail(
                "memory transaction reference does not exist",
                transaction_id=self.memory.last_transaction_id,
            )
        if (
            self.memory.last_payment_request_id is not None
            and self.memory.last_payment_request_id not in self.payment_requests
        ):
            self._fail(
                "memory payment request reference does not exist",
                request_id=self.memory.last_payment_request_id,
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize state deterministically with sorted collection keys."""

        return {
            "users": {key: self.users[key].to_dict() for key in sorted(self.users)},
            "wallets": {key: self.wallets[key].to_dict() for key in sorted(self.wallets)},
            "transactions": {
                key: self.transactions[key].to_dict() for key in sorted(self.transactions)
            },
            "payment_requests": {
                key: self.payment_requests[key].to_dict() for key in sorted(self.payment_requests)
            },
            "idempotency_records": {
                key: self.idempotency_records[key].to_dict()
                for key in sorted(self.idempotency_records)
            },
            "pending_audit_events": {
                key: self.pending_audit_events[key].to_dict()
                for key in sorted(self.pending_audit_events)
            },
            "memory": self.memory.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ApplicationState:
        """Reconstruct and validate complete application state."""

        if not isinstance(data, Mapping) or set(data) != _STATE_KEYS:
            raise ValueError("state top-level keys are missing or unknown")

        def collection(name: str) -> Mapping[str, Any]:
            value = data[name]
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
            return value

        users = {key: User.from_dict(value) for key, value in collection("users").items()}
        wallets = {key: Wallet.from_dict(value) for key, value in collection("wallets").items()}
        transactions = {
            key: Transaction.from_dict(value) for key, value in collection("transactions").items()
        }
        requests = {
            key: PaymentRequest.from_dict(value)
            for key, value in collection("payment_requests").items()
        }
        records = {
            key: IdempotencyRecord.from_dict(value)
            for key, value in collection("idempotency_records").items()
        }
        events = {
            key: AuditEvent.from_dict(value)
            for key, value in collection("pending_audit_events").items()
        }
        memory_data = data["memory"]
        if not isinstance(memory_data, Mapping):
            raise ValueError("memory must be a mapping")
        state = cls(
            users=users,
            wallets=wallets,
            transactions=transactions,
            payment_requests=requests,
            idempotency_records=records,
            pending_audit_events=events,
            memory=BusinessMemory.from_dict(memory_data),
        )
        state.validate_invariants()
        return state

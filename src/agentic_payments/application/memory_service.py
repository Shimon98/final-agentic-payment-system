"""Immutable business memory models and in-process memory service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from agentic_payments.application.results import AgentResult, RouterDecision
from agentic_payments.domain import (
    Intent,
    PaymentRequest,
    PaymentRequestStatus,
    Transaction,
    User,
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty stripped string")
    return value


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise TypeError("mapping keys must be non-empty strings")
            result[key] = _json(nested)
        return result
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("Decimal values must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        return _aware(value, "datetime").isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        if not isfinite(value):
            raise TypeError("float values must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """One timestamped, JSON-compatible remembered action."""

    action: str
    occurred_at: datetime
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        _text(self.action, "action")
        _aware(self.occurred_at, "occurred_at")
        if not isinstance(self.details, Mapping):
            raise TypeError("details must be a mapping")
        converted = _json(self.details)
        object.__setattr__(self, "details", MappingProxyType(converted))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the memory entry."""

        return {
            "action": self.action,
            "occurred_at": self.occurred_at.isoformat(),
            "details": _json(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MemoryEntry:
        """Reconstruct a memory entry from serialized data."""

        required = {"action", "occurred_at", "details"}
        if set(data) != required:
            raise ValueError("memory entry fields are missing or unknown")
        occurred = data["occurred_at"]
        if not isinstance(occurred, str):
            raise ValueError("occurred_at must be an ISO-8601 string")
        try:
            parsed = datetime.fromisoformat(occurred)
        except ValueError as error:
            raise ValueError("occurred_at is malformed") from error
        details = data["details"]
        if not isinstance(details, Mapping):
            raise ValueError("details must be a mapping")
        return cls(action=data["action"], occurred_at=parsed, details=details)


@dataclass(frozen=True, slots=True)
class BusinessMemory:
    """Immutable snapshot of application-level business memory."""

    last_intent: Intent | None = None
    last_tool: str | None = None
    last_user_message: str | None = None
    last_action: str | None = None
    last_user_id: str | None = None
    last_transaction_id: str | None = None
    last_payment_request_id: str | None = None
    last_result: Mapping[str, Any] | None = None
    recent_actions: tuple[MemoryEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.last_intent is not None and not isinstance(self.last_intent, Intent):
            raise ValueError("last_intent must be an Intent or None")
        for field in (
            "last_tool",
            "last_user_message",
            "last_action",
            "last_user_id",
            "last_transaction_id",
            "last_payment_request_id",
        ):
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        if self.last_result is not None:
            if not isinstance(self.last_result, Mapping):
                raise TypeError("last_result must be a mapping")
            object.__setattr__(self, "last_result", MappingProxyType(_json(self.last_result)))
        if not isinstance(self.recent_actions, tuple):
            raise ValueError("recent_actions must be a tuple")
        if len(self.recent_actions) > 20:
            raise ValueError("recent_actions cannot exceed 20 entries")
        if not all(isinstance(entry, MemoryEntry) for entry in self.recent_actions):
            raise ValueError("recent_actions must contain MemoryEntry values")

    def to_dict(self) -> dict[str, Any]:
        """Serialize business memory."""

        return {
            "last_intent": self.last_intent.value if self.last_intent else None,
            "last_tool": self.last_tool,
            "last_user_message": self.last_user_message,
            "last_action": self.last_action,
            "last_user_id": self.last_user_id,
            "last_transaction_id": self.last_transaction_id,
            "last_payment_request_id": self.last_payment_request_id,
            "last_result": _json(self.last_result) if self.last_result is not None else None,
            "recent_actions": [entry.to_dict() for entry in self.recent_actions],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BusinessMemory:
        """Reconstruct business memory from serialized data."""

        required = {
            "last_intent",
            "last_tool",
            "last_user_message",
            "last_action",
            "last_user_id",
            "last_transaction_id",
            "last_payment_request_id",
            "last_result",
            "recent_actions",
        }
        if set(data) != required:
            raise ValueError("business memory fields are missing or unknown")
        actions = data["recent_actions"]
        if not isinstance(actions, list):
            raise ValueError("recent_actions must be a list")
        intent = data["last_intent"]
        return cls(
            last_intent=None if intent is None else Intent(intent),
            last_tool=data["last_tool"],
            last_user_message=data["last_user_message"],
            last_action=data["last_action"],
            last_user_id=data["last_user_id"],
            last_transaction_id=data["last_transaction_id"],
            last_payment_request_id=data["last_payment_request_id"],
            last_result=data["last_result"],
            recent_actions=tuple(MemoryEntry.from_dict(item) for item in actions),
        )


class MemoryService:
    """In-process service that replaces immutable business-memory snapshots."""

    def __init__(self, memory: BusinessMemory | None = None) -> None:
        self._memory = memory or BusinessMemory()

    def _actions(self, entry: MemoryEntry) -> tuple[MemoryEntry, ...]:
        return (*self._memory.recent_actions, entry)[-20:]

    def remember_route(
        self,
        decision: RouterDecision,
        user_message: str,
        *,
        occurred_at: datetime,
    ) -> None:
        """Remember a validated route using a caller-supplied timestamp."""

        _text(user_message, "user_message")
        _aware(occurred_at, "occurred_at")
        entry = MemoryEntry(
            "route",
            occurred_at,
            {
                "intent": decision.intent,
                "confidence": decision.confidence,
                "requires_clarification": decision.requires_clarification,
                "clarification_question": decision.clarification_question,
            },
        )
        self._memory = replace(
            self._memory,
            last_intent=decision.intent,
            last_user_message=user_message,
            last_action="route",
            recent_actions=self._actions(entry),
        )

    def remember_user(self, user: User, *, occurred_at: datetime) -> None:
        """Remember a created user."""

        _aware(occurred_at, "occurred_at")
        entry = MemoryEntry("createUser", occurred_at, {"user_id": user.user_id})
        self._memory = replace(
            self._memory,
            last_user_id=user.user_id,
            last_action="createUser",
            recent_actions=self._actions(entry),
        )

    def remember_transaction(self, transaction: Transaction, *, occurred_at: datetime) -> None:
        """Remember a transfer and its deterministic risk facts."""

        _aware(occurred_at, "occurred_at")
        details = {
            "transaction_id": transaction.transaction_id,
            "status": transaction.status,
            "sender_id": transaction.sender_id,
            "receiver_id": transaction.receiver_id,
            "amount": transaction.amount,
            "risk_score": transaction.risk_score,
            "risk_level": transaction.risk_level,
            "risk_reasons": transaction.risk_reasons,
        }
        entry = MemoryEntry("transferMoney", occurred_at, details)
        self._memory = replace(
            self._memory,
            last_transaction_id=transaction.transaction_id,
            last_action="transferMoney",
            recent_actions=self._actions(entry),
        )

    def remember_payment_request(
        self,
        request: PaymentRequest,
        *,
        occurred_at: datetime,
    ) -> None:
        """Remember a payment-request state transition."""

        _aware(occurred_at, "occurred_at")
        actions = {
            PaymentRequestStatus.PENDING: "requestPayment",
            PaymentRequestStatus.APPROVED: "approvePayment",
            PaymentRequestStatus.REJECTED: "rejectPayment",
        }
        action = actions[request.status]
        entry = MemoryEntry(
            action,
            occurred_at,
            {"request_id": request.request_id, "status": request.status},
        )
        self._memory = replace(
            self._memory,
            last_payment_request_id=request.request_id,
            last_action=action,
            recent_actions=self._actions(entry),
        )

    def remember_result(self, result: AgentResult, *, occurred_at: datetime) -> None:
        """Remember an agent result as JSON-compatible facts."""

        _aware(occurred_at, "occurred_at")
        output = result.output
        if isinstance(output, Mapping):
            converted_output = _json(output)
        elif isinstance(output, BaseModel):
            converted_output = output.model_dump(mode="json")
        elif is_dataclass(output) and not isinstance(output, type):
            converted_output = _json(asdict(output))
        elif output is None or isinstance(
            output, (str, int, bool, list, tuple, Decimal, datetime, Enum)
        ):
            converted_output = {"value": _json(output)}
        else:
            converted_output = {"value": str(output)}
        remembered = {
            "agent_name": result.agent_name,
            "output": converted_output,
            "confidence": result.confidence,
            "metadata": _json(result.metadata) if result.metadata is not None else None,
        }
        entry = MemoryEntry("agentResult", occurred_at, remembered)
        self._memory = replace(
            self._memory,
            last_tool=result.agent_name,
            last_action="agentResult",
            last_result=remembered,
            recent_actions=self._actions(entry),
        )

    def snapshot(self) -> BusinessMemory:
        """Return the current immutable memory snapshot."""

        return self._memory

    def reset(self) -> None:
        """Replace memory with an empty snapshot."""

        self._memory = BusinessMemory()

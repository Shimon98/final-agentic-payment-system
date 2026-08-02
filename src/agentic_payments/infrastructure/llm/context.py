"""Defensive immutable context supplied to read-only SDK agents and tools."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any

from agentic_payments.domain import Intent

_ALLOWED_INTENTS = frozenset(
    {
        Intent.FRAUD_CHECK,
        Intent.SECURITY_REVIEW,
        Intent.EXPLAIN_LAST_ACTION,
    }
)
_SECRET_KEY_MARKERS = (
    "api_key",
    "authorization",
    "secret",
    "password",
    "token",
    "prompt",
)
_MONEY_KEY_MARKERS = ("amount", "balance", "money", "price", "total", "fund")
_COMPLETE_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){7,15}(?!\d)")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _contains_complete_phone(value: str) -> bool:
    for match in _COMPLETE_PHONE.finditer(value):
        digits = re.sub(r"\D", "", match.group())
        if 7 <= len(digits) <= 15:
            return True
    return False


def _freeze_json(value: Any, *, path: str, money_context: bool = False) -> Any:
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            if not key or key != key.strip():
                raise ValueError(f"{path} keys must be non-empty stripped strings")
            lowered = key.lower()
            if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
                raise ValueError(f"{path} contains a prohibited key")
            nested_money = any(marker in lowered for marker in _MONEY_KEY_MARKERS)
            converted[key] = _freeze_json(
                nested,
                path=f"{path}.{key}",
                money_context=nested_money,
            )
        return MappingProxyType(converted)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, path=f"{path}[]", money_context=money_context) for item in value
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{path} Decimal must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        if not _is_aware(value):
            raise ValueError(f"{path} datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Enum):
        return _freeze_json(value.value, path=path, money_context=money_context)
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} float must be finite")
        if money_context:
            raise ValueError(f"{path} monetary float is not allowed")
        return value
    if isinstance(value, str):
        if _contains_complete_phone(value):
            raise ValueError(f"{path} must not contain a complete phone number")
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    raise TypeError(f"{path} contains unsupported mutable or domain value")


def json_compatible_copy(value: Any) -> Any:
    """Return a mutable JSON-compatible copy of a previously frozen value."""

    if isinstance(value, Mapping):
        return {key: json_compatible_copy(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [json_compatible_copy(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported frozen value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class SDKReadOnlyContext:
    """One immutable, recursively sanitized specialist invocation."""

    allowed_intent: Intent
    correlation_id: str
    requested_at: datetime
    facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.allowed_intent not in _ALLOWED_INTENTS:
            raise ValueError("allowed_intent must be an approved read-only intent")
        if (
            not isinstance(self.correlation_id, str)
            or not self.correlation_id
            or self.correlation_id != self.correlation_id.strip()
        ):
            raise ValueError("correlation_id must be a non-empty stripped string")
        if not isinstance(self.requested_at, datetime) or not _is_aware(self.requested_at):
            raise ValueError("requested_at must be timezone-aware")
        if not isinstance(self.facts, Mapping):
            raise TypeError("facts must be a mapping")
        frozen = _freeze_json(self.facts, path="facts")
        object.__setattr__(self, "facts", frozen)

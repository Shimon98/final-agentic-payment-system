"""Deterministically ordered resource lock identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class LockScope(IntEnum):
    """Define the mandatory cross-resource lock ordering."""

    IDEMPOTENCY = 10
    USER_REGISTRY = 20
    PAYMENT_REQUEST = 30
    TRANSACTION = 40
    WALLET = 50


@dataclass(frozen=True, order=True, slots=True)
class LockKey:
    """Identify one resource lock by ordered scope and exact identifier."""

    scope: LockScope
    resource_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, LockScope):
            raise TypeError("scope must be a LockScope")
        if not isinstance(self.resource_id, str):
            raise TypeError("resource_id must be a string")
        if not self.resource_id or self.resource_id != self.resource_id.strip():
            raise ValueError("resource_id must be a non-empty stripped string")

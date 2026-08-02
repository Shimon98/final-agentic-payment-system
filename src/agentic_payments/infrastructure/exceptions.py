"""Safe, structured failures raised by concrete infrastructure adapters."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


class InfrastructureError(Exception):
    """Base class for failures at an infrastructure boundary."""

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not message or message != message.strip():
            raise ValueError("message must be a non-empty stripped string")
        if context is not None and not isinstance(context, Mapping):
            raise TypeError("context must be a mapping or None")
        self._message = message
        self._context = MappingProxyType(dict(context or {}))
        super().__init__(message)

    @property
    def message(self) -> str:
        """Return the safe human-readable message."""

        return self._message

    @property
    def context(self) -> Mapping[str, Any]:
        """Return a read-only defensive copy of safe structured context."""

        return self._context


class StatePersistenceError(InfrastructureError):
    """Application state could not be safely loaded or persisted."""


class AuditPersistenceError(InfrastructureError):
    """Audit data could not be safely loaded or persisted."""


class AuditEventConflictError(AuditPersistenceError):
    """One audit event ID identifies different immutable content."""


class AuditLogCorruptionError(AuditPersistenceError):
    """An existing audit log contains malformed data."""


class ConfigurationError(InfrastructureError):
    """Infrastructure configuration is invalid."""

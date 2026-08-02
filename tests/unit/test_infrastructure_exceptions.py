"""Validation and secrecy tests for infrastructure exception types."""

from types import MappingProxyType

import pytest

from agentic_payments.infrastructure import (
    AuditEventConflictError,
    AuditLogCorruptionError,
    AuditPersistenceError,
    ConfigurationError,
    InfrastructureError,
    StatePersistenceError,
)


@pytest.mark.parametrize(
    "exception_type",
    [
        InfrastructureError,
        StatePersistenceError,
        AuditPersistenceError,
        AuditEventConflictError,
        AuditLogCorruptionError,
        ConfigurationError,
    ],
)
def test_infrastructure_exception_types_store_safe_message(exception_type: type[Exception]) -> None:
    error = exception_type("safe failure")
    assert str(error) == "safe failure"


@pytest.mark.parametrize("message", ["", " ", " leading", "trailing "])
def test_infrastructure_exception_rejects_invalid_message(message: str) -> None:
    with pytest.raises(ValueError):
        InfrastructureError(message)


def test_infrastructure_exception_context_is_defensive_and_read_only() -> None:
    supplied = {"path": "safe.json"}
    error = InfrastructureError("safe failure", context=supplied)
    supplied["path"] = "changed.json"

    assert isinstance(error.context, MappingProxyType)
    assert error.context == {"path": "safe.json"}
    with pytest.raises(TypeError):
        error.context["path"] = "mutated.json"  # type: ignore[index]


def test_infrastructure_exception_requires_mapping_context() -> None:
    with pytest.raises(TypeError):
        InfrastructureError("safe failure", context=["invalid"])  # type: ignore[arg-type]

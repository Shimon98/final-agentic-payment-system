"""Tests for application-state and idempotency serialization."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentic_payments.application import ApplicationState, IdempotencyRecord
from agentic_payments.domain import AuditEvent

NOW = datetime(2026, 6, 2, tzinfo=UTC)


def test_application_idempotency_record_validation_and_round_trip() -> None:
    record = IdempotencyRecord("IDEM-001", "create_user", "a" * 64, "USR-001", NOW)
    assert IdempotencyRecord.from_dict(record.to_dict()) == record


@pytest.mark.parametrize("fingerprint", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "123"])
def test_application_idempotency_rejects_invalid_fingerprint(fingerprint: str) -> None:
    with pytest.raises(ValueError):
        IdempotencyRecord("IDEM", "operation", fingerprint, "REF", NOW)


def test_application_idempotency_rejects_naive_or_malformed_time() -> None:
    with pytest.raises(ValueError):
        IdempotencyRecord("IDEM", "operation", "a" * 64, "REF", datetime(2026, 1, 1))
    data = IdempotencyRecord("IDEM", "operation", "a" * 64, "REF", NOW).to_dict()
    data["created_at"] = "bad"
    with pytest.raises(ValueError):
        IdempotencyRecord.from_dict(data)


def test_application_state_serialization_round_trip_and_exact_keys() -> None:
    event_b = AuditEvent("EVT-B", "COR", "ACTION", "SUCCESS", NOW, "system", {})
    event_a = AuditEvent("EVT-A", "COR", "ACTION", "SUCCESS", NOW, "system", {})
    state = ApplicationState(pending_audit_events={"EVT-B": event_b, "EVT-A": event_a})
    serialized = state.to_dict()
    assert list(serialized) == [
        "users",
        "wallets",
        "transactions",
        "payment_requests",
        "idempotency_records",
        "pending_audit_events",
        "memory",
    ]
    assert list(serialized["pending_audit_events"]) == ["EVT-A", "EVT-B"]
    restored = ApplicationState.from_dict(serialized)
    assert restored.to_dict() == serialized


def test_application_state_serialization_rejects_missing_unknown_or_malformed() -> None:
    data = ApplicationState().to_dict()
    missing = dict(data)
    del missing["users"]
    with pytest.raises(ValueError):
        ApplicationState.from_dict(missing)
    unknown = {**data, "extra": {}}
    with pytest.raises(ValueError):
        ApplicationState.from_dict(unknown)
    malformed = dict(data)
    malformed["wallets"] = []
    with pytest.raises(ValueError):
        ApplicationState.from_dict(malformed)

"""Backward-compatible IdempotencyRecord result-payload tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

import pytest

from agentic_payments.application import ApplicationState, IdempotencyRecord

FIXED = datetime(2026, 5, 6, 7, 8, tzinfo=UTC)
FINGERPRINT = "a" * 64


class ExampleEnum(StrEnum):
    VALUE = "VALUE"


def _record(payload: object = None) -> IdempotencyRecord:
    return IdempotencyRecord(
        idempotency_key="IDEMP-1",
        operation_type="transferMoney",
        request_fingerprint=FINGERPRINT,
        result_reference="TXN-1",
        created_at=FIXED,
        result_payload=payload,  # type: ignore[arg-type]
    )


def test_none_payload_remains_backward_compatible() -> None:
    record = _record()

    assert record.result_payload is None
    assert record.to_dict()["result_payload"] is None


def test_payload_is_defensively_recursively_copied() -> None:
    source = {"nested": {"items": ["original"]}}
    record = _record(source)
    source["nested"]["items"].append("changed")

    assert record.result_payload == {"nested": {"items": ["original"]}}
    assert isinstance(record.result_payload, MappingProxyType)


def test_payload_converts_decimal_datetime_and_enum() -> None:
    record = _record(
        {
            "amount": Decimal("12.30"),
            "occurred_at": FIXED,
            "status": ExampleEnum.VALUE,
        }
    )

    assert record.to_dict()["result_payload"] == {
        "amount": "12.30",
        "occurred_at": FIXED.isoformat(),
        "status": "VALUE",
    }


@pytest.mark.parametrize("value", [1.5, object(), {1: "invalid"}])
def test_unsupported_payload_values_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        _record({"value": value})


def test_to_dict_and_from_dict_round_trip_payload() -> None:
    original = _record({"result_type": "Example", "values": [1, True, None]})

    restored = IdempotencyRecord.from_dict(original.to_dict())

    assert restored == original
    assert restored.result_payload == original.result_payload


def test_from_dict_accepts_legacy_record_without_payload() -> None:
    legacy = {
        "idempotency_key": "IDEMP-1",
        "operation_type": "transferMoney",
        "request_fingerprint": FINGERPRINT,
        "result_reference": "TXN-1",
        "created_at": FIXED.isoformat(),
    }

    restored = IdempotencyRecord.from_dict(legacy)

    assert restored.result_payload is None


def test_application_state_clone_preserves_independent_payload() -> None:
    state = ApplicationState(idempotency_records={"IDEMP-1": _record({"nested": {"x": 1}})})

    clone = state.clone()

    assert clone.idempotency_records["IDEMP-1"].result_payload == {"nested": {"x": 1}}
    assert (
        clone.idempotency_records["IDEMP-1"].result_payload
        is not state.idempotency_records["IDEMP-1"].result_payload
    )

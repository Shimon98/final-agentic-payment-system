"""Safe formatter behavior and redaction tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pytest
from pydantic import BaseModel

from agentic_payments.application import AgentResult, ApplicationState
from agentic_payments.application.payment_domain_service import PaymentDomainService
from agentic_payments.domain import Intent
from agentic_payments.infrastructure import JsonStateRepository, Settings
from agentic_payments.infrastructure.concurrency import AsyncResourceLockManager
from agentic_payments.presentation.formatters import (
    format_agent_result,
    format_help,
    format_status,
    to_safe_json_value,
)


class _Schema(BaseModel):
    amount: Decimal
    occurred_at: datetime


class _Example(Enum):
    VALUE = "value"


@dataclass(frozen=True)
class _Record:
    amount: Decimal
    kind: _Example


def test_agent_result_is_stable_sorted_utf8_json() -> None:
    result = AgentResult(
        "Agent",
        {"שלום": "עולם", "amount": Decimal("10.00")},
        confidence=0.9,
        metadata={"z": 2, "a": 1},
    )

    rendered = format_agent_result(result)

    assert rendered == format_agent_result(result)
    assert rendered.index('"agent_name"') < rendered.index('"confidence"')
    assert "\\u" not in rendered
    assert json.loads(rendered)["output"]["amount"] == "10.00"


def test_agent_result_requires_exact_type() -> None:
    with pytest.raises(TypeError):
        format_agent_result(object())  # type: ignore[arg-type]


def test_pydantic_decimal_datetime_enum_and_dataclass_conversion() -> None:
    occurred_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    converted = to_safe_json_value(
        {
            "schema": _Schema(amount=Decimal("1.25"), occurred_at=occurred_at),
            "record": _Record(Decimal("2.50"), _Example.VALUE),
        }
    )

    assert converted == {
        "schema": {"amount": "1.25", "occurred_at": "2026-01-02T03:04:00Z"},
        "record": {"amount": "2.50", "kind": "value"},
    }


@pytest.mark.parametrize("field", ["confidence", "route_confidence", "confidence_threshold"])
def test_approved_confidence_float_is_allowed(field: str) -> None:
    assert to_safe_json_value({field: 0.75}) == {field: 0.75}


@pytest.mark.parametrize(
    "value",
    [
        {"amount": 1.25},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": float("-inf")},
    ],
)
def test_monetary_and_nonfinite_floats_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        to_safe_json_value(value)


@pytest.mark.parametrize(
    "key",
    ["api_key", "Authorization", "db_password", "client_secret", "access_token", "system_prompt"],
)
def test_secret_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match="prohibited"):
        to_safe_json_value({key: "sensitive"})


def test_complete_phone_numbers_and_phone_fields_are_redacted() -> None:
    converted = to_safe_json_value(
        {
            "phone_number": "0501234567",
            "nested": ["call 0509876543 now"],
            "label": "safe",
        }
    )

    assert converted == {
        "phone_number": "[REDACTED]",
        "nested": ["call [REDACTED] now"],
        "label": "safe",
    }


@pytest.mark.parametrize(
    "value",
    [
        RuntimeError("sensitive"),
        ApplicationState(),
        JsonStateRepository(Path("state.json")),
        AsyncResourceLockManager(),
        PaymentDomainService,
    ],
)
def test_exceptions_state_repository_lock_and_unknown_objects_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        to_safe_json_value(value)


@pytest.mark.asyncio
async def test_status_contains_only_safe_aggregate_fields(tmp_path: Path) -> None:
    from agentic_payments.bootstrap import build_application

    settings = Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )
    container = await build_application(settings)

    payload = json.loads(format_status(container))

    assert set(payload) == {
        "app_environment",
        "llm_provider",
        "llm_router_enabled",
        "user_count",
        "wallet_count",
        "transaction_count",
        "payment_request_count",
        "pending_audit_count",
        "last_memory_action",
        "startup_warning_count",
    }
    rendered = format_status(container).lower()
    assert "api_key" not in rendered
    assert str(tmp_path).lower() not in rendered
    assert "balance" not in rendered
    assert "phone" not in rendered


def test_help_contains_all_ten_intents_in_english_and_hebrew() -> None:
    rendered = format_help()
    intents = [
        "createUser",
        "checkBalance",
        "transferMoney",
        "requestPayment",
        "approvePayment",
        "rejectPayment",
        "showTransactions",
        "fraudCheck",
        "securityReview",
        "explainLastAction",
    ]

    assert all(intent in rendered for intent in intents)
    assert "יצירת משתמש" in rendered
    assert "הסבר הפעולה האחרונה" in rendered
    assert len(list(Intent)) == 11  # Ten supported intents plus UNKNOWN.

"""Deterministic routing tests for exact English and Hebrew grammars."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.agents import AgentContext, RouterAgent
from agentic_payments.application import AgentResult, BusinessMemory, RouterDecision
from agentic_payments.domain import Intent

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)

_ENGLISH_CASES = [
    (
        'createUser name="Alice Cohen" phone=0501234567 initial_balance=100.00',
        Intent.CREATE_USER,
        {
            "name": "Alice Cohen",
            "phone_number": "0501234567",
            "initial_balance": Decimal("100.00"),
        },
    ),
    ("checkBalance user_id=USR-001", Intent.CHECK_BALANCE, {"user_id": "USR-001"}),
    (
        "transferMoney sender_id=USR-001 receiver_id=USR-002 amount=25.50",
        Intent.TRANSFER_MONEY,
        {
            "sender_id": "USR-001",
            "receiver_id": "USR-002",
            "amount": Decimal("25.50"),
        },
    ),
    (
        "requestPayment requester_id=USR-001 payer_id=USR-002 amount=30.00",
        Intent.REQUEST_PAYMENT,
        {
            "requester_id": "USR-001",
            "payer_id": "USR-002",
            "amount": Decimal("30.00"),
        },
    ),
    ("approvePayment request_id=REQ-001", Intent.APPROVE_PAYMENT, {"request_id": "REQ-001"}),
    ("rejectPayment request_id=REQ-001", Intent.REJECT_PAYMENT, {"request_id": "REQ-001"}),
    ("showTransactions user_id=USR-001", Intent.SHOW_TRANSACTIONS, {"user_id": "USR-001"}),
    ("fraudCheck transaction_id=TXN-001", Intent.FRAUD_CHECK, {"transaction_id": "TXN-001"}),
    (
        "securityReview transaction_id=TXN-001",
        Intent.SECURITY_REVIEW,
        {"transaction_id": "TXN-001"},
    ),
    ("securityReview", Intent.SECURITY_REVIEW, {"transaction_id": None}),
    ("explainLastAction", Intent.EXPLAIN_LAST_ACTION, {}),
]

_HEBREW_COMMANDS = [
    ("צורמשתמש", _ENGLISH_CASES[0][0].split(" ", 1)[1], Intent.CREATE_USER),
    ("בדוקיתרה", "user_id=USR-001", Intent.CHECK_BALANCE),
    (
        "העברכסף",
        "sender_id=USR-001 receiver_id=USR-002 amount=25.50",
        Intent.TRANSFER_MONEY,
    ),
    (
        "בקששלום",
        "requester_id=USR-001 payer_id=USR-002 amount=30.00",
        Intent.REQUEST_PAYMENT,
    ),
    ("אשרתשלום", "request_id=REQ-001", Intent.APPROVE_PAYMENT),
    ("דחהתשלום", "request_id=REQ-001", Intent.REJECT_PAYMENT),
    ("הצגעסקאות", "user_id=USR-001", Intent.SHOW_TRANSACTIONS),
    ("בדיקתהונאה", "transaction_id=TXN-001", Intent.FRAUD_CHECK),
    ("בדיקתאבטחה", "transaction_id=TXN-001", Intent.SECURITY_REVIEW),
    ("הסברפעולהאחרונה", "", Intent.EXPLAIN_LAST_ACTION),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("command", "intent", "parameters"), _ENGLISH_CASES)
async def test_every_canonical_english_intent(
    command: str,
    intent: Intent,
    parameters: dict[str, Any],
) -> None:
    result = await RouterAgent().route(command)
    decision = result.output

    assert isinstance(result, AgentResult)
    assert isinstance(decision, RouterDecision)
    assert decision.intent is intent
    assert decision.parameters == parameters
    assert decision.confidence == 1.0
    assert result.metadata == {
        "mode": "canonical",
        "confidence_threshold": 0.8,
        "below_threshold": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("alias", "parameters", "intent"), _HEBREW_COMMANDS)
async def test_every_canonical_hebrew_alias(
    alias: str,
    parameters: str,
    intent: Intent,
) -> None:
    command = f"{alias} {parameters}".strip()
    result = await RouterAgent().route(command)
    assert result.output.intent is intent
    assert result.output.confidence == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "transfer 25.50 from USR-001 to USR-002",
        "transfer 25.50 ILS from USR-001 to USR-002",
        "העבר 25.50 מ-USR-001 ל-USR-002",
        "העבר 25.50 שקלים מ- USR-001 ל- USR-002",
    ],
)
async def test_supported_natural_transfer_forms(command: str) -> None:
    result = await RouterAgent().route(command)
    assert result.output == RouterDecision(
        intent=Intent.TRANSFER_MONEY,
        parameters={
            "sender_id": "USR-001",
            "receiver_id": "USR-002",
            "amount": Decimal("25.50"),
        },
        confidence=0.90,
    )
    assert result.metadata["mode"] == "natural"


@pytest.mark.asyncio
async def test_amounts_are_decimal_and_never_float() -> None:
    decision = (
        await RouterAgent().route("transferMoney sender_id=A receiver_id=B amount=25.50")
    ).output
    assert decision.parameters["amount"] == Decimal("25.50")
    assert not isinstance(decision.parameters["amount"], float)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "preserved"),
    [
        ("transferMoney sender_id=A amount=1.00", {"sender_id": "A", "amount": Decimal("1.00")}),
        (
            "transferMoney sender_id=A receiver_id=B amount=not-money",
            {"sender_id": "A", "receiver_id": "B"},
        ),
        (
            "checkBalance user_id=USR-1 unexpected=value",
            {"user_id": "USR-1"},
        ),
    ],
)
async def test_malformed_or_missing_canonical_input_requests_clarification(
    command: str,
    preserved: dict[str, Any],
) -> None:
    result = await RouterAgent().route(command)
    decision = result.output
    assert decision.confidence == 0.60
    assert decision.requires_clarification is True
    assert decision.clarification_question
    assert decision.parameters == preserved
    assert result.metadata["mode"] == "clarification"
    assert result.metadata["below_threshold"] is True


@pytest.mark.asyncio
async def test_unknown_has_no_executable_parameters_or_invented_values() -> None:
    result = await RouterAgent().route("please do something magical with USR-1")
    decision = result.output
    assert decision.intent is Intent.UNKNOWN
    assert decision.parameters == {}
    assert decision.confidence == 0.0
    assert decision.requires_clarification
    assert result.metadata["mode"] == "unknown"


@pytest.mark.asyncio
async def test_threshold_metadata_uses_configured_value() -> None:
    result = await RouterAgent(confidence_threshold=0.50).route("unknown")
    assert result.metadata["confidence_threshold"] == 0.50
    assert result.metadata["below_threshold"] is True


@pytest.mark.parametrize("threshold", [True, -0.01, 1.01, "0.8"])
def test_invalid_confidence_threshold_is_rejected(threshold: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        RouterAgent(confidence_threshold=threshold)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_non_string_input_is_programming_error() -> None:
    with pytest.raises(TypeError):
        await RouterAgent().route(123)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_routes_context_input_and_returns_agent_result() -> None:
    context = AgentContext(
        "checkBalance user_id=USR-1",
        "COR-1",
        NOW,
        BusinessMemory(),
    )
    result = await RouterAgent().run(context)
    assert isinstance(result, AgentResult)
    assert result.output.intent is Intent.CHECK_BALANCE

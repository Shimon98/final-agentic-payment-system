"""Factual bilingual explanation tests without inference or sensitive leakage."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentic_payments.agents import AgentContext, ExplanationAgent
from agentic_payments.application import AgentResult, BusinessMemory
from agentic_payments.domain import Intent, RiskLevel, Transaction, TransactionStatus

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _transaction(
    status: TransactionStatus,
    *,
    reasons: tuple[str, ...] = (),
    failure_reason: str | None = None,
) -> Transaction:
    return Transaction(
        "TXN-1",
        "SENDER",
        "RECEIVER",
        Decimal("25.50"),
        NOW,
        status,
        80 if status is TransactionStatus.FLAGGED else 0,
        RiskLevel.HIGH if status is TransactionStatus.FLAGGED else RiskLevel.LOW,
        reasons,
        failure_reason,
        "COR-1",
        "IDEM-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transaction", "expected_phrase"),
    [
        (_transaction(TransactionStatus.COMPLETED), "completed"),
        (
            _transaction(
                TransactionStatus.FLAGGED,
                reasons=("stored_reason",),
            ),
            "flagged",
        ),
        (
            _transaction(
                TransactionStatus.FAILED,
                failure_reason="stored failure",
            ),
            "failed",
        ),
        (_transaction(TransactionStatus.REJECTED), "rejected"),
    ],
)
async def test_transaction_status_explanations(
    transaction: Transaction,
    expected_phrase: str,
) -> None:
    result = await ExplanationAgent().explain_transaction(transaction)
    assert isinstance(result, AgentResult)
    assert result.confidence == 1.0
    assert expected_phrase in result.output["message_en"].lower()
    assert result.output["message_he"]


@pytest.mark.asyncio
async def test_transaction_facts_are_exact_and_json_compatible() -> None:
    transaction = _transaction(
        TransactionStatus.FLAGGED,
        reasons=("stored_reason",),
    )
    output = (await ExplanationAgent().explain_transaction(transaction)).output

    assert set(output) == {"message_he", "message_en", "facts"}
    assert output["facts"] == {
        "transaction_id": "TXN-1",
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "amount": "25.50",
        "status": "FLAGGED",
        "risk_score": 80,
        "risk_level": "HIGH",
        "risk_reasons": ["stored_reason"],
        "failure_reason": None,
    }
    assert "stored_reason" in str(output)
    assert "invented" not in str(output)


@pytest.mark.asyncio
async def test_last_result_memory_explanation_redacts_sensitive_values() -> None:
    memory = BusinessMemory(
        last_action="agentResult",
        last_result={
            "status": "SUCCESS",
            "phone_number": "0501234567",
            "api_key": "secret-value",
            "unlabeled_sensitive_value": "0527654321",
        },
    )
    result = await ExplanationAgent().explain_last_action(memory)

    assert result.confidence == 0.95
    assert result.output["facts"]["status"] == "SUCCESS"
    rendered = str(result.output)
    assert "0501234567" not in rendered
    assert "0527654321" not in rendered
    assert "secret-value" not in rendered


@pytest.mark.asyncio
async def test_reference_only_and_empty_memory_confidence_levels() -> None:
    reference = BusinessMemory(
        last_intent=Intent.TRANSFER_MONEY,
        last_action="transferMoney",
        last_transaction_id="TXN-1",
    )
    reference_result = await ExplanationAgent().explain_last_action(reference)
    empty_result = await ExplanationAgent().explain_last_action(BusinessMemory())

    assert reference_result.confidence == 0.75
    assert reference_result.output["facts"] == {
        "last_action": "transferMoney",
        "last_intent": "transferMoney",
        "last_transaction_id": "TXN-1",
    }
    assert empty_result.confidence == 0.60
    assert empty_result.output["facts"] == {}
    assert "no previous action" in empty_result.output["message_en"].lower()
    assert empty_result.output["message_he"]


@pytest.mark.asyncio
async def test_run_dispatches_transaction_or_memory() -> None:
    agent = ExplanationAgent()
    transaction = _transaction(TransactionStatus.COMPLETED)
    transaction_result = await agent.run(
        AgentContext(
            "explain",
            "COR-1",
            NOW,
            BusinessMemory(),
            payload={"transaction": transaction},
        )
    )
    memory_result = await agent.run(AgentContext("explain", "COR-1", NOW, BusinessMemory()))

    assert transaction_result.confidence == 1.0
    assert memory_result.confidence == 0.60


@pytest.mark.asyncio
async def test_run_rejects_invalid_transaction_payload() -> None:
    with pytest.raises(TypeError):
        await ExplanationAgent().run(
            AgentContext(
                "explain",
                "COR-1",
                NOW,
                BusinessMemory(),
                payload={"transaction": "not a transaction"},
            )
        )

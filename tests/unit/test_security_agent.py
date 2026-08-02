"""Read-only security review tests for transaction and aggregate facts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentic_payments.agents import AgentContext, SecurityAgent
from agentic_payments.application import (
    AgentResult,
    ApplicationState,
    BusinessMemory,
    SecurityReview,
)
from agentic_payments.domain import (
    RiskLevel,
    Transaction,
    TransactionSnapshot,
    TransactionStatus,
    User,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _snapshot() -> TransactionSnapshot:
    transaction = Transaction(
        "TXN-1",
        "SENDER",
        "RECEIVER",
        Decimal("10.00"),
        NOW,
        TransactionStatus.COMPLETED,
        0,
        RiskLevel.LOW,
        (),
        None,
        "COR-1",
        "IDEM-1",
    )
    return TransactionSnapshot(
        transaction,
        Decimal("100.00"),
        Decimal("90.00"),
        Decimal("20.00"),
        Decimal("30.00"),
        (),
    )


@pytest.mark.asyncio
async def test_valid_transaction_snapshot_has_exact_checks() -> None:
    result = await SecurityAgent().review_transaction(_snapshot())
    assert result.output == SecurityReview(
        approved=True,
        checks_performed=[
            "positive_amount",
            "different_participants",
            "sender_balance_equation",
            "receiver_balance_equation",
            "non_negative_balances",
            "supported_status",
        ],
        violations=[],
        recommendations=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "violation"),
    [
        (("transaction", "amount", Decimal("0.00")), "invalid_amount"),
        (("transaction", "receiver_id", "SENDER"), "self_transfer"),
        (("snapshot", "sender_balance_after", Decimal("89.00")), "sender_balance_mismatch"),
        (("snapshot", "receiver_balance_after", Decimal("31.00")), "receiver_balance_mismatch"),
        (("snapshot", "sender_balance_after", Decimal("-1.00")), "negative_balance"),
        (
            ("transaction", "status", TransactionStatus.PENDING),
            "unsupported_transaction_status",
        ),
    ],
)
async def test_each_transaction_violation(
    mutation: tuple[str, str, object],
    violation: str,
) -> None:
    snapshot = _snapshot()
    target, field_name, value = mutation
    subject = snapshot.transaction if target == "transaction" else snapshot
    object.__setattr__(subject, field_name, value)

    result = await SecurityAgent().review_transaction(snapshot)

    assert violation in result.output.violations
    assert result.output.approved is False
    assert len(result.output.recommendations) == len(result.output.violations)


@pytest.mark.asyncio
async def test_multiple_violations_retain_check_order() -> None:
    snapshot = _snapshot()
    object.__setattr__(snapshot.transaction, "amount", Decimal("0.00"))
    object.__setattr__(snapshot.transaction, "receiver_id", "SENDER")
    object.__setattr__(snapshot, "sender_balance_after", Decimal("-1.00"))
    object.__setattr__(snapshot.transaction, "status", TransactionStatus.PENDING)

    violations = (await SecurityAgent().review_transaction(snapshot)).output.violations
    assert violations == [
        "invalid_amount",
        "self_transfer",
        "sender_balance_mismatch",
        "receiver_balance_mismatch",
        "negative_balance",
        "unsupported_transaction_status",
    ]


@pytest.mark.asyncio
async def test_valid_and_invalid_application_state_reviews_do_not_mutate_input() -> None:
    agent = SecurityAgent()
    valid = ApplicationState()
    approved = await agent.review_system(valid)
    assert approved.output.approved is True
    assert approved.output.checks_performed == ["application_state_invariants"]

    user = User("USR-1", "Alice", "0501234567", NOW)
    invalid = ApplicationState(users={user.user_id: user})
    before = invalid.to_dict()
    rejected = await agent.review_system(invalid)
    assert rejected.output == SecurityReview(
        approved=False,
        checks_performed=["application_state_invariants"],
        violations=["state_invariant_violation"],
        recommendations=["Review application-state references and invariants safely."],
    )
    assert invalid.to_dict() == before
    assert "0501234567" not in str(rejected.output)


@pytest.mark.asyncio
async def test_run_dispatches_exactly_one_payload_target() -> None:
    agent = SecurityAgent()
    transaction_result = await agent.run(
        AgentContext(
            "security",
            "COR-1",
            NOW,
            BusinessMemory(),
            payload={"snapshot": _snapshot()},
        )
    )
    system_result = await agent.run(
        AgentContext(
            "security",
            "COR-1",
            NOW,
            BusinessMemory(),
            payload={"state": ApplicationState()},
        )
    )
    assert isinstance(transaction_result, AgentResult)
    assert isinstance(system_result, AgentResult)

    for payload in ({}, {"snapshot": _snapshot(), "state": ApplicationState()}):
        with pytest.raises(ValueError):
            await agent.run(
                AgentContext("security", "COR-1", NOW, BusinessMemory(), payload=payload)
            )

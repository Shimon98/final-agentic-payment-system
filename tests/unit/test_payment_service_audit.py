"""Audit-outbox and risk-annotation tests for PaymentDomainService."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from conftest import DeterministicIdGenerator

from agentic_payments.domain import RiskLevel, StateInvariantError, TransactionStatus


async def _transferred_harness(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> Any:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )
    snapshot = await harness.service.transfer_money(
        sender_id="SENDER",
        receiver_id="RECEIVER",
        amount=Decimal("10.00"),
        idempotency_key="IDEMP-TRANSFER",
        correlation_id="CORR-TRANSFER",
    )
    return harness, snapshot


@pytest.mark.asyncio
async def test_transfer_audit_contains_exact_financial_facts(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness, snapshot = await _transferred_harness(
        payment_harness_factory,
        application_state_factory,
    )

    event = next(iter(harness.manager.current_state.pending_audit_events.values()))

    assert event.action == "transferMoney"
    assert event.status == "SUCCESS"
    assert event.actor == "system"
    assert event.correlation_id == "CORR-TRANSFER"
    assert event.details == {
        "transaction_id": snapshot.transaction.transaction_id,
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "amount": "10.00",
        "sender_balance_before": "100.00",
        "sender_balance_after": "90.00",
        "receiver_balance_before": "20.00",
        "receiver_balance_after": "30.00",
    }


@pytest.mark.asyncio
async def test_low_risk_annotation_replaces_transaction_without_wallet_change(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness, snapshot = await _transferred_harness(
        payment_harness_factory,
        application_state_factory,
    )
    before = harness.manager.current_state.wallets

    updated = await harness.service.annotate_transaction_risk(
        transaction_id=snapshot.transaction.transaction_id,
        score=10,
        level=RiskLevel.LOW,
        reasons=["reviewed"],
        flagged=False,
        idempotency_key="IDEMP-RISK",
        correlation_id="CORR-RISK",
    )

    assert updated.status is TransactionStatus.COMPLETED
    assert updated.risk_score == 10
    assert updated.risk_reasons == ("reviewed",)
    assert harness.manager.current_state.wallets == before


@pytest.mark.asyncio
async def test_flagged_risk_annotation_creates_flagged_audit(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness, snapshot = await _transferred_harness(
        payment_harness_factory,
        application_state_factory,
    )

    updated = await harness.service.annotate_transaction_risk(
        transaction_id=snapshot.transaction.transaction_id,
        score=90,
        level=RiskLevel.HIGH,
        reasons=["large", "rapid"],
        flagged=True,
        idempotency_key="IDEMP-RISK",
        correlation_id="CORR-RISK",
    )
    events = list(harness.manager.current_state.pending_audit_events.values())

    assert updated.status is TransactionStatus.FLAGGED
    assert events[-1].action == "annotateTransactionRisk"
    assert events[-1].status == "FLAGGED"
    assert events[-1].details["risk_level"] == "HIGH"
    assert events[-1].details["reasons"] == ["large", "rapid"]


@pytest.mark.asyncio
async def test_missing_transaction_risk_annotation_raises_state_invariant(
    payment_harness_factory: Any,
) -> None:
    harness = payment_harness_factory()

    with pytest.raises(StateInvariantError) as captured:
        await harness.service.annotate_transaction_risk(
            transaction_id="MISSING",
            score=10,
            level=RiskLevel.LOW,
            reasons=[],
            flagged=False,
            idempotency_key="IDEMP-RISK",
            correlation_id="CORR-RISK",
        )

    assert captured.value.context["transaction_id"] == "MISSING"


@pytest.mark.asyncio
async def test_audit_event_id_collision_rolls_back_entire_operation(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    ids = DeterministicIdGenerator(audit_event_ids=["AUD-SAME", "AUD-SAME"])
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        ),
        ids=ids,
    )
    await harness.service.transfer_money(
        sender_id="SENDER",
        receiver_id="RECEIVER",
        amount=Decimal("10.00"),
        idempotency_key="IDEMP-FIRST",
        correlation_id="CORR-FIRST",
    )

    with pytest.raises(StateInvariantError, match="audit event ID already exists"):
        await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id="RECEIVER",
            amount=Decimal("10.00"),
            idempotency_key="IDEMP-SECOND",
            correlation_id="CORR-SECOND",
        )

    state = harness.manager.current_state
    assert state.wallets["SENDER"].balance == Decimal("90.00")
    assert len(state.transactions) == 1
    assert len(state.pending_audit_events) == 1


@pytest.mark.asyncio
async def test_audit_events_remain_pending_and_are_not_delivered(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness, _ = await _transferred_harness(
        payment_harness_factory,
        application_state_factory,
    )

    assert len(harness.manager.current_state.pending_audit_events) == 1
    assert not hasattr(harness.service, "flush_pending")

"""Committed-operation post-processing and snapshot tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.agents import ExplanationAgent, PolicyAgent, SecurityAgent
from agentic_payments.application import (
    AgentResult,
    ApprovePaymentCommand,
    FraudAssessment,
    FraudCheckCommand,
    RequestContext,
    RequestPaymentCommand,
    TransferMoneyCommand,
)
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import RiskLevel, StateInvariantError, TransferPolicy

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _policy() -> TransferPolicy:
    return TransferPolicy(
        maximum_single_transfer=Decimal("1000.00"),
        maximum_daily_transfer=Decimal("5000.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )


class _Fraud:
    def __init__(self, score: int, level: RiskLevel, security: bool) -> None:
        self.score = score
        self.level = level
        self.security = security

    async def assess_transaction(self, snapshot: Any) -> AgentResult:
        return AgentResult(
            "Fraud",
            FraudAssessment(
                transaction_id=snapshot.transaction.transaction_id,
                risk_score=self.score,
                risk_level=self.level,
                reasons=["fixed"],
                requires_security_review=self.security,
            ),
        )


class _FailingFraud:
    async def assess_transaction(self, snapshot: Any) -> AgentResult:
        raise RuntimeError("sensitive details must not escape")


class _CancellingFraud:
    async def assess_transaction(self, snapshot: Any) -> AgentResult:
        raise asyncio.CancelledError


class _CountingSecurity(SecurityAgent):
    def __init__(self) -> None:
        self.calls = 0

    async def review_transaction(self, snapshot: Any) -> AgentResult:
        self.calls += 1
        return await super().review_transaction(snapshot)


def _facade(harness: Any, fraud: Any, security: Any) -> PaymentFacade:
    return PaymentFacade(
        payment_service=harness.service,
        transaction_manager=harness.manager,
        fraud_agent=fraud,
        security_agent=security,
        explanation_agent=ExplanationAgent(),
        policy_agent=PolicyAgent(transfer_policy=_policy()),
    )


def _command(key: str, amount: str = "80.00") -> TransferMoneyCommand:
    return TransferMoneyCommand(
        "SENDER",
        "RECEIVER",
        Decimal(amount),
        RequestContext(f"COR-{key}", key, NOW),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "level", "review", "status"),
    [
        (80, RiskLevel.HIGH, True, "FLAGGED"),
        (50, RiskLevel.MEDIUM, True, "COMPLETED"),
        (10, RiskLevel.LOW, False, "COMPLETED"),
    ],
)
async def test_risk_annotation_and_conditional_security(
    payment_harness_factory: Any,
    application_state_factory: Any,
    score: int,
    level: RiskLevel,
    review: bool,
    status: str,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        ),
        transfer_policy=_policy(),
    )
    security = _CountingSecurity()
    facade = _facade(harness, _Fraud(score, level, review), security)

    result = await facade.transfer_money(_command(f"IDEMP-{score}"))
    transaction = harness.manager.current_state.transactions[result.output["transaction_id"]]

    assert transaction.status.value == status
    assert security.calls == int(review)
    assert f"IDEMP-{score}:risk:{transaction.transaction_id}" in (
        harness.manager.current_state.idempotency_records
    )


@pytest.mark.asyncio
async def test_approval_uses_same_post_processing_pipeline(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        ),
        transfer_policy=_policy(),
    )
    security = _CountingSecurity()
    facade = _facade(harness, _Fraud(50, RiskLevel.MEDIUM, True), security)
    pending = await facade.request_payment(
        RequestPaymentCommand(
            "RECEIVER",
            "SENDER",
            Decimal("10.00"),
            RequestContext("COR-R", "IDEMP-R", NOW),
        )
    )

    result = await facade.approve_payment(
        ApprovePaymentCommand(
            pending.output["payment_request_id"],
            RequestContext("COR-A", "IDEMP-A", NOW),
        )
    )

    assert result.output["post_processing_status"] == "completed"
    assert security.calls == 1
    assert f"IDEMP-A:risk:{result.output['transaction_id']}" in (
        harness.manager.current_state.idempotency_records
    )


@pytest.mark.asyncio
async def test_committed_transfer_degrades_and_cancellation_propagates(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"SENDER": Decimal("200.00"), "RECEIVER": Decimal("0.00")})
    degraded_harness = payment_harness_factory(initial_state=state, transfer_policy=_policy())
    degraded = await _facade(degraded_harness, _FailingFraud(), _CountingSecurity()).transfer_money(
        _command("IDEMP-DEG", "20.00")
    )

    assert degraded.output["post_processing_status"] == "degraded"
    assert degraded.confidence == 0.85
    assert degraded.metadata == {
        "post_processing_error_type": "RuntimeError",
        "post_processing_error_message": "Committed operation post-processing failed",
        "financial_operation_committed": True,
    }
    assert degraded_harness.manager.current_state.wallets["SENDER"].balance == Decimal("180.00")

    cancel_harness = payment_harness_factory(initial_state=state, transfer_policy=_policy())
    with pytest.raises(asyncio.CancelledError):
        await _facade(cancel_harness, _CancellingFraud(), _CountingSecurity()).transfer_money(
            _command("IDEMP-CANCEL", "20.00")
        )


@pytest.mark.asyncio
async def test_snapshot_lookup_uses_original_balances_and_current_transaction(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("10.00")}
        ),
        transfer_policy=_policy(),
    )
    facade = _facade(harness, _Fraud(80, RiskLevel.HIGH, True), _CountingSecurity())
    transferred = await facade.transfer_money(_command("IDEMP-LOOKUP", "20.00"))
    checked = await facade.fraud_check(
        FraudCheckCommand(
            transferred.output["transaction_id"],
            RequestContext("COR-F", "IDEMP-F", NOW),
        )
    )

    assert checked.output.transaction_id == transferred.output["transaction_id"]
    assert (
        harness.manager.current_state.transactions[transferred.output["transaction_id"]].risk_level
        is RiskLevel.HIGH
    )

    async with harness.manager.transaction() as unit:
        unit.state.idempotency_records.clear()
        unit.validate_invariants()
        await unit.commit()
    with pytest.raises(StateInvariantError):
        await facade.fraud_check(
            FraudCheckCommand(
                transferred.output["transaction_id"],
                RequestContext("COR-M", "IDEMP-M", NOW),
            )
        )

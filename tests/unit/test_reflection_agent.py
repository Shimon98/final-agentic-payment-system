"""Safe Hebrew recovery mapping tests for ReflectionAgent."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentic_payments.agents import AgentContext, ReflectionAgent
from agentic_payments.application import AgentResult, BusinessMemory, ReflectionAdvice
from agentic_payments.domain import (
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidAmountError,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestNotFoundError,
    PaymentRequestStatus,
    PolicyViolationError,
    SelfTransferError,
    StateInvariantError,
    UserNotFoundError,
    WalletNotFoundError,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _context(error: Exception) -> AgentContext:
    return AgentContext(
        "reflect",
        "COR-1",
        NOW,
        BusinessMemory(),
        payload={"error": error},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (InvalidAmountError(Decimal("-1.00"), "invalid"), "invalid_amount"),
        (
            InsufficientFundsError("USR-1", Decimal("20.00"), Decimal("30.00")),
            "insufficient_funds",
        ),
        (SelfTransferError("USR-1"), "self_transfer"),
        (UserNotFoundError("USR-1"), "user_not_found"),
        (WalletNotFoundError("USR-1"), "wallet_not_found"),
        (PaymentRequestNotFoundError("REQ-1"), "payment_request_not_found"),
        (
            PaymentRequestAlreadyResolvedError(
                "REQ-1",
                PaymentRequestStatus.APPROVED,
            ),
            "payment_request_already_resolved",
        ),
        (
            PolicyViolationError(
                "maximum",
                Decimal("50.00"),
                Decimal("60.00"),
            ),
            "policy_violation",
        ),
        (IdempotencyConflictError("IDEM-1"), "idempotency_conflict"),
        (
            StateInvariantError(
                "unsafe internal context",
                context={"phone_number": "0501234567"},
            ),
            "state_invariant_error",
        ),
    ],
)
async def test_every_mapped_domain_exception(error: Exception, code: str) -> None:
    result = await ReflectionAgent().reflect_on_error(error, _context(error))
    assert isinstance(result, AgentResult)
    assert isinstance(result.output, ReflectionAdvice)
    assert result.output.error_code == code
    assert result.confidence == 1.0
    assert result.output.user_message
    assert result.output.recovery_steps
    assert all(re.search(r"[\u0590-\u05FF]", step) for step in result.output.recovery_steps)


@pytest.mark.asyncio
async def test_insufficient_funds_and_policy_suggestions_are_exact() -> None:
    insufficient = InsufficientFundsError(
        "USR-1",
        Decimal("20.00"),
        Decimal("30.00"),
    )
    policy = PolicyViolationError(
        "maximum",
        Decimal("50.00"),
        Decimal("60.00"),
    )
    insufficient_advice = (
        await ReflectionAgent().reflect_on_error(insufficient, _context(insufficient))
    ).output
    policy_advice = (await ReflectionAgent().reflect_on_error(policy, _context(policy))).output

    assert insufficient_advice.suggested_parameters == {"amount": "20.00"}
    assert policy_advice.suggested_parameters == {"maximum_allowed": "50.00"}


@pytest.mark.asyncio
async def test_idempotency_conflict_never_suggests_same_key_retry() -> None:
    error = IdempotencyConflictError("IDEM-SECRET")
    advice = (await ReflectionAgent().reflect_on_error(error, _context(error))).output
    rendered = " ".join(advice.recovery_steps)
    assert "מפתח חדש" in rendered
    assert "IDEM-SECRET" not in rendered


class HTTPTimeoutError(Exception):
    pass


@pytest.mark.asyncio
async def test_unknown_exception_is_safe_snake_case_without_repr_or_traceback() -> None:
    secret = "secret exception payload 0501234567"
    error = HTTPTimeoutError(secret)
    result = await ReflectionAgent().reflect_on_error(error, _context(error))

    assert result.output.error_code == "http_timeout_error"
    assert result.confidence == 0.70
    rendered = str(result.output)
    assert secret not in rendered
    assert "Traceback" not in rendered
    assert repr(error) not in rendered


@pytest.mark.asyncio
async def test_state_invariant_context_is_not_exposed() -> None:
    error = StateInvariantError(
        "unsafe state",
        context={"phone_number": "0501234567", "complete_state": {"secret": True}},
    )
    advice = await ReflectionAgent().reflect_on_error(error, _context(error))
    rendered = str(advice.output)
    assert "0501234567" not in rendered
    assert "complete_state" not in rendered


@pytest.mark.asyncio
async def test_run_requires_exception_payload() -> None:
    error = UserNotFoundError("USR-1")
    assert isinstance(await ReflectionAgent().run(_context(error)), AgentResult)
    with pytest.raises(TypeError):
        await ReflectionAgent().run(AgentContext("reflect", "COR-1", NOW, BusinessMemory()))

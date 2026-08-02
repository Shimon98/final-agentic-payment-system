"""Hybrid routing success, fallback, cancellation, and context tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from agentic_payments.agents import AgentContext, HybridRouterAgent, RouterAgent
from agentic_payments.application import BusinessMemory, RouterDecision
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm import (
    LLMStructuredOutputError,
    LLMUnavailableError,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class Gateway:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    async def route(
        self,
        *,
        user_input: str,
        correlation_id: str,
        memory: BusinessMemory,
    ) -> RouterDecision:
        self.calls.append(
            {
                "user_input": user_input,
                "correlation_id": correlation_id,
                "memory": memory,
            }
        )
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_disabled_mode_calls_deterministic_router_directly() -> None:
    gateway = Gateway(AssertionError("must not call LLM"))
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=gateway,
        llm_enabled=False,
    )
    result = await hybrid.route("checkBalance user_id=USR-1")
    assert result.agent_name == "RouterAgent"
    assert result.output.intent is Intent.CHECK_BALANCE
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_successful_llm_route_has_exact_metadata_and_confidence() -> None:
    decision = RouterDecision(
        intent=Intent.CHECK_BALANCE,
        parameters={"user_id": "USR-1"},
        confidence=0.92,
    )
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=Gateway(decision),
        llm_enabled=True,
    )
    result = await hybrid.route("check my balance")
    assert result.agent_name == "HybridRouterAgent"
    assert result.output == decision
    assert result.confidence == 0.92
    assert result.metadata == {"route_source": "llm"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        LLMUnavailableError("Provider unavailable"),
        LLMStructuredOutputError("Invalid structured output"),
        ValueError("bad provider result"),
    ],
)
async def test_ordinary_llm_failure_uses_deterministic_fallback(
    failure: Exception,
) -> None:
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=Gateway(failure),
        llm_enabled=True,
    )
    result = await hybrid.route("checkBalance user_id=USR-1")
    assert result.output.intent is Intent.CHECK_BALANCE
    assert result.confidence == 1.0
    assert result.metadata == {
        "route_source": "deterministic_fallback",
        "llm_failure_type": type(failure).__name__,
    }
    assert "bad provider result" not in repr(result.metadata)


@pytest.mark.asyncio
async def test_invalid_llm_object_uses_deterministic_fallback() -> None:
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=Gateway({"intent": "checkBalance"}),
        llm_enabled=True,
    )
    result = await hybrid.route("checkBalance user_id=USR-1")
    assert result.metadata["llm_failure_type"] == "TypeError"


@pytest.mark.asyncio
async def test_cancelled_error_propagates() -> None:
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=Gateway(asyncio.CancelledError()),
        llm_enabled=True,
    )
    with pytest.raises(asyncio.CancelledError):
        await hybrid.route("checkBalance user_id=USR-1")


@pytest.mark.asyncio
async def test_run_passes_exact_context_values_without_state_access() -> None:
    decision = RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=0.1)
    gateway = Gateway(decision)
    memory = BusinessMemory(last_user_id="USR-1")
    context = AgentContext(
        user_input="help",
        correlation_id="CORR-1",
        requested_at=NOW,
        memory=memory,
    )
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=gateway,
        llm_enabled=True,
    )
    result = await hybrid.run(context)
    assert result.output == decision
    assert gateway.calls == [{"user_input": "help", "correlation_id": "CORR-1", "memory": memory}]


def test_hybrid_router_has_no_application_state_attribute() -> None:
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=Gateway(RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=0.0)),
        llm_enabled=True,
    )
    assert not any("state" in name.lower() for name in vars(hybrid))

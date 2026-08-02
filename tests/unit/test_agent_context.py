"""Tests for immutable agent context and the shared abstract contract."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from agentic_payments.agents import (
    AgentContext,
    BaseAgent,
    CriticAgent,
    ExplanationAgent,
    FallbackAgent,
    FraudDetectionAgent,
    PolicyAgent,
    ReflectionAgent,
    RouterAgent,
    SecurityAgent,
)
from agentic_payments.application import BusinessMemory, RouterDecision
from agentic_payments.domain import Intent, TransferPolicy

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _policy() -> TransferPolicy:
    return TransferPolicy(
        maximum_single_transfer=Decimal("100.00"),
        maximum_daily_transfer=Decimal("500.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=10,
        rapid_transfer_count=3,
    )


def test_valid_context_preserves_user_whitespace_and_copies_payload() -> None:
    payload = {"value": object()}
    context = AgentContext(
        user_input="  transfer request  ",
        correlation_id="COR-1",
        requested_at=NOW,
        memory=BusinessMemory(),
        payload=payload,
    )
    payload["late"] = "mutation"

    assert context.user_input == "  transfer request  "
    assert isinstance(context.payload, MappingProxyType)
    assert "late" not in context.payload
    with pytest.raises(TypeError):
        context.payload["new"] = "blocked"  # type: ignore[index]


@pytest.mark.parametrize("user_input", ["", " ", "\t\n"])
def test_blank_user_input_is_rejected(user_input: str) -> None:
    with pytest.raises(ValueError):
        AgentContext(user_input, "COR-1", NOW, BusinessMemory())


@pytest.mark.parametrize("correlation_id", ["", " ", " COR-1", "COR-1 "])
def test_correlation_id_must_be_non_empty_and_stripped(correlation_id: str) -> None:
    with pytest.raises(ValueError):
        AgentContext("input", correlation_id, NOW, BusinessMemory())


def test_requested_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        AgentContext("input", "COR-1", datetime(2026, 8, 2), BusinessMemory())


def test_memory_and_router_decision_types_are_validated() -> None:
    with pytest.raises(TypeError):
        AgentContext("input", "COR-1", NOW, "memory")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        AgentContext(
            "input",
            "COR-1",
            NOW,
            BusinessMemory(),
            router_decision="decision",  # type: ignore[arg-type]
        )

    decision = RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=0.0)
    assert (
        AgentContext(
            "input",
            "COR-1",
            NOW,
            BusinessMemory(),
            decision,
        ).router_decision
        is decision
    )


def test_payload_must_be_mapping() -> None:
    with pytest.raises(TypeError):
        AgentContext("input", "COR-1", NOW, BusinessMemory(), payload=[])  # type: ignore[arg-type]


def test_all_concrete_agents_are_base_agents_with_exact_names() -> None:
    policy = _policy()
    agents = [
        RouterAgent(),
        FraudDetectionAgent(transfer_policy=policy),
        SecurityAgent(),
        ExplanationAgent(),
        CriticAgent(),
        PolicyAgent(transfer_policy=policy),
        ReflectionAgent(),
        FallbackAgent(),
    ]
    assert all(isinstance(agent, BaseAgent) for agent in agents)
    assert [agent.name for agent in agents] == [
        "RouterAgent",
        "FraudDetectionAgent",
        "SecurityAgent",
        "ExplanationAgent",
        "CriticAgent",
        "PolicyAgent",
        "ReflectionAgent",
        "FallbackAgent",
    ]

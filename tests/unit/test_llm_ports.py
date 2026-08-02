"""Application LLM protocols remain structural and SDK-independent."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from agentic_payments.application import AgentResult, BusinessMemory, RouterDecision
from agentic_payments.application.llm_ports import (
    LLMRouterGateway,
    ReadOnlySpecialistGateway,
)
from agentic_payments.domain import Intent


class CompleteGateway:
    async def route(
        self,
        *,
        user_input: str,
        correlation_id: str,
        memory: BusinessMemory,
    ) -> RouterDecision:
        return RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=0.0)

    async def run_specialist(
        self,
        *,
        intent: Intent,
        user_input: str,
        correlation_id: str,
        requested_at: datetime,
        facts: Mapping[str, Any],
    ) -> AgentResult:
        return AgentResult("Specialist", {})


class IncompleteGateway:
    pass


def test_complete_gateway_satisfies_both_runtime_protocols() -> None:
    gateway = CompleteGateway()
    assert isinstance(gateway, LLMRouterGateway)
    assert isinstance(gateway, ReadOnlySpecialistGateway)


def test_incomplete_gateway_satisfies_neither_runtime_protocol() -> None:
    gateway = IncompleteGateway()
    assert not isinstance(gateway, LLMRouterGateway)
    assert not isinstance(gateway, ReadOnlySpecialistGateway)

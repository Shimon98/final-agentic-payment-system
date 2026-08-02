"""Provider-independent protocols for optional read-only language-model adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from agentic_payments.application.memory_service import BusinessMemory
from agentic_payments.application.results import AgentResult, RouterDecision
from agentic_payments.domain import Intent


@runtime_checkable
class LLMRouterGateway(Protocol):
    """Classify a request without executing it."""

    async def route(
        self,
        *,
        user_input: str,
        correlation_id: str,
        memory: BusinessMemory,
    ) -> RouterDecision:
        """Return one locally validated routing decision."""


@runtime_checkable
class ReadOnlySpecialistGateway(Protocol):
    """Run an approved specialist against caller-supplied immutable facts."""

    async def run_specialist(
        self,
        *,
        intent: Intent,
        user_input: str,
        correlation_id: str,
        requested_at: datetime,
        facts: Mapping[str, Any],
    ) -> AgentResult:
        """Return explanation or review text without mutating business state."""

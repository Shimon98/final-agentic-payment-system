"""Shared immutable context and abstract contract for deterministic agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from agentic_payments.application import AgentResult, BusinessMemory, RouterDecision


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Immutable request facts supplied to one read-only agent invocation."""

    user_input: str
    correlation_id: str
    requested_at: datetime
    memory: BusinessMemory
    router_decision: RouterDecision | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.user_input, str):
            raise TypeError("user_input must be a string")
        if not self.user_input.strip():
            raise ValueError("user_input must not be blank")
        if not isinstance(self.correlation_id, str):
            raise TypeError("correlation_id must be a string")
        if not self.correlation_id or self.correlation_id != self.correlation_id.strip():
            raise ValueError("correlation_id must be a non-empty stripped string")
        if (
            not isinstance(self.requested_at, datetime)
            or self.requested_at.tzinfo is None
            or self.requested_at.utcoffset() is None
        ):
            raise ValueError("requested_at must be timezone-aware")
        if not isinstance(self.memory, BusinessMemory):
            raise TypeError("memory must be BusinessMemory")
        if self.router_decision is not None and not isinstance(
            self.router_decision, RouterDecision
        ):
            raise TypeError("router_decision must be RouterDecision or None")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a Mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class BaseAgent(ABC):
    """Abstract read-only adapter contract shared by every deterministic agent."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable public agent identity."""

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Run the agent against one immutable context."""

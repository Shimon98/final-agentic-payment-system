"""Optional LLM router with deterministic classification fallback."""

from __future__ import annotations

import asyncio

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.agents.router_agent import RouterAgent
from agentic_payments.application.llm_ports import LLMRouterGateway
from agentic_payments.application.memory_service import BusinessMemory
from agentic_payments.application.results import AgentResult, RouterDecision


class HybridRouterAgent(BaseAgent):
    """Use a validated LLM route when enabled and deterministic routing otherwise."""

    def __init__(
        self,
        *,
        deterministic_router: RouterAgent,
        llm_gateway: LLMRouterGateway,
        llm_enabled: bool,
    ) -> None:
        if not isinstance(deterministic_router, RouterAgent):
            raise TypeError("deterministic_router must be RouterAgent")
        if not isinstance(llm_gateway, LLMRouterGateway):
            raise TypeError("llm_gateway must satisfy LLMRouterGateway")
        if not isinstance(llm_enabled, bool):
            raise TypeError("llm_enabled must be bool")
        self._deterministic_router = deterministic_router
        self._llm_gateway = llm_gateway
        self._llm_enabled = llm_enabled

    @property
    def name(self) -> str:
        """Return the exact stable hybrid router name."""

        return "HybridRouterAgent"

    @staticmethod
    def _validated(decision: object) -> RouterDecision:
        if not isinstance(decision, RouterDecision):
            raise TypeError("LLM route output must be RouterDecision")
        return RouterDecision.model_validate(decision.model_dump(mode="python"))

    async def _deterministic_fallback(
        self,
        user_input: str,
        *,
        failure: Exception,
    ) -> AgentResult:
        deterministic = await self._deterministic_router.route(user_input)
        decision = self._validated(deterministic.output)
        return AgentResult(
            agent_name=self.name,
            output=decision,
            confidence=deterministic.confidence,
            metadata={
                "route_source": "deterministic_fallback",
                "llm_failure_type": type(failure).__name__,
            },
        )

    async def _route_with_context(
        self,
        *,
        user_input: str,
        correlation_id: str,
        memory: BusinessMemory,
    ) -> AgentResult:
        if not self._llm_enabled:
            return await self._deterministic_router.route(user_input)
        try:
            decision = await self._llm_gateway.route(
                user_input=user_input,
                correlation_id=correlation_id,
                memory=memory,
            )
            validated = self._validated(decision)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return await self._deterministic_fallback(user_input, failure=error)
        return AgentResult(
            agent_name=self.name,
            output=validated,
            confidence=validated.confidence,
            metadata={"route_source": "llm"},
        )

    async def route(
        self,
        user_input: str,
    ) -> AgentResult:
        """Route through the structural Phase 7 router API.

        The richer ``run`` API supplies request memory and correlation. The structural
        ``route`` compatibility path uses an empty immutable memory snapshot and a
        stable non-generated correlation marker.
        """

        return await self._route_with_context(
            user_input=user_input,
            correlation_id="hybrid-router-route",
            memory=BusinessMemory(),
        )

    async def run(
        self,
        context: AgentContext,
    ) -> AgentResult:
        """Route using the exact immutable request context values."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        return await self._route_with_context(
            user_input=context.user_input,
            correlation_id=context.correlation_id,
            memory=context.memory,
        )

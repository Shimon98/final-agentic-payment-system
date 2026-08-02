"""Explicit production composition root for the complete payment application."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from agentic_payments.agents import (
    CriticAgent,
    ExplanationAgent,
    FallbackAgent,
    FraudDetectionAgent,
    HybridRouterAgent,
    PolicyAgent,
    ReflectionAgent,
    RouterAgent,
    SecurityAgent,
)
from agentic_payments.application import (
    ApplicationState as ApplicationState,
)
from agentic_payments.application import (
    BusinessMemory,
    MemoryService,
)
from agentic_payments.application.orchestrator import OrchestratorAgent
from agentic_payments.application.payment_domain_service import PaymentDomainService
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.infrastructure import (
    AuditOutboxDispatcher,
    JsonLinesAuditRepository,
    JsonStateRepository,
    OutboxFlushResult,
    StatePersistenceError,
    SystemClock,
    UuidIdGenerator,
)
from agentic_payments.infrastructure import (
    Settings as Settings,
)
from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    PaymentTransactionManager,
)
from agentic_payments.infrastructure.llm import AgentsModelFactory, OpenAIAgentsRuntime
from agentic_payments.tools import PaymentToolRegistry, ToolGuardrails


@dataclass(slots=True)
class ApplicationContainer:
    """Concrete application graph and safe lifecycle operations."""

    settings: Settings
    state_repository: JsonStateRepository
    audit_repository: JsonLinesAuditRepository
    lock_manager: AsyncResourceLockManager
    transaction_manager: PaymentTransactionManager
    memory_service: MemoryService
    outbox_dispatcher: AuditOutboxDispatcher
    orchestrator: OrchestratorAgent
    llm_runtime: OpenAIAgentsRuntime | None
    startup_outbox_result: OutboxFlushResult | None
    startup_warnings: tuple[str, ...]

    def snapshot(self) -> ApplicationState:
        """Return an independent clone without exposing manager internals."""

        return self.transaction_manager.current_state

    async def flush_outbox(self) -> OutboxFlushResult:
        """Delegate exactly one audit-outbox flush."""

        return await self.outbox_dispatcher.flush_pending()

    async def reset_state(self) -> OutboxFlushResult:
        """Atomically clear business state only after pending audit delivery."""

        flush_result = await self.outbox_dispatcher.flush_pending()
        if flush_result.pending_after > 0:
            raise StatePersistenceError("Cannot reset while audit events remain pending.")
        async with self.transaction_manager.transaction() as unit:
            state = unit.state
            state.users.clear()
            state.wallets.clear()
            state.transactions.clear()
            state.payment_requests.clear()
            state.idempotency_records.clear()
            state.pending_audit_events.clear()
            state.memory = BusinessMemory()
            unit.validate_invariants()
            await unit.commit()
        self.memory_service.reset()
        return flush_result


def _startup_warning(stage: str, error: Exception) -> str:
    return f"{stage} failed safely ({type(error).__name__})."


async def build_application(
    settings: Settings | None = None,
) -> ApplicationContainer:
    """Build the full explicit graph, initialize audit, and flush startup outbox."""

    if settings is not None and not isinstance(settings, Settings):
        raise TypeError("settings must be Settings or None")
    resolved_settings = settings or Settings()

    state_repository = JsonStateRepository(resolved_settings.state_file)
    audit_repository = JsonLinesAuditRepository(resolved_settings.audit_file)

    loaded_state = await state_repository.load()

    lock_manager = AsyncResourceLockManager()
    transaction_manager = PaymentTransactionManager(
        initial_state=loaded_state,
        state_repository=state_repository,
    )
    memory_service = MemoryService(loaded_state.memory)
    outbox_dispatcher = AuditOutboxDispatcher(
        transaction_manager=transaction_manager,
        audit_repository=audit_repository,
    )

    transfer_policy = resolved_settings.build_transfer_policy()
    clock = SystemClock()
    id_generator = UuidIdGenerator()
    payment_service = PaymentDomainService(
        transaction_manager=transaction_manager,
        lock_manager=lock_manager,
        transfer_policy=transfer_policy,
        clock=clock,
        id_generator=id_generator,
    )

    deterministic_router = RouterAgent(
        confidence_threshold=resolved_settings.router_confidence_threshold
    )
    fraud_agent = FraudDetectionAgent(transfer_policy=transfer_policy)
    security_agent = SecurityAgent()
    explanation_agent = ExplanationAgent()
    critic_agent = CriticAgent()
    policy_agent = PolicyAgent(transfer_policy=transfer_policy)
    reflection_agent = ReflectionAgent()
    fallback_agent = FallbackAgent()

    llm_runtime: OpenAIAgentsRuntime | None = None
    selected_router: RouterAgent | HybridRouterAgent
    if not resolved_settings.enable_llm_router or resolved_settings.llm_provider == "rule_based":
        selected_router = deterministic_router
    else:
        model_factory = AgentsModelFactory(settings=resolved_settings)
        llm_runtime = OpenAIAgentsRuntime(model_factory=model_factory)
        # Phase 7's route(user_input) port has no real correlation or memory parameters;
        # HybridRouterAgent therefore uses its approved compatibility marker and empty memory.
        selected_router = HybridRouterAgent(
            deterministic_router=deterministic_router,
            llm_gateway=llm_runtime,
            llm_enabled=True,
        )

    payment_facade = PaymentFacade(
        payment_service=payment_service,
        transaction_manager=transaction_manager,
        fraud_agent=fraud_agent,
        security_agent=security_agent,
        explanation_agent=explanation_agent,
        policy_agent=policy_agent,
    )
    tool_registry = PaymentToolRegistry(payment_facade=payment_facade)
    tool_guardrails = ToolGuardrails(
        confidence_threshold=resolved_settings.router_confidence_threshold
    )
    orchestrator = OrchestratorAgent(
        router_agent=selected_router,
        tool_registry=tool_registry,
        tool_guardrails=tool_guardrails,
        critic_agent=critic_agent,
        reflection_agent=reflection_agent,
        fallback_agent=fallback_agent,
        memory_service=memory_service,
        transaction_manager=transaction_manager,
        # The Phase 7 structural port returns a protocol view of this concrete result.
        audit_outbox_dispatcher=cast(Any, outbox_dispatcher),
        clock=clock,
        id_generator=id_generator,
        confidence_threshold=resolved_settings.router_confidence_threshold,
    )

    startup_warnings: list[str] = []
    try:
        await audit_repository.list_all()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        startup_warnings.append(_startup_warning("Audit initialization", error))

    startup_outbox_result: OutboxFlushResult | None = None
    try:
        startup_outbox_result = await outbox_dispatcher.flush_pending()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        if not startup_warnings:
            startup_warnings.append(_startup_warning("Startup outbox flush", error))

    return ApplicationContainer(
        settings=resolved_settings,
        state_repository=state_repository,
        audit_repository=audit_repository,
        lock_manager=lock_manager,
        transaction_manager=transaction_manager,
        memory_service=memory_service,
        outbox_dispatcher=outbox_dispatcher,
        orchestrator=orchestrator,
        llm_runtime=llm_runtime,
        startup_outbox_result=startup_outbox_result,
        startup_warnings=tuple(startup_warnings),
    )

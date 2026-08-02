"""Deterministic orchestration of routing, tools, memory, and audit delivery."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from agentic_payments.agents.base import AgentContext
from agentic_payments.application.commands import (
    ApprovePaymentCommand,
    CheckBalanceCommand,
    CreateUserCommand,
    ExplainLastActionCommand,
    FraudCheckCommand,
    RejectPaymentCommand,
    RequestContext,
    RequestPaymentCommand,
    SecurityReviewCommand,
    ShowTransactionsCommand,
    TransferMoneyCommand,
)
from agentic_payments.application.memory_service import MemoryService
from agentic_payments.application.ports import Clock, IdGenerator
from agentic_payments.application.results import (
    AgentResult,
    CriticReview,
    RouterDecision,
)
from agentic_payments.domain import Intent, StateInvariantError
from agentic_payments.infrastructure.concurrency.transaction_manager import (
    PaymentTransactionManager,
)
from agentic_payments.tools import PaymentToolRegistry, ToolGuardrails

_DECIMAL_PATTERN = re.compile(r"[+-]?(?:0|[1-9]\d*)(?:\.\d{1,2})?")
_MUTATING_INTENTS = {
    Intent.CREATE_USER,
    Intent.TRANSFER_MONEY,
    Intent.REQUEST_PAYMENT,
    Intent.APPROVE_PAYMENT,
    Intent.REJECT_PAYMENT,
}


class _RouterAgentPort(Protocol):
    async def route(self, user_input: str) -> AgentResult: ...


class _CriticAgentPort(Protocol):
    async def review(self, result: AgentResult, expected_intent: Intent) -> AgentResult: ...


class _ReflectionAgentPort(Protocol):
    async def reflect_on_error(
        self,
        error: Exception,
        context: AgentContext,
    ) -> AgentResult: ...


class _FallbackAgentPort(Protocol):
    async def handle_unknown(self, user_input: str) -> AgentResult: ...

    async def handle_low_confidence(self, decision: RouterDecision) -> AgentResult: ...

    async def request_missing_parameters(self, decision: RouterDecision) -> AgentResult: ...


class _OutboxFailurePort(Protocol):
    event_id: str
    error_type: str
    message: str


class _OutboxFlushResultPort(Protocol):
    attempted: int
    delivered: int
    already_delivered: int
    removed: int
    failures: tuple[_OutboxFailurePort, ...]
    pending_after: int


class _OutboxDispatcherPort(Protocol):
    async def flush_pending(self) -> _OutboxFlushResultPort: ...


def _checked_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty stripped string")
    return value


def _checked_time(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _strict_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str) and _DECIMAL_PATTERN.fullmatch(value) is not None:
        try:
            result = Decimal(value)
        except InvalidOperation as error:
            raise ValueError(f"{field_name} must be a strict decimal") from error
    else:
        raise ValueError(f"{field_name} must be a strict decimal")
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _safe_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    safe: dict[str, Any] = {}
    for key, nested in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(nested, Mapping):
            safe[key] = _safe_mapping(nested)
        elif isinstance(nested, (list, tuple)):
            safe[key] = [
                _safe_mapping(item) if isinstance(item, Mapping) else item
                for item in nested
                if item is None or isinstance(item, (str, int, float, bool, Mapping))
            ]
        elif nested is None or isinstance(nested, (str, int, float, bool)):
            safe[key] = nested
    return safe


class OrchestratorAgent:
    """Coordinate exactly one deterministic primary tool per request."""

    def __init__(
        self,
        *,
        router_agent: _RouterAgentPort,
        tool_registry: PaymentToolRegistry,
        tool_guardrails: ToolGuardrails,
        critic_agent: _CriticAgentPort,
        reflection_agent: _ReflectionAgentPort,
        fallback_agent: _FallbackAgentPort,
        memory_service: MemoryService,
        transaction_manager: PaymentTransactionManager,
        audit_outbox_dispatcher: _OutboxDispatcherPort,
        clock: Clock,
        id_generator: IdGenerator,
        confidence_threshold: float = 0.80,
    ) -> None:
        if not isinstance(tool_registry, PaymentToolRegistry):
            raise TypeError("tool_registry must be PaymentToolRegistry")
        if not isinstance(tool_guardrails, ToolGuardrails):
            raise TypeError("tool_guardrails must be ToolGuardrails")
        if not isinstance(memory_service, MemoryService):
            raise TypeError("memory_service must be MemoryService")
        if not isinstance(transaction_manager, PaymentTransactionManager):
            raise TypeError("transaction_manager must be PaymentTransactionManager")
        if isinstance(confidence_threshold, bool) or not isinstance(
            confidence_threshold, (int, float)
        ):
            raise TypeError("confidence_threshold must be numeric and not bool")
        threshold = float(confidence_threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self._router_agent = router_agent
        self._tool_registry = tool_registry
        self._tool_guardrails = tool_guardrails
        self._critic_agent = critic_agent
        self._reflection_agent = reflection_agent
        self._fallback_agent = fallback_agent
        self._memory_service = memory_service
        self._transaction_manager = transaction_manager
        self._audit_outbox_dispatcher = audit_outbox_dispatcher
        self._clock = clock
        self._id_generator = id_generator
        self._confidence_threshold = threshold

    async def handle(
        self,
        user_input: str,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        requested_at: datetime | None = None,
    ) -> AgentResult:
        """Execute one complete deterministic application request lifecycle."""

        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        if not user_input.strip():
            raise ValueError("user_input must not be blank")
        correlation = (
            _checked_text(correlation_id, "correlation_id")
            if correlation_id is not None
            else _checked_text(
                self._id_generator.new_correlation_id(),
                "generated correlation_id",
            )
        )
        occurred_at = (
            _checked_time(requested_at, "requested_at")
            if requested_at is not None
            else _checked_time(self._clock.now(), "clock time")
        )
        idempotency = (
            _checked_text(idempotency_key, "idempotency_key")
            if idempotency_key is not None
            else f"IDEMP-{correlation}"
        )
        decision: RouterDecision | None = None
        primary_mutation_committed = False
        committed_tool_result: AgentResult | None = None
        committed_tool_name: str | None = None
        try:
            route_result = await self._router_agent.route(user_input)
            if not isinstance(route_result, AgentResult) or not isinstance(
                route_result.output, RouterDecision
            ):
                raise TypeError("router output must be RouterDecision")
            decision = route_result.output
            self._memory_service.remember_route(
                decision,
                user_input,
                occurred_at=occurred_at,
            )

            if decision.intent is Intent.UNKNOWN:
                fallback = await self._fallback_agent.handle_unknown(user_input)
                return await self._finish_fallback(
                    fallback,
                    decision=decision,
                    correlation_id=correlation,
                    idempotency_key=idempotency,
                    occurred_at=occurred_at,
                )
            if decision.requires_clarification:
                fallback = await self._fallback_agent.request_missing_parameters(decision)
                return await self._finish_fallback(
                    fallback,
                    decision=decision,
                    correlation_id=correlation,
                    idempotency_key=idempotency,
                    occurred_at=occurred_at,
                )
            if decision.confidence < self._confidence_threshold:
                fallback = await self._fallback_agent.handle_low_confidence(decision)
                return await self._finish_fallback(
                    fallback,
                    decision=decision,
                    correlation_id=correlation,
                    idempotency_key=idempotency,
                    occurred_at=occurred_at,
                )

            context = RequestContext(
                correlation_id=correlation,
                idempotency_key=idempotency,
                requested_at=occurred_at,
                actor="user",
            )
            command = self._build_command(decision, context)
            self._tool_guardrails.validate_before_execution(
                decision=decision,
                command=command,
            )
            tool_name = self._tool_registry.tool_name_for_intent(decision.intent)
            tool_result = await self._tool_registry.execute(
                intent=decision.intent,
                command=command,
                memory=self._memory_service.snapshot(),
            )
            if not isinstance(tool_result, AgentResult):
                raise TypeError("tool result must be AgentResult")
            if decision.intent in _MUTATING_INTENTS:
                primary_mutation_committed = True
                committed_tool_result = tool_result
                committed_tool_name = tool_name
                return await self._finish_committed_tool(
                    decision=decision,
                    tool_result=tool_result,
                    tool_name=tool_name,
                    correlation_id=correlation,
                    idempotency_key=idempotency,
                    occurred_at=occurred_at,
                )
            self._tool_guardrails.validate_after_execution(
                intent=decision.intent,
                result=tool_result,
            )
            critic_result = await self._critic_agent.review(
                tool_result,
                expected_intent=decision.intent,
            )
            if not isinstance(critic_result, AgentResult) or not isinstance(
                critic_result.output, CriticReview
            ):
                raise TypeError("critic output must be CriticReview")
            critic_review = critic_result.output
            if critic_review.requires_fallback or not critic_review.approved:
                fallback = await self._fallback_agent.handle_unknown(
                    "Generated result failed deterministic quality review"
                )
                return await self._finish_fallback(
                    fallback,
                    decision=decision,
                    correlation_id=correlation,
                    idempotency_key=idempotency,
                    occurred_at=occurred_at,
                    extra_metadata={
                        "critic_review": critic_review.model_dump(mode="json"),
                        "tool_name": tool_name,
                        "fallback_trigger": "critic_rejection",
                    },
                )

            self._remember_entities(
                decision.intent,
                tool_result,
                occurred_at=occurred_at,
            )
            self._memory_service.remember_result(
                tool_result,
                occurred_at=occurred_at,
            )
            await self._persist_memory()
            outbox = await self._flush_outbox()
            metadata: dict[str, Any] = {
                "intent": decision.intent.value,
                "route_confidence": decision.confidence,
                "correlation_id": correlation,
                "idempotency_key": idempotency,
                "tool_name": tool_name,
                "tool_agent_name": tool_result.agent_name,
                "critic_review": critic_review.model_dump(mode="json"),
                "memory_persisted": True,
                "outbox": outbox,
                "post_processing": _safe_mapping(tool_result.metadata),
            }
            return AgentResult(
                "OrchestratorAgent",
                tool_result.output,
                tool_result.confidence,
                metadata,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if (
                primary_mutation_committed
                and decision is not None
                and committed_tool_result is not None
                and committed_tool_name is not None
            ):
                return await self._finish_committed_failure(
                    decision=decision,
                    tool_result=committed_tool_result,
                    tool_name=committed_tool_name,
                    correlation_id=correlation,
                    idempotency_key=idempotency,
                    occurred_at=occurred_at,
                    stage="post_commit_finalization",
                    error=error,
                )
            return await self._reflect_failure(
                error,
                user_input=user_input,
                decision=decision,
                correlation_id=correlation,
                idempotency_key=idempotency,
                occurred_at=occurred_at,
            )

    @staticmethod
    def _parameters(
        decision: RouterDecision,
        expected: frozenset[str],
    ) -> Mapping[str, Any]:
        if frozenset(decision.parameters) != expected:
            raise ValueError("decision parameters do not match the intent contract")
        return decision.parameters

    def _build_command(
        self,
        decision: RouterDecision,
        context: RequestContext,
    ) -> object:
        intent = decision.intent
        if intent is Intent.CREATE_USER:
            values = self._parameters(
                decision,
                frozenset({"name", "phone_number", "initial_balance"}),
            )
            return CreateUserCommand(
                name=values["name"],
                phone_number=values["phone_number"],
                initial_balance=_strict_decimal(values["initial_balance"], "initial_balance"),
                context=context,
            )
        if intent is Intent.CHECK_BALANCE:
            values = self._parameters(decision, frozenset({"user_id"}))
            return CheckBalanceCommand(user_id=values["user_id"], context=context)
        if intent is Intent.TRANSFER_MONEY:
            values = self._parameters(
                decision,
                frozenset({"sender_id", "receiver_id", "amount"}),
            )
            return TransferMoneyCommand(
                sender_id=values["sender_id"],
                receiver_id=values["receiver_id"],
                amount=_strict_decimal(values["amount"], "amount"),
                context=context,
            )
        if intent is Intent.REQUEST_PAYMENT:
            values = self._parameters(
                decision,
                frozenset({"requester_id", "payer_id", "amount"}),
            )
            return RequestPaymentCommand(
                requester_id=values["requester_id"],
                payer_id=values["payer_id"],
                amount=_strict_decimal(values["amount"], "amount"),
                context=context,
            )
        if intent is Intent.APPROVE_PAYMENT:
            values = self._parameters(decision, frozenset({"request_id"}))
            return ApprovePaymentCommand(request_id=values["request_id"], context=context)
        if intent is Intent.REJECT_PAYMENT:
            values = self._parameters(decision, frozenset({"request_id"}))
            return RejectPaymentCommand(request_id=values["request_id"], context=context)
        if intent is Intent.SHOW_TRANSACTIONS:
            values = self._parameters(decision, frozenset({"user_id"}))
            return ShowTransactionsCommand(user_id=values["user_id"], context=context)
        if intent is Intent.FRAUD_CHECK:
            values = self._parameters(decision, frozenset({"transaction_id"}))
            return FraudCheckCommand(
                transaction_id=values["transaction_id"],
                context=context,
            )
        if intent is Intent.SECURITY_REVIEW:
            values = self._parameters(decision, frozenset({"transaction_id"}))
            return SecurityReviewCommand(
                transaction_id=values["transaction_id"],
                context=context,
            )
        if intent is Intent.EXPLAIN_LAST_ACTION:
            self._parameters(decision, frozenset())
            return ExplainLastActionCommand(context=context)
        raise ValueError("UNKNOWN intent cannot construct a command")

    def _remember_entities(
        self,
        intent: Intent,
        result: AgentResult,
        *,
        occurred_at: datetime,
    ) -> None:
        if not isinstance(result.output, Mapping):
            return
        state = self._transaction_manager.current_state
        if intent is Intent.CREATE_USER:
            user_id = result.output.get("user_id")
            user = state.users.get(user_id) if isinstance(user_id, str) else None
            if user is None:
                raise StateInvariantError(
                    "Committed user is missing",
                    context={"user_id": user_id if isinstance(user_id, str) else "missing"},
                )
            self._memory_service.remember_user(user, occurred_at=occurred_at)
        elif intent is Intent.TRANSFER_MONEY:
            transaction_id = result.output.get("transaction_id")
            transaction = (
                state.transactions.get(transaction_id) if isinstance(transaction_id, str) else None
            )
            if transaction is None:
                raise StateInvariantError(
                    "Committed transaction is missing",
                    context={
                        "transaction_id": (
                            transaction_id if isinstance(transaction_id, str) else "missing"
                        )
                    },
                )
            self._memory_service.remember_transaction(
                transaction,
                occurred_at=occurred_at,
            )
        elif intent in {
            Intent.REQUEST_PAYMENT,
            Intent.APPROVE_PAYMENT,
            Intent.REJECT_PAYMENT,
        }:
            request_id = result.output.get("payment_request_id")
            request = (
                state.payment_requests.get(request_id) if isinstance(request_id, str) else None
            )
            if request is None:
                raise StateInvariantError(
                    "Committed payment request is missing",
                    context={
                        "request_id": request_id if isinstance(request_id, str) else "missing"
                    },
                )
            self._memory_service.remember_payment_request(
                request,
                occurred_at=occurred_at,
            )
            if intent is Intent.APPROVE_PAYMENT:
                transaction_id = result.output.get("transaction_id")
                transaction = (
                    state.transactions.get(transaction_id)
                    if isinstance(transaction_id, str)
                    else None
                )
                if transaction is None:
                    raise StateInvariantError(
                        "Committed approval transaction is missing",
                        context={
                            "transaction_id": (
                                transaction_id if isinstance(transaction_id, str) else "missing"
                            )
                        },
                    )
                self._memory_service.remember_transaction(
                    transaction,
                    occurred_at=occurred_at,
                )

    @staticmethod
    def _post_commit_warning(
        *,
        stage: str,
        error: Exception,
        delivery_status: str = "committed_with_post_commit_warning",
        message: str = "Committed result post-processing failed",
    ) -> dict[str, Any]:
        return {
            "primary_mutation_committed": True,
            "delivery_status": delivery_status,
            "post_commit_warning_stage": stage,
            "post_commit_warning_type": type(error).__name__,
            "post_commit_warning_message": message,
        }

    async def _remember_committed_result(
        self,
        *,
        intent: Intent,
        tool_result: AgentResult,
        occurred_at: datetime,
    ) -> tuple[bool, str | None, str | None]:
        error_type: str | None = None
        error_stage: str | None = None
        try:
            self._remember_entities(intent, tool_result, occurred_at=occurred_at)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            error_type = type(error).__name__
            error_stage = "memory_entity_update"
        try:
            self._memory_service.remember_result(
                tool_result,
                occurred_at=occurred_at,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if error_type is None:
                error_type = type(error).__name__
                error_stage = "remember_result"
        try:
            await self._persist_memory()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if error_type is None:
                error_type = type(error).__name__
                error_stage = "memory_persistence"
        return error_type is None, error_type, error_stage

    async def _finish_committed_tool(
        self,
        *,
        decision: RouterDecision,
        tool_result: AgentResult,
        tool_name: str,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> AgentResult:
        warning: dict[str, Any] | None = None
        critic_review: CriticReview | None = None
        try:
            self._tool_guardrails.validate_after_execution(
                intent=decision.intent,
                result=tool_result,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            warning = self._post_commit_warning(
                stage="output_guardrail",
                error=error,
                delivery_status="committed_with_validation_warning",
                message="Committed result validation failed",
            )
        else:
            try:
                critic_result = await self._critic_agent.review(
                    tool_result,
                    expected_intent=decision.intent,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                warning = self._post_commit_warning(
                    stage="critic",
                    error=error,
                    message="Committed result quality review failed",
                )
            else:
                try:
                    if not isinstance(critic_result, AgentResult) or not isinstance(
                        critic_result.output, CriticReview
                    ):
                        raise TypeError("critic output must be CriticReview")
                    critic_review = critic_result.output
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    warning = self._post_commit_warning(
                        stage="critic_output_validation",
                        error=error,
                        message="Committed quality-review validation failed",
                    )
                else:
                    if critic_review.requires_fallback or not critic_review.approved:
                        warning = {
                            "primary_mutation_committed": True,
                            "delivery_status": "committed_with_quality_warning",
                            "critic_review": critic_review.model_dump(mode="json"),
                            "fallback_suppressed_reason": ("primary_mutation_already_committed"),
                        }

        (
            memory_persisted,
            memory_error_type,
            memory_error_stage,
        ) = await self._remember_committed_result(
            intent=decision.intent,
            tool_result=tool_result,
            occurred_at=occurred_at,
        )
        outbox = await self._flush_outbox()
        metadata: dict[str, Any] = {
            "intent": decision.intent.value,
            "route_confidence": decision.confidence,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "tool_agent_name": tool_result.agent_name,
            "memory_persisted": memory_persisted,
            "outbox": outbox,
            "post_processing": _safe_mapping(tool_result.metadata),
        }
        if critic_review is not None and warning is None:
            metadata["critic_review"] = critic_review.model_dump(mode="json")
        if warning is not None:
            metadata.update(warning)
        if memory_error_type is not None:
            metadata["memory_error_type"] = memory_error_type
            metadata["memory_warning_stage"] = memory_error_stage
            if warning is None:
                metadata.update(
                    {
                        "primary_mutation_committed": True,
                        "delivery_status": "committed_with_post_commit_warning",
                        "post_commit_warning_stage": memory_error_stage,
                        "post_commit_warning_type": memory_error_type,
                        "post_commit_warning_message": ("Committed result memory handling failed"),
                    }
                )
        if (
            not outbox.get("outbox_flush_succeeded", False)
            and "error_type" in outbox
            and warning is None
            and memory_error_type is None
        ):
            metadata.update(
                {
                    "primary_mutation_committed": True,
                    "delivery_status": "committed_with_post_commit_warning",
                    "post_commit_warning_stage": "outbox_flush",
                    "post_commit_warning_type": outbox["error_type"],
                    "post_commit_warning_message": "Committed result outbox flush failed",
                }
            )
        return AgentResult(
            "OrchestratorAgent",
            tool_result.output,
            (min(tool_result.confidence, 0.85) if warning is not None else tool_result.confidence),
            metadata,
        )

    async def _finish_committed_failure(
        self,
        *,
        decision: RouterDecision,
        tool_result: AgentResult,
        tool_name: str,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime,
        stage: str,
        error: Exception,
    ) -> AgentResult:
        memory_persisted, memory_error_type, _ = await self._remember_committed_result(
            intent=decision.intent,
            tool_result=tool_result,
            occurred_at=occurred_at,
        )
        outbox = await self._flush_outbox()
        metadata: dict[str, Any] = {
            "intent": decision.intent.value,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "tool_name": tool_name,
            "tool_agent_name": tool_result.agent_name,
            "memory_persisted": memory_persisted,
            "outbox": outbox,
            **self._post_commit_warning(stage=stage, error=error),
        }
        if memory_error_type is not None:
            metadata["memory_error_type"] = memory_error_type
        return AgentResult(
            "OrchestratorAgent",
            tool_result.output,
            min(tool_result.confidence, 0.85),
            metadata,
        )

    async def _persist_memory(self) -> None:
        snapshot = self._memory_service.snapshot()
        async with self._transaction_manager.transaction() as unit:
            unit.state.memory = snapshot
            unit.validate_invariants()
            await unit.commit()

    async def _flush_outbox(self) -> dict[str, Any]:
        try:
            result = await self._audit_outbox_dispatcher.flush_pending()
            safe_failures = [
                {
                    "event_id": failure.event_id,
                    "error_type": failure.error_type,
                    "message": failure.message,
                }
                for failure in result.failures
            ]
            return {
                "outbox_flush_succeeded": not safe_failures,
                "attempted": result.attempted,
                "delivered": result.delivered,
                "already_delivered": result.already_delivered,
                "removed": result.removed,
                "failures": safe_failures,
                "pending_after": result.pending_after,
            }
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return {
                "outbox_flush_succeeded": False,
                "error_type": type(error).__name__,
                "message": "Audit outbox flush failed",
            }

    async def _finish_fallback(
        self,
        result: AgentResult,
        *,
        decision: RouterDecision,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        if not isinstance(result, AgentResult):
            raise TypeError("fallback result must be AgentResult")
        self._memory_service.remember_result(result, occurred_at=occurred_at)
        await self._persist_memory()
        outbox = await self._flush_outbox()
        metadata: dict[str, Any] = {
            "intent": decision.intent.value,
            "route_confidence": decision.confidence,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "memory_persisted": True,
            "outbox": outbox,
        }
        if extra_metadata is not None:
            metadata.update(_safe_mapping(extra_metadata) or {})
        return AgentResult(
            result.agent_name,
            result.output,
            result.confidence,
            metadata,
        )

    async def _reflect_failure(
        self,
        error: Exception,
        *,
        user_input: str,
        decision: RouterDecision | None,
        correlation_id: str,
        idempotency_key: str,
        occurred_at: datetime,
    ) -> AgentResult:
        context = AgentContext(
            user_input=user_input,
            correlation_id=correlation_id,
            requested_at=occurred_at,
            memory=self._memory_service.snapshot(),
            router_decision=decision,
            payload={"error": error},
        )
        reflected = await self._reflection_agent.reflect_on_error(error, context)
        if not isinstance(reflected, AgentResult):
            raise TypeError("reflection result must be AgentResult")
        self._memory_service.remember_result(reflected, occurred_at=occurred_at)
        memory_persisted = True
        memory_error_type: str | None = None
        try:
            await self._persist_memory()
        except asyncio.CancelledError:
            raise
        except Exception as persistence_error:
            memory_persisted = False
            memory_error_type = type(persistence_error).__name__
        outbox = await self._flush_outbox()
        metadata: dict[str, Any] = {
            "intent": decision.intent.value if decision is not None else Intent.UNKNOWN.value,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "error_handled": True,
            "memory_persisted": memory_persisted,
            "outbox": outbox,
        }
        if memory_error_type is not None:
            metadata["memory_persistence_error_type"] = memory_error_type
        return AgentResult(
            reflected.agent_name,
            reflected.output,
            reflected.confidence,
            metadata,
        )

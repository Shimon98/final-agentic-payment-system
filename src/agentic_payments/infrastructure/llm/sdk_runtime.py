"""Public OpenAI Agents SDK runtime behind provider-independent application ports."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from agents import (
    HandoffOutputItem,
    InputGuardrailTripwireTriggered,
    Model,
    ModelBehaviorError,
    OutputGuardrailTripwireTriggered,
    RunConfig,
    Runner,
    ToolCallItem,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
)
from pydantic import ValidationError

from agentic_payments.application import AgentResult, BusinessMemory, RouterDecision
from agentic_payments.application.llm_ports import (
    LLMRouterGateway,
    ReadOnlySpecialistGateway,
)
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm.context import SDKReadOnlyContext
from agentic_payments.infrastructure.llm.exceptions import (
    LLMGuardrailError,
    LLMHandoffError,
    LLMStructuredOutputError,
    LLMUnavailableError,
)
from agentic_payments.infrastructure.llm.provider_factory import AgentsModelFactory
from agentic_payments.infrastructure.llm.schemas import (
    ReadOnlySpecialistOutput,
    SDKRunMetadata,
    SpecialistType,
)
from agentic_payments.infrastructure.llm.sdk_agents import (
    _router_agent,
    _specialist_agents,
    _SpecialistAgents,
)
from agentic_payments.infrastructure.llm.sdk_guardrails import (
    _specialist_output_rejection_reason,
)

MAX_TURNS = 4
RUN_TIMEOUT_SECONDS = 30.0

_ALLOWED_SPECIALISTS = {
    Intent.FRAUD_CHECK: ("Fraud Review Specialist", SpecialistType.FRAUD),
    Intent.SECURITY_REVIEW: ("Security Review Specialist", SpecialistType.SECURITY),
    Intent.EXPLAIN_LAST_ACTION: (
        "Payment Explanation Specialist",
        SpecialistType.EXPLANATION,
    ),
}
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){7,15}(?!\d)")
_KNOWN_OUTPUT_GUARDRAIL_REASONS = frozenset(
    {
        "invalid_output_type",
        "wrong_specialist_identity",
        "payment_execution_claim",
        "invented_identifier",
        "invented_amount",
    }
)
_UNKNOWN_OUTPUT_GUARDRAIL_REASON = "unknown_output_guardrail_reason"


def _redact_complete_phone(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        return "[redacted-phone]" if 7 <= len(digits) <= 15 else match.group()

    return _PHONE.sub(replace, text)


def _safe_output_guardrail_reason(error: OutputGuardrailTripwireTriggered) -> str:
    try:
        output_info = error.guardrail_result.output.output_info
    except AttributeError:
        return _UNKNOWN_OUTPUT_GUARDRAIL_REASON
    if not isinstance(output_info, Mapping):
        return _UNKNOWN_OUTPUT_GUARDRAIL_REASON
    reason = output_info.get("reason")
    if not isinstance(reason, str) or reason not in _KNOWN_OUTPUT_GUARDRAIL_REASONS:
        return _UNKNOWN_OUTPUT_GUARDRAIL_REASON
    return reason


class OpenAIAgentsRuntime(
    LLMRouterGateway,
    ReadOnlySpecialistGateway,
):
    """Execute structured, read-only SDK runs with strict local validation."""

    def __init__(
        self,
        *,
        model_factory: AgentsModelFactory,
    ) -> None:
        if not isinstance(model_factory, AgentsModelFactory):
            raise TypeError("model_factory must be AgentsModelFactory")
        self._model_factory = model_factory
        self._router_definition: Any | None = None
        self._specialist_definitions: _SpecialistAgents | None = None

    def _require_enabled(self) -> None:
        if not self._model_factory.is_enabled():
            raise LLMUnavailableError(
                "Language-model runtime is disabled",
                context={"provider": self._model_factory.provider_name()},
            )

    def _router(self) -> Any:
        self._require_enabled()
        if self._router_definition is None:
            self._router_definition = _router_agent(cast(Model, self._model_factory.create_model()))
        return self._router_definition

    def _specialists(self) -> _SpecialistAgents:
        self._require_enabled()
        if self._specialist_definitions is None:
            self._specialist_definitions = _specialist_agents(
                cast(Model, self._model_factory.create_model())
            )
        return self._specialist_definitions

    def _run_config(self, workflow_name: str) -> RunConfig:
        tracing_enabled = self._model_factory._tracing_enabled()
        return RunConfig(
            tracing_disabled=not tracing_enabled,
            trace_include_sensitive_data=False,
            workflow_name=workflow_name,
            trace_metadata={"provider": self._model_factory.provider_name()},
        )

    async def _run_sdk(
        self,
        *,
        agent: Any,
        input_value: str,
        context: SDKReadOnlyContext | None,
        workflow_name: str,
    ) -> Any:
        try:
            return await asyncio.wait_for(
                Runner.run(
                    agent,
                    input_value,
                    context=context,
                    max_turns=MAX_TURNS,
                    run_config=self._run_config(workflow_name),
                ),
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as error:
            raise LLMUnavailableError(
                "Language-model run timed out",
                context={"provider": self._model_factory.provider_name()},
            ) from error
        except OutputGuardrailTripwireTriggered as error:
            raise LLMGuardrailError(
                "Language-model guardrail rejected the run",
                context={
                    "provider": self._model_factory.provider_name(),
                    "guardrail_reason": _safe_output_guardrail_reason(error),
                },
            ) from error
        except (
            InputGuardrailTripwireTriggered,
            ToolInputGuardrailTripwireTriggered,
            ToolOutputGuardrailTripwireTriggered,
        ) as error:
            raise LLMGuardrailError(
                "Language-model guardrail rejected the run",
                context={"provider": self._model_factory.provider_name()},
            ) from error
        except ModelBehaviorError as error:
            raise LLMStructuredOutputError(
                "Language-model provider did not return the required structured output",
                context={"provider": self._model_factory.provider_name()},
            ) from error
        except Exception as error:
            raise LLMUnavailableError(
                "Language-model provider run failed",
                context={
                    "provider": self._model_factory.provider_name(),
                    "failure_type": type(error).__name__,
                },
            ) from error

    @staticmethod
    def _memory_summary(memory: BusinessMemory) -> str:
        summary = {
            "last_intent": memory.last_intent.value if memory.last_intent else None,
            "last_user_id": memory.last_user_id,
            "last_transaction_id": memory.last_transaction_id,
            "last_payment_request_id": memory.last_payment_request_id,
        }
        return json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    async def route(
        self,
        *,
        user_input: str,
        correlation_id: str,
        memory: BusinessMemory,
    ) -> RouterDecision:
        """Return a locally revalidated structured route."""

        if not isinstance(user_input, str) or not user_input.strip():
            raise LLMStructuredOutputError("Router input must be a non-blank string")
        if (
            not isinstance(correlation_id, str)
            or not correlation_id
            or correlation_id != correlation_id.strip()
        ):
            raise LLMStructuredOutputError("Router correlation ID is invalid")
        if not isinstance(memory, BusinessMemory):
            raise LLMStructuredOutputError("Router memory must be BusinessMemory")
        prompt = (
            f"Request:\n{user_input.strip()}\n\n"
            f"Sanitized memory summary:\n{self._memory_summary(memory)}"
        )
        result = await self._run_sdk(
            agent=self._router(),
            input_value=prompt,
            context=None,
            workflow_name="Payment intent routing",
        )
        try:
            output = result.final_output
            if not isinstance(output, RouterDecision):
                raise TypeError("final output is not RouterDecision")
            return RouterDecision.model_validate(output.model_dump(mode="python"))
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            raise LLMStructuredOutputError(
                "Router returned invalid structured output",
                context={"provider": self._model_factory.provider_name()},
            ) from error

    @staticmethod
    def _specialist_prompt(
        *,
        intent: Intent,
        user_input: str,
        correlation_id: str,
        fact_names: list[str],
    ) -> str:
        sanitized_input = _redact_complete_phone(user_input.strip())
        payload = {
            "allowed_intent": intent.value,
            "correlation_id": correlation_id,
            "request": sanitized_input,
            "available_fact_names": fact_names,
            "instruction": "Hand off to the matching read-only specialist.",
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _run_metadata(result: Any) -> tuple[bool, list[str]]:
        handoff_occurred = False
        tool_names: list[str] = []
        for item in result.new_items:
            if isinstance(item, HandoffOutputItem):
                handoff_occurred = True
            elif isinstance(item, ToolCallItem):
                name = getattr(item.raw_item, "name", None)
                if isinstance(name, str) and name and name not in tool_names:
                    tool_names.append(name)
        return handoff_occurred, tool_names

    async def run_specialist(
        self,
        *,
        intent: Intent,
        user_input: str,
        correlation_id: str,
        requested_at: datetime,
        facts: Mapping[str, Any],
    ) -> AgentResult:
        """Run one actual read-only handoff and return only validated project output."""

        expected = _ALLOWED_SPECIALISTS.get(intent)
        if expected is None:
            raise LLMGuardrailError(
                "Intent is not approved for the read-only specialist runtime",
                context={"intent": intent.value if isinstance(intent, Intent) else "invalid"},
            )
        context = SDKReadOnlyContext(
            allowed_intent=intent,
            correlation_id=correlation_id,
            requested_at=requested_at,
            facts=facts,
        )
        definitions = self._specialists()
        prompt = self._specialist_prompt(
            intent=intent,
            user_input=user_input,
            correlation_id=correlation_id,
            fact_names=sorted(context.facts),
        )
        result = await self._run_sdk(
            agent=definitions.triage,
            input_value=prompt,
            context=context,
            workflow_name="Payment read-only specialist review",
        )
        expected_agent_name, expected_specialist = expected
        try:
            final_agent_name = result.last_agent.name
            handoff_occurred, tool_names = self._run_metadata(result)
        except (AttributeError, TypeError) as error:
            raise LLMHandoffError(
                "SDK run did not expose valid handoff metadata",
                context={"expected_agent": expected_agent_name},
            ) from error
        if not handoff_occurred:
            raise LLMHandoffError(
                "Required read-only specialist handoff did not occur",
                context={"expected_agent": expected_agent_name},
            )
        if final_agent_name != expected_agent_name:
            raise LLMHandoffError(
                "Read-only handoff reached the wrong specialist",
                context={
                    "expected_agent": expected_agent_name,
                    "actual_agent": final_agent_name,
                },
            )
        try:
            output = result.final_output
            if not isinstance(output, ReadOnlySpecialistOutput):
                raise TypeError("final output is not ReadOnlySpecialistOutput")
            validated = ReadOnlySpecialistOutput.model_validate(output.model_dump(mode="python"))
            if validated.specialist is not expected_specialist:
                raise ValueError("specialist identity does not match intent")
        except (AttributeError, TypeError, ValueError, ValidationError) as error:
            raise LLMStructuredOutputError(
                "Specialist returned invalid structured output",
                context={"expected_agent": expected_agent_name},
            ) from error
        rejection_reason = _specialist_output_rejection_reason(
            context,
            validated,
            expected_specialist,
        )
        if rejection_reason is not None:
            raise LLMGuardrailError(
                "Specialist output violated authorized read-only facts",
                context={
                    "expected_agent": expected_agent_name,
                    "reason": rejection_reason,
                },
            )
        metadata = SDKRunMetadata(
            provider=self._model_factory.provider_name(),
            model=self._model_factory.model_name(),
            final_agent_name=final_agent_name,
            handoff_occurred=True,
            tool_names_used=tool_names,
            structured_output_validated=True,
        )
        return AgentResult(
            agent_name=expected_agent_name,
            output=validated,
            confidence=1.0,
            metadata=metadata.model_dump(mode="json"),
        )

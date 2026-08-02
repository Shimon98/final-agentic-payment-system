"""Repeatable read-only function tools for SDK specialist agents."""

from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm.context import (
    SDKReadOnlyContext,
    json_compatible_copy,
)
from agentic_payments.infrastructure.llm.exceptions import LLMGuardrailError
from agentic_payments.infrastructure.llm.sdk_guardrails import (
    _tool_input_guardrail,
    _tool_output_guardrail,
)


def _read_facts(
    context: RunContextWrapper[SDKReadOnlyContext],
    *,
    expected_intent: Intent,
) -> dict[str, Any]:
    if not isinstance(context.context, SDKReadOnlyContext):
        raise LLMGuardrailError("Read-only tool received an invalid context")
    if context.context.allowed_intent is not expected_intent:
        raise LLMGuardrailError(
            "Read-only tool is not authorized for this intent",
            context={"intent": context.context.allowed_intent.value},
        )
    return {
        "intent": expected_intent.value,
        "correlation_id": context.context.correlation_id,
        "requested_at": context.context.requested_at.isoformat(),
        "facts": json_compatible_copy(context.context.facts),
    }


@function_tool(
    name_override="get_fraud_review_facts",
    tool_input_guardrails=[
        _tool_input_guardrail(
            expected_intent=Intent.FRAUD_CHECK,
            expected_tool="get_fraud_review_facts",
        )
    ],
    tool_output_guardrails=[_tool_output_guardrail(expected_tool="get_fraud_review_facts")],
)
async def get_fraud_review_facts(
    context: RunContextWrapper[SDKReadOnlyContext],
) -> dict[str, Any]:
    """Return only the caller-authorized immutable fraud-review facts."""

    return _read_facts(context, expected_intent=Intent.FRAUD_CHECK)


@function_tool(
    name_override="get_security_review_facts",
    tool_input_guardrails=[
        _tool_input_guardrail(
            expected_intent=Intent.SECURITY_REVIEW,
            expected_tool="get_security_review_facts",
        )
    ],
    tool_output_guardrails=[_tool_output_guardrail(expected_tool="get_security_review_facts")],
)
async def get_security_review_facts(
    context: RunContextWrapper[SDKReadOnlyContext],
) -> dict[str, Any]:
    """Return only the caller-authorized immutable security-review facts."""

    return _read_facts(context, expected_intent=Intent.SECURITY_REVIEW)


@function_tool(
    name_override="get_last_action_facts",
    tool_input_guardrails=[
        _tool_input_guardrail(
            expected_intent=Intent.EXPLAIN_LAST_ACTION,
            expected_tool="get_last_action_facts",
        )
    ],
    tool_output_guardrails=[_tool_output_guardrail(expected_tool="get_last_action_facts")],
)
async def get_last_action_facts(
    context: RunContextWrapper[SDKReadOnlyContext],
) -> dict[str, Any]:
    """Return only the caller-authorized immutable last-action facts."""

    return _read_facts(context, expected_intent=Intent.EXPLAIN_LAST_ACTION)

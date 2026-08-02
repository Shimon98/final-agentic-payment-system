"""Actual function-tool construction and repeatable read-only behavior tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from agents.tool_context import ToolContext

from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm import SDKReadOnlyContext
from agentic_payments.infrastructure.llm.sdk_tools import (
    get_fraud_review_facts,
    get_last_action_facts,
    get_security_review_facts,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

TOOLS = {
    Intent.FRAUD_CHECK: get_fraud_review_facts,
    Intent.SECURITY_REVIEW: get_security_review_facts,
    Intent.EXPLAIN_LAST_ACTION: get_last_action_facts,
}


def _tool_context(intent: Intent, tool_name: str) -> ToolContext[SDKReadOnlyContext]:
    return ToolContext(
        context=SDKReadOnlyContext(intent, "CORR-1", NOW, {"status": "reviewed"}),
        tool_name=tool_name,
        tool_call_id="CALL-1",
        tool_arguments="{}",
    )


def _decoded(value: object) -> dict[str, object]:
    if isinstance(value, str):
        parsed = json.loads(value)
        assert isinstance(parsed, dict)
        return parsed
    assert isinstance(value, dict)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(("intent", "tool"), list(TOOLS.items()))
async def test_correct_intent_reads_only_authorized_facts(
    intent: Intent,
    tool: object,
) -> None:
    context = _tool_context(intent, tool.name)  # type: ignore[attr-defined]
    result = await tool.on_invoke_tool(context, "{}")  # type: ignore[attr-defined]
    decoded = _decoded(result)
    assert decoded == {
        "intent": intent.value,
        "correlation_id": "CORR-1",
        "requested_at": NOW.isoformat(),
        "facts": {"status": "reviewed"},
    }


@pytest.mark.asyncio
async def test_wrong_intent_is_rejected_by_tool_body() -> None:
    context = _tool_context(Intent.SECURITY_REVIEW, get_fraud_review_facts.name)
    result = await get_fraud_review_facts.on_invoke_tool(context, "{}")
    assert "not authorized" in str(result)


@pytest.mark.asyncio
async def test_repeated_tool_call_is_safe_and_identical() -> None:
    context = _tool_context(Intent.FRAUD_CHECK, get_fraud_review_facts.name)
    first = await get_fraud_review_facts.on_invoke_tool(context, "{}")
    second = await get_fraud_review_facts.on_invoke_tool(context, "{}")
    assert first == second


@pytest.mark.parametrize("tool", list(TOOLS.values()))
def test_tool_has_no_arbitrary_identifier_argument(tool: object) -> None:
    schema = tool.params_json_schema  # type: ignore[attr-defined]
    assert schema["properties"] == {}
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("tool", "expected_name"),
    [
        (get_fraud_review_facts, "get_fraud_review_facts"),
        (get_security_review_facts, "get_security_review_facts"),
        (get_last_action_facts, "get_last_action_facts"),
    ],
)
def test_exact_tool_names_and_actual_guardrails(
    tool: object,
    expected_name: str,
) -> None:
    assert tool.name == expected_name  # type: ignore[attr-defined]
    assert len(tool.tool_input_guardrails) == 1  # type: ignore[attr-defined]
    assert len(tool.tool_output_guardrails) == 1  # type: ignore[attr-defined]


def test_only_three_read_only_function_tools_exist() -> None:
    from agentic_payments.infrastructure.llm import sdk_tools

    names = {
        value.name for value in vars(sdk_tools).values() if type(value).__name__ == "FunctionTool"
    }
    assert names == {
        "get_fraud_review_facts",
        "get_security_review_facts",
        "get_last_action_facts",
    }
    assert all(
        word not in " ".join(names).lower()
        for word in ("transfer", "approve", "create_user", "balance_mutation")
    )

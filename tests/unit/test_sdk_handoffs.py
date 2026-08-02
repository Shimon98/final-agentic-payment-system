"""Public SDK handoff graph and sanitizing input-filter tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from agents import (
    Agent,
    HandoffCallItem,
    HandoffInputData,
    HandoffOutputItem,
    RunContextWrapper,
)
from openai.types.responses import ResponseFunctionToolCall

from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm.context import SDKReadOnlyContext
from agentic_payments.infrastructure.llm.sdk_agents import _specialist_agents
from agentic_payments.infrastructure.llm.sdk_handoffs import _sanitize_handoff_input

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _input_data() -> HandoffInputData:
    context = SDKReadOnlyContext(
        Intent.FRAUD_CHECK,
        "CORR-1",
        NOW,
        {"transaction_id": "TXN-1", "amount": "10.00"},
    )
    source_agent = Agent(name="Payment Read-Only Triage", model="test-model")
    target_agent = Agent(name="Fraud Review Specialist", model="test-model")
    handoff_call = HandoffCallItem(
        agent=source_agent,
        raw_item=ResponseFunctionToolCall(
            arguments="{}",
            call_id="CALL-1",
            name="transfer_to_fraud_review_specialist",
            type="function_call",
        ),
    )
    handoff_output = HandoffOutputItem(
        agent=source_agent,
        raw_item={
            "type": "function_call_output",
            "call_id": "CALL-1",
            "output": "accepted",
        },
        source_agent=source_agent,
        target_agent=target_agent,
    )
    return HandoffInputData(
        input_history="unsafe prior history with TXN-999 and 99.00",
        pre_handoff_items=(handoff_call,),
        new_items=(handoff_call, handoff_output),
        run_context=RunContextWrapper(context=context),
    )


def test_exact_three_handoff_targets_and_public_filters() -> None:
    agents = _specialist_agents("test-model")  # type: ignore[arg-type]
    assert [handoff.agent_name for handoff in agents.triage.handoffs] == [
        "Fraud Review Specialist",
        "Security Review Specialist",
        "Payment Explanation Specialist",
    ]
    assert all(handoff.input_filter is not None for handoff in agents.triage.handoffs)


@pytest.mark.parametrize(
    ("intent", "enabled_name"),
    [
        (Intent.FRAUD_CHECK, "Fraud Review Specialist"),
        (Intent.SECURITY_REVIEW, "Security Review Specialist"),
        (Intent.EXPLAIN_LAST_ACTION, "Payment Explanation Specialist"),
    ],
)
@pytest.mark.asyncio
async def test_exactly_one_handoff_is_enabled_for_each_read_only_intent(
    intent: Intent,
    enabled_name: str,
) -> None:
    agents = _specialist_agents("test-model")  # type: ignore[arg-type]
    context = SDKReadOnlyContext(intent, "CORR-1", NOW, {})
    wrapper = RunContextWrapper(context=context)
    enabled: list[str] = []
    for configured_handoff in agents.triage.handoffs:
        predicate = configured_handoff.is_enabled
        assert callable(predicate)
        if await predicate(wrapper, agents.triage):
            enabled.append(configured_handoff.agent_name)
    assert enabled == [enabled_name]


@pytest.mark.parametrize(
    "context",
    [
        object(),
        SimpleNamespace(allowed_intent=Intent.TRANSFER_MONEY),
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_mutating_context_enables_no_handoff(context: object) -> None:
    agents = _specialist_agents("test-model")  # type: ignore[arg-type]
    wrapper = RunContextWrapper(context=context)
    for configured_handoff in agents.triage.handoffs:
        predicate = configured_handoff.is_enabled
        assert callable(predicate)
        assert await predicate(wrapper, agents.triage) is False


def test_handoff_input_is_replaced_with_sanitized_current_context() -> None:
    source = _input_data()
    filtered = _sanitize_handoff_input(source)
    payload = json.loads(filtered.input_history)
    assert payload == {
        "correlation_id": "CORR-1",
        "facts": {"amount": "10.00", "transaction_id": "TXN-1"},
        "requested_at": NOW.isoformat(),
        "task": "fraudCheck",
    }
    assert "TXN-999" not in filtered.input_history
    assert filtered.pre_handoff_items == ()
    assert filtered.new_items == source.new_items
    assert filtered.new_items is source.new_items
    assert any(isinstance(item, HandoffCallItem) for item in filtered.new_items)
    assert any(isinstance(item, HandoffOutputItem) for item in filtered.new_items)
    assert filtered.input_items == ()


def test_handoff_filter_does_not_mutate_source() -> None:
    source = _input_data()
    original_history = source.input_history
    original_pre_handoff_items = source.pre_handoff_items
    original_new_items = source.new_items
    filtered = _sanitize_handoff_input(source)
    assert filtered is not source
    assert source.input_history == original_history
    assert source.pre_handoff_items == original_pre_handoff_items
    assert source.new_items == original_new_items
    assert source.input_items is None


def test_handoff_filter_excludes_complete_memory_state_services_and_prompts() -> None:
    filtered = _sanitize_handoff_input(_input_data())
    lowered = str(filtered.input_history).lower()
    assert all(
        marker not in lowered
        for marker in (
            "businessmemory",
            "applicationstate",
            "repository",
            "service",
            "api_key",
            "system prompt",
        )
    )


def test_missing_context_produces_no_unsafe_history() -> None:
    source = HandoffInputData(
        input_history="secret prior history",
        pre_handoff_items=(),
        new_items=(),
    )
    filtered = _sanitize_handoff_input(source)
    assert json.loads(filtered.input_history) == {"task": "invalid_read_only_context"}
    assert "secret prior history" not in filtered.input_history


def test_source_context_remains_the_same_object() -> None:
    source = _input_data()
    wrapper = source.run_context
    filtered = _sanitize_handoff_input(source)
    assert source.run_context is wrapper
    assert filtered.run_context is wrapper

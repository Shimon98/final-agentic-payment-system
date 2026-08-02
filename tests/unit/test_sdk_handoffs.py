"""Public SDK handoff graph and sanitizing input-filter tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from agents import HandoffInputData, RunContextWrapper

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
    return HandoffInputData(
        input_history="unsafe prior history with TXN-999 and 99.00",
        pre_handoff_items=(),
        new_items=(),
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
    assert filtered.new_items == ()
    assert filtered.input_items == ()


def test_handoff_filter_does_not_mutate_source() -> None:
    source = _input_data()
    original_history = source.input_history
    filtered = _sanitize_handoff_input(source)
    assert filtered is not source
    assert source.input_history == original_history
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

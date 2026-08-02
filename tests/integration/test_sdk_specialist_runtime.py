"""Offline actual-handoff result validation for each read-only specialist."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent, HandoffOutputItem, Runner, ToolCallItem

from agentic_payments.domain import Intent
from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm import (
    AgentsModelFactory,
    LLMGuardrailError,
    LLMHandoffError,
    LLMStructuredOutputError,
    OpenAIAgentsRuntime,
    ReadOnlySpecialistOutput,
    SpecialistType,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

EXPECTED = {
    Intent.FRAUD_CHECK: (
        "Fraud Review Specialist",
        SpecialistType.FRAUD,
        "get_fraud_review_facts",
    ),
    Intent.SECURITY_REVIEW: (
        "Security Review Specialist",
        SpecialistType.SECURITY,
        "get_security_review_facts",
    ),
    Intent.EXPLAIN_LAST_ACTION: (
        "Payment Explanation Specialist",
        SpecialistType.EXPLANATION,
        "get_last_action_facts",
    ),
}


def _runtime() -> OpenAIAgentsRuntime:
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        llm_model="test-model",
        llm_api_key="test-secret",
        enable_llm_router=True,
    )
    return OpenAIAgentsRuntime(model_factory=AgentsModelFactory(settings=settings))


def _result(
    *,
    starting_agent: Agent[Any],
    final_name: str,
    output: object,
    tool_name: str,
    include_handoff: bool = True,
) -> SimpleNamespace:
    target = Agent(name=final_name, model="test-model")
    new_items: list[object] = []
    if include_handoff:
        new_items.append(
            HandoffOutputItem(
                agent=starting_agent,
                raw_item={"type": "handoff_output", "output": "accepted"},
                source_agent=starting_agent,
                target_agent=target,
            )
        )
    new_items.append(
        ToolCallItem(
            agent=target,
            raw_item=SimpleNamespace(name=tool_name),
        )
    )
    return SimpleNamespace(
        final_output=output,
        last_agent=target,
        new_items=new_items,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("intent", "expected"), list(EXPECTED.items()))
async def test_structured_specialist_result_and_exact_handoff(
    intent: Intent,
    expected: tuple[str, SpecialistType, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_name, specialist_type, tool_name = expected
    output = ReadOnlySpecialistOutput(
        specialist=specialist_type,
        message_he="בדיקה הושלמה.",
        message_en="Review completed.",
        facts_used=["status"],
    )
    captured: dict[str, Any] = {}

    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        captured.update({"input": input, **kwargs})
        return _result(
            starting_agent=starting_agent,
            final_name=final_name,
            output=output,
            tool_name=tool_name,
        )

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    result = await _runtime().run_specialist(
        intent=intent,
        user_input="review this read-only task",
        correlation_id="CORR-1",
        requested_at=NOW,
        facts={"status": "reviewed"},
    )
    assert result.agent_name == final_name
    assert result.output == output
    assert result.confidence == 1.0
    assert result.metadata == {
        "provider": "openai",
        "model": "test-model",
        "final_agent_name": final_name,
        "handoff_occurred": True,
        "tool_names_used": [tool_name],
        "structured_output_validated": True,
    }
    assert captured["max_turns"] == 4
    assert captured["context"].allowed_intent is intent
    assert "0501234567" not in captured["input"]


@pytest.mark.asyncio
async def test_wrong_final_specialist_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        return _result(
            starting_agent=starting_agent,
            final_name="Security Review Specialist",
            output=ReadOnlySpecialistOutput(
                specialist=SpecialistType.SECURITY,
                message_he="נבדק.",
                message_en="Reviewed.",
                facts_used=[],
            ),
            tool_name="get_security_review_facts",
        )

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    with pytest.raises(LLMHandoffError, match="wrong specialist"):
        await _runtime().run_specialist(
            intent=Intent.FRAUD_CHECK,
            user_input="fraud review",
            correlation_id="CORR-1",
            requested_at=NOW,
            facts={},
        )


@pytest.mark.asyncio
async def test_missing_handoff_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        return _result(
            starting_agent=starting_agent,
            final_name="Fraud Review Specialist",
            output=ReadOnlySpecialistOutput(
                specialist=SpecialistType.FRAUD,
                message_he="נבדק.",
                message_en="Reviewed.",
                facts_used=[],
            ),
            tool_name="get_fraud_review_facts",
            include_handoff=False,
        )

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    with pytest.raises(LLMHandoffError, match="did not occur"):
        await _runtime().run_specialist(
            intent=Intent.FRAUD_CHECK,
            user_input="fraud review",
            correlation_id="CORR-1",
            requested_at=NOW,
            facts={},
        )


@pytest.mark.asyncio
async def test_invalid_specialist_output_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        return _result(
            starting_agent=starting_agent,
            final_name="Fraud Review Specialist",
            output="free text",
            tool_name="get_fraud_review_facts",
        )

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    with pytest.raises(LLMStructuredOutputError):
        await _runtime().run_specialist(
            intent=Intent.FRAUD_CHECK,
            user_input="fraud review",
            correlation_id="CORR-1",
            requested_at=NOW,
            facts={},
        )


@pytest.mark.asyncio
async def test_mutating_intent_is_rejected_before_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Runner must not be called")

    monkeypatch.setattr(Runner, "run", fail_run)
    with pytest.raises(LLMGuardrailError):
        await _runtime().run_specialist(
            intent=Intent.TRANSFER_MONEY,
            user_input="transfer money",
            correlation_id="CORR-1",
            requested_at=NOW,
            facts={},
        )

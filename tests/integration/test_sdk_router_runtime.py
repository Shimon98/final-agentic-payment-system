"""Offline structured router runtime tests through the public Runner entry point."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from agents import (
    Agent,
    GuardrailFunctionOutput,
    OutputGuardrail,
    OutputGuardrailTripwireTriggered,
    Runner,
)
from agents.guardrail import OutputGuardrailResult

from agentic_payments.application import BusinessMemory, RouterDecision
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm import (
    AgentsModelFactory,
    LLMGuardrailError,
    LLMStructuredOutputError,
    LLMUnavailableError,
    OpenAIAgentsRuntime,
    sdk_runtime,
)


def _runtime(*, tracing: bool = False) -> OpenAIAgentsRuntime:
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        llm_model="test-model",
        llm_api_key="test-secret",
        enable_llm_router=True,
        enable_tracing=tracing,
    )
    return OpenAIAgentsRuntime(model_factory=AgentsModelFactory(settings=settings))


def _runner_result(output: object) -> SimpleNamespace:
    return SimpleNamespace(
        final_output=output,
        last_agent=Agent(name="Payment Intent Router", model="test-model"),
        new_items=[],
    )


def _output_guardrail_error(reason: object) -> OutputGuardrailTripwireTriggered:
    guardrail = OutputGuardrail(
        lambda _context, _agent, _output: GuardrailFunctionOutput(
            output_info={"reason": reason},
            tripwire_triggered=True,
        ),
        name="test_output_guardrail",
    )
    function_output = GuardrailFunctionOutput(
        output_info={
            "reason": reason,
            "unsafe_extra": "prompt facts test-secret raw-model-output",
        },
        tripwire_triggered=True,
    )
    result = OutputGuardrailResult(
        guardrail=guardrail,
        agent_output="prompt facts test-secret raw-model-output",
        agent=Agent(name="Guardrail Agent", model="test-model"),
        output=function_output,
    )
    return OutputGuardrailTripwireTriggered(result)


@pytest.mark.asyncio
async def test_structured_router_result_is_revalidated_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = RouterDecision(
        intent=Intent.CHECK_BALANCE,
        parameters={"user_id": "USR-1"},
        confidence=0.95,
    )
    captured: dict[str, Any] = {}

    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        captured.update(
            {
                "agent": starting_agent,
                "input": input,
                **kwargs,
            }
        )
        return _runner_result(decision)

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    runtime = _runtime()
    result = await runtime.route(
        user_input="check my balance",
        correlation_id="CORR-1",
        memory=BusinessMemory(last_user_id="USR-1"),
    )
    assert result == decision
    assert result is not decision
    assert captured["agent"].name == "Payment Intent Router"
    assert captured["max_turns"] == 4
    assert "last_user_id" in captured["input"]
    assert "session" not in captured
    assert captured["run_config"].tracing_disabled
    assert captured["run_config"].trace_include_sensitive_data is False


@pytest.mark.asyncio
async def test_openai_tracing_is_opt_in_and_excludes_sensitive_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        captured.update(kwargs)
        return _runner_result(RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=0.1))

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    await _runtime(tracing=True).route(
        user_input="unknown",
        correlation_id="CORR-1",
        memory=BusinessMemory(),
    )
    assert captured["run_config"].tracing_disabled is False
    assert captured["run_config"].trace_include_sensitive_data is False
    assert captured["run_config"].trace_metadata == {"provider": "openai"}


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [{"intent": "unknown"}, "free text", None])
async def test_invalid_router_output_converts_to_structured_output_error(
    output: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        return _runner_result(output)

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    with pytest.raises(LLMStructuredOutputError):
        await _runtime().route(
            user_input="unknown",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        RouterDecision.model_construct(intent="notAnIntent", parameters={}, confidence=0.9),
        RouterDecision.model_construct(intent=Intent.UNKNOWN, parameters={}, confidence=1.5),
        RouterDecision.model_construct(
            intent=Intent.TRANSFER_MONEY,
            parameters=["not", "a", "mapping"],
            confidence=0.95,
        ),
    ],
)
async def test_constructed_invalid_router_decision_is_rejected_locally(
    output: RouterDecision,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        return _runner_result(output)

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))

    with pytest.raises(LLMStructuredOutputError):
        await _runtime().route(
            user_input="unsafe provider result",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )


@pytest.mark.asyncio
async def test_timeout_is_safely_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never_returns(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        await asyncio.Future()

    monkeypatch.setattr(Runner, "run", classmethod(never_returns))
    monkeypatch.setattr(sdk_runtime, "RUN_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(LLMUnavailableError, match="timed out"):
        await _runtime().route(
            user_input="unknown",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )


@pytest.mark.asyncio
async def test_provider_exception_is_safely_converted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fails(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        raise RuntimeError("raw secret provider body")

    monkeypatch.setattr(Runner, "run", classmethod(fails))
    with pytest.raises(LLMUnavailableError) as captured:
        await _runtime().route(
            user_input="unknown",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )
    assert "raw secret provider body" not in str(captured.value)
    assert captured.value.context["failure_type"] == "RuntimeError"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "invalid_output_type",
        "wrong_specialist_identity",
        "payment_execution_claim",
        "invented_identifier",
        "invented_amount",
    ],
)
async def test_approved_output_guardrail_reason_is_safely_retained(
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rejected(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        raise _output_guardrail_error(reason)

    monkeypatch.setattr(Runner, "run", classmethod(rejected))
    with pytest.raises(LLMGuardrailError) as captured:
        await _runtime().route(
            user_input="unknown",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )
    assert captured.value.context == {
        "provider": "openai",
        "guardrail_reason": reason,
    }
    rendered = f"{captured.value} {dict(captured.value.context)}"
    assert "raw-model-output" not in rendered
    assert "test-secret" not in rendered
    assert "prompt facts" not in rendered


@pytest.mark.asyncio
async def test_unknown_output_guardrail_reason_uses_stable_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rejected(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        raise _output_guardrail_error("future_unsafe_reason")

    monkeypatch.setattr(Runner, "run", classmethod(rejected))
    with pytest.raises(LLMGuardrailError) as captured:
        await _runtime().route(
            user_input="unknown",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )
    assert captured.value.context == {
        "provider": "openai",
        "guardrail_reason": "unknown_output_guardrail_reason",
    }


@pytest.mark.asyncio
async def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancelled(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(Runner, "run", classmethod(cancelled))
    with pytest.raises(asyncio.CancelledError):
        await _runtime().route(
            user_input="unknown",
            correlation_id="CORR-1",
            memory=BusinessMemory(),
        )

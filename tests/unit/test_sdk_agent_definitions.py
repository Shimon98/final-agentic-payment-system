"""Exact real SDK agent, tool, prompt, and handoff definitions."""

from __future__ import annotations

from agents import Agent, AgentOutputSchema

from agentic_payments.application import RouterDecision
from agentic_payments.infrastructure.llm.schemas import ReadOnlySpecialistOutput
from agentic_payments.infrastructure.llm.sdk_agents import (
    _router_agent,
    _specialist_agents,
)


def test_router_exact_definition() -> None:
    router = _router_agent("test-model")  # type: ignore[arg-type]
    assert isinstance(router, Agent)
    assert router.name == "Payment Intent Router"
    assert isinstance(router.output_type, AgentOutputSchema)
    assert router.output_type.output_type is RouterDecision
    assert router.output_type.is_strict_json_schema() is False
    assert router.tools == []
    assert router.handoffs == []


def test_exact_specialist_agent_names() -> None:
    definitions = _specialist_agents("test-model")  # type: ignore[arg-type]
    assert [
        definitions.triage.name,
        definitions.fraud.name,
        definitions.security.name,
        definitions.explanation.name,
    ] == [
        "Payment Read-Only Triage",
        "Fraud Review Specialist",
        "Security Review Specialist",
        "Payment Explanation Specialist",
    ]


def test_triage_has_exact_three_handoffs_and_no_tools() -> None:
    definitions = _specialist_agents("test-model")  # type: ignore[arg-type]
    assert definitions.triage.tools == []
    assert [handoff.agent_name for handoff in definitions.triage.handoffs] == [
        "Fraud Review Specialist",
        "Security Review Specialist",
        "Payment Explanation Specialist",
    ]


def test_each_specialist_has_its_only_approved_read_only_tool() -> None:
    definitions = _specialist_agents("test-model")  # type: ignore[arg-type]
    assert [tool.name for tool in definitions.fraud.tools] == ["get_fraud_review_facts"]
    assert [tool.name for tool in definitions.security.tools] == ["get_security_review_facts"]
    assert [tool.name for tool in definitions.explanation.tools] == ["get_last_action_facts"]
    assert all(
        agent.output_type is ReadOnlySpecialistOutput
        for agent in (
            definitions.fraud,
            definitions.security,
            definitions.explanation,
        )
    )
    assert all(
        not isinstance(agent.output_type, AgentOutputSchema)
        for agent in (
            definitions.fraud,
            definitions.security,
            definitions.explanation,
        )
    )


def test_every_specialist_has_input_and_output_guardrails() -> None:
    definitions = _specialist_agents("test-model")  # type: ignore[arg-type]
    assert definitions.triage.input_guardrails
    for agent in (
        definitions.fraud,
        definitions.security,
        definitions.explanation,
    ):
        assert agent.input_guardrails
        assert agent.output_guardrails


def test_all_instructions_contain_required_safety_boundaries() -> None:
    definitions = _specialist_agents("test-model")  # type: ignore[arg-type]
    agents = [
        _router_agent("test-model"),  # type: ignore[arg-type]
        definitions.triage,
        definitions.fraud,
        definitions.security,
        definitions.explanation,
    ]
    for agent in agents:
        instructions = str(agent.instructions).lower()
        assert "educational payment simulation" in instructions
        assert "real banks or payment providers" in instructions
        assert "deterministic business" in instructions
        assert "never mutate a balance" in instructions
        assert "do not invent" in instructions
        assert "structured schema" in instructions


def test_no_financial_mutation_tool_or_handoff_exists() -> None:
    definitions = _specialist_agents("test-model")  # type: ignore[arg-type]
    tool_names = [
        tool.name
        for agent in (
            definitions.triage,
            definitions.fraud,
            definitions.security,
            definitions.explanation,
        )
        for tool in agent.tools
    ]
    handoff_names = [handoff.agent_name for handoff in definitions.triage.handoffs]
    joined = " ".join([*tool_names, *handoff_names]).lower()
    assert "transfer_money" not in joined
    assert "approve_payment" not in joined
    assert "create_user" not in joined

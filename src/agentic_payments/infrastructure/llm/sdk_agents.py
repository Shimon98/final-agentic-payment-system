"""Real, safety-bounded OpenAI Agents SDK definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents import Agent, AgentOutputSchema, Model, ModelSettings

from agentic_payments.agents.prompts import (
    EXPLANATION_SYSTEM_PROMPT,
    FRAUD_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
)
from agentic_payments.application import RouterDecision
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm.context import SDKReadOnlyContext
from agentic_payments.infrastructure.llm.schemas import (
    ReadOnlySpecialistOutput,
    SpecialistType,
)
from agentic_payments.infrastructure.llm.sdk_guardrails import (
    _read_only_agent_input_guardrail,
    _specialist_output_guardrail,
)
from agentic_payments.infrastructure.llm.sdk_handoffs import _read_only_handoff
from agentic_payments.infrastructure.llm.sdk_tools import (
    get_fraud_review_facts,
    get_last_action_facts,
    get_security_review_facts,
)

_COMMON_SUFFIX = """
This is an educational payment simulation only; never contact real banks or payment providers.
Deterministic business logic is authoritative. Never mutate a balance or any business state.
Do not invent information. Return only the configured structured schema.
""".strip()

_ROUTER_SUFFIX = """
Return only RouterDecision and use only the approved Intent values.
Extract only parameters explicitly present in the request.
Never invent IDs, names, phone numbers, or amounts.
Represent monetary values as Decimal-compatible strings.
Use UNKNOWN when classification cannot be completed safely.
This agent only classifies and never performs a payment.
""".strip()

_TRIAGE_SUFFIX = """
You are a read-only triage agent. Use allowed_intent from the sanitized request and hand off
exactly once to the matching fraud, security, or explanation specialist. Never handle a mutating
intent and never answer the task yourself.
""".strip()

_SPECIALIST_FACT_SUFFIX = """
Call the assigned read-only fact tool before producing the final output.
Use only exact facts returned by that tool.
Do not mention the correlation ID.
Do not invent or infer IDs.
Do not invent or infer monetary amounts.
Do not describe an operation as executed unless that exact status is present in the returned facts.
When information is unavailable, say it is unavailable without guessing.
Set recommendation=None when no recommendation can be supported directly by the supplied facts.
""".strip()

_FRAUD_SUFFIX = """
You are the fraud read-only specialist. Call only get_fraud_review_facts.
Use only returned facts. Set specialist to fraud. Review only; never perform a payment.
""".strip()

_SECURITY_SUFFIX = """
You are the security read-only specialist. Call only get_security_review_facts.
Use only returned facts. Set specialist to security. Review only; never perform a payment.
""".strip()

_EXPLANATION_SUFFIX = """
You are the explanation read-only specialist. Call only get_last_action_facts.
Use only returned facts. Set specialist to explanation. Explain only; never perform a payment.
Explain only the supplied action and status.
Do not ask the user to locate an amount when no amount is present.
Do not refer to an account UI, external log, bank, or payment provider.
Do not mention a transaction ID unless it is explicitly present in facts.
""".strip()


@dataclass(frozen=True, slots=True)
class _SpecialistAgents:
    triage: Agent[SDKReadOnlyContext]
    fraud: Agent[SDKReadOnlyContext]
    security: Agent[SDKReadOnlyContext]
    explanation: Agent[SDKReadOnlyContext]


def _router_agent(model: Model) -> Agent[None]:
    return Agent(
        name="Payment Intent Router",
        instructions=f"{ROUTER_SYSTEM_PROMPT}\n\n{_COMMON_SUFFIX}\n\n{_ROUTER_SUFFIX}",
        model=model,
        output_type=AgentOutputSchema(
            RouterDecision,
            strict_json_schema=False,
        ),
        tools=[],
        handoffs=[],
    )


def _specialist_agents(model: Model) -> _SpecialistAgents:
    read_only_input = _read_only_agent_input_guardrail()
    fraud = Agent[SDKReadOnlyContext](
        name="Fraud Review Specialist",
        handoff_description="Review supplied immutable fraud facts only.",
        instructions=(
            f"{FRAUD_SYSTEM_PROMPT}\n\n{_COMMON_SUFFIX}\n\n"
            f"{_SPECIALIST_FACT_SUFFIX}\n\n{_FRAUD_SUFFIX}"
        ),
        model=model,
        output_type=ReadOnlySpecialistOutput,
        tools=[get_fraud_review_facts],
        handoffs=[],
        input_guardrails=[read_only_input],
        output_guardrails=[_specialist_output_guardrail(SpecialistType.FRAUD)],
    )
    security = Agent[SDKReadOnlyContext](
        name="Security Review Specialist",
        handoff_description="Review supplied immutable security facts only.",
        instructions=(
            f"{SECURITY_SYSTEM_PROMPT}\n\n{_COMMON_SUFFIX}\n\n"
            f"{_SPECIALIST_FACT_SUFFIX}\n\n{_SECURITY_SUFFIX}"
        ),
        model=model,
        output_type=ReadOnlySpecialistOutput,
        tools=[get_security_review_facts],
        handoffs=[],
        input_guardrails=[read_only_input],
        output_guardrails=[_specialist_output_guardrail(SpecialistType.SECURITY)],
    )
    explanation = Agent[SDKReadOnlyContext](
        name="Payment Explanation Specialist",
        handoff_description="Explain supplied immutable last-action facts only.",
        instructions=(
            f"{EXPLANATION_SYSTEM_PROMPT}\n\n{_COMMON_SUFFIX}\n\n"
            f"{_SPECIALIST_FACT_SUFFIX}\n\n{_EXPLANATION_SUFFIX}"
        ),
        model=model,
        output_type=ReadOnlySpecialistOutput,
        tools=[get_last_action_facts],
        handoffs=[],
        input_guardrails=[read_only_input],
        output_guardrails=[_specialist_output_guardrail(SpecialistType.EXPLANATION)],
    )
    triage = Agent[SDKReadOnlyContext](
        name="Payment Read-Only Triage",
        instructions=f"{ROUTER_SYSTEM_PROMPT}\n\n{_COMMON_SUFFIX}\n\n{_TRIAGE_SUFFIX}",
        model=model,
        tools=[],
        handoffs=[
            _read_only_handoff(fraud, allowed_intent=Intent.FRAUD_CHECK),
            _read_only_handoff(security, allowed_intent=Intent.SECURITY_REVIEW),
            _read_only_handoff(
                explanation,
                allowed_intent=Intent.EXPLAIN_LAST_ACTION,
            ),
        ],
        input_guardrails=[read_only_input],
        model_settings=ModelSettings(
            tool_choice="required",
            parallel_tool_calls=False,
        ),
    )
    return _SpecialistAgents(
        triage=triage,
        fraud=fraud,
        security=security,
        explanation=explanation,
    )


def _agent_model_name(agent: Agent[Any]) -> str:
    model = agent.model
    return type(model).__name__ if model is not None else "unconfigured"

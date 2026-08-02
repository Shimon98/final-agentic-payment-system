"""Safety-boundary and source-of-truth tests for future LLM prompts."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import pytest

from agentic_payments.agents.prompts import (
    ALL_AGENT_PROMPTS,
    CRITIC_SYSTEM_PROMPT,
    EXPLANATION_SYSTEM_PROMPT,
    FALLBACK_SYSTEM_PROMPT,
    FRAUD_SYSTEM_PROMPT,
    REFLECTION_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
)

PROMPTS = [
    ROUTER_SYSTEM_PROMPT,
    FRAUD_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
    EXPLANATION_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    REFLECTION_SYSTEM_PROMPT,
    FALLBACK_SYSTEM_PROMPT,
]


def test_every_required_prompt_exists_is_non_empty_and_stripped() -> None:
    assert len(PROMPTS) == 7
    assert all(
        isinstance(prompt, str) and prompt and prompt == prompt.strip() for prompt in PROMPTS
    )


@pytest.mark.parametrize("prompt", PROMPTS)
def test_every_prompt_contains_all_safety_boundaries(prompt: str) -> None:
    lowered = prompt.lower()
    assert "educational payment simulation" in lowered
    assert "do not connect to real banks or payment providers" in lowered
    assert "do not directly change balances" in lowered
    assert "deterministic business tools remain authoritative" in lowered
    assert "structured schema" in lowered
    assert "do not invent missing information" in lowered


def test_all_agent_prompts_has_exact_read_only_mapping() -> None:
    assert isinstance(ALL_AGENT_PROMPTS, Mapping)
    assert isinstance(ALL_AGENT_PROMPTS, MappingProxyType)
    assert list(ALL_AGENT_PROMPTS) == [
        "RouterAgent",
        "FraudDetectionAgent",
        "SecurityAgent",
        "ExplanationAgent",
        "CriticAgent",
        "ReflectionAgent",
        "FallbackAgent",
    ]
    with pytest.raises(TypeError):
        ALL_AGENT_PROMPTS["PolicyAgent"] = "forbidden"  # type: ignore[index]


def test_policy_agent_has_no_prompt() -> None:
    assert "PolicyAgent" not in ALL_AGENT_PROMPTS

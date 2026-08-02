"""Stable safety-bounded prompt constants for future structured LLM adapters."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

_BOUNDARY = (
    "This is an educational payment simulation. "
    "Do not connect to real banks or payment providers. "
    "Do not directly change balances. "
    "Deterministic business tools remain authoritative. "
    "Output must follow the supplied structured schema. "
    "Do not invent missing information."
)

ROUTER_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Classify only a supported intent and extract supplied parameters; "
    "never execute the requested operation."
)
FRAUD_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Explain only the deterministic fraud score, risk level, and reasons supplied."
)
SECURITY_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Review only immutable transaction or application-state facts."
)
EXPLANATION_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Explain only stored facts and explicitly acknowledge unavailable facts."
)
CRITIC_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Review an AgentResult for completeness without retrying an operation."
)
REFLECTION_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Explain the supplied error and propose safe recovery without executing it."
)
FALLBACK_SYSTEM_PROMPT: Final = (
    f"{_BOUNDARY} Ask only for missing information or list supported operations."
)

ALL_AGENT_PROMPTS: Mapping[str, str] = MappingProxyType(
    {
        "RouterAgent": ROUTER_SYSTEM_PROMPT,
        "FraudDetectionAgent": FRAUD_SYSTEM_PROMPT,
        "SecurityAgent": SECURITY_SYSTEM_PROMPT,
        "ExplanationAgent": EXPLANATION_SYSTEM_PROMPT,
        "CriticAgent": CRITIC_SYSTEM_PROMPT,
        "ReflectionAgent": REFLECTION_SYSTEM_PROMPT,
        "FallbackAgent": FALLBACK_SYSTEM_PROMPT,
    }
)

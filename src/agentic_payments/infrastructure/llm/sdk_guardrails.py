"""Actual public Agents SDK guardrails for the read-only specialist boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrail,
    OutputGuardrail,
    RunContextWrapper,
    ToolGuardrailFunctionOutput,
    ToolInputGuardrail,
    ToolInputGuardrailData,
    ToolOutputGuardrail,
    ToolOutputGuardrailData,
    TResponseInputItem,
)

from agentic_payments.domain import Intent
from agentic_payments.infrastructure.llm.context import SDKReadOnlyContext
from agentic_payments.infrastructure.llm.schemas import (
    ReadOnlySpecialistOutput,
    SpecialistType,
)

MAX_TOOL_OUTPUT_CHARACTERS = 20_000

_INTENT_TO_TOOL = {
    Intent.FRAUD_CHECK: "get_fraud_review_facts",
    Intent.SECURITY_REVIEW: "get_security_review_facts",
    Intent.EXPLAIN_LAST_ACTION: "get_last_action_facts",
}
_SECRET_MARKERS = ("api_key", "authorization", "secret", "password", "token", "prompt")
_MONEY_MARKERS = ("amount", "balance", "money", "price", "total", "fund")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]*){7,15}(?!\d)")
_IDENTIFIER = re.compile(r"\b(?:USR|TXN|REQ|AUD|CORR)-[A-Za-z0-9_-]+\b")
_DECIMAL_AMOUNT = re.compile(r"(?<![\w.-])\d+\.\d{1,2}(?![\w.-])")
_EXECUTION_CLAIM = re.compile(
    r"\b(?:i|we|the system)\s+(?:have\s+)?"
    r"(?:executed|initiated|sent|transferred|approved|paid)\b"
    r"|(?:payment|transfer)\s+(?:has\s+been\s+)?(?:executed|initiated|approved)\b"
    r"|(?:ביצעתי|העברתי|שלחתי|אישרתי).{0,25}(?:תשלום|כסף|העברה)?",
    flags=re.IGNORECASE,
)
_EXECUTABLE_INSTRUCTION = re.compile(
    r"\b(?:execute|initiate|send|transfer|approve|pay)\b.{0,35}"
    r"\b(?:payment|money|funds|transfer)\b"
    r"|(?:בצע|העבר|שלח|אשר).{0,30}(?:תשלום|כסף|העברה)",
    flags=re.IGNORECASE,
)


def _has_complete_phone(value: str) -> bool:
    return any(7 <= len(re.sub(r"\D", "", match.group())) <= 15 for match in _PHONE.finditer(value))


def _validate_json_value(value: Any, *, path: str, money_context: bool = False) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or not key or key != key.strip():
                raise ValueError(f"{path} contains an invalid key")
            lowered = key.lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                raise ValueError(f"{path} contains a secret-like key")
            _validate_json_value(
                nested,
                path=f"{path}.{key}",
                money_context=any(marker in lowered for marker in _MONEY_MARKERS),
            )
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item, path=f"{path}[]", money_context=money_context)
        return
    if isinstance(value, float) and money_context:
        raise ValueError(f"{path} contains float money")
    if isinstance(value, str):
        if _has_complete_phone(value):
            raise ValueError(f"{path} contains a complete phone number")
        if _EXECUTABLE_INSTRUCTION.search(value):
            raise ValueError(f"{path} contains an executable instruction")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise TypeError(f"{path} contains a non-JSON or mutable domain value")


def _validate_tool_output(output: Any) -> None:
    _validate_json_value(output, path="tool_output")
    try:
        encoded = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("tool output must be JSON-compatible") from error
    if len(encoded) > MAX_TOOL_OUTPUT_CHARACTERS:
        raise ValueError("tool output exceeds the safe size limit")


def _tool_input_guardrail(
    *,
    expected_intent: Intent,
    expected_tool: str,
) -> ToolInputGuardrail[SDKReadOnlyContext]:
    def validate(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        context = data.context.context
        if not isinstance(context, SDKReadOnlyContext):
            return ToolGuardrailFunctionOutput.raise_exception({"reason": "invalid_context"})
        if context.allowed_intent is not expected_intent:
            return ToolGuardrailFunctionOutput.raise_exception({"reason": "wrong_intent"})
        if data.context.tool_name != expected_tool:
            return ToolGuardrailFunctionOutput.raise_exception({"reason": "wrong_tool"})
        try:
            arguments = json.loads(data.context.tool_arguments or "{}")
        except json.JSONDecodeError:
            return ToolGuardrailFunctionOutput.raise_exception({"reason": "invalid_arguments"})
        if arguments != {}:
            return ToolGuardrailFunctionOutput.raise_exception(
                {"reason": "unexpected_resource_selector"}
            )
        return ToolGuardrailFunctionOutput.allow({"validated": True})

    return ToolInputGuardrail(validate, name=f"{expected_tool}_input_guardrail")


def _tool_output_guardrail(
    *,
    expected_tool: str,
) -> ToolOutputGuardrail[SDKReadOnlyContext]:
    def validate(data: ToolOutputGuardrailData) -> ToolGuardrailFunctionOutput:
        if data.context.tool_name != expected_tool:
            return ToolGuardrailFunctionOutput.raise_exception({"reason": "wrong_tool"})
        try:
            _validate_tool_output(data.output)
        except (TypeError, ValueError):
            return ToolGuardrailFunctionOutput.raise_exception({"reason": "unsafe_output"})
        return ToolGuardrailFunctionOutput.allow({"validated": True})

    return ToolOutputGuardrail(validate, name=f"{expected_tool}_output_guardrail")


def _read_only_agent_input_guardrail() -> InputGuardrail[SDKReadOnlyContext]:
    def validate(
        context: RunContextWrapper[SDKReadOnlyContext],
        _agent: Agent[Any],
        _input_value: str | list[TResponseInputItem],
    ) -> GuardrailFunctionOutput:
        valid = (
            isinstance(context.context, SDKReadOnlyContext)
            and context.context.allowed_intent in _INTENT_TO_TOOL
        )
        return GuardrailFunctionOutput(
            output_info={"read_only_intent": valid},
            tripwire_triggered=not valid,
        )

    return InputGuardrail(validate, name="read_only_specialist_input", run_in_parallel=False)


def _flatten_authorized_values(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        flattened: set[str] = set()
        for key, nested in value.items():
            flattened.add(str(key))
            flattened.update(_flatten_authorized_values(nested))
        return flattened
    if isinstance(value, (list, tuple)):
        flattened = set()
        for nested in value:
            flattened.update(_flatten_authorized_values(nested))
        return flattened
    if value is None:
        return set()
    return {str(value)}


def _specialist_output_guardrail(
    expected_specialist: SpecialistType,
) -> OutputGuardrail[SDKReadOnlyContext]:
    def validate(
        context: RunContextWrapper[SDKReadOnlyContext],
        _agent: Agent[Any],
        output: Any,
    ) -> GuardrailFunctionOutput:
        reason = _specialist_output_rejection_reason(
            context.context,
            output,
            expected_specialist,
        )
        return GuardrailFunctionOutput(
            output_info={"reason": reason or "validated"},
            tripwire_triggered=reason is not None,
        )

    return OutputGuardrail(validate, name=f"{expected_specialist.value}_specialist_output")


def _specialist_output_rejection_reason(
    context: SDKReadOnlyContext,
    output: Any,
    expected_specialist: SpecialistType,
) -> str | None:
    """Return a stable safe reason when specialist output violates local facts."""

    if not isinstance(output, ReadOnlySpecialistOutput):
        return "invalid_output_type"
    if output.specialist is not expected_specialist:
        return "wrong_specialist_identity"
    texts = " ".join(
        (
            output.message_he,
            output.message_en,
            output.recommendation or "",
        )
    )
    if _EXECUTION_CLAIM.search(texts):
        return "payment_execution_claim"
    authorized = _flatten_authorized_values(context.facts)
    identifiers = set(_IDENTIFIER.findall(texts))
    amounts = set(_DECIMAL_AMOUNT.findall(texts))
    if any(identifier not in authorized for identifier in identifiers):
        return "invented_identifier"
    if any(amount not in authorized for amount in amounts):
        return "invented_amount"
    return None

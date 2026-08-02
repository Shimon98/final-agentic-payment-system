"""Strict read-only SDK schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_payments.infrastructure.llm.schemas import (
    ReadOnlySpecialistOutput,
    SDKRunMetadata,
    SpecialistType,
)


def _output(**overrides: object) -> ReadOnlySpecialistOutput:
    values: dict[str, object] = {
        "specialist": SpecialistType.FRAUD,
        "message_he": "בדיקה הושלמה.",
        "message_en": "Review completed.",
        "facts_used": ["risk_score", "risk_level"],
        "recommendation": "Review the deterministic facts.",
    }
    values.update(overrides)
    return ReadOnlySpecialistOutput.model_validate(values)


def test_valid_output_strips_messages_and_recommendation() -> None:
    output = _output(
        message_he="  בדיקה הושלמה.  ",
        message_en="  Review completed.  ",
        recommendation="  Review facts.  ",
    )
    assert output.message_he == "בדיקה הושלמה."
    assert output.message_en == "Review completed."
    assert output.recommendation == "Review facts."


@pytest.mark.parametrize("field", ["message_he", "message_en"])
def test_blank_message_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        _output(**{field: "  "})


def test_fact_names_are_stripped_and_deduplicated_in_first_seen_order() -> None:
    output = _output(facts_used=[" risk_score ", "risk_level", "risk_score"])
    assert output.facts_used == ["risk_score", "risk_level"]


def test_blank_fact_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _output(facts_used=["risk_score", " "])


def test_executable_field_and_instruction_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ReadOnlySpecialistOutput.model_validate(
            {
                **_output().model_dump(),
                "execute_payment": True,
            }
        )
    with pytest.raises(ValidationError):
        _output(recommendation="Execute the payment now.")


def test_output_is_frozen() -> None:
    output = _output()
    with pytest.raises(ValidationError):
        output.message_en = "Changed"  # type: ignore[misc]


def test_sdk_metadata_strips_and_deduplicates_tool_names() -> None:
    metadata = SDKRunMetadata(
        provider=" openai ",
        model=" gpt-test ",
        final_agent_name=" Fraud Review Specialist ",
        handoff_occurred=True,
        tool_names_used=[" get_fraud_review_facts ", "get_fraud_review_facts"],
        structured_output_validated=True,
    )
    assert metadata.provider == "openai"
    assert metadata.tool_names_used == ["get_fraud_review_facts"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": " "},
        {"model": " "},
        {"final_agent_name": " "},
        {"tool_names_used": [""]},
        {"provider": "Bearer secret-value"},
    ],
)
def test_invalid_or_secret_metadata_is_rejected(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "provider": "openai",
        "model": "gpt-test",
        "final_agent_name": "Fraud Review Specialist",
        "handoff_occurred": True,
        "tool_names_used": [],
        "structured_output_validated": True,
    }
    values.update(overrides)
    with pytest.raises(ValidationError):
        SDKRunMetadata.model_validate(values)


def test_sdk_metadata_is_frozen() -> None:
    metadata = SDKRunMetadata(
        provider="openai",
        model="gpt-test",
        final_agent_name="Fraud Review Specialist",
        handoff_occurred=True,
        tool_names_used=[],
        structured_output_validated=True,
    )
    with pytest.raises(ValidationError):
        metadata.provider = "changed"  # type: ignore[misc]

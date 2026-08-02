"""Strict structured outputs that may cross the SDK infrastructure boundary."""

from __future__ import annotations

import re
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator

_EXECUTION_INSTRUCTION = re.compile(
    r"(?:\b(?:execute|initiate|perform|send|transfer|pay|approve)\b"
    r".{0,40}\b(?:payment|money|funds|transfer)\b)"
    r"|(?:\b(?:payment|transfer)\b.{0,25}\b(?:now|immediately)\b)"
    r"|(?:בצע|העבר|שלח|אשר).{0,30}(?:תשלום|כסף|העברה)",
    flags=re.IGNORECASE,
)


def _stripped_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


def _review_text(value: object, field_name: str) -> str:
    stripped = _stripped_text(value, field_name)
    if _EXECUTION_INSTRUCTION.search(stripped):
        raise ValueError(f"{field_name} must not instruct payment execution")
    return stripped


def _deduplicated_texts(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    copied: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _stripped_text(item, field_name)
        if text not in seen:
            seen.add(text)
            copied.append(text)
    return copied


class SpecialistType(str, Enum):  # noqa: UP042 - exact approved public base classes.
    """The three approved read-only specialist identities."""

    FRAUD = "fraud"
    SECURITY = "security"
    EXPLANATION = "explanation"


class ReadOnlySpecialistOutput(BaseModel):
    """Explanation or review text with no executable action fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specialist: SpecialistType
    message_he: str
    message_en: str
    facts_used: list[str]
    recommendation: str | None = None

    @field_validator("message_he", "message_en", mode="before")
    @classmethod
    def _messages(cls, value: object, info: ValidationInfo) -> str:
        return _review_text(value, info.field_name or "message")

    @field_validator("facts_used", mode="before")
    @classmethod
    def _facts_used(cls, value: object) -> list[str]:
        return _deduplicated_texts(value, "facts_used")

    @field_validator("recommendation", mode="before")
    @classmethod
    def _recommendation(cls, value: object) -> object:
        if value is None:
            return None
        return _review_text(value, "recommendation")


class SDKRunMetadata(BaseModel):
    """Safe metadata retained from one SDK run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    final_agent_name: str
    handoff_occurred: bool
    tool_names_used: list[str]
    structured_output_validated: bool

    @field_validator("provider", "model", "final_agent_name", mode="before")
    @classmethod
    def _texts(cls, value: object, info: ValidationInfo) -> str:
        return _stripped_text(value, info.field_name or "text")

    @field_validator("tool_names_used", mode="before")
    @classmethod
    def _tool_names(cls, value: object) -> list[str]:
        return _deduplicated_texts(value, "tool_names_used")

    @model_validator(mode="after")
    def _reject_secret_metadata(self) -> Self:
        combined = " ".join(
            (self.provider, self.model, self.final_agent_name, *self.tool_names_used)
        ).lower()
        if any(
            marker in combined
            for marker in ("api_key", "authorization:", "bearer ", "password=", "secret=")
        ):
            raise ValueError("SDK metadata must not contain secrets")
        return self

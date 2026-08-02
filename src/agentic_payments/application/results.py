"""Shared agent results and validated structured schemas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional  # noqa: UP035 - lecturer-required AgentResult shape.

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentic_payments.domain import Intent, RiskLevel


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty stripped string")
    return value


def _text_list(value: object, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list")
    copied = list(value)
    if required and not copied:
        raise ValueError(f"{field} must not be empty")
    for item in copied:
        _text(item, field)
    return copied


@dataclass(slots=True)
class AgentResult:
    """Common result returned by every agent."""

    agent_name: str
    output: Any
    confidence: float = 1.0
    metadata: Optional[Dict[str, Any]] = None  # noqa: UP006,UP045 - required shape.

    def __post_init__(self) -> None:
        _text(self.agent_name, "agent_name")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be numeric and not bool")
        self.confidence = float(self.confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.metadata is not None:
            if not isinstance(self.metadata, dict):
                raise TypeError("metadata must be a dictionary or None")
            self.metadata = dict(self.metadata)


class RouterDecision(BaseModel):
    """Validated intent classification without command execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent
    parameters: dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    requires_clarification: bool = False
    clarification_question: str | None = None

    @field_validator("parameters", mode="before")
    @classmethod
    def _copy_parameters(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("parameters must be a dictionary")
        return dict(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _strict_confidence(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("confidence must be numeric and not bool")
        return float(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> RouterDecision:
        if self.requires_clarification:
            _text(self.clarification_question, "clarification_question")
        elif self.clarification_question is not None:
            raise ValueError("clarification_question requires clarification")
        executable = {
            "name",
            "phone_number",
            "initial_balance",
            "user_id",
            "sender_id",
            "receiver_id",
            "amount",
            "requester_id",
            "payer_id",
            "request_id",
            "transaction_id",
        }
        if self.intent is Intent.UNKNOWN and executable.intersection(self.parameters):
            raise ValueError("unknown intent cannot contain executable parameters")
        return self


class FraudAssessment(BaseModel):
    """Validated deterministic fraud-assessment output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    reasons: list[str]
    requires_security_review: bool

    @field_validator("transaction_id")
    @classmethod
    def _transaction_id(cls, value: str) -> str:
        return _text(value, "transaction_id")

    @field_validator("risk_score", mode="before")
    @classmethod
    def _score(cls, value: object) -> object:
        if isinstance(value, bool):
            raise TypeError("risk_score must not be bool")
        return value

    @field_validator("reasons", mode="before")
    @classmethod
    def _reasons(cls, value: object) -> list[str]:
        return _text_list(value, "reasons")

    @model_validator(mode="after")
    def _risk_consistency(self) -> FraudAssessment:
        if self.risk_level is RiskLevel.HIGH and not self.requires_security_review:
            raise ValueError("high risk requires security review")
        if self.risk_level is RiskLevel.LOW and self.requires_security_review:
            raise ValueError("low risk must not require security review")
        return self


class SecurityReview(BaseModel):
    """Validated read-only security review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved: bool
    checks_performed: list[str]
    violations: list[str]
    recommendations: list[str]

    @field_validator("checks_performed", "violations", "recommendations", mode="before")
    @classmethod
    def _lists(cls, value: object, info: Any) -> list[str]:
        return _text_list(value, info.field_name)

    @model_validator(mode="after")
    def _approval_consistency(self) -> SecurityReview:
        if self.approved and self.violations:
            raise ValueError("approved review cannot contain violations")
        if not self.approved and not self.violations:
            raise ValueError("rejected review requires violations")
        return self


class CriticReview(BaseModel):
    """Validated quality review of an agent result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved: bool
    quality_score: int = Field(ge=1, le=5)
    problems: list[str]
    requires_fallback: bool

    @field_validator("quality_score", mode="before")
    @classmethod
    def _quality_score(cls, value: object) -> object:
        if isinstance(value, bool):
            raise TypeError("quality_score must not be bool")
        return value

    @field_validator("problems", mode="before")
    @classmethod
    def _problems(cls, value: object) -> list[str]:
        return _text_list(value, "problems")

    @model_validator(mode="after")
    def _critic_consistency(self) -> CriticReview:
        if not self.approved and not self.problems:
            raise ValueError("rejected review requires problems")
        if self.approved and self.requires_fallback:
            raise ValueError("approved review cannot require fallback")
        if self.quality_score <= 2 and not self.requires_fallback:
            raise ValueError("low quality score requires fallback")
        if self.quality_score >= 4 and self.approved and self.requires_fallback:
            raise ValueError("approved high-quality review cannot require fallback")
        return self


class ReflectionAdvice(BaseModel):
    """Validated recovery guidance without executing recovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_code: str
    user_message: str
    recovery_steps: list[str]
    suggested_parameters: dict[str, Any]

    @field_validator("error_code")
    @classmethod
    def _error_code(cls, value: str) -> str:
        checked = _text(value, "error_code")
        if re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", checked) is None:
            raise ValueError("error_code must be snake_case")
        return checked

    @field_validator("user_message")
    @classmethod
    def _user_message(cls, value: str) -> str:
        return _text(value, "user_message")

    @field_validator("recovery_steps", mode="before")
    @classmethod
    def _steps(cls, value: object) -> list[str]:
        return _text_list(value, "recovery_steps", required=True)

    @field_validator("suggested_parameters", mode="before")
    @classmethod
    def _parameters(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise TypeError("suggested_parameters must be a dictionary")
        return dict(value)

"""Validated, immutable environment-backed application settings."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentic_payments.domain import TransferPolicy


class Settings(BaseSettings):
    """Validate local runtime configuration without creating external clients."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    llm_provider: Literal[
        "rule_based",
        "openai",
        "gemini",
        "openai_compatible",
    ] = "rule_based"
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    router_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    enable_llm_router: bool = False
    enable_tracing: bool = False
    state_file: Path = Path("data/payment_state.json")
    audit_file: Path = Path("data/audit_log.jsonl")
    maximum_single_transfer: Decimal = Decimal("5000.00")
    maximum_daily_transfer: Decimal = Decimal("10000.00")
    suspicious_balance_ratio: Decimal = Decimal("0.70")
    rapid_transfer_window_minutes: int = Field(default=10, gt=0)
    rapid_transfer_count: int = Field(default=3, gt=0)

    @field_validator("llm_model", "llm_base_url", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("llm_api_key", mode="before")
    @classmethod
    def _normalize_optional_secret(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            return value if value.get_secret_value().strip() else None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("router_confidence_threshold", mode="before")
    @classmethod
    def _reject_bool_confidence(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("router_confidence_threshold must not be bool")
        return value

    @field_validator(
        "maximum_single_transfer",
        "maximum_daily_transfer",
        "suspicious_balance_ratio",
        mode="before",
    )
    @classmethod
    def _reject_float_decimal_settings(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Decimal settings must not originate from float or bool")
        return value

    @field_validator("maximum_single_transfer", "maximum_daily_transfer")
    @classmethod
    def _validate_money_setting(cls, value: Decimal) -> Decimal:
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("monetary settings must be finite Decimal values")
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -2:
            raise ValueError("monetary settings must have at most two fractional digits")
        if value <= 0:
            raise ValueError("monetary limits must be positive")
        return value

    @field_validator("suspicious_balance_ratio")
    @classmethod
    def _validate_ratio(cls, value: Decimal) -> Decimal:
        if not isinstance(value, Decimal) or not value.is_finite() or not 0 < value <= 1:
            raise ValueError("suspicious_balance_ratio must be a finite Decimal in (0, 1]")
        return value

    @model_validator(mode="after")
    def _validate_combined_settings(self) -> Self:
        if self.state_file == self.audit_file:
            raise ValueError("state_file and audit_file must differ")
        for field_name, path in (
            ("state_file", self.state_file),
            ("audit_file", self.audit_file),
        ):
            if path.is_dir():
                raise ValueError(f"{field_name} must refer to a file")
        if self.maximum_daily_transfer < self.maximum_single_transfer:
            raise ValueError("maximum_daily_transfer must be at least maximum_single_transfer")
        if self.enable_llm_router:
            if self.llm_provider == "rule_based":
                raise ValueError("rule_based cannot be used when enable_llm_router is true")
            if self.llm_model is None:
                raise ValueError("llm_model is required when enable_llm_router is true")
            if self.llm_provider in {"openai", "gemini"} and self.llm_api_key is None:
                raise ValueError("llm_api_key is required for the selected provider")
            if self.llm_provider == "openai_compatible" and self.llm_base_url is None:
                raise ValueError("llm_base_url is required for openai_compatible")
        return self

    def build_transfer_policy(self) -> TransferPolicy:
        """Build the immutable deterministic domain policy."""

        return TransferPolicy(
            maximum_single_transfer=self.maximum_single_transfer,
            maximum_daily_transfer=self.maximum_daily_transfer,
            suspicious_balance_ratio=self.suspicious_balance_ratio,
            rapid_transfer_window_minutes=self.rapid_transfer_window_minutes,
            rapid_transfer_count=self.rapid_transfer_count,
        )

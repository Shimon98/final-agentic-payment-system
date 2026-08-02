"""Tests for immutable Pydantic Settings v2 configuration."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_payments.domain import TransferPolicy
from agentic_payments.infrastructure import Settings


def test_default_rule_based_settings() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.llm_provider == "rule_based"
    assert settings.enable_llm_router is False
    assert settings.state_file == Path("data/payment_state.json")
    assert settings.maximum_single_transfer == Decimal("5000.00")


def test_dotenv_loading_and_blank_optional_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=test\nLLM_MODEL=  model-one  \nLLM_API_KEY=\nLLM_BASE_URL=   \n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_env == "test"
    assert settings.llm_model == "model-one"
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None


def test_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")

    assert Settings(_env_file=env_file).app_env == "production"


def test_invalid_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(llm_provider="invalid", _env_file=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"enable_llm_router": True}, "rule_based"),
        (
            {"enable_llm_router": True, "llm_provider": "openai"},
            "llm_model",
        ),
        (
            {
                "enable_llm_router": True,
                "llm_provider": "openai",
                "llm_model": "model",
            },
            "llm_api_key",
        ),
        (
            {
                "enable_llm_router": True,
                "llm_provider": "gemini",
                "llm_model": "model",
            },
            "llm_api_key",
        ),
        (
            {
                "enable_llm_router": True,
                "llm_provider": "openai_compatible",
                "llm_model": "model",
            },
            "llm_base_url",
        ),
    ],
)
def test_llm_enabled_provider_requirements(
    values: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**values, _env_file=None)


def test_valid_llm_settings_mask_secret() -> None:
    secret = "top-secret-value"
    settings = Settings(
        enable_llm_router=True,
        llm_provider="openai",
        llm_model="model",
        llm_api_key=secret,
        _env_file=None,
    )

    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == secret
    assert secret not in repr(settings)


def test_state_and_audit_paths_must_differ() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        Settings(state_file=Path("same.json"), audit_file=Path("same.json"), _env_file=None)


@pytest.mark.parametrize("field_name", ["state_file", "audit_file"])
def test_existing_directory_is_not_a_file(
    field_name: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match=field_name):
        Settings(**{field_name: tmp_path}, _env_file=None)


def test_settings_construction_does_not_create_parent_directories(tmp_path: Path) -> None:
    parent = tmp_path / "not-created"
    Settings(
        state_file=parent / "state.json",
        audit_file=parent / "audit.jsonl",
        _env_file=None,
    )
    assert not parent.exists()


def test_build_transfer_policy_returns_valid_immutable_policy() -> None:
    settings = Settings(_env_file=None)
    policy = settings.build_transfer_policy()

    assert isinstance(policy, TransferPolicy)
    assert policy.maximum_daily_transfer == Decimal("10000.00")
    with pytest.raises((AttributeError, TypeError)):
        policy.maximum_daily_transfer = Decimal("1.00")  # type: ignore[misc]


@pytest.mark.parametrize(
    "values",
    [
        {"maximum_single_transfer": Decimal("0.00")},
        {"maximum_single_transfer": Decimal("1.001")},
        {"maximum_daily_transfer": Decimal("4999.99")},
        {"maximum_daily_transfer": Decimal("NaN")},
        {"suspicious_balance_ratio": Decimal("0")},
        {"suspicious_balance_ratio": Decimal("1.01")},
    ],
)
def test_invalid_monetary_limits(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**values, _env_file=None)


@pytest.mark.parametrize(
    "field_name",
    [
        "maximum_single_transfer",
        "maximum_daily_transfer",
        "suspicious_balance_ratio",
    ],
)
def test_float_decimal_configuration_is_rejected(field_name: str) -> None:
    with pytest.raises(ValidationError, match="must not originate"):
        Settings(**{field_name: 0.5}, _env_file=None)


@pytest.mark.parametrize("value", [0.0, 1.0, "0.5"])
def test_confidence_boundaries_are_valid(value: object) -> None:
    assert Settings(
        router_confidence_threshold=value, _env_file=None
    ).router_confidence_threshold == (float(value))


@pytest.mark.parametrize("value", [True, False, -0.1, 1.1])
def test_invalid_confidence_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(router_confidence_threshold=value, _env_file=None)


def test_settings_are_frozen() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(ValidationError):
        settings.app_env = "test"  # type: ignore[misc]

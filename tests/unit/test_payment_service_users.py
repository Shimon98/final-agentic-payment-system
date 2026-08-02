"""User-creation tests for PaymentDomainService."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from conftest import DeterministicIdGenerator

from agentic_payments.domain import (
    DuplicatePhoneNumberError,
    IdempotencyConflictError,
    InvalidInitialBalanceError,
    UserAlreadyExistsError,
)


@pytest.mark.asyncio
async def test_create_valid_user_and_wallet(payment_harness_factory: Any) -> None:
    harness = payment_harness_factory()

    user = await harness.service.create_user(
        name="Alice",
        phone_number="0501234567",
        initial_balance=Decimal("100.00"),
        idempotency_key="IDEMP-CREATE",
        correlation_id="CORR-CREATE",
    )
    state = harness.manager.current_state

    assert user.user_id == "USR-001"
    assert state.users[user.user_id] == user
    assert state.wallets[user.user_id].balance == Decimal("100.00")
    assert state.wallets[user.user_id].version == 0


@pytest.mark.asyncio
async def test_zero_initial_balance_is_valid(payment_harness_factory: Any) -> None:
    harness = payment_harness_factory()

    user = await harness.service.create_user(
        name="Zero",
        phone_number="0500000001",
        initial_balance=Decimal("0"),
        idempotency_key="IDEMP-ZERO",
        correlation_id="CORR-ZERO",
    )

    assert harness.manager.current_state.wallets[user.user_id].balance == Decimal("0")


@pytest.mark.asyncio
async def test_negative_initial_balance_is_rejected(payment_harness_factory: Any) -> None:
    harness = payment_harness_factory()

    with pytest.raises(InvalidInitialBalanceError):
        await harness.service.create_user(
            name="Negative",
            phone_number="0500000002",
            initial_balance=Decimal("-0.01"),
            idempotency_key="IDEMP-NEGATIVE",
            correlation_id="CORR-NEGATIVE",
        )

    assert harness.repository.save_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_phone", "normalized"),
    [
        ("+972-50-123-4567", "972501234567"),
        ("050 123 4567", "0501234567"),
        ("(050) 123-4567", "0501234567"),
    ],
)
async def test_phone_formats_are_normalized(
    payment_harness_factory: Any,
    raw_phone: str,
    normalized: str,
) -> None:
    harness = payment_harness_factory()

    user = await harness.service.create_user(
        name="Normalized",
        phone_number=raw_phone,
        initial_balance=Decimal("1.00"),
        idempotency_key="IDEMP-PHONE",
        correlation_id="CORR-PHONE",
    )

    assert user.phone_number == normalized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phone",
    ["050ABC4567", "++972501234567", "050.123.4567", "123456", "1" * 16],
)
async def test_invalid_phone_characters_or_lengths_are_rejected(
    payment_harness_factory: Any,
    phone: str,
) -> None:
    harness = payment_harness_factory()

    with pytest.raises(ValueError, match="phone_number"):
        await harness.service.create_user(
            name="Invalid",
            phone_number=phone,
            initial_balance=Decimal("1.00"),
            idempotency_key="IDEMP-PHONE",
            correlation_id="CORR-PHONE",
        )


@pytest.mark.asyncio
async def test_duplicate_normalized_phone_is_rejected(payment_harness_factory: Any) -> None:
    harness = payment_harness_factory()
    await harness.service.create_user(
        name="First",
        phone_number="050-123-4567",
        initial_balance=Decimal("1.00"),
        idempotency_key="IDEMP-FIRST",
        correlation_id="CORR-FIRST",
    )

    with pytest.raises(DuplicatePhoneNumberError):
        await harness.service.create_user(
            name="Second",
            phone_number="(050) 123 4567",
            initial_balance=Decimal("1.00"),
            idempotency_key="IDEMP-SECOND",
            correlation_id="CORR-SECOND",
        )

    assert len(harness.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_generated_user_id_collision_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"USR-EXISTING": Decimal("10.00")})
    ids = DeterministicIdGenerator(user_ids=["USR-EXISTING"])
    harness = payment_harness_factory(initial_state=state, ids=ids)

    with pytest.raises(UserAlreadyExistsError):
        await harness.service.create_user(
            name="Collision",
            phone_number="0509999999",
            initial_balance=Decimal("1.00"),
            idempotency_key="IDEMP-COLLISION",
            correlation_id="CORR-COLLISION",
        )

    assert harness.repository.save_calls == 0


@pytest.mark.asyncio
async def test_create_user_audit_masks_phone(payment_harness_factory: Any) -> None:
    harness = payment_harness_factory()
    user = await harness.service.create_user(
        name="Masked",
        phone_number="+972-50-123-4567",
        initial_balance=Decimal("5.00"),
        idempotency_key="IDEMP-MASK",
        correlation_id="CORR-MASK",
    )

    event = next(iter(harness.manager.current_state.pending_audit_events.values()))

    assert event.action == "createUser"
    assert event.details["phone_last4"] == "4567"
    assert user.phone_number not in event.details.values()
    assert "phone_number" not in event.details


@pytest.mark.asyncio
async def test_user_creation_idempotent_retry_returns_original_without_save(
    payment_harness_factory: Any,
) -> None:
    harness = payment_harness_factory()
    arguments = {
        "name": "Retry",
        "phone_number": "0501112222",
        "initial_balance": Decimal("50.00"),
        "idempotency_key": "IDEMP-RETRY",
        "correlation_id": "CORR-RETRY",
    }

    first = await harness.service.create_user(**arguments)
    second = await harness.service.create_user(**arguments)

    assert second == first
    assert harness.repository.save_calls == 1
    assert harness.ids.user_calls == 1
    assert harness.ids.audit_event_calls == 1
    assert len(harness.manager.current_state.users) == 1


@pytest.mark.asyncio
async def test_same_user_key_with_changed_parameters_conflicts(
    payment_harness_factory: Any,
) -> None:
    harness = payment_harness_factory()
    await harness.service.create_user(
        name="Original",
        phone_number="0501112222",
        initial_balance=Decimal("50.00"),
        idempotency_key="IDEMP-CONFLICT",
        correlation_id="CORR-ONE",
    )

    with pytest.raises(IdempotencyConflictError):
        await harness.service.create_user(
            name="Changed",
            phone_number="0501112222",
            initial_balance=Decimal("50.00"),
            idempotency_key="IDEMP-CONFLICT",
            correlation_id="CORR-TWO",
        )

    assert harness.repository.save_calls == 1

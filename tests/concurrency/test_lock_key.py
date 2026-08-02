"""Tests for exact lock scopes and deterministic lock-key ordering."""

from __future__ import annotations

import pytest

from agentic_payments.infrastructure.concurrency import LockKey, LockScope


def test_lock_scope_numeric_order_is_exact() -> None:
    assert [(scope.name, scope.value) for scope in LockScope] == [
        ("IDEMPOTENCY", 10),
        ("USER_REGISTRY", 20),
        ("PAYMENT_REQUEST", 30),
        ("TRANSACTION", 40),
        ("WALLET", 50),
    ]


def test_valid_lock_key_preserves_resource_id() -> None:
    key = LockKey(LockScope.WALLET, "User-A")

    assert key.scope is LockScope.WALLET
    assert key.resource_id == "User-A"


@pytest.mark.parametrize("resource_id", ["", " ", "\t", "\n"])
def test_empty_or_whitespace_resource_id_is_rejected(resource_id: str) -> None:
    with pytest.raises(ValueError, match="non-empty stripped"):
        LockKey(LockScope.WALLET, resource_id)


@pytest.mark.parametrize("resource_id", [" wallet", "wallet ", " wallet "])
def test_resource_id_must_already_be_stripped(resource_id: str) -> None:
    with pytest.raises(ValueError, match="non-empty stripped"):
        LockKey(LockScope.WALLET, resource_id)


@pytest.mark.parametrize("scope", [10, True, False])
def test_plain_integer_and_bool_scopes_are_rejected(scope: object) -> None:
    with pytest.raises(TypeError, match="LockScope"):
        LockKey(scope, "resource")  # type: ignore[arg-type]


def test_non_string_resource_id_is_rejected() -> None:
    with pytest.raises(TypeError, match="string"):
        LockKey(LockScope.WALLET, 7)  # type: ignore[arg-type]


def test_sorting_uses_scope_then_exact_resource_id() -> None:
    keys = [
        LockKey(LockScope.WALLET, "B"),
        LockKey(LockScope.IDEMPOTENCY, "Z"),
        LockKey(LockScope.WALLET, "A"),
        LockKey(LockScope.TRANSACTION, "A"),
    ]

    assert sorted(keys) == [
        LockKey(LockScope.IDEMPOTENCY, "Z"),
        LockKey(LockScope.TRANSACTION, "A"),
        LockKey(LockScope.WALLET, "A"),
        LockKey(LockScope.WALLET, "B"),
    ]

"""Shared deterministic test fixtures introduced with their owning phases."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.application.payment_domain_service import PaymentDomainService
from agentic_payments.domain import TransferPolicy, User, Wallet
from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    PaymentTransactionManager,
)

FIXED_TIME = datetime(2026, 4, 5, 6, 7, tzinfo=UTC)


def pytest_configure(config: pytest.Config) -> None:
    """Collect same-named unit and concurrency modules by their full paths."""

    config.option.importmode = "importlib"


class FixedClock:
    """Return a deterministic timezone-aware timestamp."""

    def __init__(self, value: datetime = FIXED_TIME) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class DeterministicIdGenerator:
    """Return configured IDs or deterministic sequential defaults."""

    def __init__(
        self,
        *,
        user_ids: Sequence[str] = (),
        transaction_ids: Sequence[str] = (),
        payment_request_ids: Sequence[str] = (),
        audit_event_ids: Sequence[str] = (),
    ) -> None:
        self._user_ids = deque(user_ids)
        self._transaction_ids = deque(transaction_ids)
        self._payment_request_ids = deque(payment_request_ids)
        self._audit_event_ids = deque(audit_event_ids)
        self.user_calls = 0
        self.transaction_calls = 0
        self.payment_request_calls = 0
        self.audit_event_calls = 0

    def new_user_id(self) -> str:
        self.user_calls += 1
        if self._user_ids:
            return self._user_ids.popleft()
        return f"USR-{self.user_calls:03d}"

    def new_transaction_id(self) -> str:
        self.transaction_calls += 1
        if self._transaction_ids:
            return self._transaction_ids.popleft()
        return f"TXN-{self.transaction_calls:03d}"

    def new_payment_request_id(self) -> str:
        self.payment_request_calls += 1
        if self._payment_request_ids:
            return self._payment_request_ids.popleft()
        return f"REQ-{self.payment_request_calls:03d}"

    def new_audit_event_id(self) -> str:
        self.audit_event_calls += 1
        if self._audit_event_ids:
            return self._audit_event_ids.popleft()
        return f"AUD-{self.audit_event_calls:03d}"

    def new_correlation_id(self) -> str:
        return "CORR-GENERATED"


class InMemoryStateRepository:
    """Store defensive state clones and support one configured failure."""

    def __init__(self) -> None:
        self.save_calls = 0
        self.saved: list[ApplicationState] = []
        self.fail_next = False

    async def load(self) -> ApplicationState:
        if not self.saved:
            return ApplicationState()
        return self.saved[-1].clone()

    async def save_atomic(self, state: ApplicationState) -> None:
        self.save_calls += 1
        if self.fail_next:
            self.fail_next = False
            raise OSError("configured save failure")
        self.saved.append(state.clone())

    async def reset(self) -> None:
        self.saved.clear()


@dataclass(slots=True)
class PaymentHarness:
    """Collect one deterministic service and its observable test fakes."""

    service: PaymentDomainService
    manager: PaymentTransactionManager
    repository: InMemoryStateRepository
    ids: DeterministicIdGenerator
    clock: FixedClock
    locks: AsyncResourceLockManager


def build_state(
    balances: Mapping[str, Decimal],
    *,
    created_at: datetime = FIXED_TIME,
) -> ApplicationState:
    """Build a valid deterministic state with one wallet per user."""

    state = ApplicationState()
    for index, (user_id, balance) in enumerate(balances.items(), start=1):
        user = User(
            user_id=user_id,
            name=f"User {index}",
            phone_number=f"050000{index:04d}",
            created_at=created_at,
        )
        state.users[user_id] = user
        state.wallets[user_id] = Wallet(
            user_id=user_id,
            balance=balance,
            currency="ILS",
            version=0,
            updated_at=created_at,
        )
    state.validate_invariants()
    return state


def build_harness(
    *,
    initial_state: ApplicationState | None = None,
    repository: InMemoryStateRepository | None = None,
    ids: DeterministicIdGenerator | None = None,
    clock: FixedClock | None = None,
    transfer_policy: TransferPolicy | None = None,
) -> PaymentHarness:
    """Build a service wired to real locks and deterministic test fakes."""

    chosen_repository = repository or InMemoryStateRepository()
    chosen_ids = ids or DeterministicIdGenerator()
    chosen_clock = clock or FixedClock()
    chosen_policy = transfer_policy or TransferPolicy(
        maximum_single_transfer=Decimal("10000.00"),
        maximum_daily_transfer=Decimal("20000.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )
    lock_manager = AsyncResourceLockManager()
    manager = PaymentTransactionManager(
        initial_state=initial_state or ApplicationState(),
        state_repository=chosen_repository,
    )
    service = PaymentDomainService(
        transaction_manager=manager,
        lock_manager=lock_manager,
        transfer_policy=chosen_policy,
        clock=chosen_clock,
        id_generator=chosen_ids,
    )
    return PaymentHarness(
        service=service,
        manager=manager,
        repository=chosen_repository,
        ids=chosen_ids,
        clock=chosen_clock,
        locks=lock_manager,
    )


@pytest.fixture
def payment_harness_factory() -> Any:
    """Return the deterministic PaymentHarness factory."""

    return build_harness


@pytest.fixture
def application_state_factory() -> Any:
    """Return the deterministic valid-state factory."""

    return build_state

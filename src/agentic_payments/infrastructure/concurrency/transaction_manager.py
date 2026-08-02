"""Serialized copy-on-write payment transactions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentic_payments.application import ApplicationState, StateRepository
from agentic_payments.infrastructure.concurrency.unit_of_work import PaymentUnitOfWork


class PaymentTransactionManager:
    """Serialize whole-state transactions and atomically publish saved clones."""

    def __init__(
        self,
        *,
        initial_state: ApplicationState,
        state_repository: StateRepository,
    ) -> None:
        if not isinstance(initial_state, ApplicationState):
            raise TypeError("initial_state must be an ApplicationState")
        initial_state.validate_invariants()
        self._state = initial_state.clone()
        self._state_repository = state_repository
        self._transaction_gate = asyncio.Lock()

    @property
    def current_state(self) -> ApplicationState:
        """Return an independent clone of the latest committed state."""

        return self._state.clone()

    async def _commit(self, working_state: ApplicationState) -> None:
        working_state.validate_invariants()
        repository_state = working_state.clone()
        committed_state = working_state.clone()
        await self._state_repository.save_atomic(repository_state)
        self._state = committed_state

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PaymentUnitOfWork]:
        """Yield one serialized Unit of Work that requires explicit commit."""

        await self._transaction_gate.acquire()
        unit = PaymentUnitOfWork._create(
            working_state=self._state.clone(),
            commit_callback=self._commit,
        )
        try:
            try:
                yield unit
            except asyncio.CancelledError:
                await unit.rollback()
                raise
            except BaseException:
                await unit.rollback()
                raise
            else:
                await unit.rollback()
        finally:
            self._transaction_gate.release()

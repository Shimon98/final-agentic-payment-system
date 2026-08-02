"""Cancellation-safe, deterministically ordered asynchronous resource locks."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass

from agentic_payments.infrastructure.concurrency.lock_key import LockKey


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    references: int = 0


class AsyncResourceLockManager:
    """Coordinate named resource locks within one event loop."""

    def __init__(self) -> None:
        self._locks: dict[LockKey, _LockEntry] = {}
        self._registry_lock = asyncio.Lock()

    async def _reserve_entries(self, keys: tuple[LockKey, ...]) -> tuple[_LockEntry, ...]:
        entries: list[_LockEntry] = []
        async with self._registry_lock:
            for key in keys:
                entry = self._locks.get(key)
                if entry is None:
                    entry = _LockEntry(asyncio.Lock())
                    self._locks[key] = entry
                entry.references += 1
                entries.append(entry)
        return tuple(entries)

    async def _release_references(
        self,
        keys: tuple[LockKey, ...],
        entries: tuple[_LockEntry, ...],
    ) -> None:
        async with self._registry_lock:
            for key, entry in zip(keys, entries, strict=True):
                entry.references -= 1
                if entry.references == 0 and not entry.lock.locked():
                    self._locks.pop(key, None)

    @asynccontextmanager
    async def acquire(self, key: LockKey) -> AsyncIterator[None]:
        """Acquire one resource lock using the shared multi-lock safety path."""

        async with self.acquire_many((key,)):
            yield

    @asynccontextmanager
    async def acquire_many(self, keys: Collection[LockKey]) -> AsyncIterator[None]:
        """Acquire unique resource locks in natural order and release in reverse."""

        supplied = tuple(keys)
        if not all(isinstance(key, LockKey) for key in supplied):
            raise TypeError("every resource lock key must be a LockKey")
        ordered = tuple(sorted(set(supplied)))
        entries = await self._reserve_entries(ordered)
        acquired: list[_LockEntry] = []
        try:
            for entry in entries:
                await entry.lock.acquire()
                acquired.append(entry)
            yield
        finally:
            for entry in reversed(acquired):
                entry.lock.release()
            await self._release_references(ordered, entries)

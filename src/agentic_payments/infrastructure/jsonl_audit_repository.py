"""Idempotent, ordered JSON Lines persistence for immutable audit events."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure.exceptions import (
    AuditEventConflictError,
    AuditLogCorruptionError,
    AuditPersistenceError,
)


async def _wait_for_thread_append(task: asyncio.Task[None]) -> bool:
    """Wait through caller cancellation and report whether it must be re-requested."""

    cancellation_requested = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancellation_requested = True
    task.result()
    return cancellation_requested


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty stripped string")
    return value


class JsonLinesAuditRepository:
    """Append complete durable audit lines and maintain an idempotency index."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("path must be a Path")
        self._path = path
        self._io_lock = asyncio.Lock()
        self._initialization_lock = asyncio.Lock()
        self._initialized = False
        self._events_by_id: dict[str, AuditEvent] = {}
        self._ordered_event_ids: list[str] = []

    def _context(self, category: str, **extra: object) -> dict[str, object]:
        return {"path": str(self._path), "category": category, **extra}

    def _read_sync(self) -> str:
        return self._path.read_text(encoding="utf-8")

    def _append_sync(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_dir():
            raise IsADirectoryError(self._path)
        with self._path.open("a", encoding="utf-8", newline="") as audit_file:
            audit_file.write(line)
            audit_file.flush()
            os.fsync(audit_file.fileno())

    def _parse_payload(self, payload: str) -> tuple[dict[str, AuditEvent], list[str]]:
        events: dict[str, AuditEvent] = {}
        ordered_ids: list[str] = []
        for line_number, line in enumerate(payload.splitlines(), start=1):
            if line == "":
                continue
            try:
                raw_event: Any = json.loads(line)
                if not isinstance(raw_event, dict):
                    raise TypeError("audit JSON root must be an object")
                event = AuditEvent.from_dict(raw_event)
            except Exception as error:
                raise AuditLogCorruptionError(
                    "Audit log contains a malformed event",
                    context=self._context("malformed_line", line_number=line_number),
                ) from error
            existing = events.get(event.event_id)
            if existing is None:
                events[event.event_id] = event
                ordered_ids.append(event.event_id)
            elif existing != event:
                raise AuditEventConflictError(
                    "Audit log contains conflicting event content",
                    context=self._context(
                        "event_id_conflict",
                        line_number=line_number,
                        event_id=event.event_id,
                    ),
                )
        return events, ordered_ids

    async def initialize(self) -> None:
        """Build the in-memory index once without modifying the audit file."""

        if self._initialized:
            return
        async with self._initialization_lock:
            if self._initialized:
                return
            async with self._io_lock:
                if self._path.is_dir():
                    raise AuditPersistenceError(
                        "Audit log path must refer to a file",
                        context=self._context("path_is_directory"),
                    )
                if not self._path.exists():
                    self._events_by_id = {}
                    self._ordered_event_ids = []
                    self._initialized = True
                    return
                try:
                    payload = await asyncio.to_thread(self._read_sync)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    raise AuditPersistenceError(
                        "Unable to read audit log",
                        context=self._context("io_error"),
                    ) from error
                events, ordered_ids = self._parse_payload(payload)
                self._events_by_id = events
                self._ordered_event_ids = ordered_ids
                self._initialized = True

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    @staticmethod
    def _rerequest_cancellation() -> None:
        current_task = asyncio.current_task()
        if current_task is not None:
            current_task.cancel()

    async def append(self, event: AuditEvent) -> None:
        """Durably append one new logical event or accept an identical retry."""

        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        await self._ensure_initialized()
        cancellation_requested = False
        async with self._io_lock:
            existing = self._events_by_id.get(event.event_id)
            if existing is not None:
                if existing == event:
                    return
                raise AuditEventConflictError(
                    "Audit event ID conflicts with existing content",
                    context=self._context("event_id_conflict", event_id=event.event_id),
                )
            line = (
                json.dumps(
                    event.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            append_task = asyncio.create_task(asyncio.to_thread(self._append_sync, line))
            try:
                cancellation_requested = await _wait_for_thread_append(append_task)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise AuditPersistenceError(
                    "Unable to append audit event",
                    context=self._context("io_error", event_id=event.event_id),
                ) from error
            self._events_by_id[event.event_id] = event
            self._ordered_event_ids.append(event.event_id)
        if cancellation_requested:
            self._rerequest_cancellation()

    async def list_all(self) -> list[AuditEvent]:
        """Return all unique logical events in original file order."""

        await self._ensure_initialized()
        async with self._io_lock:
            return [self._events_by_id[event_id] for event_id in self._ordered_event_ids]

    async def find_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        """Return matching events in original file order."""

        validated_id = _validate_identifier(correlation_id, "correlation_id")
        await self._ensure_initialized()
        async with self._io_lock:
            return [
                self._events_by_id[event_id]
                for event_id in self._ordered_event_ids
                if self._events_by_id[event_id].correlation_id == validated_id
            ]

    def contains_event_id(self, event_id: str) -> bool:
        """Consult only the initialized in-memory event index."""

        validated_id = _validate_identifier(event_id, "event_id")
        if not self._initialized:
            raise RuntimeError("audit repository must be initialized before contains_event_id")
        return validated_id in self._events_by_id

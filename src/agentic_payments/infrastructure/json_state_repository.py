"""Atomic UTF-8 JSON persistence for complete application state."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from agentic_payments.application import ApplicationState
from agentic_payments.infrastructure.exceptions import StatePersistenceError


async def _wait_for_thread_write(task: asyncio.Task[None]) -> bool:
    """Wait through caller cancellation and report whether it must be re-requested."""

    cancellation_requested = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancellation_requested = True
    task.result()
    return cancellation_requested


class JsonStateRepository:
    """Persist one complete validated state using same-directory replacement."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("path must be a Path")
        self._path = path
        self._operation_lock = asyncio.Lock()

    def _context(self, category: str) -> dict[str, str]:
        return {"path": str(self._path), "category": category}

    def _read_sync(self) -> str:
        return self._path.read_text(encoding="utf-8")

    @staticmethod
    def _serialize(state: ApplicationState) -> str:
        return (
            json.dumps(
                state.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )

    def _fsync_parent_best_effort(self) -> None:
        descriptor: int | None = None
        try:
            descriptor = os.open(self._path.parent, os.O_RDONLY)
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)

    def _write_sync(self, payload: str) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_dir():
            raise IsADirectoryError(self._path)
        temporary_path = self._path.with_name(f"{self._path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="") as temporary_file:
                temporary_file.write(payload)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self._path)
            self._fsync_parent_best_effort()
        except BaseException:
            try:
                if temporary_path.exists() and not temporary_path.is_dir():
                    temporary_path.unlink()
            except OSError:
                pass
            raise

    async def load(self) -> ApplicationState:
        """Load and independently reconstruct the complete state."""

        async with self._operation_lock:
            if self._path.is_dir():
                raise StatePersistenceError(
                    "Application state path must refer to a file",
                    context=self._context("path_is_directory"),
                )
            if not self._path.exists():
                state = ApplicationState()
                state.validate_invariants()
                return state
            try:
                payload = await asyncio.to_thread(self._read_sync)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise StatePersistenceError(
                    "Unable to read application state",
                    context=self._context("io_error"),
                ) from error
            if not payload.strip():
                raise StatePersistenceError(
                    "Existing application state file is empty",
                    context=self._context("empty_file"),
                )
            try:
                raw_data: Any = json.loads(payload)
            except json.JSONDecodeError as error:
                raise StatePersistenceError(
                    "Application state JSON is malformed",
                    context=self._context("malformed_json"),
                ) from error
            if not isinstance(raw_data, dict):
                root_error = TypeError("application state JSON root must be an object")
                raise StatePersistenceError(
                    "Application state JSON root must be an object",
                    context=self._context("invalid_root"),
                ) from root_error
            try:
                state = ApplicationState.from_dict(raw_data)
                state.validate_invariants()
                return state.clone()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise StatePersistenceError(
                    "Application state data is invalid",
                    context=self._context("invalid_state"),
                ) from error

    async def _save_locked(self, state: ApplicationState) -> bool:
        try:
            snapshot = state.clone()
            snapshot.validate_invariants()
            payload = self._serialize(snapshot)
        except Exception as error:
            raise StatePersistenceError(
                "Application state cannot be serialized",
                context=self._context("invalid_state"),
            ) from error

        write_task = asyncio.create_task(asyncio.to_thread(self._write_sync, payload))
        try:
            return await _wait_for_thread_write(write_task)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise StatePersistenceError(
                "Unable to persist application state",
                context=self._context("io_error"),
            ) from error

    @staticmethod
    def _rerequest_cancellation() -> None:
        current_task = asyncio.current_task()
        if current_task is not None:
            current_task.cancel()

    async def save_atomic(self, state: ApplicationState) -> None:
        """Validate a snapshot and atomically replace the persisted state."""

        if not isinstance(state, ApplicationState):
            raise TypeError("state must be an ApplicationState")
        cancellation_requested = False
        async with self._operation_lock:
            cancellation_requested = await self._save_locked(state)
        if cancellation_requested:
            self._rerequest_cancellation()

    async def reset(self) -> None:
        """Atomically replace only application state with a valid empty state."""

        cancellation_requested = False
        async with self._operation_lock:
            cancellation_requested = await self._save_locked(ApplicationState())
        if cancellation_requested:
            self._rerequest_cancellation()

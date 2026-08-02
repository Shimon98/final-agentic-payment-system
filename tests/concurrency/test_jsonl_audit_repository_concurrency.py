"""Concurrent append and initialization tests for the JSONL repository."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import AuditEventConflictError, JsonLinesAuditRepository

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _event(event_id: str, *, label: str = "same") -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id="COR-CONCURRENT",
        action="TEST",
        status="SUCCESS",
        occurred_at=NOW,
        actor="system",
        details={"label": label},
    )


@pytest.mark.asyncio
async def test_concurrent_appends_produce_complete_valid_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)
    events = [_event(f"AUD-{index:03d}") for index in range(50)]

    await asyncio.wait_for(
        asyncio.gather(*(repository.append(event) for event in events)),
        timeout=5.0,
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    parsed_ids = [json.loads(line)["event_id"] for line in lines]
    assert len(lines) == 50
    assert len(set(parsed_ids)) == 50
    assert len(await repository.list_all()) == 50


@pytest.mark.asyncio
async def test_concurrent_identical_appends_write_one_line(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)
    event = _event("AUD-SAME")

    await asyncio.wait_for(
        asyncio.gather(*(repository.append(event) for _ in range(20))),
        timeout=3.0,
    )

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert await repository.list_all() == [event]


@pytest.mark.asyncio
async def test_concurrent_conflicting_appends_have_one_success_one_conflict(
    tmp_path: Path,
) -> None:
    repository = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    results = await asyncio.wait_for(
        asyncio.gather(
            repository.append(_event("AUD-1", label="A")),
            repository.append(_event("AUD-1", label="B")),
            return_exceptions=True,
        ),
        timeout=2.0,
    )

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, AuditEventConflictError) for result in results) == 1
    assert len(await repository.list_all()) == 1


@pytest.mark.asyncio
async def test_initialize_and_append_race_is_safe(tmp_path: Path) -> None:
    repository = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    event = _event("AUD-1")

    await asyncio.wait_for(
        asyncio.gather(repository.initialize(), repository.append(event)),
        timeout=2.0,
    )

    assert repository.contains_event_id("AUD-1")
    assert await repository.list_all() == [event]

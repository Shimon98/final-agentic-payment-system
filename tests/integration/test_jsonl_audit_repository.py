"""Filesystem integration tests for idempotent JSONL audit persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.application import AuditRepository
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import (
    AuditEventConflictError,
    AuditLogCorruptionError,
    AuditPersistenceError,
    JsonLinesAuditRepository,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    correlation_id: str = "COR-1",
    label: str = "שלום",
) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id=correlation_id,
        action="TEST",
        status="SUCCESS",
        occurred_at=NOW,
        actor="system",
        details={"label": label},
    )


@pytest.mark.asyncio
async def test_missing_file_initializes_empty_without_creation(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)

    assert isinstance(repository, AuditRepository)
    assert await repository.list_all() == []
    assert not path.exists()


def test_contains_requires_initialization_and_valid_identifier(tmp_path: Path) -> None:
    repository = JsonLinesAuditRepository(tmp_path / "audit.jsonl")

    with pytest.raises(RuntimeError, match="initialized"):
        repository.contains_event_id("AUD-1")
    with pytest.raises(ValueError):
        repository.contains_event_id(" ")


@pytest.mark.asyncio
async def test_append_creates_one_complete_utf8_line_and_updates_index(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)
    event = _event("AUD-1")

    await repository.append(event)
    payload = path.read_text(encoding="utf-8")

    assert payload.endswith("\n")
    assert payload.count("\n") == 1
    assert "\\u" not in payload
    assert json.loads(payload) == event.to_dict()
    assert repository.contains_event_id("AUD-1")


@pytest.mark.asyncio
async def test_list_and_correlation_search_preserve_order_and_return_new_lists(
    tmp_path: Path,
) -> None:
    repository = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    events = [
        _event("AUD-2", correlation_id="COR-X"),
        _event("AUD-1", correlation_id="COR-Y"),
        _event("AUD-3", correlation_id="COR-X"),
    ]
    for event in events:
        await repository.append(event)

    first = await repository.list_all()
    second = await repository.list_all()
    matches = await repository.find_by_correlation_id("COR-X")
    first.clear()

    assert second == events
    assert matches == [events[0], events[2]]
    assert await repository.list_all() == events
    assert first is not second


@pytest.mark.asyncio
async def test_identical_duplicate_append_is_noop_but_conflict_raises(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)
    original = _event("AUD-1", label="original")
    await repository.append(original)
    first_payload = path.read_bytes()

    await repository.append(original)
    with pytest.raises(AuditEventConflictError):
        await repository.append(_event("AUD-1", label="different"))

    assert path.read_bytes() == first_payload
    assert await repository.list_all() == [original]


@pytest.mark.asyncio
async def test_identical_file_duplicates_form_one_logical_event(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    line = json.dumps(_event("AUD-1").to_dict(), sort_keys=True)
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    repository = JsonLinesAuditRepository(path)

    assert await repository.list_all() == [_event("AUD-1")]


@pytest.mark.asyncio
async def test_conflicting_file_duplicates_fail(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    first = json.dumps(_event("AUD-1", label="one").to_dict())
    second = json.dumps(_event("AUD-1", label="two").to_dict())
    path.write_text(f"{first}\n{second}\n", encoding="utf-8")

    with pytest.raises(AuditEventConflictError) as caught:
        await JsonLinesAuditRepository(path).initialize()

    assert caught.value.context["line_number"] == 2


@pytest.mark.asyncio
async def test_completely_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    line = json.dumps(_event("AUD-1").to_dict())
    path.write_text(f"\n{line}\n\n", encoding="utf-8")

    assert await JsonLinesAuditRepository(path).list_all() == [_event("AUD-1")]


@pytest.mark.asyncio
async def test_whitespace_non_json_line_is_corruption_with_safe_line_number(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    malformed = "   sensitive malformed content"
    path.write_text(f"\n{malformed}\n", encoding="utf-8")

    with pytest.raises(AuditLogCorruptionError) as caught:
        await JsonLinesAuditRepository(path).list_all()

    assert caught.value.context["line_number"] == 2
    assert caught.value.context["category"] == "malformed_line"
    assert malformed not in str(caught.value)


@pytest.mark.asyncio
async def test_failed_append_does_not_change_file_or_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)
    await repository.initialize()

    def fail_append(line: str) -> None:
        raise OSError("controlled append failure")

    monkeypatch.setattr(repository, "_append_sync", fail_append)

    with pytest.raises(AuditPersistenceError) as caught:
        await repository.append(_event("AUD-1"))

    assert not path.exists()
    assert not repository.contains_event_id("AUD-1")
    assert isinstance(caught.value.__cause__, OSError)


@pytest.mark.asyncio
async def test_directory_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AuditPersistenceError) as caught:
        await JsonLinesAuditRepository(tmp_path).initialize()

    assert caught.value.context["category"] == "path_is_directory"

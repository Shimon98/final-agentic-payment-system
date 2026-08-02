"""Filesystem integration tests for atomic application-state JSON persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import JsonStateRepository, StatePersistenceError

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _event(event_id: str, *, label: str = "בדיקה") -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id=f"COR-{event_id}",
        action="TEST",
        status="SUCCESS",
        occurred_at=NOW,
        actor="system",
        details={"label": label},
    )


@pytest.mark.asyncio
async def test_missing_file_returns_empty_without_creating_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    repository = JsonStateRepository(path)

    state = await repository.load()

    assert state.to_dict() == ApplicationState().to_dict()
    assert not path.exists()


@pytest.mark.asyncio
async def test_save_load_round_trip_is_deterministic_utf8_and_final_newline(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "state.json"
    repository = JsonStateRepository(path)
    state = ApplicationState(
        pending_audit_events={
            "AUD-B": _event("AUD-B", label="שלום"),
            "AUD-A": _event("AUD-A", label="עולם"),
        }
    )

    await repository.save_atomic(state)
    first_payload = path.read_text(encoding="utf-8")
    loaded = await repository.load()
    await repository.save_atomic(loaded)
    second_payload = path.read_text(encoding="utf-8")

    assert first_payload == second_payload
    assert first_payload.endswith("\n")
    assert "\\u" not in first_payload
    assert list(json.loads(first_payload)["pending_audit_events"]) == ["AUD-A", "AUD-B"]
    assert loaded.to_dict() == state.to_dict()


@pytest.mark.asyncio
async def test_save_uses_atomic_replacement_without_leaving_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    repository = JsonStateRepository(path)

    await repository.save_atomic(ApplicationState())

    assert path.is_file()
    assert not path.with_name("state.json.tmp").exists()


@pytest.mark.asyncio
async def test_previous_file_survives_replace_failure_and_temp_is_cleaned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    repository = JsonStateRepository(path)
    await repository.save_atomic(ApplicationState())
    original = path.read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("controlled replacement failure")

    monkeypatch.setattr(
        "agentic_payments.infrastructure.json_state_repository.os.replace", fail_replace
    )

    with pytest.raises(StatePersistenceError) as caught:
        await repository.save_atomic(
            ApplicationState(pending_audit_events={"AUD-1": _event("AUD-1")})
        )

    assert path.read_bytes() == original
    assert not path.with_name("state.json.tmp").exists()
    assert isinstance(caught.value.__cause__, OSError)
    assert "controlled replacement failure" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ("{broken", "malformed_json"),
        ("[]", "invalid_root"),
        ("   \n", "empty_file"),
        ('{"unexpected":true}', "invalid_state"),
    ],
)
async def test_corrupt_or_invalid_state_is_safely_wrapped(
    payload: str,
    category: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(StatePersistenceError) as caught:
        await JsonStateRepository(path).load()

    assert caught.value.context["category"] == category
    assert str(path) in caught.value.context["path"]
    assert payload not in str(caught.value)


@pytest.mark.asyncio
async def test_directory_path_is_rejected(tmp_path: Path) -> None:
    repository = JsonStateRepository(tmp_path)

    with pytest.raises(StatePersistenceError) as caught:
        await repository.load()

    assert caught.value.context["category"] == "path_is_directory"


@pytest.mark.asyncio
async def test_reset_atomically_saves_empty_state_without_touching_audit(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text("audit-sentinel\n", encoding="utf-8")
    repository = JsonStateRepository(state_path)
    await repository.save_atomic(ApplicationState(pending_audit_events={"AUD-1": _event("AUD-1")}))

    await repository.reset()

    assert (await repository.load()).to_dict() == ApplicationState().to_dict()
    assert audit_path.read_text(encoding="utf-8") == "audit-sentinel\n"


@pytest.mark.asyncio
async def test_saved_and_loaded_states_are_independent(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    repository = JsonStateRepository(path)
    supplied = ApplicationState(pending_audit_events={"AUD-1": _event("AUD-1")})

    await repository.save_atomic(supplied)
    supplied.pending_audit_events.clear()
    loaded = await repository.load()
    loaded.pending_audit_events.clear()

    assert "AUD-1" in (await repository.load()).pending_audit_events


@pytest.mark.asyncio
async def test_ordinary_read_error_is_chained_and_safely_wrapped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    repository = JsonStateRepository(path)

    def fail_read() -> str:
        raise OSError("sensitive raw operating-system detail")

    monkeypatch.setattr(repository, "_read_sync", fail_read)

    with pytest.raises(StatePersistenceError) as caught:
        await repository.load()

    assert isinstance(caught.value.__cause__, OSError)
    assert "sensitive raw" not in str(caught.value)

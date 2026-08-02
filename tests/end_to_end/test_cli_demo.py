"""Deterministic temporary CLI demo end to end."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import agentic_payments.presentation.cli as cli
from agentic_payments.bootstrap import ApplicationContainer


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.asyncio
async def test_demo_has_exact_result_and_removes_temporary_files(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real_build = cli.build_application
    built: list[ApplicationContainer] = []

    async def recording_build(settings: object = None) -> ApplicationContainer:
        container = await real_build(settings)  # type: ignore[arg-type]
        built.append(container)
        return container

    monkeypatch.setattr(cli, "build_application", recording_build)
    repository_data = Path.cwd() / "data"
    data_before = _tree_snapshot(repository_data)

    assert await cli.run_demo() == 0

    assert len(built) == 1
    container = built[0]
    state = container.snapshot()
    balances = {state.wallets[user_id].balance for user_id in state.users}
    assert balances == {Decimal("875.00"), Decimal("325.00")}
    assert len(state.transactions) == 1
    assert state.pending_audit_events == {}
    assert not container.settings.state_file.parent.exists()
    assert _tree_snapshot(repository_data) == data_before
    rendered = capsys.readouterr().out
    assert "Demo completed successfully." in rendered
    assert "0501234567" not in rendered
    assert "0509876543" not in rendered
    assert "Traceback" not in rendered

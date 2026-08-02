"""Exact argparse surface and event-loop ownership tests."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import agentic_payments.presentation.cli as cli
from agentic_payments.presentation.cli import build_parser


def test_default_command_is_interactive() -> None:
    arguments = build_parser().parse_args([])

    assert arguments.command == "interactive"
    assert arguments.env_file is None


@pytest.mark.parametrize("command", ["interactive", "demo", "status", "flush", "reset"])
def test_every_subcommand_is_supported(command: str) -> None:
    assert build_parser().parse_args([command]).command == command


def test_env_file_and_reset_confirmation_are_parsed(tmp_path: Path) -> None:
    env_file = tmp_path / "settings.env"
    arguments = build_parser().parse_args(["--env-file", str(env_file), "reset", "--yes"])

    assert arguments.env_file == env_file
    assert arguments.command == "reset"
    assert arguments.yes is True


def test_unknown_argument_fails() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["--unknown"])

    assert raised.value.code == 2


def test_parser_does_not_mutate_environment() -> None:
    before = dict(os.environ)

    build_parser().parse_args(["--env-file", "local.env", "status"])

    assert dict(os.environ) == before


def test_main_owns_exactly_one_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def finish(coroutine: object) -> int:
        coroutine.close()  # type: ignore[attr-defined]
        return 0

    run = Mock(side_effect=finish)
    monkeypatch.setattr(cli.asyncio, "run", run)

    assert cli.main(["status"]) == 0
    run.assert_called_once()


def test_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupt(coroutine: object) -> int:
        coroutine.close()  # type: ignore[attr-defined]
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", Mock(side_effect=interrupt))

    assert cli.main(["status"]) == 130
    assert "Interrupted safely." in capsys.readouterr().out

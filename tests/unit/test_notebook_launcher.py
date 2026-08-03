"""Safe repository discovery and JupyterLab launcher behavior."""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentic_payments.presentation import notebook_launcher


def _repository(tmp_path: Path, *, notebook: bool = True, source: bool = True) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    if source:
        (tmp_path / "src" / "agentic_payments" / "presentation").mkdir(parents=True)
    if notebook:
        (tmp_path / notebook_launcher.NOTEBOOK_NAME).write_text("{}", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / ".gitkeep").write_text("\n", encoding="utf-8")
    return tmp_path


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
    *,
    available: bool = True,
    runner: object | None = None,
) -> int:
    monkeypatch.setattr(sys, "argv", ["agentic-payments-notebook"])
    monkeypatch.setattr(notebook_launcher, "_repository_root", lambda: repository_root)
    monkeypatch.setattr(notebook_launcher, "_jupyterlab_available", lambda: available)
    if runner is not None:
        monkeypatch.setattr(subprocess, "run", runner)
    return notebook_launcher.main()


def test_repository_root_is_located_from_editable_source_tree(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    module_file = root / "src" / "agentic_payments" / "presentation" / "notebook_launcher.py"
    module_file.write_text("# test module\n", encoding="utf-8")

    assert notebook_launcher._find_repository_root(module_file) == root


def test_launcher_uses_current_python_repository_root_and_exact_notebook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    before = (root / "data" / ".gitkeep").read_bytes()
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        captured.update(command=command, cwd=cwd, check=check)
        return SimpleNamespace(returncode=0)

    assert _run_main(monkeypatch, root, runner=fake_run) == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command == [
        sys.executable,
        "-m",
        "jupyterlab",
        f"--notebook-dir={root}",
        notebook_launcher.NOTEBOOK_NAME,
    ]
    assert captured["cwd"] == root
    assert captured["check"] is False
    assert (root / "data" / ".gitkeep").read_bytes() == before


def test_launcher_source_does_not_access_dotenv_or_application_settings() -> None:
    source = inspect.getsource(notebook_launcher)

    assert ".env" not in source
    assert "dotenv" not in source
    assert "Settings" not in source
    assert "os.environ" not in source


@pytest.mark.parametrize(
    ("notebook", "source"),
    [
        (False, True),
        (True, False),
    ],
)
def test_missing_repository_prerequisite_returns_nonzero_without_launch(
    notebook: bool,
    source: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path, notebook=notebook, source=source)

    def forbidden_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JupyterLab must not be started")

    assert _run_main(monkeypatch, root, runner=forbidden_run) != 0


def test_missing_jupyterlab_returns_nonzero_without_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)

    def forbidden_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JupyterLab must not be started")

    assert (
        _run_main(
            monkeypatch,
            root,
            available=False,
            runner=forbidden_run,
        )
        != 0
    )


def test_keyboard_interrupt_is_handled_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)

    def interrupted(*_args: object, **_kwargs: object) -> object:
        raise KeyboardInterrupt

    assert _run_main(monkeypatch, root, runner=interrupted) == 130


def test_launcher_help_exits_without_starting_jupyterlab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["agentic-payments-notebook", "--help"])

    def forbidden_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JupyterLab must not be started for --help")

    monkeypatch.setattr(subprocess, "run", forbidden_run)
    with pytest.raises(SystemExit) as captured:
        notebook_launcher.main()
    assert captured.value.code == 0

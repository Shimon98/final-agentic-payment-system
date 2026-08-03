"""Launch the submitted notebook through this project's Python environment."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

NOTEBOOK_NAME = "final_agentic_payment_project.ipynb"
_SOURCE_PACKAGE = Path("src") / "agentic_payments"


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="agentic-payments-notebook",
        description="Open the submitted Agentic Payments notebook in JupyterLab.",
    )


def _find_repository_root(module_file: Path) -> Path | None:
    resolved = module_file.resolve()
    for candidate in resolved.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / _SOURCE_PACKAGE).is_dir():
            return candidate
    return None


def _repository_root() -> Path | None:
    return _find_repository_root(Path(__file__))


def _jupyterlab_available() -> bool:
    return importlib.util.find_spec("jupyterlab") is not None


def _launch_command(repository_root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "jupyterlab",
        f"--notebook-dir={repository_root}",
        NOTEBOOK_NAME,
    ]


def _safe_error(message: str) -> None:
    print(message, file=sys.stderr)


def main() -> int:
    """Validate the repository layout and open its exact notebook in JupyterLab."""

    _build_parser().parse_args()
    repository_root = _repository_root()
    if repository_root is None:
        _safe_error("The editable project repository root could not be located.")
        return 2
    notebook = repository_root / NOTEBOOK_NAME
    if not notebook.is_file():
        _safe_error("The submitted notebook is missing from the repository root.")
        return 2
    if not (repository_root / _SOURCE_PACKAGE).is_dir():
        _safe_error("The production source package is missing from the repository.")
        return 2
    if not _jupyterlab_available():
        _safe_error("JupyterLab is not installed in the current project environment.")
        return 3

    try:
        completed = subprocess.run(
            _launch_command(repository_root),
            cwd=repository_root,
            check=False,
        )
    except KeyboardInterrupt:
        _safe_error("Notebook launch interrupted.")
        return 130
    except OSError:
        _safe_error("JupyterLab could not be started safely.")
        return 3
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

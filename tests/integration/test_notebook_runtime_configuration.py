"""Locked JupyterLab dependency, console entrypoint, and shared IDE launchers."""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
RUN_NOTEBOOK = ROOT / ".run" / "Run Final Notebook.run.xml"
EXECUTE_NOTEBOOK = ROOT / ".run" / "Execute and Validate Final Notebook.run.xml"


def _configuration(path: Path) -> ET.Element:
    document = ET.parse(path)
    configuration = document.getroot().find("configuration")
    assert configuration is not None
    return configuration


def _option(configuration: ET.Element, name: str) -> str:
    for option in configuration.findall("option"):
        if option.get("name") == name:
            return option.get("value", "")
    raise AssertionError(f"missing run configuration option: {name}")


def test_jupyterlab_dependency_and_console_entrypoint_are_declared() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert "jupyterlab>=4.4,<5" in data["dependency-groups"]["dev"]
    assert data["project"]["scripts"]["agentic-payments-notebook"] == (
        "agentic_payments.presentation.notebook_launcher:main"
    )


def test_shared_run_final_notebook_configuration_is_portable() -> None:
    configuration = _configuration(RUN_NOTEBOOK)
    script = _option(configuration, "SCRIPT_TEXT")

    assert configuration.get("name") == "Run Final Notebook"
    assert configuration.get("type") == "ShConfigurationType"
    assert _option(configuration, "SCRIPT_WORKING_DIRECTORY") == "$PROJECT_DIR$"
    assert _option(configuration, "INTERPRETER_PATH") == ""
    assert script.splitlines() == [
        "uv sync --frozen",
        "uv run agentic-payments-notebook",
    ]


def test_shared_execute_and_validate_configuration_is_portable() -> None:
    configuration = _configuration(EXECUTE_NOTEBOOK)
    script = _option(configuration, "SCRIPT_TEXT")

    assert configuration.get("name") == "Execute and Validate Final Notebook"
    assert _option(configuration, "SCRIPT_WORKING_DIRECTORY") == "$PROJECT_DIR$"
    assert script.splitlines() == [
        "uv run python scripts/build_notebook.py",
        "uv run python scripts/validate_notebook.py",
    ]


def test_shared_configurations_contain_no_absolute_path_or_secret() -> None:
    combined = RUN_NOTEBOOK.read_text(encoding="utf-8") + EXECUTE_NOTEBOOK.read_text(
        encoding="utf-8"
    )
    lowered = combined.lower()

    assert re.search(r"[a-z]:[\\/]", combined, flags=re.IGNORECASE) is None
    assert "/users/" not in lowered
    assert "/home/" not in lowered
    assert ".env" not in lowered
    assert "api_key" not in lowered
    assert "jupyter token" not in lowered
    assert "sk-" not in lowered


def test_headless_builder_and_validator_remain_available() -> None:
    assert (ROOT / "scripts" / "build_notebook.py").is_file()
    assert (ROOT / "scripts" / "validate_notebook.py").is_file()

"""Visible notebook order, RTL, and single-artifact structure tests."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
builder = importlib.import_module("build_notebook")
validator = importlib.import_module("validate_notebook")
NOTEBOOK = ROOT / "final_agentic_payment_project.ipynb"


def test_exact_root_notebook_has_all_required_sections_and_rtl() -> None:
    notebook = validator.validate_structure(NOTEBOOK)
    text = "\n".join(str(cell.source) for cell in notebook.cells)

    positions = [text.index(title) for title in builder.SECTION_TITLES]
    assert positions == sorted(positions)
    assert all(title in text for title in builder.SCENARIO_TITLES)
    assert "Lecturer requirement | Project component | Demonstration section" in text
    assert "PolicyAgent" in text
    assert "ReflectionAgent" in text
    assert "בטיחות במקביליות" in text


def test_every_hebrew_markdown_cell_has_rtl_wrapper() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    hebrew_cells = [
        str(cell.source)
        for cell in notebook.cells
        if cell.cell_type == "markdown"
        and any("\u0590" <= character <= "\u05ff" for character in str(cell.source))
    ]

    assert hebrew_cells
    assert all('<div dir="rtl">' in source for source in hebrew_cells)


def test_cleanup_is_the_final_cell_and_outputs_are_preserved() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    last = notebook.cells[-1]

    assert last.cell_type == "code"
    assert "NOTEBOOK_RUNTIME.cleanup()" in str(last.source)
    assert "Temporary notebook runtime cleaned successfully." in str(last.outputs[0].text)


def test_only_one_submission_notebook_exists() -> None:
    notebooks = [
        path
        for path in ROOT.rglob("*.ipynb")
        if not any(
            part in {".venv", ".uv-cache", ".ipynb_checkpoints", ".pytest_cache"}
            for part in path.parts
        )
    ]

    assert notebooks == [NOTEBOOK]

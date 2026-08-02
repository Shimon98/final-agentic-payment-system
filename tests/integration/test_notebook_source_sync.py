"""Manifest drift and exact embedded-source synchronization tests."""

from __future__ import annotations

import copy
import importlib
import shutil
import sys
from pathlib import Path

import nbformat
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
validator = importlib.import_module("validate_notebook")
NOTEBOOK = ROOT / "final_agentic_payment_project.ipynb"


def test_manifest_and_every_source_cell_match_current_production() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)

    validator.validate_source_sync(notebook)


def test_changed_source_requires_rebuild(tmp_path: Path) -> None:
    copied_root = tmp_path / "agentic_payments"
    shutil.copytree(ROOT / "src" / "agentic_payments", copied_root)
    target = copied_root / "__init__.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    notebook = nbformat.read(NOTEBOOK, as_version=4)

    with pytest.raises(ValueError, match="manifest"):
        validator.validate_source_sync(notebook, source_root=copied_root)


def test_missing_embedded_file_is_rejected() -> None:
    notebook = copy.deepcopy(nbformat.read(NOTEBOOK, as_version=4))
    source_index = next(
        index
        for index, cell in enumerate(notebook.cells)
        if str(cell.source).startswith("%%writefile src/agentic_payments/")
    )
    del notebook.cells[source_index]

    with pytest.raises(ValueError, match="source set mismatch"):
        validator.validate_source_sync(notebook)


def test_extra_embedded_file_is_rejected() -> None:
    notebook = copy.deepcopy(nbformat.read(NOTEBOOK, as_version=4))
    notebook.cells.append(
        nbformat.v4.new_code_cell(
            "%%writefile src/agentic_payments/unapproved.py\nVALUE = 1\n",
            id="extra-source-cell",
        )
    )

    with pytest.raises(ValueError, match="source set mismatch"):
        validator.validate_source_sync(notebook)


def test_modified_embedded_text_is_rejected() -> None:
    notebook = copy.deepcopy(nbformat.read(NOTEBOOK, as_version=4))
    source_cell = next(
        cell
        for cell in notebook.cells
        if str(cell.source).startswith("%%writefile src/agentic_payments/")
    )
    source_cell.source = str(source_cell.source) + "# mismatch\n"

    with pytest.raises(ValueError, match="source text differs"):
        validator.validate_source_sync(notebook)

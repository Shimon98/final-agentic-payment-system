"""Repository-source use and production-source non-duplication tests."""

from __future__ import annotations

import copy
import importlib
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


def test_notebook_imports_current_package_from_repository_src() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    validator.validate_repository_setup(notebook)
    text = "\n".join(str(cell.source) for cell in notebook.cells)

    assert 'SOURCE_ROOT = REPOSITORY_ROOT / "src"' in text
    assert '(SOURCE_ROOT / "agentic_payments").is_dir()' in text
    assert "sys.path.insert(0, str(SOURCE_ROOT))" in text


def test_notebook_contains_no_embedded_source_or_manifest() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    text = "\n".join(str(cell.source) for cell in notebook.cells)

    assert "%%writefile" not in text
    assert "agentic_payments_source_manifest" not in notebook.metadata
    assert not any(
        str(cell.source).startswith("%%writefile src/agentic_payments/") for cell in notebook.cells
    )


def test_embedded_writefile_is_rejected() -> None:
    notebook = copy.deepcopy(nbformat.read(NOTEBOOK, as_version=4))
    notebook.cells.append(
        nbformat.v4.new_code_cell(
            "%%writefile src/agentic_payments/unapproved.py\nVALUE = 1\n",
            id="forbidden-source-cell",
        )
    )

    with pytest.raises(ValueError, match="reconstruct"):
        validator.validate_repository_setup(notebook)


def test_missing_repository_produces_clear_explanatory_failure() -> None:
    validator.verify_missing_repository_error(NOTEBOOK, timeout=60)

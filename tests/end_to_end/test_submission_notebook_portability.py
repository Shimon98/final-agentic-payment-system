"""Notebook-alone execution in an otherwise empty directory."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
validator = importlib.import_module("validate_notebook")
NOTEBOOK = ROOT / "final_agentic_payment_project.ipynb"


def test_notebook_copy_executes_without_external_project_source() -> None:
    executed = validator.execute_portability_check(NOTEBOOK, timeout=600)
    output = validator._output_text(executed)

    assert "Package import success: yes" in output
    assert "10/10 lecturer scenarios passed" in output
    assert "FINAL NOTEBOOK VALIDATION PASSED" in output


def test_notebook_contains_no_absolute_repository_path() -> None:
    notebook = validator.validate_structure(NOTEBOOK)
    serialized = "\n".join(str(cell.source) for cell in notebook.cells)

    assert str(ROOT) not in serialized
    assert "C:\\Users\\" not in serialized

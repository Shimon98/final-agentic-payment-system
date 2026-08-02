"""Repository-based submission notebook execution and failure-mode tests."""

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


def test_notebook_executes_with_current_repository_source() -> None:
    executed = validator.execute_repository_check(NOTEBOOK, timeout=600)
    output = validator._output_text(executed)

    assert "Repository package import success: yes" in output
    assert "10/10 lecturer scenarios passed" in output
    assert "FINAL NOTEBOOK VALIDATION PASSED" in output


def test_notebook_fails_clearly_without_repository_source() -> None:
    validator.verify_missing_repository_error(NOTEBOOK, timeout=60)


def test_notebook_contains_no_absolute_repository_path() -> None:
    notebook = validator.validate_structure(NOTEBOOK)
    serialized = "\n".join(str(cell.source) for cell in notebook.cells)

    assert str(ROOT) not in serialized
    assert "C:\\Users\\" not in serialized

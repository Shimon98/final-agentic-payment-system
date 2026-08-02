"""Final submission notebook end-to-end acceptance."""

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


def test_submission_notebook_passes_complete_repository_validation() -> None:
    notebook = validator.validate_notebook(NOTEBOOK, execute=False)

    assert NOTEBOOK.is_file()
    assert NOTEBOOK.name == "final_agentic_payment_project.ipynb"
    assert notebook.metadata["agentic_payments_notebook_role"] == "repository-based-demonstration"


def test_submission_has_no_error_output_and_final_success() -> None:
    notebook = validator.validate_structure(NOTEBOOK)
    output = validator._output_text(notebook)

    assert all(
        item.output_type != "error" for cell in notebook.cells for item in cell.get("outputs", ())
    )
    assert "FINAL NOTEBOOK VALIDATION PASSED" in output
    assert "Temporary notebook runtime cleaned successfully." in output

"""Fresh-kernel execution and preserved-output integration tests."""

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


def _data_snapshot() -> dict[str, bytes]:
    data = ROOT / "data"
    return {
        path.relative_to(data).as_posix(): path.read_bytes()
        for path in data.rglob("*")
        if path.is_file()
    }


def test_fresh_kernel_execution_succeeds_and_cleans_runtime() -> None:
    before = _data_snapshot()

    executed = validator.execute_repository_check(NOTEBOOK, timeout=600)

    validator.validate_outputs(executed)
    assert _data_snapshot() == before == {".gitkeep": b"\n"}
    assert all(
        output.output_type != "error"
        for cell in executed.cells
        for output in cell.get("outputs", ())
    )


def test_submitted_outputs_are_preserved_and_monotonic() -> None:
    notebook = validator.validate_structure(NOTEBOOK)
    validator.validate_outputs(notebook)
    counts = [cell.execution_count for cell in notebook.cells if cell.cell_type == "code"]

    assert counts == sorted(counts)
    assert len(counts) == len(set(counts))

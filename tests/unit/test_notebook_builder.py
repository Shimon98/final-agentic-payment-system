"""Deterministic, readable, atomic repository-notebook builder tests."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
builder = importlib.import_module("build_notebook")


def test_notebook_model_is_deterministic_and_repository_based() -> None:
    first = builder.create_notebook()
    second = builder.create_notebook()
    text = "\n".join(str(cell.source) for cell in first.cells)

    assert [cell.id for cell in first.cells] == [cell.id for cell in second.cells]
    assert first.metadata["agentic_payments_notebook_role"] == "repository-based-demonstration"
    assert 'SOURCE_ROOT = REPOSITORY_ROOT / "src"' in text
    assert "sys.path.insert(0, str(SOURCE_ROOT))" in text
    assert "Run this notebook from the root of the submitted repository." in text


def test_notebook_does_not_embed_or_reconstruct_production_source() -> None:
    notebook = builder.create_notebook()
    text = "\n".join(str(cell.source) for cell in notebook.cells)

    assert "%%writefile" not in text
    assert "agentic_payments_source_manifest" not in notebook.metadata
    assert "source_manifest" not in text
    assert "C:\\Users\\" not in text
    assert ".codex-local" not in text
    assert "BEGIN PRIVATE KEY" not in text


def test_generated_notebook_meets_human_readability_limits() -> None:
    notebook = builder.create_notebook()
    code_lines = [
        len(str(cell.source).splitlines()) for cell in notebook.cells if cell.cell_type == "code"
    ]

    assert 30 <= len(notebook.cells) <= 60
    assert sum(code_lines) <= 1_500
    assert max(code_lines) <= 200


def test_no_execute_uses_exact_requested_output_path(tmp_path: Path) -> None:
    output = tmp_path / "final_agentic_payment_project.ipynb"

    notebook = builder.build_notebook(output, execute=False)

    assert output.is_file()
    assert output.name == "final_agentic_payment_project.ipynb"
    assert all(cell.execution_count is None for cell in notebook.cells if cell.cell_type == "code")


def test_wrong_notebook_filename_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="filename"):
        builder.build_notebook(tmp_path / "wrong.ipynb", execute=False)


def test_execution_failure_preserves_existing_notebook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "final_agentic_payment_project.ipynb"
    previous = b"previous-valid-notebook"
    output.write_bytes(previous)

    def fail_execution(*args: object, **kwargs: object) -> object:
        raise RuntimeError("configured execution failure")

    monkeypatch.setattr(builder, "_execute_notebook", fail_execution)

    with pytest.raises(RuntimeError, match="configured execution failure"):
        builder.build_notebook(output, execute=True)

    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(f".{output.name}.*.tmp"))

"""Deterministic, readable, atomic notebook-builder tests."""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
builder = importlib.import_module("build_notebook")


def test_collects_every_production_python_file_in_stable_order() -> None:
    sources = builder.collect_source_files(builder.SOURCE_ROOT)
    expected = {
        Path("src", "agentic_payments", *path.relative_to(builder.SOURCE_ROOT).parts).as_posix()
        for path in builder.SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    }

    assert set(sources) == expected
    assert list(sources) == sorted(sources)
    assert all(path.endswith(".py") for path in sources)
    assert all("__pycache__" not in path for path in sources)


def test_manifest_has_stable_sha256_hashes() -> None:
    sources = builder.collect_source_files(builder.SOURCE_ROOT)
    first = builder.source_manifest(sources)
    second = builder.source_manifest(sources)

    assert first == second
    assert [entry["path"] for entry in first] == sorted(sources)
    assert all(
        entry["sha256"] == hashlib.sha256(sources[entry["path"]].encode("utf-8")).hexdigest()
        for entry in first
    )


def test_source_cells_are_readable_exact_text_with_deterministic_ids() -> None:
    sources = builder.collect_source_files(builder.SOURCE_ROOT)
    first = builder.create_notebook(sources)
    second = builder.create_notebook(sources)
    source_cells = [
        cell
        for cell in first.cells
        if cell.cell_type == "code"
        and str(cell.source).startswith("%%writefile src/agentic_payments/")
    ]

    assert [cell.id for cell in first.cells] == [cell.id for cell in second.cells]
    assert len(source_cells) == len(sources)
    for cell in source_cells:
        line, _, embedded = str(cell.source).partition("\n")
        path = line.removeprefix("%%writefile ")
        assert embedded == sources[path]


def test_generated_notebook_excludes_private_and_secret_material() -> None:
    notebook = builder.create_notebook(builder.collect_source_files(builder.SOURCE_ROOT))
    text = "\n".join(str(cell.source) for cell in notebook.cells)

    assert ".codex-local" not in text
    assert "C:\\Users\\" not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert "sk-live-" not in text


def test_no_execute_uses_exact_requested_output_path(tmp_path: Path) -> None:
    output = tmp_path / "final_agentic_payment_project.ipynb"

    notebook = builder.build_notebook(output, execute=False)

    assert output.is_file()
    assert output.name == "final_agentic_payment_project.ipynb"
    assert all(cell.execution_count is None for cell in notebook.cells if cell.cell_type == "code")


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

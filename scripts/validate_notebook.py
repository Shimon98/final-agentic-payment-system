"""Validate source sync, execution outputs, privacy, and portability."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import nbformat
from build_notebook import (
    DEFAULT_OUTPUT,
    REQUIRED_PASS_LINES,
    SCENARIO_TITLES,
    SECTION_TITLES,
    SOURCE_ROOT,
    collect_source_files,
    source_manifest,
)
from nbclient import NotebookClient
from nbformat import NotebookNode

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/Users/[^/\s]+/", re.IGNORECASE),
    re.compile(r"/home/[^/\s]+/", re.IGNORECASE),
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(
        r"(?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        re.IGNORECASE,
    ),
)
PHONE_PATTERN = re.compile(r"(?<![A-Za-z0-9])\+?\d{7,15}(?![A-Za-z0-9])")


def _read_notebook(path: Path) -> NotebookNode:
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not path.is_file():
        raise FileNotFoundError("submission notebook is missing")
    return cast(
        NotebookNode,
        nbformat.read(path, as_version=4),  # type: ignore[no-untyped-call]
    )


def _notebook_text(notebook: NotebookNode) -> str:
    return "\n".join(str(cell.source) for cell in notebook.cells)


def _output_text(notebook: NotebookNode) -> str:
    pieces: list[str] = []
    for cell in notebook.cells:
        for output in cell.get("outputs", ()):
            if output.output_type == "stream":
                pieces.append(str(output.text))
            elif output.output_type in {"execute_result", "display_data"}:
                data = output.get("data", {})
                text = data.get("text/plain")
                if text is not None:
                    pieces.append(str(text))
    return "\n".join(pieces)


def _embedded_sources(notebook: NotebookNode) -> dict[str, str]:
    sources: dict[str, str] = {}
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        text = str(cell.source)
        if not text.startswith("%%writefile src/agentic_payments/"):
            continue
        first_line, separator, source = text.partition("\n")
        if not separator:
            raise ValueError("embedded source cell has no readable body")
        path = first_line.removeprefix("%%writefile ").strip()
        if path in sources:
            raise ValueError(f"duplicate embedded source: {path}")
        sources[path] = source
    return sources


def validate_source_sync(
    notebook: NotebookNode,
    *,
    source_root: Path = SOURCE_ROOT,
) -> None:
    """Validate manifest and readable cells against every production source file."""

    current_sources = collect_source_files(source_root)
    expected_manifest = list(source_manifest(current_sources))
    actual_manifest = notebook.metadata.get("agentic_payments_source_manifest")
    if actual_manifest != expected_manifest:
        raise ValueError("source manifest does not match current production source")
    embedded = _embedded_sources(notebook)
    if set(embedded) != set(current_sources):
        missing = sorted(set(current_sources) - set(embedded))
        extra = sorted(set(embedded) - set(current_sources))
        raise ValueError(f"embedded source set mismatch: missing={missing}, extra={extra}")
    for path, expected in current_sources.items():
        actual = embedded[path]
        if actual != expected:
            raise ValueError(f"embedded source text differs: {path}")


def validate_structure(
    path: Path,
    *,
    source_root: Path = SOURCE_ROOT,
    require_executed: bool = True,
) -> NotebookNode:
    """Validate filename, sections, cell ordering, source sync, and privacy."""

    notebook = _read_notebook(path)
    if path.name != "final_agentic_payment_project.ipynb":
        raise ValueError("submission notebook filename is not exact")
    cell_types = {cell.cell_type for cell in notebook.cells}
    if not {"markdown", "code"}.issubset(cell_types):
        raise ValueError("notebook must contain Markdown and code cells")
    text = _notebook_text(notebook)
    for title in SECTION_TITLES:
        if title not in text:
            raise ValueError(f"required section is missing: {title}")
    for title in SCENARIO_TITLES:
        if title not in text:
            raise ValueError(f"lecturer scenario heading is missing: {title}")
    hebrew_markdown = [
        str(cell.source)
        for cell in notebook.cells
        if cell.cell_type == "markdown" and re.search(r"[\u0590-\u05FF]", str(cell.source))
    ]
    if not hebrew_markdown or not all('<div dir="rtl">' in source for source in hebrew_markdown):
        raise ValueError("Hebrew Markdown must use RTL wrappers")
    if notebook.cells[-1].cell_type != "code" or "NOTEBOOK_RUNTIME.cleanup()" not in str(
        notebook.cells[-1].source
    ):
        raise ValueError("cleanup must be the final notebook cell")
    ids = [cell.id for cell in notebook.cells]
    if len(ids) != len(set(ids)):
        raise ValueError("notebook cell IDs must be unique")
    validate_source_sync(notebook, source_root=source_root)
    lowered = text.lower()
    if ".codex-local" in lowered:
        raise ValueError("private control content appears in notebook")
    serialized = json.dumps(notebook, ensure_ascii=False)
    for pattern in ABSOLUTE_PATH_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("absolute local user path appears in notebook")
    for pattern in SECRET_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("secret pattern appears in notebook")
    if require_executed:
        code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
        counts = [cell.execution_count for cell in code_cells]
        if any(not isinstance(count, int) for count in counts):
            raise ValueError("all code cells must have execution counts")
        numeric_counts = [int(count) for count in counts]
        if any(
            right <= left for left, right in zip(numeric_counts, numeric_counts[1:], strict=False)
        ):
            raise ValueError("execution counts must increase monotonically")
    return notebook


def validate_outputs(notebook: NotebookNode) -> None:
    """Validate preserved success outputs and absence of unsafe output."""

    for cell in notebook.cells:
        for output in cell.get("outputs", ()):
            if output.output_type == "error":
                raise ValueError("notebook contains an error output")
    output = _output_text(notebook)
    for line in REQUIRED_PASS_LINES:
        if line not in output:
            raise ValueError(f"required PASS output is missing: {line}")
    required_output = (
        "10/10 lecturer scenarios passed",
        "PASS — concurrency safety demonstrations",
        "PASS — JSON persistence and BusinessMemory survived restart",
        "PASS — Audit Outbox delivered all temporary audit events",
        "FINAL NOTEBOOK VALIDATION PASSED",
        "Temporary notebook runtime cleaned successfully.",
    )
    for line in required_output:
        if line not in output:
            raise ValueError(f"required notebook output is missing: {line}")
    lowered = output.lower()
    if "traceback" in lowered:
        raise ValueError("notebook output contains traceback text")
    for pattern in SECRET_PATTERNS:
        if pattern.search(output):
            raise ValueError("notebook output contains a secret pattern")
    for pattern in ABSOLUTE_PATH_PATTERNS:
        if pattern.search(output):
            raise ValueError("notebook output contains an absolute user path")
    if PHONE_PATTERN.search(output):
        raise ValueError("notebook output contains a complete phone number")


def _execute(
    notebook: NotebookNode,
    *,
    workdir: Path,
    timeout: int,
) -> NotebookNode:
    client = NotebookClient(
        notebook,
        timeout=timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(workdir)}},
        record_timing=False,
        allow_errors=False,
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Proactor event loop does not implement add_reader.*",
            category=RuntimeWarning,
        )
        return client.execute()


def execute_portability_check(path: Path, *, timeout: int = 600) -> NotebookNode:
    """Copy only the notebook to an empty directory and execute it there."""

    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    with tempfile.TemporaryDirectory(prefix="agentic-notebook-portability-") as directory:
        workdir = Path(directory)
        copied = workdir / "final_agentic_payment_project.ipynb"
        shutil.copy2(path, copied)
        if set(workdir.iterdir()) != {copied}:
            raise ValueError("portability directory must initially contain only the notebook")
        unexecuted = _read_notebook(copied)
        for cell in unexecuted.cells:
            if cell.cell_type == "code":
                cell.execution_count = None
                cell.outputs = []
        executed = _execute(unexecuted, workdir=workdir, timeout=timeout)
        validate_outputs(executed)
        if {item.name for item in workdir.iterdir()} != {copied.name}:
            raise ValueError("portable execution left external project files behind")
        return executed


def validate_repository_data(repository_root: Path) -> None:
    """Require repository data to remain exactly the placeholder file."""

    data_root = repository_root / "data"
    contents = (
        {path.relative_to(data_root).as_posix() for path in data_root.rglob("*") if path.is_file()}
        if data_root.exists()
        else set()
    )
    if contents != {".gitkeep"}:
        raise ValueError(f"repository data contains runtime files: {sorted(contents)}")


def validate_notebook(
    path: Path = DEFAULT_OUTPUT,
    *,
    portability: bool = True,
    timeout: int = 600,
) -> NotebookNode:
    """Run every structural, output, source, repository, and portability check."""

    notebook = validate_structure(path)
    validate_outputs(notebook)
    validate_repository_data(Path(__file__).resolve().parents[1])
    if portability:
        execute_portability_check(path, timeout=timeout)
    return notebook


def build_parser() -> argparse.ArgumentParser:
    """Build the notebook-validator command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--notebook",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Submission notebook path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the notebook and print one concise success summary."""

    arguments = build_parser().parse_args(argv)
    notebook = validate_notebook(arguments.notebook)
    manifest = notebook.metadata["agentic_payments_source_manifest"]
    code_count = sum(cell.cell_type == "code" for cell in notebook.cells)
    markdown_count = sum(cell.cell_type == "markdown" for cell in notebook.cells)
    print(
        "Notebook validation passed:",
        arguments.notebook.name,
        f"cells={len(notebook.cells)}",
        f"code={code_count}",
        f"markdown={markdown_count}",
        f"sources={len(manifest)}",
        "portability=yes",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

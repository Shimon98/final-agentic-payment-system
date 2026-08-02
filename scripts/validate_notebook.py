"""Validate the repository-based notebook, outputs, privacy, and execution."""

from __future__ import annotations

import argparse
import copy
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
    REPOSITORY_ROOT,
    REQUIRED_PASS_LINES,
    SCENARIO_TITLES,
    SECTION_TITLES,
)
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError
from nbformat import NotebookNode

MAX_CELLS = 60
MAX_CODE_LINES = 1_500
MAX_CODE_CELL_LINES = 200
MAX_NOTEBOOK_BYTES = 700_000

ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/Users/[^/\s]+/", re.IGNORECASE),
    re.compile(r"/home/[^/\s]+/", re.IGNORECASE),
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(
        r"(?:api[_-]?key|authorization|password|secret|token)"
        r"\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        re.IGNORECASE,
    ),
)
PHONE_PATTERN = re.compile(r"(?<![A-Za-z0-9])\+?\d{7,15}(?![A-Za-z0-9])")
RTL_PREFIX = '<div dir="rtl" style="text-align: right; line-height: 1.7;">'
MISSING_REPOSITORY_MESSAGE = "Run this notebook from the root of the submitted repository."


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
                text = output.get("data", {}).get("text/plain")
                if text is not None:
                    pieces.append(str(text))
    return "\n".join(pieces)


def code_metrics(notebook: NotebookNode) -> tuple[int, int]:
    line_counts = [
        len(str(cell.source).splitlines()) for cell in notebook.cells if cell.cell_type == "code"
    ]
    return sum(line_counts), max(line_counts, default=0)


def validate_repository_setup(notebook: NotebookNode) -> None:
    """Require real repository imports and forbid embedded repository copies."""

    text = _notebook_text(notebook)
    required = (
        "REPOSITORY_ROOT = Path.cwd().resolve()",
        'SOURCE_ROOT = REPOSITORY_ROOT / "src"',
        '(SOURCE_ROOT / "agentic_payments").is_dir()',
        "sys.path.insert(0, str(SOURCE_ROOT))",
        MISSING_REPOSITORY_MESSAGE,
        "TemporaryDirectory",
        "_env_file=None",
    )
    if not all(marker in text for marker in required):
        raise ValueError("repository-based setup is incomplete")
    if "%%writefile" in text:
        raise ValueError("notebook must not reconstruct production source")
    if "agentic_payments_source_manifest" in notebook.metadata:
        raise ValueError("notebook must not contain a production source manifest")
    if "sha256" in text.lower() and "source_manifest" in text.lower():
        raise ValueError("notebook must not contain a complete source hash table")


def validate_structure(
    path: Path,
    *,
    require_executed: bool = True,
) -> NotebookNode:
    """Validate filename, presentation, size, source role, and execution state."""

    notebook = _read_notebook(path)
    if path.name != DEFAULT_OUTPUT.name:
        raise ValueError("submission notebook filename is not exact")
    if path.stat().st_size > MAX_NOTEBOOK_BYTES:
        raise ValueError("submission notebook exceeds the size limit")
    if len(notebook.cells) > MAX_CELLS:
        raise ValueError("submission notebook exceeds the cell limit")
    if not {"markdown", "code"}.issubset({cell.cell_type for cell in notebook.cells}):
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
    if not hebrew_markdown or not all(
        source.startswith(RTL_PREFIX) and source.rstrip().endswith("</div>")
        for source in hebrew_markdown
    ):
        raise ValueError("every Hebrew Markdown cell must use the approved RTL wrapper")

    total_lines, maximum_lines = code_metrics(notebook)
    if total_lines > MAX_CODE_LINES:
        raise ValueError("notebook exceeds the total code-source line limit")
    if maximum_lines > MAX_CODE_CELL_LINES:
        raise ValueError("a notebook code cell exceeds the line limit")

    if notebook.cells[-1].cell_type != "code" or "NOTEBOOK_RUNTIME.cleanup()" not in str(
        notebook.cells[-1].source
    ):
        raise ValueError("cleanup must be the final notebook cell")
    ids = [cell.id for cell in notebook.cells]
    if len(ids) != len(set(ids)):
        raise ValueError("notebook cell IDs must be unique")

    validate_repository_setup(notebook)
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
    """Validate concise success outputs and absence of unsafe output."""

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


def _unexecuted_copy(notebook: NotebookNode) -> NotebookNode:
    copied = copy.deepcopy(notebook)
    for cell in copied.cells:
        if cell.cell_type == "code":
            cell.execution_count = None
            cell.outputs = []
    return copied


def _data_snapshot(repository_root: Path) -> dict[str, bytes]:
    data_root = repository_root / "data"
    return {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file()
    }


def execute_repository_check(
    path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    timeout: int = 600,
) -> NotebookNode:
    """Execute a fresh notebook kernel from the submitted repository root."""

    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    if not (repository_root / "src" / "agentic_payments").is_dir():
        raise FileNotFoundError("repository production source is missing")
    before = _data_snapshot(repository_root)
    executed = _execute(
        _unexecuted_copy(_read_notebook(path)),
        workdir=repository_root,
        timeout=timeout,
    )
    validate_outputs(executed)
    if _data_snapshot(repository_root) != before:
        raise ValueError("notebook execution modified repository data")
    return executed


def verify_missing_repository_error(path: Path, *, timeout: int = 60) -> None:
    """Confirm a notebook-only run fails with the approved explanatory message."""

    with tempfile.TemporaryDirectory(prefix="agentic-notebook-missing-repository-") as directory:
        workdir = Path(directory)
        copied = workdir / DEFAULT_OUTPUT.name
        shutil.copy2(path, copied)
        try:
            _execute(
                _unexecuted_copy(_read_notebook(copied)),
                workdir=workdir,
                timeout=timeout,
            )
        except CellExecutionError as error:
            if MISSING_REPOSITORY_MESSAGE not in str(error):
                raise ValueError("missing repository error is not explanatory") from error
        else:
            raise ValueError("notebook unexpectedly ran without repository source")


def validate_repository_data(repository_root: Path) -> None:
    """Require repository data to remain exactly the placeholder file."""

    contents = _data_snapshot(repository_root)
    if contents != {".gitkeep": b"\n"}:
        raise ValueError("repository data must contain only the placeholder")


def validate_notebook(
    path: Path = DEFAULT_OUTPUT,
    *,
    execute: bool = True,
    timeout: int = 600,
) -> NotebookNode:
    """Run every structural, output, repository, and fresh-kernel check."""

    notebook = validate_structure(path)
    validate_outputs(notebook)
    validate_repository_data(REPOSITORY_ROOT)
    if execute:
        execute_repository_check(path, timeout=timeout)
    return notebook


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the repository-based agentic payment notebook."
    )
    parser.add_argument(
        "--notebook",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Submission notebook path.",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Skip the independent fresh-kernel repository execution.",
    )
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    notebook = validate_notebook(
        arguments.notebook,
        execute=not arguments.no_execute,
        timeout=arguments.timeout,
    )
    code_count = sum(cell.cell_type == "code" for cell in notebook.cells)
    markdown_count = sum(cell.cell_type == "markdown" for cell in notebook.cells)
    total_lines, maximum_lines = code_metrics(notebook)
    print(
        "Notebook validation passed:",
        arguments.notebook.name,
        f"cells={len(notebook.cells)}",
        f"code={code_count}",
        f"markdown={markdown_count}",
        f"code_lines={total_lines}",
        f"max_code_cell_lines={maximum_lines}",
        "repository_execution=yes" if not arguments.no_execute else "repository_execution=no",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

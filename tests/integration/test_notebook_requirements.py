"""Lecturer content, advanced feature, and limitation requirements."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
builder = importlib.import_module("build_notebook")
validator = importlib.import_module("validate_notebook")
NOTEBOOK = ROOT / "final_agentic_payment_project.ipynb"


def test_all_lecturer_requirements_and_ten_pass_lines_are_visible() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(str(cell.source) for cell in notebook.cells)
    output = validator._output_text(notebook)
    required_components = (
        "AgentResult",
        "RouterAgent",
        "OrchestratorAgent",
        "PaymentToolRegistry",
        "BusinessMemory",
        "FraudDetectionAgent",
        "SecurityAgent",
        "CriticAgent",
        "ExplanationAgent",
        "PolicyAgent",
        "ReflectionAgent",
        "JSON persistence",
    )

    assert all(component in source for component in required_components)
    assert all(line in output for line in builder.REQUIRED_PASS_LINES)
    assert "10/10 lecturer scenarios passed" in output


def test_advanced_concurrency_sdk_summary_and_limitations_are_visible() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(str(cell.source) for cell in notebook.cells)
    output = validator._output_text(notebook)

    assert "PASS — concurrency safety demonstrations" in output
    assert "PASS — JSON persistence and BusinessMemory survived restart" in output
    assert "PASS — Audit Outbox delivered all temporary audit events" in output
    assert "Optional SDK router schema: locally validated" in output
    assert "Financial function tool present: no" in output
    assert "event loop" in source
    assert "מסד נתונים טרנזקציוני" in source
    assert "FINAL NOTEBOOK VALIDATION PASSED" in output

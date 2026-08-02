"""Submission artifact, inclusion, exclusion, and no-API instructions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "docs" / "submission.md").read_text(encoding="utf-8")


def test_submission_names_exact_notebook_and_commands() -> None:
    assert "final_agentic_payment_project.ipynb" in TEXT
    assert "uv run python scripts/build_notebook.py" in TEXT
    assert "uv run python scripts/validate_notebook.py" in TEXT
    assert "FINAL NOTEBOOK VALIDATION PASSED" in TEXT


def test_submission_inclusion_list_is_complete() -> None:
    required = (
        "`src/`",
        "`tests/`",
        "`scripts/`",
        "`docs/`",
        "`final_agentic_payment_project.ipynb`",
        "`README.md`",
        "`pyproject.toml`",
        "`uv.lock`",
        "`.env.example`",
        "`.github/workflows/ci.yml`",
        "`LICENSE`",
    )

    assert all(item in TEXT for item in required)


def test_submission_exclusion_list_is_complete() -> None:
    excluded = (
        "`.env`",
        "`.codex-local`",
        "`.idea`",
        "`.venv`",
        "caches",
        "temporary data",
        "API keys",
        "live provider outputs",
    )

    assert all(item in TEXT for item in excluded)


def test_submission_documents_portable_no_api_execution_and_scenarios() -> None:
    lowered = TEXT.lower()

    assert "no api key is required" in lowered
    assert "otherwise empty temporary directory" in lowered
    assert "source-manifest" in lowered
    assert all(f"{number}." in TEXT for number in range(1, 11))

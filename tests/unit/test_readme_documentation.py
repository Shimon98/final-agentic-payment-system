"""README structure, claims, commands, and public index."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
TEXT = README.read_text(encoding="utf-8")

SECTIONS = (
    "# Agentic Payment System",
    "## Educational disclaimer",
    "## Overview",
    "## Key capabilities",
    "## Architecture",
    "## Agent responsibilities",
    "## Supported intents",
    "## Payment business rules",
    "## Concurrency and transaction safety",
    "## Persistence and audit",
    "## Optional OpenAI Agents SDK integration",
    "## Project structure",
    "## Requirements",
    "## Installation",
    "## Configuration",
    "## Running the CLI",
    "## Running the demonstration",
    "## Running the notebook",
    "## Running tests",
    "## Provider-specific live tests",
    "## Security and privacy",
    "## Known limitations",
    "## Lecturer-requirement mapping",
    "## Documentation index",
    "## License",
)

DOC_FILES = (
    "architecture.md",
    "class_design.md",
    "agent_flows.md",
    "prompts.md",
    "concurrency_and_transactions.md",
    "persistence_and_audit.md",
    "security.md",
    "testing.md",
    "execution_examples.md",
    "requirements_traceability.md",
    "provider_configuration.md",
    "submission.md",
)


def test_readme_has_exact_required_section_order_and_subtitle() -> None:
    positions = [TEXT.index(section) for section in SECTIONS]

    assert positions == sorted(positions)
    assert (
        "Production-inspired educational payment simulation using deterministic business logic "
        "and\nguarded AI agents."
    ) in TEXT


def test_disclaimer_is_near_top_and_claims_are_bounded() -> None:
    beginning = TEXT[:1200].lower()
    normalized_beginning = " ".join(beginning.split())
    lowered = TEXT.lower()

    assert "educational simulation only" in normalized_beginning
    assert "no real bank, card, or" in normalized_beginning
    assert "no real financial data should be used" in normalized_beginning
    assert "financial mutations are deterministic" in normalized_beginning
    assert "language-model behavior is optional and advisory" in normalized_beginning
    assert "production-ready banking system" not in lowered
    assert "fully secure financial platform" not in lowered
    assert "distributed transaction safe" not in lowered


def test_readme_contains_all_verified_commands_and_exact_notebook() -> None:
    commands = (
        "uv sync",
        "uv run python -m agentic_payments --help",
        "uv run python -m agentic_payments demo",
        "uv run python -m agentic_payments interactive",
        "uv run agentic-payments --help",
        "uv run agentic-payments demo",
        "uv run python scripts/build_notebook.py",
        "uv run python scripts/validate_notebook.py",
        'uv run pytest tests/unit tests/integration tests/concurrency tests/end_to_end -m "not '
        'live_llm"',
        "uv run ruff check src scripts tests",
        "uv run ruff format --check src scripts tests",
        "uv run mypy src/agentic_payments scripts",
    )

    assert all(command in TEXT for command in commands)
    assert "final_agentic_payment_project.ipynb" in TEXT


def test_readme_contains_every_public_document_link() -> None:
    for filename in DOC_FILES:
        assert f"](docs/{filename})" in TEXT

    assert "](final_agentic_payment_project.ipynb)" in TEXT
    assert "](docs/requirements_traceability.md)" in TEXT


def test_readme_has_no_secret_like_value_or_absolute_local_path() -> None:
    assert re.search(r"\bsk-[A-Za-z0-9_-]{10,}", TEXT) is None
    assert re.search(r"\bAIza[A-Za-z0-9_-]{10,}", TEXT) is None
    assert re.search(r"[A-Za-z]:\\", TEXT) is None
    assert re.search(r"/(?:home|Users)/[^/\s]+", TEXT) is None
    assert "file://" not in TEXT.lower()

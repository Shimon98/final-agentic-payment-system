"""Offline validation of the real GitHub Actions workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict[str, object]:
    parsed = yaml.load(TEXT, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def test_ci_is_valid_yaml_with_exact_name_triggers_and_permissions() -> None:
    workflow = _workflow()
    triggers = workflow["on"]

    assert workflow["name"] == "CI"
    assert isinstance(triggers, dict)
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}


def test_ci_uses_linux_python_uv_cache_and_safe_environment() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["quality"]  # type: ignore[index]
    env = workflow["env"]
    serialized = str(job)

    assert job["runs-on"] == "ubuntu-latest"
    assert "astral-sh/setup-uv@" in serialized
    assert "enable-cache" in serialized
    assert "actions/setup-python@" in serialized
    assert "3.12" in serialized
    assert env == {
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "RUN_LIVE_LLM_TESTS": "false",
        "LLM_PROVIDER": "rule_based",
        "ENABLE_LLM_ROUTER": "false",
    }


def test_ci_runs_every_required_quality_and_validation_step() -> None:
    required = (
        "uv sync --frozen",
        "uv run ruff check src scripts tests",
        "uv run ruff format --check src scripts tests",
        "uv run mypy src/agentic_payments scripts",
        '-m "not live_llm"',
        "--cov=src/agentic_payments",
        "--cov=scripts",
        "--cov-fail-under=85",
        "uv run python scripts/validate_notebook.py",
        "test_documentation_source_alignment.py",
        "test_submission_documentation.py",
        "find data -type f",
        "test_documentation_security.py",
    )

    assert all(item in TEXT for item in required)


def test_ci_uses_no_secrets_live_provider_deploy_or_git_write() -> None:
    lowered = TEXT.lower()

    assert "${{ secrets." not in lowered
    assert 'run_live_llm_tests: "false"' in lowered
    assert 'llm_provider: "rule_based"' in lowered
    assert 'enable_llm_router: "false"' in lowered
    assert "tests/live" not in lowered
    assert "deploy" not in lowered
    assert "git push" not in lowered
    assert "git commit" not in lowered
    assert "git add" not in lowered

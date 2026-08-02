"""Public-document and CI privacy scans."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = (
    ROOT / "README.md",
    ROOT / ".github" / "workflows" / "ci.yml",
    *sorted((ROOT / "docs").glob("*.md")),
)
TEXT_BY_PATH = {path: path.read_text(encoding="utf-8") for path in PUBLIC_FILES}
ALL_TEXT = "\n".join(TEXT_BY_PATH.values())


def test_public_material_has_no_api_key_or_complete_phone_number() -> None:
    secret_patterns = (
        r"\bsk-[A-Za-z0-9_-]{10,}",
        r"\bAIza[A-Za-z0-9_-]{10,}",
        r"\bghp_[A-Za-z0-9]{10,}",
        r"(?i)api[_-]?key\s*[:=]\s*[\"']?[A-Za-z0-9_-]{16,}",
    )

    assert all(re.search(pattern, ALL_TEXT) is None for pattern in secret_patterns)
    assert re.search(r"(?<![A-Za-z0-9])0\d{6,14}(?![A-Za-z0-9])", ALL_TEXT) is None


def test_public_material_has_no_absolute_path_private_text_or_internal_failure_dump() -> None:
    lowered = ALL_TEXT.lower()

    assert re.search(r"[A-Za-z]:\\", ALL_TEXT) is None
    assert re.search(r"/(?:home|Users)/[^/\s]+", ALL_TEXT) is None
    assert "file://" not in lowered
    assert "binding overrides and resolved design decisions" not in lowered
    assert "phase gates and required stop points" not in lowered
    assert "codex master prompt" not in lowered
    assert "traceback" not in lowered
    assert "raw provider response" not in lowered


def test_private_directory_name_appears_only_as_required_submission_exclusion() -> None:
    occurrences = [path for path, text in TEXT_BY_PATH.items() if ".codex-local" in text.lower()]

    assert occurrences == [ROOT / "docs" / "submission.md"]
    assert "- `.codex-local`" in TEXT_BY_PATH[ROOT / "docs" / "submission.md"]


def test_env_examples_use_names_and_placeholders_only() -> None:
    provider = TEXT_BY_PATH[ROOT / "docs" / "provider_configuration.md"]
    assignments = re.findall(r"^(LLM_[A-Z_]+|ENABLE_[A-Z_]+)=(.+)$", provider, re.MULTILINE)

    assert assignments
    assert all(value.startswith("<") and value.endswith(">") for _, value in assignments)
    assert "LLM_API_KEY=<your-local-api-key>" in provider


def test_ci_never_references_secret_context_or_provider_credentials() -> None:
    ci = TEXT_BY_PATH[ROOT / ".github" / "workflows" / "ci.yml"].lower()

    assert "${{ secrets." not in ci
    assert "llm_api_key" not in ci
    assert 'llm_provider: "rule_based"' in ci
    assert 'run_live_llm_tests: "false"' in ci

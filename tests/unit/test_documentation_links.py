"""Resolution and privacy rules for public Markdown links."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_MARKDOWN = (ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")))
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _relative_links(path: Path) -> list[str]:
    links: list[str] = []
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        clean = unquote(target.strip().split("#", 1)[0])
        if clean and not re.match(r"^[a-z][a-z0-9+.-]*://", clean, re.IGNORECASE):
            links.append(clean)
    return links


def test_every_relative_markdown_link_resolves() -> None:
    for document in PUBLIC_MARKDOWN:
        for target in _relative_links(document):
            resolved = (document.parent / target).resolve()
            assert resolved.is_relative_to(ROOT.resolve()), (document, target)
            assert resolved.exists(), (document, target)


def test_links_never_target_private_or_absolute_locations() -> None:
    for document in PUBLIC_MARKDOWN:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            lowered = target.lower()
            assert ".codex-local" not in lowered
            assert not re.match(r"^[A-Za-z]:[\\/]", target)
            assert not target.startswith(("/home/", "/Users/", "file://"))
            assert "sandbox:" not in lowered


def test_all_required_public_document_files_exist() -> None:
    expected = {
        "agent_flows.md",
        "architecture.md",
        "class_design.md",
        "concurrency_and_transactions.md",
        "execution_examples.md",
        "persistence_and_audit.md",
        "prompts.md",
        "provider_configuration.md",
        "requirements_traceability.md",
        "security.md",
        "submission.md",
        "testing.md",
    }

    assert {path.name for path in (ROOT / "docs").glob("*.md")} == expected


def test_readme_links_to_notebook_and_traceability() -> None:
    links = set(_relative_links(ROOT / "README.md"))

    assert "final_agentic_payment_project.ipynb" in links
    assert "docs/requirements_traceability.md" in links

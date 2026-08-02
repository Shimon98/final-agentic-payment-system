"""Static architecture boundaries for the deterministic agent layer."""

from __future__ import annotations

import ast
from pathlib import Path

import agentic_payments.agents as agents_package

AGENTS_ROOT = Path(agents_package.__file__).parent
PRODUCTION_FILES = sorted(AGENTS_ROOT.glob("*.py"))

FORBIDDEN_IMPORT_PARTS = {
    "agentic_payments.infrastructure",
    "agentic_payments.presentation",
    "openai",
    "agents",
    "httpx",
    "requests",
    "dotenv",
    "pathlib",
    "urllib",
    "socket",
}


def _sources() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in PRODUCTION_FILES}


def test_agents_package_exports_only_approved_public_api() -> None:
    assert agents_package.__all__ == [
        "AgentContext",
        "BaseAgent",
        "RouterAgent",
        "FraudDetectionAgent",
        "SecurityAgent",
        "ExplanationAgent",
        "CriticAgent",
        "PolicyAgent",
        "ReflectionAgent",
        "FallbackAgent",
    ]
    assert not (AGENTS_ROOT / "factory.py").exists()


def test_no_forbidden_infrastructure_network_filesystem_or_sdk_imports() -> None:
    for path, source in _sources().items():
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            for module in imported:
                assert not any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_IMPORT_PARTS
                ), f"{path.name} imports forbidden module {module}"


def test_no_system_time_random_uuid_or_filesystem_calls() -> None:
    combined = "\n".join(_sources().values())
    forbidden_snippets = [
        "datetime.now(",
        "datetime.utcnow(",
        "time.time(",
        "uuid4(",
        "random.",
        "Path(",
        "open(",
        ".read_text(",
        ".write_text(",
    ]
    for snippet in forbidden_snippets:
        assert snippet not in combined


def test_no_state_entity_or_wallet_balance_assignment() -> None:
    for path, source in _sources().items():
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets.extend(node.targets)
                else:
                    targets.append(node.target)
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr != "balance", (
                            f"{path.name} directly assigns Wallet.balance"
                        )
                        assert not (
                            isinstance(target.value, ast.Name)
                            and target.value.id in {"state", "transaction", "snapshot"}
                        ), f"{path.name} mutates an immutable input"


def test_no_locks_unit_of_work_or_transaction_manager_use() -> None:
    combined = "\n".join(_sources().values())
    forbidden_names = [
        "AsyncResourceLockManager",
        "PaymentUnitOfWork",
        "PaymentTransactionManager",
        "LockKey",
        "LockScope",
        "asyncio.Lock",
    ]
    for name in forbidden_names:
        assert name not in combined


def test_agent_modules_depend_only_on_standard_library_application_domain_and_agents() -> None:
    for path, source in _sources().items():
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("agentic_payments.")
            ):
                assert node.module.startswith(
                    (
                        "agentic_payments.application",
                        "agentic_payments.domain",
                        "agentic_payments.agents",
                    )
                ), f"{path.name} crosses the approved application/domain boundary"

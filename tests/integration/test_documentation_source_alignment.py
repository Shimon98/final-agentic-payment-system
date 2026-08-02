"""Public documentation alignment with current production symbols and paths."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

from agentic_payments.agents import prompts
from agentic_payments.application.memory_service import MemoryService
from agentic_payments.application.orchestrator import OrchestratorAgent
from agentic_payments.application.payment_domain_service import PaymentDomainService
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.concurrency.lock_key import LockScope
from agentic_payments.infrastructure.config import Settings
from agentic_payments.presentation.cli import build_parser
from agentic_payments.tools import payment_tools

ROOT = Path(__file__).resolve().parents[2]
DOCS = {
    path.name: path.read_text(encoding="utf-8") for path in sorted((ROOT / "docs").glob("*.md"))
}
CLASS_DESIGN = DOCS["class_design.md"]

CLASS_PATHS = {
    "User": "src/agentic_payments/domain/entities.py",
    "Wallet": "src/agentic_payments/domain/entities.py",
    "Transaction": "src/agentic_payments/domain/entities.py",
    "PaymentRequest": "src/agentic_payments/domain/entities.py",
    "AuditEvent": "src/agentic_payments/domain/entities.py",
    "TransactionSnapshot": "src/agentic_payments/domain/snapshots.py",
    "TransferPolicy": "src/agentic_payments/domain/policies.py",
    "AgentResult": "src/agentic_payments/application/results.py",
    "ApplicationState": "src/agentic_payments/application/state.py",
    "BusinessMemory": "src/agentic_payments/application/memory_service.py",
    "MemoryService": "src/agentic_payments/application/memory_service.py",
    "PaymentDomainService": "src/agentic_payments/application/payment_domain_service.py",
    "PaymentFacade": "src/agentic_payments/application/payment_facade.py",
    "OrchestratorAgent": "src/agentic_payments/application/orchestrator.py",
    "RouterAgent": "src/agentic_payments/agents/router_agent.py",
    "HybridRouterAgent": "src/agentic_payments/agents/hybrid_router_agent.py",
    "FraudDetectionAgent": "src/agentic_payments/agents/fraud_agent.py",
    "SecurityAgent": "src/agentic_payments/agents/security_agent.py",
    "ExplanationAgent": "src/agentic_payments/agents/explanation_agent.py",
    "CriticAgent": "src/agentic_payments/agents/critic_agent.py",
    "PolicyAgent": "src/agentic_payments/agents/policy_agent.py",
    "ReflectionAgent": "src/agentic_payments/agents/reflection_agent.py",
    "FallbackAgent": "src/agentic_payments/agents/fallback_agent.py",
    "PaymentToolRegistry": "src/agentic_payments/tools/payment_tools.py",
    "ToolGuardrails": "src/agentic_payments/tools/guardrails.py",
    "AsyncResourceLockManager": (
        "src/agentic_payments/infrastructure/concurrency/resource_lock_manager.py"
    ),
    "PaymentTransactionManager": (
        "src/agentic_payments/infrastructure/concurrency/transaction_manager.py"
    ),
    "PaymentUnitOfWork": "src/agentic_payments/infrastructure/concurrency/unit_of_work.py",
    "JsonStateRepository": "src/agentic_payments/infrastructure/json_state_repository.py",
    "JsonLinesAuditRepository": ("src/agentic_payments/infrastructure/jsonl_audit_repository.py"),
    "AuditOutboxDispatcher": "src/agentic_payments/infrastructure/audit_outbox.py",
    "TransactionalIdempotencyStore": ("src/agentic_payments/infrastructure/idempotency_store.py"),
    "Settings": "src/agentic_payments/infrastructure/config.py",
    "SystemClock": "src/agentic_payments/infrastructure/clock.py",
    "UuidIdGenerator": "src/agentic_payments/infrastructure/id_generator.py",
    "AgentsModelFactory": "src/agentic_payments/infrastructure/llm/provider_factory.py",
    "OpenAIAgentsRuntime": "src/agentic_payments/infrastructure/llm/sdk_runtime.py",
    "ApplicationContainer": "src/agentic_payments/bootstrap.py",
}

PROMPT_NAMES = (
    "ROUTER_SYSTEM_PROMPT",
    "FRAUD_SYSTEM_PROMPT",
    "SECURITY_SYSTEM_PROMPT",
    "EXPLANATION_SYSTEM_PROMPT",
    "CRITIC_SYSTEM_PROMPT",
    "REFLECTION_SYSTEM_PROMPT",
    "FALLBACK_SYSTEM_PROMPT",
)


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_documented_public_classes_exist_in_named_source() -> None:
    for class_name, relative_path in CLASS_PATHS.items():
        path = ROOT / relative_path
        assert path.is_file()
        assert class_name in _class_names(path)
        assert f"`{class_name}`" in CLASS_DESIGN


def test_documented_intents_prompts_locks_and_tools_match_production() -> None:
    all_docs = "\n".join(DOCS.values())
    prompt_doc = DOCS["prompts.md"]
    concurrency_doc = DOCS["concurrency_and_transactions.md"]

    assert all(intent.value in all_docs for intent in Intent)
    assert all(hasattr(prompts, name) and name in prompt_doc for name in PROMPT_NAMES)
    for scope in LockScope:
        assert f"`{scope.name}`" in concurrency_doc
        assert f"| {scope.value} |" in concurrency_doc
    for intent, tool_name in payment_tools._TOOL_NAMES.items():
        assert intent.value in CLASS_DESIGN
        assert tool_name in CLASS_DESIGN


def test_documented_cli_subcommands_and_environment_names_match_source() -> None:
    parser = build_parser()
    action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
    documented_cli = (ROOT / "README.md").read_text(encoding="utf-8") + DOCS[
        "execution_examples.md"
    ]
    provider_doc = DOCS["provider_configuration.md"]

    assert set(action.choices) == {"interactive", "demo", "status", "flush", "reset"}
    assert all(command in documented_cli for command in action.choices)
    assert all(field.upper() in provider_doc for field in Settings.model_fields)


def test_every_documented_principal_method_exists() -> None:
    methods = {
        PaymentDomainService: (
            "create_user",
            "get_balance",
            "get_transactions",
            "transfer_money",
            "request_payment",
            "approve_payment_request",
            "reject_payment_request",
            "annotate_transaction_risk",
        ),
        PaymentFacade: (
            "create_user",
            "check_balance",
            "transfer_money",
            "request_payment",
            "approve_payment",
            "reject_payment",
            "show_transactions",
            "fraud_check",
            "security_review",
            "explain_last_action",
        ),
        OrchestratorAgent: ("handle",),
        MemoryService: (
            "remember_route",
            "remember_user",
            "remember_transaction",
            "remember_payment_request",
            "remember_result",
            "snapshot",
            "reset",
        ),
    }

    for class_type, names in methods.items():
        assert all(hasattr(class_type, name) for name in names)
        assert all(f"`{name}`" in CLASS_DESIGN for name in names)


def test_traceability_source_and_test_paths_exist() -> None:
    traceability = DOCS["requirements_traceability.md"]
    paths = re.findall(
        r"`((?:src|tests)/[^`]+|final_agentic_payment_project\.ipynb)`", traceability
    )

    assert paths
    assert all((ROOT / path).exists() for path in paths)

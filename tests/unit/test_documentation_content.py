"""Required public documentation content and safety boundaries."""

from __future__ import annotations

from pathlib import Path

from agentic_payments.domain import Intent

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCS = {
    path.name: path.read_text(encoding="utf-8") for path in sorted((ROOT / "docs").glob("*.md"))
}
ALL_TEXT = README + "\n" + "\n".join(DOCS.values())


def test_every_intent_agent_and_operation_is_documented() -> None:
    agents = (
        "RouterAgent",
        "HybridRouterAgent",
        "FraudDetectionAgent",
        "SecurityAgent",
        "ExplanationAgent",
        "CriticAgent",
        "PolicyAgent",
        "ReflectionAgent",
        "FallbackAgent",
    )
    operations = (
        "create_user",
        "get_balance",
        "transfer_money",
        "get_transactions",
        "request_payment",
        "approve_payment_request",
        "reject_payment_request",
        "annotate_transaction_risk",
    )

    assert all(intent.value in ALL_TEXT for intent in Intent)
    assert all(agent in ALL_TEXT for agent in agents)
    assert all(operation in ALL_TEXT for operation in operations)


def test_business_rules_and_mutation_boundary_are_explicit() -> None:
    lowered = ALL_TEXT.lower()
    normalized = " ".join(lowered.replace("`", "").split())
    rules = (
        "decimal",
        "non-negative",
        "positive",
        "self-transfer",
        "negative balance",
        "single-transfer",
        "daily-transfer",
        "resolved only once",
        "idempotency",
        "immutable",
        "version",
    )

    assert all(rule in lowered for rule in rules)
    assert "paymentdomainservice is the mutation boundary" in normalized
    assert "agents do not change balances" in normalized


def test_concurrency_provider_and_live_test_limits_are_accurate() -> None:
    lowered = ALL_TEXT.lower()

    assert "one python process and one event loop" in lowered
    assert "transactional database" in lowered
    assert all(
        mode in DOCS["provider_configuration.md"]
        for mode in (
            "rule_based",
            "openai",
            "gemini",
            "openai_compatible",
        )
    )
    assert "live tests are opt-in" in lowered
    assert "run_live_llm_tests=true" in lowered
    assert "llm_api_key=<your-local-api-key>" in lowered


def test_notebook_scenarios_and_historical_totals_are_labeled() -> None:
    submission = DOCS["submission.md"].lower()
    testing = DOCS["testing.md"]

    assert all(f"{number}." in submission for number in range(1, 11))
    assert "944 passed" in testing
    assert "88.00%" in testing
    assert "historical Phase 10" in testing
    assert "not a permanent guarantee" in testing
    assert "Phase 12 will run and report final totals again" in testing

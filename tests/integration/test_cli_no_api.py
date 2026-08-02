"""Default rule-based CLI graph without API clients or network."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

import agentic_payments.bootstrap as bootstrap
from agentic_payments.agents import RouterAgent
from agentic_payments.bootstrap import build_application
from agentic_payments.infrastructure import Settings


@pytest.mark.asyncio
async def test_no_api_full_transfer_flow_uses_deterministic_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network must not be used")

    def forbid_model_factory(*args: object, **kwargs: object) -> None:
        raise AssertionError("provider factory must not be constructed")

    monkeypatch.setattr(socket, "create_connection", forbid_network)
    monkeypatch.setattr(bootstrap, "AgentsModelFactory", forbid_model_factory)
    settings = Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )
    assert settings.llm_api_key is None

    container = await build_application(settings)
    alice = await container.orchestrator.handle(
        'createUser name="Alice" phone=0501111111 initial_balance=100.00',
        idempotency_key="NOAPI-ALICE",
    )
    bob = await container.orchestrator.handle(
        'createUser name="Bob" phone=0502222222 initial_balance=50.00',
        idempotency_key="NOAPI-BOB",
    )
    transfer = await container.orchestrator.handle(
        (
            f"transferMoney sender_id={alice.output['user_id']} "
            f"receiver_id={bob.output['user_id']} amount=25.00"
        ),
        idempotency_key="NOAPI-TRANSFER",
    )

    assert isinstance(container.orchestrator._router_agent, RouterAgent)
    assert container.llm_runtime is None
    assert transfer.output["operation"] == "transferMoney"
    assert container.snapshot().wallets[alice.output["user_id"]].balance == 75
    assert container.snapshot().wallets[bob.output["user_id"]].balance == 75

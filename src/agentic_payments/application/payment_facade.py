"""Deterministic application facade over payment-domain operations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from agentic_payments.application.commands import (
    ApprovePaymentCommand,
    CheckBalanceCommand,
    CreateUserCommand,
    ExplainLastActionCommand,
    FraudCheckCommand,
    RejectPaymentCommand,
    RequestPaymentCommand,
    SecurityReviewCommand,
    ShowTransactionsCommand,
    TransferMoneyCommand,
)
from agentic_payments.application.memory_service import BusinessMemory
from agentic_payments.application.payment_domain_service import PaymentDomainService
from agentic_payments.application.results import AgentResult, FraudAssessment, SecurityReview
from agentic_payments.domain import (
    RiskLevel,
    StateInvariantError,
    Transaction,
    TransactionSnapshot,
)
from agentic_payments.infrastructure.concurrency.transaction_manager import (
    PaymentTransactionManager,
)


class _FraudAgentPort(Protocol):
    async def assess_transaction(self, snapshot: TransactionSnapshot) -> AgentResult: ...


class _SecurityAgentPort(Protocol):
    async def review_transaction(self, snapshot: TransactionSnapshot) -> AgentResult: ...

    async def review_system(self, state: Any) -> AgentResult: ...


class _ExplanationAgentPort(Protocol):
    async def explain_last_action(self, memory: BusinessMemory) -> AgentResult: ...


class _PolicyAgentPort(Protocol):
    async def evaluate_transfer(
        self,
        *,
        sender_id: str,
        amount: Decimal,
        balance_before: Decimal,
        previous_transactions: Sequence[Transaction],
        now: Any,
    ) -> AgentResult: ...


def _require_exact(value: object, expected: type[object], field_name: str) -> None:
    if type(value) is not expected:
        raise TypeError(f"{field_name} must be exactly {expected.__name__}")


def _schema_mapping(value: FraudAssessment | SecurityReview) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _serialize_snapshot(snapshot: TransactionSnapshot) -> dict[str, Any]:
    return {
        "transaction": snapshot.transaction.to_dict(),
        "sender_balance_before": format(snapshot.sender_balance_before, "f"),
        "sender_balance_after": format(snapshot.sender_balance_after, "f"),
        "receiver_balance_before": format(snapshot.receiver_balance_before, "f"),
        "receiver_balance_after": format(snapshot.receiver_balance_after, "f"),
        "recent_sender_transactions": [
            transaction.to_dict() for transaction in snapshot.recent_sender_transactions
        ],
    }


def _decimal_from_payload(value: object) -> Decimal:
    if not isinstance(value, str) or not value:
        raise ValueError("snapshot money value must be a non-empty string")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("snapshot money value is malformed") from error
    if not amount.is_finite():
        raise ValueError("snapshot money value must be finite")
    return amount


def _safe_post_processing_error(error: Exception) -> dict[str, Any]:
    return {
        "post_processing_error_type": type(error).__name__,
        "post_processing_error_message": "Committed operation post-processing failed",
        "financial_operation_committed": True,
    }


class PaymentFacade:
    """Expose the approved typed application operations without I/O."""

    def __init__(
        self,
        *,
        payment_service: PaymentDomainService,
        transaction_manager: PaymentTransactionManager,
        fraud_agent: _FraudAgentPort,
        security_agent: _SecurityAgentPort,
        explanation_agent: _ExplanationAgentPort,
        policy_agent: _PolicyAgentPort,
    ) -> None:
        if not isinstance(payment_service, PaymentDomainService):
            raise TypeError("payment_service must be PaymentDomainService")
        if not isinstance(transaction_manager, PaymentTransactionManager):
            raise TypeError("transaction_manager must be PaymentTransactionManager")
        self._payment_service = payment_service
        self._transaction_manager = transaction_manager
        self._fraud_agent = fraud_agent
        self._security_agent = security_agent
        self._explanation_agent = explanation_agent
        self._policy_agent = policy_agent

    async def create_user(self, command: CreateUserCommand) -> AgentResult:
        """Create one user through the authoritative domain service."""

        _require_exact(command, CreateUserCommand, "command")
        user = await self._payment_service.create_user(
            name=command.name,
            phone_number=command.phone_number,
            initial_balance=command.initial_balance,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        return AgentResult(
            "PaymentFacade",
            {
                "operation": "createUser",
                "user_id": user.user_id,
                "user": user.to_dict(),
            },
            1.0,
        )

    async def check_balance(self, command: CheckBalanceCommand) -> AgentResult:
        """Read one current wallet balance."""

        _require_exact(command, CheckBalanceCommand, "command")
        balance = await self._payment_service.get_balance(user_id=command.user_id)
        return AgentResult(
            "PaymentFacade",
            {
                "operation": "checkBalance",
                "user_id": command.user_id,
                "balance": format(balance, "f"),
                "currency": "ILS",
            },
            1.0,
        )

    async def transfer_money(self, command: TransferMoneyCommand) -> AgentResult:
        """Commit a transfer and run advisory post-processing after release."""

        _require_exact(command, TransferMoneyCommand, "command")
        balance = await self._payment_service.get_balance(user_id=command.sender_id)
        transactions = await self._payment_service.get_transactions(user_id=command.sender_id)
        policy_result = await self._policy_agent.evaluate_transfer(
            sender_id=command.sender_id,
            amount=command.amount,
            balance_before=balance,
            previous_transactions=transactions,
            now=command.context.requested_at,
        )
        snapshot = await self._payment_service.transfer_money(
            sender_id=command.sender_id,
            receiver_id=command.receiver_id,
            amount=command.amount,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        processed = await self._post_process_snapshot(
            snapshot,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        output = {
            "operation": "transferMoney",
            "transaction_id": processed[0].transaction.transaction_id,
            "snapshot": _serialize_snapshot(processed[0]),
            "fraud_assessment": processed[1],
            "security_review": processed[2],
            "post_processing_status": processed[3],
        }
        metadata = processed[4]
        if processed[3] == "completed":
            metadata = {
                "policy_review": self._safe_result_output(policy_result),
                "financial_operation_committed": True,
            }
        return AgentResult(
            "PaymentFacade",
            output,
            1.0 if processed[3] == "completed" else 0.85,
            metadata,
        )

    async def request_payment(self, command: RequestPaymentCommand) -> AgentResult:
        """Create one payment request through the domain service."""

        _require_exact(command, RequestPaymentCommand, "command")
        request = await self._payment_service.request_payment(
            requester_id=command.requester_id,
            payer_id=command.payer_id,
            amount=command.amount,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        return AgentResult(
            "PaymentFacade",
            {
                "operation": "requestPayment",
                "payment_request_id": request.request_id,
                "payment_request": request.to_dict(),
            },
            1.0,
        )

    async def approve_payment(self, command: ApprovePaymentCommand) -> AgentResult:
        """Approve a request and post-process its committed transfer."""

        _require_exact(command, ApprovePaymentCommand, "command")
        request, snapshot = await self._payment_service.approve_payment_request(
            request_id=command.request_id,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        processed = await self._post_process_snapshot(
            snapshot,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        return AgentResult(
            "PaymentFacade",
            {
                "operation": "approvePayment",
                "payment_request_id": request.request_id,
                "transaction_id": processed[0].transaction.transaction_id,
                "payment_request": request.to_dict(),
                "snapshot": _serialize_snapshot(processed[0]),
                "fraud_assessment": processed[1],
                "security_review": processed[2],
                "post_processing_status": processed[3],
            },
            1.0 if processed[3] == "completed" else 0.85,
            (
                {"financial_operation_committed": True}
                if processed[3] == "completed"
                else processed[4]
            ),
        )

    async def reject_payment(self, command: RejectPaymentCommand) -> AgentResult:
        """Reject one pending payment request."""

        _require_exact(command, RejectPaymentCommand, "command")
        request = await self._payment_service.reject_payment_request(
            request_id=command.request_id,
            idempotency_key=command.context.idempotency_key,
            correlation_id=command.context.correlation_id,
        )
        return AgentResult(
            "PaymentFacade",
            {
                "operation": "rejectPayment",
                "payment_request_id": request.request_id,
                "payment_request": request.to_dict(),
            },
            1.0,
        )

    async def show_transactions(self, command: ShowTransactionsCommand) -> AgentResult:
        """Read a newest-first serialized transaction list."""

        _require_exact(command, ShowTransactionsCommand, "command")
        transactions = await self._payment_service.get_transactions(user_id=command.user_id)
        return AgentResult(
            "PaymentFacade",
            {
                "operation": "showTransactions",
                "user_id": command.user_id,
                "transactions": [transaction.to_dict() for transaction in transactions],
            },
            1.0,
        )

    async def fraud_check(self, command: FraudCheckCommand) -> AgentResult:
        """Run a read-only fraud assessment against the original snapshot."""

        _require_exact(command, FraudCheckCommand, "command")
        return await self._fraud_agent.assess_transaction(
            self._find_snapshot(command.transaction_id)
        )

    async def security_review(self, command: SecurityReviewCommand) -> AgentResult:
        """Run a transaction-specific or whole-state read-only review."""

        _require_exact(command, SecurityReviewCommand, "command")
        if command.transaction_id is not None:
            return await self._security_agent.review_transaction(
                self._find_snapshot(command.transaction_id)
            )
        return await self._security_agent.review_system(self._transaction_manager.current_state)

    async def explain_last_action(
        self,
        command: ExplainLastActionCommand,
        *,
        memory: BusinessMemory,
    ) -> AgentResult:
        """Explain the supplied immutable business-memory snapshot."""

        _require_exact(command, ExplainLastActionCommand, "command")
        if not isinstance(memory, BusinessMemory):
            raise TypeError("memory must be BusinessMemory")
        return await self._explanation_agent.explain_last_action(memory)

    @staticmethod
    def _safe_result_output(result: AgentResult) -> Any:
        output = result.output
        if isinstance(output, (FraudAssessment, SecurityReview)):
            return _schema_mapping(output)
        if isinstance(output, Mapping):
            return dict(output)
        return None

    async def _post_process_snapshot(
        self,
        snapshot: TransactionSnapshot,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> tuple[
        TransactionSnapshot,
        dict[str, Any],
        dict[str, Any] | None,
        str,
        dict[str, Any],
    ]:
        assessment: FraudAssessment | None = None
        security: SecurityReview | None = None
        try:
            fraud_result = await self._fraud_agent.assess_transaction(snapshot)
            if not isinstance(fraud_result, AgentResult) or not isinstance(
                fraud_result.output, FraudAssessment
            ):
                raise TypeError("fraud agent output must be FraudAssessment")
            assessment = fraud_result.output
            updated = await self._payment_service.annotate_transaction_risk(
                transaction_id=snapshot.transaction.transaction_id,
                score=assessment.risk_score,
                level=assessment.risk_level,
                reasons=assessment.reasons,
                flagged=assessment.risk_level is RiskLevel.HIGH,
                idempotency_key=(f"{idempotency_key}:risk:{snapshot.transaction.transaction_id}"),
                correlation_id=correlation_id,
            )
            updated_snapshot = replace(snapshot, transaction=updated)
            if assessment.requires_security_review:
                security_result = await self._security_agent.review_transaction(updated_snapshot)
                if not isinstance(security_result, AgentResult) or not isinstance(
                    security_result.output, SecurityReview
                ):
                    raise TypeError("security agent output must be SecurityReview")
                security = security_result.output
            return (
                updated_snapshot,
                _schema_mapping(assessment),
                _schema_mapping(security) if security is not None else None,
                "completed",
                {"financial_operation_committed": True},
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            fallback = (
                _schema_mapping(assessment)
                if assessment is not None
                else {
                    "transaction_id": snapshot.transaction.transaction_id,
                    "risk_score": 0,
                    "risk_level": RiskLevel.LOW.value,
                    "reasons": ["post_processing_unavailable"],
                    "requires_security_review": False,
                }
            )
            return (
                snapshot,
                fallback,
                None,
                "degraded",
                _safe_post_processing_error(error),
            )

    def _find_snapshot(self, transaction_id: str) -> TransactionSnapshot:
        state = self._transaction_manager.current_state
        current = state.transactions.get(transaction_id)
        if current is None:
            raise StateInvariantError(
                "Transaction snapshot is unavailable",
                context={"transaction_id": transaction_id},
            )
        for key in sorted(state.idempotency_records):
            payload = state.idempotency_records[key].result_payload
            if not isinstance(payload, Mapping):
                continue
            result_type = payload.get("result_type")
            if result_type not in {"TransactionSnapshot", "ApprovedPaymentRequest"}:
                continue
            candidate = payload.get("snapshot")
            if not isinstance(candidate, Mapping):
                continue
            old_transaction = candidate.get("transaction")
            if (
                not isinstance(old_transaction, Mapping)
                or old_transaction.get("transaction_id") != transaction_id
            ):
                continue
            try:
                recent_data = candidate["recent_sender_transactions"]
                if not isinstance(recent_data, list):
                    raise ValueError("recent transactions must be a list")
                return TransactionSnapshot(
                    transaction=current,
                    sender_balance_before=_decimal_from_payload(candidate["sender_balance_before"]),
                    sender_balance_after=_decimal_from_payload(candidate["sender_balance_after"]),
                    receiver_balance_before=_decimal_from_payload(
                        candidate["receiver_balance_before"]
                    ),
                    receiver_balance_after=_decimal_from_payload(
                        candidate["receiver_balance_after"]
                    ),
                    recent_sender_transactions=tuple(
                        Transaction.from_dict(item) for item in recent_data
                    ),
                )
            except (KeyError, TypeError, ValueError):
                break
        raise StateInvariantError(
            "Transaction snapshot is unavailable",
            context={"transaction_id": transaction_id},
        )

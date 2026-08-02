"""Deterministic payment operations coordinated through locks and transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, NoReturn, cast

from agentic_payments.application.ports import Clock, IdGenerator
from agentic_payments.application.state import ApplicationState, IdempotencyRecord
from agentic_payments.domain import (
    AuditEvent,
    DuplicatePhoneNumberError,
    IdempotencyConflictError,
    InvalidAmountError,
    InvalidInitialBalanceError,
    PaymentDomainError,
    PaymentRequest,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestNotFoundError,
    PaymentRequestStatus,
    RiskLevel,
    SelfTransferError,
    StateInvariantError,
    Transaction,
    TransactionSnapshot,
    TransactionStatus,
    TransferPolicy,
    User,
    UserAlreadyExistsError,
    UserNotFoundError,
    Wallet,
    WalletNotFoundError,
)
from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    LockKey,
    LockScope,
    PaymentTransactionManager,
    PaymentUnitOfWork,
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty stripped string")
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("name must be a non-empty string")
    return value.strip()


def _normalize_phone(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("phone_number must be a non-empty string")
    candidate = value.strip()
    if candidate.startswith("+"):
        candidate = candidate[1:]
    for removable in (" ", "-", "(", ")"):
        candidate = candidate.replace(removable, "")
    if (
        not candidate
        or not candidate.isascii()
        or not candidate.isdigit()
        or not 7 <= len(candidate) <= 15
    ):
        raise ValueError("phone_number must normalize to 7 to 15 ASCII digits")
    return candidate


def _money_parameter(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvalidAmountError(cast(Decimal, value), f"{field} must be a Decimal")
    if not value.is_finite():
        raise InvalidAmountError(value, f"{field} must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise InvalidAmountError(value, f"{field} must have at most two fractional digits")
    return value


def _initial_balance(value: object) -> Decimal:
    try:
        balance = _money_parameter(value, "initial_balance")
    except InvalidAmountError as error:
        raise InvalidInitialBalanceError(cast(Decimal, value)) from error
    if balance < 0:
        raise InvalidInitialBalanceError(balance)
    return balance


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("fingerprint dictionary keys must be strings")
            converted[key] = _canonical_value(nested)
        return converted
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("fingerprint Decimal values must be finite")
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported fingerprint value: {type(value).__name__}")


def _fingerprint(operation_type: str, parameters: Mapping[str, Any]) -> str:
    payload = {
        "operation_type": operation_type,
        "parameters": _canonical_value(parameters),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _state_failure(message: str, **context: Any) -> NoReturn:
    raise StateInvariantError(message, context=context)


def _payload_mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        _state_failure("idempotency result payload field is missing or malformed", field=field)
    return value


def _payload_decimal(payload: Mapping[str, Any], field: str) -> Decimal:
    value = payload.get(field)
    if not isinstance(value, str):
        _state_failure("idempotency result decimal is missing or malformed", field=field)
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise StateInvariantError(
            "idempotency result decimal is malformed",
            context={"field": field},
        ) from error
    if not parsed.is_finite():
        _state_failure("idempotency result decimal must be finite", field=field)
    return parsed


def _snapshot_payload(snapshot: TransactionSnapshot) -> dict[str, Any]:
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


def _restore_entity(
    payload: Mapping[str, Any],
    *,
    expected_type: str,
    field: str,
    factory: Any,
) -> Any:
    if payload.get("result_type") != expected_type:
        _state_failure(
            "idempotency result type is missing or unexpected",
            expected_type=expected_type,
        )
    serialized = _payload_mapping(payload, field)
    try:
        return factory(serialized)
    except (KeyError, TypeError, ValueError, PaymentDomainError) as error:
        raise StateInvariantError(
            "idempotency result entity is malformed",
            context={"expected_type": expected_type, "field": field},
        ) from error


def _restore_snapshot(serialized: Mapping[str, Any]) -> TransactionSnapshot:
    transaction_data = _payload_mapping(serialized, "transaction")
    recent_data = serialized.get("recent_sender_transactions")
    if not isinstance(recent_data, list):
        _state_failure(
            "idempotency result snapshot history is missing or malformed",
            field="recent_sender_transactions",
        )
    try:
        transaction = Transaction.from_dict(transaction_data)
        recent = tuple(
            Transaction.from_dict(item) for item in recent_data if isinstance(item, Mapping)
        )
        if len(recent) != len(recent_data):
            _state_failure(
                "idempotency result snapshot history is malformed",
                field="recent_sender_transactions",
            )
        return TransactionSnapshot(
            transaction=transaction,
            sender_balance_before=_payload_decimal(serialized, "sender_balance_before"),
            sender_balance_after=_payload_decimal(serialized, "sender_balance_after"),
            receiver_balance_before=_payload_decimal(serialized, "receiver_balance_before"),
            receiver_balance_after=_payload_decimal(serialized, "receiver_balance_after"),
            recent_sender_transactions=recent,
        )
    except StateInvariantError:
        raise
    except (KeyError, TypeError, ValueError, PaymentDomainError) as error:
        raise StateInvariantError(
            "idempotency transaction snapshot is malformed",
            context={"result_type": "TransactionSnapshot"},
        ) from error


class PaymentDomainService:
    """Execute deterministic payment operations through locks and a Unit of Work."""

    def __init__(
        self,
        *,
        transaction_manager: PaymentTransactionManager,
        lock_manager: AsyncResourceLockManager,
        transfer_policy: TransferPolicy,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._transaction_manager = transaction_manager
        self._lock_manager = lock_manager
        self._transfer_policy = transfer_policy
        self._clock = clock
        self._id_generator = id_generator

    def _now(self) -> datetime:
        return _aware(self._clock.now(), "clock time")

    def _generated_id(self, value: object, field: str) -> str:
        return _text(value, field)

    def _existing_payload(
        self,
        state: ApplicationState,
        *,
        idempotency_key: str,
        operation_type: str,
        fingerprint: str,
    ) -> Mapping[str, Any] | None:
        record = state.idempotency_records.get(idempotency_key)
        if record is None:
            return None
        if record.operation_type != operation_type or record.request_fingerprint != fingerprint:
            raise IdempotencyConflictError(idempotency_key)
        if record.result_payload is None:
            _state_failure(
                "successful idempotency record has no result payload",
                idempotency_key=idempotency_key,
                operation_type=operation_type,
            )
        return record.result_payload

    def _record(
        self,
        unit: PaymentUnitOfWork,
        *,
        idempotency_key: str,
        operation_type: str,
        fingerprint: str,
        result_reference: str,
        created_at: datetime,
        result_payload: Mapping[str, Any],
    ) -> None:
        unit.state.idempotency_records[idempotency_key] = IdempotencyRecord(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            request_fingerprint=fingerprint,
            result_reference=result_reference,
            created_at=created_at,
            result_payload=result_payload,
        )

    def _audit(
        self,
        unit: PaymentUnitOfWork,
        *,
        correlation_id: str,
        action: str,
        status: str,
        occurred_at: datetime,
        details: Mapping[str, Any],
    ) -> None:
        event_id = self._generated_id(
            self._id_generator.new_audit_event_id(),
            "generated audit event ID",
        )
        if event_id in unit.state.pending_audit_events:
            _state_failure("generated audit event ID already exists", event_id=event_id)
        unit.append_audit(
            AuditEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                action=action,
                status=status,
                occurred_at=occurred_at,
                actor="system",
                details=details,
            )
        )

    def _require_user(self, state: ApplicationState, user_id: str) -> User:
        user = state.users.get(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def _require_wallet(self, state: ApplicationState, user_id: str) -> Wallet:
        wallet = state.wallets.get(user_id)
        if wallet is None:
            raise WalletNotFoundError(user_id)
        return wallet

    def _prior_sender_transactions(
        self,
        state: ApplicationState,
        sender_id: str,
    ) -> list[Transaction]:
        return [
            transaction
            for transaction in state.transactions.values()
            if transaction.sender_id == sender_id
            and transaction.status in {TransactionStatus.COMPLETED, TransactionStatus.FLAGGED}
        ]

    def _recent_sender_transactions(
        self,
        state: ApplicationState,
        *,
        sender_id: str,
        now: datetime,
    ) -> tuple[Transaction, ...]:
        window_start = now - timedelta(minutes=self._transfer_policy.rapid_transfer_window_minutes)
        recent = [
            transaction
            for transaction in state.transactions.values()
            if transaction.sender_id == sender_id and window_start <= transaction.created_at <= now
        ]
        return tuple(sorted(recent, key=lambda item: (item.created_at, item.transaction_id)))

    def _new_transaction(
        self,
        unit: PaymentUnitOfWork,
        *,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        occurred_at: datetime,
        correlation_id: str,
        idempotency_key: str,
    ) -> Transaction:
        transaction_id = self._generated_id(
            self._id_generator.new_transaction_id(),
            "generated transaction ID",
        )
        if transaction_id in unit.state.transactions:
            _state_failure(
                "generated transaction ID already exists",
                transaction_id=transaction_id,
            )
        return Transaction(
            transaction_id=transaction_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=amount,
            created_at=occurred_at,
            status=TransactionStatus.COMPLETED,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            risk_reasons=(),
            failure_reason=None,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def _transfer_snapshot(
        self,
        unit: PaymentUnitOfWork,
        *,
        sender: Wallet,
        receiver: Wallet,
        amount: Decimal,
        now: datetime,
        correlation_id: str,
        idempotency_key: str,
    ) -> TransactionSnapshot:
        previous = self._prior_sender_transactions(unit.state, sender.user_id)
        self._transfer_policy.validate_amount(amount)
        self._transfer_policy.validate_single_transfer_limit(amount)
        self._transfer_policy.validate_daily_limit(
            previous_transactions=previous,
            amount=amount,
            now=now,
        )
        recent = self._recent_sender_transactions(
            unit.state,
            sender_id=sender.user_id,
            now=now,
        )
        updated_sender = sender.debit(amount, now)
        updated_receiver = receiver.credit(amount, now)
        transaction = self._new_transaction(
            unit,
            sender_id=sender.user_id,
            receiver_id=receiver.user_id,
            amount=amount,
            occurred_at=now,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        unit.state.wallets[sender.user_id] = updated_sender
        unit.state.wallets[receiver.user_id] = updated_receiver
        unit.state.transactions[transaction.transaction_id] = transaction
        return TransactionSnapshot(
            transaction=transaction,
            sender_balance_before=sender.balance,
            sender_balance_after=updated_sender.balance,
            receiver_balance_before=receiver.balance,
            receiver_balance_after=updated_receiver.balance,
            recent_sender_transactions=recent,
        )

    def _transfer_audit_details(
        self,
        snapshot: TransactionSnapshot,
    ) -> dict[str, Any]:
        return {
            "transaction_id": snapshot.transaction.transaction_id,
            "sender_id": snapshot.transaction.sender_id,
            "receiver_id": snapshot.transaction.receiver_id,
            "amount": format(snapshot.transaction.amount, "f"),
            "sender_balance_before": format(snapshot.sender_balance_before, "f"),
            "sender_balance_after": format(snapshot.sender_balance_after, "f"),
            "receiver_balance_before": format(snapshot.receiver_balance_before, "f"),
            "receiver_balance_after": format(snapshot.receiver_balance_after, "f"),
        }

    async def create_user(
        self,
        *,
        name: str,
        phone_number: str,
        initial_balance: Decimal,
        idempotency_key: str,
        correlation_id: str,
    ) -> User:
        """Create one user and wallet atomically."""

        normalized_name = _name(name)
        normalized_phone = _normalize_phone(phone_number)
        balance = _initial_balance(initial_balance)
        key = _text(idempotency_key, "idempotency_key")
        correlation = _text(correlation_id, "correlation_id")
        operation = "createUser"
        fingerprint = _fingerprint(
            operation,
            {
                "name": normalized_name,
                "phone_number": normalized_phone,
                "initial_balance": balance,
            },
        )
        locks = {
            LockKey(LockScope.IDEMPOTENCY, key),
            LockKey(LockScope.USER_REGISTRY, "users"),
            LockKey(LockScope.USER_REGISTRY, f"phone:{normalized_phone}"),
        }
        async with self._lock_manager.acquire_many(locks):  # noqa: SIM117
            async with self._transaction_manager.transaction() as unit:
                payload = self._existing_payload(
                    unit.state,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                )
                if payload is not None:
                    return cast(
                        User,
                        _restore_entity(
                            payload,
                            expected_type="User",
                            field="user",
                            factory=User.from_dict,
                        ),
                    )
                if any(user.phone_number == normalized_phone for user in unit.state.users.values()):
                    raise DuplicatePhoneNumberError(normalized_phone)
                user_id = self._generated_id(
                    self._id_generator.new_user_id(),
                    "generated user ID",
                )
                if user_id in unit.state.users:
                    raise UserAlreadyExistsError(user_id)
                now = self._now()
                user = User(user_id, normalized_name, normalized_phone, now)
                wallet = Wallet(user_id, balance, "ILS", 0, now)
                unit.state.users[user_id] = user
                unit.state.wallets[user_id] = wallet
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="createUser",
                    status="SUCCESS",
                    occurred_at=now,
                    details={
                        "user_id": user_id,
                        "phone_last4": normalized_phone[-4:],
                        "initial_balance": format(balance, "f"),
                        "currency": "ILS",
                    },
                )
                self._record(
                    unit,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                    result_reference=user_id,
                    created_at=now,
                    result_payload={"result_type": "User", "user": user.to_dict()},
                )
                unit.validate_invariants()
                await unit.commit()
                return user

    async def get_balance(self, *, user_id: str) -> Decimal:
        """Return one current immutable wallet balance."""

        checked_id = _text(user_id, "user_id")
        state = self._transaction_manager.current_state
        self._require_user(state, checked_id)
        return self._require_wallet(state, checked_id).balance

    async def get_transactions(self, *, user_id: str) -> list[Transaction]:
        """Return one user's transactions in deterministic newest-first order."""

        checked_id = _text(user_id, "user_id")
        state = self._transaction_manager.current_state
        self._require_user(state, checked_id)
        self._require_wallet(state, checked_id)
        transactions = [
            transaction
            for transaction in state.transactions.values()
            if checked_id in {transaction.sender_id, transaction.receiver_id}
        ]
        return sorted(
            transactions,
            key=lambda item: (item.created_at, item.transaction_id),
            reverse=True,
        )

    async def transfer_money(
        self,
        *,
        sender_id: str,
        receiver_id: str,
        amount: Decimal,
        idempotency_key: str,
        correlation_id: str,
    ) -> TransactionSnapshot:
        """Transfer money atomically between two distinct wallets."""

        sender_key = _text(sender_id, "sender_id")
        receiver_key = _text(receiver_id, "receiver_id")
        if sender_key == receiver_key:
            raise SelfTransferError(sender_key)
        checked_amount = _money_parameter(amount, "amount")
        key = _text(idempotency_key, "idempotency_key")
        correlation = _text(correlation_id, "correlation_id")
        operation = "transferMoney"
        fingerprint = _fingerprint(
            operation,
            {
                "sender_id": sender_key,
                "receiver_id": receiver_key,
                "amount": checked_amount,
            },
        )
        locks = {
            LockKey(LockScope.IDEMPOTENCY, key),
            LockKey(LockScope.WALLET, sender_key),
            LockKey(LockScope.WALLET, receiver_key),
        }
        async with self._lock_manager.acquire_many(locks):  # noqa: SIM117
            async with self._transaction_manager.transaction() as unit:
                payload = self._existing_payload(
                    unit.state,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                )
                if payload is not None:
                    if payload.get("result_type") != "TransactionSnapshot":
                        _state_failure(
                            "idempotency result type is missing or unexpected",
                            expected_type="TransactionSnapshot",
                        )
                    return _restore_snapshot(_payload_mapping(payload, "snapshot"))
                self._require_user(unit.state, sender_key)
                self._require_user(unit.state, receiver_key)
                sender = self._require_wallet(unit.state, sender_key)
                receiver = self._require_wallet(unit.state, receiver_key)
                now = self._now()
                snapshot = self._transfer_snapshot(
                    unit,
                    sender=sender,
                    receiver=receiver,
                    amount=checked_amount,
                    now=now,
                    correlation_id=correlation,
                    idempotency_key=key,
                )
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="transferMoney",
                    status="SUCCESS",
                    occurred_at=now,
                    details=self._transfer_audit_details(snapshot),
                )
                self._record(
                    unit,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                    result_reference=snapshot.transaction.transaction_id,
                    created_at=now,
                    result_payload={
                        "result_type": "TransactionSnapshot",
                        "snapshot": _snapshot_payload(snapshot),
                    },
                )
                unit.validate_invariants()
                await unit.commit()
                return snapshot

    async def request_payment(
        self,
        *,
        requester_id: str,
        payer_id: str,
        amount: Decimal,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentRequest:
        """Create one pending payment request without changing balances."""

        requester_key = _text(requester_id, "requester_id")
        payer_key = _text(payer_id, "payer_id")
        if requester_key == payer_key:
            raise SelfTransferError(requester_key)
        checked_amount = _money_parameter(amount, "amount")
        key = _text(idempotency_key, "idempotency_key")
        correlation = _text(correlation_id, "correlation_id")
        operation = "requestPayment"
        fingerprint = _fingerprint(
            operation,
            {
                "requester_id": requester_key,
                "payer_id": payer_key,
                "amount": checked_amount,
            },
        )
        locks = {
            LockKey(LockScope.IDEMPOTENCY, key),
            LockKey(LockScope.PAYMENT_REQUEST, "registry"),
            LockKey(LockScope.WALLET, requester_key),
            LockKey(LockScope.WALLET, payer_key),
        }
        async with self._lock_manager.acquire_many(locks):  # noqa: SIM117
            async with self._transaction_manager.transaction() as unit:
                payload = self._existing_payload(
                    unit.state,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                )
                if payload is not None:
                    return cast(
                        PaymentRequest,
                        _restore_entity(
                            payload,
                            expected_type="PaymentRequest",
                            field="payment_request",
                            factory=PaymentRequest.from_dict,
                        ),
                    )
                self._require_user(unit.state, requester_key)
                self._require_user(unit.state, payer_key)
                self._require_wallet(unit.state, requester_key)
                self._require_wallet(unit.state, payer_key)
                self._transfer_policy.validate_amount(checked_amount)
                request_id = self._generated_id(
                    self._id_generator.new_payment_request_id(),
                    "generated payment request ID",
                )
                if request_id in unit.state.payment_requests:
                    _state_failure(
                        "generated payment request ID already exists",
                        request_id=request_id,
                    )
                now = self._now()
                request = PaymentRequest(
                    request_id=request_id,
                    requester_id=requester_key,
                    payer_id=payer_key,
                    amount=checked_amount,
                    status=PaymentRequestStatus.PENDING,
                    created_at=now,
                    resolved_at=None,
                    related_transaction_id=None,
                    correlation_id=correlation,
                )
                unit.state.payment_requests[request_id] = request
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="requestPayment",
                    status="SUCCESS",
                    occurred_at=now,
                    details={
                        "request_id": request_id,
                        "requester_id": requester_key,
                        "payer_id": payer_key,
                        "amount": format(checked_amount, "f"),
                    },
                )
                self._record(
                    unit,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                    result_reference=request_id,
                    created_at=now,
                    result_payload={
                        "result_type": "PaymentRequest",
                        "payment_request": request.to_dict(),
                    },
                )
                unit.validate_invariants()
                await unit.commit()
                return request

    async def approve_payment_request(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> tuple[PaymentRequest, TransactionSnapshot]:
        """Approve a pending request and transfer payer funds atomically."""

        request_key = _text(request_id, "request_id")
        key = _text(idempotency_key, "idempotency_key")
        correlation = _text(correlation_id, "correlation_id")
        operation = "approvePayment"
        fingerprint = _fingerprint(operation, {"request_id": request_key})
        preliminary = self._transaction_manager.current_state.payment_requests.get(request_key)
        if preliminary is None:
            raise PaymentRequestNotFoundError(request_key)
        locks = {
            LockKey(LockScope.IDEMPOTENCY, key),
            LockKey(LockScope.PAYMENT_REQUEST, request_key),
            LockKey(LockScope.WALLET, preliminary.payer_id),
            LockKey(LockScope.WALLET, preliminary.requester_id),
        }
        async with self._lock_manager.acquire_many(locks):  # noqa: SIM117
            async with self._transaction_manager.transaction() as unit:
                payload = self._existing_payload(
                    unit.state,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                )
                if payload is not None:
                    if payload.get("result_type") != "ApprovedPaymentRequest":
                        _state_failure(
                            "idempotency result type is missing or unexpected",
                            expected_type="ApprovedPaymentRequest",
                        )
                    restored_request = cast(
                        PaymentRequest,
                        _restore_entity(
                            payload,
                            expected_type="ApprovedPaymentRequest",
                            field="payment_request",
                            factory=PaymentRequest.from_dict,
                        ),
                    )
                    snapshot = _restore_snapshot(_payload_mapping(payload, "snapshot"))
                    return restored_request, snapshot
                request = unit.state.payment_requests.get(request_key)
                if request is None:
                    raise PaymentRequestNotFoundError(request_key)
                if (
                    request.payer_id != preliminary.payer_id
                    or request.requester_id != preliminary.requester_id
                ):
                    _state_failure(
                        "payment request participants changed during approval",
                        request_id=request_key,
                    )
                if not request.is_pending():
                    raise PaymentRequestAlreadyResolvedError(request.request_id, request.status)
                self._require_user(unit.state, request.payer_id)
                self._require_user(unit.state, request.requester_id)
                payer = self._require_wallet(unit.state, request.payer_id)
                requester = self._require_wallet(unit.state, request.requester_id)
                now = self._now()
                snapshot = self._transfer_snapshot(
                    unit,
                    sender=payer,
                    receiver=requester,
                    amount=request.amount,
                    now=now,
                    correlation_id=correlation,
                    idempotency_key=key,
                )
                approved = request.approve(
                    transaction_id=snapshot.transaction.transaction_id,
                    resolved_at=now,
                )
                unit.state.payment_requests[request_key] = approved
                transfer_details = self._transfer_audit_details(snapshot)
                transfer_details["source"] = "paymentRequest"
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="transferMoney",
                    status="SUCCESS",
                    occurred_at=now,
                    details=transfer_details,
                )
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="approvePayment",
                    status="SUCCESS",
                    occurred_at=now,
                    details={
                        "request_id": request_key,
                        "transaction_id": snapshot.transaction.transaction_id,
                        "requester_id": request.requester_id,
                        "payer_id": request.payer_id,
                        "amount": format(request.amount, "f"),
                    },
                )
                self._record(
                    unit,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                    result_reference=request_key,
                    created_at=now,
                    result_payload={
                        "result_type": "ApprovedPaymentRequest",
                        "payment_request": approved.to_dict(),
                        "snapshot": _snapshot_payload(snapshot),
                    },
                )
                unit.validate_invariants()
                await unit.commit()
                return approved, snapshot

    async def reject_payment_request(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> PaymentRequest:
        """Reject one pending payment request without changing wallets."""

        request_key = _text(request_id, "request_id")
        key = _text(idempotency_key, "idempotency_key")
        correlation = _text(correlation_id, "correlation_id")
        operation = "rejectPayment"
        fingerprint = _fingerprint(operation, {"request_id": request_key})
        locks = {
            LockKey(LockScope.IDEMPOTENCY, key),
            LockKey(LockScope.PAYMENT_REQUEST, request_key),
        }
        async with self._lock_manager.acquire_many(locks):  # noqa: SIM117
            async with self._transaction_manager.transaction() as unit:
                payload = self._existing_payload(
                    unit.state,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                )
                if payload is not None:
                    return cast(
                        PaymentRequest,
                        _restore_entity(
                            payload,
                            expected_type="PaymentRequest",
                            field="payment_request",
                            factory=PaymentRequest.from_dict,
                        ),
                    )
                request = unit.state.payment_requests.get(request_key)
                if request is None:
                    raise PaymentRequestNotFoundError(request_key)
                if not request.is_pending():
                    raise PaymentRequestAlreadyResolvedError(request.request_id, request.status)
                now = self._now()
                rejected = request.reject(resolved_at=now)
                unit.state.payment_requests[request_key] = rejected
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="rejectPayment",
                    status="SUCCESS",
                    occurred_at=now,
                    details={
                        "request_id": request_key,
                        "requester_id": request.requester_id,
                        "payer_id": request.payer_id,
                        "amount": format(request.amount, "f"),
                    },
                )
                self._record(
                    unit,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                    result_reference=request_key,
                    created_at=now,
                    result_payload={
                        "result_type": "PaymentRequest",
                        "payment_request": rejected.to_dict(),
                    },
                )
                unit.validate_invariants()
                await unit.commit()
                return rejected

    async def annotate_transaction_risk(
        self,
        *,
        transaction_id: str,
        score: int,
        level: RiskLevel,
        reasons: Sequence[str],
        flagged: bool,
        idempotency_key: str,
        correlation_id: str,
    ) -> Transaction:
        """Replace one transaction's risk assessment idempotently."""

        transaction_key = _text(transaction_id, "transaction_id")
        key = _text(idempotency_key, "idempotency_key")
        correlation = _text(correlation_id, "correlation_id")
        if not isinstance(level, RiskLevel):
            raise ValueError("level must be a RiskLevel")
        if isinstance(reasons, (str, bytes)):
            raise ValueError("reasons must be a sequence of strings")
        normalized_reasons = tuple(reasons)
        operation = "annotateTransactionRisk"
        fingerprint = _fingerprint(
            operation,
            {
                "transaction_id": transaction_key,
                "score": score,
                "level": level,
                "reasons": normalized_reasons,
                "flagged": flagged,
            },
        )
        locks = {
            LockKey(LockScope.IDEMPOTENCY, key),
            LockKey(LockScope.TRANSACTION, transaction_key),
        }
        async with self._lock_manager.acquire_many(locks):  # noqa: SIM117
            async with self._transaction_manager.transaction() as unit:
                payload = self._existing_payload(
                    unit.state,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                )
                if payload is not None:
                    return cast(
                        Transaction,
                        _restore_entity(
                            payload,
                            expected_type="Transaction",
                            field="transaction",
                            factory=Transaction.from_dict,
                        ),
                    )
                transaction = unit.state.transactions.get(transaction_key)
                if transaction is None:
                    _state_failure(
                        "transaction does not exist for risk annotation",
                        transaction_id=transaction_key,
                    )
                updated = transaction.with_risk_assessment(
                    score=score,
                    level=level,
                    reasons=normalized_reasons,
                    flagged=flagged,
                )
                now = self._now()
                unit.state.transactions[transaction_key] = updated
                self._audit(
                    unit,
                    correlation_id=correlation,
                    action="annotateTransactionRisk",
                    status="FLAGGED" if flagged else "COMPLETED",
                    occurred_at=now,
                    details={
                        "transaction_id": transaction_key,
                        "risk_score": score,
                        "risk_level": level.value,
                        "reasons": list(normalized_reasons),
                    },
                )
                self._record(
                    unit,
                    idempotency_key=key,
                    operation_type=operation,
                    fingerprint=fingerprint,
                    result_reference=transaction_key,
                    created_at=now,
                    result_payload={
                        "result_type": "Transaction",
                        "transaction": updated.to_dict(),
                    },
                )
                unit.validate_invariants()
                await unit.commit()
                return updated

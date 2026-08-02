"""Typed business exceptions raised by the payment domain."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

from agentic_payments.domain.enums import PaymentRequestStatus


class PaymentDomainError(Exception):
    """Base class for deterministic payment-domain failures."""

    code = "payment_domain_error"

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self._message = message
        self._context = MappingProxyType(dict(context or {}))
        super().__init__(message)

    @property
    def message(self) -> str:
        """Return the immutable human-readable error message."""

        return self._message

    @property
    def context(self) -> Mapping[str, Any]:
        """Return immutable structured error context."""

        return self._context


class UserNotFoundError(PaymentDomainError):
    """Raised when a requested user does not exist."""

    code = "user_not_found"

    def __init__(self, user_id: str) -> None:
        super().__init__(f"User not found: {user_id}", context={"user_id": user_id})

    @property
    def user_id(self) -> str:
        """Return the missing user identifier."""

        return cast(str, self.context["user_id"])


class UserAlreadyExistsError(PaymentDomainError):
    """Raised when a user identifier is already registered."""

    code = "user_already_exists"

    def __init__(self, user_id: str) -> None:
        super().__init__(f"User already exists: {user_id}", context={"user_id": user_id})

    @property
    def user_id(self) -> str:
        """Return the duplicate user identifier."""

        return cast(str, self.context["user_id"])


class DuplicatePhoneNumberError(PaymentDomainError):
    """Raised when a normalized phone number is already registered."""

    code = "duplicate_phone_number"

    def __init__(self, phone_number: str) -> None:
        super().__init__(
            f"Phone number already exists: {phone_number}",
            context={"phone_number": phone_number},
        )

    @property
    def phone_number(self) -> str:
        """Return the duplicate normalized phone number."""

        return cast(str, self.context["phone_number"])


class InvalidInitialBalanceError(PaymentDomainError):
    """Raised when a requested initial balance is invalid."""

    code = "invalid_initial_balance"

    def __init__(self, balance: Decimal) -> None:
        super().__init__(
            f"Invalid initial balance: {balance}",
            context={"balance": balance},
        )

    @property
    def balance(self) -> Decimal:
        """Return the invalid balance."""

        return cast(Decimal, self.context["balance"])


class InvalidAmountError(PaymentDomainError):
    """Raised when a monetary amount violates domain rules."""

    code = "invalid_amount"

    def __init__(self, amount: Decimal, reason: str) -> None:
        super().__init__(
            f"Invalid amount {amount}: {reason}",
            context={"amount": amount, "reason": reason},
        )

    @property
    def amount(self) -> Decimal:
        """Return the rejected amount."""

        return cast(Decimal, self.context["amount"])

    @property
    def reason(self) -> str:
        """Return the rejection reason."""

        return cast(str, self.context["reason"])


class InsufficientFundsError(PaymentDomainError):
    """Raised when a wallet cannot cover a debit."""

    code = "insufficient_funds"

    def __init__(self, user_id: str, available: Decimal, required: Decimal) -> None:
        super().__init__(
            f"Insufficient funds for user {user_id}",
            context={"user_id": user_id, "available": available, "required": required},
        )

    @property
    def user_id(self) -> str:
        """Return the wallet owner identifier."""

        return cast(str, self.context["user_id"])

    @property
    def available(self) -> Decimal:
        """Return the available balance."""

        return cast(Decimal, self.context["available"])

    @property
    def required(self) -> Decimal:
        """Return the required debit."""

        return cast(Decimal, self.context["required"])


class SelfTransferError(PaymentDomainError):
    """Raised when sender and receiver are the same user."""

    code = "self_transfer"

    def __init__(self, user_id: str) -> None:
        super().__init__(
            f"Self-transfer is not allowed for user {user_id}",
            context={"user_id": user_id},
        )

    @property
    def user_id(self) -> str:
        """Return the duplicated participant identifier."""

        return cast(str, self.context["user_id"])


class WalletNotFoundError(PaymentDomainError):
    """Raised when a requested wallet does not exist."""

    code = "wallet_not_found"

    def __init__(self, user_id: str) -> None:
        super().__init__(f"Wallet not found for user {user_id}", context={"user_id": user_id})

    @property
    def user_id(self) -> str:
        """Return the wallet owner identifier."""

        return cast(str, self.context["user_id"])


class PaymentRequestNotFoundError(PaymentDomainError):
    """Raised when a requested payment request does not exist."""

    code = "payment_request_not_found"

    def __init__(self, request_id: str) -> None:
        super().__init__(
            f"Payment request not found: {request_id}",
            context={"request_id": request_id},
        )

    @property
    def request_id(self) -> str:
        """Return the missing request identifier."""

        return cast(str, self.context["request_id"])


class PaymentRequestAlreadyResolvedError(PaymentDomainError):
    """Raised when a resolved payment request is resolved again."""

    code = "payment_request_already_resolved"

    def __init__(self, request_id: str, status: PaymentRequestStatus) -> None:
        super().__init__(
            f"Payment request {request_id} is already {status.value}",
            context={"request_id": request_id, "status": status},
        )

    @property
    def request_id(self) -> str:
        """Return the resolved request identifier."""

        return cast(str, self.context["request_id"])

    @property
    def status(self) -> PaymentRequestStatus:
        """Return the current request status."""

        return cast(PaymentRequestStatus, self.context["status"])


class PolicyViolationError(PaymentDomainError):
    """Raised when a configured transfer policy is exceeded."""

    code = "policy_violation"

    def __init__(self, policy_name: str, limit: Decimal, attempted: Decimal) -> None:
        super().__init__(
            f"Policy {policy_name} limit exceeded",
            context={"policy_name": policy_name, "limit": limit, "attempted": attempted},
        )

    @property
    def policy_name(self) -> str:
        """Return the violated policy name."""

        return cast(str, self.context["policy_name"])

    @property
    def limit(self) -> Decimal:
        """Return the configured limit."""

        return cast(Decimal, self.context["limit"])

    @property
    def attempted(self) -> Decimal:
        """Return the attempted amount."""

        return cast(Decimal, self.context["attempted"])


class NegativeBalanceInvariantError(PaymentDomainError):
    """Raised when a wallet would hold a negative balance."""

    code = "negative_balance_invariant"

    def __init__(self, user_id: str, balance: Decimal) -> None:
        super().__init__(
            f"Negative balance invariant violated for user {user_id}",
            context={"user_id": user_id, "balance": balance},
        )

    @property
    def user_id(self) -> str:
        """Return the affected wallet owner."""

        return cast(str, self.context["user_id"])

    @property
    def balance(self) -> Decimal:
        """Return the invalid balance."""

        return cast(Decimal, self.context["balance"])


class StateInvariantError(PaymentDomainError):
    """Raised when aggregate state violates a required invariant."""

    code = "state_invariant"


class IdempotencyConflictError(PaymentDomainError):
    """Raised when one idempotency key identifies different requests."""

    code = "idempotency_conflict"

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            f"Idempotency key conflicts with an existing request: {idempotency_key}",
            context={"idempotency_key": idempotency_key},
        )

    @property
    def idempotency_key(self) -> str:
        """Return the conflicting idempotency key."""

        return cast(str, self.context["idempotency_key"])
